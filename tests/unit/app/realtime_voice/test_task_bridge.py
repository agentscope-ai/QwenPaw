import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.realtime_voice.contracts import (
    HandoffVoiceAction,
    VoiceRunEvent,
    VoiceTaskEvent,
)
from qwenpaw.app.realtime_voice.task_bridge import VoiceTaskBridge
from qwenpaw.app.task_tracker import RunInput, RunOutcome, TaskTracker
from qwenpaw.runtime.reply_cycle import InputStateEvent


@pytest.mark.asyncio
async def test_cancelled_run_keeps_completed_inputs_and_cancels_active_input():
    tracker = TaskTracker()
    started = asyncio.Event()

    async def stream(payload):
        cycle = payload["meta"]["request_context"]["_reply_cycle_context"]
        cycle.finish_reply("completed")
        cycle.activate(("active-input",))
        yield 'data: {"object":"response","status":"in_progress"}\n\n'
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            yield 'data: {"object":"response","status":"completed"}\n\n'
            raise

    queue, _, _ = await tracker.submit_or_start(
        "chat-1",
        {},
        stream,
        RunInput(("first",), "done-input"),
    )
    task_bridge = bridge(tracker)
    events = task_bridge.subscribe()
    await task_bridge.observe_active_run()
    await started.wait()
    await tracker.request_stop("chat-1")
    await asyncio.wait_for(task_bridge._observer_task, timeout=1)

    assert (await task_bridge.status("done-input")).status == "responded"
    assert (await task_bridge.status("active-input")).status == "cancelled"
    terminals = [e for e in events._queue if isinstance(e, VoiceRunEvent)]
    assert len(terminals) == 1
    assert terminals[0].status == "cancelled"
    # Ordinary Chat must still receive only its supported SSE messages.
    ordinary = [
        item async for item in tracker.stream_from_queue(queue, "chat-1")
    ]
    assert all(isinstance(item, str) for item in ordinary)
    assert '"status":"completed"' in ordinary[-1]
    await task_bridge.close()


class Tracker:
    def __init__(self, payloads=(), *, status="completed"):
        self.input_context = TaskTracker().input_context
        self.payloads = list(payloads)
        self.status = status
        self.run_id = "run-1"
        self.claim_live_subscriber = AsyncMock(return_value=True)
        self.detach_subscriber = AsyncMock()
        self.attach_live_once_with_identity = AsyncMock(return_value=None)

    async def stream_events_from_queue(self, _events, _chat_id):
        context = self.input_context(_chat_id)
        input_ids = set(context._sources)
        for input_id in input_ids:
            if context.state(input_id) is None:
                event = InputStateEvent(self.run_id, (input_id,), "queued")
                context.observe_state(event)
                yield event
        for payload in self.payloads:
            if isinstance(payload, InputStateEvent):
                input_ids.update(payload.input_ids)
                context.observe_state(payload)
                yield payload
            else:
                yield f"data: {json.dumps(payload)}\n\n"
        if self.status is not None:
            for input_id in input_ids:
                state = context.state(input_id)
                if (
                    state is not None
                    and state.run_id == self.run_id
                    and state.status
                    not in {"completed", "failed", "cancelled"}
                    and not (
                        state.status == "waiting"
                        and self.status == "completed"
                    )
                ):
                    event = InputStateEvent(
                        self.run_id,
                        (input_id,),
                        "cancelled"
                        if self.status == "cancelled"
                        else "failed",
                    )
                    context.observe_state(event)
                    yield event
            yield RunOutcome(self.run_id, self.status)


def bridge(tracker: Tracker) -> VoiceTaskBridge:
    return VoiceTaskBridge(
        SimpleNamespace(task_tracker=tracker),
        SimpleNamespace(id="chat-1", name="Existing title"),
    )


async def publish_state(task_bridge, event):
    # The producer writes the shared view before notifying its consumers.
    task_bridge._input_context.observe_state(event)
    await task_bridge._refresh_input_state(event)


