# -*- coding: utf-8 -*-
# pylint: disable=protected-access,using-constant-test
"""C2 admission behavior exercises real queues and real proxy ACK handling."""

import asyncio
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


async def noop_agent(_request):
    if False:
        yield None


def proxy():
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.app.channels.process_supervisor import LaunchSpec

    return IsolatedChannelProxy(
        noop_agent,
        launch_spec=LaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            code_root=ROOT / "plugins/channel/feishu",
            descriptor_path=ROOT / "plugins/channel/feishu/channel.json",
            source_revision="0" * 64,
            channel_key="feishu",
            instance_id="queue-workspace",
            generation=1,
            qwenpaw_version="2.2.2b4",
            config={"enabled": True},
        ),
    )


def batch(channel, event_id="event-one", *, generation=None):
    from qwenpaw.channel_protocol.models import EventBatchParams, InboundEvent

    spec = channel._launch_spec
    return EventBatchParams(
        "batch:" + event_id,
        (
            InboundEvent(
                event_id=event_id,
                channel_key="feishu",
                instance_id=spec.instance_id,
                generation=generation or spec.generation,
                conversation={"id": "session-one", "type": "private"},
                sender_id="ou_alice",
                acl_sender_id="ou_alice",
                sender_name="Alice",
                content_parts=({"type": "text", "text": "hello"},),
                event_kind="message",
                metadata={
                    "session_id": "session-one",
                    "user_id": "ou_alice",
                    "debounce_key": "session-one",
                    # Complete Driver fixture context;
                    # host treats these as opaque.
                    "feishu_receive_id": "ou_alice",
                    "feishu_receive_id_type": "open_id",
                    "session_webhook": (
                        "https://oapi.dingtalk.com/robot/"
                        "sendBySession?session=old-session"
                    ),
                    "conversation_id": "session-one",
                    "conversation_type": "single",
                },
            ),
        ),
    )


@pytest.mark.asyncio
async def test_scheduled_enqueue_without_actual_queue_is_rejected():
    """Current sync scheduling falsely ACKs a message that has no queue."""
    from qwenpaw.app.channels.manager import ChannelManager

    channel = proxy()
    manager = ChannelManager([channel])
    manager._loop = asyncio.get_running_loop()
    channel.set_enqueue(manager._make_enqueue_cb("feishu"))
    ack = await channel._event_batch(batch(channel), None)
    assert ack["accepted_event_ids"] == []
    assert ack["rejected_events"] == [
        {
            "event_id": "event-one",
            "reason_code": "QUEUE_UNAVAILABLE",
            "retryable": True,
        },
    ]
    assert "event-one" not in channel._accepted


@pytest.mark.asyncio
async def test_real_queue_capacity_deadline_close_and_cancel_do_not_commit():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    entered, release = asyncio.Event(), asyncio.Event()

    async def consumer(queue, *_args):
        entered.set()
        await release.wait()
        await queue.get()

    queues = UnifiedQueueManager(consumer, queue_maxsize=1)
    try:
        first = await queues.admit("feishu", "session", 20, "first")
        await entered.wait()
        assert first.accepted
        rejected = await queues.admit(
            "feishu",
            "session",
            20,
            "full",
            timeout=0.03,
        )
        assert (
            rejected.accepted,
            rejected.reason_code,
            rejected.retryable,
        ) == (False, "QUEUE_CAPACITY_TIMEOUT", True)
        state = queues._queues[("feishu", "session", 20)]
        assert state.queue.qsize() == 1
        guarded = asyncio.Event()

        def guard():
            guarded.set()

        cancelled = asyncio.create_task(
            queues.admit(
                "feishu",
                "session",
                20,
                "cancelled",
                admission_guard=guard,
            ),
        )
        await guarded.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert list(state.queue._queue) == ["first"]
        waiting = asyncio.create_task(
            queues.admit("feishu", "session", 20, "closed"),
        )
        await queues.stop_all()
        outcome = await asyncio.wait_for(waiting, 1)
        assert (outcome.accepted, outcome.reason_code, outcome.retryable) == (
            False,
            "QUEUE_CLOSED",
            True,
        )
        closed = await queues.admit("feishu", "new-session", 20, "late")
        assert closed.reason_code == "QUEUE_CLOSED" and not queues._queues
    finally:
        release.set()
        await queues.stop_all()


