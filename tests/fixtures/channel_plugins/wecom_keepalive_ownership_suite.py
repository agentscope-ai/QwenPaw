"""Targeted ownership units on real WeComPlatform; no SDK interoperability claim."""

import asyncio
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/wecom"))

from qwenpaw_channel_wecom.platform import WeComPlatform


@pytest.fixture
def platform(tmp_path):
    return WeComPlatform({"workspace_dir": str(tmp_path)}, None, None)


def processing(platform, task):
    platform._processing["handle-A"] = {
        "stream_id": "owned-sid", "final": False, "unknown": False,
    }
    platform._keepalive_tasks["owned-sid"] = task


async def test_cancel_before_first_schedule_removes_only_settled_owner(platform):
    entered = []

    async def pending():
        entered.append(True)
        await asyncio.Event().wait()

    task = asyncio.create_task(pending())
    processing(platform, task)
    assert await platform._cancel_processing("handle-A") == "owned-sid"
    assert task.cancelled()
    assert entered == []
    assert platform._keepalive_tasks == {}


async def test_failed_cleanup_retains_still_live_task_evidence(platform, monkeypatch):
    import qwenpaw_channel_wecom.platform as implementation

    entered, release = asyncio.Event(), asyncio.Event()

    async def refuses_until_released():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(refuses_until_released())
    await entered.wait()
    processing(platform, task)

    async def broken_wait(_task):
        raise RuntimeError("cleanup wait failed")

    monkeypatch.setattr(implementation, "_settle", broken_wait)
    try:
        with pytest.raises(RuntimeError, match="cleanup wait failed"):
            await platform._cancel_processing("handle-A")
        assert not task.done()
        assert platform._keepalive_tasks["owned-sid"] is task
    finally:
        release.set()
        await task


async def test_old_keepalive_finally_cannot_remove_new_task_under_same_sid(platform):
    state = {"stream_id": "owned-sid", "final": False, "unknown": False}
    old = asyncio.create_task(platform._keepalive_processing("handle-A", {}, state))
    platform._keepalive_tasks["owned-sid"] = old
    # Let the actual coroutine enter its first scheduled wait.
    await asyncio.sleep(0)
    replacement = asyncio.create_task(asyncio.Event().wait())
    platform._keepalive_tasks["owned-sid"] = replacement
    try:
        old.cancel()
        with pytest.raises(asyncio.CancelledError):
            await old
        assert platform._keepalive_tasks["owned-sid"] is replacement
        assert not replacement.done()
    finally:
        replacement.cancel()
        await asyncio.gather(replacement, return_exceptions=True)
