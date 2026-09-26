from bot.core.i18n import t

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from aiogram import Bot

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


async def check_due_words_task(bot: Bot) -> None:
    """
    Background job triggered by APScheduler.
    Finds active users with due words and sends notification if allowed by quiet hours.
    """
    now_utc = datetime.now(timezone.utc)
    logger.debug("Running check_due_words_task at %s UTC", now_utc)

    users_col = get_users_collection()
    words_col = get_words_collection()

    users_cursor = users_col.find({"is_active": True})
    async for user_doc in users_cursor:
        try:
            user = User.model_validate(user_doc)

            if not is_within_allowed_hours(user, now_utc):
                continue

            # Rate limit: do not spam more frequently than every 4 hours
            if user.last_notified_at:
                user_notif_time = user.last_notified_at
                if user_notif_time.tzinfo is None:
                    user_notif_time = user_notif_time.replace(tzinfo=timezone.utc)
                elapsed = now_utc - user_notif_time
                if elapsed < timedelta(hours=4):
                    continue

            # Count words ready for review
            due_count = await words_col.count_documents({
                "user_id": user.tg_id,
                "is_archived": False,
                "next_review_at": {"$lte": now_utc},
                "target_language": user.target_language,
                "native_language": user.native_language,
            })

            if due_count > 0:
                text = (
                    f"Пора повторить <b>{due_count}</b> слов! 🧠\n\n" +
                    t(user.native_language, "Интервальное повторение активирует долговременную память. ") +
                    t(user.native_language, "Пройди быстрый квиз прямо сейчас:")
                )
                await bot.send_message(
                    chat_id=user.tg_id,
                    text=text,
                    reply_markup=get_scheduler_notification_keyboard(),
                    parse_mode="HTML",
                )
                await users_col.update_one(
                    {"tg_id": user.tg_id},
                    {"$set": {"last_notified_at": now_utc}},
                )
                logger.info("Sent review notification to tg_id=%s for %s words", user.tg_id, due_count)

        except Exception as ex:
            logger.exception("Error checking due words for user: %s", ex)