@pytest.mark.asyncio
async def test_legacy_enqueue_still_raises_capacity_timeout():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    async def consumer(*_args):
        await asyncio.Event().wait()

    queues = UnifiedQueueManager(consumer, queue_maxsize=1)
    real_admit = queues.admit

    async def short_budget(*args, **kwargs):
        return await real_admit(*args, timeout=0.02, **kwargs)

    queues.admit = (
        short_budget  # Budget instrumentation; actual queue remains real.
    )
    try:
        await queues.enqueue("feishu", "session", 20, "first")
        with pytest.raises(asyncio.TimeoutError):
            await queues.enqueue("feishu", "session", 20, "full")
    finally:
        await queues.stop_all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,reason,retryable",
    [
        ("removed", "CHANNEL_STOPPING", True),
        ("replaced", "STALE_GENERATION", False),
        ("generation", "STALE_GENERATION", False),
    ],
)
async def test_waiting_real_put_rechecks_bound_owner_before_capacity_commit(
    mutation,
    reason,
    retryable,
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    channel = proxy()
    manager = ChannelManager([channel])
    manager._loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), asyncio.Event()

    async def consumer(queue, *args):
        entered.set()
        await release.wait()
        await manager._consume_queue(queue, *args)

    queues = UnifiedQueueManager(consumer, queue_maxsize=1)
    manager._queue_manager = queues
    payload = {
        "session_id": "session-one",
        "content_parts": [{"type": "text", "text": "hello"}],
        "sender_id": "ou_alice",
    }
    try:
        assert (await manager.enqueue_async(channel, payload)).accepted
        await entered.wait()
        task = asyncio.create_task(
            manager.enqueue_async(
                channel,
                {**payload, "id": "late"},
                timeout=1,
            ),
        )
        # Event loop barrier enters capacity wait while the queue stays full.
        await asyncio.sleep(0)
        if mutation == "removed":
            manager.channels.clear()
        elif mutation == "replaced":
            manager.channels = [proxy()]
        else:
            channel._launch_spec = replace(channel._launch_spec, generation=2)
        state = queues._queues[("feishu", "session-one", 20)]
        state.queue.get_nowait()
        result = await asyncio.wait_for(task, 2)
        assert (result.accepted, result.reason_code, result.retryable) == (
            False,
            reason,
            retryable,
        )
        assert state.queue.empty()
    finally:
        release.set()
        await queues.stop_all()


@pytest.mark.asyncio
async def test_admission_deadline_includes_wait_for_queue_allocation_lock():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    async def consumer(*_args):
        await asyncio.Event().wait()

    queues = UnifiedQueueManager(consumer)
    await queues._lock.acquire()
    try:
        result = await asyncio.wait_for(
            queues.admit("feishu", "locked", 20, "payload", timeout=0.02),
            0.3,
        )
        assert (
            not result.accepted
            and result.reason_code == "QUEUE_CAPACITY_TIMEOUT"
        )
        assert not queues._queues
    finally:
        queues._lock.release()
        await queues.stop_all()


@pytest.mark.asyncio
async def test_close_during_allocation_wait_never_starts_new_consumer():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    consumer_started = asyncio.Event()

    async def consumer(*_args):
        consumer_started.set()
        await asyncio.Event().wait()

    queues = UnifiedQueueManager(consumer)
    await queues._lock.acquire()
    waiting = asyncio.create_task(
        queues.admit("feishu", "closing", 20, "payload"),
    )
    await asyncio.sleep(0)
    stopping = asyncio.create_task(queues.stop_all())
    await asyncio.sleep(0)
    try:
        queues._lock.release()
        result = await asyncio.wait_for(waiting, 1)
        await asyncio.wait_for(stopping, 1)
        assert not result.accepted and result.reason_code == "QUEUE_CLOSED"
        assert not consumer_started.is_set() and not queues._queues
    finally:
        if queues._lock.locked():
            queues._lock.release()
        await queues.stop_all()


