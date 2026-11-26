import io
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendRichMessage
from aiogram.types import (
    BufferedInputFile,
    InputMediaAudio,
    InputRichMessage,
    InputRichMessageMedia,
    Message,
    Chat,
    User as TgUser,
)

from bot.core.telegram_session import ResilientAiohttpSession, call_with_retry
from bot.models.user import User
from bot.models.word import Word

TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


def _net_err() -> TelegramNetworkError:
    return TelegramNetworkError(method=MagicMock(), message="Request timeout error")


def _rich_with_audio() -> InputRichMessage:
    media = InputRichMessageMedia(
        id="audio1",
        media=InputMediaAudio(media=BufferedInputFile(b"MP3" * 100, filename="a.mp3"), title="t"),
    )
    return InputRichMessage(html='x <audio src="tg://audio?id=audio1"></audio>', media=[media])


# ---------- ResilientAiohttpSession ----------

def test_session_forces_ipv4_by_default():
    session = ResilientAiohttpSession()
    assert session._connector_init["family"] == socket.AF_INET


def test_session_ipv4_can_be_disabled():
    session = ResilientAiohttpSession(force_ipv4=False)
    assert "family" not in session._connector_init


@pytest.mark.asyncio
async def test_buffered_file_is_sent_with_known_content_length():
    session = ResilientAiohttpSession()
    bot = Bot(token=TOKEN, session=session)
    method = SendRichMessage(chat_id=1, rich_message=_rich_with_audio())
    payload = session.build_form_data(bot, method)()
    # Known size => Content-Length instead of chunked transfer encoding
    assert payload.size is not None
    await session.close()


# ---------- call_with_retry ----------

@pytest.mark.asyncio
async def test_call_with_retry_succeeds_on_second_attempt():
    func = AsyncMock(side_effect=[_net_err(), "ok"])
    result = await call_with_retry(func, 1, foo="bar", delay=0)
    assert result == "ok"
    assert func.await_count == 2
    for call in func.await_args_list:
        assert call.kwargs["foo"] == "bar"
        assert call.kwargs["request_timeout"] == 15


@pytest.mark.asyncio
async def test_call_with_retry_raises_after_last_attempt():
    func = AsyncMock(side_effect=[_net_err(), _net_err()])
    with pytest.raises(TelegramNetworkError):
        await call_with_retry(func, delay=0)
    assert func.await_count == 2


@pytest.mark.asyncio
async def test_call_with_retry_does_not_retry_bad_request():
    func = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="Bad Request"))
    with pytest.raises(TelegramBadRequest):
        await call_with_retry(func, delay=0)
    assert func.await_count == 1


# ---------- quiz_fsm.update_main_quiz_message ----------

def _state(data: dict) -> AsyncMock:
    state = AsyncMock()
    state.get_data.return_value = data
    return state


@pytest.mark.asyncio
async def test_update_main_quiz_message_retries_media_send(monkeypatch):
    from bot.handlers import quiz_fsm
    monkeypatch.setattr(quiz_fsm, "MEDIA_RETRY_DELAY", 0)

    bot = MagicMock()
    sent = MagicMock(message_id=77)
    bot.send_rich_message = AsyncMock(side_effect=[_net_err(), sent])
    state = _state({})

    await quiz_fsm.update_main_quiz_message(bot, 1, state, rich_message=_rich_with_audio())

    assert bot.send_rich_message.await_count == 2
    assert bot.send_rich_message.await_args.kwargs["request_timeout"] == 15
    state.update_data.assert_awaited_with(quiz_msg_id=77)


@pytest.mark.asyncio
async def test_update_main_quiz_message_retries_media_edit(monkeypatch):
    from bot.handlers import quiz_fsm
    monkeypatch.setattr(quiz_fsm, "MEDIA_RETRY_DELAY", 0)

    bot = MagicMock()
    bot.edit_message_text = AsyncMock(side_effect=[_net_err(), True])
    bot.send_rich_message = AsyncMock()
    state = _state({"quiz_msg_id": 10})

    await quiz_fsm.update_main_quiz_message(bot, 1, state, rich_message=_rich_with_audio())

    assert bot.edit_message_text.await_count == 2
    bot.send_rich_message.assert_not_called()


