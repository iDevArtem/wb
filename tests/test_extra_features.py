import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.keyboards.inline import get_word_card_keyboard
from bot.models.word import Word
from bot.handlers.word_input import (
    format_forms_message,
    format_tenses_message,
    format_family_message,
    format_dialogue_message,
)
from bot.services.gemini_service import (
    WordFormsDetail,
    WordAllTensesResponse,
    TenseItem,
    WordFamilyResponse,
    WordFamilyItem,
    WordDialogueResponse,
    DialogueLine,
    GeminiService,
)


def test_word_forms_detail_schema():
    data = {
        "summary": "take (V1) → took (V2) → taken (V3) | -ing: taking | 3rd: takes",
        "v1": "take",
        "v2": "took",
        "v3": "taken",
        "v_ing": "taking",
        "v_s": "takes",
        "notes": "Неправильный глагол",
    }
    forms = WordFormsDetail.model_validate(data)
    assert forms.v1 == "take"
    assert forms.v2 == "took"
    assert forms.v3 == "taken"
    assert forms.v_ing == "taking"
    assert forms.notes == "Неправильный глагол"


def test_word_all_tenses_schema():
    data = {
        "word": "take",
        "is_verb": True,
        "notes": None,
        "tenses": [
            {
                "tense_name": "Present Simple",
                "aspect": "Регулярное действие",
                "example_en": "I take the train every day.",
                "example_ru": "Я сажусь на поезд каждый день.",
            },
            {
                "tense_name": "Present Continuous",
                "aspect": "Действие в момент речи",
                "example_en": "I am taking notes now.",
                "example_ru": "Я сейчас делаю заметки.",
            },
        ],
    }
    resp = WordAllTensesResponse.model_validate(data)
    assert resp.word == "take"
    assert len(resp.tenses) == 2
    assert resp.tenses[0].tense_name == "Present Simple"


def test_word_family_schema():
    data = {
        "root": "decide",
        "members": [
            {
                "word": "decision",
                "pos": "существительное",
                "translation": "решение",
                "example_en": "It was a hard decision.",
                "example_ru": "Это было трудное решение.",
            },
            {
                "word": "decisive",
                "pos": "прилагательное",
                "translation": "решительный",
                "example_en": "She is very decisive.",
                "example_ru": "Она очень решительная.",
            },
        ],
    }
    resp = WordFamilyResponse.model_validate(data)
    assert resp.root == "decide"
    assert len(resp.members) == 2
    assert resp.members[0].word == "decision"


def test_word_dialogue_schema():
    data = {
        "word": "negotiate",
        "situation": "Деловая встреча",
        "lines": [
            {
                "speaker": "John",
                "en": "Are you ready to negotiate the contract?",
                "ru": "Вы готовы вести переговоры по контракту?",
            },
            {
                "speaker": "Mary",
                "en": "Yes, let's negotiate favorable terms.",
                "ru": "Да, давайте обсудим выгодные условия.",
            },
        ],
    }
    resp = WordDialogueResponse.model_validate(data)
    assert resp.word == "negotiate"
    assert resp.situation == "Деловая встреча"
    assert len(resp.lines) == 2


def test_format_forms_message():
    word = Word(
        id=1,
        user_id=1,
        canonical_word="take",
        lemma="take",
        pos="verb",
        transcription="/teɪk/",
        translation="брать",
        extra_data={
            "forms": {
                "summary": "take (V1) → took (V2) → taken (V3)",
                "v1": "take",
                "v2": "took",
                "v3": "taken",
                "v_ing": "taking",
                "v_s": "takes",
                "notes": "Неправильный глагол",
            }
        },
    )
    msg = format_forms_message(word)
    assert "📐 <b>Грамматические формы: take</b>" in msg
    assert "Неправильный глагол" in msg
    assert "take (V1) → took (V2) → taken (V3)" in msg
    assert "V1 (Infinitive):" in msg
    assert "V2 (Past Simple):" in msg


def test_format_forms_message_empty():
    word = Word(
        id=2,
        user_id=1,
        canonical_word="always",
        lemma="always",
        pos="adverb",
        transcription="/ˈɔːlweɪz/",
        translation="всегда",
        extra_data={},
    )
    msg = format_forms_message(word)
    assert "Для этого слова нет отдельных грамматических форм" in msg


