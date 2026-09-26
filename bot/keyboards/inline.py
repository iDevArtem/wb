from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.core.config import settings


def get_word_card_keyboard(word_id: int | str) -> InlineKeyboardMarkup:
    """
    Inline keyboard for a newly added or inspected word card:
    [🔊 Озвучить еще раз]
    [💬 Примеры]
    [🗑 Удалить] [✅ Знаю (в архив)]
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔊 Озвучить еще раз",
            callback_data=f"tts:{word_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="💬 Примеры",
            callback_data=f"examples:{word_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"delete_word:{word_id}",
        ),
        InlineKeyboardButton(
            text="✅ Знаю (в архив)",
            callback_data=f"archive_word:{word_id}",
        ),
    )
    return builder.as_markup()


def get_duplicate_word_keyboard(word_id: int | str) -> InlineKeyboardMarkup:
    """
    Keyboard when the word is already in user's dictionary.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🎯 Повторить прямо сейчас",
            callback_data=f"quiz_word:{word_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔊 Послушать",
            callback_data=f"tts:{word_id}",
        ),
        InlineKeyboardButton(
            text="🔙 Понятно",
            callback_data="dismiss",
        ),
    )
    return builder.as_markup()


def get_quiz_options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    """
    4 Multiple-choice buttons for quiz, plus skip/stop controls.
    """
    builder = InlineKeyboardBuilder()
    for idx, opt in enumerate(options):
        # Limit text length to avoid telegram button overflow
        btn_text = opt[:40] + ("..." if len(opt) > 40 else "")
        builder.row(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"quiz_mc:{idx}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="quiz_skip"),
        InlineKeyboardButton(text="🛑 Завершить", callback_data="quiz_stop"),
    )
    return builder.as_markup()


def get_quiz_control_keyboard() -> InlineKeyboardMarkup:
    """
    Controls during text/voice quiz: skip or stop.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="quiz_skip"),
        InlineKeyboardButton(text="🛑 Завершить", callback_data="quiz_stop"),
    )
    return builder.as_markup()


def get_quiz_next_keyboard() -> InlineKeyboardMarkup:
    """
    Buttons shown after word quiz resolution (success or 3 attempts exhausted).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➡️ Следующее слово", callback_data="quiz_next"),
        InlineKeyboardButton(text="🛑 Завершить", callback_data="quiz_stop"),
    )
    return builder.as_markup()


def get_scheduler_notification_keyboard() -> InlineKeyboardMarkup:
    """
    Keyboard for scheduler push notification.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🎯 Начать квиз",
            callback_data="quiz_start_due",
        ),
    )
    return builder.as_markup()


def get_archive_item_keyboard(word_id: int | str) -> InlineKeyboardMarkup:
    """
    Button to restore an archived word.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="↩️ Вернуть в обучение",
            callback_data=f"unarchive_word:{word_id}",
        ),
    )
    return builder.as_markup()


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """
    Settings menu keyboard.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📚 Мои словари", callback_data="my_dictionaries"),
    )
    builder.row(
        InlineKeyboardButton(text="🗣 Родной язык", callback_data="set_native_lang"),
        InlineKeyboardButton(text="🎯 Изучаемый язык", callback_data="set_target_lang"),
    )
    builder.row(
        InlineKeyboardButton(text="🌍 Выбрать часовой пояс", callback_data="set_tz"),
    )
    builder.row(
        InlineKeyboardButton(text="🌙 Настроить тихие часы", callback_data="set_quiet"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Закрыть", callback_data="dismiss"),
    )
    return builder.as_markup()


def get_timezone_presets_keyboard() -> InlineKeyboardMarkup:
    """
    Quick timezone preset buttons.
    """
    presets = [
        ("Москва (UTC+3)", "Europe/Moscow"),
        ("Киев (UTC+2/3)", "Europe/Kyiv"),
        ("Лондон (UTC+0/1)", "Europe/London"),
        ("Нью-Йорк (UTC-5/4)", "America/New_York"),
        ("Алматы (UTC+5)", "Asia/Almaty"),
        ("UTC (+0)", "UTC"),
    ]
    builder = InlineKeyboardBuilder()
    for title, tz in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"save_tz:{tz}"))
    builder.row(InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="manual_tz"))
    builder.row(InlineKeyboardButton(text="🔙 Назад в настройки", callback_data="open_settings"))
    return builder.as_markup()


def get_quiet_hours_presets_keyboard() -> InlineKeyboardMarkup:
    """
    Quiet hours presets.
    """
    presets = [
        ("🌙 21:00 — 10:00 (По умолчанию)", "quiet:21:10"),
        ("🌙 22:00 — 09:00", "quiet:22:9"),
        ("🌙 23:00 — 08:00", "quiet:23:8"),
        ("🔔 Без ограничений (всегда)", "quiet:0:0"),
    ]
    builder = InlineKeyboardBuilder()
    for title, data in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=data))
    builder.row(InlineKeyboardButton(text="🔙 Назад в настройки", callback_data="open_settings"))
    return builder.as_markup()


def get_words_pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """
    Pagination keyboard for /words list.
    """
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"words_page:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"words_page:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    if settings.webapp_url:
        builder.row(
            InlineKeyboardButton(
                text="🌐 Открыть веб-словарь (Mini App)",
                web_app=WebAppInfo(url=settings.webapp_url),
            )
        )

    builder.row(
        InlineKeyboardButton(text="🎯 Повторить слова (/quiz)", callback_data="quiz_start_due"),
        InlineKeyboardButton(text="🔙 Закрыть", callback_data="dismiss"),
    )
    return builder.as_markup()


def get_start_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for /start greeting with direct WebApp button."""
    builder = InlineKeyboardBuilder()
    if settings.webapp_url:
        builder.row(
            InlineKeyboardButton(
                text="📖 Открыть мой веб-словарь",
                web_app=WebAppInfo(url=settings.webapp_url),
            )
        )
    return builder.as_markup()


def get_language_presets_keyboard(lang_type: str) -> InlineKeyboardMarkup:
    """
    Quick language preset buttons.
    """
    presets = [
        ("Українська", "uk"),
        ("English", "en"),
        ("Русский", "ru"),
        ("Polski", "pl"),
        ("Italiano", "it"),
        ("Español", "es"),
        ("Deutsch", "de"),
        ("Français", "fr"),
    ]
    builder = InlineKeyboardBuilder()
    for title, code in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"save_{lang_type}:{code}"))
    builder.row(InlineKeyboardButton(text="✏️ Ввести вручную (код IANA)", callback_data=f"manual_{lang_type}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад в настройки", callback_data="open_settings"))
    return builder.as_markup()
