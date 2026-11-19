import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest
from bson import ObjectId

from bot.handlers.quiz_fsm import (
    QuizState,
    cb_quiz_skip,
    cb_quiz_skip_cancel,
    cb_quiz_skip_confirm,
)
from bot.keyboards.inline import (
    get_quiz_control_keyboard,
    get_quiz_skip_confirm_keyboard,
)
from bot.models.user import User
from bot.models.word import Word


def _make_state(state_data: dict, fsm_state: str | None = QuizState.answering.state) -> AsyncMock:
    state = AsyncMock()
    state.get_state.return_value = fsm_state
    state.get_data.return_value = state_data
    return state


def _make_callback(data: str, message_id: int = 100) -> AsyncMock:
    callback = AsyncMock()
    callback.data = data
    callback.message = AsyncMock(message_id=message_id)
    callback.answer = AsyncMock()
    return callback


def test_get_quiz_skip_confirm_keyboard_layout_and_order():
    kb_ru = get_quiz_skip_confirm_keyboard(lang="ru", word_id="abc123")
    assert len(kb_ru.inline_keyboard) == 1
    row_ru = kb_ru.inline_keyboard[0]
    assert len(row_ru) == 2
    assert row_ru[0].text == "↩️ Назад"
    assert row_ru[0].callback_data == "quiz_skip_cancel:abc123"
    assert row_ru[1].text == "✅ Подтвердить"
    assert row_ru[1].callback_data == "quiz_skip_confirm:abc123"

    kb_en = get_quiz_skip_confirm_keyboard(lang="en", word_id="abc123")
    row_en = kb_en.inline_keyboard[0]
    assert row_en[0].text == "↩️ Back"
    assert row_en[0].callback_data == "quiz_skip_cancel:abc123"
    assert row_en[1].text == "✅ Confirm"
    assert row_en[1].callback_data == "quiz_skip_confirm:abc123"


@pytest.mark.asyncio
async def test_cb_quiz_skip_swaps_keyboard_without_skipping():
    user = User(tg_id=123, native_language="ru")
    word_id = "507f1f77bcf86cd799439011"
    state = _make_state({"quiz_msg_id": 100, "current_word_id": word_id})
    callback = _make_callback("quiz_skip", message_id=100)

    with patch("bot.handlers.quiz_fsm.on_quiz_failure", new_callable=AsyncMock) as mock_fail, \
         patch("bot.handlers.quiz_fsm.get_words_collection") as mock_words_col:
        await cb_quiz_skip(callback, user, state)

    callback.message.edit_reply_markup.assert_awaited_once_with(
        reply_markup=get_quiz_skip_confirm_keyboard("ru", word_id)
    )
    state.update_data.assert_awaited_once()
    assert "last_quiz_action_at" in state.update_data.call_args.kwargs
    callback.answer.assert_awaited_once_with()
    mock_fail.assert_not_called()
    mock_words_col.assert_not_called()


@pytest.mark.asyncio
async def test_cb_quiz_skip_ignores_empty_current_word_id():
    user = User(tg_id=123, native_language="ru")
    state = _make_state({"quiz_msg_id": 100, "current_word_id": ""})
    callback = _make_callback("quiz_skip", message_id=100)

    with patch("bot.handlers.quiz_fsm.on_quiz_failure", new_callable=AsyncMock) as mock_fail:
        await cb_quiz_skip(callback, user, state)

    callback.answer.assert_awaited_once_with()
    callback.message.edit_reply_markup.assert_not_called()
    mock_fail.assert_not_called()


@pytest.mark.asyncio
async def test_cb_quiz_skip_cancel_restores_control_keyboard():
    user = User(tg_id=123, native_language="ru")
    state = _make_state({"quiz_msg_id": 100, "current_word_id": "word123"})
    callback = _make_callback("quiz_skip_cancel:word123", message_id=100)

    with patch("bot.handlers.quiz_fsm.on_quiz_failure", new_callable=AsyncMock) as mock_fail:
        await cb_quiz_skip_cancel(callback, user, state)

    callback.message.edit_reply_markup.assert_awaited_once_with(
        reply_markup=get_quiz_control_keyboard("ru")
    )
    state.update_data.assert_awaited_once()
    assert "last_quiz_action_at" in state.update_data.call_args.kwargs
    callback.answer.assert_awaited_once_with()
    mock_fail.assert_not_called()


