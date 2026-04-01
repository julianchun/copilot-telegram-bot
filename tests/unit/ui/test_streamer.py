"""Unit tests for src/ui/streamer.py — MessageSender."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ui.streamer import MessageSender

PAGE_LIMIT = 4000


def _make_sender() -> MessageSender:
    """Create a MessageSender with a mocked Message."""
    mock_message = MagicMock()
    mock_message.chat = AsyncMock()
    return MessageSender(mock_message)


# ── _split_message ──────────────────────────────────────────────────


class TestSplitMessage:
    def test_under_limit(self):
        sender = _make_sender()
        text = "short message"
        assert sender._split_message(text) == [text]

    def test_over_limit(self):
        sender = _make_sender()
        text = "a " * (PAGE_LIMIT + 500)  # well over limit
        chunks = sender._split_message(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= PAGE_LIMIT + 10  # small tolerance for closing fences

    def test_code_block_tracking(self):
        """An unclosed ``` at the split boundary is closed and reopened."""
        sender = _make_sender()
        # Build text: opening code block, then filler to exceed limit
        opening = "```python\n"
        filler = "x" * (PAGE_LIMIT - len(opening) + 500)
        text = opening + filler + "\n```"

        chunks = sender._split_message(text)
        assert len(chunks) >= 2
        # First chunk should end with closing ```
        assert chunks[0].rstrip().endswith("```")
        # Second chunk should start with reopened code fence
        assert chunks[1].lstrip().startswith("```")

    def test_empty(self):
        sender = _make_sender()
        assert sender._split_message("") == [""]


# ── _ensure_safe_markdown ───────────────────────────────────────────


class TestEnsureSafeMarkdown:
    def test_balanced(self):
        text = "```python\nprint('hi')\n```"
        assert MessageSender._ensure_safe_markdown(text) == text

    def test_unclosed_code_block(self):
        text = "```python\nprint('hi')"
        result = MessageSender._ensure_safe_markdown(text)
        assert result.endswith("\n```")

    def test_unclosed_backtick(self):
        text = "use `foo for bar"
        result = MessageSender._ensure_safe_markdown(text)
        assert result.endswith("`")
        # Should have even count of backticks now
        assert result.count("`") % 2 == 0

    def test_already_safe(self):
        text = "use `foo` and `bar` ok"
        assert MessageSender._ensure_safe_markdown(text) == text


# ── send_response ───────────────────────────────────────────────────


class TestSendResponse:
    @pytest.fixture()
    def sender(self):
        return _make_sender()

    async def test_calls_split_and_send(self, sender):
        """send_response splits the text and sends each chunk."""
        sender.chat.send_message = AsyncMock()
        text = "Hello world"
        await sender.send_response(text)
        sender.chat.send_message.assert_called()

    async def test_long_message_sends_multiple(self, sender):
        sender.chat.send_message = AsyncMock()
        text = "word " * 2000  # ~10 000 chars
        await sender.send_response(text)
        assert sender.chat.send_message.call_count > 1


# ── create_working / delete_working ─────────────────────────────────


class TestWorkingMessage:
    @pytest.fixture()
    def sender(self):
        return _make_sender()

    async def test_create_working_sends_message(self, sender):
        mock_msg = AsyncMock()
        sender.chat.send_message = AsyncMock(return_value=mock_msg)
        await sender.create_working()
        sender.chat.send_message.assert_called_once()
        assert sender._working_msg is mock_msg

    async def test_delete_working_deletes_message(self, sender):
        mock_msg = AsyncMock()
        mock_msg.delete = AsyncMock()
        sender._working_msg = mock_msg
        await sender.delete_working()
        mock_msg.delete.assert_called_once()
        assert sender._working_msg is None

    async def test_delete_working_noop_when_none(self, sender):
        """Deleting when no working message should be a no-op."""
        await sender.delete_working()  # should not raise
        assert sender._working_msg is None
