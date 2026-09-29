import pytest
from unittest.mock import AsyncMock, MagicMock
from google.genai import errors

from bot.core.config import Settings, DEFAULT_MODELS_POOL
from bot.services.gemini_service import (
    GeminiService,
    GeminiServiceError,
    GeminiQuotaExhaustedError,
    WordAnalysis,
    is_rate_limit_error,
    is_model_unavailable_error,
    is_transient_server_error,
)


def test_settings_models_pool_parsing():
    s = Settings(
        _env_file=None,
        gemini_model="gemini-3.7-flash",
        gemini_models_pool="gemini-3.6-flash, gemini-3.7-flash, gemini-3.5-flash-lite",
    )
    assert s.gemini_models_pool == ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"]
    assert s.effective_models_pool[0] == "gemini-3.7-flash"
    assert "gemini-3.6-flash" in s.effective_models_pool


def test_settings_default_models_pool():
    s = Settings(_env_file=None)
    assert s.gemini_models_pool == DEFAULT_MODELS_POOL
    assert s.effective_models_pool[0] == "gemini-3.7-flash"


def test_settings_api_keys_parsing():
    s = Settings(
        _env_file=None,
        gemini_api_key="key1",
        gemini_api_keys="key2, key3",
    )
    assert s.all_gemini_api_keys == ["key1", "key2", "key3"]


def test_error_classification():
    # 429 Rate limit
    err_429 = errors.APIError(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})
    assert is_rate_limit_error(err_429)
    assert is_rate_limit_error(Exception("Quota exceeded for metric"))

    # 404 Model not found / deprecated
    err_404 = errors.APIError(404, {"error": {"message": "This model is no longer available to new users"}})
    assert is_model_unavailable_error(err_404)
    assert is_model_unavailable_error(Exception("models/gemini-2.5-flash is NOT_FOUND"))

    # 503 High demand / unavailable
    err_503 = errors.APIError(503, {"error": {"message": "This model is currently experiencing high demand"}})
    assert is_transient_server_error(err_503)
    assert is_transient_server_error(Exception("503 UNAVAILABLE. Spikes in demand"))

    # Non-recoverable client error
    err_400 = errors.APIError(400, {"error": {"message": "Invalid JSON argument"}})
    assert not is_rate_limit_error(err_400)
    assert not is_model_unavailable_error(err_400)
    assert not is_transient_server_error(err_400)


@pytest.mark.asyncio
async def test_gemini_fallback_success_on_second_model():
    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_models = MagicMock()
    mock_aio.models = mock_models

    valid_json = (
        '{"canonical_word": "hello", "lemma": "hello", "pos": "noun", '
        '"transcription": "/həˈloʊ/", "translation": "привет", '
        '"corrected_from": null, "level": "A1", "definition": "A greeting.", "grammar_notes": [], "examples": [{"target": "a", "native": "b"}]}'
    )
    success_resp = MagicMock()
    success_resp.text = valid_json

    call_history = []

    async def mock_generate_content(model, contents, config):
        call_history.append(model)
        if model == "model-a":
            raise errors.APIError(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})
        return success_resp

    mock_models.generate_content = AsyncMock(side_effect=mock_generate_content)

    service = GeminiService(
        api_key="test_key",
        models_pool=["model-a", "model-b"],
    )
    service._clients = [mock_client]

    result = await service.analyze_text("hello")

    assert isinstance(result, WordAnalysis)
    assert result.canonical_word == "hello"
    assert call_history == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_gemini_fallback_on_404_deprecated_model():
    mock_client = MagicMock()
    mock_models = MagicMock()
    mock_client.aio.models = mock_models

    valid_json = (
        '{"canonical_word": "test", "lemma": "test", "pos": "verb", '
        '"transcription": "/tɛst/", "translation": "тестировать", '
        '"corrected_from": null, "level": "A1", "definition": "A greeting.", "grammar_notes": [], "examples": [{"target": "a", "native": "b"}]}'
    )
    success_resp = MagicMock()
    success_resp.text = valid_json

    call_history = []

    async def mock_generate_content(model, contents, config):
        call_history.append(model)
        if model == "gemini-2.5-flash":
            raise errors.APIError(404, {"error": {"message": "This model is no longer available to new users."}})
        return success_resp

    mock_models.generate_content = AsyncMock(side_effect=mock_generate_content)

    service = GeminiService(
        api_key="test_key",
        models_pool=["gemini-2.5-flash", "gemini-3.5-flash-lite"],
    )
    service._clients = [mock_client]

    result = await service.analyze_text("test")
    assert result.canonical_word == "test"
    assert call_history == ["gemini-2.5-flash", "gemini-3.5-flash-lite"]


