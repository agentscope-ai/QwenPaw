# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Scroll construction, workspace ownership and cancellation regressions."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from agentscope.message import ToolResultState

import qwenpaw.agents.context as context_mod
from qwenpaw.runtime.builder import AgentBuilder, _resolve_react_iterations
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config.config import LightContextConfig
from qwenpaw.utils.io_utils import run_sync_io


def _history_workspace(tmp_path, filename="history.db", strategy="scroll"):
    ws = Workspace("agent", str(tmp_path))
    lcc = LightContextConfig(strategy=strategy)
    lcc.scroll_config.db_filename = filename
    ws._config = SimpleNamespace(
        id="agent",
        running=SimpleNamespace(light_context_config=lcc),
    )
    # Use the production descriptor without starting unrelated services.
    manager = ws._service_manager
    manager.descriptors = {
        "history_store": manager.descriptors["history_store"],
    }
    return ws


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reload_kind",
    ["same", "path", "native", "discard"],
)
# pylint: disable-next=too-many-statements
async def test_workspace_history_survives_requests_and_reload(
    tmp_path,
    reload_kind,
):
    """Exercise real registration, injection and ownership with SQLite."""

    old = _history_workspace(tmp_path)
    new = _history_workspace(
        tmp_path,
        filename="other.db" if reload_kind == "path" else "history.db",
        strategy="native" if reload_kind == "native" else "scroll",
    )
    old_manager = old._service_manager
    new_manager = new._service_manager
    await old_manager.start_all()
    store = old.history_store
    assert store is not None
    managers = []
    try:
        for session_id in ("first", "second"):
            ctx = SimpleNamespace(workspace=old, session_id=session_id)
            components = await AgentBuilder._build_scroll_components(
                ctx,
                old.config,
                model=None,
            )
            assert components is not None
            cm = components.context_manager
            assert cm._history is store
            managers.append(cm)

        managers[0].close()
        assert not store.closed
        store.append(
            session_id="second",
            entry=LogEntry(kind="model_turn", role="assistant", content="ok"),
        )
        assert store.count("second") == 1

        reusable = old_manager.get_reusable_services()
        await new.set_reusable_components(reusable)
        await new_manager.start_all()
        if reload_kind == "discard":
            await new_manager.stop_all(final=True, preserve_reused=True)
            assert not store.closed
        else:
            MultiAgentManager._mark_rejected_reusable_services_for_cleanup(
                old,
                new,
                reusable,
            )
            # The outgoing request can still write until it finishes.
            assert not store.closed
            managers[1].close()
            await old_manager.stop_all(final=False)
            if reload_kind == "same":
                assert new.history_store is store
                assert not store.closed
                assert new.history_store.count("second") == 1
            else:
                assert store.closed
                assert new.history_store is not store
            await new_manager.stop_all(final=True)
    finally:
        for cm in managers:
            cm.close()
        await old_manager.stop_all(final=True)
        await new_manager.stop_all(final=True)
    assert store.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", [False, True])
async def test_final_stop_cancels_request_and_persists_history(
    tmp_path,
    retired,
):
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    ws._started = ws._start_attempted = True
    multi = MultiAgentManager()
    multi.agents["agent"] = ws
    started = asyncio.Event()
    cancelled = asyncio.Event()
    store = ws.history_store

    async def request(_payload):
        components = await AgentBuilder._build_scroll_components(
            SimpleNamespace(workspace=ws, session_id="s"),
            ws.config,
            model=None,
        )
        assert components is not None
        started.set()
        try:
            await asyncio.Event().wait()  # A cancellable model/tool wait.
            yield "unused"
        finally:
            cancelled.set()
            try:
                await run_sync_io(
                    store.append,
                    session_id="s",
                    entry=LogEntry(kind="model_turn", content="final write"),
                )
            finally:
                await run_sync_io(components.context_manager.close)

    await ws.task_tracker.attach_or_start("request", None, request, owner=ws)
    await asyncio.wait_for(started.wait(), timeout=2)
    if retired:
        replacement = _history_workspace(tmp_path, filename="replacement.db")
        replacement.set_task_tracker(ws.task_tracker)
        await replacement._service_manager.start_all()
        replacement._started = replacement._start_attempted = True
        multi.agents["agent"] = replacement
        multi._mark_rejected_reusable_services_for_cleanup(
            ws,
            replacement,
            ws._service_manager.get_reusable_services(),
        )
        await multi._graceful_stop_old_instance(ws, "agent")
        assert not cancelled.is_set()  # Reload itself must leave it running.
    stopping = asyncio.create_task(multi.stop_agent("agent"))
    try:
        # Bound the assertion without cancelling the shutdown task on failure.
        await asyncio.wait_for(cancelled.wait(), timeout=2)
        assert await asyncio.wait_for(asyncio.shield(stopping), timeout=2)
        assert store.closed and not ws._started
        assert "agent" not in multi.agents
        assert not multi._agent_stop_tasks
        assert not await ws.task_tracker.has_active_tasks()
        from qwenpaw.agents.context.scroll.history import HistoryStore

        reopened = HistoryStore(store.path)
        try:
            assert reopened.count("s") == 1
        finally:
            reopened.close()
    finally:
        await ws.task_tracker.request_stop("request")
        await stopping


