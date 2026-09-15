import html
import logging
import math
from datetime import datetime, timezone
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from bson import ObjectId

from bot.core.database import get_words_collection
from bot.keyboards.inline import (
    get_archive_item_keyboard,
    get_start_keyboard,
    get_words_pagination_keyboard,
)
from bot.models.base import utc_now
from bot.models.user import User
from bot.models.word import Word

logger = logging.getLogger(__name__)

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, user: User) -> None:
    text = (
        f"👋 Привет, <b>{message.from_user.first_name or 'друг'}</b>!\n\n"
        "Я твой персональный AI-репетитор английского языка с научной системой "
        "интервальных повторений <b>SuperMemo-2 (SM-2)</b>, нейронным произношением и искусственным интеллектом Gemini.\n\n"
        "✨ <b>Как добавлять слова:</b>\n"
        "• <b>Текст на русском/украинском:</b> напиши <code>вдохновение</code> — переведу в каноническое английское слово.\n"
        "• <b>Слово с опечаткой:</b> напиши <code>necesary</code> — исправлю на <i>necessary</i>.\n"
        "• <b>Грамматическая форма:</b> напиши <code>went</code> или <code>better</code> — приведу к словарной лемме <i>go</i> / <i>good</i>.\n"
        "• <b>Голосовое сообщение:</b> надиктуй слово в войс — Gemini распознает и разберет его!\n\n"
        "🧠 <b>Основные возможности:</b>\n"
        "• 📖 <b>Веб-словарь:</b> отслеживай все слова, прогресс и озвучку в Mini App!\n"
        "• /words — Список всех слов на изучении\n"
        "• /quiz — Начать интерактивную тренировку слов\n"
        "• /stats — Твоя статистика и стрик повторений\n"
        "• /archive — Слова, отправленные в архив\n"
        "• /settings — Настройка часового пояса и тихих часов\n\n"
        "Отправь мне прямо сейчас любое слово текстом или голосовым! 🚀"
    )
    await message.answer(text, reply_markup=get_start_keyboard(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "📖 <b>Справочник возможностей бота:</b>\n\n"
        "1️⃣ <b>Добавление слов (Universal Input):</b>\n"
        "— Отправляй слова на английском, русском или украинском.\n"
        "— Поддерживаются войсы (Telegram voice): я напрямую отправляю аудио в Gemini, "
        "распознаю произношение и формирую карточку.\n"
        "— Каждое слово озвучивается нейронным голосом Microsoft Edge TTS.\n\n"
        "2️⃣ <b>Интервальные повторения (SM-2):</b>\n"
        "— Алгоритм SuperMemo-2 рассчитывает оптимальные дни для повторения (1 день, 6 дней, затем с коэффициентом легкости).\n"
        "— При ошибке интервал сбрасывается, чтобы закрепить материал.\n\n"
        "3️⃣ <b>Квиз и проверка знаний (/quiz):</b>\n"
        "— Режимы: правописание (Spelling), множественный выбор (4 варианта), аудирование (Listening) и голосовой ответ (Voice Mode).\n"
        "— Доступно 3 попытки с интеллектуальными подсказками.\n\n"
        "4️⃣ <b>Тихие часы:</b>\n"
        "— Напоминания приходят только в удобное для тебя время (по умолчанию с 10:00 до 21:00).\n"
        "— Настрой свой часовой пояс в /settings."
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message, user: User) -> None:
    now_utc = datetime.now(timezone.utc)
    words_col = get_words_collection()

    total_words = await words_col.count_documents({"user_id": user.tg_id})
    active_words = await words_col.count_documents({"user_id": user.tg_id, "is_archived": False})
    archived_words = await words_col.count_documents({"user_id": user.tg_id, "is_archived": True})
    due_words = await words_col.count_documents({
        "user_id": user.tg_id,
        "is_archived": False,
        "next_review_at": {"$lte": now_utc},
    })

    avg_interval = 0.0
    if active_words > 0:
        pipeline = [
            {"$match": {"user_id": user.tg_id, "is_archived": False}},
            {"$group": {"_id": None, "avg_interval": {"$avg": "$interval"}}},
        ]
        cursor = await words_col.aggregate(pipeline)
        async for doc in cursor:
            avg_interval = float(doc.get("avg_interval", 0.0) or 0.0)

    text = (
        "📊 <b>Твой прогресс в изучении:</b>\n\n"
        f"🔥 <b>Текущий стрик:</b> {user.streak} дн.\n"
        f"📚 <b>Всего слов в словаре:</b> {total_words}\n"
        f"⚡ <b>Слов на изучении:</b> {active_words}\n"
        f"✅ <b>Выучено (в архиве):</b> {archived_words}\n"
        f"🎯 <b>Готово к повторению сегодня:</b> {due_words}\n"
        f"📈 <b>Средний интервал памяти:</b> {avg_interval:.1f} дн.\n\n"
        f"🌍 <b>Часовой пояс:</b> <code>{user.timezone}</code>\n"
        f"🌙 <b>Тихие часы:</b> {user.quiet_hours_start}:00 — {user.quiet_hours_end}:00\n\n"
        + ("💡 <i>Есть слова для повторения! Напиши /quiz, чтобы освежить память.</i>" if due_words > 0 else "🎉 <i>Все слова на сегодня повторены! Отличная работа!</i>")
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("archive"))
async def cmd_archive(message: Message, user: User) -> None:
    words_col = get_words_collection()
    cursor = (
        words_col.find({"user_id": user.tg_id, "is_archived": True})
        .sort("updated_at", -1)
        .limit(10)
    )
    words = [Word.model_validate(doc) async for doc in cursor]

    if not words:
        await message.answer(
            "📭 Твой архив пока пуст. Когда ты освоишь слово и нажмешь "
            "«✅ Знаю (в архив)», оно появится здесь.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        f"📦 <b>Архив выученных слов (последние {len(words)}):</b>",
        parse_mode="HTML",
    )

    for w in words:
        item_text = (
            f"• <b>{w.canonical_word}</b> [{w.transcription}] — {w.translation}\n"
            f"  <i>Интервал памяти был: {w.interval} дн.</i>"
        )
        await message.answer(
            item_text,
            reply_markup=get_archive_item_keyboard(w.id or ""),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("unarchive_word:"))
async def cb_unarchive_word(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()

    query: dict = {"user_id": user.tg_id}
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
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer("Слово возвращено в активные повторения!", show_alert=False)
    if callback.message:
        await callback.message.edit_text(
            f"↩️ Слово <b>{word.canonical_word}</b> возвращено в обучение!",
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
    user_id: int,
    page: int = 1,
) -> tuple[str, InlineKeyboardMarkup | None]:
    now_utc = datetime.now(timezone.utc)
    words_col = get_words_collection()

    total_count = await words_col.count_documents({
        "user_id": user_id,
        "is_archived": False,
    })

    if total_count == 0:
        return (
            "📭 <b>Твой список слов пуст!</b>\n\n"
            "Отправь мне любое английское или русское слово текстом или голосовым сообщением, чтобы начать учить.",
            None,
        )

    total_pages = max(1, math.ceil(total_count / WORDS_PAGE_SIZE))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * WORDS_PAGE_SIZE

    cursor = (
        words_col.find({
            "user_id": user_id,
            "is_archived": False,
        })
        .sort([("next_review_at", 1), ("_id", 1)])
        .skip(offset)
        .limit(WORDS_PAGE_SIZE)
    )
    words = [Word.model_validate(doc) async for doc in cursor]

    header = (
        f"📚 <b>Слова на изучении</b>\n"
        f"Всего слов: <b>{total_count}</b> • Страница <b>{page}</b> из <b>{total_pages}</b>\n"
        f"<i>(Сортировка: сначала слова, готовые к повторению)</i>\n\n"
    )

    rows = []
    for idx, w in enumerate(words, start=offset + 1):
        review_time = w.next_review_at
        if review_time.tzinfo is None:
            review_time = review_time.replace(tzinfo=timezone.utc)

        if review_time <= now_utc:
            status = "🔴 <b>пора повторить!</b>"
        else:
            diff = review_time - now_utc
            hours = int(diff.total_seconds() // 3600)
            if hours < 24:
                status = f"🟡 через {max(1, hours)} ч."
            else:
                days = math.ceil(hours / 24)
                status = f"🟢 через {days} дн."

        short_transl = w.translation.split(",")[0].strip()
        transcription_str = f" [{html.escape(w.transcription)}]" if w.transcription else ""
        rows.append(
            f"{idx}. <b>{html.escape(w.canonical_word)}</b>{transcription_str} — {html.escape(short_transl)}\n"
            f"   ↳ ⏳ {w.interval} дн. (шаг {w.repetition}) • {status}"
        )

    text = header + "\n\n".join(rows)
    keyboard = get_words_pagination_keyboard(page, total_pages)
    return text, keyboard


@router.message(Command("words"))
async def cmd_words(message: Message, user: User) -> None:
    text, keyboard = await render_words_page(user.id, page=1)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("words_page:"))
async def cb_words_page(callback: CallbackQuery, user: User) -> None:
    page = int(callback.data.split(":")[1])
    text, keyboard = await render_words_page(user.id, page=page)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


