import os
import shutil
import asyncio
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Optional, List, Callable, Any, Dict

from pydantic import BaseModel, Field
from copilot import CopilotClient
from copilot.tools import define_tool
from copilot.generated.session_events import SessionEventType
import logging

logger = logging.getLogger(__name__)

# --- Global Context for Tools ---
class ServiceContext:
    def __init__(self):
        self.root_path = Path(os.getcwd()).resolve()
        self.status_callback: Optional[Callable[[str], Any]] = None
        self.read_files: List[str] = []

    def set_root(self, path: Path):
        self.root_path = path.resolve()
        
    async def report_status(self, message: str):
        """Reports a completed tool step log."""
        if self.status_callback:
            if asyncio.iscoroutinefunction(self.status_callback):
                await self.status_callback(message)
            else:
                self.status_callback(message)
    
    def track_file(self, path: str):
        if path not in self.read_files:
            self.read_files.append(path)

# Singleton context instance
CONTEXT = ServiceContext()

# --- Tool Definitions ---

class ListFilesParams(BaseModel):
    path: str = Field(description="The directory path to list files from. Defaults to current directory ('.').")

@define_tool(description="List files and directories in the project.")
async def list_files(params: ListFilesParams) -> str:
    target_path = Path(params.path)
    root = CONTEXT.root_path
    
    if target_path.is_absolute():
        abs_target = target_path.resolve()
    else:
        abs_target = (root / target_path).resolve()
    
    if not str(abs_target).startswith(str(root)):
        return "Error: Access denied."
    
    try:
        items = os.listdir(abs_target)
        await CONTEXT.report_status(f"● List directory {params.path}\n  └ {len(items)} files found")
        
        formatted_items = []
        for item in items:
            if (abs_target / item).is_dir():
                formatted_items.append(f"{item}/")
            else:
                formatted_items.append(item)
        return "\n".join(sorted(formatted_items))
    except Exception as e:
        return f"Error listing files: {str(e)}"

class ReadFileParams(BaseModel):
    path: str = Field(description="The relative path of the file to read.")

