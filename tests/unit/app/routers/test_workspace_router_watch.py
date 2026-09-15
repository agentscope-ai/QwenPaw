# -*- coding: utf-8 -*-
"""Unit tests for the workspace SSE file-watch endpoint.

Covers the pure-Python polling watcher that replaced ``watchfiles.awatch``
(https://github.com/agentscope-ai/QwenPaw/issues/7721): the baseline
snapshot walker, the snapshot diff, the background poller thread, and the
SSE generator (connected / ready / file_change / heartbeat / disconnect).
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument

from __future__ import annotations

import asyncio
import queue
import threading
import time
from pathlib import Path

import pytest

from qwenpaw.app.routers import workspace as workspace_router
from qwenpaw.app.routers.workspace import (
    _diff_events,
    _poll_watch_worker,
    _scan_snapshot,
    workspace_watch_events,
)


class _FakeRequest:
    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _fast_watch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace_router, "_WATCH_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(workspace_router, "_WATCH_QUEUE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(workspace_router, "_WATCH_HEARTBEAT_SECONDS", 0.2)


# ---------------------------------------------------------------------------
# _scan_snapshot
# ---------------------------------------------------------------------------


def test_scan_snapshot_prunes_ignored_dirs(tmp_path):
    _touch(tmp_path / "src" / "main.py")
    _touch(tmp_path / "src" / "sub" / "mod.py")
    _touch(tmp_path / "node_modules" / "pkg" / "index.js")
    _touch(tmp_path / ".venv" / "lib" / "site.py")
    _touch(tmp_path / ".hidden" / "secret.txt")
    _touch(tmp_path / ".git" / "config")

    snap = _scan_snapshot(tmp_path)
    assert set(snap) == {"src/main.py", "src/sub/mod.py"}
    mtime, size = snap["src/main.py"]
    assert size == 0
    assert mtime > 0


def test_scan_snapshot_missing_root_is_empty(tmp_path):
    assert not _scan_snapshot(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# _diff_events
# ---------------------------------------------------------------------------


def test_diff_events_detects_added_deleted_modified():
    prev = {"a.txt": (1, 10), "b.txt": (1, 10), "c.txt": (1, 10)}
    cur = {"b.txt": (1, 10), "c.txt": (2, 10), "d.txt": (1, 10)}
    events = _diff_events(prev, cur)
    assert events == [
        {"change": "added", "path": "d.txt"},
        {"change": "deleted", "path": "a.txt"},
        {"change": "modified", "path": "c.txt"},
    ]


# ---------------------------------------------------------------------------
# _poll_watch_worker
# ---------------------------------------------------------------------------


def test_poll_worker_ready_changes_done(tmp_path):
    _touch(tmp_path / "a.txt", "1")
    out: queue.Queue[tuple[str, object]] = queue.Queue()
    stop = threading.Event()
    thread = threading.Thread(
        target=_poll_watch_worker,
        args=(tmp_path, out, stop, 0.05),
        daemon=True,
    )
    thread.start()
    try:
        kind, payload = out.get(timeout=2)
        assert kind == "ready"

        _touch(tmp_path / "b.txt", "2")
        kind, payload = out.get(timeout=2)
        assert kind == "changes"
        assert {"change": "added", "path": "b.txt"} in payload

        (tmp_path / "a.txt").write_text("changed")
        kind, payload = out.get(timeout=2)
        assert kind == "changes"
        assert {"change": "modified", "path": "a.txt"} in payload
    finally:
        stop.set()
        thread.join(timeout=2)
        kind, payload = out.get(timeout=2)
        assert kind == "done"


# ---------------------------------------------------------------------------
# workspace_watch_events (SSE generator)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_events_full_flow(tmp_path, monkeypatch):
    _fast_watch_settings(monkeypatch)
    _touch(tmp_path / "a.txt", "1")
    request = _FakeRequest()
    agen = workspace_watch_events(request, tmp_path)

    assert (await anext(agen)) == 'data: {"type": "connected"}\n\n'
    assert (await anext(agen)) == 'data: {"type": "ready"}\n\n'

    _touch(tmp_path / "b.txt", "2")
    msg = await anext(agen)
    assert '"type": "file_change"' in msg
    assert '"added"' in msg and '"b.txt"' in msg

    # heartbeat fires when idle (window shortened by _fast_watch_settings)
    msg = await anext(agen)
    assert msg == ": heartbeat\n\n"

    # disconnect stops the stream
    request.disconnected = True
    with pytest.raises(StopAsyncIteration):
        await anext(agen)
    await agen.aclose()


@pytest.mark.asyncio
async def test_watch_events_loop_responsive_during_slow_scan(
    tmp_path,
    monkeypatch,
):
    """Regression: the initial scan must never block the event loop."""
    monkeypatch.setattr(workspace_router, "_WATCH_QUEUE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(workspace_router, "_WATCH_POLL_INTERVAL_SECONDS", 0.05)

    def slow_scan(_watch_dir):
        time.sleep(0.4)
        return {}

    monkeypatch.setattr(workspace_router, "_scan_snapshot", slow_scan)

    request = _FakeRequest()
    agen = workspace_watch_events(request, tmp_path)
    assert (await anext(agen)) == 'data: {"type": "connected"}\n\n'

    async def tick() -> None:
        await asyncio.sleep(0.1)

    task = asyncio.create_task(tick())
    # Returns when the slow scan finishes (~0.4s); the concurrent task must
    # already be done, proving the loop kept running during the scan.
    msg = await anext(agen)
    assert msg == 'data: {"type": "ready"}\n\n'
    assert task.done()
    await agen.aclose()


@pytest.mark.asyncio
async def test_watch_events_heartbeat_during_scan(tmp_path, monkeypatch):
    """Heartbeats keep flowing while the initial scan is still running."""
    monkeypatch.setattr(workspace_router, "_WATCH_QUEUE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(workspace_router, "_WATCH_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(workspace_router, "_WATCH_HEARTBEAT_SECONDS", 0.15)

    def slow_scan(_watch_dir):
        time.sleep(0.4)
        return {}

    monkeypatch.setattr(workspace_router, "_scan_snapshot", slow_scan)

    request = _FakeRequest()
    agen = workspace_watch_events(request, tmp_path)
    assert (await anext(agen)) == 'data: {"type": "connected"}\n\n'
    # Heartbeats (every 0.15s) must keep arriving while the scan (0.4s) is
    # still in flight — i.e. at least one heartbeat before "ready".
    frames = []
    while True:
        msg = await anext(agen)
        if msg == 'data: {"type": "ready"}\n\n':
            break
        frames.append(msg)
    assert frames
    assert all(m == ": heartbeat\n\n" for m in frames)
    await agen.aclose()
