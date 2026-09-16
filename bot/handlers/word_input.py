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


def format_word_card(analysis: WordAnalysis) -> str:
    escaped_word = html.escape(analysis.canonical_word)
    escaped_pos = html.escape(analysis.pos)
    escaped_lemma = html.escape(analysis.lemma)
    escaped_transl = html.escape(analysis.translation)

    if analysis.transcription_uk and analysis.transcription_us and analysis.transcription_uk != analysis.transcription_us:
        trans_display = f"🇬🇧 <code>{html.escape(analysis.transcription_uk)}</code> | 🇺🇸 <code>{html.escape(analysis.transcription_us)}</code>"
    else:
        raw_trans = analysis.transcription or analysis.transcription_us or analysis.transcription_uk or ""
        trans_display = f"[{html.escape(raw_trans)}]"

    typo_note = ""
    if analysis.corrected_from:
        escaped_typo = html.escape(analysis.corrected_from)
        typo_note = f"✏️ <i>Исправлена опечатка с:</i> <s>{escaped_typo}</s>\n"

    examples_block = ""
    if analysis.examples:
        ex_lines = []
        for ex in analysis.examples[:3]:
            ex_lines.append(f"• {html.escape(ex.en)}\n  — <i>{html.escape(ex.ru)}</i>")
        examples_block = "\n💬 <b>Примеры:</b>\n" + "\n".join(ex_lines) + "\n"

    colloc_block = ""
    if analysis.synonyms_collocations:
        collocs = [f"• {html.escape(c)}" for c in analysis.synonyms_collocations[:3]]
        colloc_block = "\n🔗 <b>Коллокации / синонимы:</b>\n" + "\n".join(collocs) + "\n"

    card = (
        f"📖 <b>{escaped_word}</b> {trans_display} — <i>{escaped_pos}</i>\n"
        f"{typo_note}"
        f"🌱 Словарная форма: <code>{escaped_lemma}</code>\n"
        f"🇷🇺 Перевод: <b>{escaped_transl}</b>\n"
        f"{examples_block}"
        f"{colloc_block}"
    )
    return card


def format_forms_message(word: Word) -> str:
    forms_data = (word.extra_data or {}).get("forms")
    escaped_word = html.escape(word.canonical_word)
    if not forms_data:
        return (
            f"📐 <b>Грамматические формы: {escaped_word}</b>\n\n"
            "<i>Для этого слова нет отдельных грамматических форм (неизменяемое слово или устойчивое выражение).</i>"
        )

    lines = [f"📐 <b>Грамматические формы: {escaped_word}</b>\n"]
    if forms_data.get("notes"):
        lines.append(f"ℹ️ <i>{html.escape(forms_data['notes'])}</i>\n")

    if forms_data.get("summary"):
        lines.append(f"📌 <b>Кратко:</b> <code>{html.escape(forms_data['summary'])}</code>\n")

    details = []
    if forms_data.get("v1"):
        details.append(f"• <b>V1 (Infinitive):</b> <code>{html.escape(forms_data['v1'])}</code>")
    if forms_data.get("v2"):
        details.append(f"• <b>V2 (Past Simple):</b> <code>{html.escape(forms_data['v2'])}</code>")
    if forms_data.get("v3"):
        details.append(f"• <b>V3 (Past Participle):</b> <code>{html.escape(forms_data['v3'])}</code>")
    if forms_data.get("v_ing"):
        details.append(f"• <b>-ing (Gerund/Participle):</b> <code>{html.escape(forms_data['v_ing'])}</code>")
    if forms_data.get("v_s"):
        details.append(f"• <b>3rd person (-s/-es):</b> <code>{html.escape(forms_data['v_s'])}</code>")
    if forms_data.get("comparative"):
        details.append(f"• <b>Сравнительная степень:</b> <code>{html.escape(forms_data['comparative'])}</code>")
    if forms_data.get("superlative"):
        details.append(f"• <b>Превосходная степень:</b> <code>{html.escape(forms_data['superlative'])}</code>")
    if forms_data.get("plural"):
        details.append(f"• <b>Множественное число:</b> <code>{html.escape(forms_data['plural'])}</code>")

    if details:
        lines.append("📋 <b>Подробно:</b>\n" + "\n".join(details))

    return "\n".join(lines)


