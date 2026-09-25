import io
import logging
import edge_tts
from bot.core.config import settings

logger = logging.getLogger(__name__)

LANGUAGE_VOICE_MAP = {
    "en": "en-US-AriaNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-PT-RaquelNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural"
}

class TTSService:
    def __init__(self, voice: str | None = None):
        self.default_voice = voice or settings.tts_voice
        self._cache: dict[str, bytes] = {}

    def get_voice_for_language(self, target_lang: str) -> str:
        lang_prefix = target_lang.lower().split("-")[0]
        return LANGUAGE_VOICE_MAP.get(lang_prefix, self.default_voice)

    async def generate_audio(self, text: str, target_lang: str = "en") -> io.BytesIO:
        """
        Synthesize text speech into an in-memory BytesIO buffer.
        Supports caching and hybrid engines (Edge-TTS / Gemini TTS preview).
        No temporary files are created on disk.
        """
        if not text or not text.strip():
            raise ValueError("Text for TTS cannot be empty")

        clean_text = text.strip()
        voice = self.get_voice_for_language(target_lang)
        cache_key = f"{settings.tts_engine}:{voice}:{clean_text.lower()}"
        
        if cache_key in self._cache:
            logger.debug("Returning cached TTS audio for '%s'", clean_text)
            return io.BytesIO(self._cache[cache_key])

        # Try Gemini TTS if configured
        if settings.tts_engine == "gemini":
            try:
                from bot.services.gemini_service import gemini_service
                logger.debug("Generating TTS audio with Gemini Neural TTS for text: '%s'", clean_text)
                raw_audio = await gemini_service.synthesize_speech_audio(
                    text=clean_text,
                    voice_name=settings.gemini_tts_voice,
                    model=settings.gemini_tts_model,
                )
                self._cache[cache_key] = raw_audio
                return io.BytesIO(raw_audio)
            except Exception as e:
                logger.warning("Gemini TTS failed (%s). Falling back to Edge-TTS...", e)

        # Fallback to Edge-TTS
        logger.debug("Generating TTS audio with Edge-TTS for text: '%s' with voice: %s", clean_text, voice)
        communicate = edge_tts.Communicate(text=clean_text, voice=voice)
        audio_buffer = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and "data" in chunk:
                audio_buffer.write(chunk["data"])

        audio_buffer.seek(0)
        audio_bytes = audio_buffer.getvalue()
        if not audio_bytes:
            raise RuntimeError(f"Edge-TTS produced 0 bytes for input: '{clean_text}'")

        self._cache[cache_key] = audio_bytes
        return io.BytesIO(audio_bytes)


tts_service = TTSService()
