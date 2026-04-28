import logging
import os
import time
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.config import WORKSPACE_PATH
from src.core.service import service
from src.core.context import ctx
from src.handlers.messages import chat_handler
from src.handlers.utils import security_check, check_project_selected
from src.ui.formatters import format_tokens, format_percentage, get_model_context_limit

logger = logging.getLogger(__name__)


def _get_sdk_version() -> str:
    """Get copilot SDK package version."""
    try:
        from importlib.metadata import version
        return version("github-copilot-sdk")
    except Exception:
        return "unknown"


async def _get_system_info() -> tuple[str, str, str]:
    """Get CLI version, auth status, and SDK version with error handling."""
    sdk_version = _get_sdk_version()
    
    # Get CLI version (works without service running via shell fallback)
    cli_version = "Unknown"
    try:
        cli_version = await service.get_cli_version()
    except Exception as e:
        logger.warning(f"Failed to get CLI version: {e}")
    
    # Get auth status only if service is already running (avoids premature startup)
    auth = "User"
    try:
        if service._is_running:
            auth = await service.get_auth_status()
        else:
            # Don't start service just for auth check at startup
            logger.debug("Service not running yet, skipping auth check")
    except Exception as e:
        logger.warning(f"Failed to get auth status: {e}")
    
    return cli_version, auth, sdk_version


# --- Handlers ---

async def build_main_menu() -> tuple:
    """Build main menu message and keyboard. Shared by start_command and post_init.
    
    Returns (message_text, keyboard, (cli_version, auth, sdk_version)).
    """
    from src.ui.menus import get_start_splash_content, get_project_keyboard
    cli_version, auth, sdk_version = await _get_system_info()
    msg = get_start_splash_content(auth, cli_version, sdk_version)
    keyboard = get_project_keyboard(WORKSPACE_PATH)
    return msg, keyboard, (cli_version, auth, sdk_version)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("/start command received")
    if not await security_check(update): return
    msg, keyboard, sys_info = await build_main_menu()
    # Store version info for reuse when editing start message after project selection
    context.user_data['cli_version'] = sys_info[0]
    context.user_data['auth'] = sys_info[1]
    context.user_data['sdk_version'] = sys_info[2]
    await update.message.reply_text(msg, reply_markup=keyboard)
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    from src.ui.menus import get_help_content
    
    cli_version, auth, _ = await _get_system_info()
    
    msg = get_help_content(auth, cli_version, service.current_model, service.get_working_directory(), service.project_selected)
    await update.message.reply_text(msg)

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    report = await service.get_usage_report()
    await update.message.reply_text(report)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    await service.set_mode("interactive")
    await service.deselect_agent()
    await service.reset_session()
    await update.message.reply_text("🧹 Session Cleared\nMemory reset.")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the currently processing request using SDK session.abort()."""
    if not await security_check(update): return
    if not service.session:
        await update.message.reply_text("⚠️ No active session.")
        return
    if not service._chat_lock.locked():
        await update.message.reply_text("ℹ️ No request in progress.")
        return
    try:
        service._cancelled = True
        await service.session.abort()
        await update.message.reply_text("🛑 Request cancelled.")
    except Exception as e:
        logger.error(f"Cancel failed: {e}")
        await update.message.reply_text(f"⚠️ Cancel failed: {e}")

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    if not await service.set_mode("interactive"):
        await update.message.reply_text("⏳ Please wait — a request is in progress.")
        return
    logger.info("Switched to Edit Mode")
    await update.message.reply_text("💬 Switched to Edit (Chat) Mode")

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    args = context.args
    if args:
        # /plan <prompt> — force plan mode and send prompt
        if not await service.set_mode("plan"):
            await update.message.reply_text("⏳ Please wait — a request is in progress.")
            return
        prompt = " ".join(args)
        await update.message.reply_text("📝 Plan Mode ON")
        await chat_handler(update, context, override_text=prompt)
    else:
        # /plan — toggle plan mode
        is_plan = service.current_mode == "plan"
        target = "interactive" if is_plan else "plan"
        if not await service.set_mode(target):
            await update.message.reply_text("⏳ Please wait — a request is in progress.")
            return
        if target == "plan":
            await update.message.reply_text("📝 Switch to Plan Mode")
        else:
            await update.message.reply_text("💬 Switch to Edit (Chat) Mode")

async def autopilot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    args = context.args
    if args:
        # /autopilot <prompt> — force autopilot mode and send prompt
        if not await service.set_mode("autopilot"):
            await update.message.reply_text("⏳ Please wait — a request is in progress.")
            return
        prompt = " ".join(args)
        await update.message.reply_text("🚀 Autopilot Mode ON")
        await chat_handler(update, context, override_text=prompt)
    else:
        # /autopilot — toggle autopilot mode
        is_autopilot = service.current_mode == "autopilot"
        target = "interactive" if is_autopilot else "autopilot"
        if not await service.set_mode(target):
            await update.message.reply_text("⏳ Please wait — a request is in progress.")
            return
        if target == "autopilot":
            await update.message.reply_text("🚀 Switch to Autopilot Mode")
        else:
            await update.message.reply_text("💬 Switch to Edit (Chat) Mode")

async def agent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View and select custom agents.

    /agent          — show agent list with inline keyboard
    /agent <name>   — select agent by name
    /agent reload   — reload agent definitions from disk
    """
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from src.ui.menus import get_agent_keyboard

    args = context.args
    if args:
        subcommand = args[0].lower()
        if subcommand == "reload":
            agents = await service.reload_agents()
            if agents:
                names = ", ".join(
                    (a.display_name if hasattr(a, "display_name") else a.get("display_name", ""))
                    or (a.name if hasattr(a, "name") else a.get("name", "?"))
                    for a in agents
                )
                await update.message.reply_text(f"🔄 Agents reloaded ({len(agents)}):\n{names}")
            else:
                await update.message.reply_text("🔄 Agents reloaded. No custom agents found.")
            return

        # /agent <name> — select directly
        name = " ".join(args)
        if await service.select_agent(name):
            await update.message.reply_text(f"🤖 Agent selected: {name}")
        else:
            await update.message.reply_text(f"⚠️ Failed to select agent: {name}")
        return

    # /agent (no args) — show keyboard
    agents = await service.list_agents()
    current = await service.get_current_agent()
    if not agents:
        await update.message.reply_text(
            "🤖 No custom agents found.\n\n"
            "Define agents in:\n"
            "• .github/agents/<name>.agent.md (project)\n"
            "• ~/.copilot/agents/<name>.agent.md (user)\n\n"
            "Then run /agent reload"
        )
        return
    keyboard = get_agent_keyboard(agents, current)
    await update.message.reply_text("🤖 Select an agent:", reply_markup=keyboard)

