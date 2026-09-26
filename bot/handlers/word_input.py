from bot.core.i18n import t, TranslatedText
import html
import io
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
import re
from bson import ObjectId
from bot.core.database import get_words_collection
from bot.models.base import utc_now

from bot.keyboards.inline import (
    get_duplicate_word_keyboard,
    get_word_card_keyboard,
)
from bot.models.user import User
from bot.models.word import Word
from bot.services.gemini_service import (
    GeminiQuotaExhaustedError,
    GeminiServiceError,
    WordAnalysis,
    gemini_service,
)
from bot.services.tts_service import tts_service

logger = logging.getLogger(__name__)

router = Router(name="word_input")


def format_word_card(analysis: WordAnalysis, lang: str = "ru") -> str:
    escaped_word = html.escape(analysis.canonical_word)
    escaped_pos = html.escape(analysis.pos)
    escaped_lemma = html.escape(analysis.lemma)
    escaped_transl = html.escape(analysis.translation)

    if analysis.transcription_uk and analysis.transcription_us and analysis.transcription_uk != analysis.transcription_us:
        trans_display = f"<code>{html.escape(analysis.transcription_uk)}</code> | <code>{html.escape(analysis.transcription_us)}</code>"
    else:
        raw_trans = analysis.transcription or analysis.transcription_us or analysis.transcription_uk or ""
        trans_display = f"[{html.escape(raw_trans)}]"

    typo_note = ""
    if analysis.corrected_from:
        escaped_typo = html.escape(analysis.corrected_from)
        typo_note = f"{t(lang, '✏️ Исправлена опечатка с:')} <s>{escaped_typo}</s>\n"

    # Compact layout requested by user
    lemma_note = ""
    if analysis.lemma.lower() != analysis.canonical_word.lower():
        lemma_note = f"\n{t(lang, '🌱 Словарная форма:')} <code>{escaped_lemma}</code>"

    level_display = f" • <b>{analysis.level}</b>" if getattr(analysis, "level", None) else ""
    
    definition_block = ""
    if getattr(analysis, "definition", None):
        definition_block = f"\n\n💡 <b>{t(lang, '💡 Смысл:')}</b> <i>{html.escape(analysis.definition)}</i>"
        
    grammar_block = ""
    grammar_notes = getattr(analysis, "grammar_notes", [])
    if grammar_notes:
        grammar_list = " • ".join(html.escape(n) for n in grammar_notes)
        grammar_block = f"\n📐 <b>{t(lang, '📐 Грамматика:')}</b> {grammar_list}"

    card = (
        f"📖 <b>{escaped_word}</b> <i>({escaped_pos})</i>{level_display}\n" + f"{typo_note}" +
        f"🗣 {trans_display}"
        f"{lemma_note}\n" + f"💬 <b>{escaped_transl}</b>" +
        f"{definition_block}"
        f"{grammar_block}"
    )
    return card


def _word_query_by_id(word_id_str: str, user: User) -> dict:
    query: dict = {"user_id": user.tg_id, "target_language": user.target_language, "native_language": user.native_language}
    if ObjectId.is_valid(word_id_str):
        query["_id"] = ObjectId(word_id_str)
    else:
        query["_id"] = word_id_str
    return query


async def check_existing_word(
    user: User,
    word_text: str,
) -> Word | None:
    norm = word_text.strip().lower()
    words_col = get_words_collection()
    pattern = f"^{re.escape(norm)}$"
    doc = await words_col.find_one({
        "user_id": user.tg_id, "target_language": user.target_language, "native_language": user.native_language,
        "is_archived": False,
        "$or": [
            {"canonical_word": {"$regex": pattern, "$options": "i"}},
            {"lemma": {"$regex": pattern, "$options": "i"}},
        ],
    })
    return Word.model_validate(doc) if doc else None


