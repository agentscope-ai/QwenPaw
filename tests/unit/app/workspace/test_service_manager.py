# -*- coding: utf-8 -*-
"""Strict-stop lifecycle tests for workspace services."""
# pylint: disable=protected-access
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


async def _wait_for_thread_event(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0)


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
async def test_workspace_waits_for_sync_constructor_before_cleanup(
    monkeypatch,
    tmp_path,
):
    constructor_entered = threading.Event()
    release_constructor = threading.Event()
    failure_raised = asyncio.Event()
    state = SimpleNamespace(constructed=0, closed=0)

    class _SlowConstructorService:
        def __init__(self) -> None:
            constructor_entered.set()
            release_constructor.wait()
            state.constructed += 1

        def close(self) -> None:
            state.closed += 1

    class _FailingService:
        async def start(self) -> None:
            await _wait_for_thread_event(constructor_entered)
            failure_raised.set()
            raise RuntimeError("concurrent service failed")

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    for name, service_class, start_method, stop_method in (
        ("slow", _SlowConstructorService, None, "close"),
        ("failing", _FailingService, "start", None),
    ):
        workspace._service_manager.register(
            ServiceDescriptor(
                name=name,
                service_class=service_class,
                start_method=start_method,
                stop_method=stop_method,
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
    await asyncio.sleep(0)

    try:
        assert not start_task.done()
        assert "slow" not in workspace._service_manager.services
    finally:
        release_constructor.set()

    with pytest.raises(RuntimeError, match="concurrent service failed"):
        await asyncio.wait_for(start_task, timeout=0.5)

    assert state.constructed == 1
    assert state.closed == 1
    assert "slow" in workspace._service_manager.services


@pytest.mark.asyncio
async def test_workspace_waits_for_sync_start_before_cleanup(
    monkeypatch,
    tmp_path,
):
    start_entered = threading.Event()
    release_start = threading.Event()
    failure_raised = asyncio.Event()
    state = SimpleNamespace(
        start_finished=False,
        stop_called=False,
        start_stop_overlapped=False,
    )

    class _SlowStartService:
        def start(self) -> None:
            start_entered.set()
            release_start.wait()
            state.start_finished = True

        def close(self) -> None:
            state.stop_called = True
            state.start_stop_overlapped = not state.start_finished

    class _FailingService:
        async def start(self) -> None:
            await _wait_for_thread_event(start_entered)
            failure_raised.set()
            raise RuntimeError("concurrent service failed")

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    for name, service_class in (
        ("slow", _SlowStartService),
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
    await asyncio.sleep(0)

    try:
        assert not start_task.done()
        assert state.stop_called is False
    finally:
        release_start.set()

    with pytest.raises(RuntimeError, match="concurrent service failed"):
        await asyncio.wait_for(start_task, timeout=0.5)

    assert state.start_finished is True
    assert state.stop_called is True
    assert state.start_stop_overlapped is False


@pytest.mark.asyncio
async def test_workspace_cleans_up_published_async_factory_on_sibling_failure(
    monkeypatch,
    tmp_path,
):
    factory_created = asyncio.Event()
    closed = AsyncMock()

    class _FactoryResource:
        async def close(self) -> None:
            await closed()

    async def slow_factory(_workspace, _service, publish):
        resource = _FactoryResource()
        publish(resource)
        factory_created.set()
        await asyncio.Event().wait()
        return resource

    async def failing_factory(_workspace, _service, _publish):
        await factory_created.wait()
        raise RuntimeError("concurrent factory failed")

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    for name, factory, stop_method in (
        ("slow", slow_factory, "close"),
        ("failing", failing_factory, None),
    ):
        workspace._service_manager.register(
            ServiceDescriptor(
                name=name,
                post_init=factory,
                stop_method=stop_method,
                priority=1,
                concurrent_init=True,
            ),
        )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    with pytest.raises(RuntimeError, match="concurrent factory failed"):
        await workspace.start()

    assert "slow" in workspace._service_manager.services
    closed.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workspace_cleans_up_published_async_factory_when_cancelled(
    monkeypatch,
    tmp_path,
):
    factory_created = asyncio.Event()
    closed = AsyncMock()

    class _FactoryResource:
        async def close(self) -> None:
            await closed()

    async def blocking_factory(_workspace, _service, publish):
        resource = _FactoryResource()
        publish(resource)
        factory_created.set()
        await asyncio.Event().wait()
        return resource

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    workspace._service_manager.register(
        ServiceDescriptor(
            name="blocking",
            post_init=blocking_factory,
            stop_method="close",
            concurrent_init=False,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    start_task = asyncio.create_task(workspace.start())
    await factory_created.wait()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert "blocking" in workspace._service_manager.services
    closed.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_optional_service_is_cleaned_before_removal():
    closed = AsyncMock()

    class _PartiallyStartedService:
        async def close(self) -> None:
            await closed()

    async def failing_factory(_workspace, _service, publish):
        publish(_PartiallyStartedService())
        raise RuntimeError("optional startup failed")

    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))
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
async def test_optional_cleanup_failure_aborts_workspace_start(
    monkeypatch,
    tmp_path,
):
    close_attempts = 0

    class _PartiallyStartedService:
        async def close(self) -> None:
            nonlocal close_attempts
            close_attempts += 1
            if close_attempts == 1:
                raise RuntimeError("optional cleanup failed")

    service = _PartiallyStartedService()

    async def failing_factory(_workspace, _service, publish):
        publish(service)
        raise RuntimeError("optional startup failed")

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    workspace._service_manager.register(
        ServiceDescriptor(
            name="optional",
            post_init=failing_factory,
            stop_method="close",
            optional=True,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    with pytest.raises(RuntimeError, match="optional cleanup failed"):
        await workspace.start()

    assert not workspace._started
    assert close_attempts == 2
    assert not workspace._service_manager._required_cleanup_services
    # The failed instance remains owned for cleanup, but the workspace never
    # becomes a successfully started candidate that can serve requests.
    assert workspace._service_manager.services["optional"] is service


@pytest.mark.asyncio
async def test_repeated_optional_cleanup_failure_keeps_workspace_retryable(
    monkeypatch,
    tmp_path,
):
    close_attempts = 0

    class _PartiallyStartedService:
        async def close(self) -> None:
            nonlocal close_attempts
            close_attempts += 1
            raise RuntimeError("optional cleanup still failing")

    service = _PartiallyStartedService()

    async def failing_factory(_workspace, _service, publish):
        publish(service)
        raise RuntimeError("optional startup failed")

    workspace = Workspace("agent-1", str(tmp_path))
    workspace._service_manager = ServiceManager(workspace)
    workspace._service_manager.register(
        ServiceDescriptor(
            name="optional",
            post_init=failing_factory,
            stop_method="close",
            optional=True,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(workspace, "_migrate_legacy_weixin_data", lambda: None)

    with pytest.raises(RuntimeError, match="optional cleanup still failing"):
        await workspace.start()

    assert close_attempts == 2
    assert workspace._start_attempted
    assert workspace._service_manager.services["optional"] is service

    with pytest.raises(RuntimeError, match="optional cleanup still failing"):
        await workspace.stop(final=True, preserve_reused=True)

    assert close_attempts == 3
    assert workspace._start_attempted
    assert workspace._service_manager.services["optional"] is service
    assert workspace._service_manager._required_cleanup_services == {
        "optional",
    }


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