# ---------- quiz_fsm: stale fallback guard ----------

def _word(**kw) -> Word:
    base = dict(
        id="507f1f77bcf86cd799439011", user_id=1, native_language="ru", target_language="en",
        canonical_word="upbringing", lemma="upbringing", pos="noun",
        transcription="x", translation="воспитание",
    )
    base.update(kw)
    return Word(**base)


def _msg() -> MagicMock:
    msg = MagicMock()
    msg.bot = MagicMock()
    msg.chat = MagicMock(id=1)
    return msg


@pytest.mark.asyncio
async def test_listening_fallback_skipped_when_word_changed():
    from bot.handlers import quiz_fsm
    user = User(tg_id=1, native_language="ru", target_language="en")
    word = _word()
    state = _state({"current_word_id": "another_word"})

    with patch.object(quiz_fsm.tts_service, "generate_audio", AsyncMock(return_value=io.BytesIO(b"mp3"))), \
         patch.object(quiz_fsm, "update_main_quiz_message", AsyncMock(side_effect=[_net_err(), None])) as upd:
        await quiz_fsm._deliver_quiz_question(_msg(), user, state, word, "listening", [])

    assert upd.await_count == 1  # no stale text fallback


@pytest.mark.asyncio
async def test_listening_fallback_sent_when_word_still_current():
    from bot.handlers import quiz_fsm
    user = User(tg_id=1, native_language="ru", target_language="en")
    word = _word()
    state = _state({"current_word_id": str(word.id)})

    with patch.object(quiz_fsm.tts_service, "generate_audio", AsyncMock(return_value=io.BytesIO(b"mp3"))), \
         patch.object(quiz_fsm, "update_main_quiz_message", AsyncMock(side_effect=[_net_err(), None])) as upd:
        await quiz_fsm._deliver_quiz_question(_msg(), user, state, word, "listening", [])

    assert upd.await_count == 2


# ---------- quiz_fsm.on_quiz_failure: last word keeps "Next" button ----------

@pytest.mark.asyncio
async def test_on_quiz_failure_last_word_shows_next_button_and_waits():
    from bot.handlers import quiz_fsm
    user = User(tg_id=1, native_language="ru", target_language="en")
    word = _word()
    state = _state({"queue": [str(word.id)], "completed_session": 0, "reviewed_words_list": []})
    words_col = MagicMock()
    words_col.update_one = AsyncMock()

    with patch.object(quiz_fsm, "get_words_collection", return_value=words_col), \
         patch.object(quiz_fsm.tts_service, "generate_audio", AsyncMock(return_value=io.BytesIO(b"mp3"))), \
         patch.object(quiz_fsm, "update_main_quiz_message", AsyncMock()) as upd, \
         patch.object(quiz_fsm, "present_next_word", AsyncMock()) as nxt:
        await quiz_fsm.on_quiz_failure(_msg(), user, word, state)

    nxt.assert_not_called()
    upd.assert_awaited_once()
    kwargs = upd.await_args.kwargs
    assert kwargs["rich_message"].media  # audio kept
    assert kwargs["reply_markup"] == quiz_fsm.get_quiz_next_keyboard("ru")


# ---------- word_input: degrade to card without audio ----------

@pytest.mark.asyncio
async def test_send_word_card_falls_back_to_card_without_audio(monkeypatch):
    from bot.handlers import word_input
    monkeypatch.setattr(word_input, "MEDIA_RETRY_DELAY", 0)

    bot = MagicMock()
    bot.send_rich_message = AsyncMock(side_effect=[_net_err(), _net_err(), MagicMock()])
    await word_input._send_word_card(
        bot, 1,
        html_with_audio='card <audio src="tg://audio?id=audio1"></audio>',
        html_without_audio="card",
        audio=io.BytesIO(b"mp3"),
        filename="w.mp3", title="t", performer="p",
        reply_markup=None,
    )

    assert bot.send_rich_message.await_count == 3
    last = bot.send_rich_message.await_args.kwargs["rich_message"]
    assert not last.media
    assert "<audio" not in last.html
