# -*- coding: utf-8 -*-
"""Session liveness excludes exited members without stealing leader waits."""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call

import psutil
import pytest

from qwenpaw.plugins.execution.process_tree import ProcessTree


@pytest.mark.skipif(os.name == "nt", reason="POSIX process sessions")
@pytest.mark.parametrize("reapable", [False, True])
def test_session_ignores_zombies_and_reaps_only_owned_descendants(
    monkeypatch,
    reapable,
):
    states = {
        10: psutil.STATUS_ZOMBIE,
        11: psutil.STATUS_ZOMBIE,
        12: psutil.STATUS_DEAD,
        13: psutil.STATUS_SLEEPING,
        20: psutil.STATUS_RUNNING,
    }
    monkeypatch.setattr(psutil, "pids", lambda: list(states))
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(
            create_time=lambda: 1.0,
            status=lambda: states[pid],
        ),
    )
    monkeypatch.setattr(os, "getsid", lambda pid: 10 if pid < 20 else 20)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    reap = Mock(
        return_value=(11, 0),
        side_effect=None if reapable else ChildProcessError(),
    )
    monkeypatch.setattr(os, "waitpid", reap)
    tree = ProcessTree(10, session=True)
    assert tree._session_groups() == {13}
    assert reap.call_args_list == [
        call(11, os.WNOHANG),
        call(12, os.WNOHANG),
    ]
    states[13] = psutil.STATUS_ZOMBIE
    assert not tree.alive()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process sessions")
@pytest.mark.parametrize("missing", [False, True])
def test_status_inspection_race_does_not_hide_live_processes(
    monkeypatch,
    missing,
):
    status = Mock(
        side_effect=(
            psutil.NoSuchProcess(10) if missing else psutil.AccessDenied(10)
        ),
    )
    monkeypatch.setattr(psutil, "pids", lambda: [10])
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(
            create_time=lambda: 1.0,
            status=status,
        ),
    )
    monkeypatch.setattr(os, "getsid", lambda pid: 10)
    monkeypatch.setattr(os, "getpgid", lambda pid: 10)
    tree = ProcessTree(10, session=True)
    if missing:
        assert not tree.alive()
    else:
        with pytest.raises(psutil.AccessDenied):
            tree.alive()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper")
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("separate_group", [False, True])
def test_scope_closes_and_reaps_adopted_zombie(
    asynchronous,
    separate_group,
):
    probe = (
        Path(__file__).resolve().parents[2]
        / "integration"
        / "fixtures"
        / "sdk_zombie_probe.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(probe),
            str(int(asynchronous)),
            str(int(separate_group)),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "ok\n", "")
