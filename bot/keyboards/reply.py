from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from bot.core.i18n import t
from bot.core.config import settings

def get_main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """
    Main menu using ReplyKeyboardMarkup.
    Layout:
    [ 📖 ] [ 🧠 ]
    [ 📊 ] [ 📚 ]
    [ ⚙️ ] [ ❓ ]
    """
    builder = ReplyKeyboardBuilder()
    
    if settings.webapp_url:
        builder.add(KeyboardButton(text="📖", web_app=WebAppInfo(url=f"{settings.webapp_url}?filter=all")))
    else:
        builder.add(KeyboardButton(text="📖"))
        
    builder.add(KeyboardButton(text="🧠"))
    builder.add(KeyboardButton(text="📊"))
    
    if settings.webapp_url:
        builder.add(KeyboardButton(text="📚", web_app=WebAppInfo(url=f"{settings.webapp_url}?filter=archived")))
    else:
        builder.add(KeyboardButton(text="📚"))
        
    builder.add(KeyboardButton(text="⚙️"))
    builder.add(KeyboardButton(text="❓"))
    
    builder.adjust(6)
    
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
