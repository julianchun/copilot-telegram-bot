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

def get_main_menu_content(auth_status: str, version: str, current_model: str, cwd: str, project_selected: bool = False) -> str:
    # Shorten CWD for display
    display_cwd = str(cwd)
    # Show fallback if model not yet determined
    model_display = current_model if current_model else "Auto (determined on first use)"
    
    msg = (
        f"🚀 **Copilot CLI-Telegram**\n"
        f"**User:** `{auth_status}`\n"
        f"**Copilot Version:** `{version}`\n"
        f"**Workspace:** `{display_cwd}`\n"
        f"**Model:** `{model_display}`\n\n"
        "**Core Workflow**\n"
        "/plan - Architecture & Planning mode\n"
        "/edit - Standard Chat/Coding mode\n\n"
        "**Session Control**\n"
        "/model - Switch AI Model\n"
        "/clear - Reset conversation memory\n"
        "/cancel - Cancel in-progress request\n"
        "/share - Export session to Markdown\n"
        "/usage - Display session usage metrics\n"
        "/context - Display model context info\n"
        "/session - Show session info and workspace summary\n\n"
        "**Navigation Command**\n"
        "/ls    - List files in current directory\n"
        "/cwd   - Show current directory\n"
    )
    
    # Only show "Action Required" if no project is selected
    if not project_selected:
        msg += "\n⚠️ **Action Required:** Select or create a project below to begin."
    
    return msg

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
