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
@router.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: Message, user: User) -> None:
    text = (
        "⚙️ <b>Настройки профиля:</b>\n\n"
        f"🗣 <b>Родной язык:</b> <code>{user.native_language}</code>\n"
        f"🎯 <b>Изучаемый язык:</b> <code>{user.target_language}</code>\n"
        f"🌍 <b>Часовой пояс:</b> <code>{user.timezone}</code>\n"
        f"🌙 <b>Тихие часы:</b> с {user.quiet_hours_start}:00 до {user.quiet_hours_end}:00\n"
        f"<i>(Уведомления отправляются только днем с {user.quiet_hours_end}:00 до {user.quiet_hours_start}:00)</i>\n\n"
        "Выбери нужный пункт для изменения:"
    )
    await message.answer(text, reply_markup=get_settings_keyboard(), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "open_settings")
async def cb_open_settings(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    text = (
        "⚙️ <b>Настройки профиля:</b>\n\n"
        f"🗣 <b>Родной язык:</b> <code>{user.native_language}</code>\n"
        f"🎯 <b>Изучаемый язык:</b> <code>{user.target_language}</code>\n"
        f"🌍 <b>Часовой пояс:</b> <code>{user.timezone}</code>\n"
        f"🌙 <b>Тихие часы:</b> с {user.quiet_hours_start}:00 до {user.quiet_hours_end}:00\n\n"
        "Выбери нужный пункт для изменения:"
    )
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=get_settings_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "set_tz")
async def cb_set_timezone_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🌍 <b>Выбери свой часовой пояс</b> из списка или нажми «Ввести вручную»:",
            reply_markup=get_timezone_presets_keyboard(),
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
        await callback.answer("Часовой пояс обновлен!")
        if callback.message:
            await callback.message.edit_text(
                f"✅ Часовой пояс успешно изменен на: <code>{tz_str}</code>",
                reply_markup=get_settings_keyboard(),
                parse_mode="HTML",
            )
    except Exception:
        await callback.answer("Неверный часовой пояс", show_alert=True)


@router.callback_query(lambda c: c.data == "manual_tz")
async def cb_manual_tz(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_custom_tz)
    if callback.message:
        await callback.message.answer(
            "✏️ Напиши название часового пояса в формате IANA (например, <code>Europe/Kyiv</code>, "
            "<code>Europe/Warsaw</code>, <code>Asia/Tbilisi</code>):",
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
            f"✅ Часовой пояс успешно сохранен: <code>{candidate_tz}</code>",
            reply_markup=get_settings_keyboard(),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            f"❌ Не удалось распознать часовой пояс «{html.escape(candidate_tz)}».
"
            "Пожалуйста, укажи валидный TZ из базы IANA (например: <code>Europe/Berlin</code>):",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "set_quiet")
async def cb_set_quiet_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🌙 <b>Настройка тихих часов:</b>

"
            "В указанный интервал бот не будет присылать напоминания о словах.
"
            "Выбери удобный режим:",
            reply_markup=get_quiet_hours_presets_keyboard(),
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

    await callback.answer("Тихие часы обновлены!")
    if callback.message:
        await callback.message.edit_text(
            f"✅ Тихие часы сохранены: с {start_h}:00 до {end_h}:00.",
            reply_markup=get_settings_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "set_native_lang")
async def cb_set_native_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🗣 <b>Выбери свой родной язык:</b>",
            reply_markup=get_language_presets_keyboard("native"),
            parse_mode="HTML",
        )

@router.callback_query(lambda c: c.data == "set_target_lang")
async def cb_set_target_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎯 <b>Выбери язык, который хочешь выучить:</b>
"
            "<i>(Слова для разных языков хранятся раздельно)</i>",
            reply_markup=get_language_presets_keyboard("target"),
            parse_mode="HTML",
        )

@router.callback_query(lambda c: c.data and c.data.startswith("save_native:"))
async def cb_save_native(callback: CallbackQuery, user: User) -> None:
    code = callback.data.split(":")[1]
    user.native_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"native_language": code}})
    await callback.answer("Родной язык обновлен!")
    if callback.message:
        await cb_open_settings(callback, user)

@router.callback_query(lambda c: c.data and c.data.startswith("save_target:"))
async def cb_save_target(callback: CallbackQuery, user: User) -> None:
    code = callback.data.split(":")[1]
    user.target_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"target_language": code}})
    await callback.answer("Изучаемый язык обновлен!")
    if callback.message:
        await cb_open_settings(callback, user)

@router.callback_query(lambda c: c.data == "manual_native")
async def cb_manual_native(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_custom_native)
    if callback.message:
        await callback.message.answer("✏️ Введи код языка (например, ru, en, es):")

@router.callback_query(lambda c: c.data == "manual_target")
async def cb_manual_target(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_custom_target)
    if callback.message:
        await callback.message.answer("✏️ Введи код изучаемого языка (например, en, de):")

@router.message(SettingsState.waiting_for_custom_native, F.text)
async def handle_custom_native_input(message: Message, user: User, state: FSMContext) -> None:
    code = message.text.strip().lower()[:5]
    user.native_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"native_language": code}})
    await state.clear()
    await message.answer(f"✅ Родной язык сохранен: <code>{code}</code>", reply_markup=get_settings_keyboard(), parse_mode="HTML")

@router.message(SettingsState.waiting_for_custom_target, F.text)
async def handle_custom_target_input(message: Message, user: User, state: FSMContext) -> None:
    code = message.text.strip().lower()[:5]
    user.target_language = code
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"target_language": code}})
    await state.clear()
    await message.answer(f"✅ Изучаемый язык сохранен: <code>{code}</code>", reply_markup=get_settings_keyboard(), parse_mode="HTML")

