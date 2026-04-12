"""Integration tests for /agent command and agent callback handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

CMD_MODULE = "src.handlers.commands"
CB_MODULE = "src.handlers.callbacks"


def _make_agent(name, display_name=None):
    a = MagicMock()
    a.name = name
    a.display_name = display_name or name
    a.description = ""
    return a


# ── /agent command ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_cmd(mock_service):
    with (
        patch(f"{CMD_MODULE}.security_check", new_callable=AsyncMock, return_value=True),
        patch(f"{CMD_MODULE}.check_project_selected", new_callable=AsyncMock, return_value=True),
        patch(f"{CMD_MODULE}.service", mock_service),
    ):
        yield


class TestAgentCommand:
    async def test_agent_no_args_no_agents(self, mock_update, mock_context, mock_service):
        """No custom agents → hint about .agent.md files."""
        mock_service.list_agents.return_value = []
        mock_service.get_current_agent.return_value = None
        mock_context.args = None

        from src.handlers.commands import agent_command
        await agent_command(mock_update, mock_context)

        msg = mock_update.message.reply_text.call_args.args[0]
        assert "No custom agents found" in msg

    async def test_agent_no_args_shows_keyboard(self, mock_update, mock_context, mock_service):
        """With agents, shows inline keyboard."""
        mock_service.list_agents.return_value = [_make_agent("coder")]
        mock_service.get_current_agent.return_value = None
        mock_context.args = None

        from src.handlers.commands import agent_command
        await agent_command(mock_update, mock_context)

        call_kwargs = mock_update.message.reply_text.call_args
        assert "reply_markup" in call_kwargs.kwargs
        assert "Select an agent" in call_kwargs.args[0]

    async def test_agent_select_by_name(self, mock_update, mock_context, mock_service):
        mock_context.args = ["my-agent"]

        from src.handlers.commands import agent_command
        await agent_command(mock_update, mock_context)

        mock_service.select_agent.assert_awaited_once_with("my-agent")
        msg = mock_update.message.reply_text.call_args.args[0]
        assert "my-agent" in msg

    async def test_agent_select_failure(self, mock_update, mock_context, mock_service):
        mock_service.select_agent.return_value = False
        mock_context.args = ["bad-agent"]

        from src.handlers.commands import agent_command
        await agent_command(mock_update, mock_context)

        msg = mock_update.message.reply_text.call_args.args[0]
        assert "Failed" in msg

    async def test_agent_reload(self, mock_update, mock_context, mock_service):
        mock_service.reload_agents.return_value = [_make_agent("coder", "Coder")]
        mock_context.args = ["reload"]

        from src.handlers.commands import agent_command
        await agent_command(mock_update, mock_context)

        mock_service.reload_agents.assert_awaited_once()
        msg = mock_update.message.reply_text.call_args.args[0]
        assert "reloaded" in msg.lower()
        assert "Coder" in msg

    async def test_agent_reload_empty(self, mock_update, mock_context, mock_service):
        mock_service.reload_agents.return_value = []
        mock_context.args = ["reload"]

        from src.handlers.commands import agent_command
        await agent_command(mock_update, mock_context)

        msg = mock_update.message.reply_text.call_args.args[0]
        assert "No custom agents" in msg


# ── agent callback handler ───────────────────────────────────────────


@pytest.fixture
def mock_update_with_query(mock_update, mock_callback_query):
    mock_update.callback_query = mock_callback_query
    return mock_update


class TestAgentCallback:
    @pytest.fixture(autouse=True)
    def _patch_cb(self, mock_service):
        with (
            patch(f"{CB_MODULE}.security_check", new_callable=AsyncMock, return_value=True),
            patch(f"{CB_MODULE}.service", mock_service),
        ):
            yield

    async def test_agent_select_callback(self, mock_update_with_query, mock_context, mock_service):
        mock_update_with_query.callback_query.data = "agent:my-agent"

        from src.handlers.callbacks import button_handler
        await button_handler(mock_update_with_query, mock_context)

        mock_service.select_agent.assert_awaited_once_with("my-agent")
        msg = mock_update_with_query.callback_query.edit_message_text.call_args.args[0]
        assert "my-agent" in msg

    async def test_agent_deselect_callback(self, mock_update_with_query, mock_context, mock_service):
        mock_update_with_query.callback_query.data = "agent:__default__"

        from src.handlers.callbacks import button_handler
        await button_handler(mock_update_with_query, mock_context)

        mock_service.deselect_agent.assert_awaited_once()
        msg = mock_update_with_query.callback_query.edit_message_text.call_args.args[0]
        assert "default" in msg.lower()

    async def test_agent_reload_callback(self, mock_update_with_query, mock_context, mock_service):
        mock_service.reload_agents.return_value = [_make_agent("coder")]
        mock_service.get_current_agent.return_value = None
        mock_update_with_query.callback_query.data = "agent:__reload__"

        from src.handlers.callbacks import button_handler
        await button_handler(mock_update_with_query, mock_context)

        mock_service.reload_agents.assert_awaited_once()

    async def test_agent_reload_empty_callback(self, mock_update_with_query, mock_context, mock_service):
        mock_service.reload_agents.return_value = []
        mock_update_with_query.callback_query.data = "agent:__reload__"

        from src.handlers.callbacks import button_handler
        await button_handler(mock_update_with_query, mock_context)

        msg = mock_update_with_query.callback_query.edit_message_text.call_args.args[0]
        assert "No custom agents" in msg
