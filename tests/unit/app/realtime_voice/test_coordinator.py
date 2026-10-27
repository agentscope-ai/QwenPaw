# -*- coding: utf-8 -*-
# Lifecycle regressions intentionally inspect coordinator and queue internals.
# pylint: disable=protected-access
import asyncio
import json
from itertools import permutations
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.chats.replies import ChatReply
from qwenpaw.app.realtime_voice.contracts import (
    VoiceRunEvent,
    VoiceTaskEvent,
    VoiceTaskReceipt,
    VoiceTaskSnapshot,
)
from qwenpaw.app.realtime_voice.coordinator import VoiceCoordinator
from qwenpaw.app.realtime_voice.presentation import (
    OutputCredit,
    PresentationIntent,
)
from qwenpaw.app.realtime_voice.prompts import build_update_instruction
from qwenpaw.app.realtime_voice.task_bridge import VoiceAdmissionHandle
from qwenpaw.providers.realtime_voice import (
    ProviderEvent,
    ProviderResponseResult,
)
from qwenpaw.providers.realtime_voice.dashscope import DashScopeRealtimeSession


class Provider:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.connect = AsyncMock()
        self.send_audio = AsyncMock()
        self.interrupt_output = AsyncMock()
        self.close = AsyncMock()
        self.complete_tool_call = AsyncMock(return_value="tool-output-1")
        self.request_response = AsyncMock(
            return_value=ProviderResponseResult(
                "completed",
                ("assistant-1",),
                "好的。",
            ),
        )
        self.delete_items = AsyncMock()
        self.created_messages: list[tuple[str, str, str]] = []

    async def create_message(self, role: str, text: str) -> str:
        item_id = f"message-{len(self.created_messages) + 1}"
        self.created_messages.append((item_id, role, text))
        return item_id

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event


class Bridge:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.enqueue_input = AsyncMock()
        self.observe_transcript = Mock()
        self.persist_transcript = AsyncMock()
        self.presentation_snapshots = AsyncMock(return_value=())
        self.observe_active_run = AsyncMock(return_value=None)
        self.status = AsyncMock(return_value=snapshot())

    def subscribe(self):
        return self.queue

    def unsubscribe(self, _queue):
        return None


def snapshot(task_id="task-1", status="processing", version=1):
    return VoiceTaskSnapshot(
        task_id=task_id,
        task_ref="请求一",
        status=status,
        version=version,
        request="run tests",
        run_id="run-1",
    )


def receipt(task_id="task-1", status="processing"):
    return VoiceTaskReceipt(
        task_id=task_id,
        task_ref="请求一",
        accepted=True,
        status=status,
    )


def admission(result: VoiceTaskReceipt) -> VoiceAdmissionHandle:
    completion = asyncio.get_running_loop().create_future()
    completion.set_result(result)
    return VoiceAdmissionHandle(completion)


def build_coordinator(provider, bridge, **options):
    timeline = SimpleNamespace(
        read_context=AsyncMock(
            return_value=json.dumps(
                {"available": True, "omitted": False, "messages": []},
            ),
        ),
        reserve_order=AsyncMock(side_effect=range(1, 100)),
        append_voice_exchange=AsyncMock(return_value=[]),
        reconcile=AsyncMock(return_value=0),
        observe_voice_exchange=Mock(),
    )
    return VoiceCoordinator(provider, bridge, timeline, **options), timeline


def transcript(source_id: str, text: str) -> ProviderEvent:
    return ProviderEvent(
        "input_transcript.final",
        f"transcript-{source_id}",
        {"text": text},
        correlation_id=source_id,
    )


def tool_call(
    call_id: str,
    text: str,
    *,
    name: str = "handoff_to_chat",
    source_id: str = "source-1",
) -> ProviderEvent:
    return ProviderEvent(
        "tool.call",
        f"event-{call_id}",
        {
            "call_id": call_id,
            "name": name,
            "arguments": json.dumps(
                {"request_text": text},
                ensure_ascii=False,
            ),
            "input_item_id": source_id,
        },
        correlation_id=call_id,
        response_origin="provider_auto",
    )


async def eventually(predicate) -> None:
    for _attempt in range(500):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


async def next_kind(events, kind):
    while True:
        event = await asyncio.wait_for(anext(events), 1)
        if event.kind == kind:
            return event


@pytest.mark.asyncio
async def test_asr_is_ui_evidence_and_never_admits_chat_work():
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    try:
        await provider.queue.put(transcript("source-1", "可能听错的文本"))
        visible = await next_kind(events, "input_transcript.final")
        assert visible.data["text"] == "可能听错的文本"
        await asyncio.sleep(0.01)
        bridge.enqueue_input.assert_not_awaited()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("busy", [False, True])
