from bot.core.i18n import t, TranslatedText
import html
import io
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, InputRichMessage, InputRichMessageMedia, InputMediaAudio
import re
from bson import ObjectId
from bot.core.database import get_words_collection
from bot.models.base import utc_now

from bot.keyboards.inline import (

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


def _get_us_transcription(analysis: WordAnalysis | Word) -> str:
    trans_us = getattr(analysis, "transcription_us", None)
    if not trans_us and hasattr(analysis, "extra_data") and isinstance(analysis.extra_data, dict):
        trans_us = analysis.extra_data.get("transcription_us")
    
    if trans_us:
        return trans_us
        
    raw_trans = getattr(analysis, "transcription", None) or ""
    if "🇺🇸" in raw_trans:
        parts = raw_trans.split("🇺🇸")
        if len(parts) > 1:
            return parts[1].strip()
    return raw_trans.strip()

def format_word_card(analysis: WordAnalysis | Word, lang: str = "ru", include_audio: bool = True, hide_translations: bool = True) -> str:
    escaped_word = html.escape(analysis.canonical_word)
    escaped_pos = html.escape(analysis.pos)
    escaped_lemma = html.escape(analysis.lemma)
    escaped_transl = html.escape(analysis.translation)

    def _wrap_spoiler(text: str) -> str:
        return f"<tg-spoiler>{text}</tg-spoiler>" if hide_translations else text

    typo_note = ""
    if analysis.corrected_from:
        escaped_typo = html.escape(analysis.corrected_from)
        typo_note = f"{t(lang, '✏️ Исправлена опечатка с:')} <s>{escaped_typo}</s>"

    lemma_note = ""
    if analysis.lemma.lower() != analysis.canonical_word.lower():
        lemma_note = f"🌱 {t(lang, 'Словарная форма:')} <code>{escaped_lemma}</code>"
    
    level_val = html.escape(analysis.level) if getattr(analysis, "level", None) else ""
    level_part = f"<b>{t(lang, 'Уровень')}:</b> {level_val}" if level_val else ""
    
    pos_display = f"<i>{escaped_pos}</i>" if escaped_pos else ""
    pos_native = f"<i>{html.escape(analysis.pos_native)}</i>" if getattr(analysis, "pos_native", None) else ""        

    gram_text = " • ".join(html.escape(n) for n in analysis.grammar_notes) if getattr(analysis, "grammar_notes", []) else ""
    gram_native_text = " • ".join(html.escape(n) for n in analysis.grammar_notes_native) if getattr(analysis, "grammar_notes_native", []) else ""

    target_gram_line = f"{pos_display} • {gram_text}" if (pos_display and gram_text) else (pos_display or gram_text)
    native_gram_content = f"{pos_native} • {gram_native_text}" if (pos_native and gram_native_text) else (pos_native or gram_native_text)
    native_gram_part = _wrap_spoiler(native_gram_content) if native_gram_content else ""

    extra_note = (f"<p>{typo_note}</p>" if typo_note else "") + (f"<p>{lemma_note}</p>" if lemma_note else "")

    block_lines = []
    if level_part:
        block_lines.append(level_part)
    if target_gram_line:
        block_lines.append(target_gram_line)
    if native_gram_part:
        block_lines.append(native_gram_part)

    inner_blockquote = "<br/>".join(block_lines)
    extend_info = f"<details><summary>{t(lang, '✏️ Грамматика')}</summary><blockquote>{inner_blockquote}</blockquote>{extra_note}</details>"

    forms_block = ""
    forms = getattr(analysis, "forms", [])
    if forms:
        form_lines = []
        for f in forms:
            if isinstance(f, dict):
                f_label = f.get("label", "")
                f_word = f.get("word", "")
                f_trans = f.get("translation", "")
            else:
                f_label = getattr(f, "label", "")
                f_word = getattr(f, "word", "")
                f_trans = getattr(f, "translation", "")
            
            trans_part = f" — {_wrap_spoiler(html.escape(f_trans))}" if f_trans else ""
            form_lines.append(f"• <b>{html.escape(f_label)}:</b> <code>{html.escape(f_word)}</code>{trans_part}")

        forms_block = (
            f"<details><summary>{t(lang, '📐 Формы слова')}</summary><blockquote>" +
            "<br/>".join(form_lines) +
            "</blockquote></details>"
        )

    def_text = f"<i>{html.escape(analysis.definition)}</i>" if getattr(analysis, "definition", None) else ""
    definition_native = f"<i>{html.escape(analysis.definition_native)}</i>" if getattr(analysis, "definition_native", None) else ""

    blockquote = ""
    if def_text or definition_native:
        content_lines = []
        if def_text:
            content_lines.append(f"• {def_text}")
        if definition_native:
            content_lines.append(f"- {_wrap_spoiler(definition_native)}")
            
        blockquote = (
            f"<details><summary>{t(lang, '💡 Значение')}</summary><blockquote>" +
            "<br/>".join(content_lines) +
            "</blockquote></details>"
        )

    examples_block = ""
    examples = getattr(analysis, "examples", [])
    if examples:
        ex_lines = []
        for ex in examples:
            if isinstance(ex, dict):
                target = ex.get("target", "")
                native = ex.get("native", "")
            else:
                target = getattr(ex, "target", "")
                native = getattr(ex, "native", "")
            ex_lines.append(f"• {html.escape(target)}<br/>- {_wrap_spoiler('<i>' + html.escape(native) + '</i>')}")
        
        examples_block = f"<details><summary>💬 {t(lang, 'Примеры')}</summary><blockquote>" + "<br/><br/>".join(ex_lines) + "</blockquote></details>"

    transl_display = _wrap_spoiler(escaped_transl)
    card = (
        f"<h1>{escaped_word}</h1>" +
        f"<p>{transl_display}</p>" +
        (f"<audio src=\"tg://audio?id=audio1\"></audio>" if include_audio else "") +
        f"{extend_info}" +
        f"{forms_block}" +
        f"{blockquote}" +
        f"{examples_block}"
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
        "is_pending": {"$ne": True},
        "$or": [
            {"canonical_word": {"$regex": pattern, "$options": "i"}},
            {"lemma": {"$regex": pattern, "$options": "i"}},
        ],
    })
    return Word.model_validate(doc) if doc else None


