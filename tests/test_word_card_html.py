import xml.etree.ElementTree as ET
import pytest
from bot.handlers.word_input import format_word_card
from bot.services.gemini_service import WordAnalysis, WordFormItem, ExampleItem


def test_format_word_card_valid_html_full():
    wa = WordAnalysis(
        canonical_word="demonstrated",
        lemma="demonstrate",
        pos="verb",
        transcription="ˈdem.ən.streɪ.tɪd",
        translation="продемонстрировал",
        level="B2",
        pos_native="глагол",
        definition="showed clearly",
        definition_native="показал четко",
        grammar_notes=["[transitive]"],
        grammar_notes_native=["[переходный]"],
        forms=[WordFormItem(label="Past Simple", word="demonstrated", translation="продемонстрировал")],
        examples=[ExampleItem(target="He demonstrated the tool.", native="Он продемонстрировал инструмент.")],
        corrected_from="demonstratted",
    )

    card_html = format_word_card(wa, lang="ru", hide_translations=True)
    # Ensure it is well-formed XML/HTML without unbalanced or rogue tags
    root = ET.fromstring(f"<root>{card_html}</root>")
    assert root is not None
    assert "demonstrated" in card_html
    assert "Уровень:" in card_html
    assert "B2" in card_html
    assert "<tg-spoiler>" in card_html


def test_format_word_card_valid_html_minimal():
    wa = WordAnalysis(
        canonical_word="through",
        lemma="through",
        pos="preposition",
        transcription="θruː",
        translation="через",
        level=None,
        pos_native="предлог",
        definition=None,
        definition_native=None,
        grammar_notes=[],
        grammar_notes_native=[],
        forms=[],
        examples=[],
    )

    card_html = format_word_card(wa, lang="ru", hide_translations=False)
    root = ET.fromstring(f"<root>{card_html}</root>")
    assert root is not None
    assert "through" in card_html
    assert "через" in card_html
    assert "<tg-spoiler>" not in card_html