async def test_close_persists_final_transcript_without_starting_work(busy):
    provider, bridge = Provider(), Bridge()
    if busy:
        bridge.presentation_snapshots.return_value = (snapshot(),)
    coordinator, timeline = build_coordinator(provider, bridge)
    await coordinator.start()
    await provider.queue.put(transcript("tail-source", "文件名是香蕉.txt"))
    await eventually(lambda: "tail-source" in coordinator._input_transcripts)
    await coordinator.close()
    await coordinator.close()
    timeline.append_voice_exchange.assert_awaited_once()
    call = timeline.append_voice_exchange.await_args
    assert call.args[0].startswith("voice_dialogue_")
    assert call.args[1:3] == ("文件名是香蕉.txt", "")
    bridge.enqueue_input.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["input_transcript.partial", "input_transcript.failed"],
)
async def test_close_never_persists_unconfirmed_transcription(kind):
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(
        ProviderEvent(
            kind,
            "partial",
            {"text": "UNCONFIRMED"},
            correlation_id="tail",
        ),
    )
    await next_kind(events, kind)
    await coordinator.close()
    timeline.append_voice_exchange.assert_not_awaited()
    bridge.enqueue_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_tail_save_failure_still_closes_provider():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    timeline.reserve_order.side_effect = RuntimeError("synthetic disk error")
    await coordinator.start()
    await provider.queue.put(transcript("tail", "final words"))
    await eventually(lambda: "tail" in coordinator._input_transcripts)
    await coordinator.close()
    provider.close.assert_awaited_once()
    bridge.enqueue_input.assert_not_awaited()
    assert any(
        isinstance(e, ProviderEvent)
        and e.kind == "error"
        and e.data.get("code") == "voice_history_commit_failed"
        for e in coordinator._events._queue
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted", [True, False])
async def test_close_does_not_duplicate_handoff_with_late_asr(admitted):
    provider, bridge = Provider(), Bridge()
    completion = asyncio.get_running_loop().create_future()
    if admitted:
        completion.set_result(receipt())
    bridge.enqueue_input.return_value = VoiceAdmissionHandle(completion)
    coordinator, timeline = build_coordinator(provider, bridge)
    coordinator._queue_admission = AsyncMock()
    await coordinator.start()
    await provider.queue.put(
        ProviderEvent(
            "speech.started",
            "speech-tail",
            {},
            correlation_id="tail",
        ),
    )
    await provider.queue.put(tool_call("tail-call", "执行任务", source_id="tail"))
    await eventually(lambda: bridge.enqueue_input.await_count == 1)
    await provider.queue.put(transcript("tail", "执行任务"))
    await eventually(lambda: "tail" in coordinator._input_transcripts)
    # Waiting for admission is not waiting for task completion. Closing the
    # microphone must not wait for either or create a second history input.
    await asyncio.wait_for(coordinator.close(), 1)
    timeline.append_voice_exchange.assert_not_awaited()
    bridge.enqueue_input.assert_awaited_once()
    if not completion.done():
        completion.set_result(receipt())


@pytest.mark.asyncio
async def test_close_finishes_an_inflight_direct_history_write():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    entered, release = asyncio.Event(), asyncio.Event()
    committed = []

    async def save(*_args, **_kwargs):
        entered.set()
        await release.wait()
        committed.append(True)
        return []

    timeline.append_voice_exchange.side_effect = save
    await coordinator.start()
    await provider.queue.put(transcript("tail", "问题"))
    await provider.queue.put(
        ProviderEvent(
            "response.started",
            "started",
            {"input_item_id": "tail"},
            correlation_id="r",
            response_origin="provider_auto",
        ),
    )
    await provider.queue.put(
        ProviderEvent(
            "response.finished",
            "finished",
            {
                "input_item_id": "tail",
                "status": "completed",
                "transcript": "回答",
                "had_tool_call": False,
            },
            correlation_id="r",
            response_origin="provider_auto",
        ),
    )
    await asyncio.wait_for(entered.wait(), 1)
    closing = asyncio.create_task(coordinator.close())
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 1)
        assert committed == [True]
        timeline.append_voice_exchange.assert_awaited_once()
        assert timeline.append_voice_exchange.await_args.args[1:3] == (
            "问题",
            "回答",
        )
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_close_tail_survives_journal_reload(tmp_path):
    from qwenpaw.app.chats.session import SafeJSONSession
    from qwenpaw.app.chats.timeline import ChatTimelineJournal
    from qwenpaw.app.task_tracker import TaskTracker

    chat = SimpleNamespace(
        id="chat",
        session_id="session",
        user_id="user",
        channel="console",
    )
    owner = SimpleNamespace(
        session=SafeJSONSession(str(tmp_path)),
        task_tracker=TaskTracker(),
        chat_manager=SimpleNamespace(touch_chat=AsyncMock()),
    )
    timeline = ChatTimelineJournal(owner, chat)
    provider, bridge = Provider(), Bridge()
    coordinator = VoiceCoordinator(provider, bridge, timeline)
    await coordinator.start()
    await provider.queue.put(transcript("tail", "RELOAD_REFERENCE.txt"))
    await eventually(lambda: "tail" in coordinator._input_transcripts)
    await coordinator.close()
    await timeline.conversation_view().close()
    owner.session = SafeJSONSession(str(tmp_path))
    owner.task_tracker = TaskTracker()
    restored = ChatTimelineJournal(owner, chat)
    try:
        assert await restored.reconcile() == 1
        context = await restored.read_context(max_turns=20, max_chars=16000)
        assert context.count("RELOAD_REFERENCE.txt") == 1
        bridge.enqueue_input.assert_not_awaited()
    finally:
        await restored.conversation_view().close()