async def _send_duplicate_word_message(
    message: Message,
    user: User,
    word_data,
    existing_word
) -> None:
    tts_audio = await tts_service.generate_audio(word_data.canonical_word, target_lang=user.target_language)
    voice_file_input = BufferedInputFile(
        tts_audio.getvalue(),
        filename=f"{word_data.canonical_word}.mp3",
    )
    media = InputRichMessageMedia(
        id="audio1",
        media=InputMediaAudio(
            media=voice_file_input,
            title=_get_us_transcription(word_data),
            performer=word_data.level or word_data.canonical_word
        )
    )
    card_text = format_word_card(word_data, user.native_language, hide_translations=getattr(user, "hide_translations", True))
    dup_text = (
        f"{card_text}"
        f"<i>{t(user.native_language, '💡 Ты уже учишь слово')}<br/>"
        f"{t(user.native_language, 'Интервал повторения:')} <b>{existing_word.interval}</b> {t(user.native_language, 'дн.')}</i><br/>"
    )
    await message.bot.send_rich_message(
        chat_id=message.chat.id,
        rich_message=InputRichMessage(html=dup_text, media=[media]),
        reply_markup=get_word_card_keyboard(existing_word.id or "", user.native_language),
    )

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

    try:
        # Download voice directly into in-memory stream
        voice_file = await bot.get_file(message.voice.file_id)
        if not voice_file.file_path:
            await message.answer(t(user.native_language, "❌ Не удалось загрузить голосовое сообщение из Telegram."))
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
            await _send_duplicate_word_message(message, user, analysis, existing)
            try:
                await message.delete()
            except Exception:
                pass
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
            definition_native=getattr(analysis, "definition_native", None),
            pos_native=getattr(analysis, "pos_native", None),
            grammar_notes=getattr(analysis, "grammar_notes", []),
            grammar_notes_native=getattr(analysis, "grammar_notes_native", []),
            forms=[{"label": f.label, "word": f.word, "translation": f.translation} for f in getattr(analysis, "forms", [])] if getattr(analysis, "forms", None) else [],
            examples=[{"target": ex.target, "native": ex.native} for ex in getattr(analysis, "examples", [])] if getattr(analysis, "examples", None) else [],
            extra_data={
                "transcription_uk": getattr(analysis, "transcription_uk", None),
                "transcription_us": getattr(analysis, "transcription_us", None)
            },
            repetition=0,
            interval=1,
            ease_factor=2.5,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_archived=False,
            is_pending=True,
        )
        words_col = get_words_collection()
        insert_res = await words_col.insert_one(new_word.to_mongo())
        new_word.id = str(insert_res.inserted_id)

        # Send card text
        card_text = format_word_card(analysis, user.native_language, hide_translations=getattr(user, "hide_translations", True))
        voice_file_input = BufferedInputFile(
            tts_audio.getvalue(),
            filename=f"{analysis.canonical_word}.mp3",
        )
        media = InputRichMessageMedia(
            id="audio1",
            media=InputMediaAudio(
                media=voice_file_input,
                title=_get_us_transcription(analysis),
                performer=analysis.canonical_word
            )
        )
        rich_msg = InputRichMessage(
            html=card_text,
            media=[media]
        )
        await message.bot.send_rich_message(
            chat_id=message.chat.id,
            rich_message=rich_msg,
            reply_markup=get_word_card_keyboard(new_word.id, user.native_language, is_pending=True),
        )
        try:
            await message.delete()
        except Exception:
            pass

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during voice input")
        await message.answer(
            "⏳ <b>" + t(user.native_language, "Сервис ИИ временно перегружен (исчерпан дневной лимит запросов к моделям).") + "</b>\n\n" + t(user.native_language, "Пожалуйста, подождите немного или повторите попытку позже."),
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error processing voice input")
        await message.answer(
            t(user.native_language, "⚠️ Не удалось распознать голосовое сообщение с помощью ИИ. Попробуйте записать еще раз."),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error processing voice input")
        await message.answer(
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
        await _send_duplicate_word_message(message, user, direct_match, direct_match)
        try:
            await message.delete()
        except Exception:
            pass
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

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
            await _send_duplicate_word_message(message, user, analysis, existing)
            try:
                await message.delete()
            except Exception:
                pass
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
            definition_native=getattr(analysis, "definition_native", None),
            pos_native=getattr(analysis, "pos_native", None),
            grammar_notes=getattr(analysis, "grammar_notes", []),
            grammar_notes_native=getattr(analysis, "grammar_notes_native", []),
            forms=[{"label": f.label, "word": f.word, "translation": f.translation} for f in getattr(analysis, "forms", [])] if getattr(analysis, "forms", None) else [],
            examples=[{"target": ex.target, "native": ex.native} for ex in getattr(analysis, "examples", [])] if getattr(analysis, "examples", None) else [],
            extra_data={
                "transcription_uk": getattr(analysis, "transcription_uk", None),
                "transcription_us": getattr(analysis, "transcription_us", None)
            },
            repetition=0,
            interval=1,
            ease_factor=2.5,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_archived=False,
            is_pending=True,
        )
        words_col = get_words_collection()
        insert_res = await words_col.insert_one(new_word.to_mongo())
        new_word.id = str(insert_res.inserted_id)


        # Send voice and card
        card_text = format_word_card(analysis, user.native_language, hide_translations=getattr(user, "hide_translations", True))
        voice_file_input = BufferedInputFile(
            tts_audio.getvalue(),
            filename=f"{analysis.canonical_word}.mp3",
        )
        media = InputRichMessageMedia(
            id="audio1",
            media=InputMediaAudio(
                media=voice_file_input,
                title=_get_us_transcription(analysis),
                performer=analysis.canonical_word
            )
        )
        rich_msg = InputRichMessage(
            html=card_text,
            media=[media]
        )
        await message.bot.send_rich_message(
            chat_id=message.chat.id,
            rich_message=rich_msg,
            reply_markup=get_word_card_keyboard(new_word.id or "", user.native_language, is_pending=True),
        )
        try:
            await message.delete()
        except Exception:
            pass

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during text input")
        await message.answer(
            "⏳ <b>" + t(user.native_language, "Сервис ИИ временно перегружен (исчерпан дневной лимит запросов к моделям).") + "</b>\n\n" + t(user.native_language, "Пожалуйста, подождите немного или повторите попытку позже."),
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error analyzing text word")
        await message.answer(
            t(user.native_language, "⚠️ Не удалось проанализировать слово с помощью ИИ. Пожалуйста, попробуйте снова через несколько секунд."),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error analyzing text word")
        await message.answer(
            t(user.native_language, "⚠️ Произошла непредвиденная ошибка при анализе слова. Попробуйте позже."),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("add_word:"))
async def cb_add_word(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    
    doc = await words_col.find_one_and_update(
        _word_query_by_id(word_id_str, user),
        {"$set": {"is_pending": False, "updated_at": utc_now()}},
        return_document=True,
    )

    if not doc:
        await callback.answer(t(user.native_language, "Слово не найдено"), show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer(t(user.native_language, "Добавлено в словарь!"))
    
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=get_word_card_keyboard(word.id or word_id_str, user.native_language, is_pending=False)
            )
        except Exception:
            pass


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
        try:
            await callback.message.delete()
        except Exception:
            pass


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
        try:
            await callback.message.delete()
        except Exception:
            pass


