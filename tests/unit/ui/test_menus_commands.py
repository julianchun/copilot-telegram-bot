"""Unit tests for command references in menu content."""

from src.ui.menus import get_cockpit_content, get_help_content, get_start_splash_content


def test_start_splash_includes_agent_and_resume_commands():
    content = get_start_splash_content(
        auth_status="authorized",
        cli_version="1.0.0",
        sdk_version="0.1.0",
    )

    assert "/agent - View and select custom agents" in content
    assert "/resume - Continue a previous Copilot session" in content


def test_cockpit_command_reference_includes_agent_and_resume():
    content = get_cockpit_content(
        project_name="todo-app",
        model="gpt-4.1",
        mode="Chat",
        path="/tmp/todo-app",
        branch="main",
        file_count=12,
        folder_count=3,
    )

    assert "/agent - View and select custom agents" in content
    assert "/resume - Continue a previous Copilot session" in content


def test_help_command_reference_includes_agent_and_resume():
    content = get_help_content(
        auth_status="authorized",
        version="1.0.0",
        current_model="gpt-4.1",
        cwd="/tmp/todo-app",
        project_selected=True,
    )

    assert "/agent - View and select custom agents" in content
    assert "/resume - Continue a previous Copilot session" in content
