import pytest
from bot.keyboards.inline import get_word_card_keyboard

def test_word_card_keyboard_contains_new_buttons():
    kb = get_word_card_keyboard(word_id=42)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    callbacks = [b.callback_data for b in buttons]

    assert "delete_word:42" in callbacks
    assert "archive_word:42" in callbacks
    assert "examples:42" not in callbacks
    assert "delete_word:42" in callbacks
    assert "archive_word:42" in callbacks


