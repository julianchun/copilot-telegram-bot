import logging
import re
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.config import WORKSPACE_PATH
from src.core.service import service
from src.handlers.messages import PENDING_INTERACTIONS
from src.handlers.utils import security_check

logger = logging.getLogger(__name__)

WAITING_PROJECT_NAME = 1


async def _refresh_auth_info(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh auth info in context after service is started."""
    try:
        auth = await service.get_auth_status()
        context.user_data['auth'] = auth
    except Exception as e:
        logger.debug(f"Auth refresh failed, keeping existing value: {e}")


def _build_project_selected_message(context: ContextTypes.DEFAULT_TYPE, project_name: str, action: str = "Selected") -> str:
    """Build the edited start message shown after project selection/creation.
    
    Reuses version info stored in context.user_data by start_command.
    """
    auth = context.user_data.get('auth', 'Unknown')
    cli_version = context.user_data.get('cli_version', 'Unknown')
    sdk_version = context.user_data.get('sdk_version', 'Unknown')
    return (
        f"🚀 Copilot CLI-Telegram\n"
        f"User: {auth}\n"
        f"CLI version: {cli_version}\n"
        f"SDK version: {sdk_version}\n"
        f"✅ {action}: {project_name}"
    )


async def _switch_project(path: Path, message, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Common project-switching logic used by proj:, proj_granted:, and create_project_name.
    
    If `query` is provided (CallbackQuery), edits the original start message to remove the keyboard.
    """
    context.user_data['plan_mode'] = False
    await service.set_mode("general")
    await service.set_working_directory(str(path))

    # Edit the start message to remove inline keyboard and show final status
    if query:
        try:
            await _refresh_auth_info(context)
            selected_msg = _build_project_selected_message(context, path.name, "Selected")
            await query.edit_message_text(selected_msg)
        except Exception as e:
            logger.warning(f"⚠️ Failed to edit start message: {e}")

    cockpit = await service.get_cockpit_message()
    await message.reply_text(cockpit)


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
                action_text = "Allow" if value == "allow" else "Deny"
                decision_line = f"🛡️ Permission: {tool_name} → {action_text} {action_emoji}"
                await query.edit_message_text(decision_line)
            elif action_type == "input":
                logger.info(f"✅ Resolving input future with: {value}")
                future.set_result(value)
                await query.edit_message_text(f"❓ Selected: {value}")
                await query.message.reply_text(f"✅ Selected option: {value}")
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
            f"🤖 Model: {model}\n⚠️ Session will be reset (history cleared)\n\nSelect reasoning effort:",
            reply_markup=keyboard,
        )
    else:
        await service.change_model(model)
        await query.edit_message_text(f"✅ Model: {model}")


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
        f"✅ Model: {model} | Effort: {effort_display}\n",
    )


async def _handle_skill_callback(query, context):
    """Handle skill: callback queries — toggle a skill and refresh the list."""
    from src.ui.menus import get_skill_keyboard, format_skill_list
    skill_name = query.data.split(":", 1)[1]

    # Get current state to determine toggle direction
    skills = await service.list_skills()
    current = next((s for s in skills if s["name"] == skill_name), None)
    if not current:
        await query.edit_message_text(f"⚠️ Skill '{skill_name}' not found.")
        return

    new_state = not current["enabled"]
    success = await service.toggle_skill(skill_name, enable=new_state)
    if not success:
        await query.edit_message_text(f"⚠️ Failed to toggle skill '{skill_name}'.")
        return

    # Refresh the full list and update the message in-place
    skills = await service.list_skills()
    text = format_skill_list(skills)
    keyboard = get_skill_keyboard(skills)
    await query.edit_message_text(text, reply_markup=keyboard)


async def _handle_skill_reload_callback(query, context):
    """Handle skill_reload callback — reload skills from disk and refresh."""
    from src.ui.menus import get_skill_keyboard, format_skill_list
    await service.reload_skills()
    skills = await service.list_skills()
    text = format_skill_list(skills)
    if skills:
        keyboard = get_skill_keyboard(skills)
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await query.edit_message_text(text)


async def _handle_project_callback(query, context):
    """Handle proj: callback queries."""
    folder = query.data.split(":")[1]
    path = WORKSPACE_PATH / folder
    try:
        await _switch_project(path, query.message, context, query=query)
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
            await query.message.reply_text(f"⚠️ Project path does not exist: {path}")
            return
        await _switch_project(path, query.message, context, query=query)
    except Exception as e:
        logger.error(f"Granted Project Switch Failed: {e}")
        await query.message.reply_text(f"⚠️ Failed to switch project: {e}")


