from typing import Any
from bot.core.i18n import t

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot.core.database import get_users_collection, get_words_collection
from bot.keyboards.inline import get_scheduler_notification_keyboard
from bot.models.user import User

logger = logging.getLogger(__name__)


def is_within_allowed_hours(user: User, now_utc: datetime) -> bool:
    """
    Check if the current time is within user's active/notification hours (outside quiet hours).
    Default: quiet from 21:00 to 10:00, so notifications allowed 10:00 <= hour < 21:00.
    """
    try:
        user_tz = ZoneInfo(user.timezone)
    except Exception:
        user_tz = timezone.utc

    local_time = now_utc.astimezone(user_tz)
    local_hour = local_time.hour

    start = user.quiet_hours_start
    end = user.quiet_hours_end

    # If start == end, notifications are allowed 24/7
    if start == end:
        return True

    # Standard overnight quiet hours: e.g. start=21, end=10
    if start > end:
        # Active hours are: end <= hour < start (e.g. 10 <= hour < 21)
        return end <= local_hour < start
    else:
        # Day quiet hours: e.g. start=13, end=15
        # Active hours are: hour < start or hour >= end
        return local_hour < start or local_hour >= end


async def cleanup_user_reminder(bot: Bot, user_id: int) -> None:
    """
    Delete any pending reminder notification message and clear its ID from DB.
    """
    users_col = get_users_collection()
    user_doc = await users_col.find_one({"tg_id": user_id})
    if user_doc and user_doc.get("last_reminder_msg_id"):
        msg_id = user_doc["last_reminder_msg_id"]
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            pass
        await users_col.update_one(
            {"tg_id": user_id},
            {"$unset": {"last_reminder_msg_id": ""}},
        )


