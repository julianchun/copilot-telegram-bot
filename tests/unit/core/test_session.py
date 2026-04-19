"""Unit tests for src.core.session module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
        self.cleanup_temp_dir = MagicMock()
        self._handle_event = MagicMock()
        self.allow_all_tools = False


# ── _TOOL_ALLOWLIST ───────────────────────────────────────────────────

class TestToolAllowlist:
    def test_tool_allowlist_contains_expected(self):
        expected = {
            "report_intent", "task", "view", "glob", "grep",
            "fetch_copilot_cli_documentation", "ask_user", "update_todo", "edit",
        }
        assert _TOOL_ALLOWLIST == expected


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


# ── _create_session ──────────────────────────────────────────────────

class TestCreateSession:
    async def test_create_session_registers_existing_project_skill_roots(self, tmp_path):
        svc = FakeService()
        svc.client.create_session = AsyncMock(return_value=MagicMock())

        (tmp_path / ".github" / "skills").mkdir(parents=True)
        (tmp_path / "skills").mkdir()

        with patch("src.core.session.ctx.root_path", str(tmp_path)):
            await svc._create_session()

        skill_dirs = svc.client.create_session.await_args.kwargs["skill_directories"]
        assert str(tmp_path / ".github" / "skills") in skill_dirs
        assert str(tmp_path / "skills") in skill_dirs

    async def test_create_session_keeps_skill_directories_unique(self, tmp_path):
        svc = FakeService()
        svc.client.create_session = AsyncMock(return_value=MagicMock())

        (tmp_path / ".github" / "skills").mkdir(parents=True)
        (tmp_path / "skills").mkdir()

        with patch("src.core.session.ctx.root_path", str(tmp_path)):
            await svc._create_session()

        skill_dirs = svc.client.create_session.await_args.kwargs["skill_directories"]
        assert len(skill_dirs) == len(set(skill_dirs))
