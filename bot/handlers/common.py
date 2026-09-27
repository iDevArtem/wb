from bot.core.i18n import t, TranslatedText
import html
import logging
import math
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bson import ObjectId

from bot.core.database import get_words_collection
from bot.keyboards.reply import get_main_menu_keyboard
from bot.keyboards.inline import (
    get_archive_item_keyboard,
    get_start_keyboard,
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
        "<b>" + t(user.native_language, "🎯 Выбери язык, который хочешь выучить:") + "</b>",
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
        "<b>" + t(user.native_language, "🎯 Выбери язык, который хочешь выучить:") + "</b>",
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
    
    text = (
        f"👋 {t(user.native_language, 'Привет')}, <b>{message_obj.chat.first_name or t(user.native_language, 'друг')}</b>!\n\n"
        f"{t(user.native_language, 'Отправь мне прямо сейчас любое слово текстом или голосовым! 🚀')}"
    )
    
    try:
        await message_obj.edit_text(text, reply_markup=get_start_keyboard(user.native_language), parse_mode="HTML")
    except Exception:
        await message_obj.answer(text, reply_markup=get_start_keyboard(user.native_language), parse_mode="HTML")
        
    try:
        await message_obj.answer(
            t(user.native_language, "Используй меню ниже для быстрой навигации 👇"), 
            reply_markup=get_main_menu_keyboard(user.native_language)
        )
    except Exception:
        pass


@router.message(Command("help"))
@router.message(TranslatedText("❓ Помощь"))
@router.message(F.text == "❓")
async def cmd_help(message: Message) -> None:
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
    await message.answer(text, parse_mode="HTML")


@router.message(Command("stats"))
@router.message(TranslatedText("📊 Статистика"))
@router.message(F.text == "📊")
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
        f"🎯 <b>{t(user.native_language, 'Готово к повторению сегодня:')}</b> {due_words}\n" +
        f"📈 <b>{t(user.native_language, 'Средний интервал памяти:')}</b> {avg_interval:.1f} {t(user.native_language, 'дн.')}\n\n" +
        f"🌍 <b>{t(user.native_language, 'Часовой пояс:')}</b> <code>{user.timezone}</code>\n" +
        f"🌙 <b>{t(user.native_language, 'Тихие часы:')}</b> {user.quiet_hours_start}:00 — {user.quiet_hours_end}:00\n\n" +
        (t(user.native_language, "💡 <i>Есть слова для повторения! Напиши /quiz, чтобы освежить память.</i>") if due_words > 0 else t(user.native_language, "🎉 <i>Все слова на сегодня повторены! Отличная работа!</i>"))
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("archive"))
@router.message(TranslatedText("📚 Изучено"))
@router.message(F.text == "📚")
async def cmd_archive(message: Message, user: User) -> None:
    words_col = get_words_collection()
    cursor = (
        words_col.find({"user_id": user.tg_id, "is_archived": True, "target_language": user.target_language, "native_language": user.native_language})
        .sort("updated_at", -1)
        .limit(10)
    )
    words = [Word.model_validate(doc) async for doc in cursor]

    if not words:
        await message.answer(
            t(user.native_language, "📭 Твой архив пока пуст. Когда ты освоишь слово и нажмешь «✅ Знаю (в архив)», оно появится здесь."),
            parse_mode="HTML",
        )
        return

    await message.answer(
        f"📦 <b>{t(user.native_language, 'Архив выученных слов (последние')} {len(words)}):</b>",
        parse_mode="HTML",
    )

    for w in words:
        item_text = (
            f"• <b>{w.canonical_word}</b> [{w.transcription}] — {w.translation}\n" + f"  <i>{t(user.native_language, 'Интервал памяти был:')} {w.interval} {t(user.native_language, 'дн.')}</i>"
        )
        await message.answer(
            item_text,
            reply_markup=get_archive_item_keyboard(w.id or "", user.native_language),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("unarchive_word:"))
