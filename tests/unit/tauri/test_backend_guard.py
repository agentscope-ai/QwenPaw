# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for the Tauri single-backend reconciliation guard.

The guard exists because an abnormal exit (crash / OOM / SIGKILL) leaves the
Python sidecar orphaned, and repeated launches then stack up ~500 MB backends
(issue #5550). The PID-reuse check in ``_looks_like_backend`` is the safety
critical part: a recycled PID must never be killed.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import psutil
import pytest

from qwenpaw.tauri import backend_guard as guard


def _proc(name="qwenpaw-backend", exe="/usr/bin/python3", cmdline=None):
    """Build a fake psutil.Process whose identity probes succeed."""
    proc = MagicMock()
    proc.name.return_value = name
    proc.exe.return_value = exe
    proc.cmdline.return_value = (
        cmdline
        if cmdline is not None
        else ["python3", "-m", "qwenpaw.tauri.entry"]
    )
    return proc


@pytest.fixture()
def pid_file(tmp_path):
    return tmp_path / guard.PID_FILENAME


class TestReadRecordedPid:
    def test_reads_an_integer(self, pid_file):
        pid_file.write_text("4242", encoding="utf-8")
        assert guard._read_recorded_pid(pid_file) == 4242

    def test_tolerates_surrounding_whitespace(self, pid_file):
        pid_file.write_text("  4242\n", encoding="utf-8")
        assert guard._read_recorded_pid(pid_file) == 4242

    def test_missing_file_returns_none(self, pid_file):
        assert guard._read_recorded_pid(pid_file) is None

    def test_non_integer_content_returns_none(self, pid_file):
        """A torn write must self-heal rather than raise."""
        pid_file.write_text("not-a-pid", encoding="utf-8")
        assert guard._read_recorded_pid(pid_file) is None

    def test_empty_file_returns_none(self, pid_file):
        pid_file.write_text("", encoding="utf-8")
        assert guard._read_recorded_pid(pid_file) is None

    def test_zero_pid_returns_none(self, pid_file):
        pid_file.write_text("0", encoding="utf-8")
        assert guard._read_recorded_pid(pid_file) is None

    def test_negative_pid_returns_none(self, pid_file):
        pid_file.write_text("-7", encoding="utf-8")
        assert guard._read_recorded_pid(pid_file) is None

    def test_unreadable_file_returns_none(self, pid_file):
        pid_file.mkdir()  # reading a directory raises OSError
        assert guard._read_recorded_pid(pid_file) is None


class TestLooksLikeBackend:
    def test_matches_on_process_name(self):
        assert guard._looks_like_backend(_proc(name="QwenPaw-Backend")) is True

    def test_matches_on_executable_path(self):
        proc = _proc(name="python3", exe="/opt/qwenpaw-backend/bin/run")
        assert guard._looks_like_backend(proc) is True

    def test_matches_on_tauri_entry_cmdline(self):
        proc = _proc(
            name="python3",
            exe="/usr/bin/python3",
            cmdline=["python3", "-m", "qwenpaw.tauri.entry"],
        )
        assert guard._looks_like_backend(proc) is True

    def test_matches_on_backend_marker_in_cmdline(self):
        proc = _proc(
            name="python3",
            exe="/usr/bin/python3",
            cmdline=["/usr/bin/qwenpaw-backend", "--port", "1234"],
        )
        assert guard._looks_like_backend(proc) is True

    def test_rejects_an_unrelated_process(self):
        """🔴 PID-reuse guard: a recycled PID is not a backend."""
        proc = _proc(
            name="firefox",
            exe="/usr/lib/firefox/firefox",
            cmdline=["firefox", "--new-window"],
        )
        assert guard._looks_like_backend(proc) is False

    def test_rejects_when_name_probe_raises(self):
        proc = _proc()
        proc.name.side_effect = psutil.NoSuchProcess(pid=1)
        proc.exe.return_value = "/usr/bin/vim"
        proc.cmdline.return_value = ["vim"]
        assert guard._looks_like_backend(proc) is False

    def test_rejects_when_all_probes_raise(self):
        proc = MagicMock()
        proc.name.side_effect = psutil.AccessDenied(pid=1)
        proc.exe.side_effect = psutil.AccessDenied(pid=1)
        proc.cmdline.side_effect = psutil.AccessDenied(pid=1)
        assert guard._looks_like_backend(proc) is False

    def test_survives_a_plain_os_error(self):
        proc = MagicMock()
        proc.name.side_effect = OSError("boom")
        proc.exe.side_effect = OSError("boom")
        proc.cmdline.side_effect = OSError("boom")
        assert guard._looks_like_backend(proc) is False

    def test_none_identity_values_do_not_raise(self):
        proc = MagicMock()
        proc.name.return_value = None
        proc.exe.return_value = None
        proc.cmdline.return_value = []
        assert guard._looks_like_backend(proc) is False


class TestTerminatePreviousBackend:
    def test_no_pid_file_does_nothing(self, pid_file):
        guard._terminate_previous_backend(pid_file)  # must not raise

    def test_terminates_a_recorded_backend(self, pid_file, monkeypatch):
        pid_file.write_text("999", encoding="utf-8")
        proc = _proc()
        monkeypatch.setattr(
            guard.psutil,
            "Process",
            lambda pid: proc if pid == 999 else None,
        )

        guard._terminate_previous_backend(pid_file)

        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()
        proc.kill.assert_not_called()

    def test_never_terminates_its_own_pid(self, pid_file, monkeypatch):
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        factory = MagicMock()
        monkeypatch.setattr(guard.psutil, "Process", factory)

        guard._terminate_previous_backend(pid_file)

        factory.assert_not_called()

    def test_skips_a_pid_reuse_victim(self, pid_file, monkeypatch):
        """🔴 Core safety: the unrelated PID-holder must live."""
        pid_file.write_text("999", encoding="utf-8")
        victim = _proc(
            name="postgres",
            exe="/usr/lib/postgres/bin/postgres",
            cmdline=["postgres", "-D", "/var/lib/pg"],
        )
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: victim)

        guard._terminate_previous_backend(pid_file)

        victim.terminate.assert_not_called()
        victim.kill.assert_not_called()

    def test_gone_process_is_ignored(self, pid_file, monkeypatch):
        pid_file.write_text("999", encoding="utf-8")

        def raise_gone(pid):
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(guard.psutil, "Process", raise_gone)

        guard._terminate_previous_backend(pid_file)  # must not raise

    def test_inspection_error_is_swallowed(self, pid_file, monkeypatch):
        pid_file.write_text("999", encoding="utf-8")

        def raise_denied(pid):
            raise psutil.AccessDenied(pid)

        monkeypatch.setattr(guard.psutil, "Process", raise_denied)

        guard._terminate_previous_backend(pid_file)  # must not raise

    def test_escalates_to_kill_when_terminate_times_out(
        self,
        pid_file,
        monkeypatch,
    ):
        pid_file.write_text("999", encoding="utf-8")
        proc = _proc()
        proc.wait.side_effect = psutil.TimeoutExpired(
            guard._TERMINATE_TIMEOUT_SECONDS,
            pid=999,
        )
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: proc)

        guard._terminate_previous_backend(pid_file)

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_vanishing_mid_terminate_is_not_an_error(
        self,
        pid_file,
        monkeypatch,
    ):
        pid_file.write_text("999", encoding="utf-8")
        proc = _proc()
        proc.terminate.side_effect = psutil.NoSuchProcess(999)
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: proc)

        guard._terminate_previous_backend(pid_file)

        proc.kill.assert_not_called()

    def test_terminate_failure_is_logged_not_raised(
        self,
        pid_file,
        monkeypatch,
    ):
        pid_file.write_text("999", encoding="utf-8")
        proc = _proc()
        proc.terminate.side_effect = psutil.AccessDenied(999)
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: proc)

        guard._terminate_previous_backend(pid_file)  # must not raise