@pytest.mark.asyncio
@pytest.mark.parametrize("final_before_handoff", [True, False])
async def test_native_handoff_admits_exact_model_request_and_returns_receipt(
    final_before_handoff,
):
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    try:
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech-1",
                {},
                correlation_id="source-1",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "input_transcript.partial",
                "partial",
                {"text": "截取桌面"},
                correlation_id="source-1",
            ),
        )
        if final_before_handoff:
            await provider.queue.put(transcript("source-1", "截取桌面并解释"))
        await provider.queue.put(tool_call("call-1", "截图桌面并说明重点"))
        committed = await next_kind(events, "input_turn.committed")
        await eventually(lambda: provider.complete_tool_call.await_count == 1)
        await next_kind(events, "agent.input.accepted")
        await provider.queue.put(
            ProviderEvent("speech.stopped", "stop", correlation_id="source-1"),
        )
        await next_kind(events, "speech.stopped")
        await asyncio.sleep(0.01)
        provider.request_response.assert_not_awaited()

        call = bridge.enqueue_input.await_args
        assert call.args == ("截图桌面并说明重点",)
        assert call.kwargs["idempotency_key"] == committed.data["turn_id"]
        assert call.kwargs["admission_mode"] == "steer"
        assert call.kwargs["transcript_source_id"] == "source-1"
        if not final_before_handoff:
            await provider.queue.put(transcript("source-1", "截取桌面并解释"))
        await eventually(lambda: bridge.observe_transcript.call_count == 2)
        bridge.observe_transcript.assert_any_call(
            "source-1",
            "截取桌面",
            final=False,
        )
        bridge.observe_transcript.assert_any_call(
            "source-1",
            "截取桌面并解释",
            final=True,
        )
        await eventually(lambda: bridge.persist_transcript.await_count == 1)
        bridge.persist_transcript.assert_awaited_once_with("source-1")
        bridge.enqueue_input.assert_awaited_once()
        provider.complete_tool_call.assert_awaited_once_with(
            "call-1",
            {
                "accepted": True,
                "action": "handoff",
                "task_ref": "请求一",
                "status": "processing",
            },
        )
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("save_fails", [False, True])
async def test_close_joins_handoff_transcript_write(save_fails):
    provider, bridge = Provider(), Bridge()
    entered, release = asyncio.Event(), asyncio.Event()

    async def persist(_source_id):
        entered.set()
        await release.wait()
        if save_fails:
            raise OSError("disk full")

    bridge.persist_transcript.side_effect = persist
    coordinator, _ = build_coordinator(provider, bridge)
    coordinator._handoff_sources.add("source-1")
    await coordinator.start()
    await provider.queue.put(transcript("source-1", "final evidence"))
    await asyncio.wait_for(entered.wait(), 1)
    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.gather(closing, return_exceptions=True)
    assert not coordinator._close_task.done()
    release.set()
    if save_fails:
        with pytest.raises(RuntimeError, match="history could not be saved"):
            await coordinator.close()
        assert any(
            isinstance(e, ProviderEvent)
            and e.data.get("code") == "voice_history_commit_failed"
            for e in coordinator._events._queue
        )
    else:
        await coordinator.close()
    provider.close.assert_awaited_once()
    bridge.enqueue_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_native_handoff_steers_current_chat_work():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    try:
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech-1",
                {},
                correlation_id="source-1",
            ),
        )
        await provider.queue.put(tool_call("call-2", "不要上传，只保存在桌面"))
        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        assert (
            bridge.enqueue_input.await_args.kwargs["admission_mode"] == "steer"
        )
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_duplicate_native_call_is_admitted_and_announced_once():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    try:
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech-1",
                {},
                correlation_id="source-1",
            ),
        )
        event = tool_call("same-call", "只执行一次")
        await provider.queue.put(event)
        await provider.queue.put(event)
        await eventually(lambda: provider.complete_tool_call.await_count == 1)
        await asyncio.sleep(0.01)
        bridge.enqueue_input.assert_awaited_once()
        provider.complete_tool_call.assert_awaited_once()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("resumed", [False, True])
