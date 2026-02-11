"""Filesystem browsing helpers — directory listing & project structure."""

import logging
from pathlib import Path
from typing import Optional

from src.core.context import ctx

logger = logging.getLogger(__name__)

# Directories to hide from project structure (common noise / build artifacts)
IGNORED_DIRS: set[str] = {
    "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "out", "target",
    ".next", ".nuxt", ".turbo", ".cache",
    "coverage", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pypackages__", ".eggs", ".gradle", ".idea",
}


def _format_size(path: Path) -> str:
    """Format file size for display (e.g., 2.3KB, 1.1MB)."""
    try:
        size = path.stat().st_size
        if size < 1024:
            return f"{size}B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size / (1024 * 1024):.1f}MB"
    except Exception:
        return "0B"


def get_directory_listing(session_cwd: Optional[str] = None) -> str:
    """Returns flat list of current directory content with file sizes."""
    root = Path(session_cwd) if session_cwd else ctx.root_path
    output = []
    try:
        items = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        for item in items:
            # Skip hidden files and ignored directories
            if item.name.startswith("."):
                continue
            if item.is_dir() and item.name in IGNORED_DIRS:
                continue
            if item.is_dir():
                output.append(f"📁 {item.name}/")
            else:
                size_str = _format_size(item)
                output.append(f"📄 {item.name} ({size_str})")
        return "\n".join(output) if output else "(Empty)"
    except Exception as e:
        return f"Error: {e}"


def get_project_structure(session_cwd: Optional[str] = None, max_depth: int = 2, limit: int = 999999) -> str:
    """Returns nested project structure with 2-space indentation and emoji icons."""
    root = Path(session_cwd) if session_cwd else ctx.root_path
    output: list[str] = []

    def _scan(path: Path, depth: int = 0):
        if depth > max_depth:
            return
        try:
            indent = "  " * depth
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            filtered = [
                i for i in items
                if not i.name.startswith(".")
                and not (i.is_dir() and i.name in IGNORED_DIRS)
            ]
            for item in filtered:
                if item.is_dir():
                    output.append(f"{indent}📁 {item.name}/")
                    _scan(item, depth + 1)
                else:
                    size_str = _format_size(item)
                    output.append(f"{indent}📄 {item.name} ({size_str})")
        except Exception:
            pass

    _scan(root)
    return "\n".join(output) if output else "(Empty)"
