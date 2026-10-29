# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Scroll builder I/O and workspace-owned history lifecycle."""

import asyncio
import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock

import qwenpaw.agents.context as context_mod
from qwenpaw.runtime.builder import AgentBuilder, _resolve_react_iterations
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config.config import AgentProfileConfig


def _history_workspace(path):
    ws = Workspace("agent", str(path))
    ws._config = AgentProfileConfig(id="agent", name="Agent")
    descriptor = ws._service_manager.descriptors["history_store"]
    ws._service_manager.descriptors = {"history_store": descriptor}
    return ws


async def _build_for(ws, sid):
    return await AgentBuilder._build_scroll_components(
        SimpleNamespace(workspace=ws, session_id=sid, agent_id="agent"),
        ws.config,
        model=object(),
    )


@pytest.mark.asyncio
async def test_requests_share_store_but_not_context_or_cleanup(
    tmp_path,
    monkeypatch,
):
    checks = []
    original = HistoryStore._check_fts

    def check(store):
        checks.append(store)
        return original(store)

    monkeypatch.setattr(HistoryStore, "_check_fts", check)
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    try:
        parts = await asyncio.gather(
            *(_build_for(ws, str(i)) for i in range(8)),
        )
        managers = [p.context_manager for p in parts]
        assert all(m._history is ws.history_store for m in managers)
        assert len({id(m) for m in managers}) == 8
        assert checks == [ws.history_store]
        # Exercise the real Agent teardown, including request-time retention.
        agent = SimpleNamespace(
            _context_manager=managers[0],
            _agent_config=ws.config,
            _close_decision_compactor=AsyncMock(),
        )
        await QwenPawAgent._close_resources(agent)
        assert not ws.history_store.closed
        await asyncio.gather(
            *(
                asyncio.to_thread(
                    m._history.append,
                    session_id=str(i),
                    entry=LogEntry(kind="model_turn", content=f"session {i}"),
                    dedup_key="same-key-in-each-session",
                )
                for i, m in enumerate(managers[1:], start=1)
            ),
        )
        assert all(ws.history_store.count(str(i)) == 1 for i in range(1, 8))
        assert all(not m._persisted_ids for m in managers)
        later = await _build_for(ws, "later")
        assert later.context_manager._history is ws.history_store
        assert checks == [ws.history_store]
        for m in managers:
            m.close()
        later.context_manager.close()
    finally:
        await ws._service_manager.stop_all(final=True)
    assert ws.history_store.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_caller", [False, True])
async def test_stop_waits_for_request_save_before_closing_history(
    tmp_path,
    cancel_caller,
):
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    ws._started = True
    manager = MultiAgentManager()
    manager.agents["agent"] = ws
    parts = await _build_for(ws, "active")
    cm = parts.context_manager
    store = ws.history_store
    started, saving, release = (asyncio.Event() for _ in range(3))
    saved = []
    completed = []
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(text="partial reply")],
                ),
            ],
        ),
    )

    async def stream(_payload):
        try:
            started.set()
            await asyncio.Future()
            yield "unreachable"
        finally:
            saving.set()
            await release.wait()
            saved.append(await cm._persist_guarded_async(agent))
            cm.close()

    async def finished(_key, _time):
        # TaskTracker completion callbacks also run before service teardown.
        completed.append((store.closed, store.count("active")))

    await ws.task_tracker.attach_or_start(
        "active",
        None,
        stream,
        owner=ws,
        on_finished=finished,
    )
    await started.wait()
    caller = asyncio.create_task(manager.stop_agent("agent"))
    try:
        await asyncio.wait_for(saving.wait(), 1)
        assert not caller.done()
        assert not store.closed
        with pytest.raises(RuntimeError, match="is stopping"):
            await anext(ws.stream_query(SimpleNamespace()))
        if cancel_caller:
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert not store.closed
        release.set()
        assert await asyncio.wait_for(manager.stop_agent("agent"), 1)
        if not cancel_caller:
            assert await caller
        assert saved == [True]
        assert completed == [(False, 1)]
        assert not await ws.task_tracker.has_active_tasks()
        assert store.closed
        with closing(sqlite3.connect(store.path)) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM conversation_history",
                ).fetchone()[0]
                == 1
            )
    finally:
        release.set()
        await ws.task_tracker.request_stop("active")
        await asyncio.gather(caller, return_exceptions=True)
        await manager.stop_agent("agent")


@pytest.mark.asyncio
async def test_stop_does_not_cancel_in_progress_request_cleanup(tmp_path):
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    ws._started = True
    started, saving, release = (asyncio.Event() for _ in range(3))
    saved = []

    async def stream(_payload):
        try:
            started.set()
            await asyncio.Future()
            yield "unreachable"
        finally:
            saving.set()
            await release.wait()
            saved.append(not ws.history_store.closed)

    await ws.task_tracker.attach_or_start("active", None, stream, owner=ws)
    await started.wait()
    active = await ws.task_tracker.snapshot_active_tasks(owner=ws)
    active["active"].cancel("user")
    await saving.wait()
    stopping = asyncio.create_task(ws.stop())
    try:
        async with asyncio.timeout(1):
            while not ws._stopping:
                await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, 1)
        assert saved == [True]
        assert ws.history_store.closed
    finally:
        release.set()
        await asyncio.gather(stopping, return_exceptions=True)


