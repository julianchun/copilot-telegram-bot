"""Filesystem browsing helpers — directory listing & project structure."""

import logging
from pathlib import Path
from typing import Optional

from src.core.context import ctx

logger = logging.getLogger(__name__)


def get_directory_listing(session_cwd: Optional[str] = None) -> str:
    """Returns flat list of current directory content."""
    root = Path(session_cwd) if session_cwd else ctx.root_path
    output = []
    try:
        items = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        for item in items:
            if item.is_dir():
                output.append(f"📁 {item.name}/")
            else:
                output.append(f"📄 {item.name}")
        return "\n".join(output) if output else "(Empty)"
    except Exception as e:
        return f"Error: {e}"


def get_project_structure(session_cwd: Optional[str] = None, max_depth: int = 2, limit: int = 30) -> str:
    """Returns nested project structure with file sizes."""
    root = Path(session_cwd) if session_cwd else ctx.root_path
    output: list[str] = []

    def format_size(path: Path) -> str:
        try:
            size = path.stat().st_size
            if size < 1024:
                return f"{size}B"
            if size < 1024 * 1024:
                return f"{size / 1024:.1f}KB"
            return f"{size / (1024 * 1024):.1f}MB"
        except Exception:
            return "0B"

    def _scan(path: Path, prefix: str = "", depth: int = 0):
        if depth > max_depth or len(output) > limit:
            return
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            filtered = [i for i in items if not i.name.startswith(".")]
            for item in filtered:
                if len(output) >= limit:
                    return
                if item.is_dir():
                    output.append(f"{prefix}📁 {item.name}/")
                    _scan(item, prefix + "  ", depth + 1)
                else:
                    size_str = format_size(item)
                    output.append(f"{prefix}📄 {item.name} ({size_str})")
        except Exception:
            pass

    _scan(root)
    return "\n".join(output) if output else "(Empty)"
