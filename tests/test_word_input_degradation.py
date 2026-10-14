from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiogram.types import Message, Chat, User as TgUser
from bot.models.user import User
from bot.services.gemini_service import WordAnalysis


@pytest.mark.asyncio
async def test_handle_text_input_graceful_degradation_on_tts_failure():
    """
    When TTS completely fails, handle_text_input should NOT crash:
    it should still insert the word into MongoDB and send the rich card without audio.
    """
    from bot.handlers.word_input import handle_text_input

    # Prepare mock message
    mock_bot = MagicMock()
    mock_bot.send_rich_message = AsyncMock()
    mock_bot.send_chat_action = AsyncMock()
    mock_message = MagicMock(spec=Message)
    mock_message.text = "ephemeral"
    mock_message.chat = MagicMock(spec=Chat, id=12345)
    mock_message.from_user = MagicMock(spec=TgUser, id=12345)
    mock_message.bot = mock_bot
    mock_message.delete = AsyncMock()
    mock_message.answer = AsyncMock()

    user = User(
        tg_id=12345,
        target_language="en",
        native_language="ru",
        hide_translations=True,
    )

    wa = WordAnalysis(
        canonical_word="ephemeral",
        lemma="ephemeral",
        pos="adjective",
        transcription="ɪˈfem.ər.əl",
        translation="эфемерный",
        level="C1",
        pos_native="прилагательное",
        definition="lasting for a very short time",
        definition_native="длящийся очень недолго",
        grammar_notes=[],
        grammar_notes_native=[],
        forms=[],
        examples=[],
    )

    with patch("bot.handlers.word_input.gemini_service.analyze_text", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = wa
        
        with patch("bot.handlers.word_input.check_existing_word", new_callable=AsyncMock) as mock_check_exist:
            mock_check_exist.return_value = None
            
            with patch("bot.handlers.word_input.tts_service.generate_audio", new_callable=AsyncMock) as mock_tts:
                mock_tts.side_effect = RuntimeError("All TTS engines failed (403 Forbidden)")
                
                with patch("bot.handlers.word_input.get_words_collection") as mock_get_words:
                    mock_col = MagicMock()
                    mock_insert_res = MagicMock()
                    mock_insert_res.inserted_id = "mock_word_id_123"
                    mock_col.insert_one = AsyncMock(return_value=mock_insert_res)
                    mock_get_words.return_value = mock_col

                    mock_state = MagicMock()
                    mock_state.get_state = AsyncMock(return_value=None)

                    # Call handler
                    await handle_text_input(mock_message, mock_bot, user, mock_state)

                    # Assert word was inserted to collection
                    assert mock_col.insert_one.called
                    # Assert send_rich_message was called
                    assert mock_bot.send_rich_message.called
                    call_kwargs = mock_bot.send_rich_message.call_args.kwargs
                    rich_message = call_kwargs.get("rich_message")
                    assert rich_message is not None
                    # Media should be empty or not present since TTS failed
                    assert not getattr(rich_message, "media", None)
                    # HTML card should not contain <audio ...> tag
                    assert "<audio" not in rich_message.html


@pytest.mark.asyncio
async def test_handle_text_input_with_successful_tts():
    """
    When TTS succeeds, handle_text_input should attach the audio media to the rich card.
    """
    import io
    from bot.handlers.word_input import handle_text_input

    mock_bot = MagicMock()
    mock_bot.send_rich_message = AsyncMock()
    mock_bot.send_chat_action = AsyncMock()
    mock_message = MagicMock(spec=Message)
    mock_message.text = "serendipity"
    mock_message.chat = MagicMock(spec=Chat, id=12345)
    mock_message.from_user = MagicMock(spec=TgUser, id=12345)
    mock_message.bot = mock_bot
    mock_message.delete = AsyncMock()

    user = User(
        tg_id=12345,
        target_language="en",
        native_language="ru",
        hide_translations=True,
    )

    wa = WordAnalysis(
        canonical_word="serendipity",
        lemma="serendipity",
        pos="noun",
        transcription="ˌser.ənˈdɪp.ə.ti",
        translation="счастливая случайность",
        level="C2",
        pos_native="существительное",
        definition="the occurrence and development of events by chance in a happy or beneficial way",
        definition_native="удачное стечение обстоятельств",
        grammar_notes=["[U]"],
        grammar_notes_native=["[неисчисляемое]"],
        forms=[],
        examples=[],
    )

    with patch("bot.handlers.word_input.gemini_service.analyze_text", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = wa

        with patch("bot.handlers.word_input.check_existing_word", new_callable=AsyncMock) as mock_check_exist:
            mock_check_exist.return_value = None

            with patch("bot.handlers.word_input.tts_service.generate_audio", new_callable=AsyncMock) as mock_tts:
                mock_tts.return_value = io.BytesIO(b"fake-audio-bytes-mp3")

                with patch("bot.handlers.word_input.get_words_collection") as mock_get_words:
                    mock_col = MagicMock()
                    mock_insert_res = MagicMock()
                    mock_insert_res.inserted_id = "mock_word_id_456"
                    mock_col.insert_one = AsyncMock(return_value=mock_insert_res)
                    mock_get_words.return_value = mock_col

                    mock_state = MagicMock()
                    mock_state.get_state = AsyncMock(return_value=None)

                    await handle_text_input(mock_message, mock_bot, user, mock_state)

                    assert mock_col.insert_one.called
                    assert mock_bot.send_rich_message.called
                    call_kwargs = mock_bot.send_rich_message.call_args.kwargs
                    rich_message = call_kwargs.get("rich_message")
                    assert rich_message is not None
                    # Media must be present with audio
                    assert getattr(rich_message, "media", None) is not None
                    assert len(rich_message.media) == 1
                    # HTML card should contain tg://audio?id=audio1
                    assert 'tg://audio?id=audio1' in rich_message.html

