"""Unit tests for /ping, /allowall, /instructions commands."""

from datetime import datetime
from types import SimpleNamespace
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
# /resume, /attach
# ---------------------------------------------------------------------------

class TestSessionAttachmentCommands:
    async def test_resume_empty(self, mock_update, mock_context, mock_service):
        mock_service.list_copilot_sessions = AsyncMock(return_value=[])

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import resume_command
            await resume_command(mock_update, mock_context)

        msg = mock_update.message.reply_text.return_value
        assert "No Copilot sessions" in msg.edit_text.call_args.args[0]

    async def test_resume_populated(self, mock_update, mock_context, mock_service):
        session = SimpleNamespace(
            sessionId="abc123456789",
            summary="Fix tests",
            selectedModel="gpt-5.4",
            modifiedTime="2026-05-18T12:00:00+00:00",
            context=SimpleNamespace(cwd="/repo/app", branch="main"),
        )
        mock_service.list_copilot_sessions = AsyncMock(return_value=[session])

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import resume_command
            await resume_command(mock_update, mock_context)

        msg = mock_update.message.reply_text.return_value
        text = msg.edit_text.call_args.args[0]
        assert "Resume Session" in text
        assert "Mode:" not in text
        assert "Fix tests" in text
        assert "gpt-5.4" not in text
        expected_time = datetime.fromisoformat("2026-05-18T12:00:00+00:00").astimezone().strftime("%m/%d %H:%M")
        assert expected_time in text
        assert "2026-05-18T12:00:00" not in text
        assert "reply_markup" in msg.edit_text.call_args.kwargs

    async def test_attach_session_id(self, mock_update, mock_context, mock_service):
        mock_context.args = ["abc123"]
        mock_service.attach_session = AsyncMock()
        mock_service.populate_session_metadata = AsyncMock()
        mock_service.get_session_info.return_value = mock_service.session_info

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import attach_command
            await attach_command(mock_update, mock_context)

        mock_service.attach_session.assert_awaited_once_with("abc123")
        msg = mock_update.message.reply_text.return_value
        assert "Session Attached" in msg.edit_text.call_args.args[0]
        assert "Send a message to continue." in msg.edit_text.call_args.args[0]
        assert "reply_markup" not in msg.edit_text.call_args.kwargs

    async def test_attach_usage_excludes_foreground(self, mock_update, mock_context, mock_service):
        mock_context.args = []

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import attach_command
            await attach_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args.args[0]
        assert "Usage: /attach <session_id|last>" in text
        assert "foreground" not in text

    async def test_attach_last_empty(self, mock_update, mock_context, mock_service):
        mock_context.args = ["last"]
        mock_service.attach_last_session = AsyncMock(side_effect=RuntimeError("no sessions found"))

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import attach_command
            await attach_command(mock_update, mock_context)

        msg = mock_update.message.reply_text.return_value
        assert "No Copilot sessions" in msg.edit_text.call_args.args[0]

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

    async def test_read_error_returns_user_facing_message(self, mock_update, mock_context, mock_service, tmp_path):
        instructions_dir = tmp_path / ".github"
        instructions_dir.mkdir()
        instructions_file = instructions_dir / "copilot-instructions.md"
        instructions_file.write_text("Use pytest for testing.\n")

        mock_service.get_working_directory = MagicMock(return_value=str(tmp_path))
        mock_service.project_selected = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3], \
             patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
            from src.handlers.commands import instructions_command
            await instructions_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "Failed to read custom instructions" in text

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


