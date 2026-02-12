import logging
from pathlib import Path
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
    context_command, tools_command,
    model_command, share_command, cancel_command,
    session_command,
    build_main_menu
)
from src.handlers.messages import chat_handler
from src.handlers.callbacks import button_handler, create_project_name, WAITING_PROJECT_NAME

logger = logging.getLogger(__name__)

BOT_DESCRIPTION = (
    "The Telegram AI assistant Bot built for developers. "
    "Bring the power of GitHub Copilot directly into your chats."
)
BOT_SHORT_DESCRIPTION = "GitHub Copilot AI assistant for Telegram"
ICON_PATH = Path(__file__).parent / "assets" / "copilot-telegram-bot_icon.png"

async def _setup_bot_profile(bot):
    """Set bot profile photo, description, and short description."""
    # Set description + short description
    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
        logger.info("✅ Bot description set")
    except Exception as e:
        logger.warning(f"⚠️ Failed to set bot description: {e}")

    # Set profile photo (compress + upload)
    if ICON_PATH.exists():
        try:
            from io import BytesIO
            from PIL import Image
            from telegram import InputProfilePhotoStatic

            img = Image.open(ICON_PATH)
            img = img.convert("RGBA")
            img.thumbnail((512, 512), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            buf.name = "photo.png"

            photo = InputProfilePhotoStatic(photo=buf)
            await bot.do_api_request(
                "setMyProfilePhoto",
                api_kwargs={"photo": photo},
            )
            logger.info("✅ Bot profile photo set")
        except ImportError as e:
            logger.warning(f"⚠️ Missing dependency for profile photo: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to set profile photo: {e}")
    else:
        logger.warning(f"⚠️ Icon not found: {ICON_PATH}")

async def post_init(application):
    await _setup_bot_profile(application.bot)
    if ALLOWED_USER_ID:
        try:
            msg, keyboard = await build_main_menu()
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
    fallback_handlers = [
        CommandHandler("cancel", start_command),
        CommandHandler("start", start_command),
    ]
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
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("session", session_command))
    
    # Conversation & Callbacks
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Message Handler (Chat)
    app.add_handler(MessageHandler((filters.TEXT & (~filters.COMMAND)) | filters.ATTACHMENT, chat_handler))
    
    logger.info("Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
