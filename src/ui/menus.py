from pathlib import Path
from typing import List, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from src.config import WORKSPACE_PATH, GRANTED_PROJECT_PATHS


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

def get_model_keyboard(models_data: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    btns = []
    for m in models_data:
        m_id = m.get("id", "unknown")
        mult = m.get("multiplier", "1x")
        btns.append(InlineKeyboardButton(f"({mult}) {m_id}", callback_data=f"model:{m_id}"))
    buttons = _build_button_grid(btns)
    return InlineKeyboardMarkup(buttons)


def format_skill_list(skills_data: List[Dict[str, Any]]) -> str:
    """Format skills list grouped by source, matching copilot-cli style."""
    if not skills_data:
        return "🧩 No skills found."

    # Group skills by source
    groups: Dict[str, list] = {}
    for s in skills_data:
        source = s.get("source", "unknown").capitalize()
        # Map SDK source names to friendly labels
        label = {
            "Project": "Project",
            "Personal": "Personal",
            "Plugin": "Built-in",
        }.get(source, source)
        groups.setdefault(label, []).append(s)

    lines = ["● Available Skills\n"]
    for label, skills in groups.items():
        lines.append(f"  {label}:")
        for s in skills:
            desc = s.get("description", "")
            desc_part = f"\n      {desc}" if desc else ""
            lines.append(f"    • {s['name']}{desc_part}")
        lines.append("")

    lines.append(
        f"Found {len(skills_data)} skill{'s' if len(skills_data) != 1 else ''}. "
        f"Use /skills info <name> to view details."
    )
    return "\n".join(lines)


def get_instructions_keyboard(has_instructions: bool) -> InlineKeyboardMarkup:
    """Build inline keyboard for instructions actions."""
    buttons = []
    if has_instructions:
        buttons.append([
            InlineKeyboardButton("👁️ View", callback_data="instr:view"),
            InlineKeyboardButton("🗑️ Clear", callback_data="instr:clear"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🔍 Generate with /init", callback_data="instr:init"),
        ])
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
        "/skills - List & inspect available skills\n"
        "/clear - Reset conversation memory\n"
        "/cancel - Cancel in-progress request\n"
        "/share - Export session to Markdown\n"
        "/usage - Display session usage metrics\n"
        "/context - Display model context info\n"
        "/session - Show session info and workspace summary\n\n"
        "Navigation\n"
        "/ls - Project file tree\n"
        "/cwd - Show current directory\n\n"
        "Utilities\n"
        "/ping - Health check\n"
        "/allowall - Toggle auto-approve permissions\n"
        "/instructions - View/set custom instructions\n"
        "/init - Generate custom instructions for project\n"
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
