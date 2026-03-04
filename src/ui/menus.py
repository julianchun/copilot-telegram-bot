from pathlib import Path
from typing import List, Dict, Any, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from src.config import WORKSPACE_PATH, GRANTED_PROJECT_PATHS


def _read_session_cwd(session_id: str) -> Optional[str]:
    """Read the cwd from ~/.copilot/session-state/<id>/workspace.yaml without PyYAML."""
    if not session_id:
        return None
    workspace = Path.home() / ".copilot" / "session-state" / session_id / "workspace.yaml"
    try:
        for line in workspace.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("cwd:"):
                return stripped[4:].strip() or None
    except Exception:
        pass
    return None


def _build_button_grid(items: List[InlineKeyboardButton], columns: int = 2) -> List[List[InlineKeyboardButton]]:
    """Build a grid of buttons with the given number of columns."""
    rows = []
    row = []
    for item in items:
        row.append(item)
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def get_project_keyboard(root_path: Path):
    if not root_path.exists():
        root_path.mkdir(parents=True, exist_ok=True)

    projects = []  # List of (name, callback_data) tuples

    # Add workspace subdirectories
    subdirs = sorted([d for d in root_path.iterdir() if d.is_dir() and not d.name.startswith('.')])
    for d in subdirs:
        projects.append((d.name, f"proj:{d.name}"))

    # Add granted projects
    for idx, granted_path in enumerate(GRANTED_PROJECT_PATHS):
        if granted_path.exists():
            projects.append((granted_path.name, f"proj_granted:{idx}"))

    projects.sort(key=lambda x: x[0].lower())

    btns = [InlineKeyboardButton(f"📂 {name}", callback_data=cb) for name, cb in projects]
    buttons = _build_button_grid(btns)
    buttons.append([InlineKeyboardButton("➕ Create New Project", callback_data="proj_new")])
    return InlineKeyboardMarkup(buttons)

_NOISE_PREFIXES = (
    "You are in GENERAL Mode",
    "You are in PLAN MODE",
    "You are assisting via a Telegram bot",
    "Please review the following git diff",
    "Generate a concise",
)

def _clean_summary(raw: str | None) -> str:
    """Return a display-friendly session summary, stripping system prompt noise."""
    if not raw:
        return "No summary"
    stripped = raw.strip()
    for prefix in _NOISE_PREFIXES:
        if stripped.startswith(prefix):
            return "—"
    return stripped[:38]


_PROJECT_ICONS = ["🔵", "🟢", "🟡", "🟠", "🔴", "🟣", "🟤", "⚪", "🔶", "🔷"]


def get_sessions_keyboard(sessions, cwd_filter: Optional[str] = None):
    """Build inline keyboard listing recent sessions for /sessions command.

    Returns (header_text, InlineKeyboardMarkup).

    If cwd_filter is provided, only sessions whose workspace.yaml cwd matches are shown.
    If cwd_filter is None, sessions from all projects are shown; each project gets a unique
    icon that appears both in the header legend and as a prefix on each session button.
    """
    sorted_sessions = sorted(
        sessions, key=lambda s: getattr(s, 'modifiedTime', '') or '', reverse=True
    )

    def _make_btn(s, session_id, icon=""):
        summary = _clean_summary(getattr(s, 'summary', None))
        start_time = getattr(s, 'startTime', None) or ""
        date_str = start_time[:10]
        time_str = start_time[11:16] if len(start_time) >= 16 else ""
        short_id = session_id[-8:] if len(session_id) > 8 else session_id
        prefix = f"{icon} " if icon else ""
        label = f"{prefix}{date_str} {time_str} [{short_id}]  {summary}"
        return InlineKeyboardButton(label, callback_data=f"session:{session_id}")

    if cwd_filter:
        # Single-project view: flat list filtered by CWD
        btns = []
        for s in sorted_sessions:
            if len(btns) >= 10:
                break
            session_id = getattr(s, 'sessionId', None) or str(s)
            if _read_session_cwd(session_id) != cwd_filter:
                continue
            btns.append(_make_btn(s, session_id))
        if not btns:
            btns.append(InlineKeyboardButton("No sessions for this project", callback_data="session:none"))
        return "Select a session to resume:", InlineKeyboardMarkup([[btn] for btn in btns])
    else:
        # All-projects view: assign icon per project, list legend in header
        from collections import defaultdict, OrderedDict
        groups: dict = OrderedDict()
        for s in sorted_sessions:
            session_id = getattr(s, 'sessionId', None) or str(s)
            cwd = _read_session_cwd(session_id)
            project = Path(cwd).name if cwd else "Unknown"
            if project not in groups:
                groups[project] = []
            groups[project].append((s, session_id))

        # Assign icons
        icon_map = {p: _PROJECT_ICONS[i % len(_PROJECT_ICONS)] for i, p in enumerate(groups)}

        # Build header legend
        legend = "\n".join(f"{icon_map[p]} {p}" for p in groups)
        header = f"All sessions by project:\n{legend}\n\nSelect to resume:"

        # Build buttons with icon prefix, up to 5 per project
        rows = []
        for project, items in groups.items():
            icon = icon_map[project]
            for s, session_id in items[:5]:
                rows.append([_make_btn(s, session_id, icon=icon)])

        if not rows:
            rows.append([InlineKeyboardButton("No sessions found", callback_data="session:none")])
        return header, InlineKeyboardMarkup(rows)


