# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Continuation fencing, destination receipts, busy chats and recovery."""

import asyncio
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.pawapp.tasks import (
    ExecutorEvent,
    ExecutorRunRef,
    TaskStore,
    TaskStoreError,
)
from qwenpaw.pawapp.tasks.continuation import (
    ContinuationWorker,
    prepare_turn,
)
from qwenpaw.pawapp.tasks.continuation_store import ContinuationQueue
from qwenpaw.runtime._state_utils import StateProxy
from tests.unit.pawapp.test_task_runtime import (
    host as host_fixture,
    settled,
    BODY,
    ACTION,
    PREFIX,
    SCOPE,
)

host = host_fixture


@pytest.fixture
async def setup(host, tmp_path):
    origins = host.app.state.pawapp_task_origins
    workspace = await origins.manager.get_agent("sales")
    workspace.agent_id = "sales"
    workspace.config = SimpleNamespace(backend="qwenpaw", language="en")
    workspace.session = SafeJSONSession(str(tmp_path / "sessions"))
    workspace.task_tracker = TaskTracker()
    workspace.chat_manager.mark_chat_finished = AsyncMock()
    summarizer = AsyncMock(return_value="Data analysis completed: 42.")
    worker = ContinuationWorker(
        host.app.state.pawapp_tasks,
        origins,
        summarizer=summarizer,
        interval=0.01,
    )
    now = [1000.0]
    worker.queue.clock = lambda: now[0]
    yield SimpleNamespace(
        host=host,
        workspace=workspace,
        worker=worker,
        now=now,
        summarizer=summarizer,
    )
    await worker.aclose()


async def submit(setup, *, request_id="one", engagement="delegated"):
    response = await setup.host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json={
            **BODY,
            "request_id": request_id,
            "engagement": engagement,
            "chat_id": "direct" if engagement == "direct" else "main",
        },
    )
    assert response.status_code == 202
    return await settled(setup.host, response.json()["task"]["task_id"])


async def history(setup):
    return await setup.workspace.session.get_session_state_dict(
        "main-session",
        "alice",
        "console",
    )


@pytest.mark.asyncio
async def test_delivers_once_and_direct_tasks_never_wake_main_chat(setup):
    await submit(setup, request_id="direct", engagement="direct")
    assert await setup.worker.queue.claim() is None
    task = await submit(setup)
    claim = await setup.worker.queue.claim()
    assert claim.summary["text_result"] == "42"
    await setup.worker.deliver(claim)
    saved = await history(setup)
    messages = saved["agent"]["state"]["context"]
    assert len(messages) == 1
    assert messages[0]["id"] == claim.run_id
    assert messages[0]["content"][0]["text"] == "Data analysis completed: 42."
    assert (
        messages[0]["metadata"]["pawapp_continuation"]["summary"]["status"]
        == "succeeded"
    )
    assert claim.run_id in saved["pawapp_continuation_receipts"]
    assert await setup.worker.queue.claim() is None
    assert not [
        d
        for d in await setup.host.store.pending_deliveries(
            SCOPE,
            task.handle.task_id,
        )
        if d.kind == "continuation"
    ]
    setup.workspace.chat_manager.mark_chat_finished.assert_awaited_once()


@pytest.mark.asyncio
async def test_busy_chat_queues_without_attaching_or_starting_another_turn(
    setup,
):
    await submit(setup)
    release = asyncio.Event()

    async def existing(_payload):
        await release.wait()
        yield "data: existing\n\n"

    tracker = setup.workspace.task_tracker
    existing_queue, _ = await tracker.attach_or_start("main", None, existing)
    claim = await setup.worker.queue.claim()
    await setup.worker.deliver(claim)
    assert tracker._runs["main"].queues == [existing_queue]
    setup.summarizer.assert_not_awaited()
    assert not await history(setup)
    release.set()
    async for _ in tracker.stream_from_queue(existing_queue, "main"):
        pass
    setup.now[0] += 2
    await setup.worker.deliver(await setup.worker.queue.claim())
    setup.summarizer.assert_awaited_once()
    assert len((await history(setup))["agent"]["state"]["context"]) == 1


