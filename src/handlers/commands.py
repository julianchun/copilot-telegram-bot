import asyncio
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

async def _send_paged(message, text: str, header: str = "", max_msgs: int = 5):
    """Send text across multiple messages, capped at max_msgs, in preformatted blocks."""
    from src.config import TELEGRAM_MSG_LIMIT
    import html as html_lib
    chunk_size = TELEGRAM_MSG_LIMIT - 50  # leave room for <pre> tags and header
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    if len(chunks) > max_msgs:
        keep = chunk_size * max_msgs
        text = text[:keep]
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        chunks[-1] += f"\n... truncated (showing {max_msgs}/{len(chunks)} pages)"
    total = len(chunks)
    for idx, chunk in enumerate(chunks):
        prefix = header if idx == 0 else f"(cont. {idx + 1}/{total})\n"
        safe = html_lib.escape(chunk)
        await message.reply_text(f"{prefix}<pre>{safe}</pre>", parse_mode="HTML")


async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Top-level only\n(no subfolders)", callback_data="ls:0:1")],
        [InlineKeyboardButton("🌿 Shallow\n(1 level deep)", callback_data="ls:1:1")],
        [InlineKeyboardButton("🌳 Full tree\n(2 levels deep)", callback_data="ls:2")],
    ])
    await update.message.reply_text("Choose file tree view:", reply_markup=keyboard)

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
    usage_summary = await tracker.get_usage_summary()
    msg += f"\n📊 Usage Summary:\n{usage_summary}\n"

    await update.message.reply_text(msg)


# ── New commands ──────────────────────────────────────────────────────────


async def diff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show git diff for the current project (paged, non-interactive)."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cwd = service.get_working_directory()
    msg = await update.message.reply_text("🔍 Running git diff...")
    try:
        proc = await asyncio.create_subprocess_shell(
            "git diff HEAD",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        diff = stdout.decode().strip() or stderr.decode().strip()
        if not diff:
            await msg.edit_text("ℹ️ No uncommitted changes.")
            return
        # Chunk at line boundaries; HTML tags expand each line by ~10 chars, so keep raw budget at 2500
        chunks, current, current_len = [], [], 0
        for line in diff.splitlines():
            if current_len + len(line) + 1 > 2500 and current:
                chunks.append('\n'.join(current))
                current, current_len = [line], len(line)
            else:
                current.append(line)
                current_len += len(line) + 1
        if current:
            chunks.append('\n'.join(current))
        total = len(chunks)
        # Offer paging choice
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📄 1 page", callback_data="diff:1")],
            [InlineKeyboardButton(f"📄 3 pages", callback_data="diff:3")],
            [InlineKeyboardButton(f"📄 Full ({total} page{'s' if total != 1 else ''})", callback_data=f"diff:{total}")],
        ])
        context.user_data["_diff_chunks"] = chunks
        await msg.edit_text(
            f"📋 Diff has {total} page(s). How much to show?",
            reply_markup=keyboard,
        )
    except asyncio.TimeoutError:
        await msg.edit_text("⚠️ Git diff timed out.")
    except Exception as e:
        logger.error(f"diff_command failed: {e}")
        await msg.edit_text(f"⚠️ Error: {e}")


