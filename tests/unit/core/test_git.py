"""Unit tests for src.core.git module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.git import get_diff_shortstat, get_git_info


def _make_proc(stdout_bytes: bytes):
    """Create a mock subprocess with given stdout."""
    proc = AsyncMock()
    proc.communicate.return_value = (stdout_bytes, b"")
    return proc


class TestGetGitInfo:
    async def test_get_git_info_with_session_branch_clean(self):
        with patch("src.core.git.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = _make_proc(b"")
            result = await get_git_info(session_branch="main", session_cwd="/repo")
        assert result == "@main"

    async def test_get_git_info_with_session_branch_dirty(self):
        with patch("src.core.git.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = _make_proc(b" M file.py\n")
            result = await get_git_info(session_branch="main", session_cwd="/repo")
        assert result == "@main*"

    async def test_get_git_info_fallback_to_git_clean(self):
        with patch("src.core.git.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.side_effect = [
                _make_proc(b"develop\n"),  # git rev-parse
                _make_proc(b""),            # git status (clean)
            ]
            result = await get_git_info()
        assert result == "@develop"

    async def test_get_git_info_fallback_empty_branch(self):
        with patch("src.core.git.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = _make_proc(b"")
            result = await get_git_info()
        assert result == ""

    async def test_get_git_info_exception_returns_empty(self):
        with patch("src.core.git.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.side_effect = OSError("git not found")
            result = await get_git_info()
        assert result == ""


class TestGetDiffShortstat:
    async def test_get_diff_shortstat_with_changes(self):
        with patch("src.core.git.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = _make_proc(b" 3 files changed, 10 insertions(+), 2 deletions(-)\n")
            result = await get_diff_shortstat(cwd="/repo")
        assert result == "3 files changed, 10 +, 2 -"

    async def test_get_diff_shortstat_no_changes(self):
        with patch("src.core.git.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = _make_proc(b"")
            result = await get_diff_shortstat(cwd="/repo")
        assert result == "0 files changed, 0 +, 0 -"

    async def test_get_diff_shortstat_only_insertions(self):
        with patch("src.core.git.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = _make_proc(b" 1 file changed, 5 insertions(+)\n")
            result = await get_diff_shortstat(cwd="/repo")
        assert result == "1 files changed, 5 +, 0 -"

    async def test_get_diff_shortstat_exception_returns_empty(self):
        with patch("src.core.git.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = OSError("git not found")
            result = await get_diff_shortstat(cwd="/repo")
        assert result == ""
