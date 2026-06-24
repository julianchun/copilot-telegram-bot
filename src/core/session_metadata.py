"""Helpers for SDK session metadata objects and dictionaries."""

from datetime import datetime
from typing import Any


def metadata_value(item: Any, *names: str, default: Any = None) -> Any:
    """Read the first matching field from an object or dict-like metadata item."""
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def metadata_timestamp(value: Any) -> str | None:
    """Normalize SDK timestamps to strings used by SessionInfo/UI helpers."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