async def test_direct_realtime_answer_streams_and_persists_once(resumed):
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    if resumed:
        timeline.read_context.return_value = json.dumps(
            {
                "available": True,
                "omitted": False,
                "messages": [
                    {"role": "user", "source": "voice", "text": "你好"},
                    {"role": "assistant", "source": "voice", "text": "你好"},
                ],
            },
        )
    await coordinator.start()
    events = coordinator.events()
    try:
        await provider.queue.put(transcript("source-1", "你好"))
        await provider.queue.put(
            ProviderEvent(
                "response.started",
                "r-start",
                {"input_item_id": "source-1"},
                correlation_id="response-1",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "output.started",
                "o-start",
                correlation_id="response-1",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "output.audio",
                "audio",
                audio=b"pcm",
                correlation_id="response-1",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "response.finished",
                "r-done",
                {
                    "input_item_id": "source-1",
                    "status": "completed",
                    "transcript": "你好，需要我做什么？",
                    "had_tool_call": False,
                },
                correlation_id="response-1",
                response_origin="provider_auto",
            ),
        )

        begin = await next_kind(events, "output.begin")
        audio = await next_kind(events, "output.audio")
        assert audio.audio == b"pcm"
        assert audio.data["output_id"] == begin.data["output_id"]
        await next_kind(events, "output.sealed")
        coordinator.playback_feedback(begin.data["output_id"], "drained")
        await eventually(
            lambda: timeline.append_voice_exchange.await_count == 1,
        )
        assert timeline.append_voice_exchange.await_args.args[1:3] == (
            "你好",
            "你好，需要我做什么？",
        )
        bridge.enqueue_input.assert_not_awaited()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_handoff_response_is_not_duplicated_as_direct_voice_history():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, timeline = build_coordinator(provider, bridge)
    await coordinator.start()
    try:
        await provider.queue.put(transcript("source-1", "执行长任务"))
        await provider.queue.put(
            ProviderEvent(
                "response.started",
                "start",
                {"input_item_id": "source-1"},
                correlation_id="response-1",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech-1",
                {},
                correlation_id="source-1",
            ),
        )
        await provider.queue.put(tool_call("call-1", "执行长任务"))
        await provider.queue.put(
            ProviderEvent(
                "response.finished",
                "done",
                {
                    "input_item_id": "source-1",
                    "status": "completed",
                    "transcript": "",
                    "had_tool_call": True,
                },
                correlation_id="response-1",
                response_origin="provider_auto",
            ),
        )
        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        await asyncio.sleep(0.01)
        timeline.append_voice_exchange.assert_not_awaited()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_transcription_failure_is_visible_and_not_submitted():
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    try:
        await provider.queue.put(
            ProviderEvent(
                "input_transcript.failed",
                "failed",
                {"code": "voice_transcription_failed"},
                correlation_id="source",
            ),
        )
        failed = await next_kind(events, "input_transcript.failed")
        assert failed.data["code"] == "voice_transcription_failed"
        bridge.enqueue_input.assert_not_awaited()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_configured_language_and_native_tools_reach_provider_session():
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge, language="en-US")
    await coordinator.start()
    try:
        config = provider.connect.call_args.args[0]
        assert '"en-US"' in config.instructions
        assert [tool.name for tool in config.tools] == [
            "handoff_to_chat",
            "update_response_style",
        ]
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_application_speech_uses_isolated_presenter_session():
    provider, presenter, bridge = Provider(), Provider(), Bridge()
    coordinator, _ = build_coordinator(
        provider,
        bridge,
        presentation_provider=presenter,
        language="en-US",
    )
    await coordinator.start()
    try:
        credit = coordinator._output_credit = OutputCredit()
        result = await coordinator._present(
            PresentationIntent("rejected"),
            credit,
        )

        assert result.status == "completed"
        assert not provider.created_messages
        assert [role for _, role, _ in presenter.created_messages] == [
            "system",
            "user",
        ]
        assert provider.connect.call_args.args[0].tools
        presenter_config = presenter.connect.call_args.args[0]
        assert not presenter_config.tools
        assert '"en-US"' in presenter_config.instructions
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("final_after_response", [False, True])
async def test_task_owned_turn_suppresses_native_answer_and_falls_back_to_chat(
    restored,
    final_after_response,
):
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt("fallback-task"))
    coordinator, timeline = build_coordinator(provider, bridge)
    if restored:
        timeline.read_context.return_value = json.dumps(
            {
                "available": True,
                "omitted": False,
                "messages": [
                    {
                        "role": "assistant",
                        "source": "agent",
                        "text": "旧任务已完成",
                        "persisted": True,
                    },
                ],
            },
        )
    else:
        bridge.presentation_snapshots.return_value = (
            snapshot(status="responded"),
        )
    coordinator._queue_admission = AsyncMock()
    await coordinator.start()
    try:
        bridge.enqueue_input.assert_not_awaited()
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech",
                correlation_id="source-2",
            ),
        )
        if not final_after_response:
            await provider.queue.put(transcript("source-2", "只告诉我实际结果"))
        await provider.queue.put(
            ProviderEvent(
                "response.started",
                "started",
                {"input_item_id": "source-2"},
                correlation_id="response-2",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "output_transcript.final",
                "wrong-answer",
                {"text": "还在排队"},
                correlation_id="response-2",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "response.finished",
                "finished",
                {
                    "status": "completed",
                    "input_item_id": "source-2",
                    "had_tool_call": False,
                    "transcript": "还在排队",
                },
                correlation_id="response-2",
                response_origin="provider_auto",
            ),
        )
        # Replayed final evidence must not execute the same live input twice.
        for _ in range(2 if final_after_response else 1):
            await provider.queue.put(transcript("source-2", "只告诉我实际结果"))

        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        await eventually(lambda: bridge.persist_transcript.await_count == 2)
        assert bridge.enqueue_input.await_args.args == ("只告诉我实际结果",)
        assert (
            bridge.enqueue_input.await_args.kwargs["admission_mode"] == "steer"
        )
        assert bridge.enqueue_input.await_args.kwargs[
            "idempotency_key"
        ].startswith(
            "voice_fallback_",
        )
        timeline.observe_voice_exchange.assert_not_called()
        forwarded = []
        while not coordinator._events.empty():
            forwarded.append(coordinator._events.get_nowait())
        assert not any(
            getattr(event, "response_origin", None) == "provider_auto"
            and event.kind.startswith(("output", "response"))
            for event in forwarded
        )
    finally:
        await coordinator.close()
    bridge.enqueue_input.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("restored", [False, True])
async def test_task_owned_native_tool_call_does_not_duplicate_asr_fallback(
    restored,
):
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, timeline = build_coordinator(provider, bridge)
    if restored:
        timeline.read_context.return_value = json.dumps(
            {
                "available": True,
                "omitted": False,
                "messages": [
                    {
                        "role": "assistant",
                        "source": "agent",
                        "text": "旧任务已完成",
                        "persisted": True,
                    },
                ],
            },
        )
    else:
        bridge.presentation_snapshots.return_value = (
            snapshot(status="processing"),
        )
    coordinator._queue_admission = AsyncMock()
    await coordinator.start()
    try:
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech",
                correlation_id="source-3",
            ),
        )
        await provider.queue.put(transcript("source-3", "查询当前结果"))
        await provider.queue.put(
            ProviderEvent(
                "response.started",
                "started",
                {"input_item_id": "source-3"},
                correlation_id="response-3",
                response_origin="provider_auto",
            ),
        )
        await provider.queue.put(
            tool_call(
                "call-3",
                "查询当前结果",
                source_id="source-3",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "response.finished",
                "finished",
                {
                    "status": "completed",
                    "input_item_id": "source-3",
                    "had_tool_call": True,
                    "transcript": "",
                },
                correlation_id="response-3",
                response_origin="provider_auto",
            ),
        )

        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        assert bridge.enqueue_input.await_args.args == ("查询当前结果",)
        assert (
            bridge.enqueue_input.await_args.kwargs["admission_mode"] == "steer"
        )
        assert not bridge.enqueue_input.await_args.kwargs[
            "idempotency_key"
        ].startswith(
            "voice_fallback_",
        )
    finally:
        await coordinator.close()
    bridge.enqueue_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_only_cancels_current_speech_output():
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.interrupt()
    provider.interrupt_output.assert_awaited_once()
    bridge.enqueue_input.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("order", list(permutations(("tool", "asr", "done"))))
