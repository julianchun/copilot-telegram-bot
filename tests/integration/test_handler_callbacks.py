"""Integration tests for callback handlers in src/handlers/callbacks.py."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

MODULE = "src.handlers.callbacks"


@pytest.fixture
def mock_update_with_query(mock_update, mock_callback_query):
    """Attach callback query to the update so button_handler can route."""
    mock_update.callback_query = mock_callback_query
    return mock_update


@pytest.fixture(autouse=True)
def _patch_deps(mock_service):
    """Patch security_check and service for every test."""
    with (
        patch(f"{MODULE}.security_check", new_callable=AsyncMock, return_value=True),
        patch(f"{MODULE}.service", mock_service),
    ):
        yield


@pytest.fixture
def pending_interactions():
    """Provide and clean up the PENDING_INTERACTIONS dict."""
    from src.handlers.messages import PENDING_INTERACTIONS

    PENDING_INTERACTIONS.clear()
    yield PENDING_INTERACTIONS
    PENDING_INTERACTIONS.clear()


# --- button_handler routing tests ---


async def test_button_handler_security_check_fails(mock_update_with_query, mock_context):
    """button_handler returns early when security_check fails."""
    with patch(f"{MODULE}.security_check", new_callable=AsyncMock, return_value=False):
        from src.handlers.callbacks import button_handler

        await button_handler(mock_update_with_query, mock_context)

    mock_update_with_query.callback_query.answer.assert_not_awaited()


async def test_button_handler_routes_model(mock_update_with_query, mock_context, mock_service):
    """data='model:gpt-4.1' routes to _handle_model_callback."""
    mock_update_with_query.callback_query.data = "model:gpt-4.1"
    mock_service._models_cache = []

    from src.handlers.callbacks import button_handler

    await button_handler(mock_update_with_query, mock_context)

    mock_service.change_model.assert_awaited_once_with("gpt-4.1")
    msg = mock_update_with_query.callback_query.edit_message_text.call_args.args[0]
    assert "gpt-4.1" in msg


async def test_button_handler_routes_project(
    mock_update_with_query, mock_context, mock_service, tmp_path
):
    """data='proj:myproject' routes to _handle_project_callback."""
    mock_update_with_query.callback_query.data = "proj:myproject"
    mock_service.set_working_directory = AsyncMock()
    (tmp_path / "myproject").mkdir()

    with patch(f"{MODULE}.WORKSPACE_PATH", tmp_path):
        from src.handlers.callbacks import button_handler

        await button_handler(mock_update_with_query, mock_context)

    mock_service.set_working_directory.assert_awaited_once()
    mock_service.get_cockpit_message.assert_awaited_once()


# --- _build_project_selected_message ---


def test_build_project_selected_message(mock_context):
    """Returns correctly formatted status string."""
    mock_context.user_data = {
        "auth": "testuser",
        "cli_version": "1.0.0",
        "sdk_version": "0.2.0",
    }

    from src.handlers.callbacks import _build_project_selected_message

    result = _build_project_selected_message(mock_context, "my-project", "Created")

    assert "Copilot CLI-Telegram" in result
    assert "testuser" in result
    assert "1.0.0" in result
    assert "0.2.0" in result
    assert "Created: my-project" in result


# --- _handle_model_callback ---


async def test_handle_model_callback_changes_model(
    mock_callback_query, mock_context, mock_service
):
    """Calls service.change_model for a model without reasoning support."""
    mock_callback_query.data = "model:gpt-4.1"
    mock_service._models_cache = [{"id": "gpt-4.1", "supports_reasoning": False}]

    from src.handlers.callbacks import _handle_model_callback

    await _handle_model_callback(mock_callback_query, mock_context)

    mock_service.change_model.assert_awaited_once_with("gpt-4.1")
    msg = mock_callback_query.edit_message_text.call_args.args[0]
    assert "gpt-4.1" in msg


# --- _handle_interaction_callback ---


async def test_handle_interaction_callback_permission_allow(
    mock_callback_query, mock_update_with_query, mock_context, pending_interactions
):
    """perm:ID:allow resolves the future with True."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    interaction_id = "test-123"
    pending_interactions[interaction_id] = {
        "future": future,
        "tool_name": "bash",
        "options": [],
    }

    mock_callback_query.data = f"perm:{interaction_id}:allow"

    from src.handlers.callbacks import _handle_interaction_callback

    await _handle_interaction_callback(
        mock_callback_query, mock_update_with_query, mock_context
    )

    assert future.done()
    assert future.result() is True
    assert interaction_id not in pending_interactions
    msg = mock_callback_query.edit_message_text.call_args.args[0]
    assert "Allow" in msg


async def test_handle_interaction_callback_expired(
    mock_callback_query, mock_update_with_query, mock_context, pending_interactions
):
    """Shows expired message when interaction ID is not in PENDING_INTERACTIONS."""
    mock_callback_query.data = "perm:nonexistent-id:allow"

    from src.handlers.callbacks import _handle_interaction_callback

    await _handle_interaction_callback(
        mock_callback_query, mock_update_with_query, mock_context
    )

    msg = mock_callback_query.edit_message_text.call_args.args[0]
    assert "expired" in msg.lower() or "already handled" in msg.lower()
