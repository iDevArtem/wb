from bot.core.i18n import t
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.core.config import settings


def get_word_card_keyboard(word_id: int | str, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Inline keyboard for a newly added or inspected word card:
    [🗑 Удалить] [✅ Знаю (в архив)]
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "🗑 Удалить"),
            callback_data=f"delete_word:{word_id}",
        ),
        InlineKeyboardButton(
            text=t(lang, "✅ Знаю (в архив)"),
            callback_data=f"archive_word:{word_id}",
        ),
    )
    return builder.as_markup()



def get_quiz_options_keyboard(options: list[str], lang: str = "ru") -> InlineKeyboardMarkup:
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
        InlineKeyboardButton(text=t(lang, "⏭ Пропустить"), callback_data="quiz_skip"),
        InlineKeyboardButton(text=t(lang, "🛑 Завершить"), callback_data="quiz_stop"),
    )
    return builder.as_markup()


def get_quiz_control_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Controls during text/voice quiz: skip or stop.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, "⏭ Пропустить"), callback_data="quiz_skip"),
        InlineKeyboardButton(text=t(lang, "🛑 Завершить"), callback_data="quiz_stop"),
    )
    return builder.as_markup()


def get_quiz_next_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Buttons shown after word quiz resolution (success or 3 attempts exhausted).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, "➡️ Следующее слово"), callback_data="quiz_next"),
        InlineKeyboardButton(text=t(lang, "🛑 Завершить"), callback_data="quiz_stop"),
    )
    return builder.as_markup()


def get_scheduler_notification_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Keyboard for scheduler push notification.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "🧠 Начать квиз"),
            callback_data="quiz_start_due",
        ),
    )
    return builder.as_markup()


def get_archive_item_keyboard(word_id: int | str, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Button to restore an archived word.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "↩️ Вернуть в обучение"),
            callback_data=f"unarchive_word:{word_id}",
        ),
    )
    return builder.as_markup()


def get_settings_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Settings menu keyboard.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, "📚 Мои словари"), callback_data="my_dictionaries"),
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, "🗣 Родной язык"), callback_data="set_native_lang"),
        InlineKeyboardButton(text=t(lang, "🧠 Изучаемый язык"), callback_data="set_target_lang"),
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, "🌍 Выбрать часовой пояс"), callback_data="set_tz"),
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, "🌙 Настроить тихие часы"), callback_data="set_quiet"),
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, "🔙 Закрыть"), callback_data="dismiss"),
    )
    return builder.as_markup()


def get_timezone_presets_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Quick timezone preset buttons.
    """
    presets = [
        (t(lang, "Москва (UTC+3)"), "Europe/Moscow"),
        (t(lang, "Киев (UTC+2/3)"), "Europe/Kyiv"),
        (t(lang, "Лондон (UTC+0/1)"), "Europe/London"),
        (t(lang, "Нью-Йорк (UTC-5/4)"), "America/New_York"),
        (t(lang, "Алматы (UTC+5)"), "Asia/Almaty"),
        ("UTC (+0)", "UTC"),
    ]
    builder = InlineKeyboardBuilder()
    for title, tz in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"save_tz:{tz}"))
    builder.row(InlineKeyboardButton(text=t(lang, "✏️ Ввести вручную"), callback_data="manual_tz"))
    builder.row(InlineKeyboardButton(text=t(lang, "🔙 Назад в настройки"), callback_data="open_settings"))
    return builder.as_markup()


def get_quiet_hours_presets_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Quiet hours presets.
    """
    presets = [
        (t(lang, "🌙 21:00 — 10:00 (По умолчанию)"), "quiet:21:10"),
        ("🌙 22:00 — 09:00", "quiet:22:9"),
        ("🌙 23:00 — 08:00", "quiet:23:8"),
        (t(lang, "🔔 Без ограничений (всегда)"), "quiet:0:0"),
    ]
    builder = InlineKeyboardBuilder()
    for title, data in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=data))
    builder.row(InlineKeyboardButton(text=t(lang, "🔙 Назад в настройки"), callback_data="open_settings"))
    return builder.as_markup()


def get_words_pagination_keyboard(page: int, total_pages: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Pagination keyboard for /words list.
    """
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text=t(lang, "⬅️ Назад"), callback_data=f"words_page:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text=t(lang, "Вперед ➡️"), callback_data=f"words_page:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    if settings.webapp_url:
        builder.row(
            InlineKeyboardButton(
                text=t(lang, "🌐 Открыть веб-словарь (Mini App)"),
                web_app=WebAppInfo(url=settings.webapp_url),
            )
        )

    builder.row(
        InlineKeyboardButton(text=t(lang, "🧠 Повторить слова (/quiz)"), callback_data="quiz_start_due"),
        InlineKeyboardButton(text=t(lang, "🔙 Закрыть"), callback_data="dismiss"),
    )
    return builder.as_markup()


def get_start_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Keyboard for /start greeting with direct WebApp button."""
    builder = InlineKeyboardBuilder()
    if settings.webapp_url:
        builder.row(
            InlineKeyboardButton(
                text=t(lang, "📖 Открыть мой веб-словарь"),
                web_app=WebAppInfo(url=settings.webapp_url),
            )
        )
    return builder.as_markup()


def get_language_presets_keyboard(lang_type: str, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Quick language preset buttons.
    """
    presets = [
        (t(lang, "Українська"), "uk"),
        ("English", "en"),
        (t(lang, "Русский"), "ru"),
        ("Polski", "pl"),
        ("Italiano", "it"),
        ("Español", "es"),
        ("Deutsch", "de"),
        ("Français", "fr"),
    ]
    builder = InlineKeyboardBuilder()
    for title, code in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"save_{lang_type}:{code}"))
    builder.row(InlineKeyboardButton(text=t(lang, "✏️ Ввести вручную") + " (код IANA)", callback_data=f"manual_{lang_type}"))
    builder.row(InlineKeyboardButton(text=t(lang, "🔙 Назад в настройки"), callback_data="open_settings"))
    return builder.as_markup()

def get_setup_language_keyboard(lang_type: str, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Quick language preset buttons for the /start setup flow.
    """
    presets = [
        (t(lang, "Українська"), "uk"),
        ("English", "en"),
        (t(lang, "Русский"), "ru"),
        ("Polski", "pl"),
        ("Italiano", "it"),
        ("Español", "es"),
        ("Deutsch", "de"),
        ("Français", "fr"),
    ]
    builder = InlineKeyboardBuilder()
    for title, code in presets:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"setup_{lang_type}:{code}"))
    builder.row(InlineKeyboardButton(text=t(lang, "✏️ Ввести вручную") + " (код IANA)", callback_data=f"setup_manual_{lang_type}"))
    return builder.as_markup()