async def test_style_feedback_saves_asr_and_responds_without_admitting_work(
    restored,
    order,
):
    provider, presenter, bridge = Provider(), Provider(), Bridge()
    coordinator, timeline = build_coordinator(
        provider,
        bridge,
        presentation_provider=presenter,
    )
    if restored:
        timeline.read_context.return_value = json.dumps(
            {
                "available": True,
                "omitted": False,
                "messages": [
                    {"role": "assistant", "source": "agent", "text": "任务仍在处理"},
                ],
            },
        )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(
        ProviderEvent("speech.started", "s", correlation_id="feedback"),
    )
    await next_kind(events, "speech.started")
    await provider.queue.put(
        ProviderEvent("speech.stopped", "s", correlation_id="feedback"),
    )
    await provider.queue.put(
        ProviderEvent(
            "response.started",
            "r",
            {"input_item_id": "feedback"},
            correlation_id="r",
            response_origin="provider_auto",
        ),
    )
    inputs = {
        "tool": tool_call(
            "style-call",
            "简短回复",
            name="update_response_style",
            source_id="feedback",
        ),
        "asr": transcript("feedback", "别总重复确认，接着刚才的话说。"),
        "done": ProviderEvent(
            "response.finished",
            "r",
            {
                "input_item_id": "feedback",
                "status": "completed",
                "had_tool_call": True,
            },
            correlation_id="r",
            response_origin="provider_auto",
        ),
    }
    try:
        for name in order:
            await provider.queue.put(inputs[name])
            await asyncio.sleep(0)
        await eventually(
            lambda: timeline.append_voice_exchange.await_count == 2,
        )
        # Replayed ASR, terminal events and native calls cannot create another
        # response or route the feedback through the Chat fallback.
        for name in order:
            await provider.queue.put(inputs[name])
        await asyncio.sleep(0.01)
        assert timeline.append_voice_exchange.await_count == 2
        saved = timeline.append_voice_exchange.await_args_list
        assert saved[0].args[1:3] == ("别总重复确认，接着刚才的话说。", "")
        assert saved[1].args[1:3] == ("别总重复确认，接着刚才的话说。", "好的。")
        assert saved[0].args[0] == saved[1].args[0]
        provider.complete_tool_call.assert_awaited_once_with(
            "style-call",
            {"accepted": True, "action": "update_response_style"},
        )
        bridge.enqueue_input.assert_not_awaited()
        presenter.request_response.assert_awaited_once()
        assert not presenter.connect.call_args.args[0].tools
        assert presenter.created_messages[-1][2] == "别总重复确认，接着刚才的话说。"
        assert "本轮回应用户对说话方式的反馈" in presenter.created_messages[0][2]
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("final_asr", [False, True])
async def test_close_saves_accepted_style_feedback_before_response_finishes(
    final_asr,
):
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(
        ProviderEvent("speech.started", "s", correlation_id="feedback"),
    )
    await next_kind(events, "speech.started")
    await provider.queue.put(
        tool_call(
            "style",
            "简短一点",
            name="update_response_style",
            source_id="feedback",
        ),
    )
    await eventually(lambda: provider.complete_tool_call.await_count == 1)
    if final_asr:
        await provider.queue.put(transcript("feedback", "别总重复确认。"))
        await eventually(lambda: "feedback" in coordinator._input_transcripts)
    await coordinator.close()
    timeline.append_voice_exchange.assert_awaited_once()
    assert timeline.append_voice_exchange.await_args.args[1:3] == (
        "别总重复确认。" if final_asr else "简短一点",
        "",
    )
    provider.request_response.assert_not_awaited()
    bridge.enqueue_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_waits_for_style_history_created_after_order_reservation():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    reserved, release_order, saving, release_save = (
        asyncio.Event() for _ in range(4)
    )

    async def reserve():
        reserved.set()
        await release_order.wait()
        return 1

    async def save(*_args, **_kwargs):
        saving.set()
        await release_save.wait()
        return []

    timeline.reserve_order.side_effect = reserve
    timeline.append_voice_exchange.side_effect = save
    await coordinator.start()
    await provider.queue.put(transcript("feedback", "回答连贯些"))
    await eventually(lambda: "feedback" in coordinator._live_sources)
    await coordinator._handle_tool_call(
        tool_call(
            "style",
            "回答连贯些",
            name="update_response_style",
            source_id="feedback",
        ),
    )
    coordinator._record_auto_response(
        "feedback",
        "r",
        ProviderEvent(
            "response.finished",
            "r",
            {"had_tool_call": True, "status": "completed"},
        ),
    )
    await asyncio.wait_for(reserved.wait(), 1)
    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    release_order.set()
    await asyncio.wait_for(saving.wait(), 1)
    assert not closing.done()
    release_save.set()
    await asyncio.wait_for(closing, 1)
    timeline.append_voice_exchange.assert_awaited_once()
    assert timeline.append_voice_exchange.await_args.args[1] == "回答连贯些"
    bridge.enqueue_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_and_run_updates_still_reach_voice_ui():
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    try:
        await bridge.queue.put(VoiceTaskEvent(snapshot()))
        task_event = await next_kind(events, "agent.task.updated")
        assert task_event.data["task_ref"] == "请求一"

        await bridge.queue.put(VoiceRunEvent("run-1", "completed"))
        run_event = await next_kind(events, "agent.run.completed")
        assert run_event.data["status"] == "completed"
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("dedicated", [False, True])
async def test_user_speech_preempts_application_presentation_and_pump_survives(
    dedicated,
):
    provider, bridge = Provider(), Bridge()
    presenter = Provider() if dedicated else provider
    bridge.presentation_snapshots.return_value = (snapshot(),)
    coordinator, _ = build_coordinator(
        provider,
        bridge,
        presentation_provider=presenter,
    )
    await coordinator.start()
    events = coordinator.events()
    try:
        await coordinator._queue_presentation(
            PresentationIntent("update", changed_ids=("task:task-1",)),
            persist_exchange=False,
        )
        first = await next_kind(events, "output.begin")
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "speech",
                correlation_id="audio-input",
            ),
        )
        cancelled = await next_kind(events, "output.cancelled")
        assert cancelled.data == {
            "output_id": first.data["output_id"],
            "reason": "barge_in",
        }

        await coordinator._queue_presentation(
            PresentationIntent("update", changed_ids=("task:task-1",)),
            persist_exchange=False,
        )
        await next_kind(events, "speech.started")
        await eventually(lambda: coordinator._active_presentation_task is None)
        await asyncio.sleep(0.01)
        assert presenter.request_response.await_count == 1
        assert not any(
            e.kind == "output.begin" for e in coordinator._events._queue
        )

        # A short pause can wake the pump before a new speech-start event is
        # processed in the same tick. Recheck the gate after the await.
        await provider.queue.put(
            ProviderEvent(
                "speech.stopped",
                "pause",
                correlation_id="audio-input",
            ),
        )
        await provider.queue.put(
            ProviderEvent(
                "speech.started",
                "resume",
                correlation_id="audio-input-2",
            ),
        )
        await next_kind(events, "speech.started")
        await asyncio.sleep(0.01)
        assert presenter.request_response.await_count == 1

        await provider.queue.put(
            ProviderEvent(
                "speech.stopped",
                "stop",
                correlation_id="audio-input-2",
            ),
        )
        second = await next_kind(events, "output.begin")
        assert second.data["output_id"] != first.data["output_id"]
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_close_while_user_speaks_settles_dequeued_history_waiter():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    await coordinator.start()
    await provider.queue.put(
        ProviderEvent("speech.started", "start", correlation_id="user-1"),
    )
    await next_kind(coordinator.events(), "speech.started")
    await coordinator._queue_presentation(
        PresentationIntent("rejected", user_text="not admitted"),
        persist_exchange=True,
    )
    await eventually(lambda: not coordinator._presentation_queue._direct)
    await asyncio.wait_for(coordinator.close(), 1)
    timeline.append_voice_exchange.assert_awaited_once()
    provider.request_response.assert_not_awaited()
    assert not coordinator._history_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["application", "provider_auto"])
