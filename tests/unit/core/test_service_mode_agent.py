"""Unit tests for Mode API and Agent management methods in CopilotService."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.service import CopilotService


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
