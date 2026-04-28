"""Integration tests for command handlers in src/handlers/commands.py."""

import io
import pytest
from pathlib import Path
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


# ── /session subcommand tests ─────────────────────────────────────────


class TestSessionCommand:
    """Tests for /session [info|files|plan] subcommands."""

    async def test_session_no_args_shows_info(self, mock_update, mock_context, mock_service):
        """Default (no args) should show session info."""
        from src.handlers.commands import session_command

        mock_context.args = []
        mock_service.populate_session_metadata = AsyncMock()
        mock_service.get_session_info.return_value = mock_service.session_info
        mock_service.usage_tracker.model_usage = {}
        mock_service.usage_tracker.current_tokens = 0
        mock_service.usage_tracker.token_limit = 0
        mock_service.usage_tracker.get_quota_summary = MagicMock(return_value="")
        mock_service.usage_tracker.get_usage_summary = AsyncMock(return_value="summary")

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "Session Info" in reply
        assert "test-1234" in reply

    async def test_session_info_explicit(self, mock_update, mock_context, mock_service):
        """Explicit 'info' arg should show session info."""
        from src.handlers.commands import session_command

        mock_context.args = ["info"]
        mock_service.populate_session_metadata = AsyncMock()
        mock_service.get_session_info.return_value = mock_service.session_info
        mock_service.usage_tracker.model_usage = {}
        mock_service.usage_tracker.current_tokens = 0
        mock_service.usage_tracker.token_limit = 0
        mock_service.usage_tracker.get_quota_summary = MagicMock(return_value="")
        mock_service.usage_tracker.get_usage_summary = AsyncMock(return_value="summary")

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "Session Info" in reply

    async def test_session_files_no_workspace(self, mock_update, mock_context, mock_service):
        """/session files when workspace_path is None."""
        from src.handlers.commands import session_command

        mock_context.args = ["files"]
        mock_service.session.workspace_path = None

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "not available" in reply
        assert "infinite sessions" in reply

    async def test_session_files_with_workspace(self, mock_update, mock_context, mock_service, tmp_path):
        """/session files lists workspace files."""
        from src.handlers.commands import session_command

        files_dir = tmp_path / "files"
        files_dir.mkdir()
        (files_dir / "notes.txt").write_text("hello")
        (files_dir / "data.json").write_text('{"key": "value"}')

        mock_context.args = ["files"]
        # Use string path to verify str→Path conversion
        mock_service.session.workspace_path = str(tmp_path)

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "data.json" in reply
        assert "notes.txt" in reply

    async def test_session_files_empty_workspace(self, mock_update, mock_context, mock_service, tmp_path):
        """/session files when workspace files/ is empty."""
        from src.handlers.commands import session_command

        files_dir = tmp_path / "files"
        files_dir.mkdir()

        mock_context.args = ["files"]
        mock_service.session.workspace_path = tmp_path

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "empty" in reply

    async def test_session_plan_no_workspace(self, mock_update, mock_context, mock_service):
        """/session plan when workspace_path is None."""
        from src.handlers.commands import session_command

        mock_context.args = ["plan"]
        mock_service.session.workspace_path = None

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "not available" in reply

    async def test_session_plan_shows_content(self, mock_update, mock_context, mock_service, tmp_path):
        """/session plan shows plan.md content inline."""
        from src.handlers.commands import session_command

        (tmp_path / "plan.md").write_text("# My Plan\n\n- Step 1\n- Step 2")
        mock_context.args = ["plan"]
        # Use string path to verify str→Path conversion
        mock_service.session.workspace_path = str(tmp_path)

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "My Plan" in reply
        assert "Step 1" in reply

    async def test_session_plan_no_plan_file(self, mock_update, mock_context, mock_service, tmp_path):
        """/session plan when plan.md doesn't exist."""
        from src.handlers.commands import session_command

        mock_context.args = ["plan"]
        mock_service.session.workspace_path = tmp_path

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "No plan found" in reply

    async def test_session_plan_empty_file(self, mock_update, mock_context, mock_service, tmp_path):
        """/session plan when plan.md exists but is empty or whitespace-only."""
        from src.handlers.commands import session_command

        (tmp_path / "plan.md").write_text("   \n\n  ")
        mock_context.args = ["plan"]
        mock_service.session.workspace_path = tmp_path

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "empty" in reply

    async def test_session_plan_large_sends_file(self, mock_update, mock_context, mock_service, tmp_path):
        """/session plan sends file when content exceeds Telegram limit."""
        from src.handlers.commands import session_command

        large_content = "x" * 5000
        (tmp_path / "plan.md").write_text(large_content)
        mock_context.args = ["plan"]
        mock_service.session.workspace_path = tmp_path
        mock_update.message.reply_document = AsyncMock()

        await session_command(mock_update, mock_context)

        mock_update.message.reply_document.assert_called_once()
        call_kwargs = mock_update.message.reply_document.call_args.kwargs
        assert "plan" in call_kwargs.get("caption", "").lower()

    async def test_session_unknown_subcommand(self, mock_update, mock_context, mock_service):
        """Unknown subcommand shows help text."""
        from src.handlers.commands import session_command

        mock_context.args = ["foobar"]

        await session_command(mock_update, mock_context)

        reply = mock_update.message.reply_text.call_args.args[0]
        assert "subcommands" in reply
        assert "/session info" in reply
        assert "/session files" in reply
        assert "/session plan" in reply
