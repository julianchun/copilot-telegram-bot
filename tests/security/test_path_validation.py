"""Security tests for path traversal protection in tools.py.

Validates that list_files() and read_file() reject any path that resolves
outside the configured workspace root.
"""

import os
from pathlib import Path

import pytest
from copilot.types import ToolInvocation

from src.core.context import ctx
from src.core.tools import list_files, read_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _list(path: str) -> str:
    """Call list_files handler and return the LLM-facing text."""
    inv = ToolInvocation(arguments={"path": path})
    result = await list_files.handler(inv)
    return result.text_result_for_llm


async def _read(path: str) -> str:
    """Call read_file handler and return the LLM-facing text."""
    inv = ToolInvocation(arguments={"path": path})
    result = await read_file.handler(inv)
    return result.text_result_for_llm


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    """Point ctx.root_path at a disposable tmp workspace with sample files."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# Project")

    # Resolve to canonical path (important — root_path must be resolved)
    resolved = tmp_path.resolve()
    monkeypatch.setattr(ctx, "root_path", resolved)
    yield


# ---------------------------------------------------------------------------
# list_files — traversal / escape
# ---------------------------------------------------------------------------

class TestListFilesPathTraversal:

    async def test_dotdot_traversal(self):
        result = await _list("../../../etc/passwd")
        assert "Access denied" in result

    async def test_absolute_path_outside(self):
        result = await _list("/etc")
        assert "Access denied" in result

    async def test_absolute_path_inside(self, tmp_path):
        """Absolute path that falls *within* the workspace should succeed."""
        result = await _list(str(tmp_path.resolve()))
        assert "Access denied" not in result
        assert "README.md" in result

    async def test_valid_relative_dot(self):
        result = await _list(".")
        assert "Access denied" not in result
        assert "README.md" in result

    async def test_valid_relative_subdir(self):
        result = await _list("src")
        assert "Access denied" not in result
        assert "main.py" in result


# ---------------------------------------------------------------------------
# read_file — traversal / escape
# ---------------------------------------------------------------------------

class TestReadFilePathTraversal:

    async def test_dotdot_traversal(self):
        result = await _read("../../etc/passwd")
        assert "Access denied" in result

    async def test_absolute_outside(self):
        result = await _read("/etc/passwd")
        assert "Access denied" in result

    async def test_dotdot_nested(self):
        """Traversal hidden inside a legitimate-looking relative path."""
        result = await _read("subdir/../../etc/passwd")
        assert "Access denied" in result

    async def test_symlink_outside(self, tmp_path):
        """A symlink inside the workspace that targets a file outside it."""
        link = tmp_path / "evil_link"
        os.symlink("/etc/passwd", str(link))
        result = await _read("evil_link")
        assert "Access denied" in result

    async def test_encoded_dotdot_literal(self):
        """Literal URL-encoded dots — Path treats them as regular chars."""
        result = await _read("%2e%2e/%2e%2e/etc/passwd")
        # Path won't decode percent-encoding, so this is just a bad filename.
        # It must NOT succeed in reading /etc/passwd.
        assert "root:" not in result
        assert "access denied" in result.lower() or "not found" in result.lower()

    async def test_valid_relative(self, tmp_path):
        result = await _read("README.md")
        assert "Access denied" not in result
        assert "# Project" in result

    async def test_valid_relative_in_subdir(self):
        result = await _read("src/main.py")
        assert "Access denied" not in result
        assert "print" in result