def get_model_keyboard(models_data: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    btns = []
    for m in models_data:
        m_id = m.get("id", "unknown")
        mult = m.get("multiplier", "1x")
        btns.append(InlineKeyboardButton(f"({mult}) {m_id}", callback_data=f"model:{m_id}"))
    buttons = _build_button_grid(btns)
    return InlineKeyboardMarkup(buttons)

def _command_reference() -> str:
    """Return the full command reference block."""
    return (
        "/start - Open project selection menu\n"
        "/help - Show help manual\n\n"
        "Core Workflow\n"
        "/plan - Architecture & Planning mode\n"
        "/edit - Standard Chat/Coding mode\n\n"
        "Session Control\n"
        "/model - Switch AI Model\n"
        "/effort - Set reasoning effort level\n"
        "/sessions - Browse & resume past sessions\n"
        "/clear - Reset conversation memory\n"
        "/compact - Compact context (smart reset)\n"
        "/cancel - Cancel in-progress request\n"
        "/share - Export session to Markdown\n"
        "/usage - Display session usage metrics\n"
        "/context - Display model context info\n"
        "/session - Show session info and workspace summary\n"
        "/infinite - Toggle infinite sessions (auto-compaction)\n"
        "/allowall - Toggle allow-all-tools mode\n\n"
        "Code Tools\n"
        "/diff - Show git diff\n"
        "/review - AI code review of current diff\n"
        "/changelog - Generate changelog from git log\n"
        "/instructions - View Copilot instructions file\n\n"
        "Navigation\n"
        "/ls - Project file tree\n"
        "/cwd - Show current directory\n\n"
        "Utilities\n"
        "/ping - Check CLI connection status\n"
        "/update - Update Copilot CLI\n"
    )


def get_start_splash_content(auth_status: str, cli_version: str, sdk_version: str = "") -> str:
    """Minimal start splash — bot identity + project picker prompt. No commands."""
    sdk_line = f"SDK version: {sdk_version}\n" if sdk_version else ""
    return (
        f"🚀 Copilot CLI-Telegram\n"
        f"User: {auth_status}\n"
        f"CLI version: {cli_version}\n"
        f"{sdk_line}\n"
        "⚠️ Select a project below to begin."
    )


def get_cockpit_content(
    project_name: str,
    model: str,
    mode: str,
    path: str,
    branch: str,
    file_count: int,
    folder_count: int,
) -> str:
    """Cockpit message sent after project selection — stats + commands."""
    branch_line = f"🔀 Branch: {branch}\n" if branch else ""
    return (
        f"✅ Project Loaded: {project_name}\n\n"
        f"🤖 Model: {model}\n"
        f"⚙️ Mode: {mode}\n"
        f"📂 Path: {path}\n"
        f"{branch_line}"
        f"📊 Stats: {file_count} files · {folder_count} folders\n\n"
        f"{_command_reference()}"
    )


def get_help_content(
    auth_status: str,
    version: str,
    current_model: str,
    cwd: str,
    project_selected: bool = False,
) -> str:
    """Status-aware help with 🟢/🔴 indicator and full command list."""
    status_dot = "🟢" if project_selected else "🔴"
    model_display = current_model if current_model else "Auto"
    return (
        f"{status_dot} Copilot CLI-Telegram\n"
        f"User: {auth_status}\n"
        f"Workspace: {cwd}\n"
        f"Model: {model_display}\n\n"
        f"{_command_reference()}"
        + ("" if project_selected else "\n⚠️ Action Required: Select or create a project to begin.")
    )


def get_reasoning_keyboard(model_id: str, supported_efforts: list, default_effort: str = None):
    """Build inline keyboard for reasoning effort selection."""
    effort_labels = {
        "low": "Low",
        "medium": "Medium", 
        "high": "High",
        "xhigh": "XHigh",
    }
    btns = []
    for effort in supported_efforts:
        label = effort_labels.get(effort, effort.capitalize())
        if default_effort and effort == default_effort:
            label += " (default)"
        btns.append(InlineKeyboardButton(label, callback_data=f"reasoning:{model_id}:{effort}"))
    buttons = _build_button_grid(btns)
    # Add skip button to use default
    buttons.append([InlineKeyboardButton("Skip (use default)", callback_data=f"reasoning:{model_id}:default")])
    return InlineKeyboardMarkup(buttons)
