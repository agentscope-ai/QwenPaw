# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Scroll construction, workspace ownership and cancellation regressions."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

import qwenpaw.agents.context as context_mod
from qwenpaw.runtime.builder import AgentBuilder, _resolve_react_iterations
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config.config import LightContextConfig


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
    ["same", "path", "native", "discard", "shutdown"],
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

        if reload_kind == "shutdown":
            with pytest.raises(RuntimeError, match="incomplete stop"):
                await old_manager.stop_all(final=True)
            # Final shutdown cannot cut off the request's last durable write.
            assert not store.closed
            store.append(
                session_id="second",
                entry=LogEntry(kind="model_turn", content="last write"),
            )
            assert store.count("second") == 2
            with pytest.raises(RuntimeError, match="shutting down"):
                store.acquire()
            managers[1].close()
            assert store.closed
            return

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
