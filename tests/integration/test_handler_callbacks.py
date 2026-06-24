"""Integration tests for callback handlers in src/handlers/callbacks.py."""

import asyncio
from types import SimpleNamespace

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
    """data='model:gpt-5.4' routes to _handle_model_callback."""
    mock_update_with_query.callback_query.data = "model:gpt-5.4"
    mock_service._models_cache = []

    from src.handlers.callbacks import button_handler

    await button_handler(mock_update_with_query, mock_context)

    mock_service.change_model.assert_awaited_once_with("gpt-5.4")
    msg = mock_update_with_query.callback_query.edit_message_text.call_args.args[0]
    assert "gpt-5.4" in msg


async def test_button_handler_routes_project(
    mock_update_with_query, mock_context, mock_service, tmp_path
):
    """data='proj:myproject' routes to _handle_project_callback."""
    mock_update_with_query.callback_query.data = "proj:myproject"
    mock_service.set_working_directory = AsyncMock()
    mock_service.get_cockpit_message = AsyncMock(return_value="cockpit")
    (tmp_path / "myproject").mkdir()

    with patch(f"{MODULE}.WORKSPACE_PATH", tmp_path):
        from src.handlers.callbacks import button_handler

        await button_handler(mock_update_with_query, mock_context)

    mock_service.set_working_directory.assert_awaited_once()
    mock_service.get_cockpit_message.assert_awaited_once()
    mock_update_with_query.callback_query.message.delete.assert_awaited_once()
    mock_update_with_query.callback_query.edit_message_text.assert_not_awaited()
    mock_context.bot.send_message.assert_awaited_once_with(
        chat_id=mock_update_with_query.callback_query.message.chat_id,
        text="cockpit",
    )


# --- _build_project_selected_message ---


def test_build_project_selected_message(mock_context):
    """Returns correctly formatted status string."""
    mock_context.user_data = {
        "auth": "testuser",
        "cli_version": "1.0.0",
        "sdk_version": "0.3.0",
    }

    from src.handlers.callbacks import _build_project_selected_message

    result = _build_project_selected_message(mock_context, "my-project", "Created")

    assert "Copilot CLI-Telegram" in result
    assert "testuser" in result
    assert "1.0.0" in result
    assert "0.3.0" in result
    assert "Created: my-project" in result


# --- _handle_model_callback ---


async def test_handle_model_callback_changes_model(
    mock_callback_query, mock_context, mock_service
):
    """Calls service.change_model for a model without reasoning support."""
    mock_callback_query.data = "model:gpt-5.4"
    mock_service._models_cache = [{"id": "gpt-5.4", "supports_reasoning": False}]

    from src.handlers.callbacks import _handle_model_callback

    await _handle_model_callback(mock_callback_query, mock_context)

    mock_service.change_model.assert_awaited_once_with("gpt-5.4")
    msg = mock_callback_query.edit_message_text.call_args.args[0]
    assert "gpt-5.4" in msg


async def test_handle_model_callback_cancel_does_not_change_model(
    mock_callback_query, mock_context, mock_service
):
    """Cancel option closes the model menu without switching models."""
    mock_callback_query.data = "model:__cancel__"

    from src.handlers.callbacks import _handle_model_callback

    await _handle_model_callback(mock_callback_query, mock_context)

    mock_service.change_model.assert_not_awaited()
    assert mock_callback_query.edit_message_text.call_args.args[0] == "❌ Model selection cancelled."


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


