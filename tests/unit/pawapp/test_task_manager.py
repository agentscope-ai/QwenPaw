# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.pawapp.task`.

Covers the SSE channel (buffering, close sentinel, keepalive), the task
record bookkeeping and the TaskManager lifecycle: creation with the
``ctx._sse_channel`` injection, success/error completion events,
streaming, and both cleanup paths.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import patch


from qwenpaw.pawapp import task as task_mod
from qwenpaw.pawapp.task import (
    SSEChannel,
    TaskManager,
    TaskRecord,
    get_task_manager,
)


class _Ctx:
    """Stand-in PawApp context receiving the injected SSE channel."""


def _payload(text: str = "data: ") -> dict[str, Any]:
    """Strip the SSE framing and parse the JSON body."""
    return json.loads(text.removeprefix("data: ").strip())


async def _drain(channel: SSEChannel, limit: int = 20) -> list[str]:
    """Collect channel output until it ends (bounded for safety)."""
    events: list[str] = []
    async for event in channel:
        events.append(event)
        if len(events) >= limit:
            break
    return events


# ---------------------------------------------------------------------------
# SSEChannel
# ---------------------------------------------------------------------------


class TestSSEChannelSendAndClose:
    async def test_event_is_serialised_as_sse_data(self):
        channel = SSEChannel()
        await channel.send_event({"type": "progress", "step": 1})
        channel.close()

        events = await _drain(channel)

        assert len(events) == 1
        assert events[0].startswith("data: ")
        assert events[0].endswith("\n\n")
        assert _payload(events[0]) == {"type": "progress", "step": 1}

    async def test_unicode_is_not_escaped(self):
        channel = SSEChannel()
        await channel.send_event({"text": "泰哥"})
        channel.close()

        events = await _drain(channel)

        assert "泰哥" in events[0]

    async def test_send_after_close_is_dropped(self):
        channel = SSEChannel()
        channel.close()
        await channel.send_event({"type": "late"})

        assert channel.is_closed is True
        # Only the close sentinel is queued; no data event follows.
        assert await _drain(channel) == []

    async def test_full_buffer_drops_event_without_raising(self):
        channel = SSEChannel(max_buffer=1)
        await channel.send_event({"n": 1})
        await channel.send_event({"n": 2})  # buffer full -> dropped
        channel.close()

        events = await _drain(channel)

        assert [_payload(e) for e in events] == [{"n": 1}]

    async def test_close_on_full_buffer_is_swallowed(self):
        channel = SSEChannel(max_buffer=1)
        await channel.send_event({"n": 1})

        channel.close()  # sentinel cannot be queued; must not raise

        assert channel.is_closed is True

    async def test_close_unblocks_waiting_consumer(self):
        channel = SSEChannel()
        collected: list[str] = []

        async def consumer():
            async for event in channel:
                collected.append(event)

        worker = asyncio.create_task(consumer())
        await asyncio.sleep(0)
        await channel.send_event({"type": "one"})
        channel.close()
        await asyncio.wait_for(worker, timeout=5)

        assert [_payload(e) for e in collected] == [{"type": "one"}]

    async def test_closed_and_empty_channel_ends_iteration(self):
        channel = SSEChannel()
        channel.close()
        # Drain the sentinel so the queue is empty and closed.
        await _drain(channel)

        assert await _drain(channel) == []

    async def test_idle_channel_emits_keepalive_then_stops(self):
        channel = SSEChannel()
        real_wait_for = asyncio.wait_for
        calls = {"n": 0}

        async def fake_wait_for(awaitable, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # Cancel the pending get so no task is left dangling.
                awaitable.close()
                raise asyncio.TimeoutError
            return await real_wait_for(awaitable, timeout=1)

        with patch.object(task_mod.asyncio, "wait_for", fake_wait_for):
            await channel.send_event({"type": "after-keepalive"})
            channel.close()
            events = await _drain(channel)

        assert events[0] == ": keepalive\n\n"
        assert _payload(events[1]) == {"type": "after-keepalive"}

    async def test_sentinel_is_not_yielded_as_an_event(self):
        channel = SSEChannel()
        channel.close()

        events = await _drain(channel)

        assert events == []

    def test_is_closed_defaults_to_false(self):
        assert SSEChannel().is_closed is False

    async def test_multiple_events_keep_order(self):
        channel = SSEChannel()
        for index in range(5):
            await channel.send_event({"n": index})
        channel.close()

        events = await _drain(channel)

        assert [_payload(e)["n"] for e in events] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# TaskRecord
# ---------------------------------------------------------------------------


class TestTaskRecord:
    def test_initial_state(self):
        channel = SSEChannel()

        record = TaskRecord(
            task_id="t1",
            app_id="app",
            channel=channel,
        )

        assert record.task_id == "t1"
        assert record.app_id == "app"
        assert record.channel is channel
        assert record.result is None
        assert record.error is None
        assert record.done is False

    def test_created_at_uses_monotonic_clock(self):
        before = time.monotonic()
        record = TaskRecord("t", "a", SSEChannel())
        after = time.monotonic()

        assert before <= record.created_at <= after


# ---------------------------------------------------------------------------
# TaskManager.create_task
# ---------------------------------------------------------------------------


class TestCreateTask:
    async def test_returns_unique_ids_and_registers_record(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            return "done"

        first = await manager.create_task("app", handler, _Ctx(), {})
        second = await manager.create_task("app", handler, _Ctx(), {})

        assert first != second
        assert manager.get_task(first).app_id == "app"
        assert manager.get_task(second) is not manager.get_task(first)
        await asyncio.sleep(0.01)

    async def test_ctx_receives_sse_channel(self):
        manager = TaskManager()
        ctx = _Ctx()

        async def handler(_ctx, **_params):
            return None

        await manager.create_task("app", handler, ctx, {})

        assert isinstance(ctx._sse_channel, SSEChannel)
        assert (
            ctx._sse_channel
            is manager.get_task(
                _only_task_id(manager),
            ).channel
        )
        await asyncio.sleep(0.01)

    async def test_handler_receives_ctx_and_params(self):
        manager = TaskManager()
        seen = {}
        ctx = _Ctx()

        async def handler(received_ctx, **params):
            seen["ctx"] = received_ctx
            seen["params"] = params
            return "ok"

        task_id = await manager.create_task(
            "app",
            handler,
            ctx,
            {"script": "x", "retries": 2},
        )
        await _wait_done(manager, task_id)

        assert seen["ctx"] is ctx
        assert seen["params"] == {"script": "x", "retries": 2}

    async def test_successful_task_records_result_and_done_event(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            return {"value": 7}

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        events = await _collect_stream(manager, task_id)

        record = manager.get_task(task_id)
        assert record.result == {"value": 7}
        assert record.error is None
        assert record.done is True
        assert events[-1] == {"type": "done", "data": {"value": 7}}

    async def test_channel_is_closed_after_success(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            return "ok"

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        await _collect_stream(manager, task_id)

        assert manager.get_task(task_id).channel.is_closed is True

    async def test_pushed_events_precede_done_event(self):
        manager = TaskManager()

        async def handler(ctx, **_params):
            await ctx._sse_channel.send_event({"type": "progress", "n": 1})
            await ctx._sse_channel.send_event({"type": "progress", "n": 2})
            return "finished"

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        events = await _collect_stream(manager, task_id)

        assert [event["type"] for event in events] == [
            "progress",
            "progress",
            "done",
        ]

    async def test_failing_task_records_error_event(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            raise ValueError("kaboom")

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        events = await _collect_stream(manager, task_id)

        record = manager.get_task(task_id)
        assert record.error == "kaboom"
        assert record.result is None
        assert record.done is True
        assert events[-1] == {"type": "error", "message": "kaboom"}

    async def test_failing_task_still_closes_channel(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            raise RuntimeError("boom")

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        await _collect_stream(manager, task_id)

        assert manager.get_task(task_id).channel.is_closed is True

    async def test_sync_handler_exception_is_captured(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            raise KeyError("missing")

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        events = await _collect_stream(manager, task_id)

        assert events[-1]["type"] == "error"
        assert "missing" in events[-1]["message"]


# ---------------------------------------------------------------------------
# TaskManager.stream / get_task
# ---------------------------------------------------------------------------


class TestStreamAndGetTask:
    async def test_unknown_task_yields_error_event(self):
        manager = TaskManager()

        events = [event async for event in manager.stream("nope")]

        assert len(events) == 1
        assert _payload(events[0]) == {
            "type": "error",
            "message": "Task not found",
        }

    async def test_get_task_returns_none_for_unknown_id(self):
        assert TaskManager().get_task("ghost") is None

    async def test_stream_yields_handler_events(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            return "result"

        task_id = await manager.create_task("app", handler, _Ctx(), {})

        events = [event async for event in manager.stream(task_id)]

        assert _payload(events[-1]) == {"type": "done", "data": "result"}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    async def test_cleanup_task_removes_record(self):
        manager = TaskManager()

        async def handler(_ctx, **_params):
            return None

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        await _wait_done(manager, task_id)

        manager.cleanup_task(task_id)

        assert manager.get_task(task_id) is None

    def test_cleanup_task_unknown_id_is_noop(self):
        manager = TaskManager()

        manager.cleanup_task("ghost")

        assert manager.get_task("ghost") is None

    async def test_cleanup_old_tasks_only_removes_aged_done_records(self):
        manager = TaskManager()
        now = time.monotonic()

        async def handler(_ctx, **_params):
            return None

        aged = await manager.create_task("app", handler, _Ctx(), {})
        await _wait_done(manager, aged)
        fresh = await manager.create_task("app", handler, _Ctx(), {})
        await _wait_done(manager, fresh)

        manager.get_task(aged).created_at = now - 7200
        manager.get_task(fresh).created_at = now - 10

        manager.cleanup_old_tasks(max_age_seconds=3600)

        assert manager.get_task(aged) is None
        assert manager.get_task(fresh) is not None

    async def test_cleanup_old_tasks_keeps_running_tasks(self):
        manager = TaskManager()
        release = asyncio.Event()

        async def handler(_ctx, **_params):
            await release.wait()
            return None

        task_id = await manager.create_task("app", handler, _Ctx(), {})
        await asyncio.sleep(0)
        # A running task with an ancient creation time must survive.
        manager.get_task(task_id).created_at = time.monotonic() - 99999

        manager.cleanup_old_tasks(max_age_seconds=1)

        assert manager.get_task(task_id) is not None
        release.set()
        await _wait_done(manager, task_id)

    def test_cleanup_old_tasks_default_window(self):
        manager = TaskManager()
        record = TaskRecord("t", "a", SSEChannel())
        record.done = True
        record.created_at = time.monotonic() - 3601
        manager._tasks["t"] = record

        manager.cleanup_old_tasks()

        assert manager._tasks == {}

    def test_cleanup_old_tasks_on_empty_manager(self):
        manager = TaskManager()

        manager.cleanup_old_tasks()

        assert manager._tasks == {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestGetTaskManager:
    def test_returns_same_instance_across_calls(self):
        with patch.object(task_mod, "_task_manager", None):
            first = get_task_manager()
            second = get_task_manager()

        assert first is second
        assert isinstance(first, TaskManager)

    def test_existing_instance_is_reused(self):
        existing = TaskManager()

        with patch.object(task_mod, "_task_manager", existing):
            assert get_task_manager() is existing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _only_task_id(manager: TaskManager) -> str:
    (task_id,) = manager._tasks
    return task_id


async def _wait_done(manager: TaskManager, task_id: str) -> None:
    """Wait until the spawned task has flipped ``record.done``."""
    for _ in range(200):
        record = manager.get_task(task_id)
        if record is not None and record.done:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {task_id} never completed")


async def _collect_stream(manager: TaskManager, task_id: str) -> list[dict]:
    """Drain the SSE stream of a task into parsed payloads."""
    return [
        _payload(event)
        async for event in manager.stream(task_id)
        if event.startswith("data: ")
    ]
