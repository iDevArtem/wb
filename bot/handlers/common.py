from bot.core.i18n import t, TranslatedText
import html
import logging
import math
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, InputRichMessage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bson import ObjectId

from bot.core.config import settings
from bot.core.database import get_words_collection
from bot.keyboards.reply import get_main_menu_keyboard
from bot.keyboards.inline import (
    get_archive_item_keyboard,
    get_words_pagination_keyboard,
    get_setup_language_keyboard,
)
from bot.models.base import utc_now
from bot.models.user import User
from bot.models.word import Word

logger = logging.getLogger(__name__)

router = Router(name="common")


class SetupState(StatesGroup):
    choosing_native = State()
    choosing_custom_native = State()
    choosing_target = State()
    choosing_custom_target = State()

@router.message(CommandStart())
async def cmd_start(message: Message, user: User, state: FSMContext) -> None:
    current_state = await state.get_state()
    data = await state.get_data()
    last_start = data.get("last_start", 0)
    now = message.date.timestamp()
    
    if current_state == SetupState.choosing_native.state and (now - last_start) < 2:
        return
        
    await state.update_data(last_start=now)
    await state.set_state(SetupState.choosing_native)
    name = message.from_user.first_name or "друг"
    
    greeting = (
        f"👋 <b>Вітаю / Welcome / Добро пожаловать, {name}!</b>\n\n"
        "Я твій персональний AI-словник.\n"
        "I am your personal AI-dictionary.\n"
        "Я твой персональный AI-словарь."
    )
    await message.answer(greeting, parse_mode="HTML")
    
    prompt = (
        "Оберіть вашу рідну мову\n"
        "Choose your native language\n"
        "Выберите ваш родной язык"
    )
    await message.answer(
        prompt, 
        reply_markup=get_setup_language_keyboard("native", user.native_language), 
        parse_mode="HTML"
    )

@router.callback_query(lambda c: c.data and c.data.startswith("setup_native:"))
async def cb_setup_native(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    code = callback.data.split(":")[1]
    user.native_language = code
    from bot.core.database import get_users_collection
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"native_language": code}})
    
    await state.set_state(SetupState.choosing_target)
    await callback.message.edit_text(
        "<b>" + t(user.native_language, "🧠 Выбери язык, который хочешь выучить:") + "</b>",
        reply_markup=get_setup_language_keyboard("target", user.native_language),
        parse_mode="HTML"
    )

@router.callback_query(lambda c: c.data == "setup_manual_native")
async def cb_setup_manual_native(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(SetupState.choosing_custom_native)
    await callback.message.edit_text(t(user.native_language, "✏️ Введи код языка (например, ru, en, es):"))

@router.message(SetupState.choosing_custom_native, F.text)
async def handle_setup_custom_native(message: Message, user: User, state: FSMContext) -> None:
    code = message.text.strip().lower()[:5]
    user.native_language = code
    from bot.core.database import get_users_collection
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"native_language": code}})
    
    await state.set_state(SetupState.choosing_target)
    await message.answer(
        "<b>" + t(user.native_language, "🧠 Выбери язык, который хочешь выучить:") + "</b>",
        reply_markup=get_setup_language_keyboard("target", user.native_language),
        parse_mode="HTML"
    )

