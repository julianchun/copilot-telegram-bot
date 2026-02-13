from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Any
from src.config import WORKSPACE_PATH, MAX_TRACKED_FILES, TRACKED_FILES_PRUNE_SIZE

class SessionContext:
    """
    Singleton-like context to hold state required by tools.
    Tools (functions) cannot easily accept extra arguments in many SDKs,
    so we use this context to inject dependencies like root_path or callbacks.
    """
    def __init__(self):
        self.root_path: Path = WORKSPACE_PATH
        self.status_callback: Optional[Callable[[str], Any]] = None
        self.read_files: list[str] = []
        self.session_start_time: Optional[datetime] = None

    def set_root(self, path: Path):
        self.root_path = path.resolve()
    
    def track_file(self, path: str):
        if path not in self.read_files:
            self.read_files.append(path)
            # Prevent unbounded growth
            if len(self.read_files) > MAX_TRACKED_FILES:
                self.read_files = self.read_files[-TRACKED_FILES_PRUNE_SIZE:]
    
    def clear_tracked_files(self):
        self.read_files = []

# Global instance
ctx = SessionContext()
