"""Session usage tracking — accumulates metrics from SDK events."""
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict

from copilot.generated.session_events import SessionEventType

logger = logging.getLogger(__name__)


@dataclass
class ModelUsage:
    """Track usage metrics for a single model."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0
    cost: float = 0  # Premium requests estimate
    api_duration_ms: int = 0


@dataclass
class QuotaUsage:
    """Track quota usage percentages from SDK events."""
    chat_remaining_percentage: Optional[str] = None
    completion_remaining_percentage: Optional[str] = None
    premium_remaining_percentage: Optional[str] = None


def _parse_quota_percentage(quota_snapshot) -> str:
    """Parse quota snapshot to get remaining percentage or 'Unlimited'."""
    if not quota_snapshot:
        return "N/A"
    
    is_unlimited = getattr(quota_snapshot, "is_unlimited_entitlement", False)
    if is_unlimited:
        return "Unlimited"
    
    remaining = getattr(quota_snapshot, "remaining_percentage", None)
    if remaining is not None:
        return f"{remaining:.1f}%"
    
    return "N/A"


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
    total_premium_requests: float = 0
    code_changes: Dict[str, int] = field(default_factory=lambda: {"added": 0, "removed": 0})
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
            model = getattr(event.data, 'model', None) or "unknown"
            if model not in self.model_usage:
                self.model_usage[model] = ModelUsage()

            usage = self.model_usage[model]
            usage.input_tokens += int(event.data.input_tokens or 0)
            usage.output_tokens += int(event.data.output_tokens or 0)
            usage.cache_read_tokens += int(getattr(event.data, 'cache_read_tokens', 0) or 0)
            usage.cache_write_tokens += int(getattr(event.data, 'cache_write_tokens', 0) or 0)
            usage.cost += float(getattr(event.data, 'cost', 0) or 0)
            usage.requests += 1
            usage.api_duration_ms += int(getattr(event.data, 'duration', 0) or 0)

            # Update quota snapshots and parse into QuotaUsage
            snapshots = getattr(event.data, 'quota_snapshots', None)
            if snapshots:
                self.latest_quota = snapshots
                # Parse quota snapshots into structured QuotaUsage
                # Handle both dict and object access patterns
                chat_snap = snapshots.get("chat") if isinstance(snapshots, dict) else getattr(snapshots, "chat", None)
                completions_snap = snapshots.get("completions") if isinstance(snapshots, dict) else getattr(snapshots, "completions", None)
                premium_snap = snapshots.get("premium_interactions") if isinstance(snapshots, dict) else getattr(snapshots, "premium_interactions", None)
                
                self.quota_usage.chat_remaining_percentage = _parse_quota_percentage(chat_snap)
                self.quota_usage.completion_remaining_percentage = _parse_quota_percentage(completions_snap)
                self.quota_usage.premium_remaining_percentage = _parse_quota_percentage(premium_snap)

        elif etype == SessionEventType.SESSION_SHUTDOWN:
            self.total_premium_requests = float(getattr(event.data, 'total_premium_requests', 0) or 0)
            code_changes = getattr(event.data, 'code_changes', None)
            if code_changes:
                self.code_changes["added"] = int(getattr(code_changes, 'lines_added', 0) or 0)
                self.code_changes["removed"] = int(getattr(code_changes, 'lines_removed', 0) or 0)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def selected_model(self) -> Optional[str]:
        return self._selected_model

    def get_quota_display(self) -> Optional[str]:
        """Return a short quota summary string, or None if unavailable."""
        if not self.latest_quota:
            return None
        parts = []
        for key, snap in self.latest_quota.items():
            is_unlimited = getattr(snap, 'is_unlimited_entitlement', False)
            if is_unlimited:
                parts.append(f"{key}: Unlimited")
            else:
                pct = getattr(snap, 'remaining_percentage', None)
                if pct is not None:
                    parts.append(f"{key}: {pct:.0f}% remaining")
                else:
                    ent = getattr(snap, 'entitlement_requests', 0)
                    parts.append(f"{key}: {ent:.0f} remaining")
        return "\n".join(parts) if parts else None
    
    def get_quota_summary(self) -> str:
        """Return formatted quota summary with chat/completions/premium breakdown."""
        lines = [
            f"• Chat: {self.quota_usage.chat_remaining_percentage or 'N/A'}",
            f"• Completions: {self.quota_usage.completion_remaining_percentage or 'N/A'}",
            f"• Premium Interactions: {self.quota_usage.premium_remaining_percentage or 'N/A'}",
        ]
        return "\n".join(lines)

    def get_remaining_percentage(self) -> Optional[float]:
        """Return the first available remaining_percentage, or None."""
        if not self.latest_quota:
            return None
        for _key, snap in self.latest_quota.items():
            if getattr(snap, 'is_unlimited_entitlement', False):
                return 100.0
            pct = getattr(snap, 'remaining_percentage', None)
            if pct is not None:
                return float(pct)
        return None

    def get_usage_summary(self) -> str:
        """Generate a CLI-style usage summary."""
        total_api_ms = sum(u.api_duration_ms for u in self.model_usage.values())
        session_time = (time.time() - self.session_start_time) if self.session_start_time else 0

        total_cost = sum(u.cost for u in self.model_usage.values())

        lines = [
            f"• Total usage est:        {total_cost:.0f} request cost",
            f"• API time spent:         {total_api_ms / 1000:.1f}s",
            f"• Total session time:     {self._format_duration(session_time)}",
            f"• Total code changes:     +{self.code_changes['added']} -{self.code_changes['removed']}",
        ]

        if self.current_tokens or self.token_limit:
            lines.append(f"• Context tokens:         {self.current_tokens}/{self.token_limit}")

        lines.append("• Breakdown by AI model:")

        if not self.model_usage:
            lines.append("  (No interactions yet)")
        else:
            for model, usage in self.model_usage.items():
                lines.append(
                    f"  {model}: Est. {usage.cost} request cost"
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
