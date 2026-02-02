import os
import shutil
import asyncio
import logging
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
    if not await security_check(update): return
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    version = await service.get_cli_version()
    auth = await service.get_auth_status()
    # Use WORKSPACE_ROOT to indicate the "Home Base"
    # Even if we are deep in a project, the main menu represents the overall bot status
    pwd = WORKSPACE_ROOT.replace(os.path.expanduser("~"), "~")
    
    # Compact ASCII for Mobile (approx 30 chars wide)
    logo = (
        "```\n"
        "╭────────────────────────────╮\n"
        "│    Copilot CLI-Telegram    │\n"
        "│        [v0.1.0]            │\n"
        "╰────────────────────────────╯\n"
        "```"
    )
    
    plan_mode = context.user_data.get('plan_mode', False)
    mode_status = "📐 PLAN" if plan_mode else "💬 CHAT"
    
    msg = (
        f"{logo}\n"
        f"**Status:** `{auth}` | v`{version}`\n"
        f"**Workspace:** `{pwd}`\n"
        f"**Mode:** `{mode_status}`\n"
        f"**Model:** `{service.current_model}`\n\n"
        "**Commands:**\n"
        "/start - Main Menu\n"
        "/plan  - Toggle Plan Mode\n"
        "/edit  - Switch to Chat Mode\n"
        "/model - Change Model\n"
        "/info  - Debug Info\n\n"
        "**Select Project:**"
    )
    
    # If update comes from a callback query, edit the message; otherwise reply
    if update.callback_query:
        # Check if we should edit or reply based on context? 
        # For /start (update.message), we reply.
        # For "Back" button (callback), we edit.
        try:
            await update.callback_query.message.edit_text(msg, reply_markup=get_project_keyboard(), parse_mode=ParseMode.MARKDOWN)
        except:
            await update.callback_query.message.reply_text(msg, reply_markup=get_project_keyboard(), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(msg, reply_markup=get_project_keyboard(), parse_mode=ParseMode.MARKDOWN)

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    context.user_data['plan_mode'] = False
    logger.info("Switched to Edit Mode")
    await update.message.reply_text("💬 **Switched to Edit (Chat) Mode**", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Redirect help to main menu as it contains the commands list now
    await show_main_menu(update, context)

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    mode = not context.user_data.get('plan_mode', False)
    context.user_data['plan_mode'] = mode
    status = "Enabled" if mode else "Disabled"
    logger.info(f"Plan Mode: {status}")
    await update.message.reply_text(f"📝 **Plan Mode {status}**", parse_mode=ParseMode.MARKDOWN)

async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    files = service.get_context_files()
    if not files:
        await update.message.reply_text("📂 No files in context.")
    else:
        file_list = "\n".join([f"- `{f}`" for f in files])
        await update.message.reply_text(f"🧠 **Context Files:**\n{file_list}", parse_mode=ParseMode.MARKDOWN)

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    await update.message.reply_text("🛠 **Enabled Tools**\n✅ `list_files`\n✅ `read_file`\n❌ `run_shell`", parse_mode=ParseMode.MARKDOWN)

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    msg = (
        f"📊 **Session Info**\n"
        f"• Model: `{service.current_model}`\n"
        f"• Mode: `{'Planning' if context.user_data.get('plan_mode') else 'Chat'}`\n"
        f"• Directory: `{service.get_working_directory()}`\n"
        f"• Workspace: `{WORKSPACE_ROOT}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    msg = await update.message.reply_text("🔄 Fetching models...")
    keyboard = await get_model_keyboard()
    await msg.edit_text(f"Select a model:", reply_markup=keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"Button Click: {query.data}")

    if query.data.startswith("model:"):
        model = query.data.split(":")[1]
        await service.reset_session(model)
        await query.edit_message_text(f"✅ Model: `{model}`", parse_mode=ParseMode.MARKDOWN)
    elif query.data.startswith("proj:"):
        folder = query.data.split(":")[1]
        path = Path(WORKSPACE_ROOT) / folder
        
        # Reset Plan Mode on Project Switch
        context.user_data['plan_mode'] = False
        
        # Switch Directory (Restarts Client)
        try:
            await service.set_working_directory(str(path))
            
            # Reset Session (New context)
            await service.reset_session()
            
            # 1. Send Confirmation Message (Separate)
            await query.message.reply_text(f"✅ **Switched to Project:** `{folder}`", parse_mode=ParseMode.MARKDOWN)
            
            # 2. Show Project Structure (Separate Message)
            tree = service.get_project_structure()
            welcome_msg = (
                f"📂 **Structure:**\n```\n{tree}\n```\n"
                f"💡 **Ready!** Ask questions or use /plan to start designing."
            )
            await query.message.reply_text(welcome_msg, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Project Switch Failed: {e}")
            await query.message.reply_text(f"⚠️ Failed to switch project: {e}")
            
    elif query.data == "proj_new":
        await query.message.reply_text("New project name:")
        return WAITING_PROJECT_NAME

async def create_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    name = re.sub(r"\W+", "_", update.message.text).strip("_")
    if not name: return ConversationHandler.END
    path = Path(WORKSPACE_ROOT) / name
    path.mkdir(exist_ok=True)
    
    context.user_data['plan_mode'] = False
    await service.set_working_directory(str(path))
    await service.reset_session()
    
    await update.message.reply_text(f"✅ **Created:** `{name}`", parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    user_text = update.message.text
    if context.user_data.get('plan_mode'):
        user_text = "PLAN MODE: Focus on high-level architecture. " + user_text

    # 1. Initialize Response Message IMMEDIATELY
    # This gives immediate feedback while the bot thinks or runs tools.
    response_msg = await update.message.reply_text("`Thinking...`", parse_mode=ParseMode.MARKDOWN)
    streamer = SmartStreamer(response_msg)

    async def tool_log(status: str):
        # CLI Style: Push Log ABOVE the current stream
        safe_status = status.replace("```", "'''") # Escape code block delimiters
        log_msg = f"```\n{safe_status}\n```"
        await streamer.log_event(log_msg)

    async def stream_content(text_chunk):
        # Stream content to the ALREADY created message
        await streamer.stream(text_chunk)

    try:
        await service.chat(user_text, content_callback=stream_content, status_callback=tool_log)
        
        # Append Terminal Status Line
        pwd = service.get_working_directory().replace(os.path.expanduser("~"), "~")
        git = await service.get_git_info()
        model = service.current_model
        mult = service.MODEL_METADATA.get(model, "1x")
        
        footer = f"\n\n`{pwd}{git}  {model} ({mult})`"
        streamer.full_text += footer
        await streamer.close()
            
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

async def post_init(application):
    if ALLOWED_USER_ID:
        try:
            await application.bot.send_message(chat_id=ALLOWED_USER_ID, text="🚀 **Copilot Online**\nSend /start to begin.", parse_mode=ParseMode.MARKDOWN)
        except: pass

def main():
    if not TOKEN: return
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^proj_new$")],
        states={WAITING_PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_name)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("edit", edit_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("context", context_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
    app.run_polling()

if __name__ == "__main__":
    main()