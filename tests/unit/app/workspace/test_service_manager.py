# -*- coding: utf-8 -*-
"""Strict-stop lifecycle tests for workspace services."""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.workspace.service_manager import (
    ServiceDescriptor,
    ServiceManager,
)
from qwenpaw.app.workspace.workspace import Workspace


@pytest.mark.asyncio
async def test_required_clean_stop_failure_is_propagated():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))

    class _StuckService:
        async def stop(self) -> None:
            raise RuntimeError("worker is still alive")

    descriptor = ServiceDescriptor(
        name="mail_monitor",
        stop_method="stop",
        require_clean_stop=True,
    )
    manager.register(descriptor)
    manager.services[descriptor.name] = _StuckService()

    with pytest.raises(RuntimeError, match="worker is still alive"):
        await manager.stop_all()


@pytest.mark.asyncio
async def test_candidate_cleanup_preserves_only_borrowed_services():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))
    borrowed = SimpleNamespace(close=AsyncMock())
    candidate_owned = SimpleNamespace(close=AsyncMock())
    ordinary = SimpleNamespace(close=AsyncMock())

    for name, service, reusable in (
        ("borrowed", borrowed, True),
        ("candidate_owned", candidate_owned, True),
        ("ordinary", ordinary, False),
    ):
        manager.register(
            ServiceDescriptor(
                name=name,
                stop_method="close",
                reusable=reusable,
            ),
        )
        manager.services[name] = service

    manager.reused_services.add("borrowed")

    await manager.stop_all(final=True, preserve_reused=True)

    borrowed.close.assert_not_awaited()
    candidate_owned.close.assert_awaited_once_with()
    ordinary.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workspace_cleans_up_services_after_partial_start_failure(
    monkeypatch,
    tmp_path,
):
    closed = AsyncMock()

    class _StartedService:
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            await closed()

    class _FailingService:
        async def start(self) -> None:
            raise RuntimeError("later service failed")

        async def close(self) -> None:
            return None

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    workspace._service_manager.register(
        ServiceDescriptor(
            name="started",
            service_class=_StartedService,
            start_method="start",
            stop_method="close",
            reusable=True,
            priority=1,
            concurrent_init=False,
        ),
    )
    workspace._service_manager.register(
        ServiceDescriptor(
            name="failing",
            service_class=_FailingService,
            start_method="start",
            stop_method="close",
            priority=2,
            concurrent_init=False,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    with pytest.raises(RuntimeError, match="later service failed"):
        await workspace.start()

    closed.assert_awaited_once_with()
    assert workspace._started is False
    assert workspace._start_attempted is False

    # A second stop remains a no-op after the partial cleanup completed.
    await workspace.stop()
    closed.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workspace_cancels_concurrent_starts_before_cleanup(
    monkeypatch,
    tmp_path,
):
    slow_start_entered = asyncio.Event()
    failure_raised = asyncio.Event()
    slow_start_cancelled = asyncio.Event()
    state = SimpleNamespace(active=False, closed=False)

    class _SlowService:
        async def start(self) -> None:
            slow_start_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                slow_start_cancelled.set()
                raise

        async def close(self) -> None:
            state.active = False
            state.closed = True

    class _FailingService:
        async def start(self) -> None:
            await slow_start_entered.wait()
            failure_raised.set()
            raise RuntimeError("concurrent service failed")

        async def close(self) -> None:
            return None

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    for name, service_class in (
        ("slow", _SlowService),
        ("failing", _FailingService),
    ):
        workspace._service_manager.register(
            ServiceDescriptor(
                name=name,
                service_class=service_class,
                start_method="start",
                stop_method="close",
                priority=1,
                concurrent_init=True,
            ),
        )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    start_task = asyncio.create_task(workspace.start())
    await failure_raised.wait()

    with pytest.raises(RuntimeError, match="concurrent service failed"):
        await asyncio.wait_for(start_task, timeout=0.5)

    assert slow_start_cancelled.is_set()
    assert state.closed is True
    assert state.active is False


@pytest.mark.asyncio
async def test_workspace_cleans_up_when_start_is_cancelled(
    monkeypatch,
    tmp_path,
):
    blocking_start_entered = asyncio.Event()
    closed = AsyncMock()

    class _StartedService:
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            await closed()

    class _BlockingService:
        async def start(self) -> None:
            blocking_start_entered.set()
            await asyncio.Event().wait()

        async def close(self) -> None:
            return None

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    for priority, name, service_class in (
        (1, "started", _StartedService),
        (2, "blocking", _BlockingService),
    ):
        workspace._service_manager.register(
            ServiceDescriptor(
                name=name,
                service_class=service_class,
                start_method="start",
                stop_method="close",
                priority=priority,
                concurrent_init=False,
            ),
        )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    start_task = asyncio.create_task(workspace.start())
    await blocking_start_entered.wait()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    closed.assert_awaited_once_with()
    assert workspace._started is False
    assert workspace._start_attempted is False
