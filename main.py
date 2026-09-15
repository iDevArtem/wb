import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uvicorn

from bot.core.config import settings
from bot.core.database import close_db, init_db
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

    # Initialize MongoDB connection and indexes
    await init_db()

    logger.info("Initializing Telegram bot and dispatcher...")
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Register Middlewares
    dp.update.middleware(UserMiddleware())

    # Register Routers in proper precedence
    dp.include_router(common_router)
    dp.include_router(settings_router)
    dp.include_router(quiz_router)
    dp.include_router(word_input_router)

    # Configure Telegram standard commands list and preserve Menu Button
    try:
        from aiogram.types import BotCommand, MenuButtonCommands
        bot_commands = [
            BotCommand(command="words", description="📖 Словарь и список слов"),
            BotCommand(command="quiz", description="🎯 Тренировка слов"),
            BotCommand(command="stats", description="📊 Статистика и стрик"),
            BotCommand(command="archive", description="📦 Архив выученных слов"),
            BotCommand(command="settings", description="⚙️ Настройки и тихие часы"),
            BotCommand(command="help", description="ℹ️ Справка и помощь"),
        ]
        await bot.set_my_commands(bot_commands)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Bot commands and default Menu Button registered successfully.")
    except Exception as exc:
        logger.warning("Could not set bot commands: %s", exc)

    # Initialize APScheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        check_due_words_task,
        trigger="interval",
        minutes=15,
        kwargs={"bot": bot},
        id="check_due_words_job",
        replace_existing=True,
    )

    # Start FastAPI Web Server in background
    uv_config = uvicorn.Config(
        app=web_app,
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(uv_config)
    web_server_task = asyncio.create_task(server.serve())
    logger.info("Web App server started at http://%s:%d", settings.web_host, settings.web_port)

    try:
        scheduler.start()
        logger.info("Scheduler started successfully.")

        # Drop pending updates to avoid old backlog
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot started polling...")
        await dp.start_polling(bot)
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