class TestWritePid:
    def test_writes_current_pid_as_text(self, pid_file):
        guard._write_pid(pid_file, 4242)
        assert pid_file.read_text(encoding="utf-8") == "4242"

    def test_creates_missing_parent_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / guard.PID_FILENAME
        guard._write_pid(target, 7)
        assert target.read_text(encoding="utf-8") == "7"


class TestReconcileSingletonBackend:
    def test_records_the_current_pid(self, tmp_path):
        guard.reconcile_singleton_backend(tmp_path)

        recorded = (tmp_path / guard.PID_FILENAME).read_text(encoding="utf-8")
        assert recorded == str(os.getpid())

    def test_terminates_the_orphan_then_records_itself(
        self,
        tmp_path,
        monkeypatch,
    ):
        pid_file = tmp_path / guard.PID_FILENAME
        pid_file.write_text("999", encoding="utf-8")
        orphan = _proc()
        monkeypatch.setattr(
            guard.psutil,
            "Process",
            lambda pid: orphan if pid == 999 else None,
        )

        guard.reconcile_singleton_backend(tmp_path)

        orphan.terminate.assert_called_once()
        assert pid_file.read_text(encoding="utf-8") == str(os.getpid())

    def test_creates_the_working_dir_if_absent(self, tmp_path):
        target = tmp_path / "not-yet-created"
        guard.reconcile_singleton_backend(target)
        assert (target / guard.PID_FILENAME).is_file()

    def test_accepts_a_str_path(self, tmp_path):
        guard.reconcile_singleton_backend(str(tmp_path))
        assert (tmp_path / guard.PID_FILENAME).is_file()

    def test_never_raises_when_terminate_explodes(self, tmp_path, monkeypatch):
        """Contract: a failure here must not block backend startup."""
        (tmp_path / guard.PID_FILENAME).write_text("999", encoding="utf-8")

        def explode(pid):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(guard.psutil, "Process", explode)

        guard.reconcile_singleton_backend(tmp_path)  # must not raise

        # It must still record the current pid.
        assert (tmp_path / guard.PID_FILENAME).read_text(
            encoding="utf-8",
        ) == str(os.getpid())

    def test_never_raises_when_recording_explodes(self, monkeypatch, tmp_path):
        def deny(self, *a, **kw):
            raise OSError("read-only fs")

        monkeypatch.setattr(Path, "write_text", deny)

        guard.reconcile_singleton_backend(tmp_path)  # must not raise
