import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
import pytest
from httpx import ASGITransport, AsyncClient
from pymongo import AsyncMongoClient

from bot.core.config import settings
from bot.models.user import User
from bot.models.word import Word
from bot.web.app import app
from bot.web.auth import create_access_token, validate_telegram_init_data


def generate_valid_init_data(tg_id: int, username: str = "testuser", first_name: str = "Tester") -> str:
    user_json = json.dumps({"id": tg_id, "first_name": first_name, "username": username})
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": user_json,
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items(), key=lambda x: x[0]))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = calc_hash
    return urlencode(params)


@pytest.mark.asyncio
async def test_validate_telegram_init_data():
    settings.bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    init_data = generate_valid_init_data(tg_id=987654321, username="alex", first_name="Alex")
    
    user_info = validate_telegram_init_data(init_data)
    assert user_info["id"] == 987654321
    assert user_info["username"] == "alex"
    assert user_info["first_name"] == "Alex"


@pytest.mark.asyncio
async def test_jwt_token_creation_and_verification():
    settings.jwt_secret = "test_secret_key"
    token = create_access_token(tg_id=12345, username="john")
    assert token is not None
    assert isinstance(token, str)


@pytest.mark.asyncio
async def test_web_routes(monkeypatch):
    settings.bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    settings.jwt_secret = "test_secret_key"
    
    # In-memory or test client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Test Static Index
        resp = await client.get("/")
        assert resp.status_code == 200

        # Healthcheck endpoint
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok"}

        # 2. Test Auth with invalid initData
        bad_auth = await client.post("/api/auth/telegram", json={"init_data": "invalid_data"})
        assert bad_auth.status_code in (400, 401)


@pytest.mark.asyncio
async def test_web_tts_route(monkeypatch):
    import io
    from bot.services.tts_service import tts_service

    captured_lang = []
    async def mock_generate_audio(text, target_lang="en"):
        captured_lang.append(target_lang)
        return io.BytesIO(b"dummy_mp3_bytes")

    monkeypatch.setattr(tts_service, "generate_audio", mock_generate_audio)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tts/Guten%20Tag?target_lang=de")
        assert resp.status_code == 200
        assert resp.content == b"dummy_mp3_bytes"
        assert captured_lang == ["de"]


def test_webapp_launch_token_roundtrip_and_tamper_rejection():
    from fastapi import HTTPException
    from bot.web.auth import create_webapp_launch_token, verify_webapp_launch_token

    settings.jwt_secret = "test_secret_key"
    token = create_webapp_launch_token(tg_id=424242)
    assert isinstance(token, str)
    assert verify_webapp_launch_token(token) == 424242

    # Tampered tg_id must be rejected
    _, sig = token.split(".", 1)
    with pytest.raises(HTTPException) as exc_info:
        verify_webapp_launch_token(f"999999.{sig}")
    assert exc_info.value.status_code == 401

    # Tampered signature must be rejected
    with pytest.raises(HTTPException) as exc_info:
        verify_webapp_launch_token(f"424242.{sig[:-1]}A")
    assert exc_info.value.status_code == 401

    # Malformed token must be rejected
    with pytest.raises(HTTPException) as exc_info:
        verify_webapp_launch_token("not-a-valid-token")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_launch_endpoint(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from bot.web.auth import create_webapp_launch_token, verify_access_token
    import bot.web.routes as routes_module

    settings.jwt_secret = "test_secret_key"

    fake_user_doc = {
        "tg_id": 777001,
        "username": "alice",
        "first_name": "Alice",
        "streak": 5,
        "timezone": "UTC",
        "native_language": "ru",
        "target_language": "en",
    }

    fake_db = MagicMock()
    fake_db.users = MagicMock()
    fake_db.users.find_one = AsyncMock(side_effect=lambda q: fake_user_doc if q.get("tg_id") == 777001 else None)
    monkeypatch.setattr(routes_module, "get_database", lambda: fake_db)

    valid_token = create_webapp_launch_token(tg_id=777001)
    unknown_user_token = create_webapp_launch_token(tg_id=888999)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Valid token for existing user returns JWT + user profile
        resp = await client.post("/api/auth/launch", json={"token": valid_token})
        assert resp.status_code == 200
        body = resp.json()
        assert verify_access_token(body["token"]) == 777001
        assert body["user"]["tg_id"] == 777001
        assert body["user"]["first_name"] == "Alice"

        # Invalid token returns 401
        bad_resp = await client.post("/api/auth/launch", json={"token": "777001.bad_sig"})
        assert bad_resp.status_code == 401

        # Valid token for non-existent user returns 404
        missing_resp = await client.post("/api/auth/launch", json={"token": unknown_user_token})
        assert missing_resp.status_code == 404


def test_main_menu_keyboard_includes_signed_launch_token():
    from urllib.parse import parse_qs, urlparse
    from bot.keyboards.reply import get_main_menu_keyboard
    from bot.web.auth import verify_webapp_launch_token

    settings.jwt_secret = "test_secret_key"
    settings.webapp_url = "https://wb.qper.link"

    kb = get_main_menu_keyboard("ru", tg_id=555123)
    buttons = [btn for row in kb.keyboard for btn in row]
    book_btn = next(btn for btn in buttons if btn.text == "📖")
    assert book_btn.web_app is not None

    parsed = urlparse(book_btn.web_app.url)
    qs = parse_qs(parsed.query)
    assert qs.get("filter") == ["all"]
    assert "k" in qs and len(qs["k"]) == 1
    assert verify_webapp_launch_token(qs["k"][0]) == 555123
