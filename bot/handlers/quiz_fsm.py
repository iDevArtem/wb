from bot.core.i18n import t, TranslatedText
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
from aiogram.types import BufferedInputFile, CallbackQuery, Message, InputRichMessage, InputRichMessageMedia, InputMediaAudio
from aiogram.exceptions import TelegramBadRequest
from bson import ObjectId

from bot.core.database import get_words_collection, get_users_collection
from bot.keyboards.inline import (
    get_quiz_control_keyboard,
    get_quiz_next_keyboard,
    get_quiz_options_keyboard,
    get_quiz_conflict_keyboard,
)
from bot.models.base import utc_now
from bot.models.user import User
from bot.models.word import Word
from bot.scheduler.tasks import cleanup_user_reminder
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


async def is_quiz_in_progress(state: FSMContext) -> bool:
    """Check if the user is currently engaged in an active quiz session."""
    current_state = await state.get_state()
    if current_state != QuizState.answering.state:
        return False
    data = await state.get_data()
    queue = data.get("queue")
    return bool(queue and len(queue) > 0)


async def _is_valid_quiz_callback(callback: CallbackQuery, user: User, state: FSMContext) -> bool:
    """Validate that the callback originates from the active quiz message."""
    current_state = await state.get_state()
    if current_state != QuizState.answering.state:
        await callback.answer(t(user.native_language, "⚠️ Этот квиз уже недействителен."), show_alert=True)
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        return False

    data = await state.get_data()
    active_msg_id = data.get("quiz_msg_id")
    if not callback.message or (active_msg_id and callback.message.message_id != active_msg_id):
        await callback.answer(t(user.native_language, "⚠️ Этот квиз уже недействителен."), show_alert=True)
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        return False

    return True


async def clean_temp_messages(bot: Bot, chat_id: int, state: FSMContext):
    data = await state.get_data()
    temp_ids = data.get("temp_msg_ids", [])
    for msg_id in temp_ids:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
    await state.update_data(temp_msg_ids=[])

