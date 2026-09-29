from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from bot.core.i18n import t
from bot.core.config import settings

def get_main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """
    Main menu using ReplyKeyboardMarkup.
    """
    builder = ReplyKeyboardBuilder()
    
    # 1. 🧠 Повторить
    builder.add(KeyboardButton(text=t(lang, "🧠 Повторить")))
        
    # 2. 📊
    builder.add(KeyboardButton(text="📊"))
    
    # 3. 📖 Словарь
    if settings.webapp_url:
        base_url = settings.webapp_url.rstrip("/")
        builder.add(KeyboardButton(text="📖", web_app=WebAppInfo(url=f"{base_url}/?filter=all")))
    else:
        builder.add(KeyboardButton(text="📖"))
    
    builder.adjust(3)
    
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
