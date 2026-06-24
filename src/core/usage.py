"""Session usage tracking — accumulates metrics from SDK events."""
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

from copilot.generated.session_events import SessionEventType

logger = logging.getLogger(__name__)

NANO_AIU_PER_AI_CREDIT = 1_000_000_000


@dataclass
class ModelUsage:
    """Track usage metrics for a single model."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    llm_calls: int = 0
    api_duration_ms: int = 0


@dataclass
class QuotaUsage:
    """Track quota usage percentages from SDK events."""
    chat_remaining_percentage: Optional[str] = None
    completion_remaining_percentage: Optional[str] = None
    ai_credits_remaining_percentage: Optional[str] = None


def nano_aiu_to_ai_credits(total_nano_aiu: float | int | None) -> Optional[float]:
    """Convert SDK nano-AIU totals to AI credits."""
    if total_nano_aiu is None:
        return None
    return float(total_nano_aiu) / NANO_AIU_PER_AI_CREDIT


def format_ai_credits(value: float | int | None) -> str:
    """Format AI credits compactly for Telegram messages."""
    if value is None:
        return "N/A"
    credits = float(value)
    if credits == 0:
        return "0"
    if abs(credits) < 0.001:
        return f"{credits:.6f}".rstrip("0").rstrip(".")
    if abs(credits) < 1:
        return f"{credits:.4f}".rstrip("0").rstrip(".")
    return f"{credits:.2f}".rstrip("0").rstrip(".")


def _duration_to_ms(duration: Any) -> int:
    """Normalize SDK duration values to milliseconds."""
    if not duration:
        return 0
    total_seconds = getattr(duration, "total_seconds", None)
    if callable(total_seconds):
        return int(total_seconds() * 1000)
    return int(duration or 0)


def _parse_quota_percentage(quota_snapshot) -> str:
    """Parse quota snapshot to get remaining percentage or 'Unlimited'."""
    if not quota_snapshot:
        return "N/A"

    is_unlimited = _get_snapshot_value(quota_snapshot, "is_unlimited_entitlement")
    if is_unlimited:
        return "Unlimited"

    remaining = _get_snapshot_value(quota_snapshot, "remaining_percentage")
    if remaining is not None:
        return f"{remaining:.1f}%"

    return "N/A"


def _field_name_candidates(name: str) -> list[str]:
    """Return public, v1-private, and JSON-style aliases for an SDK field."""
    raw = name[1:] if name.startswith("_") else name
    parts = raw.split("_")
    camel = parts[0] + "".join(part.capitalize() for part in parts[1:])
    candidates = [name, raw, f"_{raw}", camel]
    result = []
    for candidate in candidates:
        if candidate not in result:
            result.append(candidate)
    return result


def _get_snapshot_value(snapshot: Any, *names: str) -> Any:
    """Read a quota snapshot field from either SDK dataclass or dict shapes."""
    for name in names:
        for candidate in _field_name_candidates(name):
            if isinstance(snapshot, dict) and candidate in snapshot:
                return snapshot[candidate]
            value = getattr(snapshot, candidate, None)
            if value is not None:
                return value
    return None


def _get_quota_snapshot(account_quota: Any, key: str) -> Any:
    if not account_quota:
        return None
    snapshots = (
        _get_snapshot_value(account_quota, "quota_snapshots", "quotaSnapshots")
        or account_quota
    )
    if isinstance(snapshots, dict):
        return snapshots.get(key)
    return getattr(snapshots, key, None)


def format_ai_credits_remaining(account_quota: Any) -> Optional[str]:
    """Format remaining AI-credit quota from account.getQuota result."""
    snapshot = _get_quota_snapshot(account_quota, "premium_interactions")
    if not snapshot:
        return None

    is_unlimited = _get_snapshot_value(snapshot, "is_unlimited_entitlement")
    if is_unlimited:
        return "Unlimited"

    remaining = _get_snapshot_value(snapshot, "remaining_percentage")
    used = _get_snapshot_value(snapshot, "used_requests")
    entitlement = _get_snapshot_value(snapshot, "entitlement_requests")
    if remaining is None or used is None or entitlement is None:
        return None

    remaining_text = f"{float(remaining):.1f}".rstrip("0").rstrip(".")
    return f"{remaining_text}% ({int(used)}/{int(entitlement)} used)"


@dataclass
class SessionInfo:
    """Session metadata captured from SDK events."""
    session_id: Optional[str] = None
    name: Optional[str] = None  # Summary from SessionMetadata
    created: Optional[str] = None  # ISO format string from SDK
    modified: Optional[str] = None  # ISO format string from SDK
    selected_model: Optional[str] = None
    copilot_version: Optional[str] = None
    producer: Optional[str] = None
    cwd: Optional[str] = None
    branch: Optional[str] = None
    git_root: Optional[str] = None
    repository: Optional[str] = None
    status: str = "Active"
    workspace_path: Optional[str] = None
    
    def duration(self) -> str:
        """Calculate session duration as formatted string."""
        if not self.created:
            return "N/A"
        
        try:
            # Parse ISO format string from SDK
            start = datetime.fromisoformat(self.created)
            now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()
            dur = (now - start).total_seconds()
            h, m = int(dur // 3600), int((dur % 3600) // 60)
            s = int(dur % 60)
            
            if h:
                return f"{h}h {m}m {s}s"
            elif m:
                return f"{m}m {s}s"
            else:
                return f"{s}s"
        except (ValueError, TypeError):
            return "N/A"


@dataclass
class SessionUsageTracker:
    """Track session usage metrics in real-time from SDK events.

    Subscribes to session events via ``session.on(tracker.handle_event)`` and
    accumulates per-model token breakdowns, quota snapshots, and session timing.
    """
    session_start_time: Optional[float] = None
    current_tokens: int = 0
    token_limit: int = 0
    messages_length: int = 0
    model_usage: Dict[str, ModelUsage] = field(default_factory=dict)
    reported_ai_credits: Optional[float] = None
    latest_quota: Optional[dict] = None  # Dict[str, QuotaSnapshot]
    quota_usage: QuotaUsage = field(default_factory=QuotaUsage)
    _selected_model: Optional[str] = None

    def handle_event(self, event):
        """Process session events to update usage metrics."""
        etype = event.type

        if etype == SessionEventType.SESSION_START:
            self.session_start_time = time.time()
            # Capture SDK-selected model
            selected = getattr(event.data, 'selected_model', None)
            if selected:
                self._selected_model = selected

        elif etype == SessionEventType.SESSION_USAGE_INFO:
            self.current_tokens = int(event.data.current_tokens or 0)
            self.token_limit = int(event.data.token_limit or 0)
            self.messages_length = int(event.data.messages_length or 0)

        elif etype == SessionEventType.ASSISTANT_USAGE:
            logger.debug(f"ASSISTANT_USAGE event: {event.data}")
            model = getattr(event.data, 'model', None) or "unknown"
            if model not in self.model_usage:
                self.model_usage[model] = ModelUsage()

            usage = self.model_usage[model]
            usage.input_tokens += int(event.data.input_tokens or 0)
            usage.output_tokens += int(event.data.output_tokens or 0)
            usage.cache_read_tokens += int(getattr(event.data, 'cache_read_tokens', 0) or 0)
            usage.cache_write_tokens += int(getattr(event.data, 'cache_write_tokens', 0) or 0)
            usage.reasoning_tokens += int(getattr(event.data, 'reasoning_tokens', 0) or 0)
            usage.llm_calls += 1
            usage.api_duration_ms += _duration_to_ms(getattr(event.data, 'duration', None))

            copilot_usage = getattr(event.data, '_copilot_usage', None)
            total_nano_aiu = getattr(copilot_usage, 'total_nano_aiu', None) if copilot_usage else None
            if isinstance(total_nano_aiu, (int, float)):
                credits = nano_aiu_to_ai_credits(total_nano_aiu)
                if credits is not None:
                    self.reported_ai_credits = (self.reported_ai_credits or 0) + credits

            # Update quota snapshots and parse into QuotaUsage
            snapshots = (
                getattr(event.data, 'quota_snapshots', None)
                or getattr(event.data, '_quota_snapshots', None)
            )
            if snapshots:
                self.latest_quota = snapshots
                # Parse quota snapshots into structured QuotaUsage
                # Handle both dict and object access patterns
                chat_snap = snapshots.get("chat") if isinstance(snapshots, dict) else getattr(snapshots, "chat", None)
                completions_snap = snapshots.get("completions") if isinstance(snapshots, dict) else getattr(snapshots, "completions", None)
                premium_snap = snapshots.get("premium_interactions") if isinstance(snapshots, dict) else getattr(snapshots, "premium_interactions", None)
                
                self.quota_usage.chat_remaining_percentage = _parse_quota_percentage(chat_snap)
                self.quota_usage.completion_remaining_percentage = _parse_quota_percentage(completions_snap)
                self.quota_usage.ai_credits_remaining_percentage = _parse_quota_percentage(premium_snap)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def selected_model(self) -> Optional[str]:
        return self._selected_model

    @selected_model.setter
    def selected_model(self, value: Optional[str]):
        self._selected_model = value

    def get_quota_display(self) -> Optional[str]:
        """Return a short quota summary string, or None if unavailable."""
        if not self.latest_quota:
            return None
        parts = []
        for key, snap in self.latest_quota.items():
            is_unlimited = _get_snapshot_value(snap, "is_unlimited_entitlement")
            if is_unlimited:
                parts.append(f"{key}: Unlimited")
            else:
                pct = _get_snapshot_value(snap, "remaining_percentage")
                if pct is not None:
                    parts.append(f"{key}: {pct:.0f}% remaining")
                else:
                    ent = _get_snapshot_value(snap, "entitlement_requests")
                    parts.append(f"{key}: {ent:.0f} remaining" if ent is not None else f"{key}: N/A")
        return "\n".join(parts) if parts else None
    
    def get_quota_summary(self) -> str:
        """Return formatted quota summary with chat/completions/premium breakdown."""
        lines = [
            f"• Chat: {self.quota_usage.chat_remaining_percentage or 'N/A'}",
            f"• Completions: {self.quota_usage.completion_remaining_percentage or 'N/A'}",
            f"• AI Credits: {self.quota_usage.ai_credits_remaining_percentage or 'N/A'}",
        ]
        return "\n".join(lines)

    def get_remaining_percentage(self) -> Optional[float]:
        """Return the first available remaining_percentage, or None."""
        if not self.latest_quota:
            return None
        for _key, snap in self.latest_quota.items():
            if _get_snapshot_value(snap, "is_unlimited_entitlement"):
                return 100.0
            pct = _get_snapshot_value(snap, "remaining_percentage")
            if pct is not None:
                return float(pct)
        return None

    async def get_usage_summary(self, sdk_metrics: Any = None, account_quota: Any = None) -> str:
        """Generate a CLI-style usage summary."""
        from src.core.git import get_diff_shortstat

        if sdk_metrics is not None:
            return await self._get_sdk_usage_summary(sdk_metrics, account_quota)

        total_api_ms = sum(u.api_duration_ms for u in self.model_usage.values())
        session_time = (time.time() - self.session_start_time) if self.session_start_time else 0

        total_llm_calls = sum(u.llm_calls for u in self.model_usage.values())
        diff_stat = await get_diff_shortstat()

        lines = [
            f"• AI credits used: {format_ai_credits(self.reported_ai_credits)}",
            f"• LLM calls: {total_llm_calls}",
            f"• API time spent: {total_api_ms / 1000:.1f}s",
            f"• Total session time: {self._format_duration(session_time)}",
            f"• Unstaged changes: {diff_stat}" if diff_stat else "• Unstaged changes: N/A",
        ]
        remaining = format_ai_credits_remaining(account_quota)
        if remaining:
            lines.insert(1, f"• AI credits remaining: {remaining}")

        if self.current_tokens or self.token_limit:
            lines.append(f"• Context tokens: {self.current_tokens}/{self.token_limit}")

        lines.append("• Breakdown by AI model:")

        if not self.model_usage:
            lines.append("  (No interactions yet)")
        else:
            for model, usage in self.model_usage.items():
                token_bits = [
                    f"{usage.input_tokens} in",
                    f"{usage.output_tokens} out",
                    f"{usage.cache_read_tokens} cache read",
                    f"{usage.cache_write_tokens} cache write",
                ]
                if usage.reasoning_tokens:
                    token_bits.append(f"{usage.reasoning_tokens} reasoning")
                lines.append(
                    f"  {model}: {usage.llm_calls} calls; {', '.join(token_bits)}"
                )

        return "\n".join(lines)

    async def _get_sdk_usage_summary(self, metrics: Any, account_quota: Any = None) -> str:
        """Generate usage summary from SDK session.usage.getMetrics result."""
        from src.core.git import get_diff_shortstat

        total_ai_credits = nano_aiu_to_ai_credits(getattr(metrics, "total_nano_aiu", None))
        total_calls = int(getattr(metrics, "total_user_requests", 0) or 0)
        total_api_ms = int(getattr(metrics, "total_api_duration_ms", 0) or 0)
        diff_stat = await get_diff_shortstat()

        lines = [
            f"• AI credits used: {format_ai_credits(total_ai_credits)}",
            f"• LLM calls: {total_calls}",
            f"• API time spent: {total_api_ms / 1000:.1f}s",
            f"• Unstaged changes: {diff_stat}" if diff_stat else "• Unstaged changes: N/A",
        ]
        remaining = format_ai_credits_remaining(account_quota)
        if remaining:
            lines.insert(1, f"• AI credits remaining: {remaining}")

        if self.current_tokens or self.token_limit:
            lines.append(f"• Context tokens: {self.current_tokens}/{self.token_limit}")

        last_input = int(getattr(metrics, "last_call_input_tokens", 0) or 0)
        last_output = int(getattr(metrics, "last_call_output_tokens", 0) or 0)
        if last_input or last_output:
            lines.append(f"• Last call: {last_input} input, {last_output} output tokens")

        lines.append("• Breakdown by AI model:")
        model_metrics = getattr(metrics, "model_metrics", {}) or {}
        if not model_metrics:
            lines.append("  (No interactions yet)")
        else:
            for model, model_metric in model_metrics.items():
                usage = getattr(model_metric, "usage", None)
                requests = getattr(model_metric, "requests", None)
                calls = int(getattr(requests, "count", 0) or 0)
                model_credits = nano_aiu_to_ai_credits(getattr(model_metric, "total_nano_aiu", None))
                if usage is None:
                    lines.append(f"  {model}: {calls} calls; {format_ai_credits(model_credits)} credits")
                    continue

                token_bits = [
                    f"{int(getattr(usage, 'input_tokens', 0) or 0)} in",
                    f"{int(getattr(usage, 'output_tokens', 0) or 0)} out",
                    f"{int(getattr(usage, 'cache_read_tokens', 0) or 0)} cache read",
                    f"{int(getattr(usage, 'cache_write_tokens', 0) or 0)} cache write",
                ]
                reasoning = int(getattr(usage, "reasoning_tokens", 0) or 0)
                if reasoning:
                    token_bits.append(f"{reasoning} reasoning")
                lines.append(
                    f"  {model}: {calls} calls; {format_ai_credits(model_credits)} credits; "
                    f"{', '.join(token_bits)}"
                )

        return "\n".join(lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        mins, secs = divmod(int(seconds), 60)
        if mins < 60:
            return f"{mins}m {secs}s"
        hours, mins = divmod(mins, 60)
        return f"{hours}h {mins}m {secs}s"
