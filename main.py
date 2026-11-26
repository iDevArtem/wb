import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import BotCommand, MenuButtonCommands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uvicorn

from bot.core.config import settings
from bot.core.database import close_db, init_db
from bot.core.telegram_session import ResilientAiohttpSession
from bot.handlers.common import router as common_router
from bot.handlers.quiz_fsm import router as quiz_router
from bot.handlers.settings import router as settings_router
from bot.handlers.word_input import router as word_input_router
from bot.middlewares.user import UserMiddleware
from bot.scheduler.tasks import check_due_words_task
from bot.web.app import app as web_app

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bot.main")

TRANSIENT_TELEGRAM_ERRORS = (
    TelegramNetworkError,
    TelegramServerError,
    TelegramRetryAfter,
    TimeoutError,
    OSError,
)


async def configure_bot_commands(bot: Bot, request_timeout: int = 15) -> bool:
    """Register Telegram command list and menu button without blocking startup indefinitely."""
    try:
        bot_commands = [
            BotCommand(command="start", description="🚀"),
            BotCommand(command="words", description="📖"),
            BotCommand(command="settings", description="⚙️"),
            BotCommand(command="help", description="❓"),
        ]
        await bot.set_my_commands(bot_commands, request_timeout=request_timeout)
        await bot.set_chat_menu_button(
            menu_button=MenuButtonCommands(),
            request_timeout=request_timeout,
        )
        logger.info("Bot commands and default Menu Button registered successfully.")
        return True
    except Exception as exc:
        logger.warning("Could not set bot commands: %s", exc)
        return False


async def run_bot_polling(
    dp: Dispatcher,
    bot: Bot,
    stop_event: asyncio.Event | None = None,
    initial_retry_delay: float = 5.0,
    max_retry_delay: float = 30.0,
    startup_timeout: int = 15,
) -> None:
    """Connect to Telegram Bot API and run polling, retrying transient outages with backoff."""
    delay = initial_retry_delay
    commands_configured = False

    while stop_event is None or not stop_event.is_set():
        try:
            await bot.delete_webhook(
                drop_pending_updates=True,
                request_timeout=startup_timeout,
            )
            if not commands_configured:
                commands_configured = await configure_bot_commands(
                    bot,
                    request_timeout=startup_timeout,
                )
            logger.info("Bot started polling...")
            await dp.start_polling(bot, close_bot_session=False)
            return
        except asyncio.CancelledError:
            raise
        except TelegramUnauthorizedError:
            logger.critical("Telegram rejected BOT_TOKEN (Unauthorized). Check BOT_TOKEN configuration.")
            raise
        except TRANSIENT_TELEGRAM_ERRORS as exc:
            if stop_event is not None and stop_event.is_set():
                return
            logger.warning(
                "Telegram API unavailable during startup/polling (%s). Retrying in %.1fs...",
                exc,
                delay,
            )
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                    return
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(delay)
            delay = min(delay * 1.5, max_retry_delay)


async def main() -> None:
    if not settings.bot_token:
        logger.critical(
            "BOT_TOKEN is empty! Please configure BOT_TOKEN in .env before launching."
        )
        sys.exit(1)

    if not settings.gemini_api_key:
        logger.warning(
            "GEMINI_API_KEY is empty! Gemini analysis and voice recognition will fail without a valid key."
        )

    if settings.jwt_secret == "english_learning_bot_secret_jwt_key_2026":
        logger.warning(
            "JWT_SECRET is using the default fallback secret! For production environments, configure a unique random JWT_SECRET in .env."
        )

    # Initialize MongoDB connection and indexes
    await init_db()

    logger.info("Initializing Telegram bot and dispatcher...")
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=ResilientAiohttpSession(
            force_ipv4=getattr(settings, "telegram_force_ipv4", True),
        ),
    )
    dp = Dispatcher()

    # Register Middlewares
    dp.update.middleware(UserMiddleware())

    # Register Routers in proper precedence
    dp.include_router(common_router)
    dp.include_router(settings_router)
    dp.include_router(quiz_router)
    dp.include_router(word_input_router)

    # Initialize APScheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        check_due_words_task,
        trigger="interval",
        minutes=5,
        kwargs={"bot": bot, "dp": dp},
        id="check_due_words_job",
        replace_existing=True,
    )

    # Start FastAPI Web Server immediately so healthcheck passes even if Telegram API is slow/down
    uv_config = uvicorn.Config(
        app=web_app,
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(uv_config)
    stop_event = asyncio.Event()
    web_server_task = asyncio.create_task(server.serve())
    web_server_task.add_done_callback(lambda _: stop_event.set())
    await asyncio.sleep(0)
    logger.info("Web App server started at http://%s:%d", settings.web_host, settings.web_port)

    try:
        scheduler.start()
        logger.info("Scheduler started successfully.")

        await run_bot_polling(dp, bot, stop_event=stop_event)
    finally:
        logger.info("Shutting down...")
        server.should_exit = True
        try:
            await asyncio.wait_for(web_server_task, timeout=5.0)
        except Exception:
            pass
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await close_db()
        logger.info("Cleanup completed. Bot stopped.")



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by signal.")

