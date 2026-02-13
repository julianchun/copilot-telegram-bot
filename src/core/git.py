"""Git operations — shell-out helpers for branch/status metadata."""

import asyncio
import logging
from typing import Optional

from src.core.context import ctx

logger = logging.getLogger(__name__)


async def get_git_info(session_branch: Optional[str] = None, session_cwd: Optional[str] = None) -> str:
    """Get git info string like '@main*'. Prefers session context from SDK."""
    try:
        if session_branch:
            branch = session_branch
            cwd = session_cwd or str(ctx.root_path)
            proc = await asyncio.create_subprocess_shell(
                "git status --porcelain",
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            dirty = "*" if stdout.decode().strip() else ""
            return f"@{branch}{dirty}"

        # Fallback: query git directly
        root = ctx.root_path
        proc = await asyncio.create_subprocess_shell(
            "git rev-parse --abbrev-ref HEAD",
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        branch = stdout.decode().strip()
        if not branch:
            return ""

        proc = await asyncio.create_subprocess_shell(
            "git status --porcelain",
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        dirty = "*" if stdout.decode().strip() else ""
        return f"@{branch}{dirty}"
    except Exception as e:
        logger.debug(f"get_git_info failed: {e}")
        return ""