@pytest.mark.asyncio
async def test_retired_consumer_finally_cannot_forget_replacement_queue():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    retiring, release = asyncio.Event(), asyncio.Event()
    received = []
    calls = 0

    async def consumer(queue, *_args):
        nonlocal calls
        calls += 1
        first = calls == 1
        try:
            while True:
                received.append(await queue.get())
                queue.task_done()
        except asyncio.CancelledError:
            if first:
                retiring.set()
                await release.wait()
            raise

    queues = UnifiedQueueManager(
        consumer,
        idle_timeout=0,
        cleanup_interval=0.001,
    )
    replacement = None
    try:
        assert (
            await queues.admit("feishu", "same-session", 20, "first")
        ).accepted
        queues.start_cleanup_loop()
        await asyncio.wait_for(retiring.wait(), 1)
        assert (
            await queues.admit("feishu", "same-session", 20, "second")
        ).accepted
        replacement = queues._queues[("feishu", "same-session", 20)]
        queues._running = False
        release.set()
        await asyncio.wait_for(queues._cleanup_task, 1)
        assert (
            queues._queues.get(("feishu", "same-session", 20)) is replacement
        )
        assert not replacement.consumer_task.done()
        assert received == ["first", "second"]
        await queues.stop_all()
        assert replacement.consumer_task.done()
    finally:
        release.set()
        await queues.stop_all()
        if replacement is not None and not replacement.consumer_task.done():
            replacement.consumer_task.cancel()
            await asyncio.gather(
                replacement.consumer_task,
                return_exceptions=True,
            )


@pytest.mark.asyncio
async def test_idle_cleanup_rechecks_queue_after_scan_before_retiring():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    first_consumed, scanned, proceed = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    keep_consumer = asyncio.Event()

    class ScanBarrierLock(asyncio.Lock):
        """Instrument scheduling while preserving actual lock semantics."""

        cleanup_acquires = 0

        async def acquire(self):
            if asyncio.current_task().get_name() == "unified_queue_cleanup":
                self.cleanup_acquires += 1
                if self.cleanup_acquires == 2:
                    scanned.set()
                    await proceed.wait()
            return await super().acquire()

    async def consumer(queue, *_args):
        assert await queue.get() == "first"
        first_consumed.set()
        await keep_consumer.wait()

    queues = UnifiedQueueManager(
        consumer,
        idle_timeout=0,
        cleanup_interval=0.001,
    )
    queues._lock = ScanBarrierLock()
    try:
        assert (await queues.admit("feishu", "scanned", 20, "first")).accepted
        await first_consumed.wait()
        state = queues._queues[("feishu", "scanned", 20)]
        queues.start_cleanup_loop()
        await asyncio.wait_for(scanned.wait(), 1)
        assert (await queues.admit("feishu", "scanned", 20, "second")).accepted
        queues._running = False
        proceed.set()
        await asyncio.wait_for(queues._cleanup_task, 1)
        assert queues._queues.get(("feishu", "scanned", 20)) is state
        assert list(state.queue._queue) == ["second"]
        assert not state.consumer_task.done()
        await queues.stop_all()
        assert state.consumer_task.done()
    finally:
        proceed.set()
        keep_consumer.set()
        await queues.stop_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", ["incomplete", "exception"])
async def test_failed_stop_retains_owner_and_only_current_exit_evidence(
    monkeypatch,
    evidence,
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.plugins.execution.process import StopResult
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.ownership import RuntimeKey

    channel = proxy()
    manager = ChannelManager([channel])
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    channel._owner_registry = registry
    spec = channel._launch_spec
    lease = registry.runtime_owners.reserve(
        "feishu",
        RuntimeKey("channel", "feishu", "queue-workspace"),
        spec.code_root,
        instance_id=spec.instance_id,
    )
    channel._runtime_lease = lease
    manager._attach_runtime(channel)
    channel.last_stop_result = StopResult(True, 0, False)

    async def stop():
        if evidence == "exception":
            raise OSError("current stop failed before result")
        return StopResult(False, 9, True, ("PROCESS_RUNNING",))

    monkeypatch.setattr(channel.channel_process, "stop", stop)
    try:
        receipt = await manager.stop_one("feishu")
        assert not receipt.stopped and manager.channels == [channel]
        assert registry.runtime_owners.resource(lease) is channel
        assert (
            receipt.instance_id == "queue-workspace"
            and receipt.generation == 1
        )
        if evidence == "incomplete":
            assert (
                receipt.exited,
                receipt.returncode,
                receipt.forced,
                receipt.residual,
            ) == (False, 9, True, ("PROCESS_RUNNING",))
        else:
            assert receipt.exited is None and receipt.returncode is None
            assert not receipt.forced and receipt.residual == ()
    finally:
        PluginRegistry._instance = previous