@pytest.mark.asyncio
async def test_optional_reference_does_not_merge_or_block_handoff(monkeypatch):
    from qwenpaw.constant import CHAT_INPUT_TARGET_KEY
    from qwenpaw.app.chats.run_coordinator import ChatRunCoordinator

    task_bridge = bridge(Tracker())
    task_bridge._attach_observer = AsyncMock()
    submit = AsyncMock(
        return_value=SimpleNamespace(
            status="queued",
            run_id="run-1",
            events=asyncio.Queue(),
        )
    )
    monkeypatch.setattr(ChatRunCoordinator, "submit", submit)
    try:
        first = await task_bridge.submit("第一项工作", idempotency_key="first")
        second = await task_bridge.submit(
            "之前为什么失败？不要重新执行。",
            idempotency_key="second",
            task_ref=first.task_ref,
        )
        unknown = await task_bridge.submit(
            "还有一个问题",
            idempotency_key="third",
            task_ref="未知",
        )
        assert len({first.task_id, second.task_id, unknown.task_id}) == 3
        assert second.task_ref != first.task_ref
        reference = (
            submit.await_args_list[1]
            .args[2]
            .request_context[CHAT_INPUT_TARGET_KEY]
        )
        assert json.loads(reference) == {
            "input_id": first.task_id,
            "task_ref": first.task_ref,
            "relationship": "reference",
        }
        assert (
            CHAT_INPUT_TARGET_KEY
            not in submit.await_args.args[2].request_context
        )
        assert submit.await_count == 3
    finally:
        await task_bridge.close()


async def test_admission_carries_frozen_context_to_independent_inputs(
    monkeypatch,
):
    from qwenpaw.constant import (
        CHAT_CONVERSATION_CONTEXT_KEY,
        CHAT_INPUT_TARGET_KEY,
    )
    from qwenpaw.app.realtime_voice.contracts import HandoffVoiceAction
    from qwenpaw.app.chats.run_coordinator import ChatRunCoordinator

    task_bridge = bridge(Tracker())
    task_bridge._attach_observer = AsyncMock()
    submit = AsyncMock(
        return_value=SimpleNamespace(
            status="queued",
            run_id="run-1",
            events=asyncio.Queue(),
        )
    )
    monkeypatch.setattr(ChatRunCoordinator, "submit", submit)
    try:
        first = await task_bridge.enqueue_action(
            HandoffVoiceAction(),
            "Print it",
            idempotency_key="s1",
            conversation_context="BLUE_CAT",
        )
        duplicate = await task_bridge.enqueue_action(
            HandoffVoiceAction(),
            "Print it",
            idempotency_key="s1",
            conversation_context="WRONG_NEWER_CONTEXT",
        )
        receipt = await first.wait()
        assert duplicate.completion is first.completion
        second = await task_bridge.enqueue_action(
            HandoffVoiceAction(receipt.task_ref),
            "Append it",
            idempotency_key="s2",
            conversation_context="RED_CAT",
        )
        assert (await second.wait()).accepted
        assert submit.await_count == 2
        initial, referenced = [call.args[2] for call in submit.await_args_list]
        assert CHAT_INPUT_TARGET_KEY not in initial.request_context
        assert json.loads(
            referenced.request_context[CHAT_INPUT_TARGET_KEY]
        ) == {
            "input_id": receipt.task_id,
            "task_ref": receipt.task_ref,
            "relationship": "reference",
        }
        assert initial.client_message_id == receipt.task_id
        assert referenced.client_message_id != receipt.task_id
        for request, phrase, text in zip(
            (initial, referenced),
            ("BLUE_CAT", "RED_CAT"),
            ("Print it", "Append it"),
        ):
            assert (
                request.request_context[CHAT_CONVERSATION_CONTEXT_KEY]
                == phrase
            )
            assert (
                request.message_metadata["realtime_voice_task_id"]
                == request.client_message_id
            )
            assert request.content_parts[0].text == text
            assert (
                CHAT_CONVERSATION_CONTEXT_KEY not in request.message_metadata
            )

    finally:
        await task_bridge.close()