@pytest.mark.asyncio
async def test_concurrent_claims_serialize_chat_and_fence_expired_workers(
    setup,
):
    await submit(setup, request_id="one")
    await submit(setup, request_id="two")
    queue = setup.worker.queue
    other = ContinuationQueue(
        await TaskStore.open(setup.host.store.path),
        clock=queue.clock,
    )
    claims = await asyncio.gather(queue.claim(), other.claim())
    old = next(claim for claim in claims if claim is not None)
    assert sum(claim is not None for claim in claims) == 1
    setup.now[0] += 61
    new = await other.claim()
    assert new.task_id == old.task_id and new.token != old.token
    with pytest.raises(TaskStoreError, match="continuation_lease_lost"):
        await queue.prepare(old, prepare_turn(old, "stale"))
    with pytest.raises(TaskStoreError, match="continuation_lease_lost"):
        await queue.renew(old)
    with pytest.raises(TaskStoreError, match="continuation_lease_lost"):
        await queue.commit(old, lambda _: pytest.fail("stale write"))
    await queue.release(old, reason="stale")
    await other.renew(new)
    await other.prepare(new, prepare_turn(new, "first"))
    await setup.workspace.session.commit_task_continuation(other, new)
    following = await queue.claim()
    assert following.task_id != new.task_id


@pytest.mark.asyncio
async def test_restart_reuses_prepared_summary_without_recomputing(setup):
    await submit(setup)
    claim = await setup.worker.queue.claim()
    await setup.worker.queue.prepare(claim, prepare_turn(claim, "saved"))
    setup.now[0] += 61
    setup.worker.queue = ContinuationQueue(
        await TaskStore.open(setup.host.store.path),
        clock=lambda: setup.now[0],
    )
    retry = await setup.worker.queue.claim()
    assert retry.prepared is not None
    await setup.worker.deliver(retry)
    setup.summarizer.assert_not_awaited()
    assert (await history(setup))["agent"]["state"]["context"][0]["content"][
        0
    ]["text"] == "saved"


@pytest.mark.asyncio
async def test_crash_after_session_write_before_ack_does_not_duplicate(
    setup,
    monkeypatch,
):
    await submit(setup)
    queue = setup.worker.queue
    claim = await queue.claim()
    await queue.prepare(claim, prepare_turn(claim, "durable"))
    original = queue._owned
    calls = []

    def crash_after_write(connection, current):
        calls.append(True)
        if len(calls) == 2:
            raise OSError("injected crash after destination write")
        return original(connection, current)

    monkeypatch.setattr(queue, "_owned", crash_after_write)
    with pytest.raises(OSError, match="injected crash"):
        await setup.workspace.session.commit_task_continuation(queue, claim)
    assert len((await history(setup))["agent"]["state"]["context"]) == 1
    setup.now[0] += 61
    setup.worker.queue = ContinuationQueue(
        await TaskStore.open(setup.host.store.path),
        clock=lambda: setup.now[0],
    )
    await setup.worker.deliver(await setup.worker.queue.claim())
    setup.summarizer.assert_not_awaited()
    assert len((await history(setup))["agent"]["state"]["context"]) == 1
    assert await setup.worker.queue.claim() is None


