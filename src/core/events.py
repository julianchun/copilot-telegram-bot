"""SDK event handler methods for CopilotService (mixin)."""

import asyncio
import io
import logging

from copilot.generated.session_events import SessionEventType

from src.core.context import ctx
from src.core.session_metadata import metadata_value
from src.ui.formatters import format_tool_start, format_tool_complete, truncate_text

logger = logging.getLogger(__name__)

PLAN_MSG_INLINE_LIMIT = 3000  # chars; longer plans are sent as a document


class EventHandlerMixin:
    """Mixin providing SDK event routing and per-type handler methods.

    Expects the host class to have:
      current_callback, _tool_call_names, completion_callback,
      current_model, last_assistant_usage, last_session_usage,
      telegram_bot, telegram_chat_id, _pending_exit_plan_mode
    """

    # ── Event router ──────────────────────────────────────────────────

    def _build_handler_map(self) -> dict:
        """Build the event-type → handler lookup once per instance."""
        return {
            SessionEventType.SESSION_START: self._on_session_start,
            SessionEventType.ASSISTANT_MESSAGE: self._on_assistant_message,
            SessionEventType.TOOL_EXECUTION_START: self._on_tool_start,
            SessionEventType.TOOL_EXECUTION_COMPLETE: self._on_tool_complete,
            SessionEventType.SUBAGENT_SELECTED: self._on_subagent_selected,
            SessionEventType.SUBAGENT_DESELECTED: self._on_subagent_deselected,
            SessionEventType.SUBAGENT_STARTED: self._on_subagent_started,
            SessionEventType.SUBAGENT_COMPLETED: self._on_subagent_completed,
            SessionEventType.SUBAGENT_FAILED: self._on_subagent_failed,
            SessionEventType.SESSION_IDLE: self._on_session_idle,
            SessionEventType.SESSION_ERROR: self._on_session_error,
            SessionEventType.SESSION_USAGE_INFO: self._on_session_usage_info,
            SessionEventType.ASSISTANT_USAGE: self._on_assistant_usage,
            SessionEventType.SESSION_MODE_CHANGED: self._on_session_mode_changed,
            SessionEventType.SESSION_MODEL_CHANGE: self._on_session_model_change,
            SessionEventType.ASSISTANT_REASONING_DELTA: self._on_reasoning_delta,
            SessionEventType.SESSION_COMPACTION_START: self._on_compaction_start,
            SessionEventType.SESSION_COMPACTION_COMPLETE: self._on_compaction_complete,
            SessionEventType.SESSION_CONTEXT_CHANGED: self._on_context_changed,
            SessionEventType.EXIT_PLAN_MODE_REQUESTED: self._on_exit_plan_mode_requested,
            SessionEventType.EXIT_PLAN_MODE_COMPLETED: self._on_exit_plan_mode_completed,
        }

    def _handle_event(self, event):
        """Route SDK events to per-type handler methods."""
        try:
            handler_map = self._handler_map_cache
        except AttributeError:
            handler_map = self._handler_map_cache = self._build_handler_map()
        handler = handler_map.get(event.type)
        if handler:
            handler(event)

    # ── Per-type handlers ─────────────────────────────────────────────

    def _on_session_start(self, event):
        """Capture session context from the session.start event (via on_event)."""
        try:
            data = event.data
            self.session_info.session_id = metadata_value(data, "session_id", "sessionId")
            self.session_info.selected_model = metadata_value(data, "selected_model", "selectedModel")
            self.session_info.copilot_version = metadata_value(data, "copilot_version", "copilotVersion")
            self.session_info.producer = metadata_value(data, "producer")

            context = metadata_value(data, "context")
            if context and not isinstance(context, str):
                self.session_info.cwd = metadata_value(context, "working_directory", "cwd")
                self.session_info.branch = metadata_value(context, "branch")
                self.session_info.git_root = (
                    metadata_value(context, "git_root", "gitRoot")
                    or metadata_value(data, "git_root", "gitRoot")
                )
                self.session_info.repository = metadata_value(context, "repository")
                logger.info(
                    f"📍 Session context from session.start — "
                    f"CWD: {self.session_info.cwd}, Branch: {self.session_info.branch}"
                )

            if self.session_info.selected_model and not self.user_selected_model:
                self.current_model = self.session_info.selected_model
                logger.info(f"🤖 SDK selected model: {self.current_model}")
        except Exception as e:
            logger.warning(f"Failed to process session.start event: {e}")

    def _on_assistant_message(self, event):
        """Capture the complete assistant message (streaming is disabled)."""
        content = getattr(event.data, 'content', None)
        if content and self.current_callback:
            try:
                self._dispatch_async(self.current_callback, content)
            except Exception as e:
                logger.error(f"Failed to dispatch assistant message: {e}")

    def _on_tool_start(self, event):
        try:
            tool_name = event.data.tool_name or getattr(event.data, 'mcp_tool_name', None) or "unknown"
            args = event.data.arguments
            tool_call_id = getattr(event.data, 'tool_call_id', None)
            parent_tool_call_id = getattr(event.data, 'parent_tool_call_id', None)

            if tool_call_id and tool_name != "unknown":
                self._tool_call_names[tool_call_id] = tool_name

            logger.info(f"TOOL START: {tool_name} call_id={tool_call_id} parent={parent_tool_call_id} args={args}")

            msg = format_tool_start(tool_name, args or {})
            if parent_tool_call_id:
                msg = "  " + msg

            if ctx.status_callback:
                self._dispatch_async(ctx.status_callback, msg)
        except Exception as e:
            logger.error(f"Error handling TOOL_EXECUTION_START: {e}")

    def _on_tool_complete(self, event):
        try:
            tool_call_id = getattr(event.data, 'tool_call_id', None)
            tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'mcp_tool_name', None)
            if not tool_name and tool_call_id:
                tool_name = self._tool_call_names.get(tool_call_id, "unknown")
            if not tool_name:
                tool_name = "unknown"

            parent_tool_call_id = getattr(event.data, 'parent_tool_call_id', None)
            result = getattr(event.data, 'result', None)
            result_content = result.content if result and hasattr(result, 'content') else None

            logger.info(f"TOOL COMPLETE: {tool_name} call_id={tool_call_id} result_len={len(result_content) if result_content else 0}")

            if tool_call_id and tool_call_id in self._tool_call_names:
                del self._tool_call_names[tool_call_id]

            msg = format_tool_complete(tool_name, result_content)
            if msg and ctx.status_callback:
                if parent_tool_call_id:
                    msg = "  " + msg
                self._dispatch_async(ctx.status_callback, msg)
        except Exception as e:
            logger.error(f"Error handling TOOL_EXECUTION_COMPLETE: {e}")

    def _on_subagent_started(self, event):
        try:
            display_name = getattr(event.data, 'agent_display_name', None) or getattr(event.data, 'agent_name', 'Agent')
            msg = f"🤖 {display_name} started"
            if ctx.status_callback:
                self._dispatch_async(ctx.status_callback, msg)
            logger.info(f"SUBAGENT STARTED: {display_name}")
        except Exception as e:
            logger.error(f"Error handling SUBAGENT_STARTED: {e}")

    def _on_subagent_completed(self, event):
        try:
            display_name = getattr(event.data, 'agent_display_name', None) or getattr(event.data, 'agent_name', 'Agent')
            result = getattr(event.data, 'result', None)
            result_content = result.content if result and hasattr(result, 'content') else None
            if result_content:
                msg = f"✓ {display_name} → {truncate_text(result_content, 100)}"
            else:
                msg = f"✓ {display_name} completed"
            if ctx.status_callback:
                self._dispatch_async(ctx.status_callback, msg)
            logger.info(f"SUBAGENT COMPLETED: {display_name}")
        except Exception as e:
            logger.error(f"Error handling SUBAGENT_COMPLETED: {e}")

    def _on_subagent_selected(self, event):
        try:
            display_name = getattr(event.data, 'agent_display_name', None) or getattr(event.data, 'agent_name', 'Agent')
            self.current_agent = getattr(event.data, 'agent_name', None) or display_name
            if ctx.status_callback:
                self._dispatch_async(ctx.status_callback, f"🤖 Agent selected: {display_name}")
            logger.info(f"SUBAGENT SELECTED: {display_name}")
        except Exception as e:
            logger.error(f"Error handling SUBAGENT_SELECTED: {e}")

    def _on_subagent_deselected(self, event):
        try:
            self.current_agent = None
            if ctx.status_callback:
                self._dispatch_async(ctx.status_callback, "🤖 Returned to default agent")
            logger.info("SUBAGENT DESELECTED")
        except Exception as e:
            logger.error(f"Error handling SUBAGENT_DESELECTED: {e}")

    def _on_subagent_failed(self, event):
        try:
            display_name = getattr(event.data, 'agent_display_name', None) or getattr(event.data, 'agent_name', 'Agent')
            error = getattr(event.data, 'error', None) or "Unknown error"
            msg = f"❌ {display_name} failed: {truncate_text(error, 100)}"
            if ctx.status_callback:
                self._dispatch_async(ctx.status_callback, msg)
            logger.error(f"SUBAGENT FAILED: {display_name}: {error}")
        except Exception as e:
            logger.error(f"Error handling SUBAGENT_FAILED: {e}")

    def _on_session_idle(self, event):
        logger.info("⏸️ Session IDLE - Copilot finished")
        # Schedule async task: refresh git info first, then fire callbacks
        self._dispatch_async(self._finalize_session_idle)

    async def _finalize_session_idle(self):
        """Await git info refresh, then fire status/completion callbacks."""
        await self._refresh_git_info()
        if ctx.status_callback:
            if asyncio.iscoroutinefunction(ctx.status_callback):
                await ctx.status_callback("")
            else:
                ctx.status_callback("")
        if self.completion_callback:
            if asyncio.iscoroutinefunction(self.completion_callback):
                await self.completion_callback()
            else:
                self.completion_callback()

    def _on_session_error(self, event):
        error_msg = getattr(event.data, 'message', None) or str(event.data)
        logger.error(f"❌ Session error event: {error_msg}")
        if ctx.status_callback:
            self._dispatch_async(ctx.status_callback, f"❌ Session error: {error_msg}")

    def _on_session_usage_info(self, event):
        self.last_session_usage = event.data
        logger.info(f"Session Usage Info Received: {event.data}")

    def _on_assistant_usage(self, event):
        self.last_assistant_usage = event.data
        if hasattr(event.data, 'model') and event.data.model:
            self.current_model = event.data.model
            logger.info(f"Model from usage event: {self.current_model}")
        logger.info(f"Assistant Usage Received: {event.data}")

    def _on_session_mode_changed(self, event):
        new_mode = getattr(event.data, 'new_mode', None)
        if new_mode:
            self.current_mode = getattr(new_mode, "value", new_mode)
            logger.info(f"Session mode changed to: {self.current_mode}")
        else:
            logger.info("Session mode changed event received without new_mode field")

    def _on_session_model_change(self, event):
        new_model = getattr(event.data, 'new_model', None)
        if new_model:
            self.current_model = new_model
            logger.info(f"Session model changed to: {new_model}")
        else:
            logger.info("Session model change event received without new_model field")

    def _on_reasoning_delta(self, event):
        """Reasoning deltas are internal thinking — don't send to user, only log."""
        content = getattr(event.data, 'delta_content', None) or getattr(event.data, 'content', None)
        if content:
            logger.debug(f"🧠 Reasoning: {truncate_text(content, 200)}")

    def _on_compaction_start(self, event):
        logger.info("📦 Session compaction started")
        if ctx.status_callback:
            self._dispatch_async(ctx.status_callback, "📦 Context compaction in progress...")

    def _on_compaction_complete(self, event):
        success = getattr(event.data, 'success', None)
        status = "✅" if success else "⚠️"
        logger.info(f"📦 Session compaction complete (success={success})")
        if ctx.status_callback:
            self._dispatch_async(ctx.status_callback, f"{status} Context compaction complete")

    def _on_context_changed(self, event):
        """Update usage tracker with context window data from SDK event."""
        try:
            token_count = getattr(event.data, 'token_count', None)
            max_tokens = getattr(event.data, 'max_tokens', None)
            if token_count is not None:
                self.usage_tracker.current_tokens = int(token_count)
            if max_tokens is not None:
                self.usage_tracker.token_limit = int(max_tokens)
            logger.debug(f"📊 Context changed: {token_count}/{max_tokens} tokens")
        except Exception as e:
            logger.debug(f"Context changed event handling failed: {e}")

    def _on_exit_plan_mode_requested(self, event):
        """Agent finished creating a plan and wants user approval to exit plan mode."""
        logger.info("📋 exit_plan_mode.requested received")
        self._dispatch_async(self._finalize_exit_plan_mode_requested, event.data)

    async def _finalize_exit_plan_mode_requested(self, data):
        """Send plan approval UI to Telegram user."""
        from src.ui.menus import get_exit_plan_mode_keyboard

        bot = getattr(self, 'telegram_bot', None)
        chat_id = getattr(self, 'telegram_chat_id', None)
        if not bot or not chat_id:
            logger.warning("📋 exit_plan_mode.requested: no bot/chat_id stored, cannot notify user")
            return

        try:
            request_id = data.request_id
            summary = data.summary
            plan_content = data.plan_content
            actions = data.actions
            recommended = data.recommended_action

            self._pending_exit_plan_mode = {
                'request_id': request_id,
                'plan_content': plan_content,
                'summary': summary,
                'actions': actions,
                'recommended_action': recommended,
            }

            keyboard = get_exit_plan_mode_keyboard(request_id)
            header = "📋 Plan ready for review"
            if recommended:
                recommended_display = getattr(recommended, "value", str(recommended))
                header += f" (recommended: {recommended_display})"
            if actions:
                action_labels = [getattr(action, "value", str(action)) for action in actions]
                header += f"\nActions: {', '.join(action_labels)}"

            if plan_content and len(plan_content) <= PLAN_MSG_INLINE_LIMIT:
                msg_text = f"{header}\n\nSummary: {summary}\n\n{plan_content}"
                await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=keyboard)
            elif plan_content:
                # Plan too long — send summary inline, full content as document
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"{header}\n\nSummary: {summary}",
                    reply_markup=keyboard,
                )
                doc = io.BytesIO(plan_content.encode("utf-8"))
                doc.name = "plan.md"
                await bot.send_document(chat_id=chat_id, document=doc, caption="📋 Full plan")
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"{header}\n\nSummary: {summary}",
                    reply_markup=keyboard,
                )
        except Exception as e:
            logger.error(f"❌ Failed to send exit_plan_mode approval message: {e}", exc_info=True)

    def _on_exit_plan_mode_completed(self, event):
        """Exit plan mode request was resolved — clear pending state."""
        request_id = getattr(event.data, 'request_id', '') or ''
        logger.info(f"📋 exit_plan_mode.completed (request_id={request_id})")
        self._pending_exit_plan_mode = None

    # ── Async dispatch helper ─────────────────────────────────────────

    def _dispatch_async(self, callback, *args):
        """Fire-and-forget dispatch for async or sync callbacks."""
        try:
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(callback):
                loop.create_task(callback(*args))
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"Failed to dispatch async callback: {e}", exc_info=True)
