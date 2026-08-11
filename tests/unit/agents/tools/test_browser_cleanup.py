# -*- coding: utf-8 -*-
"""Unit tests for owned-browser process tree cleanup helpers."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.agents.tools import browser_control as bc


def test_cmdline_matches_owned_browser_by_user_data_dir(tmp_path: Path) -> None:
    user_data = tmp_path / "browser" / "user_data"
    user_data.mkdir(parents=True)
    cmdline = [
        str(tmp_path / "chrome.exe"),
        f"--user-data-dir={user_data}",
        "--remote-debugging-port=9333",
    ]
    assert bc._cmdline_matches_owned_browser(cmdline, str(user_data), 9333)
    assert bc._cmdline_matches_owned_browser(cmdline, str(user_data), None)
    assert not bc._cmdline_matches_owned_browser(cmdline, str(user_data), 9444)


def test_cmdline_rejects_unrelated_process(tmp_path: Path) -> None:
    user_data = tmp_path / "browser" / "user_data"
    user_data.mkdir(parents=True)
    cmdline = [
        "notepad.exe",
        f"--user-data-dir={user_data}",
    ]
    assert not bc._cmdline_matches_owned_browser(cmdline, str(user_data), None)


def test_managed_browser_meta_roundtrip(tmp_path: Path) -> None:
    state = {
        "workspace_id": "ws-1",
        "workspace_dir": str(tmp_path),
        "user_data_dir": str(tmp_path / "browser" / "user_data"),
        "browser_pid": 4242,
        "cdp_url": "http://127.0.0.1:9333",
    }
    bc._persist_managed_browser_meta(state)
    meta = bc._read_managed_browser_meta(state)
    assert meta is not None
    assert meta["pid"] == 4242
    assert meta["cdp_port"] == 9333
    assert Path(meta["user_data_dir"]) == Path(state["user_data_dir"])
    bc._clear_managed_browser_meta(state)
    assert bc._read_managed_browser_meta(state) is None


def test_collect_candidates_ignores_stale_pid(monkeypatch, tmp_path: Path) -> None:
    user_data = tmp_path / "browser" / "user_data"
    user_data.mkdir(parents=True)
    state = {
        "workspace_id": "ws-1",
        "workspace_dir": str(tmp_path),
        "user_data_dir": str(user_data),
        "browser_pid": 111,
        "_orphan_browser_pid": 111,
        "cdp_url": "http://127.0.0.1:9333",
    }
    bc._persist_managed_browser_meta(state)

    monkeypatch.setattr(bc, "_pid_is_active", lambda pid: pid == 111)
    monkeypatch.setattr(
        bc,
        "_pid_matches_owned_browser",
        lambda pid, user_data_dir, cdp_port=None: False,
    )
    monkeypatch.setattr(bc, "_find_owned_browser_pids", lambda *_a, **_k: [])

    assert bc._collect_owned_browser_candidate_pids(state) == []


def test_terminate_process_tree_sync_kills_children(monkeypatch) -> None:
    killed: list[int] = []

    class FakeProc:
        def __init__(self, pid: int, children=None):
            self.pid = pid
            self._children = children or []

        def children(self, recursive=False):  # noqa: ARG002
            return list(self._children)

        def terminate(self):
            killed.append(("term", self.pid))

        def kill(self):
            killed.append(("kill", self.pid))

    child = FakeProc(2)
    parent = FakeProc(1, children=[child])

    def fake_process(pid: int):
        if pid == 1:
            return parent
        if pid == 2:
            return child
        raise bc.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(bc.psutil, "Process", fake_process)
    monkeypatch.setattr(
        bc.psutil,
        "wait_procs",
        lambda procs, timeout=None: (list(procs), []),  # noqa: ARG005
    )
    monkeypatch.setattr(bc, "_pid_is_active", lambda _pid: False)

    assert bc._terminate_process_tree_sync(1) is True
    assert ("term", 2) in killed
    assert ("term", 1) in killed


@pytest.mark.asyncio
async def test_dispose_retains_meta_when_owned_stop_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = bc._make_fresh_state("ws-1", str(tmp_path))
    state["owned_browser_process"] = True
    state["browser_pid"] = 5555
    state["cdp_url"] = "http://127.0.0.1:9333"
    state["user_data_dir"] = str(tmp_path / "browser" / "user_data")
    state["playwright"] = SimpleNamespace()
    state["browser"] = SimpleNamespace(close=lambda: None)
    state["context"] = SimpleNamespace(close=lambda: None)

    async def fake_stop_owned(_state):
        return False

    async def fake_stop_pw(_pw, cleanup_errors=None, label=""):  # noqa: ARG001
        return True

    monkeypatch.setattr(bc, "_stop_owned_browser_process", fake_stop_owned)
    monkeypatch.setattr(bc, "_stop_playwright_instance", fake_stop_pw)
    monkeypatch.setattr(bc, "_USE_SYNC_PLAYWRIGHT", False)

    result = await bc._dispose_browser_state(state, "test")
    assert result["fully_cleaned"] is False
    assert state.get("_orphan_browser_pid") == 5555
    meta = bc._read_managed_browser_meta(state)
    assert meta is not None
    assert meta["pid"] == 5555
