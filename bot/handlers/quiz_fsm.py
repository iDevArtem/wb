import html
import io
import logging
import random
from datetime import datetime, timezone
from typing import Any
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from bson import ObjectId

from bot.core.database import get_words_collection
from bot.keyboards.inline import (
    get_quiz_control_keyboard,
    get_quiz_next_keyboard,
    get_quiz_options_keyboard,
)
from bot.models.base import utc_now
from bot.models.user import User
from bot.models.word import Word
from bot.services.gemini_service import (
    GeminiQuotaExhaustedError,
    GeminiServiceError,
    gemini_service,
)
from bot.services.srs_service import SRSService
from bot.services.tts_service import tts_service

logger = logging.getLogger(__name__)

router = Router(name="quiz_fsm")


class QuizState(StatesGroup):
    answering = State()


BACKUP_DISTRACTORS = [
    "достижение", "исследование", "возможность", "препятствие",
    "намерение", "решение", "соглашение", "развитие", "внимание",
    "ответственность", "впечатление", "сравнение", "отношение",
    "улучшение", "вдохновение", "воображение", "любопытство",
]


def _word_query_by_id(word_id_str: str, user_id: int) -> dict:
    query: dict = {"user_id": user_id}
    if ObjectId.is_valid(word_id_str):
        query["_id"] = ObjectId(word_id_str)
    else:
        query["_id"] = word_id_str
    return query


async def fetch_distractors(
    user_id: int,
    correct_translation: str,
    count: int = 3,
) -> list[str]:
    words_col = get_words_collection()
    cursor = words_col.find(
        {"user_id": user_id, "translation": {"$ne": correct_translation}},
        {"translation": 1},
    ).limit(20)
    results = [doc.get("translation") async for doc in cursor if doc.get("translation")]
    unique_candidates = list({r for r in results if r and r != correct_translation})

    if len(unique_candidates) < count:
        for backup in BACKUP_DISTRACTORS:
            if backup != correct_translation and backup not in unique_candidates:
                unique_candidates.append(backup)
            if len(unique_candidates) >= count:
                break

    random.shuffle(unique_candidates)
    return unique_candidates[:count]


async def start_quiz_session(
    target_message: Message,
    user: User,
    state: FSMContext,
    only_word_id: str | int | None = None,
    allow_all: bool = False,
) -> None:
    now_utc = datetime.now(timezone.utc)
    words_col = get_words_collection()

    if only_word_id is not None:
        query = _word_query_by_id(str(only_word_id), user.id)
        doc = await words_col.find_one(query, {"_id": 1})
        word_ids = [str(doc["_id"])] if doc else []
    elif allow_all:
        cursor = words_col.find(
            {"user_id": user.id, "is_archived": False},
            {"_id": 1},
        ).sort("next_review_at", 1).limit(15)
        word_ids = [str(doc["_id"]) async for doc in cursor]
    else:
        cursor = words_col.find(
            {"user_id": user.id, "is_archived": False, "next_review_at": {"$lte": now_utc}},
            {"_id": 1},
        ).sort("next_review_at", 1).limit(20)
        word_ids = [str(doc["_id"]) async for doc in cursor]

    if not word_ids:
        # Check if user has any active words
        has_any = await words_col.find_one(
            {"user_id": user.id, "is_archived": False},
            {"_id": 1},
        )

        if not has_any:
            await target_message.answer(
                "📭 Твой словарь пуст!\n"
                "Отправь мне любое слово текстом или голосовым сообщением, чтобы начать учить.",
                parse_mode="HTML",
            )
            return

        await target_message.answer(
            "🎉 <b>Все слова на сегодня повторены!</b>\n\n"
            "Интервалы SuperMemo-2 защищают тебя от зубрежки. "
            "Но если ты хочешь потренироваться вне графика, отправь команду: /quiz_practice",
            parse_mode="HTML",
        )
        return

    # Store queue in FSM
    word_queue = list(word_ids)
    await state.update_data(
        queue=word_queue,
        total_session=len(word_queue),
        completed_session=0,
        correct_first_try=0,
    )

    await present_next_word(target_message, user, state)


