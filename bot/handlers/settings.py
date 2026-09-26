from bot.core.i18n import t, TranslatedText
import html
import logging
from zoneinfo import ZoneInfo
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.core.database import get_users_collection
from bot.keyboards.inline import (
    get_quiet_hours_presets_keyboard,
    get_language_presets_keyboard,
    get_settings_keyboard,
    get_timezone_presets_keyboard,
)
from bot.models.base import utc_now
from bot.models.user import User

logger = logging.getLogger(__name__)

router = Router(name="settings")


class SettingsState(StatesGroup):
    waiting_for_custom_tz = State()
    waiting_for_custom_native = State()
    waiting_for_custom_target = State()


@router.message(Command("settings"))
@router.message(TranslatedText("⚙️ Настройки"))
async def cmd_settings(message: Message, user: User) -> None:
    text = (
        f"⚙️ <b>{t(user.native_language, 'Настройки профиля:')}</b>\n\n" +
        f"🗣 <b>{t(user.native_language, 'Родной язык:')}</b> <code>{user.native_language}</code>\n" +
        f"🎯 <b>{t(user.native_language, 'Изучаемый язык:')}</b> <code>{user.target_language}</code>\n" +
        f"🌍 <b>{t(user.native_language, 'Часовой пояс:')}</b> <code>{user.timezone}</code>\n" +
        f"🌙 <b>{t(user.native_language, 'Тихие часы:')}</b> {t(user.native_language, 'с')} {user.quiet_hours_start}:00 {t(user.native_language, 'до')} {user.quiet_hours_end}:00\n" +
        f"<i>({t(user.native_language, 'Уведомления отправляются только днем с')} {user.quiet_hours_end}:00 {t(user.native_language, 'до')} {user.quiet_hours_start}:00)</i>\n\n" +
        t(user.native_language, "Выбери нужный пункт для изменения:")
    )
    await message.answer(text, reply_markup=get_settings_keyboard(user.native_language), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "open_settings")
async def cb_open_settings(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    text = (
        f"⚙️ <b>{t(user.native_language, 'Настройки профиля:')}</b>\n\n" +
        f"🗣 <b>{t(user.native_language, 'Родной язык:')}</b> <code>{user.native_language}</code>\n" +
        f"🎯 <b>{t(user.native_language, 'Изучаемый язык:')}</b> <code>{user.target_language}</code>\n" +
        f"🌍 <b>{t(user.native_language, 'Часовой пояс:')}</b> <code>{user.timezone}</code>\n" +
        f"🌙 <b>{t(user.native_language, 'Тихие часы:')}</b> {t(user.native_language, 'с')} {user.quiet_hours_start}:00 {t(user.native_language, 'до')} {user.quiet_hours_end}:00\n\n" +
        t(user.native_language, "Выбери нужный пункт для изменения:")
    )
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=get_settings_keyboard(user.native_language),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "set_tz")
async def cb_set_timezone_menu(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🌍 <b>" + t(user.native_language, "Выбери свой часовой пояс из списка или нажми «Ввести вручную»:") + "</b>",
            reply_markup=get_timezone_presets_keyboard(user.native_language),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("save_tz:"))
async def cb_save_timezone(
    callback: CallbackQuery,
    user: User,
) -> None:
    tz_str = callback.data.split(":", 1)[1]
    try:
        ZoneInfo(tz_str)
        user.timezone = tz_str
        users_col = get_users_collection()
        await users_col.update_one(
            {"tg_id": user.tg_id},
            {"$set": {"timezone": tz_str, "updated_at": utc_now()}},
        )
        await callback.answer(t(user.native_language, "Часовой пояс обновлен!"))
        if callback.message:
            await callback.message.edit_text(
                f"✅ {t(user.native_language, 'Часовой пояс успешно изменен на:')} <code>{tz_str}</code>",
                reply_markup=get_settings_keyboard(user.native_language),
                parse_mode="HTML",
            )
    except Exception:
        await callback.answer(t(user.native_language, "Неверный часовой пояс"), show_alert=True)


@router.callback_query(lambda c: c.data == "manual_tz")
async def cb_manual_tz(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_custom_tz)
    if callback.message:
        await callback.message.answer(
            t(user.native_language, "✏️ Напиши название часового пояса в формате IANA (например, Europe/Kyiv, Europe/Warsaw, Asia/Tbilisi):"),
            parse_mode="HTML",
        )