async def cb_unarchive_word(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()

    query: dict = {"user_id": user.tg_id, "target_language": user.target_language, "native_language": user.native_language}
    if ObjectId.is_valid(word_id_str):
        query["_id"] = ObjectId(word_id_str)
    else:
        query["_id"] = word_id_str

    doc = await words_col.find_one_and_update(
        query,
        {"$set": {"is_archived": False, "updated_at": utc_now()}},
        return_document=True,
    )

    if not doc:
        await callback.answer(t(user.native_language, "Слово не найдено"), show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer(t(user.native_language, "Слово возвращено в активные повторения!"), show_alert=False)
    if callback.message:
        await callback.message.edit_text(
            f"↩️ {t(user.native_language, 'Слово')} <b>{word.canonical_word}</b> {t(user.native_language, 'возвращено в обучение!')}",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "dismiss")
async def cb_dismiss(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass


WORDS_PAGE_SIZE = 10


async def render_words_page(
    user: User,
    page: int = 1,
) -> tuple[str, InlineKeyboardMarkup | None]:
    now_utc = datetime.now(timezone.utc)
    words_col = get_words_collection()

    total_count = await words_col.count_documents({
        "user_id": user.tg_id,
        "is_archived": False,
        "target_language": user.target_language,
        "native_language": user.native_language,
    })

    if total_count == 0:
        return (
            "📭 <b>" + t(user.native_language, "Твой список слов пуст!") + "</b>\n\n" + t(user.native_language, "Отправь мне любое слово на изучаемом или родном языке текстом или голосовым сообщением, чтобы начать учить."),
            None,
        )

    total_pages = max(1, math.ceil(total_count / WORDS_PAGE_SIZE))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * WORDS_PAGE_SIZE

    cursor = (
        words_col.find({
            "user_id": user.tg_id,
            "is_archived": False,
            "target_language": user.target_language,
            "native_language": user.native_language,
        })
        .sort([("next_review_at", 1), ("_id", 1)])
        .skip(offset)
        .limit(WORDS_PAGE_SIZE)
    )
    words = [Word.model_validate(doc) async for doc in cursor]

    header = (
        f"📚 <b>{t(user.native_language, 'Слова на изучении')}</b>\n" + f"{t(user.native_language, 'Всего слов:')} <b>{total_count}</b> • {t(user.native_language, 'Страница')} <b>{page}</b> {t(user.native_language, 'из')} <b>{total_pages}</b>\n" +
        f"<i>{t(user.native_language, '(Сортировка: сначала слова, готовые к повторению)')}</i>\n\n"
    )

    rows = []
    for idx, w in enumerate(words, start=offset + 1):
        review_time = w.next_review_at
        if review_time.tzinfo is None:
            review_time = review_time.replace(tzinfo=timezone.utc)

        if review_time <= now_utc:
            status = "🔴 <b>" + t(user.native_language, "пора повторить!") + "</b>"
        else:
            diff = review_time - now_utc
            hours = int(diff.total_seconds() // 3600)
            if hours < 24:
                status = f"🟡 {t(user.native_language, 'через')} {max(1, hours)} {t(user.native_language, 'ч.')}"
            else:
                days = math.ceil(hours / 24)
                status = f"🟢 {t(user.native_language, 'через')} {days} {t(user.native_language, 'дн.')}"

        short_transl = w.translation.split(",")[0].strip()
        transcription_str = f" [{html.escape(w.transcription)}]" if w.transcription else ""
        rows.append(
            f"{idx}. <b>{html.escape(w.canonical_word)}</b>{transcription_str} — {html.escape(short_transl)}\n" + f"   ↳ ⏳ {w.interval} {t(user.native_language, 'дн.')} ({t(user.native_language, 'шаг')} {w.repetition}) • {status}"
        )

    text = header + "\n\n".join(rows)
    keyboard = get_words_pagination_keyboard(page, total_pages, user.native_language)
    return text, keyboard


@router.message(Command("words"))
@router.message(TranslatedText("📖 Мой словарь"))
@router.message(F.text == "📖")
async def cmd_words(message: Message, user: User) -> None:
    text, keyboard = await render_words_page(user, page=1)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("words_page:"))
async def cb_words_page(callback: CallbackQuery, user: User) -> None:
    page = int(callback.data.split(":")[1])
    text, keyboard = await render_words_page(user, page=page)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


