from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from src.config import GRANTED_PROJECT_PATHS, TELEGRAM_MSG_LIMIT


SELECTION_BUTTON_COLUMNS = 3
SELECTION_PAGE_SIZE = SELECTION_BUTTON_COLUMNS * 3
SESSIONS_PAGE_SIZE = 6


@dataclass(frozen=True)
class SelectionOption:
    text: str
    callback_data: str
    selected: bool = False


@dataclass(frozen=True)
class ProjectEntry:
    name: str
    path: Path


def _build_button_grid(
    items: List[InlineKeyboardButton],
    columns: int = SELECTION_BUTTON_COLUMNS,
) -> List[List[InlineKeyboardButton]]:
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


def _selection_base_lines(header_text: str) -> list[str]:
    header = (header_text or "").rstrip()
    if not header:
        return []
    return [header, ""]


def _selection_footer(prompt: str, page: int, total_pages: int) -> str:
    if not prompt:
        return ""
    if total_pages <= 1:
        return prompt
    return f"Page {page + 1}/{total_pages} · {prompt}"


def _selection_line(number: int, option: SelectionOption) -> str:
    suffix = " ✅" if option.selected else ""
    return f"{number}. {option.text}{suffix}"


def _fit_selection_line(
    number: int,
    option: SelectionOption,
    base_lines: list[str],
    footer: str,
) -> str:
    suffix = " ✅" if option.selected else ""
    prefix = f"{number}. "
    skeleton = [*base_lines, f"{prefix}{suffix}"]
    if footer:
        skeleton.extend(["", footer])
    available = TELEGRAM_MSG_LIMIT - len("\n".join(skeleton))
    if available <= 0:
        display = "..."
    elif len(option.text) <= available:
        display = option.text
    elif available <= 3:
        display = option.text[:available]
    else:
        display = option.text[:available - 3].rstrip() + "..."
    return f"{prefix}{display}{suffix}"


def _paginate_selection_options(
    header_text: str,
    options: list[SelectionOption],
    prompt: str,
    max_items_per_page: int,
) -> list[tuple[int, int]]:
    if not options:
        return [(0, 0)]

    base_lines = _selection_base_lines(header_text)
    footer = _selection_footer(prompt, 98, 99)
    pages: list[tuple[int, int]] = []
    start = 0

    while start < len(options):
        current_lines: list[str] = []
        end = start
        while end < len(options) and (end - start) < max_items_per_page:
            candidate_lines = [*base_lines, *current_lines, _selection_line(end + 1, options[end])]
            if footer:
                candidate_lines.extend(["", footer])
            if len("\n".join(candidate_lines)) <= TELEGRAM_MSG_LIMIT:
                current_lines.append(_selection_line(end + 1, options[end]))
                end += 1
                continue
            if end == start:
                end += 1
            break
        pages.append((start, end))
        start = end

    return pages


def build_numbered_selection_menu(
    header_text: str,
    options: list[SelectionOption],
    *,
    prompt: str = "Select an option:",
    page: int = 0,
    button_columns: int = SELECTION_BUTTON_COLUMNS,
    page_callback_builder: Callable[[int], str] | None = None,
    action_rows: list[list[InlineKeyboardButton]] | None = None,
    max_items_per_page: int = SELECTION_PAGE_SIZE,
) -> tuple[str, InlineKeyboardMarkup]:
    pages = _paginate_selection_options(header_text, options, prompt, max_items_per_page)
    page = max(0, min(page, len(pages) - 1))
    start, end = pages[page]
    footer = _selection_footer(prompt, page, len(pages))

    lines = _selection_base_lines(header_text)
    for index in range(start, end):
        lines.append(_fit_selection_line(index + 1, options[index], lines, footer))
    if footer:
        if lines:
            lines.append("")
        lines.append(footer)
    text = "\n".join(lines).strip()

    buttons = [
        InlineKeyboardButton(
            f"{index + 1}{' ✅' if options[index].selected else ''}",
            callback_data=options[index].callback_data,
        )
        for index in range(start, end)
    ]
    rows = _build_button_grid(buttons, columns=button_columns) if buttons else []

    if len(pages) > 1 and page_callback_builder:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=page_callback_builder(page - 1)))
        if page < len(pages) - 1:
            nav_row.append(InlineKeyboardButton("Next ▶", callback_data=page_callback_builder(page + 1)))
        if nav_row:
            rows.append(nav_row)

    if action_rows:
        rows.extend(action_rows)

    return text, InlineKeyboardMarkup(rows)