@pytest.mark.parametrize(
    "history",
    ["", '{"text":"' + "旧资料" * 1329 + '"}'],
    ids=["empty-history", "near-history-budget"],
)
@pytest.mark.parametrize("mode", ["queue", "steer"])
async def test_resolved_target_reaches_actual_formatter_per_input(
    monkeypatch, history, mode
):
    from agentscope.formatter import (
        DashScopeChatFormatter,
        OpenAIChatFormatter,
    )
    from agentscope.message import Msg
    from qwenpaw.app.realtime_voice.contracts import HandoffVoiceAction
    from qwenpaw.app.chats.run_coordinator import ChatRunCoordinator
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.schemas import Message

    task_bridge = bridge(Tracker())
    task_bridge._attach_observer = AsyncMock()
    submit = AsyncMock(
        return_value=SimpleNamespace(
            status="queued",
            run_id="run-1",
            events=asyncio.Queue(),
        )
    )
    monkeypatch.setattr(ChatRunCoordinator, "submit", submit)
    runtime = Runtime(
        workspace=SimpleNamespace(agent_id="default"), app_services=None
    )
    try:
        one = await task_bridge.submit("首次操作", idempotency_key="one")
        two = await task_bridge.submit("另一个任务", idempotency_key="two")
        for index, receipt in enumerate((two, one)):
            action = HandoffVoiceAction(receipt.task_ref)
            handle = await task_bridge.enqueue_action(
                action,
                f"追加一步{index}",
                idempotency_key=f"follow-{index}",
                admission_mode=mode,
                conversation_context=history,
            )
            current = await handle.wait()
            assert current.task_id != receipt.task_id
            request = submit.await_args.args[2]
            context = runtime._build_context(
                SimpleNamespace(
                    session_id="test",
                    request_context=request.request_context,
                    input=[
                        Message(
                            role="user",
                            content=list(request.content_parts),
                            metadata=request.message_metadata,
                        )
                    ],
                )
            )
            hints = [
                b.hint
                for m in context.input_msgs
                for b in m.content
                if b.type == "hint"
            ]
            assert len(hints) == 1
            assert receipt.task_ref in hints[0] and receipt.task_id in hints[0]
            assert (
                request.message_metadata["realtime_voice_task_id"]
                == current.task_id
            )
            other = one if receipt == two else two
            assert other.task_id not in hints[0]
            assert "reference" in hints[0]
            assert len(hints[0]) <= len(history) + 1000
            restored = [
                Msg.model_validate(m.model_dump()) for m in context.input_msgs
            ]
            for formatter in (DashScopeChatFormatter(), OpenAIChatFormatter()):
                wire = await formatter.format(restored)
                encoded = json.dumps(wire, ensure_ascii=False)
                assert (
                    receipt.task_ref in encoded and receipt.task_id in encoded
                )
                assert f"追加一步{index}" in encoded
                assert not any(m["role"] == "system" for m in wire)
        assert submit.await_count == 4
    finally:
        await task_bridge.close()


@pytest.mark.asyncio
async def test_admission_order_precedes_queued_inputs_before_producer_starts():
    tracker = TaskTracker()
    task_bridge = bridge(tracker)
    release = asyncio.Event()

    async def stream(payload):
        await release.wait()
        yield 'data: {"object":"response","status":"completed"}\n\n'

    for input_id in ("first", "second", "third"):
        await tracker.submit_or_start(
            "chat-1", {}, stream, RunInput((input_id,), input_id, mode="queue")
        )
    for _ in range(20):
        if len(task_bridge._records) == 3:
            break
        await asyncio.sleep(0)
    assert (await task_bridge.status("first")).task_ref == "请求一"
    assert (await task_bridge.status("second")).task_ref == "请求二"
    assert (await task_bridge.status("third")).task_ref == "请求三"
    release.set()
    assert await tracker.wait_all_done(timeout=1)
    await task_bridge.close()


@pytest.mark.asyncio
async def test_observer_eof_without_outcome_is_not_task_completion():
    tracker = Tracker(
        [InputStateEvent("run-1", ("input",), "processing")], status=None
    )
    task_bridge = bridge(tracker)
    events = task_bridge.subscribe()
    await task_bridge._observe(asyncio.Queue(), "run-1")
    assert (await task_bridge.status("input")).status == "processing"
    assert not any(isinstance(event, VoiceRunEvent) for event in events._queue)
    await task_bridge.close()