class TestSessionAttachmentCallbacks:
    async def test_session_attach_callback(self, mock_callback_query, mock_context, mock_service):
        mock_callback_query.data = "sessattach:abc123"
        mock_service.attach_session = AsyncMock()
        mock_service.populate_session_metadata = AsyncMock()
        mock_service.get_session_info.return_value = mock_service.session_info

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_session_attach_callback
            await _handle_session_attach_callback(mock_callback_query, mock_context)

        mock_service.attach_session.assert_awaited_once_with("abc123")
        assert "Session Attached" in mock_callback_query.edit_message_text.call_args.args[0]
        assert "Send a message to continue." in mock_callback_query.edit_message_text.call_args.args[0]
        assert "reply_markup" not in mock_callback_query.edit_message_text.call_args.kwargs

    async def test_session_picker_page_callback(self, mock_callback_query, mock_context, mock_service):
        mock_callback_query.data = "sessions_page:0"
        sessions = [
            SimpleNamespace(
                sessionId=f"session-{index}",
                summary=f"Session {index}",
                modifiedTime=f"2026-05-18T12:0{index}:00+00:00",
                context=SimpleNamespace(cwd=f"/repo/app-{index}", branch="main"),
            )
            for index in range(7)
        ]
        mock_service.list_copilot_sessions = AsyncMock(return_value=sessions)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_sessions_page_callback
            await _handle_sessions_page_callback(mock_callback_query, mock_context)

        text = mock_callback_query.edit_message_text.call_args.args[0]
        assert "Session 6" in text
        assert "Session 1" in text
        assert "Session 0" not in text
        assert "Mode:" not in text
        keyboard = mock_callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        buttons = [
            button
            for row in keyboard.inline_keyboard
            for button in row
        ]
        numbered_buttons = [button for button in buttons if button.text.isdigit()]
        assert [button.text for button in numbered_buttons] == ["1", "2", "3", "4", "5", "6"]
        assert all(button.callback_data.startswith("sessdetail:") for button in numbered_buttons)
        assert all(not button.callback_data.startswith("sessattach:") for button in buttons)
        assert all(not button.callback_data.startswith("sessshow:") for button in buttons)
        assert "Foreground" not in [button.text for button in buttons]
        assert "Last" not in [button.text for button in buttons]

    async def test_session_detail_callback(self, mock_callback_query, mock_context, mock_service):
        mock_callback_query.data = "sessdetail:abc123456789"
        mock_service.list_copilot_sessions = AsyncMock(return_value=[
            SimpleNamespace(
                sessionId="abc123456789",
                summary="Fix tests",
                startTime="2026-05-18T11:00:00",
                modifiedTime="2026-05-18T12:00:00",
                context=SimpleNamespace(cwd="/repo/app", branch="main"),
                selectedModel="gpt-5.4",
            )
        ])

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_session_detail_callback
            await _handle_session_detail_callback(mock_callback_query, mock_context)

        text = mock_callback_query.edit_message_text.call_args.args[0]
        assert "Session Details" in text
        assert "abc123456789" in text
        assert "Fix tests" in text
        assert "Created: unknown time" not in text
        keyboard = mock_callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        button_texts = [
            button.text
            for row in keyboard.inline_keyboard
            for button in row
        ]
        assert button_texts == ["Attach", "⬅ Back"]


# ---------------------------------------------------------------------------
# Permission bridge with allow_all_tools
# ---------------------------------------------------------------------------

class TestPermissionBridgeAllowAll:
    async def test_allow_all_bypasses_permission(self):
        """When allow_all_tools is True, non-URL requests are approved once."""
        import asyncio
        from copilot.rpc import PermissionDecisionApproveOnce
        from src.core.session import SessionMixin

        class FakeService(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.session = MagicMock()
                self.session_id = "test-123"
                self.session_info = MagicMock()
                self._is_running = True
                self._usage_unsubscribe = None
                self.current_model = "gpt-5.4"
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
        result = await svc._permission_request_bridge(
            SimpleNamespace(kind="shell", full_command_text="rm -rf /"),
            MagicMock(),
        )
        assert isinstance(result, PermissionDecisionApproveOnce)

    async def test_allow_all_does_not_bypass_url_permission(self):
        """URL permission requests still require Telegram approval."""
        import asyncio
        from copilot.rpc import PermissionDecisionUserNotAvailable
        from src.core.session import SessionMixin

        class FakeService(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.session = MagicMock()
                self.session_id = "test-123"
                self.session_info = MagicMock()
                self._is_running = True
                self._usage_unsubscribe = None
                self.current_model = "gpt-5.4"
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
        result = await svc._permission_request_bridge(
            SimpleNamespace(kind="url", url="https://example.com"),
            MagicMock(),
        )
        assert isinstance(result, PermissionDecisionUserNotAvailable)


# ---------------------------------------------------------------------------
# /autopilot
# ---------------------------------------------------------------------------

class TestAutopilotCommand:
    async def test_toggle_on(self, mock_update, mock_context, mock_service):
        mock_context.args = []
        mock_service.current_mode = "interactive"
        mock_service.set_mode.return_value = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import autopilot_command
            await autopilot_command(mock_update, mock_context)

        mock_service.set_mode.assert_awaited_once_with("autopilot")
        text = mock_update.message.reply_text.call_args[0][0]
        assert "Autopilot Mode" in text

    async def test_toggle_off(self, mock_update, mock_context, mock_service):
        mock_context.args = []
        mock_service.current_mode = "autopilot"
        mock_service.set_mode.return_value = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import autopilot_command
            await autopilot_command(mock_update, mock_context)

        mock_service.set_mode.assert_awaited_once_with("interactive")
        text = mock_update.message.reply_text.call_args[0][0]
        assert "Edit" in text

    async def test_force_on_with_prompt(self, mock_update, mock_context, mock_service):
        mock_context.args = ["do", "stuff"]
        mock_service.set_mode.return_value = True

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3], \
             patch("src.handlers.commands.chat_handler", new_callable=AsyncMock) as mock_chat:
            from src.handlers.commands import autopilot_command
            await autopilot_command(mock_update, mock_context)

        mock_service.set_mode.assert_awaited_once_with("autopilot")
        mock_chat.assert_awaited_once_with(mock_update, mock_context, override_text="do stuff")
