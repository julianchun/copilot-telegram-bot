"""Session lifecycle methods for CopilotService (mixin)."""

import asyncio
import time
import uuid
import logging
from datetime import datetime
from typing import Optional

from src.config import (
    DEFAULT_MODEL,
    GITHUB_TOKEN,
    INTERACTION_TIMEOUT,
    PERMISSION_TIMEOUT,
)
from src.core.context import ctx
from src.core.usage import SessionUsageTracker, SessionInfo

logger = logging.getLogger(__name__)


# ── Tool allowlist (auto-approved without asking user) ────────────────

_TOOL_ALLOWLIST = frozenset({
    "report_intent", "task", "list_files", "read_file",
    "view", "glob", "grep", "fetch_copilot_cli_documentation",
    "ask_user", "update_todo", "edit"
})


class _PermissionRequest:
    """Lightweight container for tool permission request data."""
    __slots__ = ("tool_name", "arguments")

    def __init__(self, name: str, args: dict):
        self.tool_name = name
        self.arguments = args


class SessionMixin:
    """Mixin providing session lifecycle methods for CopilotService.

    Expects the host class to have:
      client, session, session_id, session_info, _is_running,
      _event_unsubscribe, _usage_unsubscribe, current_model,
      user_selected_model, current_reasoning_effort, interaction_callback,
      session_expired, session_end_callback, usage_tracker,
      _tool_call_names, _chat_lock, last_session_usage, last_assistant_usage,
      _handle_event (from EventHandlerMixin), cleanup_temp_dir
    """

    # ── Public lifecycle ──────────────────────────────────────────────

    async def start(self):
        """Start the Copilot client and create an initial session."""
        if not self._is_running:
            logger.info("Starting Copilot Client...")
            try:
                await self.client.start()
                self._is_running = True
                logger.info("Copilot Client Started.")
            except Exception as e:
                logger.error(f"Failed to start client: {e}")
                raise e
        if not self.session:
            await self._create_session()

    async def stop(self):
        """Stop the Copilot client and clean up resources."""
        logger.info("Stopping Copilot Client...")
        self.cleanup_temp_dir()
        self._unsubscribe_handlers()

        if self.session:
            try:
                await self.session.destroy()
            except Exception as e:
                logger.warning(f"Error destroying session during stop: {e}")
            self.session = None

        if self._is_running:
            try:
                errors = await asyncio.wait_for(self.client.stop(), timeout=10)
                if errors:
                    for err in errors:
                        logger.warning(f"⚠️ Client stop error: {err.message}")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Graceful stop timed out, forcing stop...")
                await self.client.force_stop()
            except Exception as e:
                logger.error(f"Error during client stop: {e}")
                try:
                    await self.client.force_stop()
                except Exception:
                    pass
            self._is_running = False

        logger.info("Copilot Client Stopped.")

    async def reset_session(self, model: Optional[str] = None):
        """Destroy the current session and create a fresh one."""
        if model:
            self.current_model = model
            self.user_selected_model = model
        logger.info("Resetting session...")

        self.cleanup_temp_dir()
        self.session_id = str(uuid.uuid4())[:8]
        self._tool_call_names.clear()
        self.last_session_usage = None
        self.last_assistant_usage = None

        # Reset session info so /session shows fresh data
        self.session_info = SessionInfo()

        self._unsubscribe_handlers()

        if self.session:
            try:
                await self.session.destroy()
            except Exception as e:
                logger.warning(f"Error destroying session: {e}")
            self.session = None

        await self._create_session()

    async def change_model(self, model: str, reasoning_effort: str = None):
        """Change the model by resetting the session (conversation history will be lost).

        Note: Session resume with model change causes duplicate events in SDK v0.1.23.
        See: https://github.com/julianchun/copilot-cli-telegram-bot/issues/2
        """
        self.current_reasoning_effort = reasoning_effort

        self.current_model = model
        self.user_selected_model = model
        logger.info(f"🔄 Changing model to {model} (will reset session)")

        await self.reset_session(model)

    async def populate_session_metadata(self):
        """Fetch session metadata (name, created, modified) from client.list_sessions()."""
        if not self.session_info.session_id:
            logger.warning("No session_id available to fetch metadata")
            return

        try:
            sessions = await self.client.list_sessions()
            meta = next(
                (s for s in sessions if getattr(s, 'sessionId', None) == self.session_info.session_id),
                None,
            )
            if meta:
                self.session_info.name = getattr(meta, 'summary', None)
                self.session_info.created = getattr(meta, 'startTime', None)
                self.session_info.modified = getattr(meta, 'modifiedTime', None)
                logger.info(f"📊 Session metadata fetched - Name: {self.session_info.name}, Created: {self.session_info.created}")
            else:
                logger.warning(f"Session {self.session_info.session_id} not found in list_sessions()")
        except Exception as e:
            logger.warning(f"Failed to fetch session metadata: {e}")

    async def resume_session_by_id(self, session_id: str):
        """Resume an existing Copilot session by ID."""
        logger.info(f"Resuming session: {session_id}")
        self.cleanup_temp_dir()
        self.session_id = str(uuid.uuid4())[:8]
        self._tool_call_names.clear()
        self.last_session_usage = None
        self.last_assistant_usage = None
        self.session_info = SessionInfo()
        self._unsubscribe_handlers()

        if self.session:
            try:
                await self.session.destroy()
            except Exception as e:
                logger.warning(f"Error destroying old session: {e}")
            self.session = None

        model = self.user_selected_model or self.current_model or DEFAULT_MODEL
        resume_config = {
            "model": model,
            "streaming": False,
            "hooks": {
                "on_pre_tool_use": self._permission_bridge,
                "on_session_end": self._on_session_end,
            },
            "on_user_input_request": self._user_input_bridge,
        }
        if self.current_reasoning_effort:
            resume_config["reasoning_effort"] = self.current_reasoning_effort

        self.session = await self.client.resume_session(session_id, resume_config)
        self.current_model = model
        logger.info(f"✅ Session resumed: {session_id}")

        self.session_info.workspace_path = str(ctx.root_path)
        self._extract_session_start_context()
        self._event_unsubscribe = self.session.on(self._handle_event)
        self.session_expired = False
        ctx.clear_tracked_files()
        ctx.session_start_time = datetime.now()
        self.usage_tracker = SessionUsageTracker()
        self.usage_tracker.session_start_time = time.time()
        if self.current_model:
            self.usage_tracker.selected_model = self.current_model
        self._usage_unsubscribe = self.session.on(self.usage_tracker.handle_event)

    # ── Session hooks ─────────────────────────────────────────────────

    async def _on_session_end(self, input_data, invocation):
        """Hook called by SDK when session ends (timeout, error, etc.)."""
        reason = input_data.get("reason", "unknown")
        error = input_data.get("error")
        logger.info(f"📛 Session ended | reason={reason} error={error}")

        self.cleanup_temp_dir()

        if reason in ("timeout", "error"):
            self.session_expired = True
            self.session_info.status = "Expired"
            if self.session_end_callback:
                try:
                    msg = f"⚠️ Session expired ({reason}). Use /start to begin a new session."
                    if error:
                        msg += f"\nError: {error}"
                    await self.session_end_callback(msg)
                except Exception as e:
                    logger.error(f"❌ Failed to send session end notification: {e}")
        return None

    # ── Internal helpers ──────────────────────────────────────────────

    def _unsubscribe_handlers(self):
        """Unsubscribe from event and usage handlers (deduplicated helper)."""
        if self._event_unsubscribe:
            try:
                self._event_unsubscribe()
            except Exception as e:
                logger.warning(f"Failed to unsubscribe event handler: {e}")
            self._event_unsubscribe = None

        if self._usage_unsubscribe:
            try:
                self._usage_unsubscribe()
            except Exception as e:
                logger.warning(f"Failed to unsubscribe usage tracker: {e}")
            self._usage_unsubscribe = None

    async def _create_session(self):
        """Create and configure a new Copilot SDK session."""
        model = self.user_selected_model or self.current_model or DEFAULT_MODEL
        logger.info(f"Creating new session with model: {model}")

        session_config = {
            "model": model,
            "streaming": False,
            "hooks": {
                "on_pre_tool_use": self._permission_bridge,
                "on_session_end": self._on_session_end,
            },
            "on_user_input_request": self._user_input_bridge,
            "system_message": {
                "mode": "append",
                "content": (
                    "You are assisting via a Telegram bot. "
                    "Respond concisely and always use Plain text. "
                    "Avoid HTML tags. Keep responses focused and actionable. "
                    "**Format:** Response must be **PLAIN TEXT** (no markdown code blocks, use simple bullets)."
                ),
            },
        }
        if self.current_reasoning_effort:
            session_config["reasoning_effort"] = self.current_reasoning_effort
        if self.infinite_sessions_enabled:
            session_config["infinite_sessions"] = {"enabled": True}

        self.session = await self.client.create_session(session_config)
        self.current_model = model
        logger.info(f"✅ Session created with model: {model}")

        # Populate initial session info with workspace details
        self.session_info.workspace_path = str(ctx.root_path)
        self._extract_session_start_context()

        # Subscribe to SDK events
        self._event_unsubscribe = self.session.on(self._handle_event)
        self.session_expired = False
        ctx.clear_tracked_files()
        ctx.session_start_time = datetime.now()

        # Reset usage tracker for new session BEFORE subscribing
        self.usage_tracker = SessionUsageTracker()
        self.usage_tracker.session_start_time = time.time()
        if self.current_model:
            self.usage_tracker.selected_model = self.current_model
        self._usage_unsubscribe = self.session.on(self.usage_tracker.handle_event)

    def _extract_session_start_context(self):
        """Capture session context from session.start event via get_messages()."""
        # Note: SESSION_START event doesn't fire reliably, so we query messages.
        # This is called synchronously after session creation — we schedule the
        # async work as a task.
        async def _extract():
            try:
                messages = await self.session.get_messages()
                if messages and len(messages) > 0:
                    first_event = messages[0]
                    if first_event.type.value == "session.start":
                        self.session_info.session_id = getattr(first_event.data, 'session_id', None)
                        self.session_info.selected_model = getattr(first_event.data, 'selected_model', None)
                        self.session_info.copilot_version = getattr(first_event.data, 'copilot_version', None)
                        self.session_info.producer = getattr(first_event.data, 'producer', None)

                        if hasattr(first_event.data, 'context'):
                            context = first_event.data.context
                            if context and not isinstance(context, str):
                                self.session_info.cwd = getattr(context, 'cwd', None)
                                self.session_info.branch = getattr(context, 'branch', None)
                                self.session_info.git_root = getattr(context, 'git_root', None)
                                self.session_info.repository = getattr(context, 'repository', None)
                                logger.info(
                                    f"📍 Session context captured from session.start - "
                                    f"CWD: {self.session_info.cwd}, Branch: {self.session_info.branch}, "
                                    f"Git Root: {self.session_info.git_root}"
                                )

                        if self.session_info.selected_model and not self.user_selected_model:
                            self.current_model = self.session_info.selected_model
                            logger.info(f"🤖 SDK selected model: {self.current_model}")
            except Exception as e:
                logger.warning(f"Could not retrieve session context from messages: {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_extract())
        except RuntimeError:
            logger.debug("No running event loop — skipping session context extraction")

    async def _permission_bridge(self, input_data, invocation):
        """Bridge between SDK on_pre_tool_use and Telegram permission UI."""
        tool_name = input_data.get('toolName', 'unknown')
        tool_args = input_data.get('arguments', {})

        # Auto-approve when allow_all_tools is enabled
        if self.allow_all_tools:
            logger.info(f"✅ Auto-approved (allow_all mode): {tool_name}")
            return {"permissionDecision": "allow"}

        # Auto-approve tools in allowlist
        if tool_name in _TOOL_ALLOWLIST:
            logger.info(f"✅ Auto-approved allowlisted tool: {tool_name}")
            return {"permissionDecision": "allow"}

        # Ask user for permission via interaction callback
        if not self.interaction_callback:
            logger.warning(f"🟡 No interaction_callback, auto-approving: {tool_name}")
            return {"permissionDecision": "allow"}

        try:
            logger.info(f"🔔 Requesting user permission for tool: {tool_name}")
            request = _PermissionRequest(tool_name, tool_args)

            result = await asyncio.wait_for(
                self.interaction_callback("permission", request),
                timeout=PERMISSION_TIMEOUT,
            )

            decision = "allow" if result else "deny"
            logger.info(f"{'✅' if decision == 'allow' else '❌'} User {decision}ed tool: {tool_name}")
            return {"permissionDecision": decision}

        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Permission request timeout, denying: {tool_name}")
            return {"permissionDecision": "deny"}
        except Exception as e:
            logger.error(f"❌ Permission request failed: {e}", exc_info=True)
            return {"permissionDecision": "deny"}

    async def _refresh_git_info(self):
        """Re-query git branch/status and update session_info (3s timeout)."""
        try:
            cwd = self.session_info.cwd or str(ctx.root_path)
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    "git rev-parse --abbrev-ref HEAD",
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=3.0,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            branch = stdout.decode().strip()
            if branch:
                if branch != self.session_info.branch:
                    logger.info(f"🔀 Git branch updated: {self.session_info.branch} → {branch}")
                self.session_info.branch = branch
        except asyncio.TimeoutError:
            logger.warning("⏱️ Git info refresh timed out (3s)")
        except Exception as e:
            logger.debug(f"Git info refresh failed: {e}")

    async def _user_input_bridge(self, request, invocation=None):
        """Bridge between SDK's ask_user format and Telegram interaction_callback."""
        question = request.get("question", "")
        choices = request.get("choices", [])
        allow_freeform = request.get("allowFreeform", True)

        logger.info(
            f"🔔 user_input_bridge called | Question: '{question[:60]}...' | "
            f"Choices: {choices} | Callback exists: {self.interaction_callback is not None}"
        )

        try:
            if not self.interaction_callback:
                logger.error("❌ No interaction_callback registered!")
                return {"answer": "", "wasFreeform": False}

            from src.core.service import _RequestWrapper
            wrapped = _RequestWrapper(request)

            logger.info(f"⏳ Calling interaction_callback with {INTERACTION_TIMEOUT}s timeout...")
            result = await asyncio.wait_for(
                self.interaction_callback("input", wrapped),
                timeout=INTERACTION_TIMEOUT,
            )
            logger.info(f"✅ interaction_callback returned: {result}")

            was_cancel = (result == "cancel" or not result)
            was_freeform = allow_freeform and (not choices or result not in choices)

            response = {
                "answer": result if not was_cancel else "",
                "wasFreeform": was_freeform,
            }
            logger.info(f"📤 Returning to SDK: {response}")
            return response

        except asyncio.TimeoutError:
            logger.error(f"⏱️ user_input_bridge timed out after {INTERACTION_TIMEOUT}s")
            return {"answer": "", "wasFreeform": False}
        except Exception as e:
            logger.error(f"❌ user_input_bridge failed: {e}", exc_info=True)
            return {"answer": "", "wasFreeform": False}
