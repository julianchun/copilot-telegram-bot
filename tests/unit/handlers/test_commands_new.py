"""Unit tests for /ping, /allowall, /instructions commands."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


def _service_patches(mock_service):
    """Return combined patches for service in commands, callbacks, and utils modules."""
    return (
        patch("src.handlers.commands.service", mock_service),
        patch("src.handlers.callbacks.service", mock_service),
        patch("src.handlers.utils.service", mock_service),
        patch("src.handlers.utils.ALLOWED_USER_ID", 12345),
    )


# ---------------------------------------------------------------------------
# /ping
# ---------------------------------------------------------------------------

class TestPingCommand:
    async def test_ping_all_healthy(self, mock_update, mock_context, mock_service):
        mock_service._is_running = True
        mock_service.session = MagicMock()
        mock_service.session_expired = False
        mock_service.session.rpc.model.get_current = AsyncMock()

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import ping_command
            await ping_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "🏓 Pong!" in text
        assert "🟢 Running" in text
        assert "🟢 Active" in text
        assert "🟢 OK" in text

    async def test_ping_client_not_running(self, mock_update, mock_context, mock_service):
        mock_service._is_running = False
        mock_service.session = None
        mock_service.session_expired = False

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import ping_command
            await ping_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "🔴 Not running" in text
        assert "🔴 None" in text

    async def test_ping_no_project_still_works(self, mock_update, mock_context, mock_service):
        """Ping does NOT require project selection."""
        mock_service.project_selected = False
        mock_service._is_running = True
        mock_service.session = None
        mock_service.session_expired = False

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import ping_command
            await ping_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        text = mock_update.message.reply_text.call_args[0][0]
        assert "🏓 Pong!" in text

    async def test_ping_rpc_error(self, mock_update, mock_context, mock_service):
        mock_service._is_running = True
        mock_service.session = MagicMock()
        mock_service.session_expired = False
        mock_service.session.rpc.model.get_current = AsyncMock(side_effect=Exception("timeout"))

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import ping_command
            await ping_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "🔴 Error" in text


# ---------------------------------------------------------------------------
# /allowall
# ---------------------------------------------------------------------------

class TestAllowallCommand:
    async def test_toggle_on(self, mock_update, mock_context, mock_service):
        mock_service.allow_all_tools = False
        mock_service.project_selected = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import allowall_command
            await allowall_command(mock_update, mock_context)

        assert mock_service.allow_all_tools is True
        text = mock_update.message.reply_text.call_args[0][0]
        assert "ON" in text

    async def test_toggle_off(self, mock_update, mock_context, mock_service):
        mock_service.allow_all_tools = True
        mock_service.project_selected = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import allowall_command
            await allowall_command(mock_update, mock_context)

        assert mock_service.allow_all_tools is False
        text = mock_update.message.reply_text.call_args[0][0]
        assert "OFF" in text

    async def test_requires_project(self, mock_update, mock_context, mock_service):
        mock_service.project_selected = False
        mock_service.allow_all_tools = False

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import allowall_command
            await allowall_command(mock_update, mock_context)

        # allow_all_tools should NOT have been toggled
        assert mock_service.allow_all_tools is False


# ---------------------------------------------------------------------------
# /instructions
# ---------------------------------------------------------------------------

class TestInstructionsCommand:
    async def test_with_file_shows_active_status(self, mock_update, mock_context, mock_service, tmp_path):
        instructions_dir = tmp_path / ".github"
        instructions_dir.mkdir()
        instructions_file = instructions_dir / "copilot-instructions.md"
        instructions_file.write_text("Use pytest for testing.\n")

        mock_service.get_working_directory = MagicMock(return_value=str(tmp_path))
        mock_service.project_selected = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import instructions_command
            await instructions_command(mock_update, mock_context)

        call_kwargs = mock_update.message.reply_text.call_args
        text = call_kwargs[0][0]
        assert "Active" in text
        assert "Custom Instructions" in text
        # Should have inline keyboard with View and Clear buttons
        assert "reply_markup" in call_kwargs[1]

    async def test_no_file_shows_not_found(self, mock_update, mock_context, mock_service, tmp_path):
        mock_service.get_working_directory = MagicMock(return_value=str(tmp_path))
        mock_service.project_selected = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import instructions_command
            await instructions_command(mock_update, mock_context)

        call_kwargs = mock_update.message.reply_text.call_args
        text = call_kwargs[0][0]
        assert "No custom instructions found" in text
        # Should have inline keyboard with Generate button
        assert "reply_markup" in call_kwargs[1]

    async def test_requires_project(self, mock_update, mock_context, mock_service):
        mock_service.project_selected = False

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import instructions_command
            await instructions_command(mock_update, mock_context)

        # The check_project_selected decorator replies with a warning
        calls = mock_update.message.reply_text.call_args_list
        assert len(calls) == 1
        assert "project" in calls[0][0][0].lower() or "select" in calls[0][0][0].lower()


# ---------------------------------------------------------------------------
# Instructions callbacks
# ---------------------------------------------------------------------------

class TestInstructionsCallbacks:
    async def test_view_callback(self, mock_callback_query, mock_update, mock_context, mock_service, tmp_path):
        instructions_dir = tmp_path / ".github"
        instructions_dir.mkdir()
        instructions_file = instructions_dir / "copilot-instructions.md"
        instructions_file.write_text("Use pytest for testing.\n")

        mock_callback_query.data = "instr:view"
        mock_service.get_working_directory = MagicMock(return_value=str(tmp_path))

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_instructions_callback
            await _handle_instructions_callback(mock_callback_query, mock_update, mock_context)

        text = mock_callback_query.edit_message_text.call_args[0][0]
        assert "Use pytest for testing." in text

    async def test_clear_callback(self, mock_callback_query, mock_update, mock_context, mock_service, tmp_path):
        instructions_dir = tmp_path / ".github"
        instructions_dir.mkdir()
        instructions_file = instructions_dir / "copilot-instructions.md"
        instructions_file.write_text("old instructions\n")

        mock_callback_query.data = "instr:clear"
        mock_service.get_working_directory = MagicMock(return_value=str(tmp_path))
        mock_service.reset_session = AsyncMock()

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_instructions_callback
            await _handle_instructions_callback(mock_callback_query, mock_update, mock_context)

        assert not instructions_file.exists()
        mock_service.reset_session.assert_awaited_once()
        text = mock_callback_query.edit_message_text.call_args[0][0]
        assert "cleared" in text

    async def test_clear_no_file(self, mock_callback_query, mock_update, mock_context, mock_service, tmp_path):
        mock_callback_query.data = "instr:clear"
        mock_service.get_working_directory = MagicMock(return_value=str(tmp_path))

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_instructions_callback
            await _handle_instructions_callback(mock_callback_query, mock_update, mock_context)

        text = mock_callback_query.edit_message_text.call_args[0][0]
        assert "No custom instructions" in text


# ---------------------------------------------------------------------------
# Permission bridge with allow_all_tools
# ---------------------------------------------------------------------------

class TestPermissionBridgeAllowAll:
    async def test_allow_all_bypasses_permission(self):
        """When allow_all_tools is True, _permission_bridge auto-approves everything."""
        import asyncio
        from src.core.session import SessionMixin

        class FakeService(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.session = MagicMock()
                self.session_id = "test-123"
                self.session_info = MagicMock()
                self._is_running = True
                self._usage_unsubscribe = None
                self.current_model = "gpt-4.1"
                self.user_selected_model = None
                self.current_reasoning_effort = None
                self.interaction_callback = None
                self.session_expired = False
                self.session_end_callback = None
                self.usage_tracker = MagicMock()
                self._tool_call_names = {}
                self._chat_lock = asyncio.Lock()
                self.last_session_usage = None
                self.last_assistant_usage = None
                self.current_mode = "general"
                self.cleanup_temp_dir = MagicMock()
                self._handle_event = MagicMock()
                self.allow_all_tools = True

        svc = FakeService()
        result = await svc._permission_bridge(
            {"toolName": "bash", "toolArgs": {"command": "rm -rf /"}}, MagicMock(),
        )
        assert result == {"permissionDecision": "allow"}
