"""Integration tests for src/handlers/messages.py."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.handlers.messages import (
    INTERACTION_TTL,
    PENDING_INTERACTIONS,
    _send_interaction_msg,
    chat_handler,
    cleanup_pending_interactions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_pending():
    """Ensure PENDING_INTERACTIONS is empty before and after every test."""
    PENDING_INTERACTIONS.clear()
    yield
    PENDING_INTERACTIONS.clear()


# ---------------------------------------------------------------------------
# cleanup_pending_interactions tests
# ---------------------------------------------------------------------------

class TestCleanupPendingInteractions:

    async def test_cleanup_removes_done_futures(self):
        """A future that is already done should be removed."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result("ok")

        PENDING_INTERACTIONS["done-1"] = {
            "future": future,
            "timestamp": time.time(),
            "chat_id": 99999,
        }

        cleanup_pending_interactions()

        assert "done-1" not in PENDING_INTERACTIONS

    async def test_cleanup_removes_expired(self):
        """An interaction older than INTERACTION_TTL should be removed."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        PENDING_INTERACTIONS["expired-1"] = {
            "future": future,
            "timestamp": time.time() - INTERACTION_TTL - 10,
            "chat_id": 99999,
        }

        cleanup_pending_interactions()

        assert "expired-1" not in PENDING_INTERACTIONS
        # The expired future should have had a TimeoutError set on it
        assert future.done()

    async def test_cleanup_keeps_active(self):
        """A fresh, not-done future should remain in the dict."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        PENDING_INTERACTIONS["active-1"] = {
            "future": future,
            "timestamp": time.time(),
            "chat_id": 99999,
        }

        cleanup_pending_interactions()

        assert "active-1" in PENDING_INTERACTIONS


# ---------------------------------------------------------------------------
# chat_handler tests
# ---------------------------------------------------------------------------

class TestChatHandler:

    @patch("src.handlers.messages.security_check", new_callable=AsyncMock, return_value=False)
    async def test_chat_handler_security_check_fails(
        self, mock_sec, mock_update, mock_context
    ):
        """Handler returns early when security_check fails."""
        await chat_handler(mock_update, mock_context)

        mock_sec.assert_awaited_once_with(mock_update)
        mock_update.message.reply_text.assert_not_awaited()

    @patch("src.handlers.messages.check_project_selected", new_callable=AsyncMock, return_value=False)
    @patch("src.handlers.messages.security_check", new_callable=AsyncMock, return_value=True)
    async def test_chat_handler_no_project_selected(
        self, mock_sec, mock_proj, mock_update, mock_context
    ):
        """Handler returns early when no project is selected."""
        await chat_handler(mock_update, mock_context)

        mock_proj.assert_awaited_once_with(mock_update)
        mock_update.message.reply_text.assert_not_awaited()

    @patch("src.handlers.messages.service")
    @patch("src.handlers.messages.check_project_selected", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.messages.security_check", new_callable=AsyncMock, return_value=True)
    async def test_chat_handler_session_expired(
        self, mock_sec, mock_proj, mock_svc, mock_update, mock_context
    ):
        """Handler replies with session-expired message when session is expired."""
        mock_svc.session_expired = True

        await chat_handler(mock_update, mock_context)

        mock_update.message.reply_text.assert_awaited_once()
        args = mock_update.message.reply_text.call_args
        assert "Session expired" in args[0][0]

    @patch("src.handlers.messages.service")
    @patch("src.handlers.messages.check_project_selected", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.messages.security_check", new_callable=AsyncMock, return_value=True)
    async def test_chat_handler_chat_lock_busy(
        self, mock_sec, mock_proj, mock_svc, mock_update, mock_context
    ):
        """Handler replies with 'please wait' when _chat_lock is locked."""
        mock_svc.session_expired = False
        lock = asyncio.Lock()
        mock_svc._chat_lock = lock

        # Acquire the lock to simulate a busy state
        await lock.acquire()
        try:
            await chat_handler(mock_update, mock_context)
        finally:
            lock.release()

        mock_update.message.reply_text.assert_awaited_once()
        args = mock_update.message.reply_text.call_args
        assert "Please wait" in args[0][0]

    @patch("src.handlers.messages.MessageSender")
    @patch("src.handlers.messages.service")
    @patch("src.handlers.messages.check_project_selected", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.messages.security_check", new_callable=AsyncMock, return_value=True)
    async def test_chat_handler_callback_timeout_uses_effective_message(
        self, mock_sec, mock_proj, mock_svc, mock_sender_cls, mock_update, mock_context
    ):
        mock_svc.session_expired = False
        mock_svc._chat_lock = asyncio.Lock()
        mock_svc.set_mode = AsyncMock()
        mock_svc.chat = AsyncMock(side_effect=asyncio.TimeoutError("waiting for session.idle"))
        sender = MagicMock()
        sender.create_working = AsyncMock()
        sender.delete_working = AsyncMock()
        sender.send_response = AsyncMock()
        mock_sender_cls.return_value = sender

        mock_update.message = None

        await chat_handler(mock_update, mock_context, override_text="generate instructions")

        mock_update.effective_message.reply_text.assert_awaited_once()
        text = mock_update.effective_message.reply_text.call_args[0][0]
        assert "waiting for user selection" in text

    @patch("src.handlers.messages.MessageSender")
    @patch("src.handlers.messages.service")
    @patch("src.handlers.messages.check_project_selected", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.messages.security_check", new_callable=AsyncMock, return_value=True)
    async def test_chat_handler_callback_exception_uses_effective_message(
        self, mock_sec, mock_proj, mock_svc, mock_sender_cls, mock_update, mock_context
    ):
        mock_svc.session_expired = False
        mock_svc._chat_lock = asyncio.Lock()
        mock_svc.set_mode = AsyncMock()
        mock_svc.chat = AsyncMock(side_effect=RuntimeError("boom"))
        sender = MagicMock()
        sender.create_working = AsyncMock()
        sender.delete_working = AsyncMock()
        sender.send_response = AsyncMock()
        mock_sender_cls.return_value = sender

        mock_update.message = None

        await chat_handler(mock_update, mock_context, override_text="generate instructions")

        mock_update.effective_message.reply_text.assert_awaited_once_with("⚠️ Error: boom")


class TestInteractionMessages:
    async def test_send_interaction_msg_uses_effective_message(self, mock_update, mock_context):
        mock_update.message = None

        await _send_interaction_msg(mock_update, mock_context, 99999, "Allow?", [[MagicMock()]])

        mock_update.effective_message.reply_text.assert_awaited_once()
        args, kwargs = mock_update.effective_message.reply_text.call_args
        assert args[0] == "Allow?"
        assert "reply_markup" in kwargs

    async def test_send_interaction_msg_falls_back_to_bot_send(self, mock_update, mock_context):
        mock_update.message = None
        mock_update.effective_message.reply_text = AsyncMock(side_effect=RuntimeError("telegram failed"))

        await _send_interaction_msg(mock_update, mock_context, 99999, "Allow?", [[MagicMock()]])

        mock_context.bot.send_message.assert_awaited_once()
        kwargs = mock_context.bot.send_message.call_args.kwargs
        assert kwargs["chat_id"] == 99999
        assert kwargs["text"] == "Allow?"
