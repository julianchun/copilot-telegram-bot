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
    await service.set_mode("interactive")
    await service.deselect_agent()
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


def _build_project_menu(context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    from src.ui.menus import get_project_menu, get_start_splash_content

    auth = context.user_data.get("auth", "Unknown")
    cli_version = context.user_data.get("cli_version", "Unknown")
    sdk_version = context.user_data.get("sdk_version", "Unknown")
    header = get_start_splash_content(auth, cli_version, sdk_version)
    return get_project_menu(WORKSPACE_PATH, header, page=page)


async def _handle_interaction_callback(query, update, context):
    """Handle perm: and input: callback queries."""
    parts = query.data.split(":", 2)
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
        prompt = interaction_data.get("prompt", "")
        allow_freeform = interaction_data.get("allow_freeform", True)
        logger.info(f"📦 Found interaction data | Future done: {future.done() if future else 'None'} | Options: {options}")
        if action_type == "input" and value and value.isdigit() and options:
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
            elif action_type == "input_page":
                from src.ui.menus import get_input_selection_menu

                page = int(value or 0)
                text, keyboard = get_input_selection_menu(
                    prompt,
                    options,
                    interaction_id,
                    allow_freeform=allow_freeform,
                    page=page,
                )
                await query.edit_message_text(text, reply_markup=keyboard)
                return
            elif action_type == "input":
                if value == "cancel":
                    logger.info(f"❌ Cancelling input interaction {interaction_id}")
                    future.set_result("cancel")
                    await query.edit_message_text("❌ Selection cancelled.")
                    PENDING_INTERACTIONS.pop(interaction_id, None)
                    return
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
    if model == "__cancel__":
        await query.edit_message_text("❌ Model selection cancelled.")
        return
    model_info = next((m for m in service._models_cache if m["id"] == model), None)
    if model_info and model_info.get("supports_reasoning") and model_info.get("supported_efforts"):
        from src.ui.menus import get_reasoning_menu

        text, keyboard = get_reasoning_menu(
            model,
            model_info["supported_efforts"],
            default_effort=model_info.get("default_effort"),
            current_effort=service.current_reasoning_effort,
        )
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
        )
    else:
        await service.change_model(model)
        await query.edit_message_text(f"✅ Model: {model}")


async def _handle_model_page_callback(query, context):
    """Handle model_page: callback queries."""
    from src.ui.menus import get_model_menu

    page = int(query.data.split(":")[1])
    models = service._models_cache or await service.get_available_models()
    text, keyboard = get_model_menu(models, current_model=service.current_model, page=page)
    await query.edit_message_text(text, reply_markup=keyboard)


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


async def _handle_reasoning_page_callback(query, context):
    """Handle reasoning_page: callback queries."""
    from src.ui.menus import get_reasoning_menu

    _, model, page_value = query.data.split(":", 2)
    page = int(page_value)
    model_info = next((m for m in service._models_cache if m["id"] == model), None)
    if not model_info:
        models = service._models_cache or await service.get_available_models()
        model_info = next((m for m in models if m["id"] == model), None)
    if not model_info:
        await query.edit_message_text(f"⚠️ Model not found: {model}")
        return

    text, keyboard = get_reasoning_menu(
        model,
        model_info.get("supported_efforts", []),
        default_effort=model_info.get("default_effort"),
        current_effort=service.current_reasoning_effort,
        page=page,
    )
    await query.edit_message_text(text, reply_markup=keyboard)


async def _handle_agent_callback(query, context):
    """Handle agent: callback queries (agent selection keyboard)."""
    name = query.data.split(":", 1)[1]

    if name == "__reload__":
        from src.ui.menus import get_agent_menu

        agents = await service.reload_agents()
        current = await service.get_current_agent()
        try:
            from telegram.error import BadRequest
            if agents:
                text, keyboard = get_agent_menu(agents, current)
                await query.edit_message_text(text, reply_markup=keyboard)
            else:
                await query.edit_message_text("🔄 Agents reloaded. No custom agents found.")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Failed to edit agent menu: {e}")
        return

    if name == "__default__":
        if await service.deselect_agent():
            await query.edit_message_text("🤖 Switched to default (no agent)")
        else:
            await query.edit_message_text("⚠️ Failed to deselect agent")
        return

    if await service.select_agent(name):
        await query.edit_message_text(f"🤖 Agent selected: {name}")
    else:
        await query.edit_message_text(f"⚠️ Failed to select agent: {name}")


