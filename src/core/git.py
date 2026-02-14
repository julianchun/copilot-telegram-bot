"""Git operations — shell-out helpers for branch/status metadata."""

import asyncio
import logging
import re
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


async def get_diff_shortstat(cwd: str = None) -> str:
    """Run 'git diff --shortstat' and return formatted summary.
    
    Returns e.g. '3 files changed, 10 +, 2 -' or empty string if no changes.
    """
    work_dir = cwd or str(ctx.root_path)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--shortstat",
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode().strip()
        if not raw:
            return "0 files changed, 0 +, 0 -"

        files = insertions = deletions = 0
        m = re.search(r"(\d+) file", raw)
        if m:
            files = int(m.group(1))
        m = re.search(r"(\d+) insertion", raw)
        if m:
            insertions = int(m.group(1))
        m = re.search(r"(\d+) deletion", raw)
        if m:
            deletions = int(m.group(1))

        return f"{files} files changed, {insertions} +, {deletions} -"
    except Exception as e:
        logger.debug(f"get_diff_shortstat failed: {e}")
        return ""