@router.callback_query(lambda c: c.data and c.data.startswith("setup_target:"))
async def cb_setup_target(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    code = callback.data.split(":")[1]
    await finalize_setup(callback.message, user, code, state)
    await callback.answer()

@router.callback_query(lambda c: c.data == "setup_manual_target")
async def cb_setup_manual_target(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(SetupState.choosing_custom_target)
    await callback.message.edit_text(t(user.native_language, "✏️ Введи код изучаемого языка (например, en, de):"))

@router.message(SetupState.choosing_custom_target, F.text)
async def handle_setup_custom_target(message: Message, user: User, state: FSMContext) -> None:
    code = message.text.strip().lower()[:5]
    await finalize_setup(message, user, code, state)

async def finalize_setup(message_obj: Message, user: User, target_code: str, state: FSMContext) -> None:
    user.target_language = target_code
    from bot.core.database import get_users_collection
    await get_users_collection().update_one({"tg_id": user.tg_id}, {"$set": {"target_language": target_code}})
    await state.clear()
    
    text = f"{t(user.native_language, 'Отправь мне прямо сейчас любое слово текстом или голосовым! 🚀')}"
    
    try:
        await message_obj.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
        
    await message_obj.answer(
        text, 
        parse_mode="HTML", 
        reply_markup=get_main_menu_keyboard(user.native_language)
    )


@router.message(Command("help"))
@router.message(TranslatedText("❓ Помощь"))
@router.message(F.text.in_({"❓", "❓\ufe0f"}))
async def cmd_help(message: Message, user: User) -> None:
    text = (
        "📖 <b>" + t(user.native_language, "Справочник возможностей бота:") + "</b>\n\n" + 
        "1️⃣ <b>" + t(user.native_language, "Добавление слов (Universal Input):") + "</b>\n" +
        t(user.native_language, "— Отправляй слова на родном или изучаемом языке.") + "\n" +
        t(user.native_language, "— Поддерживаются войсы (Telegram voice): я напрямую отправляю аудио в Gemini, распознаю произношение и формирую карточку.") + "\n" +
        t(user.native_language, "— Каждое слово озвучивается нейронным голосом Microsoft Edge TTS.") + "\n\n" +
        "2️⃣ <b>" + t(user.native_language, "Интервальные повторения (SM-2):") + "</b>\n" +
        t(user.native_language, "— Алгоритм SuperMemo-2 рассчитывает оптимальные дни для повторения (1 день, 6 дней, затем с коэффициентом легкости).") + "\n" +
        t(user.native_language, "— При ошибке интервал сбрасывается, чтобы закрепить материал.") + "\n\n" +
        "3️⃣ <b>" + t(user.native_language, "Квиз и проверка знаний (/quiz):") + "</b>\n" +
        t(user.native_language, "— Режимы: правописание (Spelling), множественный выбор (4 варианта), аудирование (Listening) и голосовой ответ (Voice Mode).") + "\n" +
        t(user.native_language, "— Доступно 3 попытки с интеллектуальными подсказками.") + "\n\n" +
        "4️⃣ <b>" + t(user.native_language, "Тихие часы:") + "</b>\n" +
        t(user.native_language, "— Напоминания приходят только в удобное для тебя время (по умолчанию с 10:00 до 21:00).") + "\n" +
        t(user.native_language, "— Настрой свой часовой пояс в /settings.")
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard(user.native_language))


@router.message(TranslatedText("📊 Статистика"))
@router.message(F.text.in_({"📊", "📊\ufe0f"}))
async def cmd_stats(message: Message, user: User) -> None:
    now_utc = datetime.now(timezone.utc)
    words_col = get_words_collection()

    total_words = await words_col.count_documents({"user_id": user.tg_id, "target_language": user.target_language, "native_language": user.native_language})
    active_words = await words_col.count_documents({"user_id": user.tg_id, "is_archived": False, "target_language": user.target_language, "native_language": user.native_language})
    archived_words = await words_col.count_documents({"user_id": user.tg_id, "is_archived": True, "target_language": user.target_language, "native_language": user.native_language})
    due_words = await words_col.count_documents({
        "user_id": user.tg_id,
        "is_archived": False,
        "next_review_at": {"$lte": now_utc},
        "target_language": user.target_language,
        "native_language": user.native_language,
    })

    avg_interval = 0.0
    if active_words > 0:
        pipeline = [
            {"$match": {"user_id": user.tg_id, "is_archived": False, "target_language": user.target_language, "native_language": user.native_language}},
            {"$group": {"_id": None, "avg_interval": {"$avg": "$interval"}}},
        ]
        cursor = await words_col.aggregate(pipeline)
        async for doc in cursor:
            avg_interval = float(doc.get("avg_interval", 0.0) or 0.0)

    text = (
        f"📊 <b>{t(user.native_language, 'Твой прогресс в изучении:')}</b>\n\n" +
        f"🔥 <b>{t(user.native_language, 'Текущий стрик:')}</b> {user.streak} {t(user.native_language, 'дн.')}\n" +
        f"📚 <b>{t(user.native_language, 'Всего слов в словаре:')}</b> {total_words}\n" +
        f"⚡ <b>{t(user.native_language, 'Слов на изучении:')}</b> {active_words}\n" +
        f"✅ <b>{t(user.native_language, 'Выучено (в архиве):')}</b> {archived_words}\n" +
        f"🧠 <b>{t(user.native_language, 'Готово к повторению сегодня:')}</b> {due_words}\n" +
        f"📈 <b>{t(user.native_language, 'Средний интервал памяти:')}</b> {avg_interval:.1f} {t(user.native_language, 'дн.')}\n\n" +
        f"🌍 <b>{t(user.native_language, 'Часовой пояс:')}</b> <code>{user.timezone}</code>\n" +
        f"🌙 <b>{t(user.native_language, 'Тихие часы:')}</b> {user.quiet_hours_start}:00 — {user.quiet_hours_end}:00\n\n" +
        (t(user.native_language, "💡 <i>Есть слова для повторения! Напиши /quiz, чтобы освежить память.</i>") if due_words > 0 else t(user.native_language, "🎉 <i>Все слова на сегодня повторены! Отличная работа!</i>"))
    )
    await message.answer(text, parse_mode="HTML")




@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


