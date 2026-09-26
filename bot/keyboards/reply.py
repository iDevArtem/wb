from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


from bot.core.i18n import t

def get_main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """
    Main menu using ReplyKeyboardMarkup.
    Layout:
    [ 📖 Мой словарь ] [ 🎯 Начать квиз ]
    [ 📊 Статистика ]  [ 📚 Изучено ]
    [ ⚙️ Настройки  ] [ ❓ Помощь ]
    """
    builder = ReplyKeyboardBuilder()
    
    # Row 1
    builder.add(KeyboardButton(text=t(lang, "📖 Мой словарь")))
    builder.add(KeyboardButton(text=t(lang, "🎯 Начать квиз")))
    
    # Row 2
    builder.add(KeyboardButton(text=t(lang, "📊 Статистика")))
    builder.add(KeyboardButton(text=t(lang, "📚 Изучено")))
    
    # Row 3
    builder.add(KeyboardButton(text=t(lang, "⚙️ Настройки")))
    builder.add(KeyboardButton(text=t(lang, "❓ Помощь")))
    
    builder.adjust(2, 2, 2)
    
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
