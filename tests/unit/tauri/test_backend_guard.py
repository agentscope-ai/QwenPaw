# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for the Tauri single-backend reconciliation guard.

The guard exists because an abnormal exit (crash / OOM / SIGKILL) leaves the
Python sidecar orphaned, and repeated launches then stack up ~500 MB backends
(issue #5550). The PID-reuse check in ``_looks_like_backend`` is the safety
critical part: a recycled PID must never be killed.
"""

import json
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

    def test_keeps_a_backend_whose_owner_is_still_running(
        self,
        pid_file,
        monkeypatch,
    ):
        """🔴 #8000: a second launch must not kill a live instance.

        The recorded backend is a real backend, so the old check passed it
        straight to terminate(). What makes it in use is that the desktop
        process that spawned it is still alive.
        """
        pid_file.write_text('{"pid": 999, "ppid": 111}', encoding="utf-8")
        backend = _proc()
        owner = MagicMock()
        owner.is_running.return_value = True
        owner.status.return_value = psutil.STATUS_RUNNING

        def process(pid):
            if pid == 999:
                return backend
            if pid == 111:
                return owner
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(guard.psutil, "Process", process)

        guard._terminate_previous_backend(pid_file)

        backend.terminate.assert_not_called()
        backend.kill.assert_not_called()

    def test_still_reaps_a_backend_whose_owner_is_gone(
        self,
        pid_file,
        monkeypatch,
    ):
        """The #5550 orphan case: spawner exited, backend leaked."""
        pid_file.write_text('{"pid": 999, "ppid": 111}', encoding="utf-8")
        backend = _proc()

        def process(pid):
            if pid == 999:
                return backend
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(guard.psutil, "Process", process)

        guard._terminate_previous_backend(pid_file)

        backend.terminate.assert_called_once()

    def test_reaps_a_backend_whose_owner_is_a_zombie(
        self,
        pid_file,
        monkeypatch,
    ):
        """A zombie spawner has already exited, so the backend is a leak."""
        pid_file.write_text('{"pid": 999, "ppid": 111}', encoding="utf-8")
        backend = _proc()
        owner = MagicMock()
        owner.is_running.return_value = True
        owner.status.return_value = psutil.STATUS_ZOMBIE
        monkeypatch.setattr(
            guard.psutil,
            "Process",
            lambda pid: backend if pid == 999 else owner,
        )

        guard._terminate_previous_backend(pid_file)

        backend.terminate.assert_called_once()

    def test_owner_liveness_failure_still_reaps(
        self,
        pid_file,
        monkeypatch,
    ):
        """Cannot prove an owner is alive -> keep the legacy reap."""
        pid_file.write_text('{"pid": 999, "ppid": 111}', encoding="utf-8")
        backend = _proc()

        def process(pid):
            if pid == 999:
                return backend
            raise psutil.AccessDenied(pid)

        monkeypatch.setattr(guard.psutil, "Process", process)

        guard._terminate_previous_backend(pid_file)

        backend.terminate.assert_called_once()

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
    def test_writes_pid_and_owner_as_json(self, pid_file):
        guard._write_pid(pid_file, 4242, owner_pid=111)
        assert json.loads(pid_file.read_text(encoding="utf-8")) == {
            "pid": 4242,
            "ppid": 111,
        }

    def test_omits_the_owner_when_unknown(self, pid_file):
        guard._write_pid(pid_file, 4242)
        assert json.loads(pid_file.read_text(encoding="utf-8")) == {
            "pid": 4242,
        }

    def test_omits_a_nonsensical_owner(self, pid_file):
        """A backend cannot be its own spawner."""
        guard._write_pid(pid_file, 4242, owner_pid=4242)
        assert json.loads(pid_file.read_text(encoding="utf-8")) == {
            "pid": 4242,
        }

    def test_creates_missing_parent_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / guard.PID_FILENAME
        guard._write_pid(target, 7, owner_pid=8)
        assert json.loads(target.read_text(encoding="utf-8")) == {
            "pid": 7,
            "ppid": 8,
        }


class TestReadRecordedPids:
    """The pid file carries both the backend and its spawner."""

    def test_reads_pid_and_owner_from_json(self, pid_file):
        pid_file.write_text('{"pid": 999, "ppid": 111}', encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (999, 111)

    def test_json_without_owner_has_no_owner(self, pid_file):
        pid_file.write_text('{"pid": 999}', encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (999, None)

    def test_legacy_bare_integer_has_no_owner(self, pid_file):
        """Older builds wrote a bare pid; they must still be reaped."""
        pid_file.write_text("999", encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (999, None)

    def test_legacy_whitespace_is_tolerated(self, pid_file):
        pid_file.write_text("  999\n", encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (999, None)

    def test_missing_file(self, pid_file):
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_torn_write(self, pid_file):
        pid_file.write_text('{"pid": 99', encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_non_dict_json(self, pid_file):
        pid_file.write_text("[1, 2]", encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_garbage_content(self, pid_file):
        pid_file.write_text("not-a-pid", encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_non_positive_pids_are_dropped(self, pid_file):
        pid_file.write_text('{"pid": 0, "ppid": -3}', encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_non_integer_pids_are_dropped(self, pid_file):
        pid_file.write_text('{"pid": "x", "ppid": null}', encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_empty_file(self, pid_file):
        pid_file.write_text("", encoding="utf-8")
        assert guard._read_recorded_pids(pid_file) == (None, None)

    def test_unreadable_file(self, pid_file):
        pid_file.mkdir()  # reading a directory raises OSError
        assert guard._read_recorded_pids(pid_file) == (None, None)


class TestOwnerIsLive:
    """A backend whose spawner still runs belongs to a live instance."""

    def test_missing_owner_is_not_live(self):
        assert guard._owner_is_live(None) is False

    def test_own_pid_is_not_an_owner(self):
        assert guard._owner_is_live(os.getpid()) is False

    def test_running_process_is_live(self, monkeypatch):
        proc = MagicMock()
        proc.is_running.return_value = True
        proc.status.return_value = psutil.STATUS_RUNNING
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: proc)
        assert guard._owner_is_live(4242) is True

    def test_exited_process_is_not_live(self, monkeypatch):
        proc = MagicMock()
        proc.is_running.return_value = False
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: proc)
        assert guard._owner_is_live(4242) is False

    def test_zombie_spawner_is_not_live(self, monkeypatch):
        """A reaped-but-uncollected spawner owns nothing."""
        proc = MagicMock()
        proc.is_running.return_value = True
        proc.status.return_value = psutil.STATUS_ZOMBIE
        monkeypatch.setattr(guard.psutil, "Process", lambda pid: proc)
        assert guard._owner_is_live(4242) is False

    def test_unknown_process_is_not_live(self, monkeypatch):
        def raise_gone(pid):
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(guard.psutil, "Process", raise_gone)
        assert guard._owner_is_live(4242) is False

    def test_inspection_error_is_not_live(self, monkeypatch):
        def raise_denied(pid):
            raise psutil.AccessDenied(pid)

        monkeypatch.setattr(guard.psutil, "Process", raise_denied)
        assert guard._owner_is_live(4242) is False


class TestReconcileSingletonBackend:
    def test_records_the_current_pid(self, tmp_path):
        guard.reconcile_singleton_backend(tmp_path)

        recorded = json.loads(
            (tmp_path / guard.PID_FILENAME).read_text(encoding="utf-8"),
        )
        assert recorded["pid"] == os.getpid()
        assert recorded.get("ppid") == os.getppid()

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
        assert json.loads(pid_file.read_text(encoding="utf-8"))["pid"] == (
            os.getpid()
        )

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
        assert (
            json.loads(
                (tmp_path / guard.PID_FILENAME).read_text(encoding="utf-8"),
            )["pid"]
            == os.getpid()
        )

    def test_never_raises_when_recording_explodes(self, monkeypatch, tmp_path):
        def deny(self, *a, **kw):
            raise OSError("read-only fs")

        monkeypatch.setattr(Path, "write_text", deny)

        guard.reconcile_singleton_backend(tmp_path)  # must not raise


class TestDoubleLaunchSequence:
    """The #8000 repro: a second launch must not kill the first backend."""

    def test_second_launch_leaves_the_first_backend_alive(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Instance A starts, then instance B starts on the same working dir.

        A's backend is still serving A's live window, so B's reconciliation
        must leave it alone even though it looks exactly like the orphan
        #5550 wants reaped.
        """
        pid_file = tmp_path / guard.PID_FILENAME
        first_backend = _proc()
        first_owner = MagicMock()
        first_owner.is_running.return_value = True
        first_owner.status.return_value = psutil.STATUS_RUNNING

        # Instance A records itself plus the shell that spawned it.
        guard._write_pid(pid_file, 999, owner_pid=111)

        def process(pid):
            if pid == 999:
                return first_backend
            if pid == 111:
                return first_owner
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(guard.psutil, "Process", process)

        # Instance B reconciles before binding its port.
        guard.reconcile_singleton_backend(tmp_path)

        first_backend.terminate.assert_not_called()
        first_backend.kill.assert_not_called()

    def test_relaunch_after_a_crash_still_reaps(
        self,
        tmp_path,
        monkeypatch,
    ):
        """The #5550 guarantee must survive the ownership check."""
        pid_file = tmp_path / guard.PID_FILENAME
        guard._write_pid(pid_file, 999, owner_pid=111)
        orphan = _proc()

        def process(pid):
            if pid == 999:
                return orphan
            # The shell that spawned it is gone: it really is an orphan.
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(guard.psutil, "Process", process)

        guard.reconcile_singleton_backend(tmp_path)

        orphan.terminate.assert_called_once()

    def test_legacy_pid_file_from_an_older_build_still_reaps(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A pre-upgrade pid file has no owner; keep reaping it."""
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