async def test_handle_interaction_callback_input_selection_by_index(
    mock_callback_query, mock_update_with_query, mock_context, pending_interactions
):
    """input:ID:<index> resolves the future with the full option text."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    interaction_id = "input-123"
    pending_interactions[interaction_id] = {
        "future": future,
        "prompt": "Choose one",
        "options": ["alpha option", "beta option"],
    }

    mock_callback_query.data = f"input:{interaction_id}:1"

    from src.handlers.callbacks import _handle_interaction_callback

    await _handle_interaction_callback(
        mock_callback_query, mock_update_with_query, mock_context
    )

    assert future.done()
    assert future.result() == "beta option"
    assert interaction_id not in pending_interactions
    assert mock_callback_query.edit_message_text.call_args.args[0] == "❓ Selected: beta option"
    assert mock_callback_query.message.reply_text.call_args.args[0] == "✅ Selected option: beta option"


async def test_handle_interaction_callback_input_cancel(
    mock_callback_query, mock_update_with_query, mock_context, pending_interactions
):
    """input:ID:cancel cancels the interaction cleanly."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    interaction_id = "input-cancel"
    pending_interactions[interaction_id] = {
        "future": future,
        "prompt": "Choose one",
        "options": ["alpha option"],
    }

    mock_callback_query.data = f"input:{interaction_id}:cancel"

    from src.handlers.callbacks import _handle_interaction_callback

    await _handle_interaction_callback(
        mock_callback_query, mock_update_with_query, mock_context
    )

    assert future.done()
    assert future.result() == "cancel"
    assert interaction_id not in pending_interactions
    assert mock_callback_query.edit_message_text.call_args.args[0] == "❌ Selection cancelled."


