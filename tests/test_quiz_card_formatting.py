import pytest
from bot.core.i18n import wrap_spoiler, get_pos_translation
from bot.handlers.quiz_fsm import format_quiz_pos
from bot.services.srs_service import SRSService


def test_wrap_spoiler():
    assert wrap_spoiler("капуста", hide=True) == "<tg-spoiler>капуста</tg-spoiler>"
    assert wrap_spoiler("капуста", hide=False) == "капуста"


def test_get_pos_translation():
    assert get_pos_translation("noun", "ru") == "существительное"
    assert get_pos_translation("noun", "uk") == "іменник"
    assert get_pos_translation("verb", "ru") == "глагол"
    assert get_pos_translation("verb", "uk") == "дієслово"
    assert get_pos_translation("phrasal verb", "ru") == "фразовый глагол"
    assert get_pos_translation("unknown_pos_xyz", "ru") is None
    assert get_pos_translation(None, "ru") is None


def test_format_quiz_pos_with_pos_native_hidden():
    result = format_quiz_pos(
        pos="noun",
        pos_native="существительное",
        native_lang="ru",
        hide_translations=True,
    )
    assert "<i>Часть речи: noun</i>" in result
    assert "<tg-spoiler><i>Часть речи: существительное</i></tg-spoiler>" in result


def test_format_quiz_pos_with_pos_native_visible():
    result = format_quiz_pos(
        pos="noun",
        pos_native="существительное",
        native_lang="ru",
        hide_translations=False,
    )
    assert "<i>Часть речи: noun</i>" in result
    assert "<i>Часть речи: существительное</i>" in result
    assert "<tg-spoiler>" not in result


def test_format_quiz_pos_fallback_mapping_uk():
    # If pos_native is None, it should fall back to standard translation
    result = format_quiz_pos(
        pos="noun",
        pos_native=None,
        native_lang="uk",
        hide_translations=True,
    )
    assert "<i>Частина мови: noun</i>" in result
    assert "<tg-spoiler><i>Частина мови: іменник</i></tg-spoiler>" in result


def test_format_quiz_pos_empty():
    assert format_quiz_pos(None, None, "ru") == ""
    assert format_quiz_pos("", None, "ru") == ""


def test_get_attempt_2_hint_modern_keys_with_spoiler():
    examples = [{"target": "I like cabbage.", "native": "Я люблю капусту."}]
    hint = SRSService.get_attempt_2_hint(
        canonical_word="cabbage",
        lemma="cabbage",
        examples=examples,
        lang="ru",
        hide_translations=True,
    )
    assert "I like <b>___</b>." in hint
    assert "<tg-spoiler>Я люблю капусту.</tg-spoiler>" in hint


def test_get_attempt_2_hint_modern_keys_without_spoiler():
    examples = [{"target": "I like cabbage.", "native": "Я люблю капусту."}]
    hint = SRSService.get_attempt_2_hint(
        canonical_word="cabbage",
        lemma="cabbage",
        examples=examples,
        lang="ru",
        hide_translations=False,
    )
    assert "I like <b>___</b>." in hint
    assert "<i>(Я люблю капусту.)</i>" in hint
    assert "<tg-spoiler>" not in hint


def test_get_attempt_2_hint_legacy_keys_with_spoiler():
    examples = [{"en": "She grows cabbage in her garden.", "ru": "Она выращивает капусту в саду."}]
    hint = SRSService.get_attempt_2_hint(
        canonical_word="cabbage",
        lemma="cabbage",
        examples=examples,
        lang="ru",
        hide_translations=True,
    )
    assert "<b>___</b>" in hint
    assert "<tg-spoiler>Она выращивает капусту в саду.</tg-spoiler>" in hint