@router.message(SettingsState.waiting_for_custom_tz, F.text)
async def handle_custom_tz_input(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    candidate_tz = message.text.strip()
    try:
        ZoneInfo(candidate_tz)
        user.timezone = candidate_tz
        users_col = get_users_collection()
        await users_col.update_one(
            {"tg_id": user.tg_id},
            {"$set": {"timezone": candidate_tz, "updated_at": utc_now()}},
        )
        await state.clear()
        await message.answer(
            f"✅ {t(user.native_language, 'Часовой пояс успешно сохранен:')} <code>{candidate_tz}</code>",
            reply_markup=get_settings_keyboard(user.native_language),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            f"❌ {t(user.native_language, 'Не удалось распознать часовой пояс')} «{html.escape(candidate_tz)}».\n" +
            t(user.native_language, "Пожалуйста, укажи валидный TZ из базы IANA (например: Europe/Berlin):"),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "set_quiet")
async def cb_set_quiet_menu(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🌙 <b>" + t(user.native_language, "Настройка тихих часов:") + "</b>\n\n" +
            t(user.native_language, "В указанный интервал бот не будет присылать напоминания о словах.") + "\n" +
            t(user.native_language, "Выбери удобный режим:"),
            reply_markup=get_quiet_hours_presets_keyboard(user.native_language),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("quiet:"))
async def cb_save_quiet_hours(
    callback: CallbackQuery,
    user: User,
) -> None:
    parts = callback.data.split(":")
    start_h = int(parts[1])
    end_h = int(parts[2])

    user.quiet_hours_start = start_h
    user.quiet_hours_end = end_h
    users_col = get_users_collection()
    await users_col.update_one(
        {"tg_id": user.tg_id},
        {"$set": {
            "quiet_hours_start": start_h,
            "quiet_hours_end": end_h,
            "updated_at": utc_now(),
        }},
    )

    await callback.answer(t(user.native_language, "Тихие часы обновлены!"))
    if callback.message:
        await callback.message.edit_text(
            f"✅ {t(user.native_language, 'Тихие часы сохранены: с')} {start_h}:00 {t(user.native_language, 'до')} {end_h}:00.",
            reply_markup=get_settings_keyboard(user.native_language),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "set_native_lang")
async def cb_set_native_menu(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🗣 <b>" + t(user.native_language, "Выбери свой родной язык:") + "</b>",
            reply_markup=get_language_presets_keyboard("native", user.native_language),
            parse_mode="HTML",
        )

@router.callback_query(lambda c: c.data == "set_target_lang")
async def cb_set_target_menu(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎯 <b>" + t(user.native_language, "Выбери язык, который хочешь выучить:") + "</b>\n" +
            "<i>" + t(user.native_language, "(Слова для разных языков хранятся раздельно)") + "</i>",
            reply_markup=get_language_presets_keyboard("target", user.native_language),
            parse_mode="HTML",
        )

@router.callback_query(lambda c: c.data and c.data.startswith("save_native:"))
async def cb_save_native(callback: CallbackQuery, user: User) -> None:
    code = callback.data.split(":")[1]
    user.native_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"native_language": code}})
    await callback.answer(t(user.native_language, "Родной язык обновлен!"))
    if callback.message:
        await cb_open_settings(callback, user)

@router.callback_query(lambda c: c.data and c.data.startswith("save_target:"))
async def cb_save_target(callback: CallbackQuery, user: User) -> None:
    code = callback.data.split(":")[1]
    user.target_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"target_language": code}})
    await callback.answer(t(user.native_language, "Изучаемый язык обновлен!"))
    if callback.message:
        await cb_open_settings(callback, user)

@router.callback_query(lambda c: c.data == "manual_native")
async def cb_manual_native(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_custom_native)
    if callback.message:
        await callback.message.answer(t(user.native_language, "✏️ Введи код языка (например, ru, en, es):"))

@router.callback_query(lambda c: c.data == "manual_target")
async def cb_manual_target(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_custom_target)
    if callback.message:
        await callback.message.answer(t(user.native_language, "✏️ Введи код изучаемого языка (например, en, de):"))