@pytest.mark.asyncio
async def test_failed_agent_run_does_not_poison_the_next_admission(
    monkeypatch,
):
    tracker = Tracker(
        [
            {
                "object": "response",
                "status": "failed",
                "error": {"message": "Model unavailable"},
            }
        ],
        status="failed",
    )
    identifiers = iter(("failed-task", "healthy-task"))
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.uuid4",
        lambda: SimpleNamespace(hex=next(identifiers)),
    )
    submit = AsyncMock(
        side_effect=[
            SimpleNamespace(
                status="started", run_id="run-1", events=asyncio.Queue()
            ),
            SimpleNamespace(
                status="started", run_id="run-2", events=asyncio.Queue()
            ),
        ]
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submit,
    )
    task_bridge = bridge(tracker)
    try:
        failed = await task_bridge.submit(
            "first task", idempotency_key="first"
        )
        await asyncio.wait_for(task_bridge._observer_task, timeout=1)
        assert (await task_bridge.status(failed.task_id)).status == "failed"
        tracker.status = "completed"
        tracker.run_id = "run-2"
        tracker.payloads = [
            {
                "object": "message",
                "role": "assistant",
                "status": "completed",
                "metadata": {"responds_to_input_ids": ["healthy-task"]},
                "content": [{"type": "text", "text": "next task completed"}],
            }
        ]
        tracker.payloads.append(
            InputStateEvent("run-2", ("healthy-task",), "completed")
        )
        healthy = await task_bridge.submit("next task", idempotency_key="next")
        await asyncio.wait_for(task_bridge._observer_task, timeout=1)
        assert healthy.accepted
        assert (await task_bridge.status(healthy.task_id)).run_id == "run-2"
        assert (
            await task_bridge.status(healthy.task_id)
        ).status == "responded"
        assert (await task_bridge.status(failed.task_id)).status == "failed"
    finally:
        await task_bridge.close()


@pytest.mark.asyncio
async def test_submit_is_fast_distinct_idempotent_and_speakable(monkeypatch):
    tracker = Tracker()
    events = asyncio.Queue()
    submit = AsyncMock(
        side_effect=[
            SimpleNamespace(status="started", run_id="run-1", events=events),
            SimpleNamespace(status="accepted", run_id="run-1", events=events),
        ]
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submit,
    )
    task_bridge = bridge(tracker)

    first = await task_bridge.submit("task A", idempotency_key="call-a")
    second = await task_bridge.submit("task B", idempotency_key="call-b")
    duplicate = await task_bridge.submit(
        "task A again",
        idempotency_key="call-a",
    )

    assert first.accepted and first.status == "accepted"
    assert second.accepted and second.status == "accepted"
    # The mocked coordinator emits no input-state events. A receipt alone
    # must no longer invent a processing/queued fact.
    assert first.task_id != second.task_id
    assert (first.task_ref, second.task_ref) == ("请求一", "请求二")
    assert duplicate.task_id == first.task_id
    assert duplicate.task_ref == "请求一"
    assert first.public_dict() == {
        "task_ref": "请求一",
        "accepted": True,
        "completed": False,
    }
    assert submit.await_count == 2
    assert all(call.args[2].mode == "queue" for call in submit.await_args_list)
    await task_bridge.close()


@pytest.mark.asyncio
async def test_input_outcomes_drive_processing_and_responded_state(
    monkeypatch,
):
    tracker = Tracker(
        [
            InputStateEvent("run-1", ("task-placeholder",), "processing"),
            InputStateEvent("run-1", ("task-placeholder",), "completed"),
        ]
    )
    events = asyncio.Queue()
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        AsyncMock(
            return_value=SimpleNamespace(
                status="started",
                run_id="run-1",
                events=events,
            )
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.uuid4",
        lambda: SimpleNamespace(hex="task-placeholder"),
    )
    task_bridge = bridge(tracker)
    receipt = await task_bridge.submit("task A", idempotency_key="call-a")

    await asyncio.wait_for(task_bridge._observer_task, timeout=1)
    snapshot = await task_bridge.status(receipt.task_id)

    assert snapshot.status == "responded"
    assert snapshot.run_id == "run-1"
    assert snapshot.task_ref == "请求一"
    assert snapshot.public_dict() == {
        "task_ref": "请求一",
        "status": "responded",
        "version": snapshot.version,
    }
    await task_bridge.close()