@pytest.mark.parametrize("playback", ["drained", "interrupted"])
async def test_update_uses_fresh_context_and_actual_playback_state(
    origin,
    playback,
):
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    try:
        if origin == "application":
            await coordinator._queue_presentation(
                PresentationIntent("update"),
                persist_exchange=False,
            )
            await next_kind(events, "output.begin")
        for kind, data in (
            ("response.started", {}),
            ("output.started", {}),
            ("output_transcript.partial", {"text": "截图"}),
            ("output_transcript.final", {"text": "截图已经保存"}),
        ):
            coordinator._handle_response_event(
                ProviderEvent(
                    kind,
                    kind,
                    data,
                    correlation_id="old-output",
                    response_origin=origin,
                ),
            )
        credit = coordinator._recent_outputs[-1]
        if playback == "drained":
            coordinator._handle_response_event(
                ProviderEvent(
                    "response.finished",
                    "done",
                    {},
                    correlation_id="old-output",
                    response_origin=origin,
                ),
            )
            coordinator.playback_feedback(credit.output_id, playback)
        else:
            await provider.queue.put(
                ProviderEvent("speech.started", "start", correlation_id="new"),
            )
            await next_kind(events, "speech.started")
            coordinator.playback_feedback(credit.output_id, playback)

        # Neither waiting for a final transcript nor reading context should
        # require durable admission/save to finish first.
        await provider.queue.put(transcript("original", "查看D盘并截图"))
        await provider.queue.put(transcript("followup", "截图了吗？"))
        await provider.queue.put(transcript("new", "别再重复确认，截图在哪？"))
        await eventually(
            lambda: coordinator._latest_user_transcript == "别再重复确认，截图在哪？",
        )
        timeline.read_context.return_value = json.dumps(
            {
                "available": True,
                "omitted": False,
                "messages": [{"role": "user", "text": "只说重点"}],
            },
            ensure_ascii=False,
        )
        bridge.presentation_snapshots.return_value = (
            replace(
                snapshot(),
                replies=(
                    ChatReply(
                        "latest",
                        "block",
                        "run-1",
                        ("input-1",),
                        5,
                        "final",
                        "文件是 desktop.png",
                    ),
                ),
            ),
        )
        instruction = await coordinator._presentation_instruction(
            PresentationIntent("update", changed_ids=("latest:block",)),
        )
        assert "只说重点" in instruction
        assert "别再重复确认，截图在哪？" in instruction
        context = json.loads(instruction.split("\n")[-1])
        assert context["recent_user_transcripts"] == [
            "查看D盘并截图",
            "截图了吗？",
            "别再重复确认，截图在哪？",
        ]
        assert "desktop.png" in instruction
        assert '"text": "截图已经保存"' in instruction
        assert f'"playback": "{playback}"' in instruction
        assert "不知道具体听到了哪一字" in instruction
        assert "不能视为用户已经听完" in instruction
        bridge.enqueue_input.assert_not_awaited()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_role", ["system", "user"])