def get_project_entries(root_path: Path) -> list[ProjectEntry]:
    if not root_path.exists():
        root_path.mkdir(parents=True, exist_ok=True)

    entries: list[ProjectEntry] = []
    subdirs = sorted([d for d in root_path.iterdir() if d.is_dir() and not d.name.startswith(".")])
    entries.extend(ProjectEntry(name=d.name, path=d) for d in subdirs)
    entries.extend(ProjectEntry(name=granted_path.name, path=granted_path) for granted_path in GRANTED_PROJECT_PATHS if granted_path.exists())
    return sorted(entries, key=lambda item: item.name.lower())


def get_project_menu(root_path: Path, header_text: str, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    entries = get_project_entries(root_path)
    options = [
        SelectionOption(text=entry.name, callback_data=f"projsel:{index}")
        for index, entry in enumerate(entries)
    ]
    action_rows = [[InlineKeyboardButton("➕ Create New Project", callback_data="proj_new")]]
    return build_numbered_selection_menu(
        header_text,
        options,
        prompt="Select a project:",
        page=page,
        page_callback_builder=lambda next_page: f"projpage:{next_page}",
        action_rows=action_rows,
    )


def get_project_keyboard(root_path: Path, page: int = 0):
    return get_project_menu(root_path, "", page=page)[1]


def get_model_menu(models_data: List[Dict[str, Any]], current_model: str | None = None, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    options = []
    for m in models_data:
        m_id = m.get("id", "unknown")
        mult = m.get("multiplier", "1x")
        options.append(
            SelectionOption(
                text=f"{m_id} ({mult})",
                callback_data=f"model:{m_id}",
                selected=m_id == current_model,
            )
        )
    header = "🤖 Select a model:"
    return build_numbered_selection_menu(
        header,
        options,
        prompt="Select a model:",
        page=page,
        page_callback_builder=lambda next_page: f"model_page:{next_page}",
        action_rows=[[InlineKeyboardButton("❌ Cancel", callback_data="model:__cancel__")]],
    )


def get_model_keyboard(models_data: List[Dict[str, Any]], current_model: str | None = None, page: int = 0) -> InlineKeyboardMarkup:
    return get_model_menu(models_data, current_model=current_model, page=page)[1]


def _session_attr(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def short_session_id(session_id: str | None) -> str:
    """Display a readable short session ID while callbacks keep the full value."""
    if not session_id:
        return "unknown"
    return session_id if len(session_id) <= 12 else f"{session_id[:8]}...{session_id[-4:]}"


def _compact_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown time"
    normalized = text
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text.replace("T", " ").replace("Z", "").split(".", 1)[0]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone().strftime("%m/%d %H:%M")


def _session_context(session: Any) -> Any:
    return _session_attr(session, "context", default=None)


def _session_cwd(session: Any) -> str | None:
    context = _session_context(session)
    return _session_attr(context, "cwd", default=None)


def _session_branch(session: Any) -> str | None:
    context = _session_context(session)
    return _session_attr(context, "branch", default=None)


def _session_model(session: Any) -> str:
    context = _session_context(session)
    return (
        _session_attr(session, "model", "selectedModel", "selected_model", "currentModel", "current_model", default=None)
        or _session_attr(context, "model", "selectedModel", "selected_model", "currentModel", "current_model", default=None)
        or "model unknown"
    )


def _session_project(session: Any) -> str:
    cwd = _session_cwd(session) or _session_attr(session, "cwd", default=None)
    return Path(cwd).name if cwd else "unknown project"


def _session_summary(session: Any) -> str:
    return _session_attr(session, "summary", "name", default=None) or "(untitled session)"


def _session_modified(session: Any) -> str:
    return _compact_timestamp(_session_attr(session, "modifiedTime", "modified", default=None))


def _session_created(session: Any) -> str:
    return _compact_timestamp(_session_attr(session, "startTime", "createdTime", "created", default=None))


def _session_overview_line(number: int, session: Any) -> str:
    session_id = _session_attr(session, "sessionId", "session_id", default=None)
    branch = _session_branch(session) or "no branch"
    return (
        f"{number}. {_session_summary(session)}\n"
        f"   {short_session_id(session_id)} · {_session_project(session)} · {branch}\n"
        f"   Updated {_session_modified(session)}"
    )


def format_session_detail(session: Any) -> str:
    """Format a single session details card for Telegram."""
    session_id = _session_attr(session, "sessionId", "session_id", default=None) or "unknown"
    cwd = _session_cwd(session) or _session_attr(session, "cwd", default=None) or "unknown path"
    branch = _session_branch(session) or _session_attr(session, "branch", default=None) or "N/A"
    return (
        "🧷 Session Details\n"
        f"• Session: {session_id}\n"
        f"• Summary: {_session_summary(session)}\n"
        f"• Project: {_session_project(session)}\n"
        f"• Path: {cwd}\n"
        f"• Branch: {branch}\n"
        f"• Model: {_session_model(session)}\n"
        f"• Created: {_session_created(session)}\n"
        f"• Updated: {_session_modified(session)}"
    )


def attach_success_title(target: str) -> str:
    if target == "last":
        return "✅ Latest Session Attached"
    return "✅ Session Attached"


def format_attached_session(
    session_info: Any,
    *,
    fallback_session_id: str | None = None,
    fallback_cwd: str | None = None,
    fallback_model: str | None = None,
    prefix: str = "✅ Attached",
) -> str:
    session_id = _session_attr(session_info, "sessionId", "session_id", default=None) or fallback_session_id
    cwd = _session_cwd(session_info) or _session_attr(session_info, "cwd", default=None) or fallback_cwd or "unknown path"
    branch = _session_branch(session_info) or _session_attr(session_info, "branch", default=None) or "N/A"
    model = _session_model(session_info)
    if model == "model unknown" and fallback_model:
        model = fallback_model
    return (
        f"{prefix}\n"
        f"• Session: {short_session_id(session_id)}\n"
        f"• Summary: {_session_summary(session_info)}\n"
        f"• Path: {cwd}\n"
        f"• Branch: {branch}\n"
        f"• Model: {model}\n\n"
        "Send a message to continue."
    )


def get_session_detail_actions(session_id: str | None) -> InlineKeyboardMarkup | None:
    if not session_id:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Attach", callback_data=f"sessattach:{session_id}")],
        [InlineKeyboardButton("⬅ Back", callback_data="sessions_page:0")],
    ])


def get_sessions_menu(
    sessions: List[Any],
    page: int = 0,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build a paginated session dashboard with detail buttons."""
    if not sessions:
        return "📭 No Copilot sessions found.", None

    sorted_sessions = sorted(
        sessions,
        key=lambda item: _session_attr(item, "modifiedTime", "modified", default="") or "",
        reverse=True,
    )

    total_pages = max(1, (len(sorted_sessions) + SESSIONS_PAGE_SIZE - 1) // SESSIONS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * SESSIONS_PAGE_SIZE
    page_sessions = sorted_sessions[start:start + SESSIONS_PAGE_SIZE]

    lines = [
        "🧷 Resume Session",
        "",
    ]
    for page_number, session in enumerate(page_sessions, start=1):
        lines.append(_session_overview_line(page_number, session))
    lines.extend([
        "",
        f"Page {page + 1}/{total_pages} · Select a session:",
    ])

    rows: list[list[InlineKeyboardButton]] = []
    for page_number, session in enumerate(page_sessions, start=1):
        session_id = _session_attr(session, "sessionId", "session_id", default="") or ""
        if not session_id:
            continue
        if not rows or len(rows[-1]) == SELECTION_BUTTON_COLUMNS:
            rows.append([])
        rows[-1].append(InlineKeyboardButton(str(page_number), callback_data=f"sessdetail:{session_id}"))

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=f"sessions_page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶", callback_data=f"sessions_page:{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    return "\n".join(lines), InlineKeyboardMarkup(rows)


def get_skill_source_display(source: str) -> tuple[str, str]:
    """Return the normalized source label and icon for a skill source."""
    normalized = (source or "unknown").capitalize()
    label = {
        "Project": "Project",
        "Personal": "Personal",
        "Plugin": "Built-in",
    }.get(normalized, normalized)
    icon = {
        "Project": "📂",
        "Personal": "👤",
        "Built-in": "📦",
    }.get(label, "📁")
    return label, icon


def format_skill_list(skills_data: List[Dict[str, Any]]) -> str:
    """Format skills list grouped by source, card style for Telegram mobile."""
    if not skills_data:
        return "🧩 No skills found."

    # Group skills by source
    groups: Dict[str, list] = {}
    for s in skills_data:
        label, _ = get_skill_source_display(s.get("source", "unknown"))
        groups.setdefault(label, []).append(s)

    lines = ["🧩 Available Skills\n"]
    for label, skills in groups.items():
        _, icon = get_skill_source_display(label)
        lines.append(f"{icon} {label}")
        for s in skills:
            desc = s.get("description", "")
            if desc:
                if len(desc) > 120:
                    desc = desc[:117] + "..."
                lines.append(f"  {s['name']}\n  {desc}")
            else:
                lines.append(f"  {s['name']}")
        lines.append("")

    count = len(skills_data)
    lines.append(f"{count} skill{'s' if count != 1 else ''} found.")
    lines.append("/skills info <name> · /skills reload")
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
        "/autopilot - Autonomous execution mode\n"
        "/edit - Standard Chat/Coding mode\n"
        "/agent - View and select custom agents\n\n"
        "Session Control\n"
        "/model - Switch AI Model\n"
        "/skills - List & inspect available skills\n"
        "/clear - Reset conversation memory\n"
        "/cancel - Cancel in-progress request\n"
        "/share - Export session to Markdown\n"
        "/usage - Display session usage metrics\n"
        "/context - Display model context info\n"
        "/session - Session management (info, files, plan)\n\n"
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
        "⚠️ Select a project to begin."
    )


def get_cockpit_content(
    project_name: str,
    model: str,
    mode: str,
    path: str,
    branch: str,
    file_count: int,
    folder_count: int,
    agent: str | None = None,
) -> str:
    """Cockpit message sent after project selection — stats + commands."""
    branch_line = f"🔀 Branch: {branch}\n" if branch else ""
    agent_line = f"🤖 Agent: {agent}\n" if agent else ""
    return (
        f"✅ Project Loaded: {project_name}\n\n"
        f"🤖 Model: {model}\n"
        f"⚙️ Mode: {mode}\n"
        f"{agent_line}"
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


def get_reasoning_menu(
    model_id: str,
    supported_efforts: list,
    default_effort: str = None,
    current_effort: str | None = None,
    page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build numbered selection menu for reasoning effort selection."""
    effort_labels = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "xhigh": "XHigh",
    }
    options: list[SelectionOption] = []
    for effort in supported_efforts:
        label = effort_labels.get(effort, effort.capitalize())
        is_default = default_effort and effort == default_effort
        if is_default:
            label += " (model default)"
        is_selected = current_effort == effort or (
            current_effort is None and default_effort == effort
        )
        options.append(
            SelectionOption(
                text=label,
                callback_data=f"reasoning:{model_id}:{'default' if is_default else effort}",
                selected=is_selected,
            )
        )
    header = f"🤖 Model: {model_id}"
    return build_numbered_selection_menu(
        header,
        options,
        prompt="Select reasoning effort:",
        page=page,
        page_callback_builder=lambda next_page: f"reasoning_page:{model_id}:{next_page}",
    )


def get_reasoning_keyboard(
    model_id: str,
    supported_efforts: list,
    default_effort: str = None,
    current_effort: str | None = None,
    page: int = 0,
):
    return get_reasoning_menu(
        model_id,
        supported_efforts,
        default_effort=default_effort,
        current_effort=current_effort,
        page=page,
    )[1]


def get_agent_menu(agents: list, current_agent: str | None = None, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """Build numbered selection menu for agent selection."""
    options = [
        SelectionOption(
            text="Default (No Agent)",
            callback_data="agent:__default__",
            selected=current_agent is None,
        )
    ]
    for agent in agents:
        name = agent.name if hasattr(agent, "name") else agent.get("name", "unknown")
        display = agent.display_name if hasattr(agent, "display_name") else agent.get("display_name", name)
        options.append(
            SelectionOption(
                text=display or name,
                callback_data=f"agent:{name}",
                selected=name == current_agent,
            )
        )

    action_rows = [[InlineKeyboardButton("🔄 Reload Agents", callback_data="agent:__reload__")]]
    return build_numbered_selection_menu(
        "🤖 Select an agent:",
        options,
        prompt="Select an agent:",
        page=page,
        page_callback_builder=lambda next_page: f"agent_page:{next_page}",
        action_rows=action_rows,
    )


def get_agent_keyboard(agents: list, current_agent: str | None = None, page: int = 0) -> InlineKeyboardMarkup:
    return get_agent_menu(agents, current_agent=current_agent, page=page)[1]


def get_input_selection_menu(
    prompt: str,
    options: list[Any],
    interaction_id: str,
    *,
    allow_freeform: bool = True,
    page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    selection_options = [
        SelectionOption(text=str(option), callback_data=f"input:{interaction_id}:{index}")
        for index, option in enumerate(options)
    ]
    action_rows = [[InlineKeyboardButton("❌ Cancel", callback_data=f"input:{interaction_id}:cancel")]]
    header = f"❓ Copilot Asks:\n{prompt}"
    if selection_options and allow_freeform:
        prompt_text = "Reply with text or select an option:"
    elif selection_options:
        prompt_text = "Select an option:"
    else:
        prompt_text = "Reply with your answer below."
    return build_numbered_selection_menu(
        header,
        selection_options,
        prompt=prompt_text,
        page=page,
        page_callback_builder=lambda next_page: f"input_page:{interaction_id}:{next_page}",
        action_rows=action_rows,
    )


def get_exit_plan_mode_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Inline keyboard for exit_plan_mode.requested approval UI."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"plan:approve:{request_id}"),
        InlineKeyboardButton("📝 Edit", callback_data=f"plan:edit:{request_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"plan:reject:{request_id}"),
    ]])