async def update_main_quiz_message(bot: Bot, chat_id: int, state: FSMContext, text: str | None = None, reply_markup=None, rich_message=None):
    data = await state.get_data()
    quiz_msg_id = data.get("quiz_msg_id")
    
    if quiz_msg_id:
        try:
            if rich_message:
                await bot.edit_message_text(text=None, chat_id=chat_id, message_id=quiz_msg_id, reply_markup=reply_markup, rich_message=rich_message)
            else:
                await bot.edit_message_text(text, chat_id=chat_id, message_id=quiz_msg_id, reply_markup=reply_markup, parse_mode="HTML")
            return
        except TelegramBadRequest as e:
            err = str(e).lower()
            if "message is not modified" in err:
                return
            # If not modified, just return. If not found or other, we will send new below.
            
    # Send new
    if rich_message:
        msg = await bot.send_rich_message(chat_id, rich_message, reply_markup=reply_markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    await state.update_data(quiz_msg_id=msg.message_id)

async def add_temp_message(state: FSMContext, msg_id: int):
    data = await state.get_data()
    temp_ids = data.get("temp_msg_ids", [])
    temp_ids.append(msg_id)
    await state.update_data(temp_msg_ids=temp_ids)

def get_backup_distractors(lang: str) -> list[str]:
    return [
        t(lang, "достижение"), t(lang, "исследование"), t(lang, "возможность"), t(lang, "препятствие"),
        t(lang, "намерение"), t(lang, "решение"), t(lang, "соглашение"), t(lang, "развитие"), t(lang, "внимание"),
        t(lang, "ответственность"), t(lang, "впечатление"), t(lang, "сравнение"), t(lang, "отношение"),
        t(lang, "улучшение"), t(lang, "вдохновение"), t(lang, "воображение"), t(lang, "любопытство"),
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
    target_lang: str,
    native_lang: str,
    count: int = 3,
) -> list[str]:
    words_col = get_words_collection()
    cursor = words_col.find(
        {"user_id": user_id, "target_language": target_lang, "native_language": native_lang, "translation": {"$ne": correct_translation}},
        {"translation": 1},
    ).limit(20)
    results = [doc.get("translation") async for doc in cursor if doc.get("translation")]
    unique_candidates = list({r for r in results if r and r != correct_translation})

    if len(unique_candidates) < count:
        for backup in get_backup_distractors(native_lang):
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
    edit_message_id: int | None = None,
) -> None:
    users_col = get_users_collection()
    if edit_message_id:
        await users_col.update_one({"tg_id": user.tg_id}, {"$unset": {"last_reminder_msg_id": ""}})
    else:
        await cleanup_user_reminder(target_message.bot, user.tg_id)

    now_utc = datetime.now(timezone.utc)
    words_col = get_words_collection()

    if only_word_id is not None:
        query = _word_query_by_id(str(only_word_id), user.id)
        doc = await words_col.find_one(query, {"_id": 1})
        word_ids = [str(doc["_id"])] if doc else []
    elif allow_all:
        cursor = words_col.find(
            {"user_id": user.id, "is_archived": False, "is_pending": {"$ne": True}, "target_language": user.target_language, "native_language": user.native_language},
            {"_id": 1},
        ).sort("next_review_at", 1).limit(15)
        word_ids = [str(doc["_id"]) async for doc in cursor]
    else:
        cursor = words_col.find(
            {"user_id": user.id, "is_archived": False, "is_pending": {"$ne": True}, "next_review_at": {"$lte": now_utc}, "target_language": user.target_language, "native_language": user.native_language},
            {"_id": 1},
        ).sort("next_review_at", 1).limit(20)
        word_ids = [str(doc["_id"]) async for doc in cursor]

    if not word_ids:
        # Check if user has any active words
        has_any = await words_col.find_one(
            {"user_id": user.id, "is_archived": False, "is_pending": {"$ne": True}, "target_language": user.target_language, "native_language": user.native_language},
            {"_id": 1},
        )

        if not has_any:
            # Check if user has archived words
            has_archived = await words_col.find_one(
                {"user_id": user.id, "is_archived": True, "is_pending": {"$ne": True}, "target_language": user.target_language, "native_language": user.native_language},
                {"_id": 1},
            )
            
            if has_archived:
                text = (
                    "📭 <b>" + t(user.native_language, "У тебя нет слов на изучении!") + "</b>\n" +
                    t(user.native_language, "Все твои добавленные слова уже выучены и находятся в архиве.") + "\n" +
                    t(user.native_language, "Отправь мне новое слово текстом или голосовым сообщением, чтобы продолжить обучение.")
                )
            else:
                text = (
                    "📭 " + t(user.native_language, "Твой словарь пуст!") + "\n" +
                    t(user.native_language, "Отправь мне любое слово текстом или голосовым сообщением, чтобы начать учить.")
                )
            if edit_message_id:
                try:
                            await target_message.bot.edit_message_text(text, chat_id=target_message.chat.id, message_id=edit_message_id, parse_mode="HTML")
                except TelegramBadRequest:
                    await target_message.answer(text, parse_mode="HTML")
            else:
                await target_message.answer(text, parse_mode="HTML")
            return

        text = (
            "🎉 <b>" + t(user.native_language, "Все слова на сегодня повторены!") + "</b>\n\n" +
            t(user.native_language, "Интервалы SuperMemo-2 защищают тебя от зубрежки. ") +
            t(user.native_language, "Но если ты хочешь потренироваться вне графика, отправь команду: /quiz_practice")
        )
        if edit_message_id:
            try:
                    await target_message.bot.edit_message_text(text, chat_id=target_message.chat.id, message_id=edit_message_id, parse_mode="HTML")
            except TelegramBadRequest:
                await target_message.answer(text, parse_mode="HTML")
        else:
            await target_message.answer(text, parse_mode="HTML")
        return

    # Store queue in FSM
    word_queue = list(word_ids)
    await state.update_data(
        queue=word_queue,
        total_session=len(word_queue),
        completed_session=0,
        correct_first_try=0,
        reviewed_words_list=[],
        temp_msg_ids=[],
        quiz_msg_id=edit_message_id,
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
        reviewed_words = data.get("reviewed_words_list", [])
        words_list_text = "\n".join(reviewed_words) if reviewed_words else t(user.native_language, "Нет слов")
        
        text = (
            f"🏁 <b>{t(user.native_language, 'Квиз завершен!')}</b>\n\n" +
            f"🧠 {t(user.native_language, 'Повторено слов:')} <b>{completed}</b>\n"
            f"⭐ {t(user.native_language, 'С первой попытки:')} <b>{first_tries}</b>\n\n" +
            f"📝 <b>{t(user.native_language, 'Пройденные слова:')}</b>\n{words_list_text}\n\n" +
            t(user.native_language, "Отличная работа для долгосрочной памяти! 🧠")
        )
        await clean_temp_messages(message.bot, message.chat.id, state)
        await update_main_quiz_message(message.bot, message.chat.id, state, text)
        await state.clear()
        return

    await clean_temp_messages(message.bot, message.chat.id, state)

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
        distractors = await fetch_distractors(user.id, word.translation, user.target_language, user.native_language, count=3)
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

    await _deliver_quiz_question(message, user, state, word, mode, options)


async def _deliver_quiz_question(
    message: Message,
    user: User,
    state: FSMContext,
    word: Word,
    mode: str,
    options: list[str],
) -> None:
    # Deliver question according to mode
    if mode == "spelling":
        prompt_text = (
            "✍️ <b>" + t(user.native_language, 'Режим: Правописание (Spelling)') + "</b>\n\n" +
            f"{t(user.native_language, 'Переведи на изучаемый язык слово:')}\n" +
            f"👉 <b>{html.escape(word.translation)}</b>\n\n" +
            f"<i>{t(user.native_language, 'Часть речи:')} {html.escape(word.pos)}</i>\n" +
            t(user.native_language, "Напиши слово на изучаемом языке в ответном сообщении (3 попытки):")
        )
        await update_main_quiz_message(message.bot, message.chat.id, state, prompt_text, reply_markup=get_quiz_control_keyboard(user.native_language))

    elif mode == "multiple_choice":
        prompt_text = (
            "🧩 <b>" + t(user.native_language, 'Режим: Выбор перевода (Multiple Choice)') + "</b><br/><br/>" +
            f"{t(user.native_language, 'Каков перевод слова:')}<br/>" +
            f"👉 <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]?<br/><br/>"
        )
        for idx, opt in enumerate(options):
            prompt_text += f'<tg-button-row><tg-button type="callback_data" data="quiz_mc:{idx}">{html.escape(opt)}</tg-button></tg-button-row>'
        
        rich_msg = InputRichMessage(html=prompt_text)
        await update_main_quiz_message(message.bot, message.chat.id, state, rich_message=rich_msg, reply_markup=get_quiz_control_keyboard(user.native_language))

    elif mode == "listening":
        prompt_text = (
            "🎧 <b>" + t(user.native_language, 'Режим: Аудирование (Listening)') + "</b><br/><br/>" +
            t(user.native_language, "Послушай произношение и напиши это слово (или его перевод):")
        )
        try:
            audio = await tts_service.generate_audio(word.canonical_word, target_lang=user.target_language)
            voice_file = BufferedInputFile(audio.getvalue(), filename="listening.mp3")
            
            media = InputRichMessageMedia(
                id="audio1",
                media=InputMediaAudio(
                    media=voice_file,
                    title=t(user.native_language, 'Аудирование'),
                    performer=t(user.target_language, 'Аудирование')
                )
            )
            rich_html = f'{prompt_text}<br/><br/><audio src="tg://audio?id=audio1"></audio><br/><br/>' + t(user.native_language, "Введи ответ:")
            rich_msg = InputRichMessage(
                html=rich_html,
                media=[media]
            )
            
            await update_main_quiz_message(message.bot, message.chat.id, state, rich_message=rich_msg, reply_markup=get_quiz_control_keyboard(user.native_language))
        except Exception:
            # Fallback to spelling if TTS fails
            await update_main_quiz_message(message.bot, message.chat.id, state, 
                f"✍️ {t(user.native_language, 'Напиши перевод слова')} <b>{html.escape(word.translation)}</b>:",
                reply_markup=get_quiz_control_keyboard(user.native_language)
            )

    elif mode == "voice_mode":
        prompt_text = (
            "🗣 <b>" + t(user.native_language, 'Режим: Голосовое произношение (Voice Mode)') + "</b>\n\n" +
            f"{t(user.native_language, 'Произнеси вслух в голосовом сообщении слово:')}\n" +
            f"👉 <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]\n" +
            f"<i>{t(user.native_language, 'Значение:')} {html.escape(word.translation)}</i>\n\n" +
            t(user.native_language, "Запиши войс (voice message) с произношением:")
        )
        await update_main_quiz_message(message.bot, message.chat.id, state, prompt_text, reply_markup=get_quiz_control_keyboard(user.native_language))


@router.message(Command("quiz"))
@router.message(TranslatedText("🧠 Учить"))
@router.message(F.text.in_({"🧠", "🧠\ufe0f"}))
async def cmd_quiz(message: Message, user: User, state: FSMContext) -> None:
    if await is_quiz_in_progress(state):
        text = (
            "⚠️ <b>" + t(user.native_language, "У тебя уже идет квиз!") + "</b>\n\n" +
            t(user.native_language, "Закончи предыдущий квиз или сбрось его, чтобы начать заново.")
        )
        await message.answer(text, reply_markup=get_quiz_conflict_keyboard(user.native_language, restart_data="quiz_restart:due"), parse_mode="HTML")
        return
    await state.clear()
    await cleanup_user_reminder(message.bot, user.tg_id)
    await start_quiz_session(message, user, state, allow_all=False)


@router.message(Command("quiz_practice"))
async def cmd_quiz_practice(message: Message, user: User, state: FSMContext) -> None:
    if await is_quiz_in_progress(state):
        text = (
            "⚠️ <b>" + t(user.native_language, "У тебя уже идет квиз!") + "</b>\n\n" +
            t(user.native_language, "Закончи предыдущий квиз или сбрось его, чтобы начать заново.")
        )
        await message.answer(text, reply_markup=get_quiz_conflict_keyboard(user.native_language, restart_data="quiz_restart:practice"), parse_mode="HTML")
        return
    await state.clear()
    await cleanup_user_reminder(message.bot, user.tg_id)
    await start_quiz_session(message, user, state, allow_all=True)


@router.callback_query(lambda c: c.data == "quiz_start_due")
async def cb_start_due_quiz(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    if await is_quiz_in_progress(state):
        text = (
            "⚠️ <b>" + t(user.native_language, "У тебя уже идет квиз!") + "</b>\n\n" +
            t(user.native_language, "Закончи предыдущий квиз или сбрось его, чтобы начать заново.")
        )
        await callback.message.edit_text(text, reply_markup=get_quiz_conflict_keyboard(user.native_language, restart_data="quiz_restart:due"), parse_mode="HTML")
        return
    await start_quiz_session(callback.message, user, state, allow_all=False, edit_message_id=callback.message.message_id)


@router.callback_query(lambda c: c.data and c.data.startswith("quiz_word:"))
async def cb_quiz_single_word(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    word_id_str = callback.data.split(":")[1]
    if await is_quiz_in_progress(state):
        text = (
            "⚠️ <b>" + t(user.native_language, "У тебя уже идет квиз!") + "</b>\n\n" +
            t(user.native_language, "Закончи предыдущий квиз или сбрось его, чтобы начать заново.")
        )
        await callback.message.edit_text(text, reply_markup=get_quiz_conflict_keyboard(user.native_language, restart_data=f"quiz_restart:word:{word_id_str}"), parse_mode="HTML")
        return
    await start_quiz_session(callback.message, user, state, only_word_id=word_id_str, edit_message_id=callback.message.message_id)


@router.callback_query(lambda c: c.data and c.data.startswith("quiz_mc:"))
async def handle_mc_choice(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not await _is_valid_quiz_callback(callback, user, state):
        return
    await callback.answer()
    choice_idx = int(callback.data.split(":")[1])
    data = await state.get_data()

    correct_idx = data.get("correct_idx")
    word_id = data.get("current_word_id")
    canonical = data.get("canonical_word", "")
    options = data.get("options", [])
    attempts_left = data.get("attempts_left", 3)

    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None

    if choice_idx == correct_idx:
        # Success!
        await on_quiz_success(callback.message, user, word, attempts_left, state)
    else:
        # Multiple choice mistake
        attempts_left -= 1
        await state.update_data(attempts_left=attempts_left)

        if attempts_left > 0:
            hint = SRSService.get_attempt_1_hint(canonical, user.native_language)
            prompt_text = (
                f"❌ {t(user.native_language, 'Неверно! Осталось попыток:')} {attempts_left}.<br/>" +
                f"💡 {t(user.native_language, 'Подсказка:')} {hint}<br/><br/>"
            )
            for idx, opt in enumerate(options):
                prompt_text += f'<tg-button-row><tg-button type="callback_data" data="quiz_mc:{idx}">{html.escape(opt)}</tg-button></tg-button-row>'
            
                rich_msg = InputRichMessage(html=prompt_text)
            await update_main_quiz_message(callback.bot, callback.message.chat.id, state, rich_message=rich_msg, reply_markup=get_quiz_control_keyboard(user.native_language))
        else:
            await on_quiz_failure(callback.message, user, word, state)


@router.message(QuizState.answering, F.voice)
async def handle_quiz_voice_answer(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
) -> None:
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    word_id = data.get("current_word_id")
    if not word_id:
        msg = await message.answer(t(user.native_language, "Пожалуйста, нажми кнопку ниже:"))
        await add_temp_message(state, msg.message_id)
        return
    canonical = data.get("canonical_word", "")
    lemma = data.get("lemma", "")
    attempts_left = data.get("attempts_left", 3)

    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None

    await message.bot.send_chat_action(message.chat.id, "record_voice")

    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_stream = io.BytesIO()
        await bot.download_file(voice_file.file_path, destination=voice_stream)
        audio_bytes = voice_stream.getvalue()

        eval_result = await gemini_service.evaluate_quiz_voice(
            audio_bytes=audio_bytes,
            target_canonical=canonical,
            target_lemma=lemma,
            native_lang=user.native_language,
            target_lang=user.target_language,
        )


        if eval_result.is_correct:
            # We pass the feedback into a state variable so on_quiz_success can append it to the main message.
            # But simpler: just edit main message directly here, or pass to on_quiz_success.
            feedback_text = (
                f"🎉 <b>{t(user.native_language, 'Отличное произношение!')}</b>\n" +
                f"{t(user.native_language, 'Ты сказал:')} «{html.escape(eval_result.transcribed_text)}»\n"
                f"💬 {html.escape(eval_result.feedback)}\n\n"
            )
            await state.update_data(voice_feedback=feedback_text)
            await on_quiz_success(message, user, word, attempts_left, state)
        else:
            attempts_left -= 1
            await state.update_data(attempts_left=attempts_left)
            await update_main_quiz_message(message.bot, message.chat.id, state,
                f"{t(user.native_language, 'Не совсем точно. Распознано:')} «{html.escape(eval_result.transcribed_text)}»\n" +
                f"💡 {html.escape(eval_result.feedback)}\n"
                f"{t(user.native_language, 'Осталось попыток:')} {attempts_left}",
                reply_markup=get_quiz_control_keyboard(user.native_language)
            )
            if attempts_left <= 0:
                await on_quiz_failure(message, user, word, state)

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during quiz voice evaluation")
        await message.answer(
            "⏳ <b>" + t(user.native_language, "Сервис ИИ временно перегружен (исчерпан дневной лимит запросов к моделям).") + "</b>\n\n" +
            t(user.native_language, "Пожалуйста, повторите голосовой ответ через минуту или введите слово текстом."),
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error evaluating quiz voice")
        await message.answer(
            t(user.native_language, "⚠️ Не удалось проверить произношение с помощью ИИ. Попробуйте записать еще раз."),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error evaluating quiz voice")
        await message.answer(
            t(user.native_language, "⚠️ Произошла ошибка при проверке голосового ответа. Попробуйте еще раз."),
            parse_mode="HTML",
        )


@router.message(QuizState.answering, F.text, ~F.text.startswith("/"))
async def handle_quiz_text_answer(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    word_id = data.get("current_word_id")
    if not word_id:
        msg = await message.answer(t(user.native_language, "Пожалуйста, нажми кнопку ниже:"))
        await add_temp_message(state, msg.message_id)
        return
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
        await on_quiz_success(message, user, word, attempts_left, state)
    else:
        attempts_left -= 1
        await state.update_data(attempts_left=attempts_left)

        if attempts_left == 2:
            # Hint 1: First letter + blanks
            hint = SRSService.get_attempt_1_hint(canonical, user.native_language)
            await update_main_quiz_message(message.bot, message.chat.id, state,
                f"❌ {t(user.native_language, 'Неверно!')}\n\n" +
                f"💡 <b>{t(user.native_language, 'Подсказка 1:')}</b> {hint}\n" +
                t(user.native_language, "Осталось 2 попытки. Попробуй еще раз:"),
                reply_markup=get_quiz_control_keyboard(user.native_language)
            )
        elif attempts_left == 1:
            # Hint 2: Example sentence with blank
            hint = SRSService.get_attempt_2_hint(canonical, lemma, examples, user.native_language)
            await update_main_quiz_message(message.bot, message.chat.id, state,
                f"❌ {t(user.native_language, 'Снова не то!')}\n\n" +
                f"💡 <b>{t(user.native_language, 'Подсказка 2 (контекст):')}</b>\n{hint}\n\n" +
                t(user.native_language, "Осталась последняя попытка:"),
                reply_markup=get_quiz_control_keyboard(user.native_language)
            )
        else:
            # Attempt 3 failed -> Exhausted
            await on_quiz_failure(message, user, word, state)


async def on_quiz_success(
    message: Message,
    user: User,
    word: Word | None,
    attempts_left: int,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    completed = data.get("completed_session", 0) + 1
    reviewed = data.get("reviewed_words_list", [])
    if word:
        reviewed.append(f"• <b>{html.escape(word.canonical_word)}</b> — {html.escape(word.translation)}")

    first_tries = data.get("correct_first_try", 0) + (1 if attempts_left == 3 else 0)

    queue: list[str] = data.get("queue", [])
    if queue and word and queue[0] == str(word.id):
        queue.pop(0)

    # Clear current_word_id so stray text messages don't re-answer the same word
    await state.update_data(
        queue=queue,
        completed_session=completed,
        correct_first_try=first_tries,
        reviewed_words_list=reviewed,
        current_word_id="",
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

        praise = t(user.native_language, "🌟 Великолепно с первой попытки!") if attempts_left == 3 else t(user.native_language, "👍 Правильно!")
        voice_feedback = data.get("voice_feedback", "")
        text = (
            f"{voice_feedback}🎉 <b>{praise}</b>\n\n" +
            f"{t(user.native_language, 'Слово:')} <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}] — {html.escape(word.translation)}\n" +
            f"📈 {t(user.native_language, 'Следующее повторение через:')} <b>{srs_res.interval}</b> {t(user.native_language, 'дн.')} ({t(user.native_language, 'шаг')} {srs_res.repetition})\n" +
            f"{t(user.native_language, 'Осталось в этой сессии:')} <b>{len(queue)}</b>"
        )
    else:
        text = f"🎉 <b>{t(user.native_language, 'Правильно!')}</b> {t(user.native_language, 'Осталось в этой сессии:')} <b>{len(queue)}</b>"

    # Clear voice_feedback if it was present
    if data.get("voice_feedback"):
        await state.update_data(voice_feedback="")
        
    if len(queue) > 0:
        await update_main_quiz_message(message.bot, message.chat.id, state, text, reply_markup=get_quiz_next_keyboard(user.native_language))
    else:
        await update_main_quiz_message(message.bot, message.chat.id, state, text)
        await present_next_word(message, user, state)


async def on_quiz_failure(
    message: Message,
    user: User,
    word: Word | None,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    completed = data.get("completed_session", 0) + 1
    reviewed = data.get("reviewed_words_list", [])
    if word:
        reviewed.append(f"• <b>{html.escape(word.canonical_word)}</b> — {html.escape(word.translation)}")

    queue: list[str] = data.get("queue", [])
    if queue and word and queue[0] == str(word.id):
        queue.pop(0)

    # Clear current_word_id so stray text messages don't re-answer the same word
    await state.update_data(
        queue=queue,
        completed_session=completed,
        reviewed_words_list=reviewed,
        current_word_id="",
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

        try:
            audio = await tts_service.generate_audio(word.canonical_word, target_lang=user.target_language)
            voice_file = BufferedInputFile(audio.getvalue(), filename=f"{word.canonical_word}.mp3")
            media = InputRichMessageMedia(
                id="audio_fail",
                media=InputMediaAudio(
                    media=voice_file,
                    title=word.canonical_word,
                    performer=t(user.native_language, 'Аудирование')
                )
            )
            text = (
                "❌ <b>" + t(user.native_language, "Все 3 попытки исчерпаны!") + "</b><br/><br/>" +
                f"{t(user.native_language, 'Правильный ответ:')} <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]<br/>" +
                f"{t(user.native_language, 'Перевод:')} <b>{html.escape(word.translation)}</b><br/><br/>" +
                '<audio src="tg://audio?id=audio_fail"></audio><br/><br/>' +
                "🔄 " + t(user.native_language, "Интервал сброшен: слово вернется на повторение уже завтра (1 день).") + "<br/>" +
                f"{t(user.native_language, 'Осталось в этой сессии:')} <b>{len(queue)}</b>"
            )
            rich_msg = InputRichMessage(html=text, media=[media])
            
            if len(queue) > 0:
                await update_main_quiz_message(message.bot, message.chat.id, state, rich_message=rich_msg, reply_markup=get_quiz_next_keyboard(user.native_language))
            else:
                await update_main_quiz_message(message.bot, message.chat.id, state, rich_message=rich_msg)
                
        except Exception:
            logger.exception("Failed to send pronunciation after failure")
            text = (
                "❌ <b>" + t(user.native_language, "Все 3 попытки исчерпаны!") + "</b><br/><br/>" +
                f"{t(user.native_language, 'Правильный ответ:')} <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]<br/>" +
                f"{t(user.native_language, 'Перевод:')} <b>{html.escape(word.translation)}</b><br/><br/>" +
                "🔄 " + t(user.native_language, "Интервал сброшен: слово вернется на повторение уже завтра (1 день).") + "<br/>" +
                f"{t(user.native_language, 'Осталось в этой сессии:')} <b>{len(queue)}</b>"
            )
            rich_msg = InputRichMessage(html=text)
            if len(queue) > 0:
                await update_main_quiz_message(message.bot, message.chat.id, state, rich_message=rich_msg, reply_markup=get_quiz_next_keyboard(user.native_language))
            else:
                await update_main_quiz_message(message.bot, message.chat.id, state, rich_message=rich_msg)

        # If queue is now empty, show quiz completion
        if len(queue) == 0:
            await present_next_word(message, user, state)
    else:
        await update_main_quiz_message(message.bot, message.chat.id, state,
            f"❌ {t(user.native_language, 'Неверно.')} {t(user.native_language, 'Осталось в этой сессии:')} <b>{len(queue)}</b>",
            reply_markup=get_quiz_next_keyboard(user.native_language)
        )
        if len(queue) == 0:
            await present_next_word(message, user, state)


@router.callback_query(lambda c: c.data == "quiz_skip")
async def cb_quiz_skip(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not await _is_valid_quiz_callback(callback, user, state):
        return
    await callback.answer(t(user.native_language, "Слово пропущено"))
    data = await state.get_data()
    word_id = data.get("current_word_id")
    words_col = get_words_collection()
    query = _word_query_by_id(str(word_id), user.id)
    doc = await words_col.find_one(query)
    word = Word.model_validate(doc) if doc else None
    await on_quiz_failure(callback.message, user, word, state)


@router.callback_query(lambda c: c.data == "quiz_next")
async def cb_quiz_next(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not await _is_valid_quiz_callback(callback, user, state):
        return
    await callback.answer()
    if callback.message:
        await present_next_word(callback.message, user, state)


@router.callback_query(lambda c: c.data == "quiz_stop")
async def cb_quiz_stop(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not await _is_valid_quiz_callback(callback, user, state):
        return
    await callback.answer()
    data = await state.get_data()
    completed = data.get("completed_session", 0)
    first_tries = data.get("correct_first_try", 0)
    reviewed_words = data.get("reviewed_words_list", [])
    words_list_text = "\n".join(reviewed_words) if reviewed_words else t(user.native_language, "Нет слов")
    
    if callback.message:
        text = (
            f"🛑 <b>{t(user.native_language, 'Квиз завершен досрочно.')}</b>\n" +
            f"{t(user.native_language, 'Повторено слов:')} {completed} ({t(user.native_language, 'с 1-й попытки:')} {first_tries}).\n\n" +
            f"📝 <b>{t(user.native_language, 'Пройденные слова:')}</b>\n{words_list_text}"
        )
        await clean_temp_messages(callback.bot, callback.message.chat.id, state)
        await update_main_quiz_message(callback.bot, callback.message.chat.id, state, text, reply_markup=None)
    await state.clear()


@router.callback_query(lambda c: c.data == "quiz_resume")
async def cb_quiz_resume(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer()
    if not callback.message:
        return

    data = await state.get_data()
    quiz_msg_id = data.get("quiz_msg_id")

    # If the conflict prompt was a separate message, delete it
    if callback.message.message_id != quiz_msg_id:
        try:
            await callback.message.delete()
        except Exception:
            pass

    current_word_id = data.get("current_word_id")
    if current_word_id:
        words_col = get_words_collection()
        query = _word_query_by_id(str(current_word_id), user.id)
        doc = await words_col.find_one(query)
        if doc:
            word = Word.model_validate(doc)
            mode = data.get("mode", "spelling")
            options = data.get("options", [])
            await _deliver_quiz_question(callback.message, user, state, word, mode, options)
            return

    await present_next_word(callback.message, user, state)


@router.callback_query(lambda c: c.data and c.data.startswith("quiz_restart"))
async def cb_quiz_restart(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer(t(user.native_language, "Квиз сброшен. Начинаем заново!"))
    if not callback.message:
        return

    data = await state.get_data()
    old_quiz_msg_id = data.get("quiz_msg_id")
    if old_quiz_msg_id and old_quiz_msg_id != callback.message.message_id:
        try:
            await callback.bot.edit_message_reply_markup(
                chat_id=callback.message.chat.id,
                message_id=old_quiz_msg_id,
                reply_markup=None,
            )
        except Exception:
            pass

    await clean_temp_messages(callback.bot, callback.message.chat.id, state)
    await state.clear()
    await cleanup_user_reminder(callback.bot, user.tg_id)

    restart_parts = callback.data.split(":")
    restart_type = restart_parts[1] if len(restart_parts) > 1 else "due"

    if restart_type == "practice":
        await start_quiz_session(callback.message, user, state, allow_all=True, edit_message_id=callback.message.message_id)
    elif restart_type == "word" and len(restart_parts) > 2:
        word_id = restart_parts[2]
        await start_quiz_session(callback.message, user, state, only_word_id=word_id, edit_message_id=callback.message.message_id)
    else:
        await start_quiz_session(callback.message, user, state, allow_all=False, edit_message_id=callback.message.message_id)

