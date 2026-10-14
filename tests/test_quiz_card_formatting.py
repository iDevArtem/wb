import pytest
from bot.core.i18n import wrap_spoiler, get_pos_translation
from bot.handlers.quiz_fsm import format_quiz_pos
from bot.services.srs_service import SRSService


def test_wrap_spoiler():
    assert wrap_spoiler("капуста", hide=True) == "<tg-spoiler>капуста</tg-spoiler>"
    assert wrap_spoiler("капуста", hide=False) == "капуста"


def test_get_pos_translation():
    assert get_pos_translation("noun", "ru") == "существительное"
    assert get_pos_translation("noun", "uk") == "іменник"
    assert get_pos_translation("verb", "ru") == "глагол"
    assert get_pos_translation("verb", "uk") == "дієслово"
    assert get_pos_translation("phrasal verb", "ru") == "фразовый глагол"
    assert get_pos_translation("unknown_pos_xyz", "ru") is None
    assert get_pos_translation(None, "ru") is None


def test_format_quiz_pos_with_pos_native_hidden():
    result = format_quiz_pos(
        pos="noun",
        pos_native="существительное",
        native_lang="ru",
        target_lang="en",
        hide_translations=True,
    )
    assert "<i>Part of speech: noun</i>" in result
    assert "<tg-spoiler><i>Часть речи: существительное</i></tg-spoiler>" in result


def test_format_quiz_pos_with_pos_native_visible():
    result = format_quiz_pos(
        pos="noun",
        pos_native="существительное",
        native_lang="ru",
        target_lang="en",
        hide_translations=False,
    )
    assert "<i>Part of speech: noun</i>" in result
    assert "<i>Часть речи: существительное</i>" in result
    assert "<tg-spoiler>" not in result


def test_format_quiz_pos_fallback_mapping_uk():
    # If pos_native is None, it should fall back to standard translation
    result = format_quiz_pos(
        pos="noun",
        pos_native=None,
        native_lang="uk",
        target_lang="en",
        hide_translations=True,
    )
    assert "<i>Part of speech: noun</i>" in result
    assert "<tg-spoiler><i>Частина мови: іменник</i></tg-spoiler>" in result


def test_format_quiz_pos_german_target():
    result = format_quiz_pos(
        pos="Nomen",
        pos_native="существительное",
        native_lang="ru",
        target_lang="de",
        hide_translations=True,
    )
    assert "<i>Wortart: Nomen</i>" in result
    assert "<tg-spoiler><i>Часть речи: существительное</i></tg-spoiler>" in result


def test_format_quiz_pos_empty():
    assert format_quiz_pos(None, None, "ru") == ""
    assert format_quiz_pos("", None, "ru") == ""


def test_get_attempt_2_hint_modern_keys_with_spoiler():
    examples = [{"target": "I like cabbage.", "native": "Я люблю капусту."}]
    hint = SRSService.get_attempt_2_hint(
        canonical_word="cabbage",
        lemma="cabbage",
        examples=examples,
        lang="ru",
        hide_translations=True,
    )
    assert "I like <b>___</b>." in hint
    assert "<tg-spoiler>Я люблю капусту.</tg-spoiler>" in hint


def test_get_attempt_2_hint_modern_keys_without_spoiler():
    examples = [{"target": "I like cabbage.", "native": "Я люблю капусту."}]
    hint = SRSService.get_attempt_2_hint(
        canonical_word="cabbage",
        lemma="cabbage",
        examples=examples,
        lang="ru",
        hide_translations=False,
    )
    assert "I like <b>___</b>." in hint
    assert "<i>(Я люблю капусту.)</i>" in hint
    assert "<tg-spoiler>" not in hint


def test_get_attempt_2_hint_legacy_keys_with_spoiler():
    examples = [{"en": "She grows cabbage in her garden.", "ru": "Она выращивает капусту в саду."}]
    hint = SRSService.get_attempt_2_hint(
        canonical_word="cabbage",
        lemma="cabbage",
        examples=examples,
        lang="ru",
        hide_translations=True,
    )
    assert "<b>___</b>" in hint
    assert "<tg-spoiler>Она выращивает капусту в саду.</tg-spoiler>" in hint


def test_get_listening_attempt_1_hint():
    hint = SRSService.get_attempt_1_hint("окно", "ru")
    assert "<code>о _ _ о</code>" in hint
    assert "4 букв" in hint


def test_get_listening_attempt_2_hint():
    examples = [{"target": "Open the window.", "native": "Открой окно."}]
    hint = SRSService.get_listening_attempt_2_hint(
        canonical_word="window",
        translation="окно",
        examples=examples,
        lang="ru",
        hide_translations=True,
    )
    assert "Open the <b>window</b>." in hint
    assert "<tg-spoiler>Открой <b>___</b>.</tg-spoiler>" in hint