@pytest.mark.asyncio
@pytest.mark.parametrize("recall_kind", ["structured", "python"])
async def test_runtime_fts_corruption_is_repaired_on_next_borrow(
    tmp_path,
    monkeypatch,
    recall_kind,
):
    ws = _history_workspace(tmp_path)
    monkeypatch.setenv("QWENPAW_ALLOW_UNSANDBOXED_RECALL", "true")
    ws.config.running.light_context_config.scroll_config.allow_unsandboxed = (
        True
    )
    await ws._service_manager.start_all()
    store = ws.history_store
    components = []
    try:
        if not store._fts:
            pytest.skip("SQLite build lacks FTS5")
        ctx = SimpleNamespace(workspace=ws, session_id="s")
        first = await AgentBuilder._build_scroll_components(
            ctx,
            ws.config,
            model=None,
        )
        assert first is not None
        components.append(first)
        store.append(
            session_id="s",
            agent_id="agent",
            entry=LogEntry(kind="model_turn", content="aardvark"),
        )
        with store._conn:
            store._conn.execute(
                "UPDATE conversation_history_fts_data "
                "SET block=x'00' WHERE id>10",
            )
        if recall_kind == "structured":
            failed = await first.recall_tool(op="search", query="aardvark")
        else:
            failed = await first.repl_tool("ms.search('aardvark')")
        assert failed.state == ToolResultState.ERROR
        first.context_manager.close()
        second = await AgentBuilder._build_scroll_components(
            ctx,
            ws.config,
            model=None,
        )
        assert second is not None
        components.append(second)
        assert second.context_manager._history is store
        result = await second.recall_tool(op="search", query="aardvark")
        assert result.state == ToolResultState.SUCCESS
        assert "aardvark" in result.content[0].text
        assert store.count("s") == 1
        assert not store._fts_check_pending
    finally:
        for component in components:
            component.context_manager.close()
        await ws._service_manager.stop_all(final=True)


@pytest.mark.asyncio
async def test_history_path_change_without_workspace_reload(tmp_path):
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    components = []
    original = ws.history_store
    try:
        ctx = SimpleNamespace(workspace=ws, session_id="s")
        first = await AgentBuilder._build_scroll_components(
            ctx,
            ws.config,
            model=None,
        )
        assert first is not None
        components.append(first)
        # A request sees the edited config before any workspace reload.
        ws.config.running.light_context_config.scroll_config.db_filename = (
            "changed.db"
        )
        second = await AgentBuilder._build_scroll_components(
            ctx,
            ws.config,
            model=None,
        )
        assert second is not None
        components.append(second)
        changed = second.context_manager._history
        assert changed.path == tmp_path / "changed.db"
        assert ws.history_store is original
        for store in (original, changed):
            store.append(
                session_id="s",
                entry=LogEntry(kind="model_turn", content="persisted"),
            )
            assert store.count("s") == 1
        second.context_manager.close()
        assert changed.closed
        assert not original.closed
        assert original.count("s") == 1
    finally:
        for component in components:
            component.context_manager.close()
        await ws._service_manager.stop_all(final=True)


@pytest.mark.asyncio
async def test_cancelled_scroll_build_releases_workspace_history(
    tmp_path,
    monkeypatch,
):
    ws = _history_workspace(tmp_path)
    await ws._service_manager.start_all()
    started = threading.Event()
    release = threading.Event()
    build = context_mod.build_scroll_components

    def blocking_build(**kwargs):
        components = build(**kwargs)
        assert components is not None
        started.set()
        assert release.wait(timeout=5)
        return components

    monkeypatch.setattr(context_mod, "build_scroll_components", blocking_build)
    task = asyncio.create_task(
        AgentBuilder._build_scroll_components(
            SimpleNamespace(workspace=ws, session_id="cancelled"),
            ws.config,
            model=None,
        ),
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await ws._service_manager.stop_all(final=True)
    assert ws.history_store.closed


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