async def present_next_word(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    queue: list[str] = data.get("queue", [])

    if not queue:
        completed = data.get("completed_session", 0)
        first_tries = data.get("correct_first_try", 0)
        await state.clear()
        await message.answer(
            f"🏁 <b>Квиз завершен!</b>\n\n"
            f"🎯 Повторено слов: <b>{completed}</b>\n"
            f"⭐ С первой попытки: <b>{first_tries}</b>\n\n"
            "Отличная работа для долгосрочной памяти! 🧠",
            parse_mode="HTML",
        )
        return

    current_word_id = queue[0]
    words_col = get_words_collection()
    query = _word_query_by_id(str(current_word_id), user.id)
    doc = await words_col.find_one(query)

    if not doc:
        # Word might have been deleted, skip
        queue.pop(0)
        await state.update_data(queue=queue)
        await present_next_word(message, user, state)
        return

    word = Word.model_validate(doc)

    # Pick a mode among: spelling, multiple_choice, listening, voice_mode
    modes = ["spelling", "multiple_choice", "listening", "voice_mode"]
    mode = random.choice(modes)

    # Prepare mode data
    options = []
    correct_idx = -1

    if mode == "multiple_choice":
        distractors = await fetch_distractors(user.id, word.translation, count=3)
        options = distractors + [word.translation]
        random.shuffle(options)
        correct_idx = options.index(word.translation)

    await state.set_state(QuizState.answering)
    await state.update_data(
        current_word_id=str(word.id),
        canonical_word=word.canonical_word,
        lemma=word.lemma,
        transcription=word.transcription,
        translation=word.translation,
        examples=word.examples,
        mode=mode,
        attempts_left=3,
        options=options,
        correct_idx=correct_idx,
    )

    # Deliver question according to mode
    if mode == "spelling":
        prompt_text = (
            "✍️ <b>Режим: Правописание (Spelling)</b>\n\n"
            f"Переведи на английский слово:\n"
            f"👉 <b>{html.escape(word.translation)}</b>\n\n"
            f"<i>Часть речи: {html.escape(word.pos)}</i>\n"
            "Напиши английское слово в ответном сообщении (3 попытки):"
        )
        await message.answer(prompt_text, reply_markup=get_quiz_control_keyboard(), parse_mode="HTML")

    elif mode == "multiple_choice":
        prompt_text = (
            "🧩 <b>Режим: Выбор перевода (Multiple Choice)</b>\n\n"
            f"Каков перевод слова:\n"
            f"👉 <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]?"
        )
        await message.answer(
            prompt_text,
            reply_markup=get_quiz_options_keyboard(options),
            parse_mode="HTML",
        )

    elif mode == "listening":
        prompt_text = (
            "🎧 <b>Режим: Аудирование (Listening)</b>\n\n"
            "Послушай произношение и напиши это слово на английском (или его русский перевод):"
        )
        try:
            audio = await tts_service.generate_audio(word.canonical_word)
            voice_file = BufferedInputFile(audio.getvalue(), filename="listening.mp3")
            await message.answer_voice(voice=voice_file, caption=prompt_text, parse_mode="HTML")
            await message.answer("Введи ответ:", reply_markup=get_quiz_control_keyboard())
        except Exception:
            # Fallback to spelling if TTS fails
            await message.answer(
                f"✍️ Напиши перевод слова <b>{html.escape(word.translation)}</b>:",
                reply_markup=get_quiz_control_keyboard(),
                parse_mode="HTML",
            )

    elif mode == "voice_mode":
        prompt_text = (
            "🗣 <b>Режим: Голосовое произношение (Voice Mode)</b>\n\n"
            f"Произнеси вслух в голосовом сообщении слово:\n"
            f"👉 <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]\n"
            f"<i>Значение: {html.escape(word.translation)}</i>\n\n"
            "Запиши войс (voice message) с произношением:"
        )
        await message.answer(prompt_text, reply_markup=get_quiz_control_keyboard(), parse_mode="HTML")


@router.message(Command("quiz"))
async def cmd_quiz(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await start_quiz_session(message, user, state, allow_all=False)


@router.message(Command("quiz_practice"))
async def cmd_quiz_practice(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await start_quiz_session(message, user, state, allow_all=True)


@router.callback_query(lambda c: c.data == "quiz_start_due")
async def cb_start_due_quiz(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await start_quiz_session(callback.message, user, state, allow_all=False)


@router.callback_query(lambda c: c.data and c.data.startswith("quiz_word:"))
async def cb_quiz_single_word(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    word_id_str = callback.data.split(":")[1]
    if callback.message:
        await start_quiz_session(callback.message, user, state, only_word_id=word_id_str)


@router.callback_query(QuizState.answering, lambda c: c.data and c.data.startswith("quiz_mc:"))
async def handle_mc_choice(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer()
    choice_idx = int(callback.data.split(":")[1])
    data = await state.get_data()

    correct_idx = data.get("correct_idx")
    word_id = data.get("current_word_id")
    canonical = data.get("canonical_word", "")
    attempts_left = data.get("attempts_left", 3)

    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None

    if choice_idx == correct_idx:
        # Success!
        await on_quiz_success(callback.message, word, attempts_left, state)
    else:
        # Multiple choice mistake
        attempts_left -= 1
        await state.update_data(attempts_left=attempts_left)

        if attempts_left > 0:
            hint = SRSService.get_attempt_1_hint(canonical)
            await callback.message.answer(
                f"❌ Неверно! Осталось попыток: {attempts_left}.\n"
                f"💡 Подсказка: {hint}",
                reply_markup=get_quiz_control_keyboard(),
                parse_mode="HTML",
            )
        else:
            await on_quiz_failure(callback.message, word, state)


@router.message(QuizState.answering, F.voice)
async def handle_quiz_voice_answer(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    word_id = data.get("current_word_id")
    canonical = data.get("canonical_word", "")
    lemma = data.get("lemma", "")
    attempts_left = data.get("attempts_left", 3)

    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None

    status_msg = await message.answer("🎙 <i>Слушаю твой ответ...</i>", parse_mode="HTML")

    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_stream = io.BytesIO()
        await bot.download_file(voice_file.file_path, destination=voice_stream)
        audio_bytes = voice_stream.getvalue()

        eval_result = await gemini_service.evaluate_quiz_voice(
            audio_bytes=audio_bytes,
            target_canonical=canonical,
            target_lemma=lemma,
        )

        await status_msg.delete()

        if eval_result.is_correct:
            await message.answer(
                f"🎉 <b>Отличное произношение!</b>\n"
                f"Ты сказал: «{html.escape(eval_result.transcribed_text)}»\n"
                f"💬 {html.escape(eval_result.feedback)}",
                parse_mode="HTML",
            )
            await on_quiz_success(message, word, attempts_left, state)
        else:
            attempts_left -= 1
            await state.update_data(attempts_left=attempts_left)
            await message.answer(
                f"Не совсем точно. Распознано: «{html.escape(eval_result.transcribed_text)}»\n"
                f"💡 {html.escape(eval_result.feedback)}\n"
                f"Осталось попыток: {attempts_left}",
                reply_markup=get_quiz_control_keyboard(),
                parse_mode="HTML",
            )
            if attempts_left <= 0:
                await on_quiz_failure(message, word, state)

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during quiz voice evaluation")
        await status_msg.edit_text(
            "⏳ <b>Сервис ИИ временно перегружен</b> (исчерпан дневной лимит запросов к моделям).\n\n"
            "Пожалуйста, повторите голосовой ответ через минуту или введите слово текстом.",
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error evaluating quiz voice")
        await status_msg.edit_text(
            "⚠️ Не удалось проверить произношение с помощью ИИ. Попробуйте записать еще раз.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error evaluating quiz voice")
        await status_msg.edit_text(
            "⚠️ Произошла ошибка при проверке голосового ответа. Попробуйте еще раз.",
            parse_mode="HTML",
        )


@router.message(QuizState.answering, F.text, ~F.text.startswith("/"))
async def handle_quiz_text_answer(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    word_id = data.get("current_word_id")
    canonical = data.get("canonical_word", "")
    lemma = data.get("lemma", "")
    translation = data.get("translation", "")
    examples = data.get("examples", [])
    mode = data.get("mode", "spelling")
    attempts_left = data.get("attempts_left", 3)

    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None

    user_text = message.text.strip()
    is_correct = SRSService.is_answer_correct(
        user_input=user_text,
        canonical_word=canonical,
        lemma=lemma,
        translation=translation,
        allow_translation=(mode == "listening"),
    )

    if is_correct:
        await on_quiz_success(message, word, attempts_left, state)
    else:
        attempts_left -= 1
        await state.update_data(attempts_left=attempts_left)

        if attempts_left == 2:
            # Hint 1: First letter + blanks
            hint = SRSService.get_attempt_1_hint(canonical)
            await message.answer(
                f"❌ Неверно!\n\n"
                f"💡 <b>Подсказка 1:</b> {hint}\n"
                "Осталось 2 попытки. Попробуй еще раз:",
                reply_markup=get_quiz_control_keyboard(),
                parse_mode="HTML",
            )
        elif attempts_left == 1:
            # Hint 2: Example sentence with blank
            hint = SRSService.get_attempt_2_hint(canonical, lemma, examples)
            await message.answer(
                f"❌ Снова не то!\n\n"
                f"💡 <b>Подсказка 2 (контекст):</b>\n{hint}\n\n"
                "Осталась последняя попытка:",
                reply_markup=get_quiz_control_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Attempt 3 failed -> Exhausted
            await on_quiz_failure(message, word, state)


async def on_quiz_success(
    message: Message,
    word: Word | None,
    attempts_left: int,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    completed = data.get("completed_session", 0) + 1
    first_tries = data.get("correct_first_try", 0) + (1 if attempts_left == 3 else 0)

    queue: list[str] = data.get("queue", [])
    if queue and word and queue[0] == str(word.id):
        queue.pop(0)

    await state.update_data(
        queue=queue,
        completed_session=completed,
        correct_first_try=first_tries,
    )

    if word:
        srs_res = SRSService.calculate_sm2(
            repetition=word.repetition,
            interval=word.interval,
            ease_factor=word.ease_factor,
            is_success=True,
        )
        word.repetition = srs_res.repetition
        word.interval = srs_res.interval
        word.ease_factor = srs_res.ease_factor
        word.next_review_at = srs_res.next_review_at

        words_col = get_words_collection()
        query = _word_query_by_id(str(word.id), word.user_id)
        await words_col.update_one(
            query,
            {"$set": {
                "repetition": srs_res.repetition,
                "interval": srs_res.interval,
                "ease_factor": srs_res.ease_factor,
                "next_review_at": srs_res.next_review_at,
                "updated_at": utc_now(),
            }},
        )

        praise = "🌟 Великолепно с первой попытки!" if attempts_left == 3 else "👍 Правильно!"
        text = (
            f"🎉 <b>{praise}</b>\n\n"
            f"Слово: <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}] — {html.escape(word.translation)}\n"
            f"📈 Следующее повторение через: <b>{srs_res.interval}</b> дн. (шаг {srs_res.repetition})\n"
            f"Осталось в этой сессии: <b>{len(queue)}</b>"
        )
    else:
        text = f"🎉 <b>Правильно!</b> Осталось в этой сессии: <b>{len(queue)}</b>"

    await message.answer(text, reply_markup=get_quiz_next_keyboard(), parse_mode="HTML")


async def on_quiz_failure(
    message: Message,
    word: Word | None,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    completed = data.get("completed_session", 0) + 1
    queue: list[str] = data.get("queue", [])
    if queue and word and queue[0] == str(word.id):
        queue.pop(0)

    await state.update_data(
        queue=queue,
        completed_session=completed,
    )

    if word:
        srs_res = SRSService.calculate_sm2(
            repetition=word.repetition,
            interval=word.interval,
            ease_factor=word.ease_factor,
            is_success=False,
        )
        word.repetition = srs_res.repetition
        word.interval = srs_res.interval
        word.ease_factor = srs_res.ease_factor
        word.next_review_at = srs_res.next_review_at

        words_col = get_words_collection()
        query = _word_query_by_id(str(word.id), word.user_id)
        await words_col.update_one(
            query,
            {"$set": {
                "repetition": srs_res.repetition,
                "interval": srs_res.interval,
                "ease_factor": srs_res.ease_factor,
                "next_review_at": srs_res.next_review_at,
                "updated_at": utc_now(),
            }},
        )

        text = (
            "❌ <b>Все 3 попытки исчерпаны!</b>\n\n"
            f"Правильный ответ: <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]\n"
            f"Перевод: <b>{html.escape(word.translation)}</b>\n\n"
            "🔄 Интервал сброшен: слово вернется на повторение уже завтра (1 день).\n"
            f"Осталось в этой сессии: <b>{len(queue)}</b>"
        )
        await message.answer(text, reply_markup=get_quiz_next_keyboard(), parse_mode="HTML")

        # Send fresh pronunciation audio
        try:
            audio = await tts_service.generate_audio(word.canonical_word)
            voice_file = BufferedInputFile(audio.getvalue(), filename=f"{word.canonical_word}.mp3")
            await message.answer_voice(
                voice=voice_file,
                caption=f"🔊 Запомни произношение: <b>{html.escape(word.canonical_word)}</b>",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send pronunciation after failure")
    else:
        await message.answer(
            f"❌ Неверно. Осталось в этой сессии: <b>{len(queue)}</b>",
            reply_markup=get_quiz_next_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "quiz_skip")
async def cb_quiz_skip(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer("Слово пропущено")
    data = await state.get_data()
    word_id = data.get("current_word_id")
    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None
    await on_quiz_failure(callback.message, word, state)


@router.callback_query(lambda c: c.data == "quiz_next")
async def cb_quiz_next(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.message:
        await present_next_word(callback.message, user, state)


@router.callback_query(lambda c: c.data == "quiz_stop")
async def cb_quiz_stop(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    data = await state.get_data()
    completed = data.get("completed_session", 0)
    first_tries = data.get("correct_first_try", 0)
    await state.clear()
    if callback.message:
        await callback.message.answer(
            f"🛑 <b>Квиз завершен досрочно.</b>\n"
            f"Повторено слов: {completed} (с 1-й попытки: {first_tries}).",
            parse_mode="HTML",
        )

