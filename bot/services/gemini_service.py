import asyncio
import logging
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from bot.core.config import settings

logger = logging.getLogger(__name__)


class WordFormsDetail(BaseModel):
    summary: str = Field(
        ...,
        description="Concise summary string of forms, e.g. for verbs: 'take (V1) → took (V2) → taken (V3) | -ing: taking | 3rd: takes'; for nouns: 'child (sg) / children (pl)'; for adjectives: 'fast → faster → fastest'",
    )
    v1: str | None = Field(default=None, description="Infinitive / base form (for verbs)")
    v2: str | None = Field(default=None, description="Past Simple form (for verbs)")
    v3: str | None = Field(default=None, description="Past Participle form (for verbs)")
    v_ing: str | None = Field(default=None, description="Present Participle / Gerund form (for verbs)")
    v_s: str | None = Field(default=None, description="3rd person singular present form (for verbs)")
    comparative: str | None = Field(default=None, description="Comparative degree (for adjectives/adverbs)")
    superlative: str | None = Field(default=None, description="Superlative degree (for adjectives/adverbs)")
    plural: str | None = Field(default=None, description="Plural form (for nouns)")
    notes: str | None = Field(default=None, description="Grammar note in the native language, e.g. 'Неправильный глагол' or 'Исчисляемое существительное'")


class ExampleItem(BaseModel):
    target: str = Field(..., description="Example sentence in the target language")
    native: str = Field(..., description="Translation of the example sentence into the native language")


class WordAnalysis(BaseModel):
    canonical_word: str = Field(
        ...,
        description="Canonical target language word or phrase (e.g., 'necessary', 'go')",
    )
    lemma: str = Field(
        ...,
        description="Dictionary base lemma (infinitive without 'to', singular noun, etc.)",
    )
    pos: str = Field(
        ...,
        description="Part of speech (noun, verb, adjective, adverb, idiom, phrasal verb)",
    )
    transcription: str = Field(
        ...,
        description="Standard IPA phonetic transcription, e.g. /ˈkæveɪˌɑːt/ or 🇬🇧 /ˈkɑːst/ | 🇺🇸 /ˈkæst/",
    )
    transcription_uk: str | None = Field(
        default=None,
        description="IPA phonetic transcription for dialect 1 (e.g. British English) if applicable",
    )
    transcription_us: str | None = Field(
        default=None,
        description="IPA phonetic transcription for dialect 2 (e.g. American English) if applicable",
    )
    translation: str = Field(
        ...,
        description="Accurate, natural translation into the native language",
    )
    corrected_from: str | None = Field(
        default=None,
        description="Original typo string if spelling was corrected, else null",
    )
    examples: list[ExampleItem] = Field(
        default_factory=list,
        description="2-3 live, natural example sentences with translations",
    )
    synonyms_collocations: list[str] = Field(
        default_factory=list,
        description="1-2 set phrases, idioms, or collocations with the word",
    )
    forms: WordFormsDetail | None = Field(
        default=None,
        description="Grammar forms if applicable (e.g. V1/V2/V3 for verbs, comparative for adjectives, plural for nouns)",
    )


class WordExamplesResponse(BaseModel):
    examples: list[ExampleItem] = Field(..., description="A list of exactly 5 contextually diverse example sentences")


class VoiceQuizEvaluation(BaseModel):
    transcribed_text: str = Field(
        ...,
        description="What the user said in the voice message",
    )
    is_correct: bool = Field(
        ...,
        description="Whether the user's spoken answer matches the target word/meaning",
    )
    feedback: str = Field(
        ...,
        description="Short encouraging feedback or pronunciation tip in the native language",
    )


def get_word_analysis_prompt(native_lang: str, target_lang: str) -> str:
    return f"""
You are an expert bilingual lexicographer, {target_lang} tutor, and linguistics engine.
Your task is to analyze user input (text or audio) and output a clean, accurate structured JSON.

Rules:
1. If the input is in {native_lang} or a related language, translate it into the most natural, commonly used canonical {target_lang} word or set expression.
2. If the input is in {target_lang} with typos (e.g. "necesary", "definately"), fix the spelling in `canonical_word`, and put the original typo in `corrected_from`. If no typo, `corrected_from` must be null.
3. If the input is in an inflected grammatical form, set `lemma` to its base dictionary headword. `canonical_word` can either be the input form or lemma, but dictionary headword `lemma` must always be the base form.
4. Phonetics: Provide strict International Phonetic Alphabet (IPA) with primary (ˈ) and secondary (ˌ) stress marks if applicable for {target_lang}.
5. Provide accurate, idiomatic {native_lang} translation in `translation`, capturing polysemy, register, and stylistic nuances.
6. Provide 2-3 modern, realistic example sentences demonstrating usage in `examples`.
7. Provide 1-2 common collocations, idioms, or synonyms in `synonyms_collocations`.
8. Provide grammatical forms in `forms` if applicable.
"""

