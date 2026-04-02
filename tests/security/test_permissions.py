import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.handlers.utils import security_check, check_project_selected


VALID_USER_ID = 123456


def _make_update(user_id=None, has_message=True, has_callback_query=False):
    update = MagicMock()
    if user_id is not None:
        user = MagicMock()
        user.id = user_id
        user.username = f"user_{user_id}"
        update.effective_user = user
    else:
        update.effective_user = None

    if has_message:
        msg = AsyncMock()
        update.message = msg
        update.effective_message = msg
    else:
        update.message = None
        update.effective_message = None

    if has_callback_query:
        update.callback_query = AsyncMock()
    else:
        update.callback_query = None

    return update


# --- security_check tests ---


@patch("src.handlers.utils.ALLOWED_USER_ID", VALID_USER_ID)
async def test_security_check_valid_user():
    update = _make_update(user_id=VALID_USER_ID)
    assert await security_check(update) is True


@patch("src.handlers.utils.ALLOWED_USER_ID", VALID_USER_ID)
async def test_security_check_invalid_user():
    update = _make_update(user_id=999999)
    assert await security_check(update) is False


@patch("src.handlers.utils.ALLOWED_USER_ID", VALID_USER_ID)
async def test_security_check_no_user():
    update = _make_update(user_id=None)
    assert await security_check(update) is False


@patch("src.handlers.utils.ALLOWED_USER_ID", None)
async def test_security_check_no_allowed_user_configured():
    update = _make_update(user_id=42)
    result = await security_check(update)
    assert result is False
    update.effective_message.reply_text.assert_awaited_once()
    call_args = update.effective_message.reply_text.call_args
    assert "42" in call_args[0][0]
    assert "Setup required" in call_args[0][0]


@patch("src.handlers.utils.ALLOWED_USER_ID", VALID_USER_ID)
@pytest.mark.parametrize("bad_id", [0, -1, 999999, 111111, 1])
async def test_security_check_different_user_ids(bad_id):
    update = _make_update(user_id=bad_id)
    assert await security_check(update) is False


# --- check_project_selected tests ---


@patch("src.handlers.utils.service")
async def test_check_project_selected_true(mock_service):
    mock_service.project_selected = True
    update = _make_update(user_id=VALID_USER_ID)
    assert await check_project_selected(update) is True


@patch("src.handlers.utils.service")
async def test_check_project_selected_false_with_message(mock_service):
    mock_service.project_selected = False
    update = _make_update(user_id=VALID_USER_ID, has_message=True)
    result = await check_project_selected(update)
    assert result is False
    update.message.reply_text.assert_awaited_once()
    assert "No Project Selected" in update.message.reply_text.call_args[0][0]


@patch("src.handlers.utils.service")
async def test_check_project_selected_false_with_callback_query(mock_service):
    mock_service.project_selected = False
    update = _make_update(user_id=VALID_USER_ID, has_message=False, has_callback_query=True)
    result = await check_project_selected(update)
    assert result is False
    update.callback_query.answer.assert_awaited_once()
    call_kwargs = update.callback_query.answer.call_args
    assert call_kwargs[1]["show_alert"] is True


@patch("src.handlers.utils.service")
async def test_check_project_selected_false_no_message(mock_service):
    mock_service.project_selected = False
    update = _make_update(user_id=VALID_USER_ID, has_message=False, has_callback_query=False)
    result = await check_project_selected(update)
    assert result is False