def test_format_tenses_message():
    word = Word(
        id=1,
        user_id=1,
        canonical_word="go",
        lemma="go",
        pos="verb",
        transcription="/ɡoʊ/",
        translation="идти",
    )
    tenses_dict = {
        "notes": "Неправильный глагол движения",
        "tenses": [
            {
                "tense_name": "Present Simple",
                "aspect": "Регулярное действие",
                "example_en": "I go to gym.",
                "example_ru": "Я хожу в зал.",
            }
        ],
    }
    msg = format_tenses_message(word, tenses_dict)
    assert "Все 12 времен английского: go" in msg
    assert "Present Simple" in msg
    assert "I go to gym." in msg


def test_format_family_message():
    word = Word(
        id=1,
        user_id=1,
        canonical_word="create",
        lemma="create",
        pos="verb",
        transcription="/kriˈeɪt/",
        translation="создавать",
    )
    family_dict = {
        "root": "create",
        "members": [
            {
                "word": "creative",
                "pos": "прилагательное",
                "translation": "творческий",
                "example_en": "She is creative.",
                "example_ru": "Она творческая.",
            }
        ],
    }
    msg = format_family_message(word, family_dict)
    assert "Однокоренные слова (Word Family): create" in msg
    assert "creative" in msg
    assert "творческий" in msg


def test_format_dialogue_message():
    word = Word(
        id=1,
        user_id=1,
        canonical_word="order",
        lemma="order",
        pos="verb",
        transcription="/ˈɔːrdər/",
        translation="заказывать",
    )
    dialogue_dict = {
        "situation": "В ресторане",
        "lines": [
            {
                "speaker": "Waiter",
                "en": "Are you ready to order?",
                "ru": "Вы готовы сделать заказ?",
            }
        ],
    }
    msg = format_dialogue_message(word, dialogue_dict)
    assert "Живой диалог: order" in msg
    assert "В ресторане" in msg
    assert "Waiter" in msg


def test_word_card_keyboard_contains_new_buttons():
    kb = get_word_card_keyboard(word_id=42)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    callbacks = [b.callback_data for b in buttons]

    assert "forms:42" in callbacks
    assert "tenses:42" in callbacks
    assert "family:42" in callbacks
    assert "dialogue:42" in callbacks
    assert "tts:42" in callbacks
    assert "delete_word:42" in callbacks
    assert "archive_word:42" in callbacks


@pytest.mark.asyncio
async def test_gemini_service_extra_methods():
    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_models = MagicMock()
    mock_aio.models = mock_models

    service = GeminiService(api_key="test_key", models_pool=["test-model"])
    service._clients = [mock_client]

    # Test tenses
    tenses_json = (
        '{"word": "run", "is_verb": true, "notes": null, "tenses": ['
        '{"tense_name": "Past Simple", "aspect": "прошлое", "example_en": "He ran.", "example_ru": "Он бежал."}'
        ']}'
    )
    resp_tenses = MagicMock()
    resp_tenses.text = tenses_json
    mock_models.generate_content = AsyncMock(return_value=resp_tenses)

    res = await service.get_word_all_tenses("run", "run", "verb", "бежать")
    assert isinstance(res, WordAllTensesResponse)
    assert res.word == "run"
    assert res.tenses[0].tense_name == "Past Simple"

    # Test family
    family_json = (
        '{"root": "act", "members": ['
        '{"word": "action", "pos": "существительное", "translation": "действие", "example_en": "Action speaks.", "example_ru": "Действие говорит."}'
        ']}'
    )
    resp_family = MagicMock()
    resp_family.text = family_json
    mock_models.generate_content = AsyncMock(return_value=resp_family)

    res_fam = await service.get_word_family("act", "act", "verb", "действовать")
    assert isinstance(res_fam, WordFamilyResponse)
    assert res_fam.root == "act"
    assert res_fam.members[0].word == "action"

    # Test dialogue
    dialogue_json = (
        '{"word": "coffee", "situation": "Кафе", "lines": ['
        '{"speaker": "A", "en": "I love coffee.", "ru": "Я люблю кофе."}'
        ']}'
    )
    resp_dialogue = MagicMock()
    resp_dialogue.text = dialogue_json
    mock_models.generate_content = AsyncMock(return_value=resp_dialogue)

    res_diag = await service.get_word_dialogue("coffee", "coffee", "noun", "кофе")
    assert isinstance(res_diag, WordDialogueResponse)
    assert res_diag.situation == "Кафе"
    assert res_diag.lines[0].speaker == "A"
