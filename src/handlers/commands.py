import logging
import os
from pathlib import Path
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from src.config import WORKSPACE_PATH
from src.core.service import service
from src.handlers.messages import chat_handler
from src.handlers.utils import security_check, check_project_selected

logger = logging.getLogger(__name__)

# Model context window sizes (estimated tokens)
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude": 200_000,
    "gpt-4": 128_000,
    "o1": 200_000,
    "o3": 200_000,
}
_DEFAULT_CONTEXT_LIMIT = 128_000


def _get_model_context_limit(model_name: str) -> int:
    """Lookup estimated context window size for a model."""
    name = model_name.lower()
    for key, limit in _MODEL_CONTEXT_LIMITS.items():
        if key in name:
            return limit
    return _DEFAULT_CONTEXT_LIMIT


# --- Handlers ---

async def _build_main_menu() -> tuple:
    """Build main menu message and keyboard. Shared by start_command and post_init."""
    from src.ui.menus import get_main_menu_content, get_project_keyboard
    try:
        version = await service.get_cli_version()
        auth = await service.get_auth_status()
    except Exception:
        version = "Unknown"
        auth = "Error"
    msg = get_main_menu_content(auth, version, service.current_model, service.get_working_directory(), service.project_selected)
    keyboard = get_project_keyboard(WORKSPACE_PATH)
    return msg, keyboard


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("/start command received")
    if not await security_check(update): return
    msg, keyboard = await _build_main_menu()
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    from src.ui.menus import get_main_menu_content
    
    try:
        version = await service.get_cli_version()
        auth = await service.get_auth_status()
    except Exception:
        version = "Unknown"
        auth = "Error"
    
    msg = get_main_menu_content(auth, version, service.current_model, service.get_working_directory(), service.project_selected)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    report = service.get_usage_report()
    await update.message.reply_text(report)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    await service.reset_session()
    await update.message.reply_text("🧹 **Session Cleared**\nMemory reset.", parse_mode=ParseMode.MARKDOWN)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the currently processing request using SDK session.abort()."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    if not service.session:
        await update.message.reply_text("⚠️ No active session.")
        return
    try:
        await service.session.abort()
        await update.message.reply_text("🛑 **Request cancelled.**", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Cancel failed: {e}")
        await update.message.reply_text(f"⚠️ Cancel failed: {e}")

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    context.user_data['plan_mode'] = False
    logger.info("Switched to Edit Mode")
    await update.message.reply_text("💬 **Switched to Edit (Chat) Mode**", parse_mode=ParseMode.MARKDOWN)

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    args = context.args
    if args:
        # /plan <prompt> — force plan mode and send prompt
        context.user_data['plan_mode'] = True
        prompt = " ".join(args)
        await update.message.reply_text("📝 **Plan Mode ON**", parse_mode=ParseMode.MARKDOWN)
        await chat_handler(update, context, override_text=prompt)
    else:
        # /plan — toggle plan mode
        mode = not context.user_data.get('plan_mode', False)
        context.user_data['plan_mode'] = mode
        if mode:
            await update.message.reply_text("📝 **Switch to Plan Mode**", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("💬 **Switch to Edit (Chat) Mode**", parse_mode=ParseMode.MARKDOWN)

async def cwd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    cwd = service.get_working_directory()
    await update.message.reply_text(f"📂 Current working directory:\n{cwd}")

async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    ls_text = service.get_directory_listing()
    await update.message.reply_text(ls_text)

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
        context_limit = _get_model_context_limit(model_name)
        
        def format_tokens(n):
            if n >= 1000:
                return f"{n/1000:.1f}k"
            return str(n)
        
        def format_percentage(used, limit):
            if limit == 0:
                return "0%"
            pct = (used / limit) * 100
            return f"{pct:.0f}%"
        
        # Build message similar to the example
        total_pct = format_percentage(total_used, context_limit)
        system_pct = format_percentage(input_tokens, context_limit)
        messages_pct = format_percentage(output_tokens, context_limit)
        free_space = context_limit - total_used
        free_pct = format_percentage(free_space, context_limit)
        
        msg = (
            f"**{model_name}** · {format_tokens(total_used)}/{format_tokens(context_limit)} tokens ({total_pct})\n"
            f"System/Tools:  {format_tokens(input_tokens)} ({system_pct})\n"
            f"Messages:      {format_tokens(output_tokens)} ({messages_pct})\n"
            f"Free Space:    {format_tokens(free_space)} ({free_pct})\n"
        )
        
        if cache_tokens > 0:
            cache_pct = format_percentage(cache_tokens, context_limit)
            msg += f"Cached:        {format_tokens(cache_tokens)} ({cache_pct})\n"
        
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            "📊 No usage data available yet. Send a message first.",
            parse_mode=ParseMode.MARKDOWN
        )

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    await update.message.reply_text("🛠 **Enabled Tools**\n✅ `list_files`\n✅ `read_file`\n❌ `run_shell`", parse_mode=ParseMode.MARKDOWN)

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    from src.config import GRANTED_PROJECT_PATHS
    status = "Active" if service.project_selected else "No Project Selected"
    current_dir = service.get_working_directory()
    
    # Determine project source
    current_path = Path(current_dir)
    project_source = "Workspace"
    for gp in GRANTED_PROJECT_PATHS:
        if current_path == gp:
            project_source = "Granted Project"
            break
    
    msg = (
        f"📊 **Session Info**\n"
        f"• Status: `{status}`\n"
        f"• Model: `{service.current_model}`\n"
        f"• Mode: `{'Planning' if context.user_data.get('plan_mode') else 'Chat'}`\n"
        f"• Current Project: `{current_path.name}` ({project_source})\n"
        f"• Directory: `{current_dir}`\n"
        f"• Workspace Root: `{WORKSPACE_PATH}`\n"
        f"• Granted Projects: `{len(GRANTED_PROJECT_PATHS)}`"
    )
    
    if GRANTED_PROJECT_PATHS:
        msg += "\n\n**Granted Projects:**\n"
        for gp in GRANTED_PROJECT_PATHS:
            exists = "✓" if gp.exists() else "✗"
            msg += f"  {exists} `{gp}`\n"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

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