async def test_acknowledged_item_cannot_revive_cancelled_presentation(
    blocked_role,
):
    provider, bridge = Provider(), Bridge()
    presenter = DashScopeRealtimeSession(SimpleNamespace(), "unused-offline")
    presenter.connect = AsyncMock()
    presenter.close = AsyncMock()
    presenter.delete_items = AsyncMock()
    presenter.request_response = AsyncMock()
    waiting = asyncio.Event()
    pending_ack = None

    async def send(kind, **payload):
        nonlocal pending_ack
        assert kind == "conversation.item.create"
        item = payload["item"]
        ack = presenter._pending_items[item["id"]]
        if item["role"] == blocked_role:
            pending_ack = ack
            waiting.set()
        else:
            ack.set_result(None)

    presenter._send = send
    coordinator, _ = build_coordinator(
        provider,
        bridge,
        presentation_provider=presenter,
    )
    await coordinator.start()
    try:
        await coordinator._queue_presentation(
            PresentationIntent("update"),
            persist_exchange=False,
        )
        await asyncio.wait_for(waiting.wait(), 1)
        # Python 3.11 wait_for can consume cancellation when its inner ACK
        # completes in the same tick. Exercise the real adapter's wait here.
        pending_ack.set_result(None)
        coordinator._preempt_presentation("barge_in")
        await eventually(lambda: coordinator._active_presentation_task is None)
        presenter.request_response.assert_not_awaited()
        assert [e.kind for e in coordinator._events._queue] == [
            "output.cancelled",
        ]
        assert not coordinator._presentation_failed
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_cancelled_response_drops_late_media_but_tracks_terminal():
    provider, presenter, bridge = Provider(), Provider(), Bridge()
    release = asyncio.Event()

    async def respond():
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Keep the provider running long enough to deliver late frames.
            await release.wait()
        return ProviderResponseResult("completed", (), "late answer")

    presenter.request_response.side_effect = respond
    coordinator, _ = build_coordinator(
        provider,
        bridge,
        presentation_provider=presenter,
    )
    await coordinator.start()
    events = coordinator.events()
    try:
        await coordinator._queue_presentation(
            PresentationIntent("update"),
            persist_exchange=False,
        )
        await next_kind(events, "output.begin")
        credit = coordinator._output_credit
        await provider.queue.put(
            ProviderEvent("speech.started", "start", correlation_id="user-1"),
        )
        await next_kind(events, "output.cancelled")
        await next_kind(events, "speech.started")
        # The start ACK itself may arrive after the output was revoked.
        for kind in (
            "response.started",
            "output.started",
            "output.audio",
            "output_transcript.final",
            "response.finished",
        ):
            await presenter.queue.put(
                ProviderEvent(
                    kind,
                    kind,
                    {"text": "late"},
                    correlation_id="old-response",
                    response_origin="application",
                ),
            )
        await asyncio.wait_for(credit.terminal.wait(), 1)
        assert credit.cancelled
        assert credit.provider_id == "old-response"
        assert coordinator._events.empty()
        release.set()
        await eventually(lambda: coordinator._active_presentation_task is None)
        await provider.queue.put(
            ProviderEvent("speech.stopped", "stop", correlation_id="user-1"),
        )
        await coordinator._queue_presentation(
            PresentationIntent("update"),
            persist_exchange=False,
        )
        await next_kind(events, "output.begin")
        for response_id in ("old-response", "new-response"):
            await presenter.queue.put(
                ProviderEvent(
                    "response.started",
                    response_id,
                    correlation_id=response_id,
                    response_origin="application",
                ),
            )
        current = await next_kind(events, "response.started")
        assert current.correlation_id == "new-response"
        assert current.data["output_id"] != credit.output_id
        assert not coordinator._presentation_failed
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("result_count", [1, 10])
async def test_background_results_wait_for_playback_without_preempting(
    result_count,
):
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge)
    seen = []

    async def collect():
        async for event in coordinator.events():
            seen.append(event)

    def events(kind):
        return [event for event in seen if event.kind == kind]

    await coordinator.start()
    collector = asyncio.create_task(collect())
    try:
        await coordinator._queue_presentation(
            PresentationIntent("update"),
            persist_exchange=False,
        )
        await eventually(lambda: bool(events("output.begin")))
        first = events("output.begin")[0].data["output_id"]
        results = tuple(
            replace(
                snapshot(f"task-{index}", status="responded"),
                replies=(
                    ChatReply(
                        f"message-{index}",
                        "final",
                        "run-1",
                        (f"input-{index}",),
                        1,
                        "final",
                        f"结果是{index}",
                    ),
                ),
            )
            for index in range(result_count)
        )
        bridge.presentation_snapshots.return_value = results
        for result in results:
            await bridge.queue.put(VoiceTaskEvent(result))
        await eventually(
            lambda: len(events("agent.task.updated")) == result_count,
        )
        for kind in ("response.started", "response.finished"):
            await provider.queue.put(
                ProviderEvent(
                    kind,
                    kind,
                    {},
                    correlation_id="response-1",
                    response_origin="application",
                ),
            )
        await eventually(lambda: bool(events("output.sealed")))
        coordinator.playback_feedback("old-session-output", "drained")
        await asyncio.sleep(0.01)
        assert not events("output.cancelled")
        assert len(events("output.begin")) == 1
        coordinator.playback_feedback(first, "drained")
        await eventually(lambda: len(events("output.begin")) == 2)
        assert all(
            f"结果是{index}" in provider.created_messages[-2][2]
            for index in range(result_count)
        )
        # Repeated or older task snapshots never schedule another output.
        for result in results:
            await bridge.queue.put(VoiceTaskEvent(result))
        await asyncio.sleep(0.01)
        assert len(events("output.begin")) == 2
    finally:
        await coordinator.close()
        await collector