@pytest.mark.asyncio
async def test_keyboard_run_uses_same_typed_task_events_without_speech():
    tracker = Tracker(
        [
            {
                "type": "message",
                "object": "message",
                "id": "assistant-message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "text", "text": "done"}],
                "metadata": {"responds_to_input_ids": ["keyboard-input"]},
            }
        ]
    )
    tracker.attach_live_once_with_identity.return_value = (
        asyncio.Queue(),
        "run-keyboard",
    )
    tracker.run_id = "run-keyboard"
    tracker.payloads.extend(
        [
            InputStateEvent("run-keyboard", ("keyboard-input",), "processing"),
            InputStateEvent("run-keyboard", ("keyboard-input",), "completed"),
        ]
    )
    task_bridge = bridge(tracker)
    bridge_events = task_bridge.subscribe()

    run_id = await task_bridge.observe_active_run()
    await asyncio.wait_for(task_bridge._observer_task, timeout=1)
    snapshot = await task_bridge.status("keyboard-input")
    emitted = tuple(bridge_events._queue)

    assert run_id == "run-keyboard"
    assert snapshot.status == "responded"
    assert snapshot.task_ref == "请求一"
    assert emitted
    assert all(
        isinstance(event, (VoiceTaskEvent, VoiceRunEvent)) for event in emitted
    )
    await task_bridge.close()


@pytest.mark.asyncio
async def test_hidden_reasoning_never_becomes_a_speech_projection(monkeypatch):
    tracker = Tracker(
        [
            {
                "type": "reasoning",
                "object": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "text", "text": "private chain of thought"}
                ],
                "metadata": {"responds_to_input_ids": ["task-placeholder"]},
            }
        ]
    )
    tracker.payloads.append(
        InputStateEvent("run-1", ("task-placeholder",), "completed")
    )
    events = asyncio.Queue()
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        AsyncMock(
            return_value=SimpleNamespace(
                status="started",
                run_id="run-1",
                events=events,
            )
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.uuid4",
        lambda: SimpleNamespace(hex="task-placeholder"),
    )
    task_bridge = bridge(tracker)
    bridge_events = task_bridge.subscribe()
    receipt = await task_bridge.submit("task A", idempotency_key="call-a")

    await asyncio.wait_for(task_bridge._observer_task, timeout=1)
    result = await task_bridge.status(receipt.task_id)
    emitted = tuple(bridge_events._queue)

    assert result.status == "responded"
    assert all(
        isinstance(event, (VoiceTaskEvent, VoiceRunEvent)) for event in emitted
    )
    assert all(
        "private chain of thought" not in repr(event) for event in emitted
    )
    await task_bridge.close()


@pytest.mark.asyncio
async def test_input_outcomes_complete_only_the_inputs_they_cover(monkeypatch):
    tracker = Tracker(
        [
            InputStateEvent("run-1", ("task-a",), "processing"),
            InputStateEvent("run-1", ("task-a",), "completed"),
            InputStateEvent("run-1", ("task-b",), "processing"),
            InputStateEvent("run-1", ("task-b",), "completed"),
        ]
    )
    events = asyncio.Queue()
    submissions = AsyncMock(
        side_effect=[
            SimpleNamespace(status="started", run_id="run-1", events=events),
            SimpleNamespace(status="accepted", run_id="run-1", events=events),
        ],
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submissions,
    )
    ids = iter(("task-a", "task-b"))
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.uuid4",
        lambda: SimpleNamespace(hex=next(ids)),
    )
    task_bridge = bridge(tracker)

    first = await task_bridge.submit("task A", idempotency_key="turn-a")
    second = await task_bridge.submit("task B", idempotency_key="turn-b")
    await asyncio.wait_for(task_bridge._observer_task, timeout=1)

    assert (await task_bridge.status(first.task_id)).status == "responded"
    assert (await task_bridge.status(second.task_id)).status == "responded"
    await task_bridge.close()


