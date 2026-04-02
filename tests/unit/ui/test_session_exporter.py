"""Unit tests for session_exporter.format_session_markdown."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from copilot.generated.session_events import SessionEventType

from src.ui.session_exporter import format_session_markdown


def make_event(event_type, ephemeral=False, **data_attrs):
    """Create a mock SessionEvent with the given type and data attributes."""
    event = MagicMock()
    event.type = event_type
    event.timestamp = datetime(2025, 1, 15, 10, 0, 0)
    event.ephemeral = ephemeral
    for key, value in data_attrs.items():
        setattr(event.data, key, value)
    return event


def _metadata(**overrides):
    base = {
        "session_id": "test-123",
        "start_time": datetime(2025, 1, 15, 10, 0, 0),
        "project_name": "test",
        "current_model": "gpt-4.1",
    }
    base.update(overrides)
    return base


class TestFormatEmptyEvents:
    def test_format_empty_events(self):
        result = format_session_markdown([], _metadata())
        assert result == "# 🤖 Copilot CLI Session\n\n> **No session history**\n"


class TestFormatWithUserMessage:
    def test_format_with_user_message(self):
        events = [make_event(SessionEventType.USER_MESSAGE, content="Hello world")]
        result = format_session_markdown(events, _metadata())
        assert "### 👤 User" in result
        assert "Hello world" in result


class TestFormatWithAssistantMessage:
    def test_format_with_assistant_message(self):
        events = [make_event(SessionEventType.ASSISTANT_MESSAGE, content="Hi there")]
        result = format_session_markdown(events, _metadata())
        assert "### 💬 Copilot" in result
        assert "Hi there" in result


class TestFormatFiltersEphemeral:
    def test_format_filters_ephemeral(self):
        events = [
            make_event(SessionEventType.USER_MESSAGE, content="visible"),
            make_event(SessionEventType.ASSISTANT_MESSAGE, ephemeral=True, content="hidden"),
        ]
        result = format_session_markdown(events, _metadata())
        assert "visible" in result
        assert "hidden" not in result


class TestFormatSessionStart:
    def test_format_session_start(self):
        events = [make_event(SessionEventType.SESSION_START, selected_model="gpt-4.1")]
        result = format_session_markdown(events, _metadata())
        assert "Session started with model: gpt-4.1" in result


class TestFormatToolExecution:
    def test_format_tool_execution(self):
        events = [
            make_event(
                SessionEventType.TOOL_EXECUTION_START,
                tool_name="bash",
                arguments={"command": "ls"},
            ),
        ]
        result = format_session_markdown(events, _metadata())
        assert "### ✅ `bash`" in result
        assert "Arguments" in result
        assert '"command"' in result


class TestFormatIncludesHeader:
    def test_format_includes_header(self):
        events = [make_event(SessionEventType.USER_MESSAGE, content="hi")]
        result = format_session_markdown(events, _metadata())
        assert "**Session ID:** `test-123`" in result
        assert "**Started:**" in result
        assert "**Exported:**" in result


class TestFormatModelChangeSynthesis:
    def test_format_model_change_synthesis(self):
        """ASSISTANT_USAGE events with a new model create synthetic model change entries."""
        events = [
            make_event(SessionEventType.USER_MESSAGE, content="hi"),
            make_event(SessionEventType.ASSISTANT_USAGE, model="claude-sonnet-4"),
        ]
        result = format_session_markdown(events, _metadata())
        assert "Model changed to: claude-sonnet-4" in result