def format_tenses_message(word: Word, tenses_dict: dict) -> str:
    escaped_word = html.escape(word.canonical_word)
    lines = [f"⏳ <b>Все 12 времен английского: {escaped_word}</b>\n"]
    if tenses_dict.get("notes"):
        lines.append(f"ℹ️ <i>{html.escape(tenses_dict['notes'])}</i>\n")

    tenses = tenses_dict.get("tenses", [])
    for t in tenses:
        name = html.escape(t.get("tense_name", ""))
        aspect = html.escape(t.get("aspect", ""))
        ex_en = html.escape(t.get("example_en", ""))
        ex_ru = html.escape(t.get("example_ru", ""))
        lines.append(
            f"🔹 <b>{name}</b> <i>({aspect})</i>\n"
            f"• {ex_en}\n"
            f"  — <i>{ex_ru}</i>\n"
        )
    return "\n".join(lines)


def format_family_message(word: Word, family_dict: dict) -> str:
    escaped_word = html.escape(word.canonical_word)
    root = html.escape(family_dict.get("root", word.lemma))
    lines = [
        f"🌱 <b>Однокоренные слова (Word Family): {escaped_word}</b>\n"
        f"Базовый корень: <code>{root}</code>\n"
    ]
    members = family_dict.get("members", [])
    for m in members:
        w = html.escape(m.get("word", ""))
        pos = html.escape(m.get("pos", ""))
        tr = html.escape(m.get("translation", ""))
        ex_en = html.escape(m.get("example_en", ""))
        ex_ru = html.escape(m.get("example_ru", ""))
        lines.append(
            f"• <b>{w}</b> <i>({pos})</i> — <b>{tr}</b>\n"
            f"  «{ex_en}»\n"
            f"  — <i>{ex_ru}</i>\n"
        )
    return "\n".join(lines)


def format_dialogue_message(word: Word, dialogue_dict: dict) -> str:
    escaped_word = html.escape(word.canonical_word)
    situation = html.escape(dialogue_dict.get("situation", "Повседневный разговор"))
    lines = [
        f"🎭 <b>Живой диалог: {escaped_word}</b>\n"
        f"📍 <i>Ситуация: {situation}</i>\n"
    ]
    dialogue_lines = dialogue_dict.get("lines", [])
    for d in dialogue_lines:
        speaker = html.escape(d.get("speaker", "Speaker"))
        en = html.escape(d.get("en", ""))
        ru = html.escape(d.get("ru", ""))
        lines.append(
            f"🗣 <b>{speaker}:</b> {en}\n"
            f"   — <i>{ru}</i>\n"
        )
    return "\n".join(lines)


def _word_query_by_id(word_id_str: str, user_id: int) -> dict:
    query: dict = {"user_id": user_id}
    if ObjectId.is_valid(word_id_str):
        query["_id"] = ObjectId(word_id_str)
    else:
        query["_id"] = word_id_str
    return query