@pytest.mark.asyncio
async def test_gemini_fallback_on_503_high_demand():
    mock_client = MagicMock()
    mock_models = MagicMock()
    mock_client.aio.models = mock_models

    valid_json = (
        '{"canonical_word": "peace", "lemma": "peace", "pos": "noun", '
        '"transcription": "/piːs/", "translation": "мир", '
        '"corrected_from": null, "level": "A1", "definition": "A greeting.", "grammar_notes": [], "examples": [{"target": "a", "native": "b"}]}'
    )
    success_resp = MagicMock()
    success_resp.text = valid_json

    call_history = []

    async def mock_generate_content(model, contents, config):
        call_history.append(model)
        if model == "gemini-3.6-flash":
            raise errors.APIError(503, {"error": {"message": "This model is currently experiencing high demand."}})
        return success_resp

    mock_models.generate_content = AsyncMock(side_effect=mock_generate_content)

    service = GeminiService(
        api_key="test_key",
        models_pool=["gemini-3.6-flash", "gemini-3.5-flash-lite"],
    )
    service._clients = [mock_client]

    result = await service.analyze_text("peace")
    assert result.canonical_word == "peace"
    assert call_history == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]


@pytest.mark.asyncio
async def test_gemini_fallback_all_exhausted():
    mock_client = MagicMock()
    mock_models = MagicMock()
    mock_client.aio.models = mock_models

    async def mock_generate_content(model, contents, config):
        raise errors.APIError(429, {"error": {"message": "Quota exceeded"}})

    mock_models.generate_content = AsyncMock(side_effect=mock_generate_content)

    service = GeminiService(
        api_key="test_key",
        models_pool=["model-a", "model-b"],
    )
    service._clients = [mock_client]

    with pytest.raises(GeminiQuotaExhaustedError):
        await service.analyze_text("hello")


@pytest.mark.asyncio
async def test_gemini_non_quota_error_raises_service_error():
    mock_client = MagicMock()
    mock_models = MagicMock()
    mock_client.aio.models = mock_models

    async def mock_generate_content(model, contents, config):
        raise errors.APIError(400, {"error": {"message": "Bad Request / Invalid Argument"}})

    mock_models.generate_content = AsyncMock(side_effect=mock_generate_content)

    service = GeminiService(
        api_key="test_key",
        models_pool=["model-a", "model-b"],
    )
    service._clients = [mock_client]

    with pytest.raises(GeminiServiceError) as exc_info:
        await service.analyze_text("hello")

    assert "Bad Request" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_multiple_keys_rotation():
    mock_client1 = MagicMock()
    mock_client1.aio.models.generate_content = AsyncMock(
        side_effect=errors.APIError(429, {"error": {"message": "Quota exceeded"}})
    )

    valid_json = (
        '{"canonical_word": "world", "lemma": "world", "pos": "noun", '
        '"transcription": "/wɜːrld/", "translation": "мир", '
        '"corrected_from": null, "level": "A1", "definition": "A greeting.", "grammar_notes": [], "examples": [{"target": "a", "native": "b"}]}'
    )
    success_resp = MagicMock()
    success_resp.text = valid_json

    mock_client2 = MagicMock()
    mock_client2.aio.models.generate_content = AsyncMock(return_value=success_resp)

    service = GeminiService(
        api_keys=["key1", "key2"],
        models_pool=["model-a"],
    )
    service._clients = [mock_client1, mock_client2]

    result = await service.analyze_text("world")
    assert result.canonical_word == "world"
    assert mock_client1.aio.models.generate_content.call_count == 1
    assert mock_client2.aio.models.generate_content.call_count == 1


@pytest.mark.asyncio
async def test_word_analysis_phonetics_uk_us():
    mock_client = MagicMock()
    mock_models = MagicMock()
    mock_client.aio.models = mock_models

    valid_json = (
        '{"canonical_word": "schedule", "lemma": "schedule", "pos": "noun", '
        '"transcription": "🇬🇧 /ˈʃɛdjuːl/ | 🇺🇸 /ˈskɛdʒuːl/", '
        '"transcription_uk": "/ˈʃɛdjuːl/", "transcription_us": "/ˈskɛdʒuːl/", '
        '"translation": "расписание", "corrected_from": null, '
        '"level": "A2", "definition": "A plan of activities or events.", "grammar_notes": [], "examples": [{"target": "a", "native": "b"}]}'
    )
    resp = MagicMock()
    resp.text = valid_json
    mock_models.generate_content = AsyncMock(return_value=resp)

    service = GeminiService(api_key="test_key", models_pool=["gemini-3.7-flash"])
    service._clients = [mock_client]

    result = await service.analyze_text("schedule")
    assert result.transcription_uk == "/ˈʃɛdjuːl/"
    assert result.transcription_us == "/ˈskɛdʒuːl/"

    # Verify thinking budget was set to 0 in config
    call_kwargs = mock_models.generate_content.call_args.kwargs
    config = call_kwargs["config"]
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_budget == 0


@pytest.mark.asyncio
async def test_gemini_tts_synthesis():
    mock_client = MagicMock()
    mock_models = MagicMock()
    mock_client.aio.models = mock_models

    mock_part = MagicMock()
    mock_part.inline_data = MagicMock()
    mock_part.inline_data.data = b"fake_pcm_audio_stream"

    mock_resp = MagicMock()
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_resp.candidates = [mock_candidate]

    mock_models.generate_content = AsyncMock(return_value=mock_resp)

    service = GeminiService(api_key="test_key", models_pool=["gemini-3.7-flash"])
    service._clients = [mock_client]

    audio = await service.synthesize_speech_audio("flabbergasted", voice_name="Kore")
    assert audio == b"fake_pcm_audio_stream"

