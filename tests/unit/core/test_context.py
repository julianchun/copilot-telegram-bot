from pathlib import Path
from unittest.mock import patch

from src.core.context import SessionContext

MOCK_MAX = 200
MOCK_PRUNE = 100


class TestSessionContext:
    def _make_ctx(self):
        with patch("src.core.context.WORKSPACE_PATH", Path("/mock/workspace")):
            return SessionContext()

    def test_set_root_resolves_path(self):
        ctx = self._make_ctx()
        test_path = Path("/some/../some/path")
        ctx.set_root(test_path)
        assert ctx.root_path == test_path.resolve()
        assert ctx.root_path.is_absolute()

    def test_track_file_adds_to_list(self):
        ctx = self._make_ctx()
        ctx.track_file("a.py")
        assert ctx.read_files == ["a.py"]

    def test_track_file_no_duplicates(self):
        ctx = self._make_ctx()
        ctx.track_file("a.py")
        ctx.track_file("a.py")
        assert ctx.read_files == ["a.py"]

    @patch("src.core.context.MAX_TRACKED_FILES", 5)
    @patch("src.core.context.TRACKED_FILES_PRUNE_SIZE", 3)
    def test_track_file_prunes_at_limit(self):
        ctx = self._make_ctx()
        for i in range(6):
            ctx.track_file(f"file_{i}.py")
        # After adding 6 files (exceeding limit of 5), list is pruned to last 3
        assert len(ctx.read_files) == 3
        assert ctx.read_files == ["file_3.py", "file_4.py", "file_5.py"]

    def test_clear_tracked_files(self):
        ctx = self._make_ctx()
        ctx.track_file("a.py")
        ctx.track_file("b.py")
        ctx.clear_tracked_files()
        assert ctx.read_files == []

    def test_session_start_time_initially_none(self):
        ctx = self._make_ctx()
        assert ctx.session_start_time is None

    def test_status_callback_initially_none(self):
        ctx = self._make_ctx()
        assert ctx.status_callback is None
