# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for bounded ReMe shutdown."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.base_memory_manager import BaseMemoryManager
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_close_is_bounded_when_auto_memory_never_releases_lease(
    monkeypatch,
) -> None:
    manager = object.__new__(ReMeLightMemoryManager)
    BaseMemoryManager.__init__(manager, working_dir="", agent_id="bot")
    manager._lifecycle_writer_lock = asyncio.Lock()
    manager._lifecycle_condition = asyncio.Condition()
    manager._lifecycle_operation = None
    manager._active_reme_jobs = 0
    manager._reme = SimpleNamespace(close=AsyncMock())
    started = asyncio.Event()
    release = asyncio.Event()

    async def stuck_auto_memory(*_args, **_kwargs) -> str:
        async with manager._reme_job_lease():
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
        return "saved"

    manager.auto_memory = stuck_auto_memory
    manager.submit_auto_memory([])
    worker = manager._auto_memory_worker_task
    assert worker is not None
    await started.wait()
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "AUTO_MEMORY_WORKER_CLOSE_TIMEOUT_SECONDS",
        0.01,
    )

    try:
        assert await asyncio.wait_for(manager.close(), timeout=0.2) is False
        manager._reme.close.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(worker, timeout=0.2)
