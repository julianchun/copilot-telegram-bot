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
    try:
        cli_version = await service.get_cli_version()
        auth = await service.get_auth_status()
        return cli_version, auth, sdk_version
    except Exception:
        return "Unknown", "Error", sdk_version


# --- Handlers ---

async def build_main_menu() -> tuple:
    """Build main menu message and keyboard. Shared by start_command and post_init."""
    from src.ui.menus import get_start_splash_content, get_project_keyboard
    cli_version, auth, sdk_version = await _get_system_info()
    msg = get_start_splash_content(auth, cli_version, sdk_version)
    keyboard = get_project_keyboard(WORKSPACE_PATH)
    return msg, keyboard


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("/start command received")
    if not await security_check(update): return
    msg, keyboard = await build_main_menu()
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
    report = service.get_usage_report()
    await update.message.reply_text(report)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    await service.reset_session()
    await update.message.reply_text("🧹 Session Cleared\nMemory reset.")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the currently processing request using SDK session.abort()."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    if not service.session:
        await update.message.reply_text("⚠️ No active session.")
        return
    try:
        await service.session.abort()
        await update.message.reply_text("🛑 Request cancelled.")
    except Exception as e:
        logger.error(f"Cancel failed: {e}")
        await update.message.reply_text(f"⚠️ Cancel failed: {e}")

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    context.user_data['plan_mode'] = False
    logger.info("Switched to Edit Mode")
    await update.message.reply_text("💬 Switched to Edit (Chat) Mode")

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    args = context.args
    if args:
        # /plan <prompt> — force plan mode and send prompt
        context.user_data['plan_mode'] = True
        prompt = " ".join(args)
        await update.message.reply_text("📝 Plan Mode ON")
        await chat_handler(update, context, override_text=prompt)
    else:
        # /plan — toggle plan mode
        mode = not context.user_data.get('plan_mode', False)
        context.user_data['plan_mode'] = mode
        if mode:
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
    header = f"📂 {service.project_name or 'Project'} Structure\n\n"
    text = header + tree
    if len(text) > TELEGRAM_MSG_LIMIT:
        avail = TELEGRAM_MSG_LIMIT - len(header) - len("\n... truncated")
        text = header + tree[:avail] + "\n... truncated"
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
            f"System/Tools:  {format_tokens(input_tokens)} ({system_pct})\n"
            f"Messages:      {format_tokens(output_tokens)} ({messages_pct})\n"
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

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    await update.message.reply_text("🛠 Enabled Tools\n✅ list_files\n✅ read_file\n❌ run_shell")

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
    """Show session info and workspace summary."""
    if not await security_check(update): return
    if not await check_project_selected(update): return

    # Fetch latest session metadata (name, created, modified) from list_sessions()
    await service.populate_session_metadata()
    
    session_info = service.get_session_info()
    tracker = service.usage_tracker

    # Session uptime from session_info
    uptime_str = session_info.duration()

    model = service.user_selected_model or service.current_model or "Auto"
    mode = "Planning" if context.user_data.get('plan_mode') else "Chat"
    status = "Expired" if service.session_expired else "Active"
    
    # Full session ID from session_info
    session_id_full = session_info.session_id or service.session_id
    
    # Use created time from session_info (ISO format string from SDK)
    created_str = session_info.created or "N/A"
    
    # Use session_info fields
    cwd = session_info.cwd or str(ctx.root_path)
    branch = session_info.branch or "N/A"

    # Message count from tracker
    total_cost = sum(u.cost for u in tracker.model_usage.values())

    msg = (
        f"📋 Session Info\n"
        f"• Session ID: {session_id_full}\n"
        f"• Status: {status}\n"
        f"• Duration: {uptime_str}\n"
        f"• Created: {created_str}\n"
        f"• Model: {model}\n"
        f"• Mode: {mode}\n"
        f"• Total Request cost: {total_cost}\n\n"
        f"📂 Workspace\n"
        f"• Project: {service.project_name or Path(cwd).name}\n"
        f"• Path: {cwd}\n"
        f"• Branch: {branch}\n"
    )
    
    # Git root and repository if available
    if session_info.git_root:
        msg += f"• Git Root: {session_info.git_root}\n"
    if session_info.repository:
        msg += f"• Repository: {session_info.repository}\n"

    # Token context
    if tracker.current_tokens or tracker.token_limit:
        pct = (tracker.current_tokens / tracker.token_limit * 100) if tracker.token_limit else 0
        msg += f"• Context: {tracker.current_tokens}/{tracker.token_limit} ({pct:.0f}%)\n"

    # Quota status
    quota_summary = tracker.get_quota_summary()
    if quota_summary:
        msg += f"\n💳 Quota Status:\n{quota_summary}\n\n"

    # Usage summary
    usage_summary = tracker.get_usage_summary()
    msg += f"\n📊 Usage Summary:\n{usage_summary}\n"

    await update.message.reply_text(msg)
