import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, Chat, User as TgUser
from bot.models.user import User
from bot.handlers.settings import (
    cb_manual_tz,
    cb_manual_native,
    cb_manual_target,
    cb_toggle_hide_translations,
    handle_custom_tz_input,
    handle_custom_native_input,
    handle_custom_target_input,
    SettingsState,
)


@pytest.fixture
def mock_user():
    return User(
        tg_id=12345,
        username="testuser",
        native_language="ru",
        target_language="en",
        timezone="UTC",
        hide_translations=True,
    )


@pytest.fixture
def mock_callback():
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    cb.message = msg
    return cb


@pytest.fixture
def mock_fsm_context():
    state = MagicMock(spec=FSMContext)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_cb_manual_tz_receives_user_and_sets_state(mock_callback, mock_user, mock_fsm_context):
    await cb_manual_tz(mock_callback, user=mock_user, state=mock_fsm_context)
    mock_callback.answer.assert_awaited_once()
    mock_fsm_context.set_state.assert_awaited_once_with(SettingsState.waiting_for_custom_tz)
    mock_callback.message.answer.assert_awaited_once()
    prompt = mock_callback.message.answer.call_args[0][0]
    assert "название часового пояса" in prompt


@pytest.mark.asyncio
async def test_cb_manual_native_receives_user_and_sets_state(mock_callback, mock_user, mock_fsm_context):
    await cb_manual_native(mock_callback, user=mock_user, state=mock_fsm_context)
    mock_callback.answer.assert_awaited_once()
    mock_fsm_context.set_state.assert_awaited_once_with(SettingsState.waiting_for_custom_native)
    mock_callback.message.answer.assert_awaited_once()
    prompt = mock_callback.message.answer.call_args[0][0]
    assert "код языка" in prompt


@pytest.mark.asyncio
async def test_cb_manual_target_receives_user_and_sets_state(mock_callback, mock_user, mock_fsm_context):
    await cb_manual_target(mock_callback, user=mock_user, state=mock_fsm_context)
    mock_callback.answer.assert_awaited_once()
    mock_fsm_context.set_state.assert_awaited_once_with(SettingsState.waiting_for_custom_target)
    mock_callback.message.answer.assert_awaited_once()
    prompt = mock_callback.message.answer.call_args[0][0]
    assert "код изучаемого языка" in prompt


@pytest.mark.asyncio
async def test_cb_toggle_hide_translations(mock_callback, mock_user):
    user_col = AsyncMock()
    with patch("bot.handlers.settings.get_users_collection", return_value=user_col):
        assert mock_user.hide_translations is True
        await cb_toggle_hide_translations(mock_callback, user=mock_user)
        assert mock_user.hide_translations is False
        user_col.update_one.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_custom_tz_input_valid(mock_user, mock_fsm_context):
    msg = MagicMock(spec=Message)
    msg.text = "Europe/Berlin"
    msg.answer = AsyncMock()
    user_col = AsyncMock()

    with patch("bot.handlers.settings.get_users_collection", return_value=user_col):
        await handle_custom_tz_input(msg, user=mock_user, state=mock_fsm_context)
        assert mock_user.timezone == "Europe/Berlin"
        user_col.update_one.assert_awaited_once()
        mock_fsm_context.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()
        assert "Europe/Berlin" in msg.answer.call_args[0][0]