async def _handle_agent_page_callback(query, context):
    """Handle agent_page: callback queries."""
    from src.ui.menus import get_agent_menu

    page = int(query.data.split(":")[1])
    agents = await service.list_agents()
    current = await service.get_current_agent()
    if not agents:
        await query.edit_message_text("🤖 No custom agents found.")
        return

    text, keyboard = get_agent_menu(agents, current, page=page)
    await query.edit_message_text(text, reply_markup=keyboard)


async def _handle_project_selection_callback(query, context):
    """Handle projsel: callback queries."""
    from src.ui.menus import get_project_entries

    try:
        selection_index = int(query.data.split(":")[1])
        entries = get_project_entries(WORKSPACE_PATH)
        if selection_index < 0 or selection_index >= len(entries):
            await query.message.reply_text("⚠️ Invalid project selection.")
            return
        await _switch_project(entries[selection_index].path, query.message, context, query=query)
    except Exception as e:
        logger.error(f"Project Switch Failed: {e}")
        await query.message.reply_text(f"⚠️ Failed to switch project: {e}")


async def _handle_project_page_callback(query, context):
    """Handle projpage: callback queries."""
    page = int(query.data.split(":")[1])
    text, keyboard = _build_project_menu(context, page=page)
    await query.edit_message_text(text, reply_markup=keyboard)


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
        if idx < 0 or idx >= len(GRANTED_PROJECT_PATHS):
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


async def _handle_sessions_page_callback(query, context):
    """Handle sessions_page: callback queries."""
    from src.ui.menus import get_sessions_menu

    page = int(query.data.split(":")[1])
    sessions = await service.list_copilot_sessions()
    text, keyboard = get_sessions_menu(sessions, page=page)
    if keyboard:
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await query.edit_message_text(text)


def _session_value(session, *names, default=None):
    for name in names:
        if isinstance(session, dict) and name in session:
            return session[name]
        if hasattr(session, name):
            return getattr(session, name)
    return default


async def _handle_session_attach_callback(query, context):
    """Handle sessattach: callback queries."""
    target = query.data.split(":", 1)[1]
    if not target:
        await query.edit_message_text("⚠️ Invalid session selection.")
        return
    try:
        if target == "last":
            await service.attach_last_session()
        else:
            await service.attach_session(target)

        service.project_selected = True
        session_info = service.get_session_info()
        cwd = session_info.cwd or service.get_working_directory()
        if cwd:
            service.project_name = Path(cwd).name
        await service.populate_session_metadata()
        session_info = service.get_session_info()
        session_id = session_info.session_id or target
        from src.ui.menus import (
            attach_success_title,
            format_attached_session,
        )

        await query.edit_message_text(
            format_attached_session(
                session_info,
                fallback_session_id=session_id,
                fallback_cwd=cwd,
                fallback_model=service.current_model,
                prefix=attach_success_title(target),
            ),
        )
    except RuntimeError as e:
        text = str(e)
        if "request in progress" in text:
            await query.edit_message_text("⏳ Please wait — a request is in progress.")
        elif target == "last" and "no sessions" in text.lower():
            await query.edit_message_text("📭 No Copilot sessions found.")
        else:
            await query.edit_message_text(f"⚠️ Failed to attach session: {e}")
    except Exception as e:
        logger.error(f"Session attach callback failed: {e}", exc_info=True)
        await query.edit_message_text(f"⚠️ Failed to attach session: {e}")


