from urllib.parse import urlencode

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from bot.core.i18n import t
from bot.core.config import settings
from bot.web.auth import create_webapp_launch_token


def get_main_menu_keyboard(lang: str, tg_id: int | None = None) -> ReplyKeyboardMarkup:
    """
    Main menu using ReplyKeyboardMarkup.
    When tg_id is provided, embeds a signed launch token in the 📖 WebApp URL
    because Telegram omits WebApp.initData for ReplyKeyboardMarkup buttons.
    """
    builder = ReplyKeyboardBuilder()
    
    # 1. 🧠 Повторить
    builder.add(KeyboardButton(text=t(lang, "🧠 Учить")))

    # 2. 📊 Статистика
    builder.add(KeyboardButton(text="📊"))
        
    # 3. 📖 Словарь
    if settings.webapp_url:
        base_url = settings.webapp_url.rstrip("/")
        params = {"filter": "all"}
        if tg_id is not None:
            params["k"] = create_webapp_launch_token(tg_id)
        builder.add(KeyboardButton(text="📖", web_app=WebAppInfo(url=f"{base_url}/?{urlencode(params)}")))
    else:
        builder.add(KeyboardButton(text="📖"))
    
    builder.adjust(3)
    
    return builder.as_markup(resize_keyboard=True)