async def cwd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    cwd = service.get_working_directory()
    await update.message.reply_text(f"📂 Current working directory:\n{cwd}")

async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from src.config import TELEGRAM_MSG_LIMIT
    tree = service.get_project_structure()
    text = tree
    if len(text) > TELEGRAM_MSG_LIMIT:
        avail = TELEGRAM_MSG_LIMIT - len("\n... truncated")
        text = tree[:avail] + "\n... truncated"
    await update.message.reply_text(text)

async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    # Get current model context usage info
    if service.last_assistant_usage:
        usage = service.last_assistant_usage
        model_name = getattr(usage, 'model', service.current_model or 'Auto')
        
        # Get token information
        input_tokens = 0
        output_tokens = 0
        cache_tokens = 0
        
        # Try to get token info from last_assistant_usage or last_session_usage
        if hasattr(usage, 'input_tokens'):
            input_tokens = int(usage.input_tokens or 0)
        if hasattr(usage, 'output_tokens'):
            output_tokens = int(usage.output_tokens or 0)
        if hasattr(usage, 'cache_read_tokens'):
            cache_tokens = int(usage.cache_read_tokens or 0)
        
        # Calculate totals and percentages (estimates — actual limits vary by model)
        total_used = input_tokens + output_tokens
        context_limit = get_model_context_limit(model_name)
        
        # Build message similar to the example
        total_pct = format_percentage(total_used, context_limit)
        system_pct = format_percentage(input_tokens, context_limit)
        messages_pct = format_percentage(output_tokens, context_limit)
        free_space = context_limit - total_used
        free_pct = format_percentage(free_space, context_limit)
        
        msg = (
            f"{model_name} · {format_tokens(total_used)}/{format_tokens(context_limit)} tokens ({total_pct})\n"
            f"Context (In):  {format_tokens(input_tokens)} ({system_pct})\n"
            f"Response (Out): {format_tokens(output_tokens)} ({messages_pct})\n"
            f"Free Space:    {format_tokens(free_space)} ({free_pct})\n"
        )
        
        if cache_tokens > 0:
            cache_pct = format_percentage(cache_tokens, context_limit)
            msg += f"Cached:        {format_tokens(cache_tokens)} ({cache_pct})\n"
        
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(
            "📊 No usage data available yet. Send a message first."
        )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from src.ui.menus import get_model_keyboard
    msg = await update.message.reply_text("🔄 Fetching models...")
    keyboard = get_model_keyboard(await service.get_available_models())
    await msg.edit_text(f"Select a model:", reply_markup=keyboard)

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skills command with subcommands: list (default), info <name>, reload."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from src.ui.menus import format_skill_list, get_skill_source_display

    args = context.args or []
    subcommand = args[0].lower() if args else "list"

    if subcommand == "list":
        msg = await update.message.reply_text("🔄 Fetching skills...")
        skills = await service.list_skills()
        text = format_skill_list(skills)
        await msg.edit_text(text)

    elif subcommand == "info":
        if len(args) < 2:
            await update.message.reply_text("Usage: /skills info <name>")
            return
        skill_name = args[1]
        msg = await update.message.reply_text(f"🔄 Fetching skill info...")
        skills = await service.list_skills()
        skill = next((s for s in skills if s["name"] == skill_name), None)
        if not skill:
            await msg.edit_text(f"⚠️ Skill '{skill_name}' not found.")
            return
        # Read SKILL.md content if path is available
        content = ""
        if skill.get("path"):
            try:
                content = Path(skill["path"]).read_text(encoding="utf-8").strip()
            except Exception:
                content = ""

        source = skill.get("source", "unknown")
        source_label, icon = get_skill_source_display(source)
        enabled = "✅ Enabled" if skill.get("enabled") else "❌ Disabled"

        lines = [
            f"🧩 {skill['name']}",
            f"━━━━━━━━━━━━━━━",
            f"{icon} Source: {source_label}",
            enabled,
        ]
        if skill.get("description"):
            lines.append(f"\n{skill['description']}")
        if content:
            import re
            content_body = re.sub(r'^---\n.*?\n---\n*', '', content, flags=re.DOTALL).strip()
            if content_body:
                lines.append(f"\n━━━━━━━━━━━━━━━")
                lines.append(content_body)

        result = "\n".join(lines)
        from src.config import TELEGRAM_MSG_LIMIT
        if len(result) > TELEGRAM_MSG_LIMIT:
            result = result[:TELEGRAM_MSG_LIMIT - 20] + "\n... truncated"
        await msg.edit_text(result)

    elif subcommand == "reload":
        msg = await update.message.reply_text("🔄 Reloading skills...")
        success = await service.reload_skills()
        if success:
            skills = await service.list_skills()
            text = format_skill_list(skills)
            await msg.edit_text(f"✅ Skills reloaded.\n\n{text}")
        else:
            await msg.edit_text("⚠️ Failed to reload skills.")

    else:
        await update.message.reply_text(
            "Unknown subcommand.\n"
            "Usage: /skills [list|info <name>|reload]"
        )

