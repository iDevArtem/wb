import pytest
from bot.services.srs_service import SRSService


def test_normalize_basic_casing_and_whitespace():
    assert SRSService.normalize_text("  Hello  ") == "hello"
    assert SRSService.normalize_text("WoRLD") == "world"
    assert SRSService.normalize_text("  multiple   spaces  ") == "multiple spaces"


def test_normalize_strips_punctuation():
    assert SRSService.normalize_text("«hello!»") == "hello"
    assert SRSService.normalize_text('"necessary",') == "necessary"
    assert SRSService.normalize_text("good-looking.") == "good-looking"
    assert SRSService.normalize_text("(example)") == "example"


def test_normalize_strips_articles():
    assert SRSService.normalize_text("a cat") == "cat"
    assert SRSService.normalize_text("an apple") == "apple"
    assert SRSService.normalize_text("the earth") == "earth"
    assert SRSService.normalize_text("The Great Wall") == "great wall"


def test_normalize_strips_infinitive_to():
    assert SRSService.normalize_text("to overcome") == "overcome"
    assert SRSService.normalize_text("To be") == "be"
    # Word that starts with 'to' but isn't an article/particle
    assert SRSService.normalize_text("today") == "today"
    assert SRSService.normalize_text("toast") == "toast"


def test_is_answer_correct_canonical_and_lemma():
    # Matches canonical
    assert SRSService.is_answer_correct("necessary", "necessary", "necessary")
    # Matches with article typed by user
    assert SRSService.is_answer_correct("a book", "book", "book")
    # Matches with 'to' typed by user
    assert SRSService.is_answer_correct("to comprehend", "comprehend", "comprehend")
    # Matches lemma
    assert SRSService.is_answer_correct("go", "went", "go")
    assert SRSService.is_answer_correct("better", "better", "good")
    # Matches with casing / punctuation
    assert SRSService.is_answer_correct("  NeCeSsArY! ", "necessary", "necessary")


def test_is_answer_correct_listening_translation():
    assert SRSService.is_answer_correct(
        user_input="собака",
        canonical_word="dog",
        lemma="dog",
        translation="собака, пёс",
        allow_translation=True,
    )
    assert not SRSService.is_answer_correct(
        user_input="кошка",
        canonical_word="dog",
        lemma="dog",
        translation="собака",
        allow_translation=True,
    )


def test_hints_generation():
    hint1 = SRSService.get_attempt_1_hint("serendipity")
    assert "s" in hint1
    assert "y" in hint1
    assert "11 букв" in hint1

    hint2 = SRSService.get_attempt_2_hint(
        canonical_word="ephemeral",
        lemma="ephemeral",
        examples=[{"en": "Fashions are ephemeral.", "ru": "Мода быстротечна."}],
    )
    assert "___" in hint2
    assert "Fashions are <b>___</b>." in hint2
