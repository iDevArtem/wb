import io
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from bot.services.tts_service import TTSService


@pytest.mark.asyncio
async def test_edge_tts_fallback_to_gemini_on_failure():
    """
    When tts_engine is 'edge' and edge_tts fails (e.g. 403 Forbidden),
    TTSService should seamlessly fall back to gemini_service.synthesize_speech_audio.
    """
    service = TTSService(voice="en-US-AriaNeural")
    
    with patch("bot.services.tts_service.settings") as mock_settings:
        mock_settings.tts_engine = "edge"
        mock_settings.gemini_tts_voice = "Kore"
        mock_settings.gemini_tts_model = "gemini-2.5-flash-preview-tts"
        
        # Mock edge_tts to fail with 403
        with patch("bot.services.tts_service.edge_tts.Communicate") as mock_communicate:
            mock_comm_instance = MagicMock()
            
            async def failing_stream():
                raise RuntimeError("403 Forbidden: Invalid response status")
                yield  # makes it an async generator
                
            mock_comm_instance.stream = failing_stream
            mock_communicate.return_value = mock_comm_instance
            
            # Mock gemini_service to succeed
            with patch("bot.services.gemini_service.gemini_service.synthesize_speech_audio", new_callable=AsyncMock) as mock_gemini:
                mock_gemini.return_value = b"fake-gemini-audio-bytes"
                
                result = await service.generate_audio("hello", target_lang="en")
                
                assert isinstance(result, io.BytesIO)
                assert result.getvalue() == b"fake-gemini-audio-bytes"
                mock_gemini.assert_awaited_once_with(
                    text="hello",
                    voice_name="Kore",
                    model="gemini-2.5-flash-preview-tts",
                )


@pytest.mark.asyncio
async def test_edge_tts_success_does_not_call_gemini():
    """
    When edge_tts succeeds, gemini_service should not be called.
    """
    service = TTSService(voice="en-US-AriaNeural")
    
    with patch("bot.services.tts_service.settings") as mock_settings:
        mock_settings.tts_engine = "edge"
        
        with patch("bot.services.tts_service.edge_tts.Communicate") as mock_communicate:
            mock_comm_instance = MagicMock()
            
            async def successful_stream():
                yield {"type": "audio", "data": b"fake-edge-audio"}
                
            mock_comm_instance.stream = successful_stream
            mock_communicate.return_value = mock_comm_instance
            
            with patch("bot.services.gemini_service.gemini_service.synthesize_speech_audio", new_callable=AsyncMock) as mock_gemini:
                result = await service.generate_audio("world", target_lang="en")
                
                assert isinstance(result, io.BytesIO)
                assert result.getvalue() == b"fake-edge-audio"
                mock_gemini.assert_not_called()


@pytest.mark.asyncio
async def test_both_engines_fail_raises_runtime_error():
    """
    When both edge-tts and gemini fail, generate_audio should raise RuntimeError.
    """
    service = TTSService(voice="en-US-AriaNeural")
    
    with patch("bot.services.tts_service.settings") as mock_settings:
        mock_settings.tts_engine = "edge"
        mock_settings.gemini_tts_voice = "Kore"
        mock_settings.gemini_tts_model = "gemini-2.5-flash-preview-tts"
        
        with patch("bot.services.tts_service.edge_tts.Communicate") as mock_communicate:
            mock_comm_instance = MagicMock()
            
            async def failing_stream():
                raise RuntimeError("Edge-TTS connection failed")
                yield
                
            mock_comm_instance.stream = failing_stream
            mock_communicate.return_value = mock_comm_instance
            
            with patch("bot.services.gemini_service.gemini_service.synthesize_speech_audio", new_callable=AsyncMock) as mock_gemini:
                mock_gemini.side_effect = Exception("Gemini quota exceeded")
                
                with pytest.raises(RuntimeError, match="All TTS engines failed"):
                    await service.generate_audio("testword", target_lang="en")


@pytest.mark.asyncio
async def test_gemini_tts_fallback_to_edge_on_failure():
    """
    When tts_engine is 'gemini' and gemini fails,
    TTSService should fall back to edge-tts.
    """
    service = TTSService(voice="en-US-AriaNeural")

    with patch("bot.services.tts_service.settings") as mock_settings:
        mock_settings.tts_engine = "gemini"
        mock_settings.gemini_tts_voice = "Kore"
        mock_settings.gemini_tts_model = "gemini-2.5-flash-preview-tts"

        with patch("bot.services.gemini_service.gemini_service.synthesize_speech_audio", new_callable=AsyncMock) as mock_gemini:
            mock_gemini.side_effect = Exception("Gemini API 503 unavailable")

            with patch("bot.services.tts_service.edge_tts.Communicate") as mock_communicate:
                mock_comm_instance = MagicMock()

                async def successful_stream():
                    yield {"type": "audio", "data": b"fake-edge-fallback-audio"}

                mock_comm_instance.stream = successful_stream
                mock_communicate.return_value = mock_comm_instance

                result = await service.generate_audio("world", target_lang="en")

                assert isinstance(result, io.BytesIO)
                assert result.getvalue() == b"fake-edge-fallback-audio"

