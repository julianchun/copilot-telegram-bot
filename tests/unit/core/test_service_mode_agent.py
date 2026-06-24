"""Unit tests for Mode API and Agent management methods in CopilotService."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.service import CopilotService
from src.core.usage import SessionInfo


def test_build_client_uses_v1_runtime_connection(tmp_path):
    svc = object.__new__(CopilotService)
    connection = object()

    with (
        patch("src.core.service.RuntimeConnection.for_stdio", return_value=connection) as for_stdio,
        patch("src.core.service.CopilotClient") as client_cls,
        patch("src.core.service.GITHUB_TOKEN", "gh-token"),
    ):
        result = svc._build_client(tmp_path)

    for_stdio.assert_called_once_with()
    client_cls.assert_called_once_with(
        working_directory=str(tmp_path),
        github_token="gh-token",
        connection=connection,
    )
    assert result is client_cls.return_value


def test_get_display_model_prefers_real_runtime_model():
    svc = object.__new__(CopilotService)
    svc.last_assistant_usage = None
    svc.session_info = SessionInfo()
    svc.current_model = None

    assert svc.get_display_model() == "Auto"

    svc.session_info.selected_model = "claude-sonnet-4.6"
    assert svc.get_display_model() == "claude-sonnet-4.6"

    svc.last_assistant_usage = SimpleNamespace(model="gpt-5.4")
    assert svc.get_display_model() == "gpt-5.4"


async def test_export_session_to_file_uses_get_events(tmp_path):
    svc = object.__new__(CopilotService)
    svc.session = MagicMock()
    svc.session.get_events = AsyncMock(return_value=[SimpleNamespace(type="event")])
    svc.session.get_messages = AsyncMock()
    svc.session_id = "session-123"
    svc.project_name = "project"
    svc.current_model = "gpt-5"

    with (
        patch("src.core.service.ctx.root_path", tmp_path),
        patch("src.core.service.ctx.session_start_time", datetime(2026, 5, 3, 0, 0, 0)),
        patch("src.ui.session_exporter.format_session_markdown", return_value="# export\n") as formatter,
    ):
        result = await svc.export_session_to_file()

    svc.session.get_events.assert_awaited_once_with()
    svc.session.get_messages.assert_not_awaited()
    formatter.assert_called_once()
    assert result == str(tmp_path / "copilot-telegram-bot-session-123.md")
    assert (tmp_path / "copilot-telegram-bot-session-123.md").read_text() == "# export\n"


async def test_get_usage_report_includes_account_quota():
    svc = object.__new__(CopilotService)
    metrics = SimpleNamespace(total_nano_aiu=1_000_000_000)
    quota = SimpleNamespace(quota_snapshots={})
    svc.get_sdk_usage_metrics = AsyncMock(return_value=metrics)
    svc.get_account_quota = AsyncMock(return_value=quota)
    svc.usage_tracker = MagicMock()
    svc.usage_tracker.get_usage_summary = AsyncMock(return_value="summary")

    result = await svc.get_usage_report()

    assert result == "summary"
    svc.get_sdk_usage_metrics.assert_awaited_once_with()
    svc.get_account_quota.assert_awaited_once_with()
    svc.usage_tracker.get_usage_summary.assert_awaited_once_with(metrics, quota)


async def test_get_account_quota_calls_server_rpc():
    svc = object.__new__(CopilotService)
    svc._is_running = True
    quota = SimpleNamespace(quota_snapshots={})
    svc.client = MagicMock()
    svc.client.rpc.account.get_quota = AsyncMock(return_value=quota)

    result = await svc.get_account_quota()

    assert result is quota
    svc.client.rpc.account.get_quota.assert_awaited_once()


@pytest.fixture
def svc():
    """Create a minimal CopilotService for testing mode/agent methods.

    Patches out __init__ side effects and wires up only what the methods need.
    """
    with patch.object(CopilotService, "__init__", lambda self: None):
        s = CopilotService()
    s.current_mode = "interactive"
    s.current_agent = None
    s._chat_lock = asyncio.Lock()
    s.session = MagicMock()
    s.session.rpc.mode.set = AsyncMock()
    s.session.rpc.agent.list = AsyncMock()
    s.session.rpc.agent.get_current = AsyncMock()
    s.session.rpc.agent.select = AsyncMock()
    s.session.rpc.agent.deselect = AsyncMock()
    s.session.rpc.agent.reload = AsyncMock()
    s.start = AsyncMock()
    return s


# ── set_mode ─────────────────────────────────────────────────────────


class TestSetMode:
    async def test_set_mode_plan(self, svc):
        result = await svc.set_mode("plan")
        assert result is True
        assert svc.current_mode == "plan"
        svc.session.rpc.mode.set.assert_awaited_once()

    async def test_set_mode_interactive(self, svc):
        svc.current_mode = "plan"
        result = await svc.set_mode("interactive")
        assert result is True
        assert svc.current_mode == "interactive"

    async def test_set_mode_autopilot(self, svc):
        result = await svc.set_mode("autopilot")
        assert result is True
        assert svc.current_mode == "autopilot"

    async def test_set_mode_same_noop(self, svc):
        """Setting the same mode returns True without RPC call."""
        result = await svc.set_mode("interactive")
        assert result is True
        svc.session.rpc.mode.set.assert_not_awaited()

    async def test_set_mode_invalid(self, svc):
        result = await svc.set_mode("bogus")
        assert result is False
        assert svc.current_mode == "interactive"

    async def test_set_mode_during_chat(self, svc):
        async with svc._chat_lock:
            result = await svc.set_mode("plan")
        assert result is False
        assert svc.current_mode == "interactive"

    async def test_set_mode_no_session(self, svc):
        """Without a session, mode is stored locally for later application."""
        svc.session = None
        result = await svc.set_mode("plan")
        assert result is True
        assert svc.current_mode == "plan"

    async def test_set_mode_rpc_failure(self, svc):
        svc.session.rpc.mode.set = AsyncMock(side_effect=RuntimeError("rpc fail"))
        result = await svc.set_mode("plan")
        assert result is False
        assert svc.current_mode == "interactive"


# ── list_agents ──────────────────────────────────────────────────────


class TestListAgents:
    async def test_list_agents_returns_list(self, svc):
        agent = MagicMock(name="test-agent", display_name="Test", description="A test agent")
        svc.session.rpc.agent.list.return_value = MagicMock(agents=[agent])
        result = await svc.list_agents()
        assert result == [agent]

    async def test_list_agents_empty(self, svc):
        svc.session.rpc.agent.list.return_value = MagicMock(agents=[])
        result = await svc.list_agents()
        assert result == []

    async def test_list_agents_no_session_starts(self, svc):
        svc.session = None
        svc.start = AsyncMock()
        result = await svc.list_agents()
        svc.start.assert_awaited_once()

    async def test_list_agents_error_returns_empty(self, svc):
        svc.session.rpc.agent.list = AsyncMock(side_effect=RuntimeError("fail"))
        result = await svc.list_agents()
        assert result == []


# ── get_current_agent ────────────────────────────────────────────────


class TestGetCurrentAgent:
    async def test_get_current_agent_with_agent(self, svc):
        agent = MagicMock()
        agent.name = "my-agent"
        svc.session.rpc.agent.get_current.return_value = MagicMock(agent=agent)
        result = await svc.get_current_agent()
        assert result == "my-agent"
        assert svc.current_agent == "my-agent"

    async def test_get_current_agent_none(self, svc):
        svc.session.rpc.agent.get_current.return_value = MagicMock(agent=None)
        result = await svc.get_current_agent()
        assert result is None
        assert svc.current_agent is None

    async def test_get_current_agent_no_session(self, svc):
        svc.session = None
        svc.current_agent = "cached"
        result = await svc.get_current_agent()
        assert result == "cached"


# ── select_agent ─────────────────────────────────────────────────────


class TestSelectAgent:
    async def test_select_agent_success(self, svc):
        result = await svc.select_agent("my-agent")
        assert result is True
        assert svc.current_agent == "my-agent"
        svc.session.rpc.agent.select.assert_awaited_once()

    async def test_select_agent_during_chat(self, svc):
        async with svc._chat_lock:
            result = await svc.select_agent("my-agent")
        assert result is False
        assert svc.current_agent is None

    async def test_select_agent_no_session(self, svc):
        svc.session = None
        result = await svc.select_agent("my-agent")
        assert result is True
        assert svc.current_agent == "my-agent"

    async def test_select_agent_rpc_failure(self, svc):
        svc.session.rpc.agent.select = AsyncMock(side_effect=RuntimeError("fail"))
        result = await svc.select_agent("my-agent")
        assert result is False
        assert svc.current_agent is None


# ── deselect_agent ───────────────────────────────────────────────────


class TestDeselectAgent:
    async def test_deselect_agent_success(self, svc):
        svc.current_agent = "active-agent"
        result = await svc.deselect_agent()
        assert result is True
        assert svc.current_agent is None
        svc.session.rpc.agent.deselect.assert_awaited_once()

    async def test_deselect_agent_during_chat(self, svc):
        svc.current_agent = "active"
        async with svc._chat_lock:
            result = await svc.deselect_agent()
        assert result is False
        assert svc.current_agent == "active"

    async def test_deselect_agent_no_session(self, svc):
        svc.session = None
        svc.current_agent = "active"
        result = await svc.deselect_agent()
        assert result is True
        assert svc.current_agent is None


# ── reload_agents ────────────────────────────────────────────────────


class TestReloadAgents:
    async def test_reload_agents_returns_list(self, svc):
        agent = MagicMock()
        svc.session.rpc.agent.reload.return_value = MagicMock(agents=[agent])
        result = await svc.reload_agents()
        assert result == [agent]

    async def test_reload_agents_error_returns_empty(self, svc):
        svc.session.rpc.agent.reload = AsyncMock(side_effect=RuntimeError("fail"))
        result = await svc.reload_agents()
        assert result == []


# ── plan_read ──────────────────────────────────────────────────────────


class TestPlanRead:
    async def test_plan_read_returns_sdk_fields(self, svc):
        svc.session.rpc.plan.read = AsyncMock(
            return_value=SimpleNamespace(exists=True, content="plan", path="/repo/plan.md")
        )

        result = await svc.plan_read()

        assert result == (True, "plan", "/repo/plan.md")

    async def test_plan_read_missing_required_field_returns_fallback(self, svc):
        svc.session.rpc.plan.read = AsyncMock(
            return_value=SimpleNamespace(exists=True, content="plan")
        )

        result = await svc.plan_read()

        assert result == (False, None, None)
