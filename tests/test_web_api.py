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

        # 2. Test Auth with invalid initData
        bad_auth = await client.post("/api/auth/telegram", json={"init_data": "invalid_data"})
        assert bad_auth.status_code in (400, 401)
