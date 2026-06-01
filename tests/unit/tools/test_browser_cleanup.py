# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for browser cleanup on Windows (#4844).

Verifies that:
- _stop_owned_browser_process kills the entire process tree on Windows
- _cleanup_browser_lock_files removes Chromium singleton files
- _reset_browser_state calls lock-file cleanup
- _atexit_cleanup falls back to sync killing when loop is running
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _cleanup_browser_lock_files
# ---------------------------------------------------------------------------


class TestCleanupBrowserLockFiles:
    """Tests for Chromium lock-file cleanup."""

    def test_removes_singleton_files(self, tmp_path):
        from qwenpaw.agents.tools.browser_control import (
            _cleanup_browser_lock_files,
        )

        user_data = tmp_path / "user_data"
        user_data.mkdir()
        lock_names = [
            "SingletonLock",
            "SingletonCookie",
            "SingletonSocket",
            "lockfile",
        ]
        for name in lock_names:
            (user_data / name).write_text("")

        state = {"user_data_dir": str(user_data)}
        _cleanup_browser_lock_files(state)

        for name in lock_names:
            assert not (
                user_data / name
            ).exists(), f"{name} should have been removed"

    def test_ignores_missing_dir(self):
        from qwenpaw.agents.tools.browser_control import (
            _cleanup_browser_lock_files,
        )

        state = {"user_data_dir": "/nonexistent/path/12345"}
        # Should not raise
        _cleanup_browser_lock_files(state)

    def test_ignores_empty_user_data_dir(self):
        from qwenpaw.agents.tools.browser_control import (
            _cleanup_browser_lock_files,
        )

        state = {"user_data_dir": ""}
        _cleanup_browser_lock_files(state)

    def test_preserves_non_lock_files(self, tmp_path):
        from qwenpaw.agents.tools.browser_control import (
            _cleanup_browser_lock_files,
        )

        user_data = tmp_path / "user_data"
        user_data.mkdir()
        (user_data / "Default").mkdir()
        (user_data / "Local State").write_text("{}")
        (user_data / "SingletonLock").write_text("")

        state = {"user_data_dir": str(user_data)}
        _cleanup_browser_lock_files(state)

        assert (user_data / "Default").exists()
        assert (user_data / "Local State").exists()
        assert not (user_data / "SingletonLock").exists()


# ---------------------------------------------------------------------------
# _reset_browser_state calls lock cleanup
# ---------------------------------------------------------------------------


class TestResetBrowserState:
    """Tests that _reset_browser_state triggers lock-file cleanup."""

    def test_calls_cleanup_lock_files(self, tmp_path):
        from qwenpaw.agents.tools.browser_control import (
            _make_fresh_state,
            _reset_browser_state,
        )

        state = _make_fresh_state("test-ws", str(tmp_path))
        user_data = tmp_path / "browser" / "user_data"
        user_data.mkdir(parents=True)
        (user_data / "SingletonLock").write_text("")

        _reset_browser_state(state)

        assert not (user_data / "SingletonLock").exists()


# ---------------------------------------------------------------------------
# _stop_owned_browser_process on Windows
# ---------------------------------------------------------------------------


class TestStopOwnedBrowserProcess:
    """Tests for process-tree killing on Windows."""

    @pytest.mark.asyncio
    async def test_uses_taskkill_on_windows(self):
        from qwenpaw.agents.tools.browser_control import (
            _stop_owned_browser_process,
        )

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = None

        state = {"browser_process": mock_proc}

        with (
            patch("sys.platform", "win32"),
            patch(
                "qwenpaw.agents.tools.browser_control.subprocess.run",
            ) as mock_run,
            patch(
                "asyncio.to_thread",
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
        ):
            result = await _stop_owned_browser_process(state)

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "taskkill" in cmd
        assert "/T" in cmd
        assert "/F" in cmd
        assert str(12345) in cmd

    @pytest.mark.asyncio
    async def test_already_exited(self):
        from qwenpaw.agents.tools.browser_control import (
            _stop_owned_browser_process,
        )

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0

        state = {"browser_process": mock_proc}
        result = await _stop_owned_browser_process(state)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_process(self):
        from qwenpaw.agents.tools.browser_control import (
            _stop_owned_browser_process,
        )

        state = {"browser_process": None}
        result = await _stop_owned_browser_process(state)
        assert result is False


# ---------------------------------------------------------------------------
# _sync_kill_browser_process (atexit fallback)
# ---------------------------------------------------------------------------


class TestSyncKillBrowserProcess:
    """Tests for synchronous process-tree killing (atexit fallback)."""

    def test_kills_on_windows(self):
        from qwenpaw.agents.tools.browser_control import (
            _sync_kill_browser_process,
        )

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = None

        state = {"browser_process": mock_proc}

        with (
            patch("sys.platform", "win32"),
            patch(
                "qwenpaw.agents.tools.browser_control.subprocess.run",
            ) as mock_run,
        ):
            _sync_kill_browser_process(state)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "taskkill" in cmd
        assert "/T" in cmd

    def test_skips_exited_process(self):
        from qwenpaw.agents.tools.browser_control import (
            _sync_kill_browser_process,
        )

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0

        state = {"browser_process": mock_proc}
        _sync_kill_browser_process(state)
        mock_proc.terminate.assert_not_called()

    def test_skips_none_process(self):
        from qwenpaw.agents.tools.browser_control import (
            _sync_kill_browser_process,
        )

        state = {"browser_process": None}
        # Should not raise
        _sync_kill_browser_process(state)
