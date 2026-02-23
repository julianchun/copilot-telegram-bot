import logging
from pathlib import Path
from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    filters
)

from src.config import TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID
from src.core.service import service
from src.handlers.commands import (
    start_command, help_command, edit_command, clear_command, 
    usage_command, plan_command, cwd_command, ls_command, 
    context_command,
    model_command, share_command, cancel_command,
    session_command,
    diff_command, instructions_command, update_command, allow_all_command,
    effort_command, sessions_command, infinite_command, ping_command,
    compact_command, review_command, changelog_command, streamer_mode_command,
    build_main_menu
)
from src.handlers.messages import chat_handler
from src.handlers.callbacks import button_handler, create_project_name, WAITING_PROJECT_NAME, cancel_create_project, reject_command_during_creation

logger = logging.getLogger(__name__)

BOT_DESCRIPTION = (
    "The Telegram AI assistant Bot built for developers. "
    "Bring the power of GitHub Copilot directly into your chats."
)
BOT_SHORT_DESCRIPTION = "GitHub Copilot AI assistant for Telegram"

async def setup_bot_commands(application):
    """Set bot commands visible in Telegram UI."""
    commands = [
        BotCommand("start", "Open project selection menu"),
        BotCommand("help", "Show help manual"),
        BotCommand("plan", "Architecture & Planning mode"),
        BotCommand("edit", "Standard Chat/Coding mode"),
        BotCommand("model", "Switch AI Model"),
        BotCommand("effort", "Set reasoning effort level"),
        BotCommand("sessions", "Browse & resume past sessions"),
        BotCommand("clear", "Reset conversation memory"),
        BotCommand("compact", "Compact context (smart reset)"),
        BotCommand("cancel", "Cancel in-progress request"),
        BotCommand("share", "Export session to Markdown"),
        BotCommand("usage", "Display session usage metrics"),
        BotCommand("context", "Display model context info"),
        BotCommand("session", "Show session info & workspace summary"),
        BotCommand("infinite", "Toggle infinite sessions (auto-compaction)"),
        BotCommand("allowall", "Toggle allow-all-tools mode"),
        BotCommand("diff", "Show git diff"),
        BotCommand("review", "AI code review of current diff"),
        BotCommand("changelog", "Generate changelog from git log"),
        BotCommand("instructions", "View Copilot instructions file"),
        BotCommand("ls", "Project file tree"),
        BotCommand("cwd", "Show current directory"),
        BotCommand("ping", "Check CLI connection status"),
        BotCommand("update", "Update Copilot CLI"),
        BotCommand("streamer_mode", "Toggle live token streaming"),
    ]
    try:
        # Set bot commands
        await application.bot.set_my_commands(commands)
        logger.info(f"✅ Bot commands set successfully ({len(commands)} commands)")
        
        # Set bot description
        await application.bot.set_my_description(BOT_DESCRIPTION)
        await application.bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
        logger.info("✅ Bot description set successfully")
    except Exception as e:
        logger.error(f"❌ Failed to set bot commands/description: {e}", exc_info=True)

async def post_init(application):
    # Set bot commands
    await setup_bot_commands(application)
    
    if ALLOWED_USER_ID:
        try:
            msg, keyboard, _ = await build_main_menu()
            await application.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, reply_markup=keyboard)
            
            # Set up session end notification callback
            async def notify_session_end(msg: str):
                try:
                    await application.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg)
                except Exception as e:
                    logger.error(f"Failed to send session end notification: {e}")
            service.session_end_callback = notify_session_end
        except Exception as e: 
            logger.error(f"Startup menu failed to send: {e}", exc_info=True)

async def post_shutdown(application):
    await service.stop()

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in env.")
        return

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Conversation Handler for Project Creation
    # Must be registered BEFORE standalone command handlers so it has priority
    # when a conversation is active (WAITING_PROJECT_NAME state).
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^proj_new$")],
        states={
            WAITING_PROJECT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_name),
                CommandHandler("cancel", cancel_create_project),
                MessageHandler(filters.COMMAND, reject_command_during_creation),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(button_handler),  # Handle proj: clicks during creation
        ],
        per_message=False
    )
    app.add_handler(conv_handler)
    
    # Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("edit", edit_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("cwd", cwd_command))
    app.add_handler(CommandHandler("ls", ls_command))
    app.add_handler(CommandHandler("context", context_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("diff", diff_command))
    app.add_handler(CommandHandler("instructions", instructions_command))
    app.add_handler(CommandHandler("update", update_command))
    app.add_handler(CommandHandler("allowall", allow_all_command))
    app.add_handler(CommandHandler("effort", effort_command))
    app.add_handler(CommandHandler("sessions", sessions_command))
    app.add_handler(CommandHandler("infinite", infinite_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("compact", compact_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("changelog", changelog_command))
    app.add_handler(CommandHandler("streamer_mode", streamer_mode_command))
    
    # Callbacks (non-project, e.g. perm:, input:, model:, reasoning:)
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Message Handler (Chat)
    app.add_handler(MessageHandler((filters.TEXT & (~filters.COMMAND)) | filters.ATTACHMENT, chat_handler))
    
    logger.info("Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
