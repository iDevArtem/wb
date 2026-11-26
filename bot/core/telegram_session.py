"""Resilient Telegram HTTP transport.

Fixes intermittent 60s hangs when uploading media (rich messages with audio) from
Docker/Coolify hosts:
  * forces IPv4 for the connector (broken IPv6 / PMTU blackholes stall large uploads);
  * sends ``BufferedInputFile`` as raw bytes so aiohttp sets ``Content-Length``
    instead of ``Transfer-Encoding: chunked``;
  * ``call_with_retry`` gives media calls a short timeout and one retry on a fresh socket.
"""
import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from aiohttp import FormData
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

MEDIA_REQUEST_TIMEOUT = 15
MEDIA_ATTEMPTS = 2
RETRYABLE_ERRORS = (TelegramNetworkError, asyncio.TimeoutError)

T = TypeVar("T")


class ResilientAiohttpSession(AiohttpSession):
    def __init__(self, *, force_ipv4: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if force_ipv4 and self._proxy is None:
            self._connector_init["family"] = socket.AF_INET

    def build_form_data(self, bot, method) -> FormData:  # type: ignore[override]
        form = FormData(quote_fields=False)
        files: dict[str, Any] = {}
        for key, value in method.model_dump(warnings=False).items():
            value = self.prepare_value(value, bot=bot, files=files)
            if not value:
                continue
            form.add_field(key, value)
        for key, input_file in files.items():
            filename = input_file.filename or key
            if isinstance(input_file, BufferedInputFile):
                form.add_field(key, input_file.data, filename=filename)
            else:
                form.add_field(key, input_file.read(bot), filename=filename)
        return form


async def call_with_retry(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    attempts: int = MEDIA_ATTEMPTS,
    delay: float = 0.5,
    request_timeout: int = MEDIA_REQUEST_TIMEOUT,
    **kwargs: Any,
) -> T:
    """Call a Bot API method with a short timeout, retrying transient network errors."""
    for attempt in range(1, attempts + 1):
        try:
            return await func(*args, request_timeout=request_timeout, **kwargs)
        except RETRYABLE_ERRORS as exc:
            if attempt >= attempts:
                raise
            logger.warning(
                "Telegram media request failed (attempt %d/%d): %s. Retrying...",
                attempt, attempts, exc,
            )
            if delay:
                await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover
