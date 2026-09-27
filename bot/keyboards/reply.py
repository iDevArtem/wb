from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


from bot.core.i18n import t

def get_main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """
    Main menu using ReplyKeyboardMarkup.
    Layout:
    [ 📖 ] [ 🎯 ]
    [ 📊 ] [ 📚 ]
    [ ⚙️ ] [ ❓ ]
    """
    builder = ReplyKeyboardBuilder()
    
    builder.add(KeyboardButton(text="📖"))
    builder.add(KeyboardButton(text="🎯"))
    builder.add(KeyboardButton(text="📊"))
    builder.add(KeyboardButton(text="📚"))
    builder.add(KeyboardButton(text="⚙️"))
    builder.add(KeyboardButton(text="❓"))
    
    builder.adjust(6)
    
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