async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    msg = await update.message.reply_text("📤 Exporting session...")
    try:
        file_path = await service.export_session_to_file()
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                await update.message.reply_document(document=f, filename=os.path.basename(file_path))
            os.remove(file_path)
            await msg.delete()
        else:
            await msg.edit_text("⚠️ Failed to export session or empty.")
    except Exception as e:
        logger.error(f"Share failed: {e}")
        await msg.edit_text(f"⚠️ Error sharing session: {e}")

async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Session management: /session [info|files|plan]."""
    if not await security_check(update): return
    if not await check_project_selected(update): return

    subcommand = (context.args[0].lower() if context.args else "info")

    if subcommand == "info":
        await _session_info(update)
    elif subcommand == "files":
        await _session_files(update)
    elif subcommand == "plan":
        await _session_plan(update)
    else:
        await update.message.reply_text(
            "📋 /session subcommands:\n"
            "• /session info — Session info & workspace summary\n"
            "• /session files — List session workspace files\n"
            "• /session plan — Show session plan"
        )


async def _session_info(update: Update):
    """Show session info and workspace summary."""
    await service.populate_session_metadata()

    session_info = service.get_session_info()
    tracker = service.usage_tracker

    uptime_str = session_info.duration()

    model = service.user_selected_model or service.current_model or "Auto"
    mode_labels = {"interactive": "Chat", "plan": "Planning", "autopilot": "Autopilot"}
    mode = mode_labels.get(service.current_mode, "Chat")
    status = "Expired" if service.session_expired else "Active"

    session_id_full = session_info.session_id or service.session_id
    created_str = session_info.created or "N/A"

    cwd = session_info.cwd or str(ctx.root_path)
    branch = session_info.branch or "N/A"

    total_requests = sum(u.requests for u in tracker.model_usage.values())

    agent_line = f"• Agent: {service.current_agent}\n" if service.current_agent else ""

    msg = (
        f"📋 Session Info\n"
        f"• Session ID: {session_id_full}\n"
        f"• Status: {status}\n"
        f"• Duration: {uptime_str}\n"
        f"• Created: {created_str}\n"
        f"• Model: {model}\n"
        f"• Mode: {mode}\n"
        f"{agent_line}"
        f"• Total Requests: {total_requests}\n"
        f"\n📂 Workspace\n"
        f"• Project: {service.project_name or Path(cwd).name}\n"
        f"• Path: {cwd}\n"
        f"• Branch: {branch}\n"
    )

    if session_info.git_root:
        msg += f"• Git Root: {session_info.git_root}\n"
    if session_info.repository:
        msg += f"• Repository: {session_info.repository}\n"

    if tracker.current_tokens or tracker.token_limit:
        pct = (tracker.current_tokens / tracker.token_limit * 100) if tracker.token_limit else 0
        msg += f"• Context: {tracker.current_tokens}/{tracker.token_limit} ({pct:.0f}%)\n"

    quota_summary = tracker.get_quota_summary()
    if quota_summary:
        msg += f"\n💳 Quota Status:\n{quota_summary}\n"

    usage_summary = await tracker.get_usage_summary()
    msg += f"\n📊 Usage Summary:\n{usage_summary}\n"

    await update.message.reply_text(msg)


async def _session_files(update: Update):
    """List files in the session workspace directory."""
    workspace_raw = getattr(service.session, "workspace_path", None) if service.session else None

    if not workspace_raw:
        await update.message.reply_text(
            "📂 Session workspace not available.\n"
            "Workspace files are only available when infinite sessions are enabled."
        )
        return

    workspace_path = Path(workspace_raw) if not isinstance(workspace_raw, Path) else workspace_raw
    files_dir = workspace_path / "files"
    if not files_dir.exists() or not any(files_dir.iterdir()):
        await update.message.reply_text("📂 Session workspace files: (empty)")
        return

    from src.config import TELEGRAM_MSG_LIMIT

    lines = []
    for entry in sorted(files_dir.iterdir()):
        if entry.is_file():
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            lines.append(f"  📄 {entry.name}  ({size_str})")
        elif entry.is_dir():
            lines.append(f"  📁 {entry.name}/")

    header = "📂 Session workspace files:\n"
    body = "\n".join(lines)
    text = header + body
    if len(text) > TELEGRAM_MSG_LIMIT:
        avail = TELEGRAM_MSG_LIMIT - len("\n... truncated")
        text = text[:avail] + "\n... truncated"
    await update.message.reply_text(text)


async def _session_plan(update: Update):
    """Show the session plan (plan.md from workspace)."""
    from src.config import TELEGRAM_MSG_LIMIT

    workspace_raw = getattr(service.session, "workspace_path", None) if service.session else None

    if not workspace_raw:
        await update.message.reply_text(
            "📋 Session plan not available.\n"
            "Session plans are only available when infinite sessions are enabled."
        )
        return

    workspace_path = Path(workspace_raw) if not isinstance(workspace_raw, Path) else workspace_raw
    plan_file = workspace_path / "plan.md"
    if not plan_file.is_file():
        await update.message.reply_text("📋 No plan found for this session.")
        return

    try:
        content = plan_file.read_text(encoding="utf-8", errors="replace").strip()
    except (PermissionError, OSError) as e:
        await update.message.reply_text(f"📋 Error reading plan: {e}")
        return

    if not content:
        await update.message.reply_text("📋 Session plan is empty.")
        return

    if len(content) <= TELEGRAM_MSG_LIMIT - 50:
        await update.message.reply_text(f"📋 Session Plan:\n\n{content}")
    else:
        import io
        doc = io.BytesIO(content.encode("utf-8"))
        doc.name = "plan.md"
        await update.message.reply_document(document=doc, caption="📋 Session Plan (full)")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Health check — works without project selection."""
    if not await security_check(update): return

    client_ok = service._is_running
    session_ok = service.session is not None and not service.session_expired

    lines = [
        "🏓 Pong!",
        f"• Client: {'🟢 Running' if client_ok else '🔴 Not running'}",
        f"• Session: {'🟢 Active' if session_ok else '🔴 None'}",
    ]

    # RPC health check (only if session exists)
    if session_ok:
        try:
            t0 = time.monotonic()
            await service.session.rpc.model.get_current()
            latency_ms = int((time.monotonic() - t0) * 1000)
            lines.append(f"• RPC: 🟢 OK ({latency_ms}ms)")
        except Exception as e:
            lines.append(f"• RPC: 🔴 Error ({e})")

    await update.message.reply_text("\n".join(lines))