@pytest.mark.asyncio
async def test_referenced_handoff_has_its_own_input_and_reply_scope(
    monkeypatch,
):
    tracker = Tracker()
    events = asyncio.Queue()
    submit = AsyncMock(
        return_value=SimpleNamespace(
            status="queued",
            run_id="run-1",
            events=events,
        )
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submit,
    )
    task_bridge = bridge(tracker)
    task_bridge._attach_observer = AsyncMock()
    try:
        first = await task_bridge.submit("task A", idempotency_key="turn-a")
        await publish_state(
            task_bridge,
            InputStateEvent("run-1", (first.task_id,), "completed"),
        )
        second = await task_bridge.submit(
            "make it shorter",
            idempotency_key="turn-b",
            task_ref=first.task_ref,
        )
        await publish_state(
            task_bridge, InputStateEvent("run-1", (second.task_id,), "queued")
        )
        assert second.accepted and second.task_id != first.task_id
        assert (await task_bridge.status(first.task_id)).status == "responded"
        assert (await task_bridge.status(second.task_id)).status == "queued"
        request = submit.await_args.args[2]
        assert request.client_message_id == second.task_id
        assert (
            request.message_metadata["realtime_voice_task_id"]
            == second.task_id
        )
        assert task_bridge._input_task_ids[second.task_id] == second.task_id
        facts = await task_bridge.presentation_snapshots()
        assert [f.input_requests for f in facts] == [
            ((first.task_id, "task A"),),
            ((second.task_id, "make it shorter"),),
        ]
        assert [f.input_states for f in facts] == [
            ((first.task_id, "completed"),),
            ((second.task_id, "queued"),),
        ]
        assert [
            f.input_requests for f in await task_bridge.routing_snapshots()
        ] == [f.input_requests for f in facts]
    finally:
        await task_bridge.close()


@pytest.mark.asyncio
async def test_execution_failure_never_replays_an_admitted_turn(monkeypatch):
    tracker = Tracker()
    task_bridge = bridge(tracker)
    task_bridge._attach_observer = AsyncMock()

    async def submit(_workspace, _chat, request):
        task_bridge._input_context.set_admission(
            request.client_message_id, "admitted"
        )
        return SimpleNamespace(
            status="queued", run_id="run-1", events=asyncio.Queue()
        )

    submission = AsyncMock(side_effect=submit)
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submission,
    )
    try:
        first = await task_bridge.submit("task A", idempotency_key="turn-a")
        await publish_state(
            task_bridge, InputStateEvent("run-1", (first.task_id,), "failed")
        )
        duplicate = await task_bridge.submit(
            "task A", idempotency_key="turn-a"
        )
        assert duplicate.accepted and duplicate.task_id == first.task_id
        assert submission.await_count == 1
        retry = await task_bridge.submit(
            "retry task A", idempotency_key="turn-b"
        )
        assert retry.accepted and retry.task_id != first.task_id
        assert submission.await_count == 2
    finally:
        await task_bridge.close()


@pytest.mark.asyncio
async def test_enqueued_admission_outlives_a_cancelled_waiter(monkeypatch):
    tracker = Tracker()
    events = asyncio.Queue()
    started = asyncio.Event()
    release = asyncio.Event()

    async def submit(*_args, **_kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(
            status="started",
            run_id="run-1",
            events=events,
        )

    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submit,
    )
    task_bridge = bridge(tracker)
    task_bridge._attach_observer = AsyncMock()
    handle = await task_bridge.enqueue_action(
        HandoffVoiceAction(),
        "long request",
        idempotency_key="turn-a",
    )
    waiter = asyncio.create_task(handle.wait())
    await asyncio.wait_for(started.wait(), timeout=1)

    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    release.set()
    result = await asyncio.wait_for(handle.wait(), timeout=1)

    assert result.accepted
    assert result.task_ref == "请求一"
    await task_bridge.close()


