"""CopilotService — main orchestrator for the Copilot SDK integration.

Event handling lives in events.py (EventHandlerMixin).
Session lifecycle lives in session.py (SessionMixin).
"""

import os
import shutil
import asyncio
import re
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Callable, Any, Dict

from copilot import CopilotClient, SubprocessConfig

from src.config import (
    WORKSPACE_PATH,
    GITHUB_TOKEN,
    DEFAULT_MODEL,
    INTERACTION_TIMEOUT,
)
from src.core.context import ctx
from src.core.git import get_git_info as _get_git_info
from src.core.filesystem import get_directory_listing, get_project_structure, get_project_stats
from src.core.usage import SessionUsageTracker, SessionInfo
from src.core.events import EventHandlerMixin
from src.core.session import SessionMixin

logger = logging.getLogger(__name__)


class _RequestWrapper:
    """Adapts SDK ask_user dict to an object with message/options/allowFreeform."""

    def __init__(self, req_dict: dict):
        self.message: str = req_dict.get("question", "")
        self.options: list = req_dict.get("choices", [])
        self.allowFreeform: bool = req_dict.get("allowFreeform", True)


class CopilotService(EventHandlerMixin, SessionMixin):
    """Singleton service wrapping the Copilot SDK client.

    Inherits:
      EventHandlerMixin  — SDK event routing (_handle_event, _on_* methods)
      SessionMixin       — lifecycle (start, stop, reset_session, change_model, etc.)
    """

    def __init__(self):
        # Initialize context root
        ctx.set_root(WORKSPACE_PATH)

        self.client = CopilotClient(SubprocessConfig(
            cwd=str(ctx.root_path),
            github_token=GITHUB_TOKEN or None,
        ))

        self.session = None  # type: ignore[assignment]
        self.session_id: str = str(uuid.uuid4())[:8]
        self._usage_unsubscribe: Optional[Callable] = None
        self.current_callback: Optional[Callable] = None
        self.interaction_callback: Optional[Callable] = None
        self.completion_callback: Optional[Callable] = None
        self.last_assistant_usage: Any = None
        self.last_session_usage: Any = None
        self.current_model: Optional[str] = DEFAULT_MODEL
        self.user_selected_model: Optional[str] = None
        self.current_reasoning_effort: Optional[str] = None
        self._models_cache: List[Dict[str, Any]] = []
        self._context_limits_cache: Dict[str, int] = {}
        self._is_running: bool = False
        self.project_selected: bool = False
        self.project_name: str = ""
        self._tool_call_names: Dict[str, str] = {}
        self.session_expired: bool = False
        self.session_end_callback: Optional[Callable[[str], Any]] = None

        # Session info from SDK events (single source of truth)
        self.session_info = SessionInfo()

        self._chat_lock = asyncio.Lock()
        self._cancelled = False  # Set by /cancel to signal abort to chat_handler

        # Usage tracking (accumulates from SDK events)
        self.usage_tracker = SessionUsageTracker()

    # ── Working directory ─────────────────────────────────────────────

    async def set_working_directory(self, path: str) -> str:
        """Switch the Copilot client to a new working directory.

        Restarts the client process so the SDK picks up the new CWD.
        """
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")

        current_root = ctx.root_path
        logger.info(f"📂 Requested CWD change: {current_root} -> {p}")

        if str(p) != str(current_root) or self.session_expired or not self.session:
            # Full client restart: CWD changed, session died, or session missing
            if str(p) != str(current_root):
                reason = "CWD change"
            elif self.session_expired:
                reason = "session recovery"
            else:
                reason = "missing session"
            logger.info(f"🔄 Full client restart ({reason}): {current_root} -> {p}")

            # Wait for any active chat to finish
            async with self._chat_lock:
                pass

            if self._is_running:
                logger.info("Stopping old Copilot Client...")
                await self.stop()

            ctx.set_root(p)
            self.session_info = SessionInfo()

            self.client = CopilotClient(SubprocessConfig(
                cwd=str(p),
                github_token=GITHUB_TOKEN or None,
            ))
            logger.info(f"🔄 CopilotClient re-initialized with CWD: {p}")

            logger.info("Starting Copilot Client with new CWD...")
            await self.start()
            await asyncio.sleep(0.2)
            logger.info("✅ Copilot Client restarted.")

        self.project_selected = True
        self.project_name = p.name
        logger.info(f"Workspace change complete: {current_root} -> {ctx.root_path}")
        return str(ctx.root_path)

    def get_working_directory(self) -> str:
        return str(ctx.root_path)

    # ── Session info helpers ──────────────────────────────────────────

    def get_session_info(self) -> SessionInfo:
        """Return session context information from SDK events."""
        return self.session_info

    def get_temp_dir(self) -> Path:
        """Returns path to the session's temp dir, creating it if needed."""
        p = ctx.root_path / f".tmp-{self.session_id}"
        if not p.exists():
            p.mkdir(exist_ok=True)
        return p

    def cleanup_temp_dir(self):
        p = ctx.root_path / f".tmp-{self.session_id}"
        if p.exists():
            try:
                shutil.rmtree(p)
                logger.info(f"Cleaned up temp dir: {p}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")

    # ── Usage / metadata ──────────────────────────────────────────────

    def get_usage_metadata(self) -> tuple[str, str, str]:
        """Returns (project, model, cost) tuple for footer construction."""
        try:
            if self.session_info.cwd:
                project = Path(self.session_info.cwd).name
            else:
                project = self.project_name or Path(ctx.root_path).name

            model = "Auto"
            cost = "0.0"

            if self.last_assistant_usage:
                if hasattr(self.last_assistant_usage, 'model') and self.last_assistant_usage.model:
                    model = self.last_assistant_usage.model
                elif self.current_model:
                    model = self.current_model
                if hasattr(self.last_assistant_usage, 'cost') and self.last_assistant_usage.cost is not None:
                    cost = f"{self.last_assistant_usage.cost:.2f}"
            elif self.current_model:
                model = self.current_model

            return project, model, cost
        except Exception as e:
            logger.error(f"get_usage_metadata failed: {e}")
            return "Unknown", "Auto", "0.0"

    async def get_usage_report(self) -> str:
        """Returns formatted usage stats from the accumulated SessionUsageTracker."""
        return await self.usage_tracker.get_usage_summary()

    # ── Session export ────────────────────────────────────────────────

    async def export_session_to_file(self) -> Optional[str]:
        """Exports the current session history to a markdown file using SDK get_messages()."""
        if not self.session:
            logger.warning("No active session to export")
            return None

        try:
            from src.ui.session_exporter import format_session_markdown

            logger.info("📥 Retrieving session history...")
            events = await self.session.get_messages()

            if not events:
                logger.warning("Session has no events to export")
                return None

            logger.info(f"📊 Retrieved {len(events)} events")

            metadata = {
                "session_id": self.session_id,
                "start_time": ctx.session_start_time,
                "project_name": self.project_name or ctx.root_path.name,
                "current_model": self.current_model,
            }

            logger.info("📝 Formatting session markdown...")
            markdown_content = format_session_markdown(events, metadata)

            filename = f"copilot-telegram-bot-{self.session_id}.md"
            filepath = ctx.root_path / filename

            filepath.write_text(markdown_content, encoding="utf-8")
            logger.info(f"✅ Session exported to: {filepath}")

            return str(filepath)

        except Exception as e:
            logger.error(f"❌ Session export failed: {e}", exc_info=True)
            return None

    # ── CLI / auth helpers ────────────────────────────────────────────

    async def get_cli_version(self) -> str:
        """Get Copilot CLI version from SDK status, with shell fallback."""
        try:
            status = await self.client.get_status()
            if hasattr(status, 'version') and status.version:
                return status.version
        except Exception as e:
            logger.debug(f"SDK get_status() failed: {e}")

        # Shell fallback
        try:
            proc = await asyncio.create_subprocess_shell(
                "copilot --version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            match = re.search(r"(\d+\.\d+\.\d+)", stdout.decode())
            if match:
                return match.group(1)
        except Exception:
            pass
        return "unknown"

    async def get_auth_status(self) -> str:
        if not self._is_running:
            await self.start()
        try:
            status = await self.client.get_auth_status()
            logger.debug(f"Auth Check: {status}")
            return status.login if hasattr(status, 'login') else "User"
        except Exception:
            return "User"

    async def get_git_info(self) -> str:
        """Get git info — delegates to core.git module."""
        return await _get_git_info(self.session_info.branch, self.session_info.cwd)

    # ── Models ────────────────────────────────────────────────────────

    async def get_available_models(self) -> List[Dict[str, str]]:
        if not self._is_running:
            await self.start()
        try:
            models = await self.client.list_models()
            results = []
            for m in models:
                mid = str(m.id) if hasattr(m, 'id') else str(m)
                mult = "1x"
                if hasattr(m, 'billing') and hasattr(m.billing, 'multiplier'):
                    multiplier_val = m.billing.multiplier
                    if isinstance(multiplier_val, (int, float)):
                        if multiplier_val == int(multiplier_val):
                            mult = f"{int(multiplier_val)}x"
                        else:
                            mult = f"{multiplier_val}x"
                    else:
                        mult = f"{multiplier_val}x"

                # Cache context window limit from SDK capabilities
                if hasattr(m, 'capabilities') and hasattr(m.capabilities, 'limits'):
                    ctx_tokens = getattr(m.capabilities.limits, 'max_context_window_tokens', None)
                    if ctx_tokens:
                        self._context_limits_cache[mid] = int(ctx_tokens)

                supports_reasoning = bool(
                    hasattr(m, 'supported_reasoning_efforts') and m.supported_reasoning_efforts
                )
                supported_efforts = getattr(m, 'supported_reasoning_efforts', []) or []
                default_effort = getattr(m, 'default_reasoning_effort', None)

                results.append({
                    "id": mid,
                    "multiplier": mult,
                    "supports_reasoning": supports_reasoning,
                    "supported_efforts": supported_efforts,
                    "default_effort": default_effort,
                })
            self._models_cache = results
            logger.info(f"📊 Cached context limits for {len(self._context_limits_cache)} models")
            return results
        except Exception as e:
            logger.error(f"Failed to fetch models: {e}")
            return []

    def get_model_context_limit(self, model_name: str) -> int:
        """Return context window size for a model from cached SDK data."""
        DEFAULT_CONTEXT_LIMIT = 128_000
        if not model_name:
            return DEFAULT_CONTEXT_LIMIT
        # Exact match first
        if model_name in self._context_limits_cache:
            return self._context_limits_cache[model_name]
        # Substring match (e.g., "claude" matches "claude-sonnet-4")
        name_lower = model_name.lower()
        for key, limit in self._context_limits_cache.items():
            if name_lower in key.lower() or key.lower() in name_lower:
                return limit
        return DEFAULT_CONTEXT_LIMIT

    # ── Project info ──────────────────────────────────────────────────

    async def get_project_info_header(self, context_user_data: Optional[dict] = None) -> str:
        """Build rich project info header with model, mode, path, branch, and structure."""
        model = self.user_selected_model or self.current_model or "Auto"
        mode = "Plan" if (context_user_data and context_user_data.get('plan_mode')) else "Chat"
        path_str = str(ctx.root_path).replace(os.path.expanduser("~"), "~")
        git_info = await self.get_git_info()
        branch_line = f"🔀 Branch: {git_info[1:]}\n" if git_info else ""
        tree = self.get_project_structure()

        header = (
            f"🤖 Model: {model}\n"
            f"⚙️ Mode: {mode}\n"
            f"📂 Path: {path_str}\n"
            f"{branch_line}"
            f"📂 Structure:\n{tree}"
        )
        return header

    async def get_cockpit_message(self, context_user_data: Optional[dict] = None) -> str:
        """Build the cockpit message shown after project selection."""
        from src.ui.menus import get_cockpit_content
        model = self.user_selected_model or self.current_model or "Auto"
        mode = "Plan" if (context_user_data and context_user_data.get('plan_mode')) else "Chat"
        path_str = str(ctx.root_path).replace(os.path.expanduser("~"), "~")
        git_info = await self.get_git_info()
        branch = git_info[1:] if git_info else ""
        file_count, folder_count = get_project_stats(self.session_info.cwd)
        return get_cockpit_content(
            project_name=self.project_name or Path(self.session_info.cwd).name,
            model=model,
            mode=mode,
            path=path_str,
            branch=branch,
            file_count=file_count,
            folder_count=folder_count,
        )

    def get_directory_listing(self) -> str:
        """Returns flat list of current directory content."""
        return get_directory_listing(self.session_info.cwd)

    def get_project_structure(self, max_depth: int = 2) -> str:
        """Returns nested project structure with file sizes."""
        return get_project_structure(self.session_info.cwd, max_depth)

    # ── Chat ──────────────────────────────────────────────────────────

    async def chat(
        self,
        user_message: str,
        content_callback: Optional[Callable[[str], Any]] = None,
        status_callback: Optional[Callable[[str], Any]] = None,
        interaction_callback: Optional[Callable[[str, Any], Any]] = None,
        completion_callback: Optional[Callable[[], Any]] = None,
        attachments: Optional[list] = None,
    ):
        """Send a message to the Copilot session and wait for completion.

        Callbacks:
          content_callback(chunk) — accumulates response text chunks.
          status_callback(status) — tool events trigger permanent messages.
          interaction_callback(kind, payload) — for permission/input dialogs.
          completion_callback() — fires when the model finishes (SESSION_IDLE).

        Args:
          attachments — optional list of SDK attachment dicts.
        """
        async with self._chat_lock:
            self._cancelled = False
            if not self.session:
                await self.start()
            self.current_callback = content_callback
            ctx.status_callback = status_callback
            self.interaction_callback = interaction_callback
            self.completion_callback = completion_callback

            try:
                await self.session.send_and_wait(
                    user_message,
                    attachments=attachments or None,
                    timeout=INTERACTION_TIMEOUT,
                )
                # abort() causes send_and_wait to return normally once session.idle fires
                if self._cancelled:
                    raise asyncio.CancelledError("Request cancelled by user")
            finally:
                self.current_callback = None
                ctx.status_callback = None
                self.interaction_callback = None
                self.completion_callback = None


# Global Singleton
service = CopilotService()
