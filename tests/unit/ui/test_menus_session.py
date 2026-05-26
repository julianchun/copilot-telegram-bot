"""Unit tests for session resume menu formatting."""

from types import SimpleNamespace

from src.ui.menus import format_session_detail


def test_format_session_detail_uses_sdk_start_time():
    session = SimpleNamespace(
        sessionId="session-123",
        summary="Existing work",
        startTime="2026-05-18T11:00:00",
        modifiedTime="2026-05-18T12:30:00",
        context=SimpleNamespace(cwd="/repo/app", branch="feature"),
    )

    result = format_session_detail(session)

    assert "Created: 05/18 11:00" in result
    assert "Updated: 05/18 12:30" in result
