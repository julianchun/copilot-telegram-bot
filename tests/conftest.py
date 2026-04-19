"""Shared test fixtures for the copilot-telegram-bot test suite."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest


# ---------------------------------------------------------------------------
# Telegram mock fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_user():
    """Fake Telegram User."""
    user = MagicMock()
    user.id = 12345
    user.username = "testuser"
    user.first_name = "Test"
    return user


@pytest.fixture
def mock_chat():
    """Fake Telegram Chat with async send_message."""
    chat = MagicMock()
    chat.id = 99999
    chat.send_message = AsyncMock()
    return chat


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Fake Telegram Message."""
    msg = MagicMock()
    msg.chat = mock_chat
    msg.from_user = mock_user
    msg.reply_text = AsyncMock()
    msg.delete = AsyncMock()
    msg.text = "hello"
    msg.document = None
    msg.photo = None
    return msg


@pytest.fixture
def mock_update(mock_user, mock_message):
    """Fake Telegram Update with message + effective_user."""
    update = MagicMock()
    update.effective_user = mock_user
    update.effective_message = mock_message
    update.message = mock_message
    update.callback_query = None
    return update


@pytest.fixture
def mock_callback_query(mock_user, mock_message):
    """Fake Telegram CallbackQuery."""
    query = MagicMock()
    query.from_user = mock_user
    query.message = mock_message
    query.data = ""
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    return query


@pytest.fixture
def mock_context():
    """Fake telegram.ext ContextTypes.DEFAULT_TYPE."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot_data = {}
    ctx.user_data = {}
    ctx.chat_data = {}
    return ctx


# ---------------------------------------------------------------------------
# Service / context fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_service():
    """Patched CopilotService singleton with common attributes stubbed."""
    svc = MagicMock()
    svc.project_selected = True
    svc.session = MagicMock()
    svc.session_id = "test-1234"
    svc.current_model = "gpt-4.1"
    svc.current_mode = "interactive"
    svc.current_agent = None
    svc._is_running = True
    svc.session_expired = False

    svc.chat = AsyncMock(return_value=None)
    svc.start = AsyncMock()
    svc.stop = AsyncMock()
    svc.reset_session = AsyncMock()
    svc.change_model = AsyncMock()
    svc.set_mode = AsyncMock(return_value=True)
    svc.list_agents = AsyncMock(return_value=[])
    svc.get_current_agent = AsyncMock(return_value=None)
    svc.select_agent = AsyncMock(return_value=True)
    svc.deselect_agent = AsyncMock(return_value=True)
    svc.reload_agents = AsyncMock(return_value=[])
    svc.get_usage_report = AsyncMock(return_value="usage report")
    svc.get_session_info = MagicMock()
    svc.get_working_directory = MagicMock(return_value="/tmp/workspace")
    svc.get_git_info = AsyncMock(return_value="@main")
    svc.get_directory_listing = MagicMock(return_value="📁 src/\n📄 main.py")
    svc.get_project_structure = MagicMock(return_value="📁 src/")
    svc.get_available_models = MagicMock(return_value=[])
    svc.get_model_context_limit = MagicMock(return_value=128000)
    svc.get_project_info_header = AsyncMock(return_value="header")
    svc.get_cockpit_message = AsyncMock(return_value="cockpit")
    svc.export_session_to_file = AsyncMock(return_value="/tmp/export.md")
    svc.get_cli_version = AsyncMock(return_value="1.0.0")
    svc.get_auth_status = AsyncMock(return_value="testuser")
    svc.get_usage_metadata = MagicMock(return_value=("project", "gpt-4.1", 0.0))

    svc.usage_tracker = MagicMock()
    svc.usage_tracker.get_usage_summary = AsyncMock(return_value="summary")
    svc.usage_tracker.get_quota_display = MagicMock(return_value="quota")
    svc.usage_tracker.get_quota_summary = MagicMock(return_value="quota summary")
    svc.usage_tracker.current_tokens = 1000
    svc.usage_tracker.token_limit = 128000

    svc.session_info = MagicMock()
    svc.session_info.session_id = "test-1234"
    svc.session_info.selected_model = "gpt-4.1"
    svc.session_info.cwd = "/tmp/workspace"
    svc.session_info.branch = "main"
    svc.session_info.duration.return_value = "5m 30s"

    return svc


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory with sample files."""
    # Create directory structure
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')")
    (src / "utils.py").write_text("# utils")

    # Hidden dir (should be filtered)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]")

    # Ignored dir
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "cache.pyc").write_bytes(b"\x00\x01")

    # Regular files
    (tmp_path / "README.md").write_text("# Test Project")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")

    return tmp_path


# ---------------------------------------------------------------------------
# SDK event mock helpers
# ---------------------------------------------------------------------------

def make_event(event_type, **data_attrs):
    """Create a fake SDK SessionEvent with the given type and data attributes."""
    event = MagicMock()
    event.type = event_type
    event.timestamp = datetime.now()
    event.ephemeral = False
    for key, value in data_attrs.items():
        setattr(event.data, key, value)
    return event