async def check_existing_word(
    user_id: int,
    word_text: str,
) -> Word | None:
    norm = word_text.strip().lower()
    words_col = get_words_collection()
    pattern = f"^{re.escape(norm)}$"
    doc = await words_col.find_one({
        "user_id": user_id,
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
    status_msg = await message.answer("🎙 <i>Слушаю и анализирую произношение...</i>", parse_mode="HTML")

    try:
        # Download voice directly into in-memory stream
        voice_file = await bot.get_file(message.voice.file_id)
        if not voice_file.file_path:
            await status_msg.edit_text("❌ Не удалось загрузить голосовое сообщение из Telegram.")
            return

        voice_stream = io.BytesIO()
        await bot.download_file(voice_file.file_path, destination=voice_stream)
        audio_bytes = voice_stream.getvalue()

        # Send in-memory audio/ogg directly to Gemini
        analysis = await gemini_service.analyze_voice(audio_bytes=audio_bytes, mime_type="audio/ogg")

        # Check duplicate
        existing = await check_existing_word(user.id, analysis.canonical_word)
        if not existing and analysis.lemma:
            existing = await check_existing_word(user.id, analysis.lemma)

        if existing:
            await status_msg.delete()
            text = (
                f"💡 Ты уже учишь слово <b>{html.escape(existing.canonical_word)}</b>!\n"
                f"Интервал повторения: <b>{existing.interval}</b> дн.\n"
                "Хочешь повторить прямо сейчас?"
            )
            await message.answer(
                text,
                reply_markup=get_duplicate_word_keyboard(existing.id or ""),
                parse_mode="HTML",
            )
            return

        # Synthesize audio with edge-tts in memory
        tts_audio = await tts_service.generate_audio(analysis.canonical_word)

        # Save to DB
        new_word = Word(
            user_id=user.id,
            canonical_word=analysis.canonical_word,
            lemma=analysis.lemma,
            pos=analysis.pos,
            transcription=analysis.transcription,
            translation=analysis.translation,
            corrected_from=analysis.corrected_from,
            examples=[e.model_dump() for e in analysis.examples],
            synonyms_collocations=analysis.synonyms_collocations,
            repetition=0,
            interval=1,
            ease_factor=2.5,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_archived=False,
            extra_data={"forms": analysis.forms.model_dump() if analysis.forms else None},
        )
        words_col = get_words_collection()
        insert_res = await words_col.insert_one(new_word.to_mongo())
        new_word.id = str(insert_res.inserted_id)

        await status_msg.delete()

        # Send card text
        card_text = format_word_card(analysis)
        voice_file_input = BufferedInputFile(
            tts_audio.getvalue(),
            filename=f"{analysis.canonical_word}.mp3",
        )
        await message.answer_voice(
            voice=voice_file_input,
            caption=f"🔊 Эталонное произношение: <b>{html.escape(analysis.canonical_word)}</b>",
            parse_mode="HTML",
        )
        await message.answer(
            card_text,
            reply_markup=get_word_card_keyboard(new_word.id),
            parse_mode="HTML",
        )

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during voice input")
        await status_msg.edit_text(
            "⏳ <b>Сервис ИИ временно перегружен</b> (исчерпан дневной лимит запросов к моделям).\n\n"
            "Пожалуйста, подождите немного или повторите попытку позже.",
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error processing voice input")
        await status_msg.edit_text(
            "⚠️ Не удалось распознать голосовое сообщение с помощью ИИ. Попробуйте записать еще раз.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error processing voice input")
        await status_msg.edit_text(
            "⚠️ Произошла непредвиденная ошибка при обработке голосового сообщения. Попробуйте позже.",
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
    Handle text input: translate Russian/Ukrainian, fix typos, reduce inflections,
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
    direct_match = await check_existing_word(user.id, text)
    if direct_match:
        dup_text = (
            f"💡 Ты уже учишь слово <b>{html.escape(direct_match.canonical_word)}</b>!\n"
            f"Интервал повторения: <b>{direct_match.interval}</b> дн.\n"
            "Хочешь повторить прямо сейчас?"
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
        analysis = await gemini_service.analyze_text(text)

        # Check for duplicate after canonical/lemma analysis
        existing = await check_existing_word(user.id, analysis.canonical_word)
        if not existing and analysis.lemma:
            existing = await check_existing_word(user.id, analysis.lemma)

        if existing:
            await status_msg.delete()
            dup_text = (
                f"💡 Ты уже учишь слово <b>{html.escape(existing.canonical_word)}</b> "
                f"(форма/перевод: <i>{html.escape(text)}</i>)!\n"
                f"Интервал повторения: <b>{existing.interval}</b> дн.\n"
                "Хочешь повторить прямо сейчас?"
            )
            await message.answer(
                dup_text,
                reply_markup=get_duplicate_word_keyboard(existing.id or ""),
                parse_mode="HTML",
            )
            return

        # In-memory neural TTS
        tts_audio = await tts_service.generate_audio(analysis.canonical_word)

        # Save to DB
        new_word = Word(
            user_id=user.id,
            canonical_word=analysis.canonical_word,
            lemma=analysis.lemma,
            pos=analysis.pos,
            transcription=analysis.transcription,
            translation=analysis.translation,
            corrected_from=analysis.corrected_from,
            examples=[e.model_dump() for e in analysis.examples],
            synonyms_collocations=analysis.synonyms_collocations,
            repetition=0,
            interval=1,
            ease_factor=2.5,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_archived=False,
            extra_data={"forms": analysis.forms.model_dump() if analysis.forms else None},
        )
        words_col = get_words_collection()
        insert_res = await words_col.insert_one(new_word.to_mongo())
        new_word.id = str(insert_res.inserted_id)

        await status_msg.delete()

        # Send voice and card
        card_text = format_word_card(analysis)
        voice_file_input = BufferedInputFile(
            tts_audio.getvalue(),
            filename=f"{analysis.canonical_word}.mp3",
        )
        await message.answer_voice(
            voice=voice_file_input,
            caption=f"🔊 Произношение: <b>{html.escape(analysis.canonical_word)}</b>",
            parse_mode="HTML",
        )
        await message.answer(
            card_text,
            reply_markup=get_word_card_keyboard(new_word.id or ""),
            parse_mode="HTML",
        )

    except GeminiQuotaExhaustedError:
        logger.warning("Gemini quota exhausted during text input")
        await status_msg.edit_text(
            "⏳ <b>Сервис ИИ временно перегружен</b> (исчерпан дневной лимит запросов к моделям).\n\n"
            "Пожалуйста, подождите немного или повторите попытку позже.",
            parse_mode="HTML",
        )
    except GeminiServiceError:
        logger.exception("Gemini service error analyzing text word")
        await status_msg.edit_text(
            "⚠️ Не удалось проанализировать слово с помощью ИИ. Пожалуйста, попробуйте снова через несколько секунд.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error analyzing text word")
        await status_msg.edit_text(
            "⚠️ Произошла непредвиденная ошибка при анализе слова. Попробуйте позже.",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("tts:"))
async def cb_repeat_tts(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    doc = await words_col.find_one(_word_query_by_id(word_id_str, user.id))

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer("Генерирую озвучку...")
    try:
        audio = await tts_service.generate_audio(word.canonical_word)
        voice_file = BufferedInputFile(audio.getvalue(), filename=f"{word.canonical_word}.mp3")
        if callback.message:
            await callback.message.answer_voice(
                voice=voice_file,
                caption=f"🔊 <b>{html.escape(word.canonical_word)}</b> [{html.escape(word.transcription)}]",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("Failed to synthesize TTS in callback")
        await callback.answer("Ошибка синтеза речи", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("delete_word:"))
async def cb_delete_word(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    doc = await words_col.find_one_and_delete(_word_query_by_id(word_id_str, user.id))

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer("Слово удалено")
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
        _word_query_by_id(word_id_str, user.id),
        {"$set": {"is_archived": True, "updated_at": utc_now()}},
        return_document=True,
    )

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    await callback.answer("Слово перенесено в архив!")
    if callback.message:
        await callback.message.edit_text(
            f"✅ Слово <b>{html.escape(word.canonical_word)}</b> перенесено в архив!",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("forms:"))
async def cb_word_forms(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    query = _word_query_by_id(word_id_str, user.id)
    doc = await words_col.find_one(query)

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    extra_data = dict(word.extra_data or {})
    forms_data = extra_data.get("forms")

    # If legacy word without pre-generated forms, generate on-the-fly and cache
    if not forms_data:
        await callback.answer("⏳ Извлекаю формы слова...")
        try:
            analysis = await gemini_service.analyze_text(word.canonical_word)
            if analysis.forms:
                extra_data["forms"] = analysis.forms.model_dump()
                word.extra_data = extra_data
                await words_col.update_one(query, {"$set": {"extra_data": extra_data, "updated_at": utc_now()}})
        except Exception as e:
            logger.warning("Could not backfill forms for word_id=%s: %s", word_id_str, e)
    else:
        await callback.answer()

    msg_text = format_forms_message(word)
    if callback.message:
        await callback.message.reply(msg_text, parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("tenses:"))
async def cb_word_tenses(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    query = _word_query_by_id(word_id_str, user.id)
    doc = await words_col.find_one(query)

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    extra_data = dict(word.extra_data or {})
    cached_tenses = extra_data.get("tenses")

    if cached_tenses:
        await callback.answer()
        text = format_tenses_message(word, cached_tenses)
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
        return

    await callback.answer("⏳ Составляю все 12 времен...")
    try:
        res = await gemini_service.get_word_all_tenses(
            word=word.canonical_word,
            lemma=word.lemma,
            pos=word.pos,
            translation=word.translation,
        )
        extra_data["tenses"] = res.model_dump()
        word.extra_data = extra_data
        await words_col.update_one(query, {"$set": {"extra_data": extra_data, "updated_at": utc_now()}})

        text = format_tenses_message(word, extra_data["tenses"])
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
    except GeminiQuotaExhaustedError:
        await callback.answer("Лимит запросов к ИИ исчерпан. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.exception("Error generating tenses for word_id=%s: %s", word_id_str, e)
        await callback.answer("Ошибка генерации времен.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("family:"))
async def cb_word_family(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    query = _word_query_by_id(word_id_str, user.id)
    doc = await words_col.find_one(query)

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    extra_data = dict(word.extra_data or {})
    cached_family = extra_data.get("family")

    if cached_family:
        await callback.answer()
        text = format_family_message(word, cached_family)
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
        return

    await callback.answer("🌱 Подбираю однокоренные слова...")
    try:
        res = await gemini_service.get_word_family(
            word=word.canonical_word,
            lemma=word.lemma,
            pos=word.pos,
            translation=word.translation,
        )
        extra_data["family"] = res.model_dump()
        word.extra_data = extra_data
        await words_col.update_one(query, {"$set": {"extra_data": extra_data, "updated_at": utc_now()}})

        text = format_family_message(word, extra_data["family"])
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
    except GeminiQuotaExhaustedError:
        await callback.answer("Лимит запросов к ИИ исчерпан. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.exception("Error generating family for word_id=%s: %s", word_id_str, e)
        await callback.answer("Ошибка подбора однокоренных слов.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("dialogue:"))
async def cb_word_dialogue(callback: CallbackQuery, user: User) -> None:
    word_id_str = callback.data.split(":")[1]
    words_col = get_words_collection()
    query = _word_query_by_id(word_id_str, user.id)
    doc = await words_col.find_one(query)

    if not doc:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    word = Word.model_validate(doc)
    extra_data = dict(word.extra_data or {})
    cached_dialogue = extra_data.get("dialogue")

    if cached_dialogue:
        await callback.answer()
        text = format_dialogue_message(word, cached_dialogue)
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
        return

    await callback.answer("🎭 Составляю живой диалог...")
    try:
        res = await gemini_service.get_word_dialogue(
            word=word.canonical_word,
            lemma=word.lemma,
            pos=word.pos,
            translation=word.translation,
        )
        extra_data["dialogue"] = res.model_dump()
        word.extra_data = extra_data
        await words_col.update_one(query, {"$set": {"extra_data": extra_data, "updated_at": utc_now()}})

        text = format_dialogue_message(word, extra_data["dialogue"])
        if callback.message:
            await callback.message.reply(text, parse_mode="HTML")
    except GeminiQuotaExhaustedError:
        await callback.answer("Лимит запросов к ИИ исчерпан. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.exception("Error generating dialogue for word_id=%s: %s", word_id_str, e)
        await callback.answer("Ошибка генерации диалога.", show_alert=True)

