import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery
from bot.models.user import User
from bot.core.database import get_words_collection, get_users_collection
from bot.models.base import utc_now
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)

router = Router(name="dictionaries")

@router.callback_query(lambda c: c.data == "my_dictionaries")
async def cb_my_dictionaries(callback: CallbackQuery, user: User) -> None:
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
    
    cursor = words_col.aggregate(pipeline)
    results = await cursor.to_list(length=100)
    
    builder = InlineKeyboardBuilder()
    
    if not results:
        text = "📭 У тебя пока нет словарей. Добавь первое слово, и словарь создастся автоматически!"
    else:
        text = "📚 <b>Твои словари:</b>\n<i>Выбери словарь, чтобы сделать его активным:</i>"
        for res in results:
            native = res["_id"].get("native_language", "ru")
            target = res["_id"].get("target_language", "en")
            count = res["count"]
            
            # Highlight active dictionary
            prefix = "✅ " if (native == user.native_language and target == user.target_language) else ""
            
            btn_text = f"{prefix}{target.upper()} (родной: {native.upper()}) — {count} слов"
            cb_data = f"switch_dict:{native}:{target}"
            builder.row(InlineKeyboardButton(text=btn_text, callback_data=cb_data))
            
    builder.row(InlineKeyboardButton(text="🔙 Назад в настройки", callback_data="open_settings"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("switch_dict:"))
async def cb_switch_dict(callback: CallbackQuery, user: User) -> None:
    _, native, target = callback.data.split(":")
    
    users_col = get_users_collection()
    await users_col.update_one(
        {"tg_id": user.tg_id},
        {"$set": {"native_language": native, "target_language": target, "updated_at": utc_now()}}
    )
    
    await callback.answer(f"✅ Выбран словарь: {target.upper()} (родной {native.upper()})", show_alert=True)
    
    # Refresh settings menu
    # Need to trigger cb_open_settings manually or just edit text directly.
    # We can just change callback.data to "open_settings" but aiogram won't re-route it automatically inside a handler.
    # It's better to recreate the text.
    user.native_language = native
    user.target_language = target
    
    text = (
        "⚙️ <b>Настройки профиля:</b>\n\n"
        f"🗣 <b>Родной язык:</b> <code>{user.native_language}</code>\n"
        f"🎯 <b>Изучаемый язык:</b> <code>{user.target_language}</code>\n"
        f"🌍 <b>Часовой пояс:</b> <code>{user.timezone}</code>\n"
        f"🌙 <b>Тихие часы:</b> с {user.quiet_hours_start}:00 до {user.quiet_hours_end}:00\n"
        f"<i>(Уведомления отправляются только днем с {user.quiet_hours_end}:00 до {user.quiet_hours_start}:00)</i>\n\n"
        "Выбери нужный пункт для изменения:"
    )
    from bot.keyboards.inline import get_settings_keyboard
    await callback.message.edit_text(text, reply_markup=get_settings_keyboard(), parse_mode="HTML")