async def instructions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View the Copilot instructions file for the current project."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from src.config import TELEGRAM_MSG_LIMIT
    cwd = service.get_working_directory()
    instructions_path = Path(cwd) / ".github" / "copilot-instructions.md"
    if instructions_path.exists():
        content = instructions_path.read_text()
        if len(content) > TELEGRAM_MSG_LIMIT - 50:
            content = content[:TELEGRAM_MSG_LIMIT - 50] + "\n... truncated"
        await update.message.reply_text(f"📋 Copilot Instructions:\n\n{content}")
    else:
        await update.message.reply_text(
            f"⚠️ No instructions file found.\nExpected: {instructions_path}\n\n"
            "Run `copilot init` in the terminal to create one."
        )


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update the Copilot CLI to the latest version."""
    if not await security_check(update): return
    import shutil
    # Try shutil.which first, then fall back to known install locations
    cli = (
        shutil.which("copilot")
        or getattr(service.client, 'options', {}).get('cli_path')
        or os.path.expanduser("~/.local/bin/copilot")
        or "/usr/local/bin/copilot"
    )
    if not cli or not Path(cli).exists():
        await update.message.reply_text("⚠️ Copilot CLI not found.")
        return
    msg = await update.message.reply_text("🔄 Updating Copilot CLI...")
    try:
        proc = await asyncio.create_subprocess_exec(
            cli, "update",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = (stdout + stderr).decode().strip() or "Update complete."
        await msg.edit_text(f"✅ {output}"[:4000])
    except asyncio.TimeoutError:
        await msg.edit_text("⚠️ Update timed out (60s).")
    except Exception as e:
        logger.error(f"update_command failed: {e}")
        await msg.edit_text(f"⚠️ Update failed: {e}")


async def allow_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle allow-all-tools mode (skip per-request permission prompts)."""
    if not await security_check(update): return
    service.allow_all_tools = not service.allow_all_tools
    if service.allow_all_tools:
        await update.message.reply_text(
            "✅ Allow All Tools: ENABLED\n"
            "All tool permissions are auto-approved. Use /allowall again to restore prompts."
        )
    else:
        await update.message.reply_text(
            "🔒 Allow All Tools: DISABLED\n"
            "Per-request permission prompts restored."
        )


async def effort_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set reasoning effort level for models that support it."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    model_id = service.user_selected_model or service.current_model
    if not model_id:
        await update.message.reply_text("⚠️ No model selected. Use /model first.")
        return
    # Populate cache if empty (e.g. first use before /model was called)
    if not service._models_cache:
        await service.get_available_models()
    model_info = next((m for m in service._models_cache if m["id"] == model_id), None)
    if not model_info or not model_info.get("supports_reasoning"):
        await update.message.reply_text(
            f"⚠️ Model '{model_id}' does not support reasoning effort.\n"
            "Switch to a reasoning-capable model with /model."
        )
        return
    from src.ui.menus import get_reasoning_keyboard
    current = service.current_reasoning_effort or model_info.get("default_effort") or "default"
    keyboard = get_reasoning_keyboard(model_id, model_info["supported_efforts"], model_info.get("default_effort"))
    await update.message.reply_text(
        f"🧠 Reasoning Effort — {model_id}\nCurrent: {current}\n\nSelect effort level:",
        reply_markup=keyboard,
    )


