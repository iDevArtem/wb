from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Main menu using ReplyKeyboardMarkup.
    Layout:
    [ 📖 Мой словарь ] [ 🎯 Начать квиз ]
    [ 📊 Статистика ]  [ 📚 Изучено ]
    [ ⚙️ Настройки  ] [ ❓ Помощь ]
    """
    builder = ReplyKeyboardBuilder()
    
    # Row 1
    builder.add(KeyboardButton(text="📖 Мой словарь"))
    builder.add(KeyboardButton(text="🎯 Начать квиз"))
    
    # Row 2
    builder.add(KeyboardButton(text="📊 Статистика"))
    builder.add(KeyboardButton(text="📚 Изучено"))
    
    # Row 3
    builder.add(KeyboardButton(text="⚙️ Настройки"))
    builder.add(KeyboardButton(text="❓ Помощь"))
    
    builder.adjust(2, 2, 2)
    
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
