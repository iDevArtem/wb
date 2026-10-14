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

    async def _synthesize_edge(self, clean_text: str, voice: str) -> bytes:
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
        return audio_bytes

    async def _synthesize_gemini(self, clean_text: str) -> bytes:
        from bot.services.gemini_service import gemini_service
        logger.debug("Generating TTS audio with Gemini Neural TTS for text: '%s'", clean_text)
        return await gemini_service.synthesize_speech_audio(
            text=clean_text,
            voice_name=settings.gemini_tts_voice,
            model=settings.gemini_tts_model,
        )

    async def generate_audio(self, text: str, target_lang: str = "en") -> io.BytesIO:
        """
        Synthesize text speech into an in-memory BytesIO buffer.
        Supports caching and hybrid engines with automatic fallback (Edge-TTS <-> Gemini TTS).
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

        is_gemini_primary = settings.tts_engine == "gemini"
        primary_name = "Gemini" if is_gemini_primary else "Edge-TTS"
        fallback_name = "Edge-TTS" if is_gemini_primary else "Gemini"

        primary_func = self._synthesize_gemini if is_gemini_primary else (lambda t: self._synthesize_edge(t, voice))
        fallback_func = (lambda t: self._synthesize_edge(t, voice)) if is_gemini_primary else self._synthesize_gemini

        last_primary_err: Exception | None = None
        try:
            audio_bytes = await primary_func(clean_text)
            self._cache[cache_key] = audio_bytes
            return io.BytesIO(audio_bytes)
        except Exception as primary_err:
            last_primary_err = primary_err
            logger.warning(
                "Primary TTS engine '%s' failed for '%s': %s. Falling back to %s...",
                primary_name, clean_text, primary_err, fallback_name
            )

        try:
            audio_bytes = await fallback_func(clean_text)
            self._cache[cache_key] = audio_bytes
            return io.BytesIO(audio_bytes)
        except Exception as fallback_err:
            logger.error(
                "Fallback TTS engine '%s' also failed for '%s': %s",
                fallback_name, clean_text, fallback_err
            )
            raise RuntimeError(
                f"All TTS engines failed for '{clean_text}'. "
                f"Primary ({primary_name}): {last_primary_err}; Fallback ({fallback_name}): {fallback_err}"
            ) from fallback_err


tts_service = TTSService()