async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse and resume past Copilot sessions."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    from src.ui.menus import get_sessions_keyboard
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    msg = await update.message.reply_text("🔄 Fetching sessions...")
    try:
        if not service._is_running:
            await service.start()
        sessions = await service.client.list_sessions()
        if not sessions:
            await msg.edit_text("📋 No past sessions found.")
            return
        cwd = service.get_working_directory()
        project_name = service.project_name or Path(cwd).name
        header, keyboard = get_sessions_keyboard(sessions, cwd_filter=cwd)
        buttons = list(keyboard.inline_keyboard)
        buttons.append([InlineKeyboardButton("🌐 Show all projects", callback_data="sessions_all")])
        await msg.edit_text(
            f"📋 Sessions for: {project_name}\n{header}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"sessions_command failed: {e}")
        await msg.edit_text(f"⚠️ Failed to fetch sessions: {e}")


async def infinite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle infinite sessions (automatic context compaction)."""
    if not await security_check(update): return
    service.infinite_sessions_enabled = not service.infinite_sessions_enabled
    if service.infinite_sessions_enabled:
        await update.message.reply_text(
            "♾️ Infinite Sessions: ENABLED\n"
            "Context auto-compaction is on. Takes effect on next /clear or session reset."
        )
    else:
        await update.message.reply_text(
            "🔒 Infinite Sessions: DISABLED\n"
            "Manual context management restored."
        )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check Copilot CLI connection and auth status."""
    if not await security_check(update): return
    if not service._is_running:
        await update.message.reply_text("🔴 Copilot CLI is not running. Select a project first.")
        return
    msg = await update.message.reply_text("🔄 Pinging...")
    try:
        state = service.client.get_state()
        ping = await service.client.ping()
        auth = await service.client.get_auth_status()
        login = auth.login or "unknown"
        authenticated = "✅" if auth.isAuthenticated else "❌"
        await msg.edit_text(
            f"🟢 Copilot CLI Status\n"
            f"• Connection: {state}\n"
            f"• Protocol: v{ping.protocolVersion}\n"
            f"• Auth: {authenticated} {login}\n"
            f"• Host: {auth.host or 'github.com'}"
        )
    except Exception as e:
        logger.error(f"ping_command failed: {e}")
        await msg.edit_text(f"🔴 Ping failed: {e}")


async def compact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compact context: resets session. Enable /infinite for auto-compaction."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    context.user_data['plan_mode'] = False
    await service.reset_session()
    tip = "" if service.infinite_sessions_enabled else "\nTip: Use /infinite to enable automatic context compaction."
    await update.message.reply_text(f"🗜️ Context compacted — session reset.{tip}")


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run an AI code review on the current git diff."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    cwd = service.get_working_directory()
    msg = await update.message.reply_text("🔍 Fetching diff for review...")
    try:
        proc = await asyncio.create_subprocess_shell(
            "git diff HEAD",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        diff = stdout.decode().strip()
    except Exception as e:
        await msg.edit_text(f"⚠️ Failed to get diff: {e}")
        return
    if not diff:
        await msg.edit_text("ℹ️ No uncommitted changes to review.")
        return
    await msg.delete()
    # Leave ~40k tokens for prompt overhead + response; 1 token ≈ 4 chars
    max_diff_chars = min(len(diff), 320_000)
    if len(diff) > max_diff_chars:
        truncation_note = f"\n\n⚠️ Diff truncated to {max_diff_chars:,} chars (full diff is {len(diff):,} chars)."
    else:
        truncation_note = ""
    prompt = (
        "Please review the following git diff. Focus on:\n"
        "- Bugs or logic errors\n"
        "- Security issues\n"
        "- Code quality and clarity\n"
        "- Any missing edge cases\n\n"
        f"```\n{diff[:max_diff_chars]}\n```"
        f"{truncation_note}"
    )
    await chat_handler(update, context, override_text=prompt)


async def changelog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a changelog entry from recent git commits."""
    if not await security_check(update): return
    if not await check_project_selected(update): return
    cwd = service.get_working_directory()
    msg = await update.message.reply_text("🔍 Reading git log...")
    try:
        proc = await asyncio.create_subprocess_shell(
            "git log --oneline -30",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        log = stdout.decode().strip()
    except Exception as e:
        await msg.edit_text(f"⚠️ Failed to get git log: {e}")
        return
    if not log:
        await msg.edit_text("ℹ️ No commits found.")
        return
    await msg.delete()
    prompt = (
        "Generate a concise, well-formatted changelog entry based on these recent commits. "
        "Group changes by type (Features, Bug Fixes, Improvements). "
        "Use plain text bullet points.\n\n"
        f"Commits:\n{log}"
    )
    await chat_handler(update, context, override_text=prompt)


async def streamer_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle live streaming mode (real-time token display)."""
    if not await security_check(update): return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    service.streaming_enabled = not service.streaming_enabled
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Reset session now", callback_data="streamer:reset")
    ]])
    if service.streaming_enabled:
        await update.message.reply_text(
            "📡 Streamer Mode: ENABLED\n"
            "Responses will stream live as tokens arrive.\n"
            "A session reset is required for streaming to take effect.",
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(
            "🔇 Streamer Mode: DISABLED\n"
            "Responses will be sent as complete messages (default behavior).\n"
            "A session reset is required for the change to take effect.",
            reply_markup=keyboard,
        )

