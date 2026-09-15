import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bot.core.config import settings
from bot.core.database import get_database
from bot.models.user import User

logger = logging.getLogger("bot.web.auth")

security = HTTPBearer(auto_error=False)


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (4 - (len(data) % 4)) if (len(data) % 4) != 0 else ""
    return base64.urlsafe_b64decode(data + padding)


def validate_telegram_init_data(init_data_raw: str) -> dict:
    """
    Validates Telegram WebApp initData query string using HMAC-SHA256.
    Returns the parsed user dict if valid, or raises HTTPException.
    """
    if not init_data_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="init_data is missing",
        )

    try:
        parsed_params = dict(parse_qsl(init_data_raw, keep_blank_values=True))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed init_data string: {exc}",
        )

    received_hash = parsed_params.pop("hash", None)
    if not received_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="hash parameter missing in init_data",
        )

    # Sort key-value pairs alphabetically
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed_params.items(), key=lambda x: x[0])
    )

    # Calculate secret key: HMAC_SHA256("WebAppData", bot_token)
    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    # Calculate validation hash: HMAC_SHA256(secret_key, data_check_string)
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        logger.warning("Telegram initData signature verification failed.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram signature",
        )

    # Verify auth_date (allow up to 7 days for webapp session resumption)
    auth_date_str = parsed_params.get("auth_date")
    if auth_date_str:
        try:
            auth_date = int(auth_date_str)
            now = int(time.time())
            if now - auth_date > 86400 * 7:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="init_data has expired",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid auth_date format",
            )

    user_str = parsed_params.get("user")
    if not user_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User object missing in init_data",
        )

    try:
        user_data = json.loads(user_str)
        return user_data
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user JSON in init_data: {exc}",
        )


def create_access_token(tg_id: int, username: str | None = None) -> str:
    """Generates standard HS256 JWT access token."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    exp = now + (settings.jwt_expire_days * 86400)
    payload = {
        "sub": str(tg_id),
        "username": username or "",
        "exp": exp,
        "iat": now,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_access_token(token: str) -> int:
    """Verifies HS256 JWT access token and returns telegram user ID (tg_id)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token structure",
            )

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(
            settings.jwt_secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()

        received_sig = _base64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, received_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
            )

        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        now = int(time.time())
        exp = payload.get("exp", 0)
        if exp < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )

        tg_id_str = payload.get("sub")
        if not tg_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject missing",
            )
        return int(tg_id_str)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {exc}",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> User:
    """FastAPI Dependency: extracts current authenticated user from Bearer token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tg_id = verify_access_token(credentials.credentials)
    db = get_database()
    user_doc = await db.users.find_one({"tg_id": tg_id})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in database",
        )

    return User(**user_doc)