@router.message(F.voice)
async def handle_voice_input(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
) -> None:
    """
    Handle Telegram voice messages: download in-memory, pass to Gemini,
    extract structured WordAnalysis, synthesize pronunciation, and save.
    """
    current_state = await state.get_state()
    if current_state is not None and "quiz" in current_state.lower():
        # Delegate to quiz FSM handler if user is currently taking a quiz
        return

    if not message.voice:
        return

    await bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
    status_msg = await message.answer(t(user.native_language, '🎙 <i>Слушаю и анализирую произношение...</i>'), parse_mode="HTML")

    try:
        # Download voice directly into in-memory stream
        voice_file = await bot.get_file(message.voice.file_id)
        if not voice_file.file_path:
            await status_msg.edit_text(t(user.native_language, "❌ Не удалось загрузить голосовое сообщение из Telegram."))
            return

        voice_stream = io.BytesIO()
        await bot.download_file(voice_file.file_path, destination=voice_stream)
        audio_bytes = voice_stream.getvalue()

        # Send in-memory audio/ogg directly to Gemini
        analysis = await gemini_service.analyze_voice(
            audio_bytes=audio_bytes,
            mime_type="audio/ogg",
            native_lang=user.native_language,
            target_lang=user.target_language,
        )

        # Check duplicate
        existing = await check_existing_word(user, analysis.canonical_word)
        if not existing and analysis.lemma:
            existing = await check_existing_word(user, analysis.lemma)

        if existing:
            await status_msg.delete()
            text = (
                f"💡 Ты уже учишь слово <b>{html.escape(existing.canonical_word)}</b>!\n" + f"Интервал повторения: <b>{existing.interval}</b> дн.\n" + t(user.native_language, "Хочешь повторить прямо сейчас?")
            )
            await message.answer(
                text,
                reply_markup=get_duplicate_word_keyboard(existing.id or ""),
                parse_mode="HTML",
            )
            return

        # Synthesize audio with edge-tts in memory
        tts_audio = await tts_service.generate_audio(analysis.canonical_word, target_lang=user.target_language)

        # Save to DB
        new_word = Word(
            user_id=user.id,
            native_language=user.native_language,
            target_language=user.target_language,
            canonical_word=analysis.canonical_word,
            lemma=analysis.lemma,
            pos=analysis.pos,
            transcription=analysis.transcription,
            translation=analysis.translation,
            corrected_from=analysis.corrected_from,
            level=getattr(analysis, "level", None),
            definition=getattr(analysis, "definition", None),
            grammar_notes=getattr(analysis, "grammar_notes", []),
            repetition=0,
            interval=1,
            ease_factor=2.5,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_archived=False,
        )
        words_col = get_words_collection()
        insert_res = await words_col.insert_one(new_word.to_mongo())
        new_word.id = str(insert_res.inserted_id)

        await status_msg.delete()

        # Send card text
        card_text = format_word_card(analysis, user.native_language)
        voice_file_input = BufferedInputFile(
            tts_audio.getvalue(),
            filename=f"{analysis.canonical_word}.mp3",
        )
        await message.answer_voice(
            voice=voice_file_input,
        )
        await message.answer(
            card_text,
            reply_markup=get_word_card_keyboard(new_word.id),
            parse_mode="HTML",
        )

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during voice input")
        await status_msg.edit_text(
            "⏳ <b>Сервис ИИ временно перегружен</b> (исчерпан дневной лимит запросов к моделям).\n\n" + t(user.native_language, "Пожалуйста, подождите немного или повторите попытку позже."),
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error processing voice input")
        await status_msg.edit_text(
            t(user.native_language, "⚠️ Не удалось распознать голосовое сообщение с помощью ИИ. Попробуйте записать еще раз."),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error processing voice input")
        await status_msg.edit_text(
            t(user.native_language, "⚠️ Произошла непредвиденная ошибка при обработке голосового сообщения. Попробуйте позже."),
            parse_mode="HTML",
        )


@router.message(F.text)
async def handle_text_input(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
) -> None:
    """
    Handle text input: translate native language, fix typos, reduce inflections,
    synthesize pronunciation, and save.
    """
    current_state = await state.get_state()
    if current_state is not None:
        # Ignore if in an active FSM state
        return

    text = message.text.strip()
    if not text:
        return

    # Check for direct local duplicate before making an API call
    direct_match = await check_existing_word(user, text)
    if direct_match:
        dup_text = (
            f"💡 Ты уже учишь слово <b>{html.escape(direct_match.canonical_word)}</b>!\n" + f"Интервал повторения: <b>{direct_match.interval}</b> дн.\n" + t(user.native_language, "Хочешь повторить прямо сейчас?")
        )
        await message.answer(
            dup_text,
            reply_markup=get_duplicate_word_keyboard(direct_match.id or ""),
            parse_mode="HTML",
        )
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    status_msg = await message.answer("🔍 <i>Анализирую слово...</i>", parse_mode="HTML")

    try:
        analysis = await gemini_service.analyze_text(
            text,
            native_lang=user.native_language,
            target_lang=user.target_language,
        )

        # Check for duplicate after canonical/lemma analysis
        existing = await check_existing_word(user, analysis.canonical_word)
        if not existing and analysis.lemma:
            existing = await check_existing_word(user, analysis.lemma)

        if existing:
            await status_msg.delete()
            dup_text = (
                f"💡 Ты уже учишь слово <b>{html.escape(existing.canonical_word)}</b> " +
                f"(форма/перевод: <i>{html.escape(text)}</i>)!\n" + f"Интервал повторения: <b>{existing.interval}</b> дн.\n" + t(user.native_language, "Хочешь повторить прямо сейчас?")
            )
            await message.answer(
                dup_text,
                reply_markup=get_duplicate_word_keyboard(existing.id or ""),
                parse_mode="HTML",
            )
            return

        # In-memory neural TTS
        tts_audio = await tts_service.generate_audio(analysis.canonical_word, target_lang=user.target_language)

        # Save to DB
        new_word = Word(
            user_id=user.id,
            native_language=user.native_language,
            target_language=user.target_language,
            canonical_word=analysis.canonical_word,
            lemma=analysis.lemma,
            pos=analysis.pos,
            transcription=analysis.transcription,
            translation=analysis.translation,
            corrected_from=analysis.corrected_from,
            level=getattr(analysis, "level", None),
            definition=getattr(analysis, "definition", None),
            grammar_notes=getattr(analysis, "grammar_notes", []),
            repetition=0,
            interval=1,
            ease_factor=2.5,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_archived=False,
        )
        words_col = get_words_collection()
        insert_res = await words_col.insert_one(new_word.to_mongo())
        new_word.id = str(insert_res.inserted_id)

        await status_msg.delete()

        # Send voice and card
        card_text = format_word_card(analysis, user.native_language)
        voice_file_input = BufferedInputFile(
            tts_audio.getvalue(),
            filename=f"{analysis.canonical_word}.mp3",
        )
        await message.answer_voice(
            voice=voice_file_input,
        )
        await message.answer(
            card_text,
            reply_markup=get_word_card_keyboard(new_word.id or ""),
            parse_mode="HTML",
        )

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during text input")
        await status_msg.edit_text(
            "⏳ <b>Сервис ИИ временно перегружен</b> (исчерпан дневной лимит запросов к моделям).\n\n" + t(user.native_language, "Пожалуйста, подождите немного или повторите попытку позже."),
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error analyzing text word")
        await status_msg.edit_text(
            t(user.native_language, "⚠️ Не удалось проанализировать слово с помощью ИИ. Пожалуйста, попробуйте снова через несколько секунд."),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error analyzing text word")
        await status_msg.edit_text(
            t(user.native_language, "⚠️ Произошла непредвиденная ошибка при анализе слова. Попробуйте позже."),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("tts:"))
async def cb_repeat_tts(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    doc = await words_col.find_one(_word_query_by_id(word_id_str, user))

    if not doc:
        await callback.answer(t(user.native_language, "Слово не найдено"), show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer(t(user.native_language, "Генерирую озвучку..."))
    try:
        audio = await tts_service.generate_audio(word.canonical_word, target_lang=user.target_language)
        voice_file = BufferedInputFile(audio.getvalue(), filename=f"{word.canonical_word}.mp3")
        if callback.message:
            await callback.message.answer_voice(
                voice=voice_file,
            )
    except Exception as e:
        logger.exception("Failed to synthesize TTS in callback")
        await callback.answer(t(user.native_language, "Ошибка синтеза речи"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("delete_word:"))
async def cb_delete_word(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    doc = await words_col.find_one_and_delete(_word_query_by_id(word_id_str, user))

    if not doc:
        await callback.answer(t(user.native_language, "Слово не найдено"), show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer(t(user.native_language, "Слово удалено"))
    if callback.message:
        await callback.message.edit_text(
            f"🗑 Слово <b>{html.escape(word.canonical_word)}</b> удалено из словаря.",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("archive_word:"))
async def cb_archive_word(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    doc = await words_col.find_one_and_update(
        _word_query_by_id(word_id_str, user),
        {"$set": {"is_archived": True, "updated_at": utc_now()}},
        return_document=True,
    )

    if not doc:
        await callback.answer(t(user.native_language, "Слово не найдено"), show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer(t(user.native_language, "Слово перенесено в архив!"))
    if callback.message:
        await callback.message.edit_text(
            f"✅ Слово <b>{html.escape(word.canonical_word)}</b> перенесено в архив!",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("examples:"))
async def cb_word_examples(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    query = _word_query_by_id(word_id_str, user)
    doc = await words_col.find_one(query)

    if not doc:
        await callback.answer(t(user.native_language, "Слово не найдено"), show_alert=True)
        return

    word = Word.model_validate(doc)
    
    await callback.answer(t(user.native_language, "💬 Придумываю примеры..."))
    try:
        res = await gemini_service.get_word_examples(
            word=word.canonical_word,
            lemma=word.lemma,
            pos=word.pos,
            translation=word.translation,
            native_lang=user.native_language,
            target_lang=user.target_language,
        )
        
        ex_lines = []
        for ex in res.examples:
            ex_lines.append(f"• {html.escape(ex.target)}\n  — <i>{html.escape(ex.native)}</i>")
        text = f"💬 <b>Примеры с «{html.escape(word.canonical_word)}»:</b>\n\n" + "\n\n".join(ex_lines)
        
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
            
    except GeminiQuotaExhaustedError:
        await callback.answer(t(user.native_language, "Лимит запросов к ИИ исчерпан. Попробуйте позже."), show_alert=True)
    except Exception as e:
        logger.exception("Error generating examples for word_id=%s: %s", word_id_str, e)
        await callback.answer(t(user.native_language, "Ошибка генерации примеров."), show_alert=True)

