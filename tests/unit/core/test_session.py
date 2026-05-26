"""Unit tests for src.core.session module."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import ctx
from src.core.session import SessionMixin, _TOOL_ALLOWLIST


class FakeService(SessionMixin):
    """Minimal stand-in that satisfies SessionMixin's attribute contract."""

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
        self.current_mode = "interactive"
        self.current_agent = None
        self.session_id = "test-123"
        self._cancelled = False
        self.cleanup_temp_dir = MagicMock()
        self._handle_event = MagicMock()
        self.allow_all_tools = False


# ── _TOOL_ALLOWLIST ───────────────────────────────────────────────────

class TestToolAllowlist:
    def test_tool_allowlist_contains_expected(self):
        expected = {
            "report_intent", "task", "view", "glob", "grep",
            "fetch_copilot_cli_documentation", "ask_user", "update_todo", "edit",
            "list_files", "sql",
        }
        assert _TOOL_ALLOWLIST == expected


# ── lifecycle disconnect ─────────────────────────────────────────────

class TestLifecycleDisconnect:
    async def test_stop_uses_disconnect_not_destroy(self):
        svc = FakeService()
        svc.client.stop = AsyncMock()
        svc.session.disconnect = AsyncMock()
        svc.session.destroy = AsyncMock()
        session = svc.session

        await svc.stop()

        session.disconnect.assert_awaited_once()
        session.destroy.assert_not_awaited()
        svc.client.stop.assert_awaited_once()


# ── _permission_bridge ────────────────────────────────────────────────

class TestPermissionBridge:
    async def test_permission_bridge_auto_approves_allowlisted(self):
        svc = FakeService()
        result = await svc._permission_bridge(
            {"toolName": "view", "toolArgs": {}}, MagicMock(),
        )
        assert result == {"permissionDecision": "allow"}

    async def test_permission_bridge_asks_for_non_allowlisted(self):
        svc = FakeService()
        svc.interaction_callback = AsyncMock(return_value=True)
        result = await svc._permission_bridge(
            {"toolName": "bash", "toolArgs": {"command": "ls"}}, MagicMock(),
        )
        assert result == {"permissionDecision": "allow"}
        svc.interaction_callback.assert_awaited_once()

    async def test_permission_bridge_user_denies(self):
        svc = FakeService()
        svc.interaction_callback = AsyncMock(return_value=False)
        result = await svc._permission_bridge(
            {"toolName": "bash", "toolArgs": {}}, MagicMock(),
        )
        assert result == {"permissionDecision": "deny"}

    async def test_permission_bridge_no_callback_auto_approves(self):
        svc = FakeService()
        svc.interaction_callback = None
        result = await svc._permission_bridge(
            {"toolName": "bash", "toolArgs": {}}, MagicMock(),
        )
        assert result == {"permissionDecision": "allow"}

    async def test_permission_bridge_timeout_denies(self):
        async def _hang(*a, **kw):
            await asyncio.sleep(999)

        svc = FakeService()
        svc.interaction_callback = _hang

        with patch("src.core.session.PERMISSION_TIMEOUT", 0.01):
            result = await svc._permission_bridge(
                {"toolName": "bash", "toolArgs": {}}, MagicMock(),
            )
        assert result == {"permissionDecision": "deny"}


# ── _user_input_bridge ────────────────────────────────────────────────