def get_voice_quiz_prompt(native_lang: str, target_lang: str) -> str:
    return f"""
You are a {target_lang} language examiner evaluating a student's voice response.
The target {target_lang} word is provided. The student records a voice message in {target_lang}.
Transcribe what the student said, check if their pronunciation and word match the target word
(or acceptable variant/synonym), and provide concise constructive feedback in {native_lang}.
"""


class GeminiServiceError(Exception):
    """Base exception for Gemini service errors."""
    pass


class GeminiQuotaExhaustedError(GeminiServiceError):
    """Raised when all models and API keys have exhausted their quota (429 RESOURCE_EXHAUSTED)."""
    def __init__(self, message: str = "Лимит запросов к ИИ исчерпан", retry_delay: float | None = None):
        super().__init__(message)
        self.retry_delay = retry_delay


def is_rate_limit_error(e: Exception) -> bool:
    code = getattr(e, "code", None)
    if code == 429:
        return True
    err_str = str(e).upper()
    return (
        "429" in err_str
        or "RESOURCE_EXHAUSTED" in err_str
        or "QUOTA EXCEEDED" in err_str
        or "RATE_LIMIT" in err_str
        or "RATE LIMIT" in err_str
    )


def is_model_unavailable_error(e: Exception) -> bool:
    code = getattr(e, "code", None)
    if code == 404:
        return True
    err_str = str(e).upper()
    return (
        "404" in err_str
        or "NOT_FOUND" in err_str
        or "NOT FOUND" in err_str
        or "NO LONGER AVAILABLE" in err_str
    )


def is_transient_server_error(e: Exception) -> bool:
    code = getattr(e, "code", None)
    if code in (500, 502, 503, 504):
        return True
    err_str = str(e).upper()
    return (
        "503" in err_str
        or "UNAVAILABLE" in err_str
        or "HIGH DEMAND" in err_str
        or "TEMPORARILY UNAVAILABLE" in err_str
    )


