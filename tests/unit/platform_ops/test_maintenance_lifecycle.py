"""Background work must retain admission until all cleanup has finished."""

import asyncio
from contextlib import asynccontextmanager

import pytest


def test_background_child_keeps_own_operation_and_generator_closes(monkeypatch):
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle

    active = set()

    @asynccontextmanager
    async def operation():
        task = asyncio.current_task()
        active.add(task)
        try:
            yield
        finally:
            active.remove(task)

    monkeypatch.setattr(lifecycle, "operation", operation)
    cleaned = []

    @lifecycle.admitted_stream
    async def stream():
        try:
            yield 1
        finally:
            assert asyncio.current_task() in active
            cleaned.append(True)

    @lifecycle.admitted
    async def child(started, release):
        started.set()
        await release.wait()
        assert asyncio.current_task() in active

    async def scenario():
        iterator = stream()
        assert await anext(iterator) == 1
        await iterator.aclose()
        assert cleaned == [True] and not active
        started, release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(child(started, release))
        await started.wait()
        assert task in active
        release.set()
        await task
        assert not active

    asyncio.run(scenario())


def test_denied_operation_never_enters_background_body(monkeypatch):
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle

    @asynccontextmanager
    async def deny():
        raise TimeoutError("maintenance")
        yield

    monkeypatch.setattr(lifecycle, "operation", deny)

    @lifecycle.admitted
    async def work():
        pytest.fail("Background work ran during maintenance")

    async def scenario():
        with pytest.raises(TimeoutError, match="maintenance"):
            await work()

    asyncio.run(scenario())


def test_tracker_drain_blocks_maintenance_until_producer_finally(monkeypatch, tmp_path):
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle
    from qwenpaw.platform_ops.maintenance import MaintenanceCoordinator
    from qwenpaw.app.task_tracker import TaskTracker

    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.5, poll_interval=0.005)
        monkeypatch.setattr(lifecycle, "operation", coordinator.operation)
        tracker = TaskTracker()
        started, finish, maintained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        writes = []

        async def producer(payload):
            try:
                started.set()
                yield "event"
                await finish.wait()
            finally:
                writes.append("persisted")

        queue, _ = await tracker.attach_or_start("run", {}, producer)
        await started.wait()
        await tracker.detach_subscriber("run", queue)

        async def maintenance():
            async with coordinator.exclusive():
                assert writes == ["persisted"]
                maintained.set()

        task = asyncio.create_task(maintenance())
        await asyncio.sleep(0.025)
        assert not maintained.is_set()
        finish.set()
        await task
        assert maintained.is_set()

    asyncio.run(scenario())


def test_tracker_denied_start_still_finishes_subscribers(monkeypatch):
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle
    from qwenpaw.platform_ops.maintenance import MaintenanceBusy
    from qwenpaw.app.task_tracker import TaskTracker

    @asynccontextmanager
    async def deny():
        raise MaintenanceBusy("platform_maintenance_busy")
        yield

    monkeypatch.setattr(lifecycle, "operation", deny)

    async def producer(payload):
        pytest.fail("must not run")
        yield

    async def scenario():
        tracker = TaskTracker()
        queue, _ = await tracker.attach_or_start("run", {}, producer)
        messages = [
            message async for message in tracker.stream_from_queue(queue, "run")
        ]
        assert any("error" in message for message in messages)
        assert await tracker.get_status("run") == "idle"

    asyncio.run(scenario())


def test_tool_denied_start_closes_result_stream(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle
    from qwenpaw.platform_ops.maintenance import MaintenanceBusy
    from qwenpaw.tool_calls._coordinator import ToolCoordinator

    @asynccontextmanager
    async def deny():
        raise MaintenanceBusy("platform_maintenance_busy")
        yield

    monkeypatch.setattr(lifecycle, "operation", deny)

    async def scenario():
        coordinator = object.__new__(ToolCoordinator)
        entry = SimpleNamespace(
            ctx=SimpleNamespace(tool_call_id="t"),
            stream=SimpleNamespace(close=AsyncMock()),
        )
        await coordinator._run_tool_with_hooks(None, None, entry)
        assert entry.end_state == "error"
        entry.stream.close.assert_awaited_once()
        assert "maintenance" in entry.final_response.content[0].text

    asyncio.run(scenario())


def test_workspace_closes_runtime_before_releasing_admission(monkeypatch):
    from types import SimpleNamespace
    from importlib import import_module
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle

    workspace_module = import_module("qwenpaw.app.workspace.workspace")
    runtime_module = import_module("qwenpaw.runtime")
    active = []
    finished = []

    @asynccontextmanager
    async def operation():
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    async def run(request):
        try:
            yield "event"
        finally:
            assert active
            finished.append(True)

    monkeypatch.setattr(lifecycle, "operation", operation)
    monkeypatch.setattr(
        workspace_module,
        "load_agent_config",
        lambda _: SimpleNamespace(backend="qwenpaw"),
    )
    monkeypatch.setattr(runtime_module, "Runtime", lambda **_: SimpleNamespace(run=run))

    async def scenario():
        workspace = SimpleNamespace(agent_id="a", _app_services=None)
        stream = workspace_module.Workspace.stream_query(workspace, None)
        assert await anext(stream) == "event"
        await stream.aclose()
        assert finished == [True] and not active

    asyncio.run(scenario())


def test_listener_retries_admission_without_running_or_losing_message(
    monkeypatch, tmp_path
):
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle
    from qwenpaw.platform_ops.maintenance import MaintenanceCoordinator

    async def scenario():
        coordinator = MaintenanceCoordinator(
            tmp_path, timeout=0.01, poll_interval=0.001
        )
        monkeypatch.setattr(lifecycle, "operation", coordinator.operation)
        received = []

        @lifecycle.admitted_listener
        async def listener(message):
            received.append(message)

        async with coordinator.exclusive():
            task = asyncio.create_task(listener("retained"))
            await asyncio.sleep(0.035)
            assert received == [] and not task.done()
        await asyncio.wait_for(task, 2)
        assert received == ["retained"]

    asyncio.run(scenario())


@pytest.mark.parametrize("channel", ["wechat", "matrix"])
def test_channel_listener_persistence_waits_for_maintenance(
    monkeypatch, tmp_path, channel
):
    from importlib import import_module
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from qwenpaw.platform_ops import maintenance_lifecycle as lifecycle
    from qwenpaw.platform_ops.maintenance import MaintenanceCoordinator

    module = import_module(f"qwenpaw.app.channels.{channel}.channel")

    async def scenario():
        coordinator = MaintenanceCoordinator(
            tmp_path, timeout=0.01, poll_interval=0.001
        )
        monkeypatch.setattr(lifecycle, "operation", coordinator.operation)
        saved = []
        if channel == "wechat":
            instance = SimpleNamespace(_save_token_to_file=saved.append)
            callback = module.WeChatChannel._persist_login_token(instance, "token")
        else:
            monkeypatch.setattr(module, "SyncResponse", SimpleNamespace)
            instance = SimpleNamespace(
                _client=SimpleNamespace(
                    sync=AsyncMock(return_value=SimpleNamespace(next_batch="cursor"))
                ),
                _save_sync_token=saved.append,
            )
            callback = module.MatrixChannel._sync_once(instance, timeout=1)
        async with coordinator.exclusive():
            task = asyncio.create_task(callback)
            await asyncio.sleep(0.035)
            assert saved == []
        await asyncio.wait_for(task, 2)
        assert saved == (["token"] if channel == "wechat" else ["cursor"])

    asyncio.run(scenario())