async def check_due_words_task(bot: Bot, dp: Any = None) -> None:
    """
    Background job triggered by APScheduler.
    Finds active users with due words and sends notification if allowed by quiet hours.
    Repeats every 30 minutes, deleting the previous reminder message, until words are reviewed.
    """
    now_utc = datetime.now(timezone.utc)
    logger.debug("Running check_due_words_task at %s UTC", now_utc)

    users_col = get_users_collection()
    words_col = get_words_collection()

    users_cursor = users_col.find({"is_active": True})
    async for user_doc in users_cursor:
        user_tg_id = user_doc.get("tg_id")
        try:
            user = User.model_validate(user_doc)

            if not is_within_allowed_hours(user, now_utc):
                continue

            # Check FSM state for quiz in progress or abandoned
            if dp and hasattr(dp, "fsm") and hasattr(dp.fsm, "storage"):
                try:
                    from aiogram.fsm.storage.base import StorageKey
                    key = StorageKey(bot_id=bot.id, chat_id=user.tg_id, user_id=user.tg_id)
                    current_state = await dp.fsm.storage.get_state(key)
                    if current_state and "quiz" in current_state.lower():
                        data = await dp.fsm.storage.get_data(key)
                        action_str = data.get("last_quiz_action_at")
                        is_abandoned = False
                        if action_str:
                            try:
                                action_time = datetime.fromisoformat(action_str)
                                if action_time.tzinfo is None:
                                    action_time = action_time.replace(tzinfo=timezone.utc)
                                if now_utc - action_time >= timedelta(minutes=30):
                                    is_abandoned = True
                            except Exception:
                                is_abandoned = True
                        else:
                            # If no action timestamp in state, check last_notified_at or consider abandoned
                            if user.last_notified_at:
                                user_notif_time = user.last_notified_at
                                if user_notif_time.tzinfo is None:
                                    user_notif_time = user_notif_time.replace(tzinfo=timezone.utc)
                                if now_utc - user_notif_time >= timedelta(minutes=30):
                                    is_abandoned = True
                            else:
                                is_abandoned = True

                        if not is_abandoned:
                            # User is actively taking quiz, do not interrupt
                            continue

                        # Quiz session is abandoned (> 30 min of inactivity).
                        # Deactivate card: remove buttons and append notice.
                        quiz_msg_id = data.get("quiz_msg_id")
                        if quiz_msg_id:
                            notice_text = t(user.native_language, "⏱ Сессия завершена из-за неактивности.")
                            try:
                                await bot.edit_message_text(
                                    text=f"⏱ <b>{notice_text}</b>",
                                    chat_id=user.tg_id,
                                    message_id=quiz_msg_id,
                                    reply_markup=None,
                                    parse_mode="HTML",
                                )
                            except Exception:
                                try:
                                    await bot.edit_message_reply_markup(
                                        chat_id=user.tg_id,
                                        message_id=quiz_msg_id,
                                        reply_markup=None,
                                    )
                                except Exception:
                                    pass

                        # Clear temp messages if any
                        temp_ids = data.get("temp_msg_ids", [])
                        for temp_id in temp_ids:
                            try:
                                await bot.delete_message(chat_id=user.tg_id, message_id=temp_id)
                            except Exception:
                                pass

                        # Clear FSM state so fresh reminders can be sent and user can start anew
                        await dp.fsm.storage.set_state(key, None)
                        await dp.fsm.storage.set_data(key, {})
                        logger.info("Deactivated abandoned quiz session for user tg_id=%s", user.tg_id)
                except Exception as ex:
                    logger.debug("Could not check FSM state for user %s: %s", user.tg_id, ex)

            # Count words ready for review
            due_count = await words_col.count_documents({
                "user_id": user.tg_id,
                "is_archived": False,
                "is_pending": {"$ne": True},
                "next_review_at": {"$lte": now_utc},
                "target_language": user.target_language,
                "native_language": user.native_language,
            })

            # If user has no due words, remove any leftover reminder message
            if due_count == 0:
                if user.last_reminder_msg_id:
                    try:
                        await bot.delete_message(chat_id=user.tg_id, message_id=user.last_reminder_msg_id)
                    except Exception:
                        pass
                    await users_col.update_one(
                        {"tg_id": user.tg_id},
                        {"$unset": {"last_reminder_msg_id": ""}},
                    )
                continue

            # Rate limit: do not re-send if less than 30 minutes have elapsed
            if user.last_notified_at:
                user_notif_time = user.last_notified_at
                if user_notif_time.tzinfo is None:
                    user_notif_time = user_notif_time.replace(tzinfo=timezone.utc)
                elapsed = now_utc - user_notif_time
                if elapsed < timedelta(minutes=30):
                    continue

            # Delete the previous reminder message before sending a new one
            if user.last_reminder_msg_id:
                try:
                    await bot.delete_message(chat_id=user.tg_id, message_id=user.last_reminder_msg_id)
                except Exception:
                    pass

            text = (
                f"{t(user.native_language, 'Пора повторить')} <b>{due_count}</b> {t(user.native_language, 'слов! 🧠')}\n\n" +
                t(user.native_language, "Интервальное повторение активирует долговременную память. ") +
                t(user.native_language, "Пройди быстрый квиз прямо сейчас:")
            )
            msg = await bot.send_message(
                chat_id=user.tg_id,
                text=text,
                reply_markup=get_scheduler_notification_keyboard(user.native_language),
                parse_mode="HTML",
            )
            await users_col.update_one(
                {"tg_id": user.tg_id},
                {"$set": {
                    "last_notified_at": now_utc,
                    "last_reminder_msg_id": msg.message_id,
                }},
            )
            logger.info("Sent review notification to tg_id=%s for %s words (msg_id=%s)", user.tg_id, due_count, msg.message_id)

        except TelegramForbiddenError:
            logger.info("User tg_id=%s has blocked the bot. Marking as is_active=False", user_tg_id)
            if user_tg_id:
                await users_col.update_one(
                    {"tg_id": user_tg_id},
                    {"$set": {"is_active": False, "updated_at": now_utc}},
                )
        except Exception as ex:
            logger.exception("Error checking due words for user %s: %s", user_tg_id, ex)