@router.message(SettingsState.waiting_for_custom_native, F.text)
async def handle_custom_native_input(message: Message, user: User, state: FSMContext) -> None:
    code = message.text.strip().lower()[:5]
    user.native_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"native_language": code}})
    await state.clear()
    await message.answer(f"✅ {t(user.native_language, 'Родной язык сохранен:')} <code>{code}</code>", reply_markup=get_settings_keyboard(user.native_language), parse_mode="HTML")

@router.message(SettingsState.waiting_for_custom_target, F.text)
async def handle_custom_target_input(message: Message, user: User, state: FSMContext) -> None:
    code = message.text.strip().lower()[:5]
    user.target_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"target_language": code}})
    await state.clear()
    await message.answer(f"✅ {t(user.native_language, 'Изучаемый язык сохранен:')} <code>{code}</code>", reply_markup=get_settings_keyboard(user.native_language), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "my_dictionaries")
async def cb_my_dictionaries(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    
    from bot.core.database import get_words_collection
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    words_col = get_words_collection()
    
    # Aggregation to find all combinations of native_language and target_language for this user
    pipeline = [
        {"$match": {"user_id": user.id}},
        {
            "$group": {
                "_id": {
                    "native_language": "$native_language",
                    "target_language": "$target_language"
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"count": -1}}
    ]
    
    cursor = await words_col.aggregate(pipeline)
    results = await cursor.to_list(length=100)
    
    builder = InlineKeyboardBuilder()
    
    if not results:
        text = t(user.native_language, "📭 У тебя пока нет словарей. Добавь первое слово, и словарь создастся автоматически!")
    else:
        text = "📚 <b>" + t(user.native_language, "Твои словари:") + "</b>\n<i>" + t(user.native_language, "Выбери словарь, чтобы сделать его активным:") + "</i>"
        for res in results:
            native = res["_id"].get("native_language", "ru")
            target = res["_id"].get("target_language", "en")
            count = res["count"]
            
            prefix = "✅ " if (native == user.native_language and target == user.target_language) else ""
            btn_text = f"{prefix}{target.upper()} ({t(user.native_language, 'родной')}: {native.upper()}) — {count} {t(user.native_language, 'слов')}"
            cb_data = f"switch_dict:{native}:{target}"
            builder.row(InlineKeyboardButton(text=btn_text, callback_data=cb_data))
            
    builder.row(InlineKeyboardButton(text=t(user.native_language, "🔙 Назад в настройки"), callback_data="open_settings"))
    
    if callback.message:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("switch_dict:"))
async def cb_switch_dict(callback: CallbackQuery, user: User) -> None:
    _, native, target = callback.data.split(":")
    
    from bot.core.database import get_users_collection
    from bot.models.base import utc_now
    
    users_col = get_users_collection()
    await users_col.update_one(
        {"tg_id": user.tg_id},
        {"$set": {"native_language": native, "target_language": target, "updated_at": utc_now()}}
    )
    
    await callback.answer(f"✅ {t(user.native_language, 'Выбран словарь:')} {target.upper()} ({t(user.native_language, '(родной')} {native.upper()})", show_alert=True)
    
    user.native_language = native
    user.target_language = target
    
    text = (
        f"⚙️ <b>{t(user.native_language, 'Настройки профиля:')}</b>\n\n" +
        f"🗣 <b>{t(user.native_language, 'Родной язык:')}</b> <code>{user.native_language}</code>\n" +
        f"🎯 <b>{t(user.native_language, 'Изучаемый язык:')}</b> <code>{user.target_language}</code>\n" +
        f"🌍 <b>{t(user.native_language, 'Часовой пояс:')}</b> <code>{user.timezone}</code>\n" +
        f"🌙 <b>{t(user.native_language, 'Тихие часы:')}</b> {t(user.native_language, 'с')} {user.quiet_hours_start}:00 {t(user.native_language, 'до')} {user.quiet_hours_end}:00\n" +
        f"<i>({t(user.native_language, 'Уведомления отправляются только днем с')} {user.quiet_hours_end}:00 {t(user.native_language, 'до')} {user.quiet_hours_start}:00)</i>\n\n" +
        t(user.native_language, "Выбери нужный пункт для изменения:")
    )
    from bot.keyboards.inline import get_settings_keyboard
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_settings_keyboard(user.native_language), parse_mode="HTML")
