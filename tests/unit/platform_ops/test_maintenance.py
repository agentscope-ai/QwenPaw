# -*- coding: utf-8 -*-
"""维护租约必须协调进程、任务和取消边界。"""

import asyncio
import subprocess
import sys

import pytest

from qwenpaw.platform_ops.maintenance import (
    MaintenanceBusy,
    MaintenanceCoordinator,
    maintenance_active,
)


def test_shared_operations_and_exclusive_gate(tmp_path):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.3, poll_interval=0.005)
        first_entered = asyncio.Event()
        release = asyncio.Event()

        async def reader():
            async with coordinator.operation():
                first_entered.set()
                await release.wait()

        task = asyncio.create_task(reader())
        await first_entered.wait()
        async with coordinator.operation():
            pass
        maintenance_entered = asyncio.Event()

        async def writer():
            async with coordinator.exclusive():
                maintenance_entered.set()

        writer_task = asyncio.create_task(writer())
        await asyncio.sleep(0.03)
        assert not maintenance_entered.is_set()
        with pytest.raises(MaintenanceBusy):
            async with coordinator.operation(timeout=0.03):
                pytest.fail("new readers must not pass a waiting maintenance gate")
        release.set()
        await asyncio.gather(task, writer_task)
        assert maintenance_entered.is_set()

    asyncio.run(scenario())


def test_nested_lease_does_not_grant_background_task_exclusive_access(tmp_path):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.04, poll_interval=0.005)
        async with coordinator.exclusive():
            assert maintenance_active()
            async with coordinator.operation():
                async with coordinator.exclusive():
                    assert maintenance_active()

            async def background():
                assert not maintenance_active()
                with pytest.raises(MaintenanceBusy):
                    async with coordinator.operation():
                        pytest.fail("child task must acquire its own lease")

            await asyncio.create_task(background())
        assert not maintenance_active()
        async with coordinator.operation():
            async with coordinator.operation():
                pass
            with pytest.raises(MaintenanceBusy):
                async with coordinator.exclusive():
                    pass

    asyncio.run(scenario())


def test_cancelled_waiter_and_exception_release_locks(tmp_path):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=1, poll_interval=0.005)
        async with coordinator.operation():
            async def waiting():
                async with coordinator.exclusive():
                    pytest.fail("operation still holds shared lock")
            task = asyncio.create_task(waiting())
            await asyncio.sleep(0.03)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            # A cancelled writer must release its gate while an old reader remains.
            async def second_reader():
                async with coordinator.operation(timeout=0.05):
                    pass
            await asyncio.create_task(second_reader())
        with pytest.raises(ValueError):
            async with coordinator.exclusive():
                raise ValueError("body failed")
        async with coordinator.exclusive():
            pass

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["operation", "exclusive"])
def test_expired_inherited_token_requires_new_lease(tmp_path, mode):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.04, poll_interval=0.005)
        proceed = asyncio.Event()
        async def inherited():
            await proceed.wait()
            assert not maintenance_active()
            with pytest.raises(MaintenanceBusy):
                async with coordinator.operation():
                    pytest.fail("expired token bypassed active maintenance")
        async with getattr(coordinator, mode)():
            task = asyncio.create_task(inherited())
        async with coordinator.exclusive():
            proceed.set()
            await task
    asyncio.run(scenario())


def test_child_shared_lease_outlives_parent_and_passes_pending_gate(tmp_path):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.3, poll_interval=0.005)
        child_start = asyncio.Event()
        child_entered = asyncio.Event()
        child_release = asyncio.Event()
        writer_entered = asyncio.Event()

        async def child():
            await child_start.wait()
            async with coordinator.operation():
                child_entered.set()
                await child_release.wait()

        async def writer():
            async with coordinator.exclusive():
                writer_entered.set()

        # Create the writer without a reader's inherited context.
        writer_start = asyncio.Event()
        async def delayed_writer():
            await writer_start.wait()
            await writer()
        writer_task = asyncio.create_task(delayed_writer())
        async with coordinator.operation():
            child_task = asyncio.create_task(child())
            writer_start.set()
            await asyncio.sleep(0.03)
            child_start.set()
            await asyncio.wait_for(child_entered.wait(), timeout=0.15)
        await asyncio.sleep(0.03)
        assert not writer_entered.is_set()
        child_release.set()
        await asyncio.gather(child_task, writer_task)
        assert writer_entered.is_set()

    asyncio.run(scenario())


def test_default_coordinator_uses_runtime_root_and_multiuser_gate(tmp_path, monkeypatch):
    from qwenpaw import constant
    from qwenpaw.platform_ops.maintenance import exclusive, operation

    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "false")
    async def legacy():
        async with exclusive():
            assert not maintenance_active()
    asyncio.run(legacy())
    assert not (tmp_path / ".maintenance").exists()
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    async def multiuser():
        async with exclusive():
            assert maintenance_active()
            async with operation():
                assert maintenance_active()
    asyncio.run(multiuser())
    assert (tmp_path / ".maintenance" / "data.lock").is_file()


def test_cancelling_active_holder_releases_lease(tmp_path):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.05, poll_interval=0.005)
        entered = asyncio.Event()
        async def holder():
            async with coordinator.exclusive():
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(holder())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with coordinator.exclusive():
            assert maintenance_active()
    asyncio.run(scenario())


def test_generator_closed_in_another_task_releases_file_locks(tmp_path):
    async def scenario():
        coordinator = MaintenanceCoordinator(tmp_path, timeout=0.05, poll_interval=0.005)
        async def stream():
            async with coordinator.operation():
                yield "data"
        iterator = stream()
        assert await anext(iterator) == "data"
        await asyncio.create_task(iterator.aclose())
        # The originating Context retains an inactive token, never authority.
        async with coordinator.exclusive():
            assert maintenance_active()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["operation", "exclusive"])
def test_cross_process_locks_and_process_exit_release(tmp_path, mode):
    code = """
import asyncio, sys
from qwenpaw.platform_ops.maintenance import MaintenanceCoordinator
async def run():
    coordinator = MaintenanceCoordinator(sys.argv[1])
    async with getattr(coordinator, sys.argv[2])():
        print('ready', flush=True)
        await asyncio.to_thread(sys.stdin.readline)
asyncio.run(run())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path), mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        async def while_child_holds():
            coordinator = MaintenanceCoordinator(tmp_path, timeout=0.04, poll_interval=0.005)
            if mode == "operation":
                async with coordinator.operation():
                    pass
            else:
                with pytest.raises(MaintenanceBusy):
                    async with coordinator.operation():
                        pass
            with pytest.raises(MaintenanceBusy):
                async with coordinator.exclusive():
                    pass
        asyncio.run(while_child_holds())
    finally:
        process.kill()
        process.communicate(timeout=10)
    async def after_exit():
        async with MaintenanceCoordinator(tmp_path, timeout=0.1).exclusive():
            pass
    asyncio.run(after_exit())
