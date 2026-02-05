import os
import shutil
import asyncio
import logging
from typing import Any, Dict
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes, 
    filters
)
from copilot_service import CopilotService
from ux_utils import SmartStreamer
import uuid
import time

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load env
load_dotenv(override=True)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.path.dirname(os.path.abspath(__file__)))

# Global Service
service = CopilotService()

# Pending Interactions (Future map)
PENDING_INTERACTIONS = {}

# Conversation States
WAITING_PROJECT_NAME = 1

# --- Helpers ---

async def security_check(update: Update) -> bool:
    user = update.effective_user
    if not ALLOWED_USER_ID:
        await update.message.reply_text(f"⚠️ Setup required. ID: `{user.id}`.")
        return False
    if str(user.id) != str(ALLOWED_USER_ID):
        return False
    return True

async def check_project_selected(update: Update) -> bool:
    if not service.project_selected:
        await update.message.reply_text("⚠️ **No Project Selected**\nPlease select or create a project from the /start menu first.", parse_mode=ParseMode.MARKDOWN)
        return False
    return True

def get_project_keyboard():
    root = Path(WORKSPACE_ROOT)
    if not root.exists(): root.mkdir(parents=True, exist_ok=True)
    buttons = []
    subdirs = sorted([d for d in root.iterdir() if d.is_dir() and not d.name.startswith('.')])
    row = []
    for d in subdirs:
        row.append(InlineKeyboardButton(f"📂 {d.name}", callback_data=f"proj:{d.name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("➕ Create New Project", callback_data="proj_new")])
    return InlineKeyboardMarkup(buttons)

async def get_model_keyboard():
    models_data = await service.get_available_models()
    buttons = []
    row = []
    for m in models_data:
        m_id = m.get("id", "unknown")
        mult = m.get("multiplier", "1x")
        row.append(InlineKeyboardButton(f"{m_id} ({mult})", callback_data=f"model:{m_id}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(buttons)

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("/start command received")
    if not await security_check(update): return
    await show_main_menu(update, context)
    return ConversationHandler.END

async def get_main_menu_content(context: ContextTypes.DEFAULT_TYPE):
    try:
        version = await service.get_cli_version()
        auth = await service.get_auth_status()
    except:
        version = "Unknown"
        auth = "Error"
        
    pwd = str(WORKSPACE_ROOT)
    
    msg = (
        f"🚀 **Copilot CLI-Telegram**\n"
        f"**User:** `{auth}`\n"
        f"**Copilot Version:** `{version}`\n"
        f"**Workspace:** `{pwd}`\n"
        f"**Model:** `{service.current_model}`\n\n"
        "**Commands:**\n"
        "• /start - Main Menu\n"
        "• /plan  - Create an implementation plan before coding\n"
        "• /edit  - Switch to Chat Mode\n"
        "• /clear - Clear the conversation history\n"
        "• /usage - Display session usage metrics and statistics\n"
        "• /model - Select AI model to use\n"
        "• /info  - Display session information\n"
        "• /share - Share session by export to a markdown file\n"
        "• /cwd   - Show current directory\n"
        "• /ls    - List files in current directory\n"
        "• /delegate - AI-generated PR to remote repository\n\n"
        "⚠️ **Action Required:** Select or create a project below to begin."
    )
    return msg, get_project_keyboard()

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Entering show_main_menu")
    try:
        msg, keyboard = await get_main_menu_content(context)
        
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.warning(f"Failed to edit message: {e}")
                await update.callback_query.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        
        logger.info("show_main_menu completed successfully")

    except Exception as e:
        logger.error(f"CRITICAL ERROR in show_main_menu: {e}", exc_info=True)

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

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    context.user_data['plan_mode'] = False
    logger.info("Switched to Edit Mode")
    await update.message.reply_text("💬 **Switched to Edit (Chat) Mode**", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    mode = not context.user_data.get('plan_mode', False)
    context.user_data['plan_mode'] = mode
    if mode:
        await update.message.reply_text(f"📝 **Switch to Plan Mode**", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"💬 **Switch to Edit (Chat) Mode**", parse_mode=ParseMode.MARKDOWN)

async def cwd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    cwd = service.get_working_directory()
    await update.message.reply_text(f"● Current working directory: {cwd}")

async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    ls_text = service.get_ls_output()
    await update.message.reply_text(ls_text)

async def delegate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    args = context.args
    prompt = " ".join(args) if args else ""
    if not prompt:
        await update.message.reply_text("⚠️ Usage: `/delegate <your instructions>`", parse_mode=ParseMode.MARKDOWN)
        return
    await chat_handler(update, context, override_text=f"/delegate {prompt}")

async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    files = service.get_context_files()
    if not files:
        await update.message.reply_text("📂 No files in context.")
    else:
        file_list = "\n".join([f"- `{f}`" for f in files])
        await update.message.reply_text(f"🧠 **Context Files:**\n{file_list}", parse_mode=ParseMode.MARKDOWN)

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    await update.message.reply_text("🛠 **Enabled Tools**\n✅ `list_files`\n✅ `read_file`\n❌ `run_shell`", parse_mode=ParseMode.MARKDOWN)

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    status = "Active" if service.project_selected else "No Project Selected"
    msg = (
        f"📊 **Session Info**\n"
        f"• Status: `{status}`\n"
        f"• Model: `{service.current_model}`\n"
        f"• Mode: `{'Planning' if context.user_data.get('plan_mode') else 'Chat'}`\n"
        f"• Directory: `{service.get_working_directory()}`\n"
        f"• Workspace: `{WORKSPACE_ROOT}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    msg = await update.message.reply_text("🔄 Fetching models...")
    keyboard = await get_model_keyboard()
    await msg.edit_text(f"Select a model:", reply_markup=keyboard)

async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    msg = await update.message.reply_text("📤 Exporting session...")
    try:
        file_path = await service.export_session_to_file()
        if file_path and os.path.exists(file_path):
            await update.message.reply_document(document=open(file_path, 'rb'), filename=os.path.basename(file_path))
            os.remove(file_path)
            await msg.delete()
        else:
            await msg.edit_text("⚠️ Failed to export session or empty.")
    except Exception as e:
        logger.error(f"Share failed: {e}")
        await msg.edit_text(f"⚠️ Error sharing session: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"Button Click: {query.data}")

    if query.data.startswith("perm:") or query.data.startswith("input:"):
        parts = query.data.split(":")
        action_type = parts[0]
        interaction_id = parts[1]
        value = parts[2] if len(parts) > 2 else None
        
        future = PENDING_INTERACTIONS.get(interaction_id)
        if future and not future.done():
            if action_type == "perm":
                result = (value == "allow")
                future.set_result(result)
                await query.edit_message_text(f"✅ **Permission:** `{value.upper()}`", parse_mode=ParseMode.MARKDOWN)
            elif action_type == "input":
                future.set_result(value)
                await query.edit_message_text(f"✅ **Selected:** `{value}`", parse_mode=ParseMode.MARKDOWN)
            PENDING_INTERACTIONS.pop(interaction_id, None)
        else:
            await query.edit_message_text("⚠️ Interaction expired or already handled.")
        return

    if query.data.startswith("model:"):
        model = query.data.split(":")[1]
        await service.reset_session(model)
        await query.edit_message_text(f"✅ Model: `{model}`", parse_mode=ParseMode.MARKDOWN)
    elif query.data.startswith("proj:"):
        folder = query.data.split(":")[1]
        path = Path(WORKSPACE_ROOT) / folder
        context.user_data['plan_mode'] = False
        try:
            await service.set_working_directory(str(path))
            await service.reset_session()
            await query.message.reply_text(f"✅ **Switched to Project:** `{folder}`", parse_mode=ParseMode.MARKDOWN)
            tree = service.get_project_structure()
            await query.message.reply_text(f"📂 Structure:\n{tree}")
        except Exception as e:
            logger.error(f"Project Switch Failed: {e}")
            await query.message.reply_text(f"⚠️ Failed to switch project: {e}")
    elif query.data == "proj_new":
        await query.message.reply_text("New project name:")
        return WAITING_PROJECT_NAME

async def create_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    name = re.sub(r"\W+", "_", update.message.text).strip("_")
    if not name: 
        await update.message.reply_text("⚠️ Invalid name. Try again or /cancel.")
        return WAITING_PROJECT_NAME
    path = Path(WORKSPACE_ROOT) / name
    if path.exists():
        await update.message.reply_text(f"⚠️ Project `{name}` already exists. Switched to it.", parse_mode=ParseMode.MARKDOWN)
    else:
        path.mkdir(exist_ok=True)
        await update.message.reply_text(f"✅ **Created:** `{name}`", parse_mode=ParseMode.MARKDOWN)
    context.user_data['plan_mode'] = False
    try:
        await service.set_working_directory(str(path))
        await service.reset_session()
        await update.message.reply_text(f"✅ **Switched to Project:** `{name}`", parse_mode=ParseMode.MARKDOWN)
        tree = service.get_project_structure()
        await update.message.reply_text(f"📂 Structure:\n{tree}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error setting directory: {e}")
    return ConversationHandler.END

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str = None):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    user_text = override_text or (update.message.text if update.message else "") or ""

    attachment = update.message.document or (update.message.photo[-1] if update.message.photo else None)
    if attachment:
        try:
            file_obj = await attachment.get_file()
            original_name = getattr(attachment, 'file_name', None)
            if not original_name:
                ext = ".jpg" if update.message.photo else ""
                original_name = f"file_{int(time.time())}{ext}"
            temp_dir = service.get_temp_dir()
            download_path = temp_dir / original_name
            await file_obj.download_to_drive(custom_path=download_path)
            rel_path = f"@{temp_dir.name}/{original_name}"
            user_text = f"{rel_path} {update.message.caption or ''}".strip()
            await update.message.reply_text(f"📎 Uploaded: `{original_name}`", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            await update.message.reply_text(f"⚠️ Upload failed: {e}")
            return
            
    if not user_text: return

    if context.user_data.get('plan_mode'):
        user_text = "PLAN MODE: Focus on high-level architecture. " + user_text

    response_msg = await update.message.reply_text("`Thinking...`", parse_mode=ParseMode.MARKDOWN)
    streamer = SmartStreamer(response_msg)

    async def tool_log(status: str):
        safe_status = status.replace("```", "'''")
        await streamer.log_event(f"```\n{safe_status}\n```")

    async def stream_content(text_chunk):
        await streamer.stream(text_chunk)

    async def interaction_callback(kind: str, payload: Any) -> Any:
        interaction_id = str(uuid.uuid4())[:8]
        future = asyncio.get_running_loop().create_future()
        PENDING_INTERACTIONS[interaction_id] = future
        try:
            if kind == "permission":
                tool_name = getattr(payload, 'tool_name', str(payload))
                args = getattr(payload, 'arguments', {})
                msg_text = f"🛡️ **Permission Request**\nTool: `{tool_name}`\nArgs: `{args}`\n\nAllow execution?"
                buttons = [[InlineKeyboardButton("✅ Allow", callback_data=f"perm:{interaction_id}:allow"), InlineKeyboardButton("❌ Deny", callback_data=f"perm:{interaction_id}:deny")]]
                await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
            elif kind == "input":
                prompt = getattr(payload, 'message', str(payload))
                options = getattr(payload, 'options', [])
                msg_text = f"❓ **Copilot Asks:**\n{prompt}\n\nSelect an option:"
                buttons = []
                for i, opt in enumerate(options):
                    label = str(opt)
                    btn_label = (label[:30] + '..') if len(label) > 30 else label
                    buttons.append([InlineKeyboardButton(btn_label, callback_data=f"input:{interaction_id}:{label}")])
                buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"input:{interaction_id}:cancel")])
                await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
            return await future
        except Exception as e:
            logger.error(f"Interaction failed: {e}")
            PENDING_INTERACTIONS.pop(interaction_id, None)
            return False if kind == "permission" else "cancel"

    try:
        await service.chat(user_text, content_callback=stream_content, status_callback=tool_log, interaction_callback=interaction_callback)
        try:
            pwd = service.get_working_directory().replace(os.path.expanduser("~"), "~")
            git = await service.get_git_info()
            model = service.current_model
            mult = service.MODEL_METADATA.get(model, "1x")
            footer = f"\n\n`{pwd}{git}  {model} ({mult})`"
            streamer.full_text += footer
        except: pass
        await streamer.close()
    except Exception as e:
        logger.error(f"Chat Error: {e}")
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

async def post_init(application):
    if ALLOWED_USER_ID:
        try:
            class MockContext: user_data = {}
            msg, keyboard = await get_main_menu_content(MockContext())
            await application.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e: logger.error(f"Startup menu failed: {e}")

async def post_shutdown(application):
    await service.stop()

def main():
    if not TOKEN: return
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    fallback_handlers = [CommandHandler("cancel", lambda u, c: ConversationHandler.END), CommandHandler("start", start)]
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^proj_new$")],
        states={WAITING_PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_name)]},
        fallbacks=fallback_handlers,
        per_message=False
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("edit", edit_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("cwd", cwd_command))
    app.add_handler(CommandHandler("ls", ls_command))
    app.add_handler(CommandHandler("delegate", delegate_command))
    app.add_handler(CommandHandler("context", context_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler((filters.TEXT & (~filters.COMMAND)) | filters.ATTACHMENT, chat_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
