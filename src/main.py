import logging
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    filters
)
from telegram.constants import ParseMode

from src.config import TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID
from src.core.service import service
from src.handlers.commands import (
    start_command, help_command, edit_command, clear_command, 
    usage_command, plan_command, cwd_command, ls_command, 
    context_command, tools_command,
    info_command, model_command, share_command, cancel_command,
    _build_main_menu
)
from src.handlers.messages import chat_handler
from src.handlers.callbacks import button_handler, create_project_name, WAITING_PROJECT_NAME

logger = logging.getLogger(__name__)

async def post_init(application):
    if ALLOWED_USER_ID:
        try:
            msg, keyboard = await _build_main_menu()
            await application.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            
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

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).concurrent_updates(True).post_init(post_init).post_shutdown(post_shutdown).build()
    
    # Conversation Handler for Project Creation
    fallback_handlers = [CommandHandler("cancel", lambda u, c: ConversationHandler.END), CommandHandler("start", start_command)]
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^proj_new$")],
        states={WAITING_PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_name)]},
        fallbacks=fallback_handlers,
        per_message=False
    )
    
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
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    
    # Conversation & Callbacks
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Message Handler (Chat)
    app.add_handler(MessageHandler((filters.TEXT & (~filters.COMMAND)) | filters.ATTACHMENT, chat_handler))
    
    logger.info("Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
