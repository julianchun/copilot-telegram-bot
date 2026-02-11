import logging
from telegram import Update
from telegram.constants import ParseMode
from src.config import ALLOWED_USER_ID
from src.core.service import service

logger = logging.getLogger(__name__)

async def security_check(update: Update) -> bool:
    """
    Verifies if the user is authorized to use the bot.
    """
    user = update.effective_user
    if not user:
        return False
        
    if not ALLOWED_USER_ID:
        msg = update.effective_message
        if msg:
            await msg.reply_text(f"⚠️ Setup required. ID: `{user.id}`.")
        return False
        
    if user.id != ALLOWED_USER_ID:
        logger.warning(f"Unauthorized access attempt by user {user.id} ({user.username})")
        return False
        
    return True

async def check_project_selected(update: Update) -> bool:
    """
    Ensures a project is currently selected in the service.
    """
    if not service.project_selected:
        if update.message:
            await update.message.reply_text(
                "⚠️ **No Project Selected**\nPlease select or create a project from the /start menu first.", 
                parse_mode=ParseMode.MARKDOWN
            )
        elif update.callback_query:
            await update.callback_query.answer("⚠️ No Project Selected", show_alert=True)
        return False
    return True
