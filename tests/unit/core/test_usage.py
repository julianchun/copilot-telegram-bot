"""Unit tests for src/core/usage.py."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from copilot.generated.session_events import SessionEventType
from src.core.usage import (
    ModelUsage,
    QuotaUsage,
    SessionInfo,
    SessionUsageTracker,
    _parse_quota_percentage,
)


# --- ModelUsage ---


def test_model_usage_defaults():
    u = ModelUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cache_read_tokens == 0
    assert u.cache_write_tokens == 0
    assert u.requests == 0
    assert u.cost == 0
    assert u.api_duration_ms == 0


# --- SessionInfo.duration() ---


def test_session_info_duration_hours():
    created = (datetime.now() - timedelta(hours=1, minutes=5, seconds=30)).isoformat()
    info = SessionInfo(created=created)
    assert info.duration() == "1h 5m 30s"


def test_session_info_duration_minutes():
    created = (datetime.now() - timedelta(minutes=5, seconds=30)).isoformat()
    info = SessionInfo(created=created)
    assert info.duration() == "5m 30s"


def test_session_info_duration_seconds():
    created = (datetime.now() - timedelta(seconds=30)).isoformat()
    info = SessionInfo(created=created)
    assert info.duration() == "30s"


def test_session_info_duration_no_created():
    info = SessionInfo()
    assert info.duration() == "N/A"


# --- _parse_quota_percentage ---


def test_parse_quota_percentage_none():
    assert _parse_quota_percentage(None) == "N/A"


def test_parse_quota_percentage_unlimited():
    snap = MagicMock(is_unlimited_entitlement=True)
    assert _parse_quota_percentage(snap) == "Unlimited"


def test_parse_quota_percentage_value():
    snap = MagicMock(is_unlimited_entitlement=False, remaining_percentage=73.456)
    assert _parse_quota_percentage(snap) == "73.5%"


# --- SessionUsageTracker.handle_event ---


def _make_event(etype, **attrs):
    event = MagicMock()
    event.type = etype
    for k, v in attrs.items():
        setattr(event.data, k, v)
    return event


def test_tracker_handle_session_start():
    tracker = SessionUsageTracker()
    event = _make_event(SessionEventType.SESSION_START, selected_model="gpt-4")
    tracker.handle_event(event)
    assert tracker.session_start_time is not None
    assert tracker.selected_model == "gpt-4"


def test_tracker_handle_usage_info():
    tracker = SessionUsageTracker()
    event = _make_event(
        SessionEventType.SESSION_USAGE_INFO,
        current_tokens=500,
        token_limit=4096,
        messages_length=10,
    )
    tracker.handle_event(event)
    assert tracker.current_tokens == 500
    assert tracker.token_limit == 4096
    assert tracker.messages_length == 10


def test_tracker_handle_assistant_usage():
    tracker = SessionUsageTracker()
    event = _make_event(
        SessionEventType.ASSISTANT_USAGE,
        model="gpt-4",
        input_tokens=100,
        output_tokens=50,
        cache_read_tokens=10,
        cache_write_tokens=5,
        cost=0.5,
        duration=200,
        quota_snapshots=None,
    )
    tracker.handle_event(event)
    assert "gpt-4" in tracker.model_usage
    usage = tracker.model_usage["gpt-4"]
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.cache_read_tokens == 10
    assert usage.cache_write_tokens == 5
    assert usage.cost == 0.5
    assert usage.requests == 1
    assert usage.api_duration_ms == 200

    # Second event accumulates
    tracker.handle_event(event)
    assert usage.requests == 2
    assert usage.input_tokens == 200


def test_tracker_handle_session_shutdown():
    tracker = SessionUsageTracker()
    event = _make_event(SessionEventType.SESSION_SHUTDOWN, total_premium_requests=42)
    tracker.handle_event(event)
    assert tracker.total_premium_requests == 42.0


# --- get_remaining_percentage ---


def test_tracker_get_remaining_percentage_unlimited():
    tracker = SessionUsageTracker()
    snap = MagicMock(is_unlimited_entitlement=True)
    tracker.latest_quota = {"chat": snap}
    assert tracker.get_remaining_percentage() == 100.0


def test_tracker_get_remaining_percentage_value():
    tracker = SessionUsageTracker()
    snap = MagicMock(is_unlimited_entitlement=False, remaining_percentage=55.5)
    tracker.latest_quota = {"chat": snap}
    assert tracker.get_remaining_percentage() == 55.5


def test_tracker_get_remaining_percentage_none():
    tracker = SessionUsageTracker()
    assert tracker.get_remaining_percentage() is None


# --- _format_duration (static) ---


def test_format_duration_static():
    fmt = SessionUsageTracker._format_duration
    assert fmt(30) == "30s"
    assert fmt(90) == "1m 30s"
    assert fmt(3661) == "1h 1m 1s"
