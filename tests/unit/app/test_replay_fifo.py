# -*- coding: utf-8 -*-
"""Completed-message FIFO against the real durable transcript writer."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import TranscriptRecorder
from qwenpaw.app.replay_persistence import ReplayEvent, replay_receipt
from qwenpaw.app.replay_snapshot import ReplayPrefix, materialize_replay
from qwenpaw.app.replay_store import ReplayStore
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.schemas import AgentRequest, Message, RunStatus, TextContent


def wire(value: dict) -> str:
    return f"data: {json.dumps(value)}\n\n"


def response(status: str = "in_progress") -> str:
    return wire(
        {
            "id": "response",
            "object": "response",
            "status": status,
            "output": [],
        },
    )


def message(index: int, *, completed: bool = True) -> Message:
    return Message(
        id=f"message-{index}",
        role="assistant",
        object="message",
        content=[TextContent(text=f"answer-{index}")] if completed else [],
        status=RunStatus.Completed if completed else RunStatus.InProgress,
        sequence_number=100 + index if completed else index + 1,
    )


async def record(recorder, replay, value) -> str:
    await recorder.observe(value)
    event = f"data: {value.model_dump_json()}\n\n"
    replay.append(event, replay_receipt.get())
    return event


def setup(tmp_path: Path):
    store = TranscriptStore(tmp_path / "session.db")
    recorder = TranscriptRecorder(
        store=store,
        request=AgentRequest(
            session_id="session",
            user_id="user",
            channel="console",
        ),
    )
    replay = ReplayStore()
    replay.append(response())
    return store, recorder, replay


@pytest.mark.asyncio
async def test_fifo_restores_evicted_messages_in_creation_order(tmp_path):
    store, recorder, replay = setup(tmp_path)
    try:
        await recorder.start()
        for index in range(12):
            await record(recorder, replay, message(index, completed=False))
        # Completion order differs from creation order, as with tools.
        for position, index in enumerate(reversed(range(12))):
            item = message(index)
            item.sequence_number = 100 + position
            await record(recorder, replay, item)
        prefix = replay.capture()
        assert isinstance(prefix, ReplayPrefix)
        assert len(prefix.messages) == 5
        events = [event async for event in prefix]
        output = json.loads(materialize_replay(events)[0][6:])["output"]
        assert [item["id"] for item in output] == [
            f"message-{index}" for index in range(12)
        ]
        assert [item["content"][0]["text"] for item in output] == [
            f"answer-{index}" for index in range(12)
        ]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_completed_messages_do_not_accumulate_or_return_in_terminal(
    tmp_path,
):
    store, recorder, replay = setup(tmp_path)
    try:
        await recorder.start()
        sizes = []
        for index in range(100):
            await record(recorder, replay, message(index))
            if index >= 10:
                sizes.append(replay.approx_bytes())
        assert max(sizes) - min(sizes) < 1000
        full_terminal = wire(
            {
                "id": "response",
                "object": "response",
                "status": "completed",
                "output": [
                    message(index).model_dump() for index in range(100)
                ],
            },
        )
        replay.append(ReplayEvent(full_terminal, response("completed")))
        prefix = replay.capture()
        assert len(prefix.messages) == 5
        assert prefix.header["status"] == "completed"
        assert replay.approx_bytes() < 10_000
        events = [event async for event in prefix]
        assert (
            len(json.loads(materialize_replay(events)[0][6:])["output"]) == 100
        )
    finally:
        store.close()


@pytest.mark.asyncio
async def test_write_failure_does_not_authorize_fifo(tmp_path):
    store, recorder, replay = setup(tmp_path)
    try:
        await recorder.start()
        for index in range(8):
            await record(recorder, replay, message(index, completed=False))
        with patch.object(store, "upsert_message", side_effect=OSError):
            with pytest.raises(OSError):
                await record(recorder, replay, message(0))
        receipt = replay_receipt.get()
        assert receipt is not None and not receipt.committed
        assert not replay.has_evicted
        assert len(json.loads(list(replay.replay())[0][6:])["output"]) == 8
    finally:
        store.close()


@pytest.mark.asyncio
async def test_pre_message_flush_cannot_acknowledge_completion(tmp_path):
    store, recorder, replay = setup(tmp_path)
    try:
        await recorder.start()
        for index in range(5):
            await record(recorder, replay, message(index))
        await record(recorder, replay, message(5, completed=False))
        await recorder.observe(message(5))
        # Console may flush a pending content event before the full message.
        replay.append(
            wire(
                {
                    "object": "content",
                    "msg_id": "message-5",
                    "type": "text",
                    "delta": True,
                    "text": "partial",
                },
            ),
            replay_receipt.get(),
        )
        assert not replay.has_evicted
        replay.append(
            f"data: {message(5).model_dump_json()}\n\n",
            replay_receipt.get(),
        )
        assert replay.has_evicted
        prefix = replay.capture()
        events = [event async for event in prefix]
        output = json.loads(materialize_replay(events)[0][6:])["output"]
        assert len(output) == 6
        assert output[-1]["content"][0]["text"] == "answer-5"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_subscription_boundary_excludes_future_db_completions(tmp_path):
    store, recorder, _ = setup(tmp_path)
    tracker = TaskTracker()
    ready = asyncio.Event()
    release = asyncio.Event()

    async def stream(_):
        await recorder.start()
        yield response()
        for index in range(8):
            item = message(index)
            await recorder.observe(item)
            yield f"data: {item.model_dump_json()}\n\n"
        ready.set()
        await release.wait()
        item = message(8)
        await recorder.observe(item)
        yield f"data: {item.model_dump_json()}\n\n"

    try:
        await tracker.attach_or_start("chat", None, stream)
        await asyncio.wait_for(ready.wait(), 5)
        prefix, queue = await tracker.attach_materialized("chat")
        release.set()
        event = await asyncio.wait_for(queue.get(), 5)
        assert json.loads(event[6:])["id"] == "message-8"
        assert await asyncio.wait_for(queue.get(), 5) is None
        events = [item async for item in prefix]
        output = json.loads(materialize_replay(events)[0][6:])["output"]
        assert [item["id"] for item in output] == [
            f"message-{index}" for index in range(8)
        ]
    finally:
        release.set()
        await tracker.wait_all_done(timeout=5)
        store.close()


def test_complete_message_replaces_delta_and_partial_survives():
    replay = ReplayStore()
    replay.append(response())
    replay.append(wire(message(0, completed=False).model_dump()))
    replay.append(
        wire(
            {
                "object": "content",
                "msg_id": "message-0",
                "type": "text",
                "delta": True,
                "text": "partial",
                "index": 0,
            },
        ),
    )
    partial = json.loads(list(replay.replay())[0][6:])["output"][0]
    assert partial["content"][0]["text"] == "partial"
    replay.append(wire(message(0).model_dump()))
    complete = json.loads(list(replay.replay())[0][6:])["output"][0]
    assert len(complete["content"]) == 1
    assert complete["content"][0]["text"] == "answer-0"


@pytest.mark.asyncio
@pytest.mark.parametrize("materialized", [False, True])
async def test_router_restores_fifo_for_both_client_versions(
    tmp_path,
    materialized,
):
    from qwenpaw.app.routers.console import _attach_reconnect

    store, recorder, _ = setup(tmp_path)
    tracker = TaskTracker()

    async def stream(_):
        await recorder.start()
        yield response()
        for index in range(9):
            item = message(index)
            await recorder.observe(item)
            yield f"data: {item.model_dump_json()}\n\n"

    try:
        await tracker.attach_or_start("chat", None, stream)
        await tracker.wait_all_done(timeout=5)
        prefix, queue = await _attach_reconnect(
            tracker,
            "chat",
            materialized,
        )
        events = [item async for item in prefix]
        output = json.loads(materialize_replay(events)[0][6:])["output"]
        assert len(output) == 9
        assert json.loads(events[-1][6:]) == {"type": "replay_end"}
        assert await queue.get() is None
    finally:
        store.close()


def test_unfinished_overflow_is_explicit_and_releases_state():
    replay = ReplayStore(max_bytes=1024)
    replay.append(response())
    replay.append(wire(message(0, completed=False).model_dump()))
    replay.append(
        wire(
            {
                "object": "content",
                "msg_id": "message-0",
                "type": "text",
                "delta": True,
                "text": "x" * 2048,
                "index": 0,
            },
        ),
    )
    assert replay.recovery_unavailable
    assert replay.requires_resync
    assert replay.approx_bytes() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.Cancelled, RunStatus.Failed])
async def test_terminal_partial_messages_survive_fifo(tmp_path, status):
    store, recorder, replay = setup(tmp_path)
    try:
        await recorder.start()
        for index in range(9):
            item = message(index)
            item.status = status
            await record(recorder, replay, item)
        prefix = replay.capture()
        events = [event async for event in prefix]
        output = json.loads(materialize_replay(events)[0][6:])["output"]
        assert len(output) == 9
        assert all(item["status"] == status for item in output)
    finally:
        store.close()
