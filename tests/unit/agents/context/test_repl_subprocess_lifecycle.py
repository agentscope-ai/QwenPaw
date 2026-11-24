# -*- coding: utf-8 -*-
"""Recall owns its local child until cancellation/timeout cleanup completes."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.agents.context.scroll import repl


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_interrupted_recall_reaps_child(monkeypatch, tmp_path, stop):
    create_subprocess = asyncio.create_subprocess_exec
    started = asyncio.Event()
    children = []

    async def track_child(*args, **kwargs):
        proc = await create_subprocess(*args, **kwargs)
        children.append(proc)
        started.set()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track_child)
    task = asyncio.create_task(
        repl._run_subprocess(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout_s=0.01 if stop == "timeout" else 60,
            cwd=str(tmp_path),
        ),
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, timeout=5)
            assert result == (
                "",
                "recall_history_python timed out after 0.01s",
                -1,
            )
        assert children[0].returncode is not None
        assert children[0].stdout.at_eof()
        assert children[0].stderr.at_eof()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for proc in children:
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()


@pytest.mark.parametrize("already_exited", [False, True])
async def test_repeated_cancellation_finishes_cleanup(
    monkeypatch,
    tmp_path,
    already_exited,
):
    reading, cleaning, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def communicate():
        if not reading.is_set():
            reading.set()
            await asyncio.Event().wait()
        cleaning.set()
        await release.wait()
        return b"", b""

    proc = SimpleNamespace(
        communicate=AsyncMock(side_effect=communicate),
        kill=Mock(side_effect=ProcessLookupError if already_exited else None),
    )
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=proc),
    )
    task = asyncio.create_task(
        repl._run_subprocess(["python"], timeout_s=60, cwd=str(tmp_path)),
    )
    try:
        await asyncio.wait_for(reading.wait(), timeout=5)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        proc.kill.assert_called_once()
        assert proc.communicate.await_count == 2
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
