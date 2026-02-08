import uuid
import asyncio
import time
import logging
from typing import Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.config import ALLOWED_USER_ID
from src.core.service import service
from src.ui.streamer import MessageSender
from src.handlers.utils import security_check, check_project_selected

logger = logging.getLogger(__name__)

# Pending Interactions (Future map) - Shared with callbacks
# Structure: {interaction_id: {"future": Future, "timestamp": float, "chat_id": int, "context": ContextTypes.DEFAULT_TYPE}}
PENDING_INTERACTIONS = {}
INTERACTION_TTL = 300  # 5 minutes (matches send_and_wait timeout)

def cleanup_pending_interactions():
    """Removes interactions that are older than INTERACTION_TTL."""
    now = time.time()
    to_remove = []
    for interaction_id, data in list(PENDING_INTERACTIONS.items()):
        if isinstance(data, dict):
            future = data.get("future")
            timestamp = data.get("timestamp", now)
            # Remove if done/cancelled or expired
            if future and (future.done() or (now - timestamp) > INTERACTION_TTL):
                to_remove.append(interaction_id)
                if not future.done():
                    logger.warning(f"Interaction {interaction_id} expired after {INTERACTION_TTL}s")
                    try:
                        future.set_exception(TimeoutError("User interaction timed out"))
                    except Exception:
                        pass
        elif hasattr(data, 'done') and data.done():
            # Legacy format - just a future
            to_remove.append(interaction_id)
    
    for k in to_remove:
        PENDING_INTERACTIONS.pop(k, None)
    
    if to_remove:
        logger.info(f"Cleaned up {len(to_remove)} pending interactions")

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str = None):
    if not await security_check(update): return
    if not await check_project_selected(update): return
    
    if service.session_expired:
        await update.message.reply_text("⚠️ Session expired. Use /start to begin a new session.")
        return
    
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

    # Send placeholder — will be edited into the first real content
    response_msg = await update.message.reply_text("`Thinking...`", parse_mode=ParseMode.MARKDOWN)
    sender = MessageSender(response_msg)
    completion_event = asyncio.Event()
    response_chunks: list[str] = []

    # ---- Callbacks wired into service.chat() ----

    async def tool_log(status: str):
        """Handle tool status events. Send all as permanent messages."""
        if not status:  # Empty status = clear signal, ignore
            return
        logger.debug(f"🔍 tool_log received: {repr(status)}")
        await sender.send_tool_event(status)

    async def stream_content(text_chunk: str):
        """Accumulate response chunks (no streaming to Telegram)."""
        response_chunks.append(text_chunk)

    async def on_completion():
        """Signal that the model has finished."""
        completion_event.set()

    async def interaction_callback(kind: str, payload: Any) -> Any:
        cleanup_pending_interactions()
        interaction_id = str(uuid.uuid4())[:8]
        future = asyncio.get_running_loop().create_future()
        chat_id = update.effective_chat.id if update and update.effective_chat else None
        
        # Store future with metadata
        PENDING_INTERACTIONS[interaction_id] = {
            "future": future,
            "timestamp": time.time(),
            "chat_id": chat_id,
            "context": context,
            "kind": kind,
            "options": getattr(payload, 'options', []) if kind == "input" else None
        }
        
        logger.info(f"⚡ Interaction created: {interaction_id} | Kind: {kind} | Chat: {chat_id}")
        
        try:
            if kind == "permission":
                tool_name = getattr(payload, 'tool_name', 'unknown')
                args = getattr(payload, 'arguments', {})
                # Compact permission request format
                args_str = ""
                if args and len(str(args)) > 0:
                    args_preview = str(args)[:80]
                    args_str = f" with: `{args_preview}{'...' if len(str(args)) > 80 else ''}`"
                msg_text = f"🛡️ Permission request: **{tool_name}**{args_str}\n\nAllow?"
                # Store tool_name in interaction_data for later reference
                PENDING_INTERACTIONS[interaction_id]["tool_name"] = tool_name
                buttons = [[
                    InlineKeyboardButton("✅ Allow", callback_data=f"perm:{interaction_id}:allow"),
                    InlineKeyboardButton("❌ Deny", callback_data=f"perm:{interaction_id}:deny"),
                ]]
                await _send_interaction_msg(update, context, chat_id, msg_text, buttons)
                        
            elif kind == "input":
                prompt = getattr(payload, 'message', str(payload))
                options = getattr(payload, 'options', [])
                
                # Edit placeholder to show waiting state if not yet used
                if not sender._placeholder_used:
                    try:
                        await sender.placeholder.edit_text("⏳ *Waiting for your input...*", parse_mode=ParseMode.MARKDOWN)
                        sender._placeholder_used = True
                    except Exception as e:
                        logger.debug(f"Could not edit placeholder: {e}")
                
                msg_text = f"❓ **Copilot Asks:**\n{prompt}\n\nSelect an option:"
                buttons = []
                for i, opt in enumerate(options):
                    label = str(opt)
                    btn_label = (label[:30] + '..') if len(label) > 30 else label
                    callback_data = f"input:{interaction_id}:{label}"
                    if len(callback_data.encode('utf-8')) > 64:
                        callback_data = f"input:{interaction_id}:{i}"
                    buttons.append([InlineKeyboardButton(btn_label, callback_data=callback_data)])
                buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"input:{interaction_id}:cancel")])
                await _send_interaction_msg(update, context, chat_id, msg_text, buttons)
            
            logger.info(f"⏳ Awaiting user response for interaction {interaction_id}...")
            result = await future
            logger.info(f"✅ User response received for {interaction_id}: {result}")
            return result

        except asyncio.TimeoutError:
            logger.error(f"⏱️ Interaction {interaction_id} timed out")
            PENDING_INTERACTIONS.pop(interaction_id, None)
            return False if kind == "permission" else "cancel"
        except Exception as e:
            logger.error(f"❌ Interaction {interaction_id} failed: {e}", exc_info=True)
            PENDING_INTERACTIONS.pop(interaction_id, None)
            return False if kind == "permission" else "cancel"

    # ---- Execute chat ----

    try:
        await service.chat(
            user_text, 
            content_callback=stream_content, 
            status_callback=tool_log, 
            interaction_callback=interaction_callback,
            completion_callback=on_completion,
        )
        
        # Wait for completion signal
        try:
            await asyncio.wait_for(completion_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Completion event timeout — proceeding")
        
        # Build footer
        footer = ""
        try:
            project, model, cost = service.get_usage_metadata()
            git = await service.get_git_info()
            mode = "Planning" if context.user_data.get('plan_mode') else "Chat"
            parts = [f"📂 {project}"]
            if git:
                parts.append(f"🔀 {git[1:]}")
            parts.append(f"🤖 {model} ({cost}x)")
            parts.append(f"⚙️ Mode: {mode}")
            footer = "\n".join(parts)
        except Exception as e:
            logger.error(f"Footer generation failed: {e}")
        
        # Send blockin response with footer
        full_response = "".join(response_chunks)
        await sender.send_response(full_response, footer)

    except asyncio.TimeoutError as e:
        error_msg = str(e)
        logger.error(f"Chat Timeout Error: {error_msg}")
        if "session.idle" in error_msg:
            user_msg = error_msg.replace("waiting for session.idle", "waiting for user selection")
            await update.message.reply_text(f"⚠️ Error: {user_msg}")
        else:
            await update.message.reply_text(f"⚠️ Error: {error_msg}")
    except Exception as e:
        logger.error(f"Chat Error: {e}")
        await update.message.reply_text(f"⚠️ Error: {str(e)}")


async def _send_interaction_msg(update, context, chat_id, text, buttons):
    """Send an inline-keyboard message, with fallback to context.bot.send_message."""
    markup = InlineKeyboardMarkup(buttons)
    try:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as send_err:
        logger.error(f"❌ Failed to send interaction message: {send_err}", exc_info=True)
        if chat_id and context:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as fallback_err:
                logger.error(f"❌ Fallback send also failed: {fallback_err}", exc_info=True)
                raise
        else:
            raise
