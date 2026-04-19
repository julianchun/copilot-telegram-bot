"""Integration tests for command handlers in src/handlers/commands.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

MODULE = "src.handlers.commands"


@pytest.fixture(autouse=True)
def _patch_security(mock_service):
    """Patch security_check, check_project_selected, service, and build_main_menu for every test."""
    with (
        patch(f"{MODULE}.security_check", new_callable=AsyncMock, return_value=True),
        patch(f"{MODULE}.check_project_selected", new_callable=AsyncMock, return_value=True),
        patch(f"{MODULE}.service", mock_service),
        patch(f"{MODULE}.build_main_menu", new_callable=AsyncMock) as mock_menu,
    ):
        mock_menu.return_value = ("Welcome!", MagicMock(), ("1.0.0", "testuser", "0.2.0"))
        yield


async def test_start_command_sends_menu(mock_update, mock_context):
    from src.handlers.commands import start_command

    await start_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_kwargs = mock_update.message.reply_text.call_args
    assert "Welcome!" in call_kwargs.args[0]
    assert "reply_markup" in call_kwargs.kwargs


async def test_help_command_sends_help(mock_update, mock_context):
    from src.handlers.commands import help_command

    with patch(f"{MODULE}._get_system_info", new_callable=AsyncMock, return_value=("1.0.0", "testuser", "0.2.0")):
        with patch("src.ui.menus.get_help_content", return_value="help text"):
            await help_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once_with("help text")


async def test_usage_command_sends_report(mock_update, mock_context, mock_service):
    from src.handlers.commands import usage_command

    await usage_command(mock_update, mock_context)

    mock_service.get_usage_report.assert_awaited_once()
    mock_update.message.reply_text.assert_called_once_with("usage report")


async def test_clear_command_resets_session(mock_update, mock_context, mock_service):
    from src.handlers.commands import clear_command

    await clear_command(mock_update, mock_context)

    mock_service.set_mode.assert_awaited_once_with("interactive")
    mock_service.deselect_agent.assert_awaited_once()
    mock_service.reset_session.assert_awaited_once()
    args = mock_update.message.reply_text.call_args.args[0]
    assert "Session Cleared" in args


async def test_cancel_command_no_session(mock_update, mock_context, mock_service):
    from src.handlers.commands import cancel_command

    mock_service.session = None

    await cancel_command(mock_update, mock_context)

    args = mock_update.message.reply_text.call_args.args[0]
    assert "No active session" in args


async def test_cwd_command_shows_directory(mock_update, mock_context, mock_service):
    from src.handlers.commands import cwd_command

    await cwd_command(mock_update, mock_context)

    reply = mock_update.message.reply_text.call_args.args[0]
    assert mock_service.get_working_directory() in reply
