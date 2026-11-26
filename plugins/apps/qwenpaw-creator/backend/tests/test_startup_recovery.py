# -*- coding: utf-8 -*-
"""Startup cancellation must release the prepared root before a retry."""

import asyncio
import threading

import pytest

import dev_main
import main
from services.project_files.facade import creator_file_services


def test_cancelled_standalone_startup_recovers_the_same_root_on_retry(
    tmp_path,
    monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        dev_main,
        "require_creator_data_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        dev_main,
        "ensure_creator_runtime_dependencies",
        lambda: {},
    )
    other_root = tmp_path / "unrelated"
    other = creator_file_services(other_root)

    def wait_in_recovery(_services):
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(
        dev_main,
        "recover_interrupted_source_analysis",
        wait_in_recovery,
    )

    async def start():
        async with dev_main.lifespan(dev_main.app):
            pytest.fail("cancelled startup accepted traffic")

    async def cancel_startup():
        task = asyncio.create_task(start())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(cancel_startup())
        tombstone = tmp_path / ".deleted-on-retry"
        tombstone.mkdir()
        creator_file_services(tmp_path)
        assert not tombstone.exists()
        assert creator_file_services(other_root) is other
    finally:
        dev_main.clear_creator_file_service_registry()


@pytest.mark.parametrize(
    "recovery",
    [
        "recover_interrupted_source_observations",
        "recover_interrupted_source_video_reads",
    ],
)
def test_cancelled_host_startup_joins_task_recovery_before_teardown(
    tmp_path,
    monkeypatch,
    recovery,
):
    entered, release = threading.Event(), threading.Event()
    order = []

    def recover(_services):
        entered.set()
        assert release.wait(5)
        order.append("recovery finished")

    async def start(_services):
        pass

    async def stop():
        order.append("media stopped")

    monkeypatch.setattr(
        main,
        "configure_creator_runtime_environment",
        lambda: None,
    )
    monkeypatch.setattr(main, "require_creator_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        main,
        "ensure_creator_runtime_dependencies",
        lambda: {},
    )
    monkeypatch.setattr(main, "ensure_vendor_libs", lambda: None)
    monkeypatch.setattr(main, "start_file_media_execution_services", start)
    monkeypatch.setattr(main, "start_creator_agent_runtime", start)
    monkeypatch.setattr(main, "shutdown_file_media_execution_services", stop)
    monkeypatch.setattr(main, recovery, recover)

    async def cancel_startup():
        task = asyncio.create_task(main._startup())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.03)
            assert not done
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(cancel_startup())
    assert order == ["recovery finished", "media stopped"]