async def test_handle_interaction_callback_input_page_rerenders_paginated_menu(
    mock_callback_query, mock_update_with_query, mock_context, pending_interactions
):
    """input_page:ID:<page> re-renders the same interaction without resolving it."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    interaction_id = "input-page"
    pending_interactions[interaction_id] = {
        "future": future,
        "prompt": "Choose one",
        "options": [f"Option {i}" for i in range(1, 11)],
    }

    mock_callback_query.data = f"input_page:{interaction_id}:1"

    from src.handlers.callbacks import _handle_interaction_callback

    await _handle_interaction_callback(
        mock_callback_query, mock_update_with_query, mock_context
    )

    assert not future.done()
    assert interaction_id in pending_interactions
    text = mock_callback_query.edit_message_text.call_args.args[0]
    assert "Page 2/2" in text
    assert "10. Option 10" in text


# --- _handle_plan_callback ---


def _mock_exit_plan_rpc(mock_service, *, success=True):
    mock_service.session = MagicMock()
    mock_service.session.rpc.ui.handle_pending_exit_plan_mode = AsyncMock(
        return_value=SimpleNamespace(success=success)
    )
    return mock_service.session.rpc.ui.handle_pending_exit_plan_mode


async def test_handle_plan_callback_stale_request_is_blocked(
    mock_callback_query, mock_context, mock_service
):
    """Stale plan callbacks are rejected with an alert."""
    mock_callback_query.data = "plan:approve:stale-request"
    mock_service._pending_exit_plan_mode = {"request_id": "active-request"}

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    mock_callback_query.answer.assert_awaited_once_with(
        "⚠️ This plan request is no longer active.", show_alert=True
    )
    mock_callback_query.edit_message_text.assert_not_awaited()


async def test_button_handler_plan_stale_request_shows_alert_once(
    mock_update_with_query, mock_context, mock_service
):
    """button_handler defers plan answers so stale alerts are not swallowed."""
    mock_update_with_query.callback_query.data = "plan:approve:stale-request"
    mock_service._pending_exit_plan_mode = {"request_id": "active-request"}

    from src.handlers.callbacks import button_handler

    await button_handler(mock_update_with_query, mock_context)

    mock_update_with_query.callback_query.answer.assert_awaited_once_with(
        "⚠️ This plan request is no longer active.", show_alert=True
    )
    mock_update_with_query.callback_query.edit_message_text.assert_not_awaited()


async def test_handle_plan_callback_reject_allows_through_when_no_pending_state(
    mock_callback_query, mock_context, mock_service
):
    """Callbacks still work after restart when no pending state is stored."""
    mock_callback_query.data = "plan:reject:req-1"
    mock_service._pending_exit_plan_mode = None
    rpc = _mock_exit_plan_rpc(mock_service)

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    request = rpc.await_args.args[0]
    assert request.request_id == "req-1"
    assert request.response.approved is False
    assert request.response.feedback == "Plan rejected by user."
    assert mock_service._pending_exit_plan_mode is None
    assert "Plan rejected" in mock_callback_query.edit_message_text.call_args.args[0]


async def test_handle_plan_callback_reject_clears_pending_state(
    mock_callback_query, mock_context, mock_service
):
    """Rejecting a plan clears the stored pending request."""
    mock_callback_query.data = "plan:reject:req-1"
    mock_service._pending_exit_plan_mode = {"request_id": "req-1"}
    rpc = _mock_exit_plan_rpc(mock_service)

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    request = rpc.await_args.args[0]
    assert request.response.approved is False
    assert request.response.feedback == "Plan rejected by user."
    assert mock_service._pending_exit_plan_mode is None
    assert "Plan rejected" in mock_callback_query.edit_message_text.call_args.args[0]


async def test_handle_plan_callback_edit_clears_pending_state(
    mock_callback_query, mock_context, mock_service
):
    """Requesting a plan edit clears the stored pending request."""
    mock_callback_query.data = "plan:edit:req-1"
    mock_service._pending_exit_plan_mode = {"request_id": "req-1"}
    rpc = _mock_exit_plan_rpc(mock_service)

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    request = rpc.await_args.args[0]
    assert request.response.approved is False
    assert request.response.feedback == "User wants to revise the plan."
    assert mock_service._pending_exit_plan_mode is None
    assert "Plan edit requested" in mock_callback_query.edit_message_text.call_args.args[0]


async def test_handle_plan_callback_approve_uses_pending_ui_rpc(
    mock_callback_query, mock_context, mock_service
):
    """Approving a plan resolves the pending v1 UI request."""
    mock_callback_query.data = "plan:approve:req-1"
    mock_service._pending_exit_plan_mode = {
        "request_id": "req-1",
        "actions": ["interactive", "autopilot"],
        "recommended_action": "autopilot",
    }
    mock_service.set_mode = AsyncMock(return_value=True)
    rpc = _mock_exit_plan_rpc(mock_service)

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    mock_service.set_mode.assert_not_awaited()
    request = rpc.await_args.args[0]
    assert request.request_id == "req-1"
    assert request.response.approved is True
    assert request.response.selected_action.value == "autopilot"
    assert "Plan approved" in mock_callback_query.edit_message_text.call_args.args[0]
    assert mock_service._pending_exit_plan_mode is None


async def test_handle_plan_callback_approve_success_false_shows_expired(
    mock_callback_query, mock_context, mock_service
):
    """The UI does not claim approval when the SDK says the request is stale."""
    mock_callback_query.data = "plan:approve:req-1"
    mock_service._pending_exit_plan_mode = {"request_id": "req-1"}
    _mock_exit_plan_rpc(mock_service, success=False)

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    assert mock_service._pending_exit_plan_mode is None
    assert "expired or was already handled" in mock_callback_query.edit_message_text.call_args.args[0]


async def test_handle_plan_callback_approve_requires_active_session(
    mock_callback_query, mock_context, mock_service
):
    """Approving a plan without a session shows an error instead of false success."""
    mock_callback_query.data = "plan:approve:req-1"
    mock_service._pending_exit_plan_mode = {"request_id": "req-1"}
    mock_service.session = None

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    mock_service.set_mode.assert_not_awaited()
    mock_callback_query.edit_message_text.assert_awaited_once_with(
        "⚠️ No active session. Cannot resolve plan request."
    )
    assert mock_service._pending_exit_plan_mode == {"request_id": "req-1"}


async def test_handle_plan_callback_resolution_error_hides_exception_details(
    mock_callback_query, mock_context, mock_service
):
    """RPC errors are logged but not echoed back to Telegram users."""
    mock_callback_query.data = "plan:approve:req-1"
    mock_service._pending_exit_plan_mode = {"request_id": "req-1"}
    mock_service.session = MagicMock()
    mock_service.session.rpc.ui.handle_pending_exit_plan_mode = AsyncMock(
        side_effect=RuntimeError("secret-token")
    )

    from src.handlers.callbacks import _handle_plan_callback

    await _handle_plan_callback(mock_callback_query, mock_context)

    text = mock_callback_query.edit_message_text.await_args.args[0]
    assert "Failed to resolve plan request" in text
    assert "secret-token" not in text