@pytest.mark.asyncio
async def test_receipts_survive_regular_session_saves(setup):
    proxy = StateProxy()
    proxy.data = {
        "state": AgentState(
            context=[
                Msg(
                    name="alice",
                    role="user",
                    content=[TextBlock(text="Analyze sales")],
                ),
            ],
        ).model_dump(mode="json"),
        "mode_state": {"custom": "preserved"},
    }
    await setup.workspace.session.save_session_state(
        "main-session",
        "alice",
        "console",
        agent=proxy,
    )
    await submit(setup)
    claim = await setup.worker.queue.claim()
    await setup.worker.deliver(claim)
    state = await history(setup)
    assert len(state["agent"]["state"]["context"]) == 2
    assert state["agent"]["state"]["context"][0]["content"][0]["text"] == (
        "Analyze sales"
    )
    assert state["agent"]["mode_state"] == {"custom": "preserved"}
    proxy.data = state["agent"]
    await setup.workspace.session.save_session_state(
        "main-session",
        "alice",
        "console",
        agent=proxy,
    )
    assert (
        claim.run_id in (await history(setup))["pawapp_continuation_receipts"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("deny", ["grant", "owner", "disabled", "backend"])
async def test_delivery_rechecks_current_authority(setup, deny):
    await submit(setup)
    claim = await setup.worker.queue.claim()
    if deny == "grant":
        setup.host.policy_path.unlink()
    elif deny == "owner":
        setup.host.chats["main"] = setup.host.chats["main"].model_copy(
            update={"user_id": "bob"},
        )
    elif deny == "disabled":
        setup.worker.origins.enabled.return_value = False
    else:
        setup.workspace.config.backend = "other"
    await setup.worker.deliver(claim)
    setup.summarizer.assert_not_awaited()
    assert not await history(setup)


@pytest.mark.asyncio
async def test_shutdown_cancels_owned_producer_and_leaves_job_recoverable(
    setup,
):
    await submit(setup)
    entered = asyncio.Event()

    async def slow(*_args):
        entered.set()
        await asyncio.Event().wait()

    setup.worker.summarizer = slow
    await setup.worker.start()
    await asyncio.wait_for(entered.wait(), 3)
    await setup.worker.aclose()
    assert await setup.workspace.task_tracker.get_status("main") == "idle"
    assert not await history(setup)
    assert await setup.worker.queue.claim() is not None


@pytest.mark.asyncio
async def test_user_stop_does_not_automatically_restart_summary(setup):
    await submit(setup)
    entered = asyncio.Event()

    async def slow(*_args):
        entered.set()
        await asyncio.Event().wait()

    setup.worker.summarizer = slow
    task = asyncio.create_task(
        setup.worker.deliver(await setup.worker.queue.claim()),
    )
    await asyncio.wait_for(entered.wait(), 3)
    await setup.workspace.task_tracker.request_stop("main")
    await asyncio.wait_for(task, 3)
    setup.now[0] += 1000
    assert await setup.worker.queue.claim() is None
    assert not await history(setup)
    # Stopping this summary must not block future tasks in the same chat.
    following = await submit(setup, request_id="following")
    next_claim = await setup.worker.queue.claim()
    assert next_claim.task_id == following.handle.task_id
    setup.worker.summarizer = setup.summarizer
    await setup.worker.deliver(next_claim)
    assert len((await history(setup))["agent"]["state"]["context"]) == 1


@pytest.mark.asyncio
async def test_stop_before_producer_starts_halts_job(setup, monkeypatch):
    await submit(setup)
    tracker = setup.workspace.task_tracker
    original = tracker.attach_or_start

    async def start_then_stop(*args, **kwargs):
        queue, started = await original(*args, **kwargs)
        producer = await tracker.task_for_subscriber("main", queue)
        producer.cancel()
        return queue, started

    monkeypatch.setattr(tracker, "attach_or_start", start_then_stop)
    await asyncio.wait_for(
        setup.worker.deliver(await setup.worker.queue.claim()),
        3,
    )
    setup.summarizer.assert_not_awaited()
    assert not await history(setup)
    setup.now[0] += 1000
    assert await setup.worker.queue.claim() is None


@pytest.mark.asyncio
async def test_stop_waits_for_session_commit_before_releasing_chat(
    setup,
    monkeypatch,
):
    from qwenpaw.app.chats import session as session_module

    await submit(setup)
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    original = session_module.write_json_atomic

    def slow_write(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=10):
            raise TimeoutError("test did not release session writer")
        return original(*args, **kwargs)

    monkeypatch.setattr(session_module, "write_json_atomic", slow_write)
    delivery = asyncio.create_task(
        setup.worker.deliver(await setup.worker.queue.claim()),
    )
    try:
        await asyncio.wait_for(entered.wait(), 3)
        stop = asyncio.create_task(
            setup.workspace.task_tracker.request_stop("main"),
        )
        done, _ = await asyncio.wait({stop}, timeout=0.03)
        assert not done
        assert (
            await setup.workspace.task_tracker.get_status("main") == "running"
        )
    finally:
        release.set()
        await asyncio.wait_for(delivery, 3)
    await stop
    assert len((await history(setup))["agent"]["state"]["context"]) == 1
    assert await setup.worker.queue.claim() is None


@pytest.mark.asyncio
async def test_model_failure_retries_are_bounded(setup):
    await submit(setup)
    setup.summarizer.side_effect = RuntimeError("provider failed")
    for _ in range(4):
        await setup.worker.deliver(await setup.worker.queue.claim())
        setup.now[0] += 10
    assert setup.summarizer.await_count == 3
    assert await setup.worker.queue.claim() is None
    assert not await history(setup)


@pytest.mark.asyncio
async def test_v2_migration_recovers_existing_outbox(setup):
    await submit(setup)
    with sqlite3.connect(setup.host.store.path) as db:
        db.execute("DROP TABLE task_continuations")
        db.execute("PRAGMA user_version = 2")
    queue = ContinuationQueue(await TaskStore.open(setup.host.store.path))
    claim = await queue.claim()
    assert claim.summary["status"] == "succeeded"
    assert claim.summary["text_result"] == "42"


@pytest.mark.asyncio
async def test_live_subscribers_only_see_committed_summary(setup):
    await submit(setup)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*_args):
        entered.set()
        await release.wait()
        return "Visible after commit"

    setup.worker.summarizer = slow
    delivery = asyncio.create_task(
        setup.worker.deliver(await setup.worker.queue.claim()),
    )
    await asyncio.wait_for(entered.wait(), 3)
    tracker = setup.workspace.task_tracker
    queue = await tracker.attach("main")
    # Reconnect marker, but no speculative model output.
    assert "replay_end" in await queue.get()
    assert queue.empty()
    assert not await history(setup)
    release.set()
    events = []
    async for data in tracker.stream_from_queue(queue, "main"):
        assert (await history(setup))["agent"]["state"]["context"]
        events.append(json.loads(data.removeprefix("data: ")))
    await delivery
    assert events[-1]["object"] == "response"
    assert events[-1]["status"] == "completed"
    assert any(e.get("text") == "Visible after commit" for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared", [False, True])
async def test_resolved_waiting_event_does_not_prompt_for_stale_input(
    setup,
    prepared,
):
    origin = await setup.worker.origins.resolve(SCOPE, "delegated", "main")
    task = await setup.host.store.create(
        SCOPE,
        ACTION,
        request_id="waiting",
        inputs=BODY["inputs"],
        origin=origin,
    )
    run = ExecutorRunRef(executor_id="engine", session_id="s", run_id="r")
    await setup.host.store.begin_submission(SCOPE, task.handle.task_id)
    await setup.host.store.record_accepted(SCOPE, task.handle.task_id, run)
    for index, status in enumerate(("waiting_for_input", "succeeded")):
        await setup.host.store.apply_event(
            SCOPE,
            task.handle.task_id,
            ExecutorEvent(
                run_ref=run,
                sequence=index,
                cursor=str(index),
                status=status,
                text_result="42" if index else "partial",
                detail={
                    "input_request": {
                        "request_id": "clarification-1",
                        "questions": [
                            {
                                "question": "Which period?",
                                "options": [
                                    {"label": "Q1"},
                                    {"label": "Q2"},
                                ],
                            },
                        ],
                    },
                }
                if index == 0
                else {},
            ),
        )
        if index == 0 and prepared:
            claim = await setup.worker.queue.claim()
            await setup.worker.queue.prepare(
                claim,
                prepare_turn(claim, "Stale question"),
            )
            setup.now[0] += 61
    await setup.worker.deliver(await setup.worker.queue.claim())
    setup.summarizer.assert_not_awaited()
    assert (await history(setup))["agent"]["state"]["context"] == []
    await setup.worker.deliver(await setup.worker.queue.claim())
    setup.summarizer.assert_awaited_once()
