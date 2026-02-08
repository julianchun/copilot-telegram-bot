import os
import shutil
import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from datetime import timedelta, datetime
from pathlib import Path
from typing import Optional, List, Callable, Any, Dict

from copilot import CopilotClient
from copilot.generated.session_events import SessionEventType

from src.config import WORKSPACE_PATH
from src.core.context import ctx
from src.core.tools import list_files, read_file
from src.core.git import get_git_info as _get_git_info
from src.core.filesystem import get_directory_listing, get_project_structure
from src.ui.formatters import format_tool_start, format_tool_complete, truncate_text

logger = logging.getLogger(__name__)


@dataclass
class _RequestWrapper:
    """Adapts SDK ask_user dict to an object with message/options/allowFreeform."""
    message: str = ""
    options: list = field(default_factory=list)
    allowFreeform: bool = True

    def __init__(self, req_dict: dict):
        self.message = req_dict.get("question", "")
        self.options = req_dict.get("choices", [])
        self.allowFreeform = req_dict.get("allowFreeform", True)


@dataclass
class SessionStats:
    """Tracks manual session statistics."""
    session_start: float = field(default_factory=time.time)
    api_time: float = 0.0
    requests: int = 0
    models: dict = field(default_factory=dict)

class CopilotService:
    def __init__(self):
        # Initialize context root
        ctx.set_root(WORKSPACE_PATH)
        
        self.client = CopilotClient({"cwd": str(ctx.root_path)})
        self.session = None
        self.session_id = str(uuid.uuid4())[:8]
        self._event_unsubscribe = None  # Track unsubscribe function for current session's event handler
        self.current_callback = None
        self.interaction_callback = None
        self.completion_callback = None
        self.last_assistant_usage = None  # Per-call usage from ASSISTANT_USAGE events
        self.last_session_usage = None  # Aggregate usage from SESSION_USAGE_INFO
        self.current_model = None  # Let Copilot choose default model
        self.user_selected_model = None  # Model explicitly chosen by user (not overwritten by usage events)
        self.current_reasoning_effort: Optional[str] = None
        self._models_cache: list = []  # Cache of model info dicts
        self._is_running = False
        self.project_selected = False # Track if a valid project is active
        self.project_name = ""  # Store current project name
        self._tool_call_names = {}  # Map tool_call_id to tool_name for COMPLETE events
        self.session_expired = False
        self.session_end_callback: Optional[Callable] = None  # Set by handler layer for notifications
        
        # Session context from SDK events (source of truth for status)
        self._sdk_reported_cwd: Optional[str] = None
        self._session_branch: Optional[str] = None
        self._session_git_root: Optional[str] = None
        self._session_repository: Optional[str] = None
        
        # Chunk queue for sequential processing (prevents out-of-order chunks)
        # Initialized lazily when needed to ensure event loop is running
        self._chunk_queue = None
        self.chunk_processor_task = None
        self._chat_lock = asyncio.Lock()
        
        # Manual Stats Tracking
        self.stats = SessionStats()

    @property
    def chunk_queue(self):
        """Lazy initialization of chunk queue to ensure event loop is running."""
        if self._chunk_queue is None:
            self._chunk_queue = asyncio.Queue()
        return self._chunk_queue

    async def set_working_directory(self, path: str):
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        
        current_root = ctx.root_path
        logger.info(f"Requested CWD change: {current_root} -> {p}")

        if str(p) != str(current_root):
            # Acquire chat lock to prevent project switch during active chat
            async with self._chat_lock:
                pass  # Just wait for any active chat to finish

            # Stop old client BEFORE reassigning to prevent orphaned subprocess
            if self._is_running:
                logger.info("Stopping old Copilot Client before CWD change...")
                await self.stop()

            ctx.set_root(p)
            # Clear session context when switching projects
            self._sdk_reported_cwd = None
            self._session_branch = None
            self._session_git_root = None
            self._session_repository = None
            
            self.client = CopilotClient({"cwd": str(p)})
            logger.info(f"CopilotClient re-initialized with CWD: {p}")

            logger.info("Starting Copilot Client with new CWD...")
            await self.start()
            # Allow SDK time to re-index workspace
            await asyncio.sleep(0.2)
            logger.info("Copilot Client restarted.")
        
        self.project_selected = True # Mark project as selected
        self.project_name = p.name  # Store project folder name
        logger.info(f"Workspace change complete: {current_root} -> {ctx.root_path}")
        return str(ctx.root_path)
        
    def get_working_directory(self) -> str:
        return str(ctx.root_path)
    
    def get_session_info(self) -> dict:
        """Return session context information from SDK events."""
        return {
            "cwd": self._sdk_reported_cwd,
            "branch": self._session_branch,
            "git_root": self._session_git_root,
            "repository": self._session_repository,
        }
    
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

    def get_usage_metadata(self) -> tuple[str, str, str]:
        """Returns (project, model, cost) tuple for footer construction."""
        try:
            # Use session context if available
            if self._sdk_reported_cwd:
                project = Path(self._sdk_reported_cwd).name
            else:
                project = self.project_name or Path(ctx.root_path).name
            
            model = "Auto"
            cost = "0.0"
            
            # Prefer last assistant usage for per-call info
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
    
    def get_usage_report(self) -> str:
        """Returns formatted usage stats using SDK-provided data."""
        # Try SDK aggregate data first
        if self.last_session_usage:
            data = self.last_session_usage
            
            # Total premium requests
            total_premium = getattr(data, 'total_premium_requests', None)
            premium_str = f"{total_premium:.1f}" if total_premium is not None else "0"
            
            # API duration
            api_duration_ms = getattr(data, 'total_api_duration_ms', None)
            api_str = f"{api_duration_ms / 1000:.1f}s" if api_duration_ms else "0.0s"
            
            # Session duration
            session_start = getattr(data, 'session_start_time', None)
            if session_start:
                elapsed = time.time() - session_start
                mins, secs = divmod(int(elapsed), 60)
                session_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            else:
                now = time.time()
                elapsed = now - self.stats.get("session_start", now)
                mins, secs = divmod(int(elapsed), 60)
                session_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            
            report = (
                f"Total usage est: {premium_str} Premium requests\n"
                f"API time spent: {api_str}\n"
                f"Total session time: {session_str}\n"
                f"Breakdown by AI model:\n"
            )
            
            # Model metrics breakdown
            model_metrics = getattr(data, 'model_metrics', None)
            if model_metrics:
                for model_name, metric in model_metrics.items():
                    requests = metric.requests
                    usage = metric.usage
                    cost_str = f"{requests.cost:.1f}" if requests.cost else "0"
                    count = int(requests.count) if requests.count else 0
                    in_tok = int(usage.input_tokens) if usage.input_tokens else 0
                    out_tok = int(usage.output_tokens) if usage.output_tokens else 0
                    cache_tok = int(usage.cache_read_tokens) if usage.cache_read_tokens else 0
                    report += (
                        f"  {model_name}: {count} requests ({cost_str}x)\n"
                        f"    Tokens: {in_tok} in / {out_tok} out / {cache_tok} cached\n"
                    )
            else:
                report += "  (No model metrics available)\n"
            
            # Quota info from last assistant usage
            if self.last_assistant_usage:
                quota_snapshots = getattr(self.last_assistant_usage, 'quota_snapshots', None)
                if quota_snapshots:
                    report += "\nQuota:\n"
                    for quota_name, snapshot in quota_snapshots.items():
                        remaining = getattr(snapshot, 'entitlement_requests', 0)
                        is_unlimited = getattr(snapshot, 'is_unlimited_entitlement', False)
                        if is_unlimited:
                            report += f"  {quota_name}: Unlimited\n"
                        else:
                            report += f"  {quota_name}: {remaining:.0f} remaining\n"
            
            return report
        
        # Fallback to manual stats
        now = time.time()
        d = timedelta(seconds=int(now - self.stats.session_start))
        session_duration = str(d)
        api_duration = f"{self.stats.api_time:.1f}s"
        requests = self.stats.requests
        
        report = (
            f"Total usage est: {requests} Premium requests\n"
            f"API time spent: {api_duration}\n"
            f"Total session time: {session_duration}\n"
            f"Breakdown by AI model:\n"
        )
        
        if not self.stats.models:
            report += "  (No interactions yet)"
        else:
            items = []
            for model, count in self.stats.models.items():
                items.append(f"  {model}: {count} requests")
            report += "\n".join(items)
        
        return report

    async def export_session_to_file(self) -> Optional[str]:
        """Exports the current session history to a markdown file using SDK get_messages()."""
        if not self.session:
            logger.warning("No active session to export")
            return None
        
        try:
            from src.ui.session_exporter import format_session_markdown
            
            # Retrieve all session events from SDK
            logger.info("📥 Retrieving session history...")
            events = await self.session.get_messages()
            
            if not events:
                logger.warning("Session has no events to export")
                return None
            
            logger.info(f"📊 Retrieved {len(events)} events")
            
            # Prepare metadata
            metadata = {
                "session_id": self.session_id,
                "start_time": ctx.session_start_time,
                "project_name": self.project_name or ctx.root_path.name,
                "current_model": self.current_model
            }
            
            # Generate markdown
            logger.info("📝 Formatting session markdown...")
            markdown_content = format_session_markdown(events, metadata)
            
            # Save to file in project root
            filename = f"copilot-telegram-bot-{self.session_id}.md"
            filepath = ctx.root_path / filename
            
            filepath.write_text(markdown_content, encoding="utf-8")
            logger.info(f"✅ Session exported to: {filepath}")
            
            return str(filepath)
            
        except Exception as e:
            logger.error(f"❌ Session export failed: {e}", exc_info=True)
            return None

    async def get_cli_version(self) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                "copilot --version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import re
            match = re.search(r"(\d+\.\d+\.\d+)", stdout.decode())
            return match.group(1) if match else "0.0.400"
        except Exception:
            return "0.0.400"

    async def get_auth_status(self) -> str:
        if not self._is_running:
             await self.start()
        try:
            status = await self.client.get_auth_status()
            logger.debug(f"Auth Check: {status}")
            return status.login if hasattr(status, 'login') else "User"
        except Exception as e:
            return "User"

    async def get_git_info(self) -> str:
        """Get git info - delegates to core.git module."""
        return await _get_git_info(self._session_branch, self._sdk_reported_cwd)

    async def start(self):
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

    async def _create_session(self):
        logger.info(f"Creating new session.")
        
        _TOOL_ALLOWLIST = {"report_intent", "task", "list_files", "read_file"}

        async def permission_bridge(input, invocation):
            tool_name = input.get('toolName', 'unknown')
            tool_args = input.get('arguments', {})
            
            # Ask user for permission via interaction callback
            if not self.interaction_callback:
                logger.warning(f"🟡 No interaction_callback, auto-approving: {tool_name}")
                return {"permissionDecision": "allow"}
            
            try:
                logger.info(f"🔔 Requesting user permission for tool: {tool_name}")
                
                # Create permission request wrapper
                class PermissionRequest:
                    def __init__(self, name, args):
                        self.tool_name = name
                        self.arguments = args
                
                request = PermissionRequest(tool_name, tool_args)
                
                # Ask user with 60s timeout
                result = await asyncio.wait_for(
                    self.interaction_callback("permission", request),
                    timeout=60.0
                )
                
                # Callback returns boolean: True for allow, False for deny
                decision = "allow" if result else "deny"
                logger.info(f"{'✅' if decision == 'allow' else '❌'} User {decision}ed tool: {tool_name}")
                return {"permissionDecision": decision}
                
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Permission request timeout, denying: {tool_name}")
                return {"permissionDecision": "deny"}
            except Exception as e:
                logger.error(f"❌ Permission request failed: {e}", exc_info=True)
                return {"permissionDecision": "deny"}
            
        async def user_input_bridge(request, invocation=None):
            """Bridge between SDK's ask_user format and Telegram interaction_callback."""
            question = request.get("question", "")
            choices = request.get("choices", [])
            allow_freeform = request.get("allowFreeform", True)
            
            logger.info(f"🔔 user_input_bridge called | Question: '{question[:60]}...' | Choices: {choices} | Callback exists: {self.interaction_callback is not None}")
            
            try:
                if not self.interaction_callback:
                    logger.error("❌ No interaction_callback registered!")
                    return {"answer": "", "wasFreeform": False}
                
                wrapped = _RequestWrapper(request)
                
                # Add timeout to prevent infinite wait
                logger.info(f"⏳ Calling interaction_callback with 300s timeout...")
                result = await asyncio.wait_for(
                    self.interaction_callback("input", wrapped),
                    timeout=300.0  # 5 minutes to match INTERACTION_TTL
                )
                logger.info(f"✅ interaction_callback returned: {result}")
                
                # Transform result from string to SDK expected dict format
                was_cancel = (result == "cancel" or not result)
                was_freeform = allow_freeform and (not choices or result not in choices)
                
                response = {
                    "answer": result if not was_cancel else "",
                    "wasFreeform": was_freeform
                }
                logger.info(f"📤 Returning to SDK: {response}")
                return response
                
            except asyncio.TimeoutError:
                logger.error(f"⏱️ user_input_bridge timed out after 300s")
                return {"answer": "", "wasFreeform": False}
            except Exception as e:
                logger.error(f"❌ user_input_bridge failed: {e}", exc_info=True)
                return {"answer": "", "wasFreeform": False}

        session_config = {
            "model": self.current_model,
            "streaming": True,
            "tools": [list_files, read_file],
            "hooks": {
                "on_pre_tool_use": permission_bridge,
                "on_session_end": self._on_session_end,
            },
            "on_user_input_request": user_input_bridge,
            "system_message": {
                "mode": "append",
                "content": (
                    "You are assisting via a Telegram bot. "
                    "Respond concisely and use Telegram-compatible Markdown. "
                    "Use single backticks for inline code, triple backticks for code blocks. "
                    "Avoid HTML tags. Keep responses focused and actionable."
                ),
            },
        }
        if self.current_reasoning_effort:
            session_config["reasoning_effort"] = self.current_reasoning_effort

        self.session = await self.client.create_session(session_config)
        
        # Capture session context immediately after creation
        # The SESSION_START event has already fired, so query the session's messages
        try:
            messages = await self.session.get_messages()
            if messages and len(messages) > 0:
                first_event = messages[0]
                if first_event.type.value == "session.start" and hasattr(first_event.data, 'context'):
                    context = first_event.data.context
                    if context and not isinstance(context, str):
                        self._sdk_reported_cwd = getattr(context, 'cwd', None)
                        self._session_branch = getattr(context, 'branch', None)
                        self._session_git_root = getattr(context, 'git_root', None)
                        self._session_repository = getattr(context, 'repository', None)
                        logger.info(f"📍 Session context captured from session.start event - "
                                   f"CWD: {self._sdk_reported_cwd}, Branch: {self._session_branch}, "
                                   f"Git Root: {self._session_git_root}")
            logger.info(f"logger message: {messages}")
        except Exception as e:
            logger.warning(f"Could not retrieve session context from messages: {e}")
        
        # session.on() returns an unsubscribe callback - track it to clean up later
        self._event_unsubscribe = self.session.on(self._handle_event)
        self.session_expired = False
        ctx.clear_tracked_files()
        ctx.session_start_time = datetime.now()
        
        self.stats = SessionStats()
        
        logger.info("Session created.")
    
    async def _on_session_end(self, input_data, invocation):
        """Hook called by SDK when session ends (timeout, error, etc.)."""
        reason = input_data.get("reason", "unknown")
        error = input_data.get("error")
        logger.info(f"📛 Session ended | reason={reason} error={error}")
        
        if reason in ("timeout", "error"):
            self.session_expired = True
            if self.session_end_callback:
                try:
                    msg = f"⚠️ Session expired ({reason}). Use /start to begin a new session."
                    if error:
                        msg += f"\nError: {error}"
                    await self.session_end_callback(msg)
                except Exception as e:
                    logger.error(f"❌ Failed to send session end notification: {e}")
        return None

    async def reset_session(self, model: Optional[str] = None):
        if model:
            self.current_model = model
            self.user_selected_model = model
        logger.info("Resetting session...")
        
        self.cleanup_temp_dir()
        self.session_id = str(uuid.uuid4())[:8]
        self._tool_call_names.clear()
        self.last_session_usage = None
        self.last_assistant_usage = None
        
        # Unsubscribe from old event handler before destroying session
        if self._event_unsubscribe:
            try:
                self._event_unsubscribe()
            except Exception as e:
                logger.warning(f"Failed to unsubscribe during reset: {e}")
        
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
        if reasoning_effort is not None:
            self.current_reasoning_effort = reasoning_effort
        
        self.current_model = model
        self.user_selected_model = model
        logger.info(f"🔄 Changing model to {model} (will reset session)")
        
        # Reset the session with the new model
        await self.reset_session(model)

    async def stop(self):
        logger.info("Stopping Copilot Client...")
        self.cleanup_temp_dir()
        
        # Unsubscribe from event handler before destroying session
        if self._event_unsubscribe:
            try:
                self._event_unsubscribe()
            except Exception as e:
                logger.warning(f"Failed to unsubscribe during stop: {e}")
        
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

    async def get_available_models(self) -> List[Dict[str, str]]:
        if not self._is_running:
             await self.start()
        try:
            models = await self.client.list_models()
            results = []
            for m in models:
                mid = str(m.id) if hasattr(m, 'id') else str(m)
                # Extract multiplier from billing.multiplier
                mult = "1x"
                if hasattr(m, 'billing') and hasattr(m.billing, 'multiplier'):
                    multiplier_val = m.billing.multiplier
                    # Format: remove trailing .0 for whole numbers
                    if isinstance(multiplier_val, (int, float)):
                        if multiplier_val == int(multiplier_val):
                            mult = f"{int(multiplier_val)}x"
                        else:
                            mult = f"{multiplier_val}x"
                    else:
                        mult = f"{multiplier_val}x"
                # Reasoning effort support
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
            return results
        except Exception as e:
            logger.error(f"Failed to fetch models: {e}")
            return []

    async def get_project_info_header(self, context_user_data: dict = None) -> str:
        """Build rich project info header with model, mode, path, branch, and structure."""
        import os
        
        # Model info
        model = self.user_selected_model or self.current_model or "Auto"
        
        # Mode
        mode = "Plan" if (context_user_data and context_user_data.get('plan_mode')) else "Chat"
        
        # Path with tilde collapse
        path_str = str(ctx.root_path).replace(os.path.expanduser("~"), "~")
        
        # Git branch
        git_info = await self.get_git_info()
        branch_line = f"🔀 Branch: `{git_info[1:]}`\n" if git_info else ""
        
        # Structure
        tree = self.get_project_structure()
        
        header = (
            f"🤖 Model: `{model}`\n"
            f"⚙️ Mode: {mode}\n"
            f"📂 Path: `{path_str}`\n"
            f"{branch_line}"
            f"📂 Structure:\n```\n{tree}\n```"
        )
        return header

    def get_directory_listing(self) -> str:
        """Returns flat list of current directory content."""
        return get_directory_listing(self._sdk_reported_cwd)

    def get_project_structure(self, max_depth=2, limit=30) -> str:
        """Returns nested project structure with file sizes."""
        return get_project_structure(self._sdk_reported_cwd, max_depth, limit)

    async def chat(self, user_message: str, 
                  content_callback: Optional[Callable[[str], Any]] = None,
                  status_callback: Optional[Callable[[str], Any]] = None,
                  interaction_callback: Optional[Callable[[str, Any], Any]] = None,
                  completion_callback: Optional[Callable[[], Any]] = None):
        """Send a message to the Copilot session and wait for completion.
        
        Callbacks:
          content_callback(chunk) — accumulates response text chunks (not streamed to UI).
          status_callback(status) — tool completion events (● prefix) trigger permanent messages.
          interaction_callback(kind, payload) — for permission/input dialogs (inline keyboards).
          completion_callback() — fires when the model finishes (SESSION_IDLE).
        """
        async with self._chat_lock:
            if not self.session:
                await self.start()
            self.current_callback = content_callback
            ctx.status_callback = status_callback
            self.interaction_callback = interaction_callback
            self.completion_callback = completion_callback
            
            # Start chunk processor if not running
            if content_callback and (not self.chunk_processor_task or self.chunk_processor_task.done()):
                self.chunk_processor_task = asyncio.create_task(self._process_chunks())
            
            start_t = time.time()
            
            try:
                # Use 300s timeout to allow for user interactions (ask_user tool)
                await self.session.send_and_wait({"prompt": user_message}, timeout=300.0)
            finally:
                duration = time.time() - start_t
                self.stats.api_time += duration
                self.stats.requests += 1
                model = self.current_model
                self.stats.models[model] = self.stats.models.get(model, 0) + 1
                
                # Signal chunk processor to stop and wait BEFORE clearing callbacks
                # so late chunks still have a valid callback to deliver to
                if self.chunk_processor_task and not self.chunk_processor_task.done():
                    try:
                        await self.chunk_queue.put(None)  # Sentinel to stop processor
                        await asyncio.wait_for(self.chunk_processor_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        self.chunk_processor_task.cancel()
                    except Exception as e:
                        logger.error(f"Error stopping chunk processor: {e}")
                
                # Now safe to clear callbacks after processor has drained
                self.current_callback = None
                ctx.status_callback = None
                self.interaction_callback = None
                self.completion_callback = None

    async def _process_chunks(self):
        """Process streaming chunks sequentially from queue to ensure correct order."""
        try:
            while True:
                chunk = await self.chunk_queue.get()
                if chunk is None:  # Sentinel value to stop
                    break
                
                if self.current_callback:
                    try:
                        if asyncio.iscoroutinefunction(self.current_callback):
                            await self.current_callback(chunk)
                        else:
                            self.current_callback(chunk)
                    except Exception as e:
                        logger.error(f"Chunk processing error: {e}", exc_info=True)
                
                self.chunk_queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Chunk processor error: {e}", exc_info=True)

    def _handle_event(self, event):
        """Route SDK events to per-type handler methods."""
        handler_map = {
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
        handler = handler_map.get(event.type)
        if handler:
            handler(event)

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
        logger.info("Session IDLE - Copilot finished")
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
        """Reasoning deltas are internal thinking—don't send to user, only log."""
        content = getattr(event.data, 'delta_content', None) or getattr(event.data, 'content', None)
        if content:
            # Log thinking for debugging, but do NOT queue to user
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

    def _dispatch_async(self, callback, *args):
        try:
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(callback):
                loop.create_task(callback(*args))
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"Failed to dispatch async callback: {e}", exc_info=True)

# Global Singleton
service = CopilotService()
