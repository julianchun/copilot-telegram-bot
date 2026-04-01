"""Unit tests for src.core.tools (list_files, read_file)."""

import importlib
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Patch the SDK decorator before importing tools so it becomes a no-op.
# ---------------------------------------------------------------------------

def _noop_decorator(**kwargs):
    """Replace @define_tool(...) with identity."""
    return lambda fn: fn


_define_tool_patch = patch("copilot.tools.define_tool", _noop_decorator)
_define_tool_patch.start()

# Force re-import so the module is loaded with the patched decorator.
if "src.core.tools" in sys.modules:
    del sys.modules["src.core.tools"]

from src.core.tools import (  # noqa: E402
    list_files,
    read_file,
    ListFilesParams,
    ReadFileParams,
)

_define_tool_patch.stop()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def workspace(tmp_path):
    """Create a tiny workspace and point ctx.root_path at it."""
    # directories
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content")

    # regular files
    (tmp_path / "hello.txt").write_text("Hello, world!")
    (tmp_path / "README.md").write_text("# README")

    with patch("src.core.tools.ctx") as mock_ctx:
        mock_ctx.root_path = tmp_path
        mock_ctx.track_file = MagicMock()
        yield tmp_path, mock_ctx


# ---------------------------------------------------------------------------
# list_files tests
# ---------------------------------------------------------------------------

class TestListFiles:
    async def test_list_files_valid_directory(self, workspace):
        ws, _ = workspace
        result = await list_files(ListFilesParams(path="."))
        assert "hello.txt" in result
        assert "README.md" in result
        assert "subdir/" in result

    async def test_list_files_relative_path(self, workspace):
        ws, _ = workspace
        result = await list_files(ListFilesParams(path="subdir"))
        assert "nested.txt" in result

    async def test_list_files_outside_workspace(self, workspace):
        result = await list_files(ListFilesParams(path="/etc"))
        assert "Access denied" in result

    async def test_list_files_nonexistent_directory(self, workspace):
        result = await list_files(ListFilesParams(path="no_such_dir"))
        assert "Error listing files" in result


# ---------------------------------------------------------------------------
# read_file tests
# ---------------------------------------------------------------------------

class TestReadFile:
    async def test_read_file_valid(self, workspace):
        ws, mock_ctx = workspace
        result = await read_file(ReadFileParams(path="hello.txt"))
        assert result == "Hello, world!"

    async def test_read_file_outside_workspace(self, workspace):
        result = await read_file(ReadFileParams(path="/etc/passwd"))
        assert "Access denied" in result

    async def test_read_file_traversal_attack(self, workspace):
        result = await read_file(ReadFileParams(path="../../etc/passwd"))
        assert "Access denied" in result

    async def test_read_file_nonexistent(self, workspace):
        result = await read_file(ReadFileParams(path="missing.txt"))
        assert "File not found" in result

    async def test_read_file_truncation(self, workspace):
        ws, _ = workspace
        big = tmp_path = ws / "big.txt"
        big.write_text("A" * 200_000)
        with patch("src.core.tools.FILE_CONTENT_LIMIT", 100_000):
            result = await read_file(ReadFileParams(path="big.txt"))
        assert result.endswith("... (File truncated)")
        # Content before truncation marker should be exactly FILE_CONTENT_LIMIT chars
        assert len(result.split("\n... (File truncated)")[0]) == 100_000

    async def test_read_file_binary(self, workspace):
        ws, _ = workspace
        bin_file = ws / "image.bin"
        bin_file.write_bytes(b"\x80\x81\x82\xff\xfe")
        result = await read_file(ReadFileParams(path="image.bin"))
        assert "Binary or unsupported file encoding" in result

    async def test_read_file_tracks_file(self, workspace):
        ws, mock_ctx = workspace
        await read_file(ReadFileParams(path="hello.txt"))
        mock_ctx.track_file.assert_called_once_with("hello.txt")
