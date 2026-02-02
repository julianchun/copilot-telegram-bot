import os
import asyncio
from pathlib import Path
from typing import Optional, List, Callable, Any, Dict

from pydantic import BaseModel, Field
from copilot import CopilotClient
from copilot.tools import define_tool
from copilot.generated.session_events import SessionEventType

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
        # Report CLI style log
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
            
            # Report CLI style log
            await CONTEXT.report_status(f"● Read {params.path}\n  └ {len(lines)} lines read")
            CONTEXT.track_file(params.path)
            
            if len(content) > 100000:
                return content[:100000] + "\n... (File truncated)"
            return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

# --- Service Class ---

import logging
# ... (imports)

logger = logging.getLogger(__name__)

# ... (ServiceContext class)

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
        self.current_callback = None
        self.current_model = "gpt-4o"
        self._is_running = False
        
    async def set_working_directory(self, path: str):
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        
        current_root = CONTEXT.root_path
        
        # Log the request
        logger.info(f"Requested CWD change: {current_root} -> {p}")

        if str(p) != str(current_root):
            # 1. Update Context for Tools
            CONTEXT.set_root(p)
            
            # 2. Update Client with new CWD
            # Re-initialize the client with the new CWD
            self.client = CopilotClient({"cwd": str(p)})
            logger.info(f"CopilotClient re-initialized with CWD: {p}")

            # 3. Restart Client
            if self._is_running:
                logger.info("Restarting Copilot Client to apply new CWD...")
                await self.stop()
                await self.start()
                logger.info("Copilot Client restarted.")
        
        return str(CONTEXT.root_path)
        
    def get_working_directory(self) -> str:
        # Return the actual OS CWD to be sure
        return os.getcwd()

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
            logger.error(f"Auth Check Failed: {e}")
            return "User"

    # ... (get_git_info)

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
        self.session = await self.client.create_session(
            {
                "model": self.current_model,
                "streaming": True,
                "tools": [list_files, read_file]
            }
        )
        self.session.on(self._handle_event)
        CONTEXT.read_files = []
        logger.info("Session created.")
    
    async def reset_session(self, model: Optional[str] = None):
        if model:
            self.current_model = model
        logger.info("Resetting session...")
        await self._create_session()

    async def stop(self):
        logger.info("Stopping Copilot Client...")
        await self.client.stop()
        self._is_running = False
        self.session = None # Clear session on stop
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

    def get_project_structure(self, max_depth=2, limit=20) -> str:
        root = CONTEXT.root_path
        output = []
        def _scan(path: Path, prefix: str = "", depth: int = 0):
            if depth > max_depth or len(output) > limit: return
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                filtered = [i for i in items if not i.name.startswith('.')]
                for i, item in enumerate(filtered):
                    if len(output) >= limit: return
                    is_last = (i == len(filtered) - 1)
                    connector = "└── " if is_last else "├── "
                    output.append(f"{prefix}{connector}{item.name}{'/' if item.is_dir() else ''}")
                    if item.is_dir():
                        _scan(item, prefix + ("    " if is_last else "│   "), depth + 1)
            except: pass
        _scan(root)
        return "\n".join(output) if output else "(Empty)"

    async def chat(self, user_message: str, 
                  content_callback: Optional[Callable[[str], Any]] = None,
                  status_callback: Optional[Callable[[str], Any]] = None):
        if not self.session:
            await self.start()
        self.current_callback = content_callback
        CONTEXT.status_callback = status_callback
        try:
            await self.session.send_and_wait({"prompt": user_message})
        finally:
            self.current_callback = None
            CONTEXT.status_callback = None

    def _handle_event(self, event):
        if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
            if self.current_callback:
                content = event.data.delta_content
                if content:
                    self._dispatch_async(self.current_callback, content)

    def _dispatch_async(self, callback, *args):
        try:
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(callback):
                loop.create_task(callback(*args))
            else:
                callback(*args)
        except: pass