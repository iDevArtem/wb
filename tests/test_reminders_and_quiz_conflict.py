from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.models.user import User
from bot.scheduler.tasks import check_due_words_task, cleanup_user_reminder
from bot.handlers.quiz_fsm import (
    QuizState,
    is_quiz_in_progress,
    _is_valid_quiz_callback,
)


@pytest.mark.asyncio
async def test_user_model_last_reminder_msg_id():
    user = User(
        tg_id=123,
        username="tester",
        last_notified_at=datetime.now(timezone.utc),
        last_reminder_msg_id=999,
    )
    assert user.last_reminder_msg_id == 999
    doc = user.to_mongo()
    assert doc["last_reminder_msg_id"] == 999

    user_restored = User.model_validate(doc)
    assert user_restored.last_reminder_msg_id == 999


@pytest.mark.asyncio
async def test_cleanup_user_reminder():
    bot = AsyncMock()
    user_col = AsyncMock()
    user_col.find_one.return_value = {"tg_id": 123, "last_reminder_msg_id": 456}

    with patch("bot.scheduler.tasks.get_users_collection", return_value=user_col):
        await cleanup_user_reminder(bot, 123)

        bot.delete_message.assert_awaited_once_with(chat_id=123, message_id=456)
        user_col.update_one.assert_awaited_once_with(
            {"tg_id": 123},
            {"$unset": {"last_reminder_msg_id": ""}},
        )


@pytest.mark.asyncio
async def test_check_due_words_task_replaces_old_reminder_after_30_minutes():
    bot = AsyncMock()
    sent_msg = MagicMock(message_id=789)
    bot.send_message = AsyncMock(return_value=sent_msg)

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(minutes=35)

    user_doc = {
        "tg_id": 123,
        "is_active": True,
        "timezone": "UTC",
        "quiet_hours_start": 0,
        "quiet_hours_end": 0,  # 24/7 allowed
        "native_language": "ru",
        "target_language": "en",
        "last_notified_at": old_time,
        "last_reminder_msg_id": 456,
    }

    class AsyncCursor:
        def __init__(self, items):
            self.items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    users_col = MagicMock()
    users_col.find.return_value = AsyncCursor([user_doc])
    users_col.update_one = AsyncMock()
    words_col = AsyncMock()
    words_col.count_documents.return_value = 5

    with patch("bot.scheduler.tasks.get_users_collection", return_value=users_col), \
         patch("bot.scheduler.tasks.get_words_collection", return_value=words_col):

        await check_due_words_task(bot)

        # Old message deleted
        bot.delete_message.assert_awaited_once_with(chat_id=123, message_id=456)
        # New message sent
        bot.send_message.assert_awaited_once()
        # DB updated with new message_id
        users_col.update_one.assert_awaited_once()
        update_args = users_col.update_one.call_args[0]
        assert update_args[0] == {"tg_id": 123}
        assert update_args[1]["$set"]["last_reminder_msg_id"] == 789


@pytest.mark.asyncio
async def test_check_due_words_task_skips_when_less_than_30_minutes():
    bot = AsyncMock()
    now = datetime.now(timezone.utc)
    recent_time = now - timedelta(minutes=15)

    user_doc = {
        "tg_id": 123,
        "is_active": True,
        "timezone": "UTC",
        "quiet_hours_start": 0,
        "quiet_hours_end": 0,
        "native_language": "ru",
        "target_language": "en",
        "last_notified_at": recent_time,
        "last_reminder_msg_id": 456,
    }

    class AsyncCursor:
        def __init__(self, items):
            self.items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    users_col = MagicMock()
    users_col.find.return_value = AsyncCursor([user_doc])
    users_col.update_one = AsyncMock()
    words_col = AsyncMock()
    words_col.count_documents.return_value = 5

    with patch("bot.scheduler.tasks.get_users_collection", return_value=users_col), \
         patch("bot.scheduler.tasks.get_words_collection", return_value=words_col):

        await check_due_words_task(bot)

        bot.delete_message.assert_not_called()
        bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_check_due_words_task_cleans_up_when_zero_due_words():
    bot = AsyncMock()
    user_doc = {
        "tg_id": 123,
        "is_active": True,
        "timezone": "UTC",
        "quiet_hours_start": 0,
        "quiet_hours_end": 0,
        "native_language": "ru",
        "target_language": "en",
        "last_reminder_msg_id": 456,
    }

    class AsyncCursor:
        def __init__(self, items):
            self.items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    users_col = MagicMock()
    users_col.find.return_value = AsyncCursor([user_doc])
    users_col.update_one = AsyncMock()
    words_col = AsyncMock()
    words_col.count_documents.return_value = 0

    with patch("bot.scheduler.tasks.get_users_collection", return_value=users_col), \
         patch("bot.scheduler.tasks.get_words_collection", return_value=words_col):

        await check_due_words_task(bot)

        bot.delete_message.assert_awaited_once_with(chat_id=123, message_id=456)
        users_col.update_one.assert_awaited_once_with(
            {"tg_id": 123},
            {"$unset": {"last_reminder_msg_id": ""}},
        )


