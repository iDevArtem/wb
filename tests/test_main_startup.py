import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramServerError,
    TelegramUnauthorizedError,
)

import main


@pytest.mark.asyncio
async def test_web_server_starts_before_telegram_api_calls():
    events: list[str] = []

    fake_settings = SimpleNamespace(
        bot_token="123456:test_token",
        gemini_api_key="test_gemini_key",
        jwt_secret="custom_secret",
        web_host="0.0.0.0",
        web_port=8000,
        log_level="INFO",
    )

    fake_server = MagicMock()
    fake_server.should_exit = False

    async def fake_serve():
        events.append("uvicorn_started")
        while not fake_server.should_exit:
            await asyncio.sleep(0.01)

    fake_server.serve = fake_serve

    fake_bot = MagicMock()
    fake_bot.session = MagicMock()
    fake_bot.session.close = AsyncMock()
    fake_bot.delete_webhook = AsyncMock(
        side_effect=lambda **kwargs: events.append("delete_webhook")
    )
    fake_bot.set_my_commands = AsyncMock(
        side_effect=lambda *args, **kwargs: events.append("set_my_commands")
    )
    fake_bot.set_chat_menu_button = AsyncMock(
        side_effect=lambda *args, **kwargs: events.append("set_chat_menu_button")
    )

    fake_dp = MagicMock()
    fake_dp.update = MagicMock()
    fake_dp.update.middleware = MagicMock()
    fake_dp.include_router = MagicMock()
    fake_dp.start_polling = AsyncMock(
        side_effect=lambda *args, **kwargs: events.append("start_polling")
    )

    fake_scheduler = MagicMock()

    with patch.object(main, "settings", fake_settings), \
         patch.object(main, "init_db", new_callable=AsyncMock), \
         patch.object(main, "close_db", new_callable=AsyncMock), \
         patch.object(main, "AsyncIOScheduler", return_value=fake_scheduler), \
         patch.object(main.uvicorn, "Server", return_value=fake_server), \
         patch.object(main, "Bot", return_value=fake_bot), \
         patch.object(main, "Dispatcher", return_value=fake_dp):
        await main.main()

    assert "uvicorn_started" in events
    assert "delete_webhook" in events
    assert "set_my_commands" in events
    assert "start_polling" in events

    uvicorn_idx = events.index("uvicorn_started")
    assert uvicorn_idx < events.index("delete_webhook")
    assert uvicorn_idx < events.index("set_my_commands")
    assert uvicorn_idx < events.index("start_polling")


@pytest.mark.asyncio
async def test_run_bot_polling_retries_on_transient_telegram_error_and_succeeds():
    bot = MagicMock()
    bot.delete_webhook = AsyncMock(
        side_effect=[
            TelegramNetworkError(method=MagicMock(), message="Request timeout error"),
            True,
        ]
    )
    bot.set_my_commands = AsyncMock(return_value=True)
    bot.set_chat_menu_button = AsyncMock(return_value=True)

    dp = MagicMock()
    dp.start_polling = AsyncMock(return_value=None)

    await main.run_bot_polling(
        dp,
        bot,
        initial_retry_delay=0.01,
        max_retry_delay=0.02,
    )

    assert bot.delete_webhook.await_count == 2
    assert bot.set_my_commands.await_count == 1
    assert bot.set_chat_menu_button.await_count == 1
    dp.start_polling.assert_awaited_once_with(bot, close_bot_session=False)


@pytest.mark.asyncio
async def test_run_bot_polling_retries_when_start_polling_fails_without_reconfiguring_commands():
    bot = MagicMock()
    bot.delete_webhook = AsyncMock(return_value=True)
    bot.set_my_commands = AsyncMock(return_value=True)
    bot.set_chat_menu_button = AsyncMock(return_value=True)

    dp = MagicMock()
    dp.start_polling = AsyncMock(
        side_effect=[
            TelegramServerError(method=MagicMock(), message="Bad Gateway"),
            None,
        ]
    )

    await main.run_bot_polling(
        dp,
        bot,
        initial_retry_delay=0.01,
        max_retry_delay=0.02,
    )

    assert dp.start_polling.await_count == 2
    assert bot.set_my_commands.await_count == 1


@pytest.mark.asyncio
async def test_run_bot_polling_exits_when_stop_event_is_set():
    bot = MagicMock()
    bot.delete_webhook = AsyncMock(
        side_effect=TelegramNetworkError(method=MagicMock(), message="timeout")
    )
    bot.set_my_commands = AsyncMock(return_value=True)
    bot.set_chat_menu_button = AsyncMock(return_value=True)

    dp = MagicMock()
    dp.start_polling = AsyncMock()

    stop_event = asyncio.Event()

    async def trigger_stop():
        await asyncio.sleep(0.02)
        stop_event.set()

    stopper = asyncio.create_task(trigger_stop())
    try:
        await asyncio.wait_for(
            main.run_bot_polling(
                dp,
                bot,
                stop_event=stop_event,
                initial_retry_delay=5.0,
                max_retry_delay=5.0,
            ),
            timeout=1.0,
        )
    finally:
        await stopper

    dp.start_polling.assert_not_called()


@pytest.mark.asyncio
async def test_run_bot_polling_propagates_unauthorized_error():
    bot = MagicMock()
    bot.delete_webhook = AsyncMock(
        side_effect=TelegramUnauthorizedError(method=MagicMock(), message="Unauthorized")
    )

    dp = MagicMock()
    dp.start_polling = AsyncMock()

    with pytest.raises(TelegramUnauthorizedError):
        await main.run_bot_polling(
            dp,
            bot,
            initial_retry_delay=0.01,
            max_retry_delay=0.02,
        )

    assert bot.delete_webhook.await_count == 1
    dp.start_polling.assert_not_called()
