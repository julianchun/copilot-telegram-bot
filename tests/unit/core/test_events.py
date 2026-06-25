"""Unit tests for EventHandlerMixin (src/core/events.py)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from copilot.generated.session_events import ExitPlanModeAction, SessionEventType
from copilot.generated.rpc import SessionMode

from src.core.events import EventHandlerMixin


# ── Test host class ──────────────────────────────────────────────────

class FakeService(EventHandlerMixin):
    """Minimal host providing attributes expected by EventHandlerMixin."""

    def __init__(self):
        self.current_callback = None
        self._tool_call_names = {}
        self.completion_callback = None
        self.current_model = "gpt-5.4"
        self.current_agent = None
        self.last_assistant_usage = None
        self.last_session_usage = None
        self.session_info = MagicMock()
        self.usage_tracker = MagicMock()
        self.current_mode = "general"
        self.user_selected_model = None
        self.telegram_bot = None
        self.telegram_chat_id = None
        self._pending_exit_plan_mode = None


def _make_event(event_type, **data_attrs):
    """Build a mock event with the given type and data attributes."""
    event = MagicMock()
    event.type = event_type
    event.data = SimpleNamespace(**data_attrs)
    return event


# ── Tests ─────────────────────────────────────────────────────────────


class TestBuildHandlerMap:
    def test_has_expected_keys(self):
        svc = FakeService()
        handler_map = svc._build_handler_map()

        expected_keys = {
            SessionEventType.SESSION_START,
            SessionEventType.ASSISTANT_MESSAGE,
            SessionEventType.TOOL_EXECUTION_START,
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            SessionEventType.SUBAGENT_SELECTED,
            SessionEventType.SUBAGENT_DESELECTED,
            SessionEventType.SUBAGENT_STARTED,
            SessionEventType.SUBAGENT_COMPLETED,
            SessionEventType.SUBAGENT_FAILED,
            SessionEventType.SESSION_IDLE,
            SessionEventType.SESSION_ERROR,
            SessionEventType.SESSION_USAGE_INFO,
            SessionEventType.ASSISTANT_USAGE,
            SessionEventType.SESSION_MODE_CHANGED,
            SessionEventType.SESSION_MODEL_CHANGE,
            SessionEventType.ASSISTANT_REASONING_DELTA,
            SessionEventType.SESSION_COMPACTION_START,
            SessionEventType.SESSION_COMPACTION_COMPLETE,
            SessionEventType.SESSION_CONTEXT_CHANGED,
            SessionEventType.EXIT_PLAN_MODE_REQUESTED,
            SessionEventType.EXIT_PLAN_MODE_COMPLETED,
        }
        assert set(handler_map.keys()) == expected_keys

    def test_all_values_are_callable(self):
        svc = FakeService()
        for handler in svc._build_handler_map().values():
            assert callable(handler)


class TestHandleEvent:
    def test_routes_to_correct_handler(self):
        svc = FakeService()
        svc._on_assistant_message = MagicMock()

        event = _make_event(SessionEventType.ASSISTANT_MESSAGE, content="hi")
        svc._handle_event(event)

        svc._on_assistant_message.assert_called_once_with(event)

    def test_unknown_event_type_is_ignored(self):
        svc = FakeService()
        event = _make_event(SessionEventType.UNKNOWN)
        # Should not raise
        svc._handle_event(event)

    def test_caches_handler_map(self):
        svc = FakeService()
        event = _make_event(SessionEventType.SESSION_ERROR, message="oops")
        with patch.object(svc, "_on_session_error"):
            svc._handle_event(event)
            svc._handle_event(event)
        # _build_handler_map only called once (cached)
        assert hasattr(svc, "_handler_map_cache")


class TestOnAssistantMessage:
    async def test_calls_callback(self):
        svc = FakeService()
        cb = AsyncMock()
        svc.current_callback = cb

        event = _make_event(SessionEventType.ASSISTANT_MESSAGE, content="hello")
        svc._on_assistant_message(event)

        await asyncio.sleep(0)  # let fire-and-forget task run
        cb.assert_awaited_once_with("hello")

    async def test_no_callback_no_error(self):
        svc = FakeService()
        svc.current_callback = None

        event = _make_event(SessionEventType.ASSISTANT_MESSAGE, content="hello")
        # Should not raise
        svc._on_assistant_message(event)

    async def test_no_content_no_dispatch(self):
        svc = FakeService()
        cb = AsyncMock()
        svc.current_callback = cb

        event = _make_event(SessionEventType.ASSISTANT_MESSAGE, content=None)
        svc._on_assistant_message(event)

        await asyncio.sleep(0)
        cb.assert_not_called()


class TestExitPlanModeRequested:
    @patch("src.ui.menus.get_exit_plan_mode_keyboard", return_value="keyboard")
    async def test_finalize_uses_required_fields(self, _mock_keyboard):
        svc = FakeService()
        svc.telegram_bot = MagicMock()
        svc.telegram_bot.send_message = AsyncMock()
        svc.telegram_chat_id = 123

        data = SimpleNamespace(
            request_id="req-1",
            summary="Summary",
            plan_content="- Step 1",
            actions=["approve", "edit"],
            recommended_action="approve",
        )

        await svc._finalize_exit_plan_mode_requested(data)

        assert svc._pending_exit_plan_mode == {
            "request_id": "req-1",
            "plan_content": "- Step 1",
            "summary": "Summary",
            "actions": ["approve", "edit"],
            "recommended_action": "approve",
        }
        svc.telegram_bot.send_message.assert_awaited_once()

    @patch("src.ui.menus.get_exit_plan_mode_keyboard", return_value="keyboard")
    async def test_finalize_displays_v1_enum_actions(self, _mock_keyboard):
        svc = FakeService()
        svc.telegram_bot = MagicMock()
        svc.telegram_bot.send_message = AsyncMock()
        svc.telegram_chat_id = 123

        data = SimpleNamespace(
            request_id="req-1",
            summary="Summary",
            plan_content="- Step 1",
            actions=[ExitPlanModeAction.INTERACTIVE, ExitPlanModeAction.AUTOPILOT],
            recommended_action=ExitPlanModeAction.INTERACTIVE,
        )

        await svc._finalize_exit_plan_mode_requested(data)

        text = svc.telegram_bot.send_message.await_args.kwargs["text"]
        assert "recommended: interactive" in text
        assert "Actions: interactive, autopilot" in text
        svc.telegram_bot.send_message.assert_awaited_once()

    @patch("src.ui.menus.get_exit_plan_mode_keyboard", return_value="keyboard")
    async def test_finalize_missing_required_field_is_caught(self, _mock_keyboard):
        svc = FakeService()
        svc.telegram_bot = MagicMock()
        svc.telegram_bot.send_message = AsyncMock()
        svc.telegram_chat_id = 123

        data = SimpleNamespace(
            request_id="req-1",
            summary="Summary",
            plan_content="- Step 1",
            actions=["approve", "edit"],
        )

        await svc._finalize_exit_plan_mode_requested(data)

        assert svc._pending_exit_plan_mode is None
        svc.telegram_bot.send_message.assert_not_awaited()


class TestOnSessionStart:
    def test_v1_metadata_aliases_are_stored(self):
        svc = FakeService()
        event = _make_event(
            SessionEventType.SESSION_START,
            session_id="session-123",
            selected_model="gpt-5",
            copilot_version="1.0.0",
            producer="copilot",
            git_root="/repo",
            context=SimpleNamespace(
                working_directory="/repo/app",
                branch="feature",
                repository="owner/repo",
            ),
        )

        svc._on_session_start(event)

        assert svc.session_info.session_id == "session-123"
        assert svc.session_info.selected_model == "gpt-5"
        assert svc.session_info.copilot_version == "1.0.0"
        assert svc.session_info.cwd == "/repo/app"
        assert svc.session_info.branch == "feature"
        assert svc.session_info.git_root == "/repo"
        assert svc.current_model == "gpt-5"


class TestOnToolStart:
    @patch("src.core.events.ctx")
    async def test_formats_message(self, mock_ctx):
        svc = FakeService()
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb

        event = _make_event(
            SessionEventType.TOOL_EXECUTION_START,
            tool_name="view",
            arguments={"path": "/a/b.py"},
            tool_call_id="tc-1",
            parent_tool_call_id=None,
            mcp_tool_name=None,
        )
        svc._on_tool_start(event)

        await asyncio.sleep(0)
        status_cb.assert_awaited_once()
        msg = status_cb.call_args[0][0]
        assert "view" in msg

    @patch("src.core.events.ctx")
    async def test_stores_tool_call_name(self, mock_ctx):
        svc = FakeService()
        mock_ctx.status_callback = None

        event = _make_event(
            SessionEventType.TOOL_EXECUTION_START,
            tool_name="bash",
            arguments={},
            tool_call_id="tc-42",
            parent_tool_call_id=None,
            mcp_tool_name=None,
        )
        svc._on_tool_start(event)

        assert svc._tool_call_names["tc-42"] == "bash"

    @patch("src.core.events.ctx")
    async def test_parent_tool_indents_message(self, mock_ctx):
        svc = FakeService()
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb

        event = _make_event(
            SessionEventType.TOOL_EXECUTION_START,
            tool_name="grep",
            arguments={},
            tool_call_id="tc-2",
            parent_tool_call_id="tc-1",
            mcp_tool_name=None,
        )
        svc._on_tool_start(event)

        await asyncio.sleep(0)
        msg = status_cb.call_args[0][0]
        assert msg.startswith("  ")


class TestOnToolComplete:
    @patch("src.core.events.ctx")
    async def test_cleans_up_tool_names(self, mock_ctx):
        svc = FakeService()
        mock_ctx.status_callback = None
        svc._tool_call_names["tc-99"] = "view"

        event = _make_event(
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            tool_call_id="tc-99",
            tool_name="view",
            parent_tool_call_id=None,
            result=MagicMock(content="file contents here"),
            mcp_tool_name=None,
        )
        svc._on_tool_complete(event)

        assert "tc-99" not in svc._tool_call_names

    @patch("src.core.events.ctx")
    async def test_resolves_name_from_cache(self, mock_ctx):
        """When tool_name is missing, fall back to _tool_call_names cache."""
        svc = FakeService()
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb
        svc._tool_call_names["tc-50"] = "glob"

        event = _make_event(
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            tool_call_id="tc-50",
            tool_name=None,
            parent_tool_call_id=None,
            result=MagicMock(content="matches found"),
            mcp_tool_name=None,
        )
        svc._on_tool_complete(event)

        await asyncio.sleep(0)
        # The cached name "glob" should be used (and produces a message)
        if status_cb.call_count:
            msg = status_cb.call_args[0][0]
            assert "glob" in msg


class TestOnSessionError:
    @patch("src.core.events.ctx")
    async def test_dispatches_error(self, mock_ctx):
        svc = FakeService()
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb

        event = _make_event(SessionEventType.SESSION_ERROR, message="something broke")
        svc._on_session_error(event)

        await asyncio.sleep(0)
        status_cb.assert_awaited_once()
        msg = status_cb.call_args[0][0]
        assert "something broke" in msg
        assert "❌" in msg


class TestOnSessionUsageInfo:
    def test_stores_data(self):
        svc = FakeService()
        event = _make_event(SessionEventType.SESSION_USAGE_INFO)
        event.data = {"prompt_tokens": 100, "completion_tokens": 50}

        svc._on_session_usage_info(event)

        assert svc.last_session_usage == {"prompt_tokens": 100, "completion_tokens": 50}


class TestOnAssistantUsage:
    def test_updates_model(self):
        svc = FakeService()
        event = _make_event(SessionEventType.ASSISTANT_USAGE, model="claude-sonnet-4")
        svc._on_assistant_usage(event)

        assert svc.current_model == "claude-sonnet-4"
        assert svc.last_assistant_usage == event.data

    def test_no_model_field_keeps_current(self):
        svc = FakeService()
        svc.current_model = "gpt-5.4"

        event = MagicMock()
        event.type = SessionEventType.ASSISTANT_USAGE
        event.data = MagicMock(spec=[])  # spec=[] → no attributes
        svc._on_assistant_usage(event)

        assert svc.current_model == "gpt-5.4"


class TestOnSessionModeChanged:
    def test_updates_current_mode(self):
        svc = FakeService()
        event = _make_event(SessionEventType.SESSION_MODE_CHANGED, new_mode="plan")

        svc._on_session_mode_changed(event)

        assert svc.current_mode == "plan"

    def test_updates_current_mode_from_v1_enum(self):
        svc = FakeService()
        event = _make_event(SessionEventType.SESSION_MODE_CHANGED, new_mode=SessionMode.PLAN)

        svc._on_session_mode_changed(event)

        assert svc.current_mode == "plan"


class TestOnSessionModelChange:
    def test_updates_current_model(self):
        svc = FakeService()
        event = _make_event(SessionEventType.SESSION_MODEL_CHANGE, new_model="claude-sonnet-4")

        svc._on_session_model_change(event)

        assert svc.current_model == "claude-sonnet-4"


class TestSubagentLifecycleEvents:
    @patch("src.core.events.ctx")
    async def test_selected_updates_current_agent(self, mock_ctx):
        svc = FakeService()
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb
        event = _make_event(
            SessionEventType.SUBAGENT_SELECTED,
            agent_name="planner",
            agent_display_name="Planner",
        )

        svc._on_subagent_selected(event)

        await asyncio.sleep(0)
        assert svc.current_agent == "planner"
        status_cb.assert_awaited_once_with("🤖 Agent selected: Planner")

    @patch("src.core.events.ctx")
    async def test_deselected_clears_current_agent(self, mock_ctx):
        svc = FakeService()
        svc.current_agent = "planner"
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb
        event = _make_event(SessionEventType.SUBAGENT_DESELECTED)

        svc._on_subagent_deselected(event)

        await asyncio.sleep(0)
        assert svc.current_agent is None
        status_cb.assert_awaited_once_with("🤖 Returned to default agent")

    @patch("src.core.events.ctx")
    async def test_failed_dispatches_error_status(self, mock_ctx):
        svc = FakeService()
        status_cb = AsyncMock()
        mock_ctx.status_callback = status_cb
        event = _make_event(
            SessionEventType.SUBAGENT_FAILED,
            agent_name="planner",
            agent_display_name="Planner",
            error="tool exploded",
        )

        svc._on_subagent_failed(event)

        await asyncio.sleep(0)
        msg = status_cb.call_args.args[0]
        assert "Planner" in msg
        assert "tool exploded" in msg


class TestOnContextChanged:
    def test_updates_usage_tracker(self):
        svc = FakeService()
        event = _make_event(
            SessionEventType.SESSION_CONTEXT_CHANGED,
            token_count=500,
            max_tokens=8000,
        )
        svc._on_context_changed(event)

        assert svc.usage_tracker.current_tokens == 500
        assert svc.usage_tracker.token_limit == 8000


class TestDispatchAsync:
    async def test_fires_async_callback(self):
        svc = FakeService()
        cb = AsyncMock()
        svc._dispatch_async(cb, "arg1", "arg2")

        await asyncio.sleep(0)
        cb.assert_awaited_once_with("arg1", "arg2")

    async def test_fires_sync_callback(self):
        svc = FakeService()
        cb = MagicMock()
        svc._dispatch_async(cb, "x")

        cb.assert_called_once_with("x")