@pytest.mark.asyncio
async def test_spelling_prompt_spacing_and_pos():
    from unittest.mock import AsyncMock, MagicMock, patch
    from aiogram.types import Message, Chat
    from bot.handlers.quiz_fsm import _deliver_quiz_question
    from bot.models.word import Word
    from bot.models.user import User

    mock_bot = MagicMock()
    mock_message = MagicMock(spec=Message)
    mock_message.chat = MagicMock(spec=Chat, id=12345)
    mock_message.bot = mock_bot
    mock_state = MagicMock()

    user = User(
        tg_id=12345,
        target_language="en",
        native_language="ru",
        hide_translations=True,
    )
    word = Word(
        user_id=12345,
        canonical_word="magazine",
        lemma="magazine",
        pos="noun",
        pos_native="существительное",
        transcription="ˌmæɡ.əˈziːn",
        translation="журнал",
        target_language="en",
        native_language="ru",
    )

    with patch("bot.handlers.quiz_fsm.update_main_quiz_message", new_callable=AsyncMock) as mock_update:
        await _deliver_quiz_question(mock_message, user, mock_state, word, mode="spelling", options=[])
        mock_update.assert_awaited_once()
        text = mock_update.call_args.args[3]
        
        # Verify bilingual POS
        assert "<i>Part of speech: noun</i>" in text
        assert "<tg-spoiler><i>Часть речи: существительное</i></tg-spoiler>" in text
        
        # Verify empty line (double newline) before prompt instruction
        expected_pos_block = (
            "<i>Part of speech: noun</i>\n"
            "<tg-spoiler><i>Часть речи: существительное</i></tg-spoiler>\n\n"
            "Напиши слово на изучаемом языке в ответном сообщении (3 попытки):"
        )
        assert expected_pos_block in text


@pytest.mark.asyncio
async def test_dictation_fallback_on_tts_failure():
    from unittest.mock import AsyncMock, MagicMock, patch
    from aiogram.types import Message, Chat
    from bot.handlers.quiz_fsm import _deliver_quiz_question
    from bot.models.word import Word
    from bot.models.user import User

    mock_bot = MagicMock()
    mock_message = MagicMock(spec=Message)
    mock_message.chat = MagicMock(spec=Chat, id=12345)
    mock_message.bot = mock_bot
    mock_state = MagicMock()

    user = User(tg_id=12345, target_language="en", native_language="ru")
    word = Word(
        user_id=12345,
        canonical_word="window",
        lemma="window",
        pos="noun",
        pos_native="существительное",
        transcription="ˈwɪn.doʊ",
        translation="окно",
        target_language="en",
        native_language="ru",
    )

    with patch("bot.handlers.quiz_fsm.tts_service.generate_audio", side_effect=RuntimeError("TTS down")), \
         patch("bot.handlers.quiz_fsm.update_main_quiz_message", new_callable=AsyncMock) as mock_update:
        await _deliver_quiz_question(mock_message, user, mock_state, word, mode="dictation", options=[])
        mock_update.assert_awaited_once()
        text = mock_update.call_args.args[3]
        
        # Fallback card must not be raw '✍️ Напиши слово окно:'
        assert "Режим: Диктант на слух (Dictation)" in text
        assert "Озвучка временно недоступна." in text
        assert "👉 <b>окно</b>" in text
        assert "Напиши слово на изучаемом языке" in text


@pytest.mark.asyncio
async def test_listening_fallback_on_tts_failure():
    from unittest.mock import AsyncMock, MagicMock, patch
    from aiogram.types import Message, Chat
    from bot.handlers.quiz_fsm import _deliver_quiz_question
    from bot.models.word import Word
    from bot.models.user import User

    mock_bot = MagicMock()
    mock_message = MagicMock(spec=Message)
    mock_message.chat = MagicMock(spec=Chat, id=12345)
    mock_message.bot = mock_bot
    mock_state = MagicMock()

    user = User(tg_id=12345, target_language="en", native_language="ru")
    word = Word(
        user_id=12345,
        canonical_word="window",
        lemma="window",
        pos="noun",
        pos_native="существительное",
        transcription="ˈwɪn.doʊ",
        translation="окно",
        target_language="en",
        native_language="ru",
    )

    with patch("bot.handlers.quiz_fsm.tts_service.generate_audio", side_effect=RuntimeError("TTS down")), \
         patch("bot.handlers.quiz_fsm.update_main_quiz_message", new_callable=AsyncMock) as mock_update:
        await _deliver_quiz_question(mock_message, user, mock_state, word, mode="listening", options=[])
        mock_update.assert_awaited_once()
        text = mock_update.call_args.args[3]
        
        assert "Режим: Аудирование (Listening)" in text
        assert "Озвучка временно недоступна." in text
        assert "👉 <b>window</b> [ˈwɪn.doʊ]" in text
        assert "Введи перевод:" in text


