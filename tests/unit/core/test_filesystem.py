"""Unit tests for src.core.filesystem."""

from pathlib import Path

import pytest

from src.core.filesystem import (
    _format_size,
    get_directory_listing,
    get_project_stats,
    get_project_structure,
)


# ── _format_size ─────────────────────────────────────────────────────────


def test_format_size_bytes(tmp_path: Path) -> None:
    f = tmp_path / "tiny.txt"
    f.write_bytes(b"x" * 100)
    assert _format_size(f) == "100B"


def test_format_size_kilobytes(tmp_path: Path) -> None:
    f = tmp_path / "medium.bin"
    f.write_bytes(b"\0" * 2048)
    assert _format_size(f) == "2.0KB"


def test_format_size_megabytes(tmp_path: Path) -> None:
    f = tmp_path / "large.bin"
    f.write_bytes(b"\0" * (2 * 1024 * 1024))
    assert _format_size(f) == "2.0MB"


# ── get_directory_listing ────────────────────────────────────────────────


def test_get_directory_listing_basic(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("hello")

    listing = get_directory_listing(str(tmp_path))

    assert "📁 src/" in listing
    assert "📄 README.md" in listing


def test_get_directory_listing_hides_hidden(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "visible.txt").write_text("ok")

    listing = get_directory_listing(str(tmp_path))

    assert ".git" not in listing
    assert ".env" not in listing
    assert "📄 visible.txt" in listing


def test_get_directory_listing_hides_ignored(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "app.py").write_text("pass")

    listing = get_directory_listing(str(tmp_path))

    assert "__pycache__" not in listing
    assert "node_modules" not in listing
    assert "📄 app.py" in listing


def test_get_directory_listing_empty(tmp_path: Path) -> None:
    assert get_directory_listing(str(tmp_path)) == "(Empty)"


# ── get_project_structure ────────────────────────────────────────────────


def test_get_project_structure_nested(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass")

    structure = get_project_structure(str(tmp_path))

    assert "📁 src/" in structure
    assert "  📄 main.py" in structure


def test_get_project_structure_depth_limit(tmp_path: Path) -> None:
    # depth 0: tmp_path  →  depth 1: a/  →  depth 2: b/  →  depth 3: deep.txt
    d = tmp_path / "a" / "b" / "c"
    d.mkdir(parents=True)
    (d / "deep.txt").write_text("deep")

    structure = get_project_structure(str(tmp_path), max_depth=2)

    assert "📁 a/" in structure
    assert "📁 b/" in structure
    assert "📁 c/" in structure
    # deep.txt is at depth 3, should NOT appear with max_depth=2
    assert "deep.txt" not in structure


# ── get_project_stats ────────────────────────────────────────────────────


def test_get_project_stats_counts(tmp_path: Path) -> None:
    (tmp_path / "dir1").mkdir()
    (tmp_path / "dir1" / "a.txt").write_text("a")
    (tmp_path / "dir2").mkdir()
    (tmp_path / "dir2" / "b.txt").write_text("b")
    (tmp_path / "root.txt").write_text("r")

    files, folders = get_project_stats(str(tmp_path))

    assert files == 3
    assert folders == 2


def test_get_project_stats_ignores_hidden_and_ignored(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "mod.pyc").write_bytes(b"\0")
    (tmp_path / "real.py").write_text("pass")

    files, folders = get_project_stats(str(tmp_path))

    assert files == 1
    assert folders == 0