async def _handle_session_detail_callback(query, context):
    """Handle sessdetail: callback queries."""
    session_id = query.data.split(":", 1)[1]
    if not session_id:
        await query.edit_message_text("⚠️ Invalid session selection.")
        return

    session = None
    try:
        sessions = await service.list_copilot_sessions()
        session = next(
            (
                item for item in sessions
                if _session_value(item, "sessionId", "session_id", default=None) == session_id
            ),
            None,
        )
    except Exception as e:
        logger.debug(f"Could not refresh sessions for detail view: {e}")

    if session is None:
        current = service.get_session_info()
        if current and (current.session_id == session_id or service.session_id == session_id):
            session = current

    if session is None:
        await query.edit_message_text("⚠️ Session details are no longer available.")
        return

    from src.ui.menus import format_session_detail, get_session_detail_actions

    await query.edit_message_text(
        format_session_detail(session),
        reply_markup=get_session_detail_actions(session_id),
    )


async def _handle_plan_callback(query, context):
    """Handle plan: callback queries (exit_plan_mode approval)."""
    parts = query.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    request_id = parts[2] if len(parts) > 2 else ""

    logger.info(f"📋 Plan callback: action={action} request_id={request_id}")

    pending = service._pending_exit_plan_mode
    if pending is not None and pending.get('request_id') != request_id:
        await query.answer("⚠️ This plan request is no longer active.", show_alert=True)
        return

    try:
        await query.answer()
    except Exception as e:
        logger.error(f"❌ query.answer() failed for plan callback: {e}", exc_info=True)

    if action == "approve":
        service._pending_exit_plan_mode = None
        if not service.session:
            await query.edit_message_text("⚠️ No active session. Cannot switch mode.")
            return

        success = await service.set_mode('interactive')
        if success:
            await query.edit_message_text("✅ Plan approved! Switched to interactive mode.")
        else:
            await query.edit_message_text("⚠️ Failed to approve plan: could not switch to interactive mode.")

    elif action == "reject":
        service._pending_exit_plan_mode = None
        await query.edit_message_text("❌ Plan rejected. Still in plan mode — send a message to revise.")

    elif action == "edit":
        service._pending_exit_plan_mode = None
        await query.edit_message_text(
            "📝 Plan edit requested.\n"
            "Send your feedback as a message and Copilot will revise the plan."
        )

    else:
        await query.edit_message_text(f"⚠️ Unknown plan action: {action}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update): return
    logger.info(f"🎯 button_handler ENTRY - CallbackQuery received")

    query = update.callback_query
    logger.info(f"🎯 Query data: {query.data}")

    data = query.data

    if not data.startswith("plan:"):
        try:
            await query.answer()
        except Exception as e:
            logger.error(f"❌ query.answer() failed: {e}", exc_info=True)

    try:
        if data.startswith("perm:") or data.startswith("input:") or data.startswith("input_page:"):
            await _handle_interaction_callback(query, update, context)
            return
        elif data.startswith("plan:"):
            await _handle_plan_callback(query, context)
        elif data.startswith("agent_page:"):
            await _handle_agent_page_callback(query, context)
        elif data.startswith("agent:"):
            await _handle_agent_callback(query, context)
        elif data.startswith("model_page:"):
            await _handle_model_page_callback(query, context)
        elif data.startswith("model:"):
            await _handle_model_callback(query, context)
        elif data.startswith("reasoning_page:"):
            await _handle_reasoning_page_callback(query, context)
        elif data.startswith("reasoning:"):
            await _handle_reasoning_callback(query, context)
        elif data.startswith("instr:"):
            await _handle_instructions_callback(query, update, context)
        elif data.startswith("sessions_page:"):
            await _handle_sessions_page_callback(query, context)
        elif data.startswith("sessattach:"):
            await _handle_session_attach_callback(query, context)
        elif data.startswith("sessdetail:"):
            await _handle_session_detail_callback(query, context)
        elif data.startswith("projpage:"):
            await _handle_project_page_callback(query, context)
            return ConversationHandler.END
        elif data.startswith("projsel:"):
            await _handle_project_selection_callback(query, context)
            return ConversationHandler.END
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
