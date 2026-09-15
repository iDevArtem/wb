import io
import logging
import edge_tts
from bot.core.config import settings

logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self, voice: str | None = None):
        self.voice = voice or settings.tts_voice

    async def generate_audio(self, text: str) -> io.BytesIO:
        """
        Synthesize text speech into an in-memory BytesIO MP3 buffer using edge-tts.
        No temporary files are created on disk.
        """
        if not text or not text.strip():
            raise ValueError("Text for TTS cannot be empty")

        clean_text = text.strip()
        logger.debug("Generating TTS audio for text: '%s' with voice: %s", clean_text, self.voice)

        communicate = edge_tts.Communicate(text=clean_text, voice=self.voice)
        audio_buffer = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and "data" in chunk:
                audio_buffer.write(chunk["data"])

        audio_buffer.seek(0)
        if audio_buffer.getbuffer().nbytes == 0:
            raise RuntimeError(f"Edge-TTS produced 0 bytes for input: '{clean_text}'")

        return audio_buffer


tts_service = TTSService()
