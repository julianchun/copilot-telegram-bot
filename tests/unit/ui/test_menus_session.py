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


def test_format_session_detail_uses_v1_metadata_names():
    session = SimpleNamespace(
        session_id="session-456",
        summary="Existing work",
        start_time="2026-05-18T11:00:00",
        modified_time="2026-05-18T12:30:00",
        context=SimpleNamespace(working_directory="/repo/app", branch="feature"),
        selected_model="gpt-5",
    )

    result = format_session_detail(session)

    assert "Session: session-456" in result
    assert "Path: /repo/app" in result
    assert "Model: gpt-5" in result
    assert "Created: 05/18 11:00" in result
    assert "Updated: 05/18 12:30" in result