async def _handle_instructions_callback(query, update, context):
    """Handle instr: callback queries (view, clear, init)."""
    action = query.data.split(":")[1]

    if action == "view":
        instructions_path = Path(service.get_working_directory()) / ".github" / "copilot-instructions.md"
        if instructions_path.exists():
            content = instructions_path.read_text(encoding="utf-8").strip()
            if content:
                from src.config import TELEGRAM_MSG_LIMIT
                display = content
                if len(display) > TELEGRAM_MSG_LIMIT - 100:
                    display = display[:TELEGRAM_MSG_LIMIT - 100] + "\n... truncated"
                await query.edit_message_text(
                    f"📋 Custom Instructions\n"
                    f"─────────────────\n"
                    f"{display}"
                )
            else:
                await query.edit_message_text("📋 No custom instructions found.")
        else:
            await query.edit_message_text("📋 No custom instructions found.")

    elif action == "clear":
        instructions_path = Path(service.get_working_directory()) / ".github" / "copilot-instructions.md"
        if instructions_path.exists():
            instructions_path.unlink()
            await service.reset_session()
            await query.edit_message_text(
                "🗑️ Custom instructions cleared.\n"
                "Session reset to apply changes."
            )
        else:
            await query.edit_message_text("📋 No custom instructions to clear.")

    elif action == "init":
        await query.edit_message_text("🔍 Analyzing project to generate custom instructions...")
        from src.handlers.messages import chat_handler
        prompt = (
            "Analyze this project's structure, tech stack, conventions, and patterns. "
            "Then create a .github/copilot-instructions.md file with concise, actionable instructions "
            "that will help Copilot understand this project. Include: language/framework, "
            "coding conventions, build/test commands, project structure overview, "
            "and any important patterns. Keep it focused and under 50 lines."
        )
        await chat_handler(update, context, override_text=prompt)


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
        elif data.startswith("skill:"):
            await _handle_skill_callback(query, context)
        elif data == "skill_reload":
            await _handle_skill_reload_callback(query, context)
        elif data.startswith("instr:"):
            await _handle_instructions_callback(query, update, context)
        elif data.startswith("proj_granted:"):
            await _handle_granted_project_callback(query, context)
            return ConversationHandler.END
        elif data.startswith("proj:"):
            await _handle_project_callback(query, context)
            return ConversationHandler.END
        elif data == "proj_new":
            context.user_data['start_message_id'] = query.message.message_id
            context.user_data['start_chat_id'] = query.message.chat_id
            await query.message.reply_text("New project name:")
            return WAITING_PROJECT_NAME
    except Exception as e:
        logger.error(f"❌ Error handling button callback '{data}': {e}", exc_info=True)
    return ConversationHandler.END


async def create_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    name = re.sub(r"[^\w-]+", "_", update.message.text).strip("_")
    if not name:
        await update.message.reply_text("⚠️ Invalid name. Try again or /cancel.")
        return WAITING_PROJECT_NAME
    path = WORKSPACE_PATH / name
    already_exists = path.exists()
    if already_exists:
        await update.message.reply_text(f"⚠️ Project {name} already exists. Switched to it.")
    else:
        path.mkdir(exist_ok=True)
        await update.message.reply_text(f"✅ Created: {name}")
    try:
        await _switch_project(path, update.message, context)
        # Hide the inline keyboard on the original /start message
        start_msg_id = context.user_data.pop('start_message_id', None)
        start_chat_id = context.user_data.pop('start_chat_id', None)
        if start_msg_id and start_chat_id:
            try:
                await _refresh_auth_info(context)
                action = "Selected" if already_exists else "Created"
                selected_msg = _build_project_selected_message(context, name, action)
                await context.bot.edit_message_text(
                    chat_id=start_chat_id,
                    message_id=start_msg_id,
                    text=selected_msg,
                )
            except Exception as e:
                logger.warning(f"⚠️ Failed to edit start message: {e}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error setting directory: {e}")
    return ConversationHandler.END


async def cancel_create_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel project creation and re-show the start menu with project keyboard."""
    if not await security_check(update): return
    logger.info("Project creation cancelled, returning to start menu")
    # Clean up stored message IDs
    context.user_data.pop('start_message_id', None)
    context.user_data.pop('start_chat_id', None)
    from src.handlers.commands import build_main_menu
    msg, keyboard, sys_info = await build_main_menu()
    context.user_data['cli_version'] = sys_info[0]
    context.user_data['auth'] = sys_info[1]
    context.user_data['sdk_version'] = sys_info[2]
    await update.message.reply_text(msg, reply_markup=keyboard)
    return ConversationHandler.END


async def reject_command_during_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject slash commands (other than /cancel) during project name input."""
    if not await security_check(update): return
    await update.message.reply_text("⚠️ Please enter a project name or use /cancel to go back.")
    return WAITING_PROJECT_NAME