@pytest.mark.asyncio
async def test_cb_quiz_skip_cancel_ignores_mismatched_word_id():
    user = User(tg_id=123, native_language="ru")
    state = _make_state({"quiz_msg_id": 100, "current_word_id": "word_new"})
    callback = _make_callback("quiz_skip_cancel:word_old", message_id=100)

    await cb_quiz_skip_cancel(callback, user, state)

    callback.message.edit_reply_markup.assert_not_called()
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cb_quiz_skip_confirm_calls_on_quiz_failure():
    user = User(tg_id=123, native_language="ru", target_language="en")
    word_id = "507f1f77bcf86cd799439011"
    word_doc = {
        "_id": ObjectId(word_id),
        "user_id": 123,
        "native_language": "ru",
        "target_language": "en",
        "canonical_word": "window",
        "lemma": "window",
        "pos": "noun",
        "transcription": "ˈwɪn.doʊ",
        "translation": "окно",
    }
    words_col = MagicMock()
    words_col.find_one = AsyncMock(return_value=word_doc)

    state = _make_state({"quiz_msg_id": 100, "current_word_id": word_id})
    callback = _make_callback(f"quiz_skip_confirm:{word_id}", message_id=100)

    with patch("bot.handlers.quiz_fsm.get_words_collection", return_value=words_col), \
         patch("bot.handlers.quiz_fsm.on_quiz_failure", new_callable=AsyncMock) as mock_fail:
        await cb_quiz_skip_confirm(callback, user, state)

    callback.answer.assert_awaited_once_with("Слово пропущено")
    mock_fail.assert_awaited_once()
    call_args = mock_fail.call_args.args
    assert call_args[0] is callback.message
    assert call_args[1] is user
    assert isinstance(call_args[2], Word)
    assert str(call_args[2].id) == word_id
    assert call_args[3] is state


@pytest.mark.asyncio
@pytest.mark.parametrize("current_word_id", ["", "other_id"])
async def test_cb_quiz_skip_confirm_ignores_stale_or_empty_word_id(current_word_id: str):
    user = User(tg_id=123, native_language="ru")
    state = _make_state({"quiz_msg_id": 100, "current_word_id": current_word_id})
    callback = _make_callback("quiz_skip_confirm:word123", message_id=100)

    with patch("bot.handlers.quiz_fsm.get_words_collection") as mock_words_col, \
         patch("bot.handlers.quiz_fsm.on_quiz_failure", new_callable=AsyncMock) as mock_fail:
        await cb_quiz_skip_confirm(callback, user, state)

    mock_words_col.assert_not_called()
    mock_fail.assert_not_called()
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "cb_data"),
    [
        (cb_quiz_skip, "quiz_skip"),
        (cb_quiz_skip_cancel, "quiz_skip_cancel:word123"),
        (cb_quiz_skip_confirm, "quiz_skip_confirm:word123"),
    ],
)
async def test_cb_quiz_skip_handlers_reject_invalid_session(handler, cb_data: str):
    user = User(tg_id=123, native_language="ru")
    state = _make_state({"quiz_msg_id": 555, "current_word_id": "word123"})
    callback = _make_callback(cb_data, message_id=444)

    with patch("bot.handlers.quiz_fsm.on_quiz_failure", new_callable=AsyncMock) as mock_fail:
        await handler(callback, user, state)

    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    callback.answer.assert_awaited_once()
    assert "недействителен" in callback.answer.call_args.args[0]
    assert callback.answer.call_args.kwargs.get("show_alert") is True
    mock_fail.assert_not_called()


@pytest.mark.asyncio
async def test_cb_quiz_skip_and_cancel_ignore_message_not_modified():
    user = User(tg_id=123, native_language="ru")
    err = TelegramBadRequest(method=MagicMock(), message="Bad Request: message is not modified")

    state_skip = _make_state({"quiz_msg_id": 100, "current_word_id": "word123"})
    cb_skip = _make_callback("quiz_skip", message_id=100)
    cb_skip.message.edit_reply_markup = AsyncMock(side_effect=err)
    await cb_quiz_skip(cb_skip, user, state_skip)
    cb_skip.answer.assert_awaited_once_with()

    state_cancel = _make_state({"quiz_msg_id": 100, "current_word_id": "word123"})
    cb_cancel = _make_callback("quiz_skip_cancel:word123", message_id=100)
    cb_cancel.message.edit_reply_markup = AsyncMock(side_effect=err)
    await cb_quiz_skip_cancel(cb_cancel, user, state_cancel)
    cb_cancel.answer.assert_awaited_once_with()


def test_skip_confirm_locales_present_in_all_languages():
    locales_dir = Path("bot/locales")
    expected_langs = {"de", "en", "es", "fr", "it", "pl", "ru", "uk"}
    found_langs = {p.stem for p in locales_dir.glob("*.json")}
    assert expected_langs.issubset(found_langs)

    for lang in sorted(expected_langs):
        data = json.loads((locales_dir / f"{lang}.json").read_text(encoding="utf-8"))
        for key in ("↩️ Назад", "✅ Подтвердить"):
            assert key in data, f"Missing '{key}' in {lang}.json"
            assert isinstance(data[key], str) and data[key].strip() != ""