async def allowall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle auto-approve for all tool permissions."""
    if not await security_check(update): return
    if not await check_project_selected(update): return

    service.allow_all_tools = not service.allow_all_tools

    if service.allow_all_tools:
        await update.message.reply_text(
            "🔓 Allow All: ON\n"
            "All tool permissions auto-approved for this session."
        )
    else:
        await update.message.reply_text(
            "🔒 Allow All: OFF\n"
            "Non-allowlisted tools will require approval."
        )

async def instructions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show custom instructions status with inline action buttons."""
    if not await security_check(update): return
    if not await check_project_selected(update): return

    instructions_path = Path(service.get_working_directory()) / ".github" / "copilot-instructions.md"
    content = ""
    try:
        if instructions_path.exists():
            content = instructions_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.error(f"Failed to read instructions file: {e}")
        await update.message.reply_text(f"⚠️ Failed to read custom instructions: {e}")
        return

    has_instructions = bool(content)

    from src.ui.menus import get_instructions_keyboard
    if has_instructions:
        try:
            size = instructions_path.stat().st_size
        except OSError as e:
            logger.error(f"Failed to stat instructions file: {e}")
            await update.message.reply_text(f"⚠️ Failed to inspect custom instructions: {e}")
            return
        text = (
            f"📋 Custom Instructions\n"
            f"Status: ✅ Active\n"
            f"File: .github/copilot-instructions.md ({size} bytes)"
        )
    else:
        text = "📋 No custom instructions found."

    keyboard = get_instructions_keyboard(has_instructions=bool(has_instructions))
    await update.message.reply_text(text, reply_markup=keyboard)

async def init_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate .github/copilot-instructions.md by analyzing the project."""
    if not await security_check(update): return
    if not await check_project_selected(update): return

    instructions_path = Path(service.get_working_directory()) / ".github" / "copilot-instructions.md"
    if instructions_path.exists():
        content = instructions_path.read_text(encoding="utf-8").strip()
        if content:
            await update.message.reply_text(
                "📋 Custom instructions already exist.\n"
                "Use /instructions to view or clear them first."
            )
            return

    await update.message.reply_text("🔍 Analyzing project to generate custom instructions...")
    prompt = (
        "Analyze this project's structure, tech stack, conventions, and patterns. "
        "Then create a .github/copilot-instructions.md file with concise, actionable instructions "
        "that will help Copilot understand this project. Include: language/framework, "
        "coding conventions, build/test commands, project structure overview, "
        "and any important patterns. Keep it focused and under 50 lines."
    )
    await chat_handler(update, context, override_text=prompt)