@pytest.mark.asyncio
async def test_enqueued_admission_is_bounded_and_idempotent(monkeypatch):
    tracker = Tracker()
    events = asyncio.Queue()
    started = asyncio.Event()
    release = asyncio.Event()

    async def submit(*_args, **_kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(
            status="accepted",
            run_id="run-1",
            events=events,
        )

    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submit,
    )
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge._MAX_PENDING_ADMISSIONS",
        2,
    )
    task_bridge = bridge(tracker)
    task_bridge._attach_observer = AsyncMock()
    first = await task_bridge.enqueue_action(
        HandoffVoiceAction(),
        "long request",
        idempotency_key="turn-a",
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    duplicate = await task_bridge.enqueue_action(
        HandoffVoiceAction(),
        "long request",
        idempotency_key="turn-a",
    )
    second = await task_bridge.enqueue_action(
        HandoffVoiceAction(),
        "long request",
        idempotency_key="turn-b",
    )

    assert duplicate.completion is first.completion
    with pytest.raises(OverflowError, match="too many pending admissions"):
        await task_bridge.enqueue_action(
            HandoffVoiceAction(),
            "long request",
            idempotency_key="turn-c",
        )

    release.set()
    assert (await asyncio.wait_for(first.wait(), timeout=1)).accepted
    assert (await asyncio.wait_for(second.wait(), timeout=1)).accepted
    await task_bridge.close()


@pytest.mark.asyncio
async def test_app_shutdown_cancels_active_and_queued_admissions(monkeypatch):
    tracker = Tracker()
    started = asyncio.Event()

    async def submit(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.task_bridge.ChatRunCoordinator.submit",
        submit,
    )
    task_bridge = bridge(tracker)
    first = await task_bridge.enqueue_action(
        HandoffVoiceAction(),
        "long request",
        idempotency_key="turn-a",
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    second = await task_bridge.enqueue_action(
        HandoffVoiceAction(),
        "long request",
        idempotency_key="turn-b",
    )

    await task_bridge.close()
    first_receipt, second_receipt = await asyncio.gather(
        first.wait(),
        second.wait(),
    )

    assert first_receipt.status == "cancelled"
    assert second_receipt.status == "cancelled"
    assert not first_receipt.accepted
    assert not second_receipt.accepted
    assert not task_bridge._pending_admission_keys


@pytest.mark.asyncio
async def test_queued_same_task_followups_cannot_complete_prematurely():
    task_bridge = bridge(Tracker(status=None))
    await task_bridge._ensure_observed_task("task", "run-1")
    task_bridge._input_task_ids.update(
        {"follow-1": "task", "follow-2": "task"}
    )
    await publish_state(
        task_bridge,
        InputStateEvent("run-1", ("task", "follow-1", "follow-2"), "queued"),
    )
    for key in ("task", "follow-1"):
        await publish_state(
            task_bridge, InputStateEvent("run-1", (key,), "processing")
        )
        await publish_state(
            task_bridge, InputStateEvent("run-1", (key,), "completed")
        )
        assert (await task_bridge.status("task")).status == "queued"
    await publish_state(
        task_bridge, InputStateEvent("run-1", ("follow-2",), "processing")
    )
    await publish_state(
        task_bridge, InputStateEvent("old-run", ("follow-2",), "completed")
    )
    assert (await task_bridge.status("task")).status == "processing"
    await publish_state(
        task_bridge, InputStateEvent("run-1", ("follow-2",), "completed")
    )
    assert (await task_bridge.status("task")).status == "responded"
    await task_bridge.close()


@pytest.mark.asyncio
async def test_revision_and_renderer_completion_are_not_input_outcomes():
    task_bridge = bridge(
        Tracker(
            [
                {
                    "metadata": {
                        "timeline_revision": 99,
                        "responds_to_input_ids": ["task"],
                    }
                },
                {"object": "response", "status": "completed"},
            ],
            status=None,
        )
    )
    await task_bridge._ensure_observed_task("task", "run-1")
    await task_bridge._observe(asyncio.Queue(), "run-1")
    assert (await task_bridge.status("task")).status == "queued"
    await task_bridge.close()


@pytest.mark.asyncio
async def test_waiting_task_requires_explicit_resume_ownership():
    task_bridge = bridge(Tracker(status=None))
    await publish_state(
        task_bridge, InputStateEvent("old", ("task",), "waiting")
    )
    await publish_state(
        task_bridge, InputStateEvent("new", ("task",), "completed")
    )
    assert (await task_bridge.status("task")).status == "waiting"
    await publish_state(
        task_bridge, InputStateEvent("new", ("task",), "processing", "old")
    )
    assert (await task_bridge.status("task")).status == "processing"
    await publish_state(
        task_bridge, InputStateEvent("old", ("task",), "failed")
    )
    await publish_state(
        task_bridge, InputStateEvent("new", ("task",), "completed")
    )
    assert (await task_bridge.status("task")).status == "responded"
    await task_bridge.close()
