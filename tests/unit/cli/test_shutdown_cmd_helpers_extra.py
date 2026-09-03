# -*- coding: utf-8 -*-
"""Supplementary tests for shutdown CLI process helpers.

Covers _backend_port resolution, _pid_exists (unix os.kill path),
_wait_for_pid_exit, _child_pids_unix (pgrep parsing), and
_listening_pids_for_port (lsof/fuser fallback), which the first
shutdown backfill pass left uncovered.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace


from qwenpaw.cli import shutdown_cmd as sc


# ---------------------------------------------------------------------------
# _backend_port
# ---------------------------------------------------------------------------


class TestBackendPort:
    def test_explicit_port_wins(self):
        ctx = SimpleNamespace(obj={"port": 8088})
        assert sc._backend_port(ctx, 9999) == 9999

    def test_context_port_used(self):
        ctx = SimpleNamespace(obj={"port": 7777})
        assert sc._backend_port(ctx, None) == 7777

    def test_default_when_no_context(self):
        ctx = SimpleNamespace(obj=None)
        assert sc._backend_port(ctx, None) == 8088

    def test_string_port_coerced(self):
        ctx = SimpleNamespace(obj={"port": "6666"})
        assert sc._backend_port(ctx, None) == 6666


# ---------------------------------------------------------------------------
# _pid_exists (unix)
# ---------------------------------------------------------------------------


class TestPidExists:
    def test_invalid_pid_returns_false(self):
        assert sc._pid_exists(0) is False
        assert sc._pid_exists(-1) is False

    def test_own_process_exists(self):
        import os

        assert sc._pid_exists(os.getpid()) is True

    def test_dead_pid_returns_false(self, monkeypatch):
        def fake_kill(pid, sig):
            raise OSError("no such process")

        monkeypatch.setattr(sc.os, "kill", fake_kill)
        assert sc._pid_exists(999999) is False


# ---------------------------------------------------------------------------
# _wait_for_pid_exit
# ---------------------------------------------------------------------------


class TestWaitForPidExit:
    def test_already_exited_returns_true(self, monkeypatch):
        monkeypatch.setattr(sc, "_pid_exists", lambda pid: False)
        assert sc._wait_for_pid_exit(1, 1.0, 0.05) is True

    def test_still_alive_returns_false(self, monkeypatch):
        monkeypatch.setattr(sc, "_pid_exists", lambda pid: True)
        assert sc._wait_for_pid_exit(1, 0.1, 0.02) is False

    def test_exit_during_wait(self, monkeypatch):
        calls = {"n": 0}

        def flaky(pid):
            calls["n"] += 1
            return calls["n"] < 2

        monkeypatch.setattr(sc, "_pid_exists", flaky)
        assert sc._wait_for_pid_exit(1, 5.0, 0.01) is True


# ---------------------------------------------------------------------------
# _child_pids_unix
# ---------------------------------------------------------------------------


class TestChildPidsUnix:
    def _pgrep_result(self, output):
        return SimpleNamespace(stdout=output, returncode=0)

    def test_direct_children(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[2] == "100":
                return self._pgrep_result("200\n201\n")
            return self._pgrep_result("")

        monkeypatch.setattr(sc.subprocess, "run", fake_run)
        result = sc._child_pids_unix(100)
        assert result == {200, 201}

    def test_recursive_grandchildren(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            pid = cmd[2]
            return {
                "100": self._pgrep_result("200"),
                "200": self._pgrep_result("300"),
                "300": self._pgrep_result(""),
            }.get(pid, self._pgrep_result(""))

        monkeypatch.setattr(sc.subprocess, "run", fake_run)
        assert sc._child_pids_unix(100) == {200, 300}

    def test_non_numeric_tokens_skipped(self, monkeypatch):
        monkeypatch.setattr(
            sc.subprocess,
            "run",
            lambda cmd, **kw: self._pgrep_result("abc\n123\nxyz\n"),
        )
        assert sc._child_pids_unix(1) == {123}

    def test_pgrep_failure_returns_empty(self, monkeypatch):
        def boom(cmd, **kwargs):
            raise OSError("pgrep missing")

        monkeypatch.setattr(sc.subprocess, "run", boom)
        assert sc._child_pids_unix(100) == set()

    def test_cycle_guard_no_infinite_loop(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            pid = cmd[2]
            # 100 -> 200 -> 100 (cycle)
            if pid == "100":
                return self._pgrep_result("200")
            if pid == "200":
                return self._pgrep_result("100")
            return self._pgrep_result("")

        monkeypatch.setattr(sc.subprocess, "run", fake_run)
        result = sc._child_pids_unix(100)
        assert result == {200, 100}


# ---------------------------------------------------------------------------
# _listening_pids_for_port (unix: lsof then fuser fallback)
# ---------------------------------------------------------------------------


class TestListeningPidsForPort:
    def _run_result(self, stdout):
        return SimpleNamespace(stdout=stdout, returncode=0)

    def test_lsof_pids_returned(self, monkeypatch):
        monkeypatch.setattr(sc.sys, "platform", "linux")
        monkeypatch.setattr(
            sc.subprocess,
            "run",
            lambda cmd, **kw: self._run_result("1234\n5678\n"),
        )
        assert sc._listening_pids_for_port(8088) == {1234, 5678}

    def test_lsof_empty_falls_to_fuser(self, monkeypatch):
        monkeypatch.setattr(sc.sys, "platform", "linux")
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd[0])
            if cmd[0] == "lsof":
                return self._run_result("")
            return self._run_result("9999\n")

        monkeypatch.setattr(sc.subprocess, "run", fake_run)
        assert sc._listening_pids_for_port(8088) == {9999}
        assert calls == ["lsof", "fuser"]

    def test_both_empty_returns_empty(self, monkeypatch):
        monkeypatch.setattr(sc.sys, "platform", "linux")
        monkeypatch.setattr(
            sc.subprocess,
            "run",
            lambda cmd, **kw: self._run_result(""),
        )
        assert sc._listening_pids_for_port(8088) == set()

    def test_lsof_missing_fuser_missing(self, monkeypatch):
        monkeypatch.setattr(sc.sys, "platform", "linux")

        def boom(cmd, **kw):
            raise OSError("command not found")

        monkeypatch.setattr(sc.subprocess, "run", boom)
        assert sc._listening_pids_for_port(8088) == set()

    def test_non_numeric_tokens_filtered(self, monkeypatch):
        monkeypatch.setattr(sc.sys, "platform", "linux")
        monkeypatch.setattr(
            sc.subprocess,
            "run",
            lambda cmd, **kw: self._run_result("abc\n42\n"),
        )
        assert sc._listening_pids_for_port(8088) == {42}


# ---------------------------------------------------------------------------
# _stop_pid_set
# ---------------------------------------------------------------------------


class TestStopPidSet:
    def test_all_stopped(self, monkeypatch):
        monkeypatch.setattr(sc, "_terminate_pid", lambda pid, **kw: True)
        stopped, failed = sc._stop_pid_set({3, 1, 2})
        assert stopped == [1, 2, 3]  # sorted
        assert failed == []

    def test_mixed_results(self, monkeypatch):
        monkeypatch.setattr(
            sc,
            "_terminate_pid",
            lambda pid, **kw: pid != 2,
        )
        stopped, failed = sc._stop_pid_set({1, 2, 3})
        assert stopped == [1, 3]
        assert failed == [2]

    def test_empty_set(self, monkeypatch):
        monkeypatch.setattr(sc, "_terminate_pid", lambda pid, **kw: True)
        stopped, failed = sc._stop_pid_set(set())
        assert stopped == []
        assert failed == []
