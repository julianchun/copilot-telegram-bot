"""Unit tests for src/core/usage.py."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from copilot.generated.session_events import SessionEventType
from src.core.usage import (
    ModelUsage,
    QuotaUsage,
    SessionInfo,
    SessionUsageTracker,
    format_ai_credits,
    format_ai_credits_remaining,
    nano_aiu_to_ai_credits,
    _parse_quota_percentage,
)


# --- ModelUsage ---


def test_model_usage_defaults():
    u = ModelUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cache_read_tokens == 0
    assert u.cache_write_tokens == 0
    assert u.reasoning_tokens == 0
    assert u.llm_calls == 0
    assert u.api_duration_ms == 0


def test_nano_aiu_to_ai_credits():
    assert nano_aiu_to_ai_credits(None) is None
    assert nano_aiu_to_ai_credits(1_500_000_000) == 1.5


def test_format_ai_credits():
    assert format_ai_credits(None) == "N/A"
    assert format_ai_credits(0) == "0"
    assert format_ai_credits(0.0000123) == "0.000012"
    assert format_ai_credits(0.125) == "0.125"
    assert format_ai_credits(1.5) == "1.5"


def test_format_ai_credits_remaining_from_account_quota():
    quota = SimpleNamespace(
        quota_snapshots={
            "premium_interactions": SimpleNamespace(
                is_unlimited_entitlement=False,
                remaining_percentage=98.9,
                used_requests=16,
                entitlement_requests=1500,
            )
        }
    )

    assert format_ai_credits_remaining(quota) == "98.9% (16/1500 used)"


def test_format_ai_credits_remaining_accepts_dict_camel_case():
    quota = {
        "quotaSnapshots": {
            "premium_interactions": {
                "isUnlimitedEntitlement": False,
                "remainingPercentage": 100.0,
                "usedRequests": 0,
                "entitlementRequests": 1500,
            }
        }
    }

    assert format_ai_credits_remaining(quota) == "100% (0/1500 used)"


def test_format_ai_credits_remaining_unlimited():
    quota = SimpleNamespace(
        quota_snapshots={
            "premium_interactions": SimpleNamespace(is_unlimited_entitlement=True)
        }
    )

    assert format_ai_credits_remaining(quota) == "Unlimited"


def test_format_ai_credits_remaining_accepts_v1_private_fields():
    quota = SimpleNamespace(
        quota_snapshots={
            "premium_interactions": SimpleNamespace(
                _is_unlimited_entitlement=False,
                _remaining_percentage=98.9,
                _used_requests=16,
                _entitlement_requests=1500,
            )
        }
    )

    assert format_ai_credits_remaining(quota) == "98.9% (16/1500 used)"


# --- SessionInfo.duration() ---


def test_session_info_duration_hours():
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    created = (fixed_now - timedelta(hours=1, minutes=5, seconds=30)).isoformat()
    info = SessionInfo(created=created)
    with patch("src.core.usage.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        assert info.duration() == "1h 5m 30s"


def test_session_info_duration_minutes():
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    created = (fixed_now - timedelta(minutes=5, seconds=30)).isoformat()
    info = SessionInfo(created=created)
    with patch("src.core.usage.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        assert info.duration() == "5m 30s"


def test_session_info_duration_seconds():
    fixed_now = datetime(2026, 1, 1, 12, 0, 0)
    created = (fixed_now - timedelta(seconds=30)).isoformat()
    info = SessionInfo(created=created)
    with patch("src.core.usage.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
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


def test_parse_quota_percentage_accepts_v1_private_fields():
    snap = SimpleNamespace(_is_unlimited_entitlement=False, _remaining_percentage=73.456)
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
        reasoning_tokens=7,
        duration=200,
        quota_snapshots=None,
        _copilot_usage=SimpleNamespace(total_nano_aiu=2_000_000_000),
    )
    tracker.handle_event(event)
    assert "gpt-4" in tracker.model_usage
    usage = tracker.model_usage["gpt-4"]
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.cache_read_tokens == 10
    assert usage.cache_write_tokens == 5
    assert usage.reasoning_tokens == 7
    assert usage.llm_calls == 1
    assert usage.api_duration_ms == 200
    assert tracker.reported_ai_credits == 2.0

    # Second event accumulates
    tracker.handle_event(event)
    assert usage.llm_calls == 2
    assert usage.input_tokens == 200
    assert tracker.reported_ai_credits == 4.0


def test_tracker_handle_assistant_usage_accepts_v1_private_quota_snapshots():
    tracker = SessionUsageTracker()
    event = _make_event(
        SessionEventType.ASSISTANT_USAGE,
        model="gpt-4",
        input_tokens=100,
        output_tokens=50,
        duration=200,
        quota_snapshots=None,
        _quota_snapshots={
            "chat": SimpleNamespace(
                _is_unlimited_entitlement=False,
                _remaining_percentage=88.8,
            ),
            "completions": SimpleNamespace(
                _is_unlimited_entitlement=True,
                _remaining_percentage=0.0,
            ),
            "premium_interactions": SimpleNamespace(
                _is_unlimited_entitlement=False,
                _remaining_percentage=98.9,
            ),
        },
    )

    tracker.handle_event(event)

    assert tracker.quota_usage.chat_remaining_percentage == "88.8%"
    assert tracker.quota_usage.completion_remaining_percentage == "Unlimited"
    assert tracker.quota_usage.ai_credits_remaining_percentage == "98.9%"


def test_tracker_ignores_legacy_session_shutdown_premium_requests():
    tracker = SessionUsageTracker()
    event = _make_event(SessionEventType.SESSION_SHUTDOWN, total_premium_requests=42)
    tracker.handle_event(event)
    assert tracker.reported_ai_credits is None


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


def test_tracker_quota_helpers_accept_v1_private_fields():
    tracker = SessionUsageTracker()
    tracker.latest_quota = {
        "premium_interactions": SimpleNamespace(
            _is_unlimited_entitlement=False,
            _remaining_percentage=98.9,
            _entitlement_requests=1500,
        )
    }

    assert tracker.get_quota_display() == "premium_interactions: 99% remaining"
    assert tracker.get_remaining_percentage() == 98.9


def test_tracker_get_remaining_percentage_none():
    tracker = SessionUsageTracker()
    assert tracker.get_remaining_percentage() is None


# --- _format_duration (static) ---


def test_format_duration_static():
    fmt = SessionUsageTracker._format_duration
    assert fmt(30) == "30s"
    assert fmt(90) == "1m 30s"
    assert fmt(3661) == "1h 1m 1s"


async def test_usage_summary_uses_sdk_ai_credit_metrics():
    tracker = SessionUsageTracker(current_tokens=100, token_limit=1000)
    metrics = SimpleNamespace(
        total_nano_aiu=1_250_000_000,
        total_user_requests=3,
        total_api_duration_ms=2500,
        last_call_input_tokens=10,
        last_call_output_tokens=5,
        model_metrics={
            "gpt-5": SimpleNamespace(
                total_nano_aiu=1_000_000_000,
                requests=SimpleNamespace(count=2),
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_tokens=20,
                    cache_write_tokens=10,
                    reasoning_tokens=7,
                ),
            )
        },
    )
    quota = SimpleNamespace(
        quota_snapshots={
            "premium_interactions": SimpleNamespace(
                is_unlimited_entitlement=False,
                remaining_percentage=98.9,
                used_requests=16,
                entitlement_requests=1500,
            )
        }
    )

    with patch("src.core.git.get_diff_shortstat", return_value="1 file changed"):
        summary = await tracker.get_usage_summary(metrics, quota)

    assert "AI credits used: 1.25" in summary
    assert "AI credits remaining: 98.9% (16/1500 used)" in summary
    assert summary.index("AI credits used") < summary.index("AI credits remaining") < summary.index("LLM calls")
    assert "LLM calls: 3" in summary
    assert "Last call: 10 input, 5 output tokens" in summary
    assert "gpt-5: 2 calls; 1 credits; 100 in, 50 out" in summary
    assert "7 reasoning" in summary
    assert "Pricing:" not in summary
    assert "models-and-pricing" not in summary