@pytest.mark.asyncio
async def test_is_quiz_in_progress():
    state = AsyncMock()
    state.get_state.return_value = QuizState.answering.state
    state.get_data.return_value = {"queue": ["word1", "word2"]}

    assert await is_quiz_in_progress(state) is True

    # Empty queue means quiz finished
    state.get_data.return_value = {"queue": []}
    assert await is_quiz_in_progress(state) is False

    # Different state means not in quiz
    state.get_state.return_value = None
    assert await is_quiz_in_progress(state) is False


@pytest.mark.asyncio
async def test_is_valid_quiz_callback_rejects_outdated_message():
    user = User(tg_id=123, native_language="ru")
    state = AsyncMock()
    state.get_state.return_value = QuizState.answering.state
    state.get_data.return_value = {"quiz_msg_id": 555}

    callback = AsyncMock()
    callback.message = AsyncMock(message_id=444)  # Mismatched message ID!

    valid = await _is_valid_quiz_callback(callback, user, state)
    assert valid is False
    callback.answer.assert_awaited_once()
    assert "недействителен" in callback.answer.call_args[0][0]
    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_is_valid_quiz_callback_accepts_current_message():
    user = User(tg_id=123, native_language="ru")
    state = AsyncMock()
    state.get_state.return_value = QuizState.answering.state
    state.get_data.return_value = {"quiz_msg_id": 555}

    callback = AsyncMock()
    callback.message = AsyncMock(message_id=555)  # Matches current active quiz message

    valid = await _is_valid_quiz_callback(callback, user, state)
    assert valid is True
    callback.message.edit_reply_markup.assert_not_called()


@pytest.mark.asyncio
async def test_check_due_words_task_skips_when_quiz_action_is_recent():
    bot = AsyncMock()
    bot.id = 99999
    now = datetime.now(timezone.utc)
    recent_action = (now - timedelta(minutes=5)).isoformat()

    dp = MagicMock()
    dp.fsm.storage.get_state = AsyncMock(return_value=QuizState.answering.state)
    dp.fsm.storage.get_data = AsyncMock(return_value={"last_quiz_action_at": recent_action, "quiz_msg_id": 888})

    user_doc = {
        "tg_id": 123,
        "is_active": True,
        "timezone": "UTC",
        "quiet_hours_start": 0,
        "quiet_hours_end": 0,
        "native_language": "ru",
        "target_language": "en",
        "last_notified_at": now - timedelta(hours=2),
    }

    class AsyncCursor:
        def __init__(self, items):
            self.items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    users_col = MagicMock()
    users_col.find.return_value = AsyncCursor([user_doc])
    words_col = AsyncMock()
    words_col.count_documents.return_value = 5

    with patch("bot.scheduler.tasks.get_users_collection", return_value=users_col), \
         patch("bot.scheduler.tasks.get_words_collection", return_value=words_col):

        await check_due_words_task(bot, dp=dp)

        # Active quiz within 30 min -> no reminder sent, state not cleared
        bot.send_message.assert_not_called()
        dp.fsm.storage.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_check_due_words_task_deactivates_abandoned_quiz_and_sends_reminder():
    bot = AsyncMock()
    bot.id = 99999
    sent_msg = MagicMock(message_id=999)
    bot.send_message = AsyncMock(return_value=sent_msg)

    now = datetime.now(timezone.utc)
    old_action = (now - timedelta(minutes=35)).isoformat()

    dp = MagicMock()
    dp.fsm.storage.get_state = AsyncMock(return_value=QuizState.answering.state)
    dp.fsm.storage.get_data = AsyncMock(return_value={
        "last_quiz_action_at": old_action,
        "quiz_msg_id": 888,
        "temp_msg_ids": [],
    })
    dp.fsm.storage.set_state = AsyncMock()
    dp.fsm.storage.set_data = AsyncMock()

    user_doc = {
        "tg_id": 123,
        "is_active": True,
        "timezone": "UTC",
        "quiet_hours_start": 0,
        "quiet_hours_end": 0,
        "native_language": "ru",
        "target_language": "en",
        "last_notified_at": now - timedelta(hours=2),
    }

    class AsyncCursor:
        def __init__(self, items):
            self.items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    users_col = MagicMock()
    users_col.find.return_value = AsyncCursor([user_doc])
    users_col.update_one = AsyncMock()
    words_col = AsyncMock()
    words_col.count_documents.return_value = 4

    with patch("bot.scheduler.tasks.get_users_collection", return_value=users_col), \
         patch("bot.scheduler.tasks.get_words_collection", return_value=words_col):

        await check_due_words_task(bot, dp=dp)

        # Deactivates old quiz card (edits message text or removes markup)
        bot.edit_message_text.assert_awaited_once()
        assert bot.edit_message_text.call_args[1]["message_id"] == 888

        # Clears FSM state
        dp.fsm.storage.set_state.assert_awaited_once()
        dp.fsm.storage.set_data.assert_awaited_once()

        # Sends fresh notification for due words
        bot.send_message.assert_awaited_once()
        assert "4" in bot.send_message.call_args[1]["text"]