class GeminiService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        models_pool: list[str] | None = None,
        api_keys: list[str] | None = None,
    ):
        self._single_key = api_key
        self._primary_model = model
        self._custom_pool = models_pool
        self._custom_keys = api_keys
        self._clients: list[genai.Client] = []

    def _get_api_keys(self) -> list[str]:
        if self._custom_keys:
            return self._custom_keys
        if self._single_key:
            return [self._single_key]
        keys = settings.all_gemini_api_keys
        if not keys and settings.gemini_api_key:
            keys = [settings.gemini_api_key]
        return [k for k in keys if k]

    def _get_models_pool(self) -> list[str]:
        if self._custom_pool:
            pool = list(self._custom_pool)
        else:
            pool = list(settings.effective_models_pool)

        # If a primary model was explicitly given and is not first, place it first
        primary = self._primary_model or (pool[0] if pool else "gemini-3.5-flash-lite")
        if primary in pool:
            pool.remove(primary)
            pool.insert(0, primary)
        elif primary:
            pool.insert(0, primary)
        return pool

    def _ensure_clients(self) -> list[genai.Client]:
        if not self._clients:
            keys = self._get_api_keys()
            if not keys:
                raise ValueError("GEMINI_API_KEY is not configured in settings or environment.")
            self._clients = [genai.Client(api_key=k) for k in keys]
        return self._clients

    async def _generate_content_with_fallback(
        self,
        contents: any,
        config: types.GenerateContentConfig,
        custom_pool: list[str] | None = None,
    ) -> types.GenerateContentResponse:
        clients = self._ensure_clients()
        models = custom_pool or self._get_models_pool()

        # Ensure thinking mode is disabled by default for low latency and quota saving
        if config.thinking_config is None:
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)

        last_error: Exception | None = None
        hit_quota = False

        for client_idx, client in enumerate(clients):
            for model_name in models:
                try:
                    logger.debug("Attempting Gemini call with model: %s (key index: %d)", model_name, client_idx)
                    response = await client.aio.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    return response
                except Exception as e:
                    last_error = e
                    if is_rate_limit_error(e):
                        hit_quota = True
                        logger.warning(
                            "Gemini model '%s' (key #%d) hit rate limit (429 RESOURCE_EXHAUSTED). Failing over to next model...",
                            model_name,
                            client_idx,
                        )
                        await asyncio.sleep(0.5)
                        continue
                    elif is_model_unavailable_error(e):
                        logger.warning(
                            "Gemini model '%s' (key #%d) is unavailable (404 NOT_FOUND). Failing over to next model...",
                            model_name,
                            client_idx,
                        )
                        continue
                    elif is_transient_server_error(e):
                        logger.warning(
                            "Gemini model '%s' (key #%d) returned transient server error (503/5xx). Retrying...",
                            model_name,
                            client_idx,
                        )
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        logger.exception("Gemini API call failed with unrecoverable error on model '%s'", model_name)
                        raise GeminiServiceError(f"Ошибка Gemini API: {e}") from e

        # All models & keys exhausted
        if hit_quota:
            logger.error("All Gemini models in pool (%s) have exhausted their quotas (429).", models)
            raise GeminiQuotaExhaustedError(
                "Все модели Gemini в пуле исчерпали квоту запросов (429 RESOURCE_EXHAUSTED)."
            ) from last_error

        raise GeminiServiceError(f"Не удалось выполнить запрос к Gemini: {last_error}") from last_error

    async def analyze_text(self, text: str, native_lang: str = "ru", target_lang: str = "en") -> WordAnalysis:
        """
        Analyze a text input (native translation, target language with typos,
        or inflected word forms) and return a structured WordAnalysis.
        """
        prompt = f"Analyze the following word or phrase: \"{text.strip()}\""
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WordAnalysis,
            system_instruction=get_word_analysis_prompt(native_lang, target_lang),
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = await self._generate_content_with_fallback(contents=prompt, config=config)
        if not response.text:
            raise GeminiServiceError("Gemini API returned an empty response")

        return WordAnalysis.model_validate_json(response.text)

    async def analyze_voice(self, audio_bytes: bytes, native_lang: str = "ru", target_lang: str = "en", mime_type: str = "audio/ogg") -> WordAnalysis:
        """
        Transcribe and analyze a voice message (in-memory audio bytes)
        and return a structured WordAnalysis.
        """
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        instruction = (
            f"Listen to this audio recording. The speaker is saying a word or phrase in {target_lang} or "
            f"{native_lang}. Recognize the word accurately, normalize it according to the "
            "system instructions, and return the structured WordAnalysis."
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WordAnalysis,
            system_instruction=get_word_analysis_prompt(native_lang, target_lang),
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = await self._generate_content_with_fallback(
            contents=[audio_part, instruction],
            config=config,
        )
        if not response.text:
            raise GeminiServiceError("Gemini API returned an empty response for voice message")

        return WordAnalysis.model_validate_json(response.text)

    async def evaluate_quiz_voice(
        self,
        audio_bytes: bytes,
        target_canonical: str,
        target_lemma: str,
        native_lang: str = "ru",
        target_lang: str = "en",
        mime_type: str = "audio/ogg",
    ) -> VoiceQuizEvaluation:
        """
        Evaluate a user's spoken answer for a quiz question against the target word.
        """
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        prompt = (
            f"The target word is: '{target_canonical}' (lemma: '{target_lemma}').\n"
            "Listen to the user's spoken voice and evaluate if they pronounced this word "
            "correctly and accurately."
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VoiceQuizEvaluation,
            system_instruction=get_voice_quiz_prompt(native_lang, target_lang),
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = await self._generate_content_with_fallback(
            contents=[audio_part, prompt],
            config=config,
        )
        if not response.text:
            raise GeminiServiceError("Gemini API returned an empty response for quiz voice evaluation")

        return VoiceQuizEvaluation.model_validate_json(response.text)

    async def get_word_examples(
        self,
        word: str,
        lemma: str,
        pos: str,
        translation: str,
        native_lang: str = "ru",
        target_lang: str = "en",
    ) -> WordExamplesResponse:
        prompt = (
            f"Generate 5 distinct and useful example sentences for the word '{word}'. "
            f"Context: lemma='{lemma}', pos='{pos}', translation in native language='{translation}'. "
            f"Target language code: {target_lang}. Native language code: {native_lang}. "
            "Ensure the examples cover different contexts or common collocations. "
            "Return JSON matching the schema."
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WordExamplesResponse,
            system_instruction="You are an expert linguist. Generate 5 contextually diverse example sentences.",
            temperature=0.7,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._generate_content_with_fallback(contents=prompt, config=config)
        if not response.text:
            raise GeminiServiceError("Gemini API returned an empty response for examples")
        return WordExamplesResponse.model_validate_json(response.text)

    async def synthesize_speech_audio(
        self,
        text: str,
        voice_name: str | None = None,
        model: str | None = None,
    ) -> bytes:
        """
        Synthesize neural speech using Gemini TTS model (e.g. gemini-2.5-flash-preview-tts).
        Returns raw audio bytes.
        """
        chosen_voice = voice_name or settings.gemini_tts_voice
        chosen_model = model or settings.gemini_tts_model
        prompt = f"Please pronounce the following clearly with natural articulation: {text.strip()}"
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=chosen_voice,
                    )
                )
            ),
        )

        response = await self._generate_content_with_fallback(
            contents=prompt,
            config=config,
            custom_pool=[chosen_model, "gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview"],
        )

        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                    return part.inline_data.data

        raise GeminiServiceError("No audio stream returned from Gemini TTS")


gemini_service = GeminiService()