@pytest.mark.asyncio
async def test_retired_workspace_stop_preserves_new_workspace_requests(
    tmp_path,
):
    old = _history_workspace(tmp_path)
    await old._service_manager.start_all()
    old._started = True
    new = _history_workspace(tmp_path)
    new.set_task_tracker(old.task_tracker)
    await new.set_reusable_components(
        old._service_manager.get_reusable_services(),
    )
    await new._service_manager.start_all()
    new._started = True
    store = new.history_store
    assert store is old.history_store
    started = {ws: asyncio.Event() for ws in (old, new)}
    finished = []

    def stream_for(ws, sid):
        async def stream(_payload):
            try:
                started[ws].set()
                await asyncio.Future()
                yield "unreachable"
            finally:
                store.append(
                    session_id=sid,
                    entry=LogEntry(kind="model_turn", content=sid),
                )
                finished.append(sid)

        return stream

    for ws, sid in ((old, "old"), (new, "new")):
        await ws.task_tracker.attach_or_start(
            sid,
            None,
            stream_for(ws, sid),
            owner=ws,
        )
        await started[ws].wait()
    try:
        # Shutdown can retire an old workspace before its normal drain ends.
        await asyncio.wait_for(old.stop(final=False), 1)
        assert finished == ["old"]
        assert not store.closed
        assert await new.task_tracker.get_status("new") == "running"
        assert not new._stopping
        await asyncio.wait_for(new.stop(), 1)
        assert finished == ["old", "new"]
        assert store.closed
    finally:
        await old.task_tracker.request_stop("old")
        await new.task_tracker.request_stop("new")
        await new.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    ["none", "path", "native", "backend", "closed"],
)
async def test_history_service_reload_ownership(tmp_path, changed):
    old = _history_workspace(tmp_path)
    await old._service_manager.start_all()
    original = old.history_store
    new = _history_workspace(tmp_path)
    if changed == "path":
        new.config.running.light_context_config.scroll_config.db_filename = (
            "new.db"
        )
    elif changed == "native":
        new.config.running.light_context_config.strategy = "native"
    elif changed == "backend":
        new.config.backend = "claude"
    elif changed == "closed":
        original.close()
    reusable = old._service_manager.get_reusable_services()
    await new.set_reusable_components(reusable)
    await new._service_manager.start_all()
    try:
        if changed == "none":
            assert new.history_store is original
            # An abandoned reload candidate cannot close the old store.
            await new._service_manager.stop_all(
                final=True,
                preserve_reused=True,
            )
            assert not original.closed
        else:
            assert new.history_store is not original
            if changed != "closed":
                original.append(
                    session_id="old-inflight",
                    entry=LogEntry(kind="model_turn", content="done"),
                )
        MultiAgentManager._mark_rejected_reusable_services_for_cleanup(
            old,
            new,
            reusable,
        )
        await old._service_manager.stop_all(final=False)
        assert original.closed is (changed != "none")
        if new.history_store is not None:
            assert not new.history_store.closed
    finally:
        await new._service_manager.stop_all(final=True)
        original.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", ["native", "backend"])
async def test_history_service_can_be_enabled_on_reload(tmp_path, disabled):
    old = _history_workspace(tmp_path)
    if disabled == "native":
        old.config.running.light_context_config.strategy = "native"
    else:
        old.config.backend = "claude"
    await old._service_manager.start_all()
    assert old.history_store is None
    assert not (tmp_path / "history.db").exists()

    new = _history_workspace(tmp_path)
    await new.set_reusable_components(
        old._service_manager.get_reusable_services(),
    )
    await new._service_manager.start_all()
    try:
        assert isinstance(new.history_store, HistoryStore)
        assert not new.history_store.closed
    finally:
        await new._service_manager.stop_all(final=True)


@pytest.mark.asyncio
async def test_request_uses_new_path_before_reload_without_closing_old(
    tmp_path,
):
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    try:
        old = ws.history_store
        ws.config.running.light_context_config.scroll_config.db_filename = (
            "changed.db"
        )
        parts = await _build_for(ws, "changed")
        temporary = parts.context_manager._history
        assert temporary is not old
        assert temporary.path.name == "changed.db"
        parts.context_manager.close()
        assert temporary.closed
        assert not old.closed
    finally:
        await ws._service_manager.stop_all(final=True)


def test_store_reuse_rejects_replaced_file(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "history.db")
    try:
        assert store.matches_path(store.path)
        original_identity = store._connection_identity
        # Windows cannot replace an open SQLite file; simulate the stat result
        # observed after a restore/replacement on platforms that permit it.
        monkeypatch.setattr(
            store,
            "_file_identity",
            lambda path: (original_identity[0], original_identity[1] + 1),
        )
        assert not store.matches_path(store.path)
    finally:
        store.close()


def test_only_internal_migration_can_raise_react_iterations():
    assert _resolve_react_iterations(100, {}) == 100
    assert (
        _resolve_react_iterations(
            100,
            {"source": "portability_adaptation", "max_react_iterations": 800},
        )
        == 800
    )
    assert (
        _resolve_react_iterations(
            100,
            {
                "source": "portability_adaptation",
                "max_react_iterations": 99_999,
            },
        )
        == 4_000
    )


@pytest.mark.asyncio
async def test_scroll_component_build_runs_in_worker_thread(
    tmp_path,
    monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    loop_thread = threading.get_ident()
    result = object()

    def blocking_build(**_kwargs):
        assert threading.get_ident() != loop_thread
        started.set()
        assert release.wait(timeout=2)
        return result

    monkeypatch.setattr(
        context_mod,
        "build_scroll_components",
        blocking_build,
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(workspace_dir=tmp_path),
        session_id="session",
        agent_id="agent",
    )
    config = SimpleNamespace(id="agent")

    task = asyncio.create_task(
        AgentBuilder._build_scroll_components(
            ctx,
            config,
            model=object(),
        ),
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        scheduled = asyncio.Event()
        asyncio.get_running_loop().call_soon(scheduled.set)
        await asyncio.wait_for(scheduled.wait(), timeout=0.5)
        assert not task.done()
    finally:
        release.set()

    assert await asyncio.wait_for(task, timeout=1) is result