@define_tool(description="Read the content of a file.")
async def read_file(params: ReadFileParams) -> str:
    target_path = Path(params.path)
    root = CONTEXT.root_path
    
    if target_path.is_absolute():
        abs_target = target_path.resolve()
    else:
        abs_target = (root / target_path).resolve()
    
    if not str(abs_target).startswith(str(root)):
        return "Error: Access denied."
        
    try:
        with open(abs_target, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            content = "".join(lines)
            
            await CONTEXT.report_status(f"● Read {params.path}\n  └ {len(lines)} lines read")
            CONTEXT.track_file(params.path)
            
            if len(content) > 100000:
                return content[:100000] + "\n... (File truncated)"
            return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

# --- Service Class ---

class CopilotService:
    MODEL_METADATA = {
        "gpt-4o": "1x",
        "claude-3.5-sonnet": "1x", 
        "o1-preview": "High",
        "o1-mini": "Low",
        "gpt-4": "1x"
    }

    def __init__(self):
        self.client = CopilotClient({"cwd": str(CONTEXT.root_path)})
        self.session = None
        self.session_id = str(uuid.uuid4())[:8]
        self.current_callback = None
        self.status_callback = None
        self.interaction_callback = None 
        self.last_usage_info = None 
        self.current_model = "gpt-4o"
        self._is_running = False
        self.project_selected = False # Track if a valid project is active
        
        # Manual Stats Tracking
        self.stats = {
            "session_start": time.time(),
            "api_time": 0.0,
            "requests": 0,
            "models": {}
        }

    async def set_working_directory(self, path: str):
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        
        current_root = CONTEXT.root_path
        logger.info(f"Requested CWD change: {current_root} -> {p}")

        if str(p) != str(current_root):
            CONTEXT.set_root(p)
            self.client = CopilotClient({"cwd": str(p)})
            logger.info(f"CopilotClient re-initialized with CWD: {p}")

            if self._is_running:
                logger.info("Restarting Copilot Client to apply new CWD...")
                await self.stop()
                await self.start()
                logger.info("Copilot Client restarted.")
        
        self.project_selected = True # Mark project as selected
        return str(CONTEXT.root_path)
        
    def get_working_directory(self) -> str:
        return str(CONTEXT.root_path)
        
    def get_temp_dir(self) -> Path:
        """Returns path to the session's temp dir, creating it if needed."""
        p = Path(CONTEXT.root_path) / f".tmp-{self.session_id}"
        if not p.exists():
            p.mkdir(exist_ok=True)
        return p
        
    def cleanup_temp_dir(self):
        p = Path(CONTEXT.root_path) / f".tmp-{self.session_id}"
        if p.exists():
            try:
                shutil.rmtree(p)
                logger.info(f"Cleaned up temp dir: {p}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")

    def get_usage_report(self) -> str:
        """Returns formatted usage stats mimicking Copilot CLI (Plain Text)."""
        now = time.time()
        d = timedelta(seconds=int(now - self.stats["session_start"]))
        session_duration = str(d)
        api_duration = f"{self.stats['api_time']:.1f}s"
        requests = self.stats["requests"]
        
        report = (
            f"Total usage est: {requests} Premium requests\n"
            f"  API time spent: {api_duration}\n"
            f"  Total session time: {session_duration}\n"
            f"  Breakdown by AI model:\n"
        )
        
        if not self.stats["models"]:
             report += f"  (No interactions yet)"
        else:
            items = []
            for model, count in self.stats["models"].items():
                items.append(f"  {model}: {count} requests")
            report += "\n".join(items)
        
        return report

    async def export_session_to_file(self) -> Optional[str]:
        """Exports the current session history to a markdown file via native /share command."""
        if not self.session:
            return None
            
        try:
            # 1. Ask Copilot to save the conversation to a file
            # We use a dummy content callback to prevent noise during the command execution
            response = await self.session.send_and_wait({"prompt": "/share"})
            
            # The response content should contain the path
            output_text = str(response.content) if hasattr(response, 'content') else str(response)
            logger.info(f"Share command output: {output_text}")
            
            # 2. Parse the output text to find the file path
            # Example: "Session shared successfully to: /tmp/copilot-session-xyz.md"
            if "successfully to:" in output_text:
                file_path = output_text.split("successfully to:")[1].strip()
                # Clean up any potential markdown backticks or extra text
                file_path = file_path.split("\n")[0].replace("`", "").strip()
                return file_path
                
            return None
            
        except Exception as e:
            logger.error(f"Native export failed: {e}")
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
        except:
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
        try:
            root = CONTEXT.root_path
            proc = await asyncio.create_subprocess_shell(
                "git rev-parse --abbrev-ref HEAD",
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            branch = stdout.decode().strip()
            if not branch: return ""
            
            proc = await asyncio.create_subprocess_shell(
                "git status --porcelain",
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            dirty = "*" if stdout.decode().strip() else ""
            return f" [⎇ {branch}{dirty}]"
        except Exception as e:
            return ""

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
        logger.info(f"Creating new session. Model: {self.current_model}")
        
        async def permission_bridge(request):
            if self.interaction_callback:
                return await self.interaction_callback("permission", request)
            return True 
            
        async def user_input_bridge(request):
            if self.interaction_callback:
                return await self.interaction_callback("input", request)
            return "cancel"

        self.session = await self.client.create_session(
            {
                "model": self.current_model,
                "streaming": True,
                "tools": [list_files, read_file],
                "on_permission_request": permission_bridge,
                "on_user_input_request": user_input_bridge
            }
        )
        self.session.on(self._handle_event)
        CONTEXT.read_files = []
        
        self.stats["session_start"] = time.time()
        self.stats["api_time"] = 0.0
        self.stats["requests"] = 0
        self.stats["models"] = {}
        
        logger.info("Session created.")
    
    async def reset_session(self, model: Optional[str] = None):
        if model:
            self.current_model = model
        logger.info("Resetting session...")
        
        self.cleanup_temp_dir()
        self.session_id = str(uuid.uuid4())[:8]
        
        if self.session:
            try:
                await self.session.destroy()
            except Exception as e:
                logger.warning(f"Error destroying session: {e}")
            self.session = None

        await self._create_session()

    async def stop(self):
        logger.info("Stopping Copilot Client...")
        self.cleanup_temp_dir()
        
        if self.session:
            try:
                await self.session.destroy()
            except Exception as e:
                logger.warning(f"Error destroying session during stop: {e}")
            self.session = None

        if self._is_running:
            await self.client.stop()
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
                mult = self.MODEL_METADATA.get(mid, "1x")
                results.append({"id": mid, "multiplier": mult})
            return results
        except:
            return [{"id": "gpt-4o", "multiplier": "1x"}]

    def get_context_files(self) -> List[str]:
        return CONTEXT.read_files

    def get_ls_output(self) -> str:
        """Returns flat list of current directory content."""
        root = CONTEXT.root_path
        output = []
        try:
            items = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            filtered = [i for i in items if not i.name.startswith('.')]
            for item in filtered:
                if item.is_dir():
                    output.append(f"📁 {item.name}/")
                else:
                    output.append(f"📄 {item.name}")
            return "\n".join(output) if output else "(Empty)"
        except Exception as e:
            return f"Error: {e}"

    def get_project_structure(self, max_depth=2, limit=30) -> str:
        """Returns nested project structure with file sizes."""
        root = CONTEXT.root_path
        output = []
        
        def format_size(path: Path):
            try:
                size = path.stat().st_size
                if size < 1024: return f"{size}B"
                if size < 1024*1024: return f"{size/1024:.1f}KB"
                return f"{size/(1024*1024):.1f}MB"
            except: return "0B"

        def _scan(path: Path, prefix: str = "", depth: int = 0):
            if depth > max_depth or len(output) > limit: return
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                filtered = [i for i in items if not i.name.startswith('.')]
                for item in filtered:
                    if len(output) >= limit: return
                    if item.is_dir():
                        output.append(f"{prefix}📁 {item.name}/")
                        _scan(item, prefix + "  ", depth + 1)
                    else:
                        size_str = format_size(item)
                        output.append(f"{prefix}📄 {item.name} ({size_str})")
            except: pass
            
        _scan(root)
        return "\n".join(output) if output else "(Empty)"

    async def chat(self, user_message: str, 
                  content_callback: Optional[Callable[[str], Any]] = None,
                  status_callback: Optional[Callable[[str], Any]] = None,
                  interaction_callback: Optional[Callable[[str, Any], Any]] = None):
        if not self.session:
            await self.start()
        self.current_callback = content_callback
        CONTEXT.status_callback = status_callback
        self.interaction_callback = interaction_callback
        
        start_t = time.time()
        
        try:
            await self.session.send_and_wait({"prompt": user_message})
        finally:
            duration = time.time() - start_t
            self.stats["api_time"] += duration
            self.stats["requests"] += 1
            model = self.current_model
            self.stats["models"][model] = self.stats["models"].get(model, 0) + 1
            
            self.current_callback = None
            CONTEXT.status_callback = None
            self.interaction_callback = None

    def _handle_event(self, event):
        if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
            if self.current_callback:
                content = event.data.delta_content
                if content:
                    self._dispatch_async(self.current_callback, content)
        elif event.type == SessionEventType.TOOL_EXECUTION_START:
            try:
                tool_name = event.data.tool_name
                args = event.data.arguments
                logger.info(f"TOOL START: {tool_name} args={args}")
            except: pass
        elif event.type == SessionEventType.SESSION_USAGE_INFO:
            self.last_usage_info = event.data
            logger.info(f"Usage Info Received: {event.data}")
        elif event.type == SessionEventType.ASSISTANT_USAGE:
            self.last_usage_info = event.data
            logger.info(f"Assistant Usage Received: {event.data}")

    def _dispatch_async(self, callback, *args):
        try:
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(callback):
                loop.create_task(callback(*args))
            else:
                callback(*args)
        except: pass
