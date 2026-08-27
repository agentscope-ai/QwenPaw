# -*- coding: utf-8 -*-
"""Cancellation-safe workspace service lifecycle tests."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.workspace.service_manager import (
    ServiceDescriptor,
    ServiceManager,
)
from qwenpaw.app.workspace.workspace import Workspace


async def _wait_for(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0)


@pytest.fixture
def workspace(monkeypatch, tmp_path) -> Workspace:
    instance = Workspace("agent-1", str(tmp_path))
    instance._service_manager = ServiceManager(instance)
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(instance, "_migrate_legacy_weixin_data", lambda: None)
    return instance


def _register(
    workspace: Workspace,
    name: str,
    service_class=None,
    **kwargs,
) -> None:
    workspace._service_manager.register(
        ServiceDescriptor(
            name=name,
            service_class=service_class,
            **kwargs,
        ),
    )


@pytest.mark.asyncio
async def test_required_clean_stop_failure_is_propagated():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))
    service = SimpleNamespace(
        stop=AsyncMock(side_effect=RuntimeError("worker is still alive")),
    )
    descriptor = ServiceDescriptor(
        name="mail_monitor",
        stop_method="stop",
        require_clean_stop=True,
    )
    manager.register(descriptor)
    manager.services[descriptor.name] = service

    with pytest.raises(RuntimeError, match="worker is still alive"):
        await manager.stop_all()


@pytest.mark.asyncio
async def test_candidate_cleanup_preserves_only_borrowed_services():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))
    services = {
        name: SimpleNamespace(close=AsyncMock())
        for name in ("borrowed", "candidate_owned", "ordinary")
    }
    for name, service in services.items():
        manager.register(
            ServiceDescriptor(
                name=name,
                stop_method="close",
                reusable=name != "ordinary",
            ),
        )
        manager.services[name] = service
    manager.reused_services.add("borrowed")

    await manager.stop_all(final=True, preserve_reused=True)

    services["borrowed"].close.assert_not_awaited()
    services["candidate_owned"].close.assert_awaited_once_with()
    services["ordinary"].close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workspace_cleans_up_after_partial_start_failure(workspace):
    closed = AsyncMock()

    class Started:
        async def start(self):
            return None

        async def close(self):
            await closed()

    class Failing:
        async def start(self):
            raise RuntimeError("later service failed")

    _register(
        workspace,
        "started",
        Started,
        start_method="start",
        stop_method="close",
        priority=1,
        concurrent_init=False,
    )
    _register(
        workspace,
        "failing",
        Failing,
        start_method="start",
        priority=2,
        concurrent_init=False,
    )

    with pytest.raises(RuntimeError, match="later service failed"):
        await workspace.start()

    closed.assert_awaited_once_with()
    assert not workspace._started
    assert not workspace._start_attempted


@pytest.mark.asyncio
async def test_concurrent_failure_cancels_sibling_before_cleanup(workspace):
    slow_entered = asyncio.Event()
    slow_cancelled = asyncio.Event()
    closed = AsyncMock()

    class Slow:
        async def start(self):
            slow_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise

        async def close(self):
            await closed()

    class Failing:
        async def start(self):
            await slow_entered.wait()
            raise RuntimeError("concurrent service failed")

    for name, service_class, stop_method in (
        ("slow", Slow, "close"),
        ("failing", Failing, None),
    ):
        _register(
            workspace,
            name,
            service_class,
            start_method="start",
            stop_method=stop_method,
            priority=1,
        )

    with pytest.raises(RuntimeError, match="concurrent service failed"):
        await workspace.start()

    assert slow_cancelled.is_set()
    closed.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocking_phase", ["constructor", "start"])
async def test_cleanup_waits_for_sync_lifecycle_work(
    workspace,
    blocking_phase,
):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    closed = threading.Event()

    class Slow:
        def __init__(self):
            if blocking_phase == "constructor":
                entered.set()
                release.wait()
                finished.set()

        def start(self):
            if blocking_phase == "start":
                entered.set()
                release.wait()
                finished.set()

        def close(self):
            assert finished.is_set()
            closed.set()

    class Failing:
        async def start(self):
            await _wait_for(entered)
            raise RuntimeError("concurrent service failed")

    _register(
        workspace,
        "slow",
        Slow,
        start_method="start",
        stop_method="close",
        priority=1,
    )
    _register(
        workspace,
        "failing",
        Failing,
        start_method="start",
        priority=1,
    )

    task = asyncio.create_task(workspace.start())
    await _wait_for(entered)
    await asyncio.sleep(0)
    try:
        assert not task.done()
        assert not closed.is_set()
    finally:
        release.set()

    with pytest.raises(RuntimeError, match="concurrent service failed"):
        await task
    assert finished.is_set()
    assert closed.is_set()
    assert "slow" in workspace._service_manager.services


@pytest.mark.asyncio
async def test_published_async_factory_is_cleaned_on_sibling_failure(
    workspace,
):
    published = asyncio.Event()
    closed = AsyncMock()

    async def slow_factory(_workspace, _service, publish):
        publish(SimpleNamespace(close=closed))
        published.set()
        await asyncio.Event().wait()

    async def failing_factory(_workspace, _service, _publish):
        await published.wait()
        raise RuntimeError("factory failed")

    for name, factory, stop_method in (
        ("slow", slow_factory, "close"),
        ("failing", failing_factory, None),
    ):
        _register(
            workspace,
            name,
            post_init=factory,
            stop_method=stop_method,
            priority=1,
        )

    with pytest.raises(RuntimeError, match="factory failed"):
        await workspace.start()

    closed.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_optional_service_is_cleaned_before_removal():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))
    closed = AsyncMock()

    async def failing_factory(_workspace, _service, publish):
        publish(SimpleNamespace(close=closed))
        raise RuntimeError("optional startup failed")

    manager.register(
        ServiceDescriptor(
            name="optional",
            post_init=failing_factory,
            stop_method="close",
            optional=True,
        ),
    )

    await manager.start_all()

    closed.assert_awaited_once_with()
    assert "optional" not in manager.services


@pytest.mark.asyncio
async def test_optional_cleanup_failure_remains_retryable(workspace):
    close_attempts = 0

    async def close():
        nonlocal close_attempts
        close_attempts += 1
        raise RuntimeError("optional cleanup failed")

    service = SimpleNamespace(close=close)

    async def failing_factory(_workspace, _service, publish):
        publish(service)
        raise RuntimeError("optional startup failed")

    _register(
        workspace,
        "optional",
        post_init=failing_factory,
        stop_method="close",
        optional=True,
    )

    with pytest.raises(RuntimeError, match="optional cleanup failed"):
        await workspace.start()
    assert close_attempts == 2
    assert workspace._start_attempted
    assert workspace._service_manager.services["optional"] is service

    with pytest.raises(RuntimeError, match="optional cleanup failed"):
        await workspace.stop(final=True, preserve_reused=True)
    assert close_attempts == 3
    assert workspace._start_attempted


@pytest.mark.asyncio
async def test_workspace_cleanup_survives_repeated_cancellation(workspace):
    start_entered = asyncio.Event()
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    close_finished = asyncio.Event()

    class Blocking:
        async def start(self):
            start_entered.set()
            await asyncio.Event().wait()

        async def close(self):
            close_entered.set()
            await release_close.wait()
            close_finished.set()

    _register(
        workspace,
        "blocking",
        Blocking,
        start_method="start",
        stop_method="close",
        concurrent_init=False,
    )

    task = asyncio.create_task(workspace.start())
    await start_entered.wait()
    task.cancel("initial cancellation")
    await close_entered.wait()
    task.cancel("repeated cancellation")
    await asyncio.sleep(0)

    assert not task.done()
    release_close.set()
    with pytest.raises(asyncio.CancelledError, match="initial cancellation"):
        await task
    assert close_finished.is_set()
    assert not workspace._started
    assert not workspace._start_attempted