class TestUserInputBridge:
    async def test_user_input_bridge_with_callback(self):
        svc = FakeService()
        svc.interaction_callback = AsyncMock(return_value="yes please")

        request = {"question": "Continue?", "choices": [], "allowFreeform": True}
        result = await svc._user_input_bridge(request, MagicMock())

        assert result["answer"] == "yes please"
        assert result["wasFreeform"] is True
        svc.interaction_callback.assert_awaited_once()

    async def test_user_input_bridge_no_callback(self):
        svc = FakeService()
        svc.interaction_callback = None

        result = await svc._user_input_bridge(
            {"question": "Q?"}, MagicMock(),
        )
        assert result == {"answer": "", "wasFreeform": False}

    async def test_user_input_bridge_timeout(self):
        async def _hang(*a, **kw):
            await asyncio.sleep(999)

        svc = FakeService()
        svc.interaction_callback = _hang

        with patch("src.core.session.INTERACTION_TIMEOUT", 0.01):
            result = await svc._user_input_bridge(
                {"question": "Q?", "choices": [], "allowFreeform": True},
                MagicMock(),
            )
        assert result == {"answer": "", "wasFreeform": False}

    async def test_user_input_bridge_cancel_response(self):
        svc = FakeService()
        svc.interaction_callback = AsyncMock(return_value="cancel")

        request = {"question": "Continue?", "choices": [], "allowFreeform": True}
        result = await svc._user_input_bridge(request, MagicMock())

        # "cancel" is treated as empty answer, but wasFreeform is computed
        # independently (allowFreeform=True and "cancel" not in choices=[])
        assert result["answer"] == ""
        assert result["wasFreeform"] is True


# ── _on_session_end ───────────────────────────────────────────────────

class TestOnSessionEnd:
    async def test_on_session_end_timeout(self):
        svc = FakeService()
        svc.session_end_callback = AsyncMock()

        await svc._on_session_end({"reason": "timeout"}, MagicMock())

        assert svc.session_expired is True
        svc.session_end_callback.assert_awaited_once()
        msg = svc.session_end_callback.call_args[0][0]
        assert "expired" in msg.lower()

    async def test_on_session_end_error(self):
        svc = FakeService()
        svc.session_end_callback = AsyncMock()

        await svc._on_session_end(
            {"reason": "error", "error": "something broke"}, MagicMock(),
        )

        assert svc.session_expired is True
        msg = svc.session_end_callback.call_args[0][0]
        assert "something broke" in msg

    async def test_on_session_end_other_reason(self):
        svc = FakeService()
        svc.session_end_callback = AsyncMock()

        await svc._on_session_end({"reason": "user_closed"}, MagicMock())

        assert svc.session_expired is False
        svc.session_end_callback.assert_not_awaited()

    async def test_on_session_end_no_callback(self):
        svc = FakeService()
        svc.session_end_callback = None

        await svc._on_session_end({"reason": "timeout"}, MagicMock())

        assert svc.session_expired is True


# ── populate_session_metadata ───────────────────────────────────────────

class TestPopulateSessionMetadata:
    async def test_populate_session_metadata_uses_direct_lookup(self):
        svc = FakeService()
        svc.session_info.session_id = "session-123"
        meta = MagicMock(summary="Test Session", startTime="2026-05-03T00:00:00", modifiedTime="2026-05-03T00:01:00")
        svc.client.get_session_metadata = AsyncMock(return_value=meta)

        await svc.populate_session_metadata()

        svc.client.get_session_metadata.assert_awaited_once_with("session-123")
        assert svc.session_info.name == "Test Session"
        assert svc.session_info.created == "2026-05-03T00:00:00"
        assert svc.session_info.modified == "2026-05-03T00:01:00"


# ── _create_session ──────────────────────────────────────────────────

class TestCreateSession:
    async def test_create_session_registers_cli_compatible_skill_roots(self, tmp_path):
        svc = FakeService()
        svc.client.create_session = AsyncMock(return_value=MagicMock())
        fake_home = tmp_path / "home"

        with (
            patch("src.core.session.ctx.root_path", str(tmp_path)),
            patch("src.core.session.Path.home", return_value=fake_home),
        ):
            await svc._create_session()

        skill_dirs = svc.client.create_session.await_args.kwargs["skill_directories"]
        assert str(fake_home / ".copilot" / "skills") in skill_dirs
        assert str(fake_home / ".agents" / "skills") in skill_dirs
        assert str(tmp_path / ".github" / "skills") in skill_dirs
        assert str(tmp_path / ".claude" / "skills") in skill_dirs
        assert str(tmp_path / ".agents" / "skills") in skill_dirs
        assert str(tmp_path / "skills") not in skill_dirs
        assert str(fake_home / ".claude" / "skills") not in skill_dirs

    async def test_create_session_enables_config_discovery(self, tmp_path):
        svc = FakeService()
        svc.client.create_session = AsyncMock(return_value=MagicMock())

        with patch("src.core.session.ctx.root_path", str(tmp_path)):
            await svc._create_session()

        assert svc.client.create_session.await_args.kwargs["enable_config_discovery"] is True