def test_update_instruction_replaces_stale_progress_with_latest_final_reply():
    progress = ChatReply(
        "message-1",
        "progress",
        "run-1",
        ("input-1",),
        1,
        "progress",
        "仍在排队",
    )
    final = ChatReply(
        "message-2",
        "final",
        "run-1",
        ("input-1",),
        2,
        "final",
        "实际输出是 301",
    )
    current = VoiceTaskSnapshot(
        task_id="task-1",
        task_ref="请求一",
        status="responded",
        version=3,
        request="运行命令",
        run_id="run-1",
        replies=(progress, final),
        input_states=(
            ("input-1", "completed"),
            ("followup", "queued"),
        ),
        input_requests=(
            ("input-1", "运行命令"),
            ("followup", "执行完了吗？"),
        ),
    )

    instruction = build_update_instruction(
        (current,),
        PresentationIntent("update", changed_ids=(progress.identity,)),
    )

    assert "实际输出是 301" in instruction
    assert "仍在排队" not in instruction
    # A pending status question is not evidence that the operation is queued.
    assert "other_requests_pending" not in instruction
    assert "执行完了吗？" not in instruction
    assert "运行命令" in instruction


@pytest.mark.asyncio
async def test_start_waits_for_history_ack_without_executing_it():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    history = {
        "available": True,
        "omitted": False,
        "messages": [
            {"role": "user", "source": "voice", "text": "创建 old.txt"},
            {"role": "assistant", "source": "agent", "text": "已创建 old.txt"},
        ],
    }
    timeline.read_context.return_value = json.dumps(history)
    entered, release = asyncio.Event(), asyncio.Event()

    async def create(role, text):
        assert (
            role == "user"
            and "已创建 old.txt"
            in json.loads(text.split("\n")[1])["messages"][1]["text"]
        )
        entered.set()
        await release.wait()
        return "history-item"

    provider.create_message = create
    starting = asyncio.create_task(coordinator.start())
    await asyncio.wait_for(entered.wait(), 1)
    assert not starting.done()
    provider.request_response.assert_not_awaited()
    bridge.enqueue_input.assert_not_awaited()
    release.set()
    await starting
    await coordinator.close()
    bridge.enqueue_input.assert_not_awaited()
    provider.request_response.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["read", "unavailable", "ack", "timeout"])
async def test_history_failure_does_not_start_voice_without_context(failure):
    from qwenpaw.app.realtime_voice.contracts import RealtimeVoiceServiceError

    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(
        provider,
        bridge,
        history_timeout_seconds=0.01,
    )
    timeline.read_context.return_value = json.dumps(
        {"available": True, "messages": [{"role": "user", "text": "secret"}]},
    )
    if failure == "read":
        timeline.read_context.side_effect = OSError("read failed")
    elif failure == "unavailable":
        timeline.read_context.return_value = '{"available":false}'
    elif failure == "ack":
        provider.create_message = AsyncMock(side_effect=OSError("rejected"))
    else:
        provider.create_message = AsyncMock(side_effect=lambda *_: None)

        async def stall(*_):
            await asyncio.Event().wait()

        provider.create_message = stall
    with pytest.raises(
        RealtimeVoiceServiceError,
        match="restore conversation history",
    ):
        await coordinator.start()
    assert not coordinator._tasks
    provider.request_response.assert_not_awaited()
    bridge.enqueue_input.assert_not_awaited()
    await coordinator.close()


@pytest.mark.asyncio
async def test_incomplete_history_routes_live_input_to_chat():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, timeline = build_coordinator(provider, bridge)
    timeline.read_context.return_value = (
        '{"available":true,"omitted":true,"messages":[]}'
    )
    coordinator._queue_admission = AsyncMock()
    await coordinator.start()
    await provider.queue.put(
        ProviderEvent("speech.started", "s", {}, correlation_id="live"),
    )
    await provider.queue.put(transcript("live", "刚才的暗号是什么"))
    await provider.queue.put(
        ProviderEvent(
            "response.finished",
            "r",
            {
                "input_item_id": "live",
                "status": "completed",
                "transcript": "错误猜测",
            },
            correlation_id="r",
            response_origin="provider_auto",
        ),
    )
    await eventually(lambda: bridge.enqueue_input.await_count == 1)
    assert bridge.enqueue_input.await_args.args[0] == "刚才的暗号是什么"
    await coordinator.close()
    assert not any(
        event.data.get("text") == "错误猜测"
        for event in list(coordinator._events._queue)
        if isinstance(event, ProviderEvent)
    )


@pytest.mark.asyncio
async def test_history_item_cannot_admit_work_without_live_speech():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    timeline.read_context.return_value = json.dumps(
        {
            "available": True,
            "omitted": False,
            "messages": [
                {"role": "user", "source": "voice", "text": "重复旧任务"},
                {"role": "assistant", "source": "agent", "text": "旧任务已完成"},
            ],
        },
    )
    await coordinator.start()
    await provider.queue.put(
        tool_call("history-call", "重复旧任务", source_id="message-1"),
    )
    await eventually(lambda: provider.complete_tool_call.await_count == 1)
    assert provider.complete_tool_call.await_args.args[1]["accepted"] is False
    bridge.enqueue_input.assert_not_awaited()
    await coordinator.close()


@pytest.mark.asyncio
async def test_all_close_callers_wait_for_save_even_if_one_is_cancelled():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    entered, release = asyncio.Event(), asyncio.Event()

    async def save(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return []

    timeline.append_voice_exchange.side_effect = save
    await coordinator.start()
    await provider.queue.put(transcript("tail", "必须保存"))
    await eventually(lambda: "tail" in coordinator._input_transcripts)
    first = asyncio.create_task(coordinator.close())
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert not second.done()
    release.set()
    await asyncio.wait_for(second, 1)
    timeline.append_voice_exchange.assert_awaited_once()
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_failure_is_reported_to_every_close_caller():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
    timeline.append_voice_exchange.side_effect = OSError("disk unavailable")
    await coordinator.start()
    await provider.queue.put(transcript("tail", "不能丢失"))
    await eventually(lambda: "tail" in coordinator._input_transcripts)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="history could not be saved"):
            await coordinator.close()
    provider.close.assert_awaited_once()
