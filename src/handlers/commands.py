import logging
import os
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
    context.user_data['plan_mode'] = False
    await service.set_mode("general")
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
    if not await service.set_mode("general"):
        await update.message.reply_text("⏳ Please wait — a request is in progress.")
        return
    context.user_data['plan_mode'] = False
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
        context.user_data['plan_mode'] = True
        prompt = " ".join(args)
        await update.message.reply_text("📝 Plan Mode ON")
        await chat_handler(update, context, override_text=prompt)
    else:
        # /plan — toggle plan mode
        target = not context.user_data.get('plan_mode', False)
        if not await service.set_mode("plan" if target else "general"):
            await update.message.reply_text("⏳ Please wait — a request is in progress.")
            return
        context.user_data['plan_mode'] = target
        if target:
            await update.message.reply_text("📝 Switch to Plan Mode")
        else:
            await update.message.reply_text("💬 Switch to Edit (Chat) Mode")

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
    mode = "Planning" if service.current_mode == "plan" else "Chat"
    status = "Expired" if service.session_expired else "Active"

    session_id_full = session_info.session_id or service.session_id
    created_str = session_info.created or "N/A"

    cwd = session_info.cwd or str(ctx.root_path)
    branch = session_info.branch or "N/A"

    total_requests = sum(u.requests for u in tracker.model_usage.values())

    msg = (
        f"📋 Session Info\n"
        f"• Session ID: {session_id_full}\n"
        f"• Status: {status}\n"
        f"• Duration: {uptime_str}\n"
        f"• Created: {created_str}\n"
        f"• Model: {model}\n"
        f"• Mode: {mode}\n"
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