# ── attach_session ──────────────────────────────────────────────────

class TestAttachSession:
    async def test_attach_current_session_is_noop(self):
        svc = FakeService()
        svc.session.session_id = "test-123"
        svc.session.disconnect = AsyncMock()
        svc.client.resume_session = AsyncMock()
        svc.client.get_session_metadata = AsyncMock(return_value=None)
        svc.session_expired = True
        svc._cancelled = True

        result = await svc.attach_session("test-123")

        assert result is svc.session
        svc.client.resume_session.assert_not_awaited()
        svc.session.disconnect.assert_not_awaited()
        assert svc.session_expired is False
        assert svc._cancelled is False

    async def test_attach_current_session_refreshes_workspace_from_metadata(self, tmp_path):
        svc = FakeService()
        svc.session.session_id = "test-123"
        target_dir = tmp_path / "target" / "project"
        target_dir.mkdir(parents=True)
        metadata = SimpleNamespace(
            sessionId="test-123",
            context=SimpleNamespace(cwd=str(target_dir), branch="feature"),
        )
        svc.client.get_session_metadata = AsyncMock(return_value=metadata)
        svc.client.resume_session = AsyncMock()

        with patch("src.core.session.ctx.root_path", tmp_path), \
             patch("src.core.session.WORKSPACE_PATH", tmp_path), \
             patch("src.core.session.GRANTED_PROJECT_PATHS", []):
            await svc.attach_session("test-123")
            assert ctx.root_path == target_dir.resolve()

        svc.client.resume_session.assert_not_awaited()
        assert svc.session_info.cwd == str(target_dir)
        assert svc.session_info.branch == "feature"

    async def test_attach_rejects_during_chat(self):
        svc = FakeService()

        async with svc._chat_lock:
            try:
                await svc.attach_session("session-456")
            except RuntimeError as e:
                assert "request in progress" in str(e)
            else:
                raise AssertionError("attach_session should reject while chat lock is held")

    async def test_attach_last_rejects_during_chat(self):
        svc = FakeService()

        async with svc._chat_lock:
            try:
                await svc.attach_last_session()
            except RuntimeError as e:
                assert "request in progress" in str(e)
            else:
                raise AssertionError("attach_last_session should reject while chat lock is held")

    async def test_attach_uses_resume_with_pending_work_and_shared_options(self, tmp_path):
        svc = FakeService()
        target_dir = tmp_path / "target" / "project"
        target_dir.mkdir(parents=True)
        old_session = MagicMock()
        old_session.disconnect = AsyncMock()
        svc.session = old_session
        new_session = MagicMock()
        new_session.session_id = "session-456"
        new_session.on = MagicMock(return_value=lambda: None)
        svc.client.resume_session = AsyncMock(return_value=new_session)
        metadata = SimpleNamespace(
            sessionId="session-456",
            summary="Existing work",
            context=SimpleNamespace(cwd=str(target_dir), branch="feature"),
        )
        svc.client.get_session_metadata = AsyncMock(return_value=metadata)

        with patch("src.core.session.ctx.root_path", tmp_path), \
             patch("src.core.session.WORKSPACE_PATH", tmp_path), \
             patch("src.core.session.GRANTED_PROJECT_PATHS", []):
            await svc.attach_session("session-456")
            assert ctx.root_path == target_dir.resolve()

        svc.client.resume_session.assert_awaited_once()
        args, kwargs = svc.client.resume_session.await_args
        assert args == ("session-456",)
        assert kwargs["continue_pending_work"] is True
        assert kwargs["on_event"] == svc._handle_event
        assert kwargs["on_user_input_request"] == svc._user_input_bridge
        assert kwargs["hooks"]["on_pre_tool_use"] == svc._permission_bridge
        assert kwargs["working_directory"] == str(target_dir.resolve())
        assert "model" not in kwargs
        old_session.disconnect.assert_awaited_once()
        assert svc.session is new_session
        assert svc.session_expired is False
        assert svc._cancelled is False

    async def test_attach_rejects_session_outside_allowed_workspaces(self, tmp_path):
        svc = FakeService()
        old_session = svc.session
        outside_dir = tmp_path.parent / "outside-project"
        metadata = SimpleNamespace(
            sessionId="session-456",
            summary="Outside workspace",
            context=SimpleNamespace(cwd=str(outside_dir), branch="feature"),
        )
        svc.client.get_session_metadata = AsyncMock(return_value=metadata)
        svc.client.resume_session = AsyncMock()

        with patch("src.core.session.ctx.root_path", tmp_path), \
             patch("src.core.session.WORKSPACE_PATH", tmp_path), \
             patch("src.core.session.GRANTED_PROJECT_PATHS", []):
            with pytest.raises(RuntimeError, match="outside allowed workspaces"):
                await svc.attach_session("session-456")

            assert ctx.root_path == tmp_path

        svc.client.resume_session.assert_not_awaited()
        assert svc.session is old_session

    async def test_attach_requires_metadata_with_cwd(self):
        svc = FakeService()
        old_session = svc.session
        svc.client.get_session_metadata = AsyncMock(return_value=None)
        svc.client.resume_session = AsyncMock()

        with pytest.raises(RuntimeError, match="metadata is missing cwd"):
            await svc.attach_session("session-456")

        svc.client.resume_session.assert_not_awaited()
        assert svc.session is old_session

    async def test_attach_resume_sends_model_when_user_selected(self, tmp_path):
        svc = FakeService()
        svc.user_selected_model = "claude-sonnet-4"
        target_dir = tmp_path / "target" / "project"
        target_dir.mkdir(parents=True)
        new_session = MagicMock()
        new_session.session_id = "session-456"
        new_session.on = MagicMock(return_value=lambda: None)
        svc.client.resume_session = AsyncMock(return_value=new_session)
        svc.client.get_session_metadata = AsyncMock(return_value=SimpleNamespace(
            sessionId="session-456",
            context=SimpleNamespace(cwd=str(target_dir)),
        ))

        with patch("src.core.session.WORKSPACE_PATH", tmp_path), \
             patch("src.core.session.GRANTED_PROJECT_PATHS", []):
            await svc.attach_session("session-456")

        _, kwargs = svc.client.resume_session.await_args
        assert kwargs["model"] == "claude-sonnet-4"
        assert kwargs["working_directory"] == str(target_dir.resolve())

    async def test_failed_attach_leaves_existing_session_intact(self, tmp_path):
        svc = FakeService()
        old_session = svc.session
        target_dir = tmp_path / "target" / "project"
        target_dir.mkdir(parents=True)
        svc.client.get_session_metadata = AsyncMock(return_value=SimpleNamespace(
            sessionId="missing",
            context=SimpleNamespace(cwd=str(target_dir)),
        ))
        svc.client.resume_session = AsyncMock(side_effect=RuntimeError("not found"))

        with patch("src.core.session.WORKSPACE_PATH", tmp_path), \
             patch("src.core.session.GRANTED_PROJECT_PATHS", []):
            try:
                await svc.attach_session("missing")
            except RuntimeError:
                pass
            else:
                raise AssertionError("attach_session should surface resume failures")

        assert svc.session is old_session
