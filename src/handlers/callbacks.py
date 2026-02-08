import logging
import asyncio
import re
from pathlib import Path
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from src.config import WORKSPACE_PATH
from src.core.service import service
from src.handlers.messages import PENDING_INTERACTIONS
from src.handlers.utils import security_check

logger = logging.getLogger(__name__)

WAITING_PROJECT_NAME = 1


async def _switch_project(path: Path, message, context: ContextTypes.DEFAULT_TYPE):
    """Common project-switching logic used by proj:, proj_granted:, and create_project_name."""
    context.user_data['plan_mode'] = False
    await service.set_working_directory(str(path))
    header = await service.get_project_info_header(context.user_data)
    await message.reply_text(f"✅ **Switched to Project:** `{path.name}`\n\n{header}", parse_mode=ParseMode.MARKDOWN)


async def _handle_interaction_callback(query, update, context):
    """Handle perm: and input: callback queries."""
    parts = query.data.split(":")
    action_type = parts[0]
    interaction_id = parts[1]
    value = parts[2] if len(parts) > 2 else None

    logger.info(f"🔘 Button callback received | Type: {action_type} | ID: {interaction_id} | Value: {value}")

    interaction_data = PENDING_INTERACTIONS.get(interaction_id)

    if not interaction_data:
        logger.warning(f"⚠️ Interaction {interaction_id} not found in pending map")
        await query.edit_message_text("⚠️ Interaction expired or already handled.")
        return

    if isinstance(interaction_data, dict):
        future = interaction_data.get("future")
        options = interaction_data.get("options", [])
        logger.info(f"📦 Found interaction data | Future done: {future.done() if future else 'None'} | Options: {options}")
        if value and value.isdigit() and options:
            index = int(value)
            if 0 <= index < len(options):
                value = str(options[index])
                logger.info(f"🔄 Converted index {index} to option: {value}")
    else:
        future = interaction_data
        logger.warning(f"Found legacy future format for {interaction_id}")

    if future and not future.done():
        try:
            if action_type == "perm":
                result = (value == "allow")
                logger.info(f"✅ Resolving permission future with: {result}")
                future.set_result(result)
                # Extract tool name from stored interaction data
                tool_name = interaction_data.get("tool_name", "Tool") if isinstance(interaction_data, dict) else "Tool"
                action_emoji = "✓" if value == "allow" else "✕"
                action_text = "**Allow**" if value == "allow" else "**Deny**"
                decision_line = f"🛡️ Permission: `{tool_name}` → {action_text} {action_emoji}"
                await query.edit_message_text(decision_line, parse_mode=ParseMode.MARKDOWN)
            elif action_type == "input":
                logger.info(f"✅ Resolving input future with: {value}")
                future.set_result(value)
                await query.edit_message_text(f"❓ **Selected:** `{value}`", parse_mode=ParseMode.MARKDOWN)
                await query.message.reply_text(f"✅ Selected option: {value}", parse_mode=ParseMode.MARKDOWN)
            PENDING_INTERACTIONS.pop(interaction_id, None)
            logger.info(f"🧹 Cleaned up interaction {interaction_id}")
        except Exception as set_err:
            logger.error(f"❌ Error setting future result: {set_err}", exc_info=True)
            await query.edit_message_text(f"⚠️ Error processing selection: {str(set_err)}")
    else:
        logger.warning(f"⚠️ Future for {interaction_id} is None or already done")
        await query.edit_message_text("⚠️ Interaction expired or already handled.")


async def _handle_model_callback(query, context):
    """Handle model: callback queries."""
    model = query.data.split(":")[1]
    model_info = next((m for m in service._models_cache if m["id"] == model), None)
    if model_info and model_info.get("supports_reasoning") and model_info.get("supported_efforts"):
        from src.ui.menus import get_reasoning_keyboard
        keyboard = get_reasoning_keyboard(model, model_info["supported_efforts"], model_info.get("default_effort"))
        await query.edit_message_text(
            f"🤖 Model: `{model}`\n⚠️ Session will be reset (history cleared)\n\nSelect reasoning effort:",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await service.change_model(model)
        await query.edit_message_text(f"✅ Model: `{model}` (⚠️ session reset)", parse_mode=ParseMode.MARKDOWN)


async def _handle_reasoning_callback(query, context):
    """Handle reasoning: callback queries."""
    parts = query.data.split(":")
    model = parts[1]
    effort = parts[2]

    if effort == "default":
        service.current_reasoning_effort = None
    else:
        service.current_reasoning_effort = effort

    await service.change_model(model, reasoning_effort=service.current_reasoning_effort)
    effort_display = effort.capitalize() if effort != "default" else "Default"
    await query.edit_message_text(
        f"✅ Model: `{model}` | Effort: {effort_display}\n⚠️ Session reset",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_project_callback(query, context):
    """Handle proj: callback queries."""
    folder = query.data.split(":")[1]
    path = WORKSPACE_PATH / folder
    try:
        await _switch_project(path, query.message, context)
    except Exception as e:
        logger.error(f"Project Switch Failed: {e}")
        await query.message.reply_text(f"⚠️ Failed to switch project: {e}")


async def _handle_granted_project_callback(query, context):
    """Handle proj_granted: callback queries."""
    from src.config import GRANTED_PROJECT_PATHS
    try:
        idx = int(query.data.split(":")[1])
        if idx >= len(GRANTED_PROJECT_PATHS):
            await query.message.reply_text("⚠️ Invalid project index.")
            return
        path = GRANTED_PROJECT_PATHS[idx]
        if not path.exists():
            await query.message.reply_text(f"⚠️ Project path does not exist: `{path}`", parse_mode=ParseMode.MARKDOWN)
            return
        await _switch_project(path, query.message, context)
    except Exception as e:
        logger.error(f"Granted Project Switch Failed: {e}")
        await query.message.reply_text(f"⚠️ Failed to switch project: {e}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    logger.info(f"🎯 button_handler ENTRY - CallbackQuery received")

    query = update.callback_query
    logger.info(f"🎯 Query data: {query.data}")

    try:
        await query.answer()
    except Exception as e:
        logger.error(f"❌ query.answer() failed: {e}", exc_info=True)

    data = query.data

    try:
        if data.startswith("perm:") or data.startswith("input:"):
            await _handle_interaction_callback(query, update, context)
            return
        elif data.startswith("model:"):
            await _handle_model_callback(query, context)
        elif data.startswith("reasoning:"):
            await _handle_reasoning_callback(query, context)
        elif data.startswith("proj_granted:"):
            await _handle_granted_project_callback(query, context)
        elif data.startswith("proj:"):
            await _handle_project_callback(query, context)
        elif data == "proj_new":
            await query.message.reply_text("New project name:")
            return WAITING_PROJECT_NAME
    except Exception as e:
        logger.error(f"❌ Error handling button callback '{data}': {e}", exc_info=True)


async def create_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = re.sub(r"\W+", "_", update.message.text).strip("_")
    if not name:
        await update.message.reply_text("⚠️ Invalid name. Try again or /cancel.")
        return WAITING_PROJECT_NAME
    path = WORKSPACE_PATH / name
    if path.exists():
        await update.message.reply_text(f"⚠️ Project `{name}` already exists. Switched to it.", parse_mode=ParseMode.MARKDOWN)
    else:
        path.mkdir(exist_ok=True)
        await update.message.reply_text(f"✅ **Created:** `{name}`", parse_mode=ParseMode.MARKDOWN)
    try:
        await _switch_project(path, update.message, context)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error setting directory: {e}")
    return ConversationHandler.END
