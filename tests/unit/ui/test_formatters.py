"""Unit tests for src/ui/formatters.py pure functions."""

from src.ui.formatters import (
    format_tool_start,
    format_tool_complete,
    truncate_command,
    truncate_text,
    format_tokens,
    format_percentage,
)


# ── format_tool_start ────────────────────────────────────────────────────────


def test_format_tool_start_no_args():
    assert format_tool_start("some_tool", {}) == "🔧 some_tool"


def test_format_tool_start_report_intent():
    result = format_tool_start("report_intent", {"intent": "Fixing bug"})
    assert result == "🔧 report_intent - Fixing bug"


def test_format_tool_start_bash_with_command():
    result = format_tool_start("bash", {"command": "echo hello"})
    assert "bash" in result
    assert "echo hello" in result


def test_format_tool_start_bash_with_description():
    result = format_tool_start("bash", {"command": "ls", "description": "List files"})
    assert "List files" in result
    assert "ls" in result


def test_format_tool_start_view_with_path():
    result = format_tool_start("view", {"path": "/home/user/project/main.py"})
    assert result == "🔧 view - main.py"


def test_format_tool_start_create_with_preview():
    result = format_tool_start(
        "create", {"path": "/tmp/test.txt", "file_text": "Hello world content"}
    )
    assert "test.txt" in result
    assert "Preview:" in result
    assert "Hello world content" in result


def test_format_tool_start_edit_with_path():
    result = format_tool_start("edit", {"path": "/home/user/src/app.py"})
    assert result == "🔧 edit - app.py"


def test_format_tool_start_default():
    result = format_tool_start("unknown_tool", {"foo": "bar"})
    assert result == "🔧 unknown_tool"


# ── format_tool_complete ─────────────────────────────────────────────────────


def test_format_tool_complete_failure():
    assert format_tool_complete("my_tool", "err", success=False) == "❌ my_tool"


def test_format_tool_complete_unknown():
    assert format_tool_complete("unknown", "some result") == ""


def test_format_tool_complete_no_result():
    assert format_tool_complete("view", None) == ""


def test_format_tool_complete_none_string():
    assert format_tool_complete("view", "None") == ""


def test_format_tool_complete_silent_tool():
    assert format_tool_complete("bash", "output here") == ""
    assert format_tool_complete("report_intent", "ok") == ""
    assert format_tool_complete("create", "done") == ""
    assert format_tool_complete("task", "done") == ""
    assert format_tool_complete("update_todo", "done") == ""


def test_format_tool_complete_with_result():
    result = format_tool_complete("view", "file contents here")
    assert result == "✓ view → file contents here"


# ── truncate_command ─────────────────────────────────────────────────────────


def test_truncate_command_short():
    assert truncate_command("echo hi") == "$ echo hi"


def test_truncate_command_long_single_line():
    long_cmd = "a" * 300
    result = truncate_command(long_cmd, max_chars=250)
    assert result.startswith("$ ")
    assert result.endswith("...")
    # 2 for "$ " + 250 for content + 3 for "..."
    assert len(result) == 2 + 250 + 3


def test_truncate_command_multiline():
    # max_chars must be smaller than total cmd length so multiline path is reached
    lines = [f"line{i}" for i in range(10)]
    cmd = "\n".join(lines)
    result = truncate_command(cmd, max_lines=4, max_chars=20)
    assert "$ line0" in result
    assert "6 more lines..." in result


def test_truncate_command_heredoc():
    cmd = "cat <<EOF\nline1\nline2\nline3\nline4\nline5\nEOF"
    result = truncate_command(cmd)
    assert "EOF" in result
    assert "line1" in result
    assert "more lines..." in result


# ── truncate_text ────────────────────────────────────────────────────────────


def test_truncate_text_empty():
    assert truncate_text("") == ""
    assert truncate_text(None) == ""


def test_truncate_text_within_limit():
    assert truncate_text("hello world") == "hello world"


def test_truncate_text_over_limit():
    long = "a" * 200
    result = truncate_text(long, max_length=150)
    assert result.endswith("...")
    assert len(result) == 153  # 150 + "..."


# ── format_tokens ────────────────────────────────────────────────────────────


def test_format_tokens_small():
    assert format_tokens(500) == "500"


def test_format_tokens_thousands():
    assert format_tokens(1500) == "1.5k"


# ── format_percentage ────────────────────────────────────────────────────────


def test_format_percentage_normal():
    assert format_percentage(50, 100) == "50%"


def test_format_percentage_zero_limit():
    assert format_percentage(50, 0) == "0%"
