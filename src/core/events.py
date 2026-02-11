"""SDK event handler methods for CopilotService (mixin)."""

import asyncio
import logging

from copilot.generated.session_events import SessionEventType

from src.core.context import ctx
from src.ui.formatters import format_tool_start, format_tool_complete, truncate_text

logger = logging.getLogger(__name__)


class EventHandlerMixin:
    """Mixin providing SDK event routing and per-type handler methods.

    Expects the host class to have:
      current_callback, chunk_queue, _tool_call_names, completion_callback,
      current_model, last_assistant_usage, last_session_usage
    """

    # ── Event router ──────────────────────────────────────────────────

    def _build_handler_map(self) -> dict:
        """Build the event-type → handler lookup once per instance."""
        return {
            SessionEventType.ASSISTANT_MESSAGE_DELTA: self._on_assistant_delta,
            SessionEventType.ASSISTANT_MESSAGE: self._on_assistant_message,
            SessionEventType.TOOL_EXECUTION_START: self._on_tool_start,
            SessionEventType.TOOL_EXECUTION_COMPLETE: self._on_tool_complete,
            SessionEventType.SUBAGENT_STARTED: self._on_subagent_started,
            SessionEventType.SUBAGENT_COMPLETED: self._on_subagent_completed,
            SessionEventType.SESSION_IDLE: self._on_session_idle,
            SessionEventType.SESSION_ERROR: self._on_session_error,
            SessionEventType.SESSION_USAGE_INFO: self._on_session_usage_info,
            SessionEventType.ASSISTANT_USAGE: self._on_assistant_usage,
            SessionEventType.ASSISTANT_REASONING_DELTA: self._on_reasoning_delta,
            SessionEventType.SESSION_COMPACTION_START: self._on_compaction_start,
            SessionEventType.SESSION_COMPACTION_COMPLETE: self._on_compaction_complete,
        }

    def _handle_event(self, event):
        """Route SDK events to per-type handler methods."""
        if not hasattr(self, '_handler_map_cache'):
            self._handler_map_cache = self._build_handler_map()
        handler = self._handler_map_cache.get(event.type)
        if handler:
            handler(event)

    # ── Per-type handlers ─────────────────────────────────────────────

    def _on_assistant_delta(self, event):
        if self.current_callback:
            content = event.data.delta_content
            if content:
                try:
                    self.chunk_queue.put_nowait(content)
                except asyncio.QueueFull:
                    logger.warning("Chunk queue full, dropping chunk")
                except Exception as e:
                    logger.error(f"Failed to queue chunk: {e}")

    def _on_assistant_message(self, event):
        logger.debug("Skipping ASSISTANT_MESSAGE event (using DELTA events instead)")

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

    def _on_session_idle(self, event):
        logger.info("⏸️ Session IDLE - Copilot finished")
        if ctx.status_callback:
            self._dispatch_async(ctx.status_callback, "")
        if self.completion_callback:
            self._dispatch_async(self.completion_callback)

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
