import asyncio
import json
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
from qwenpaw.app.realtime_voice.presentation import PresentationIntent
from qwenpaw.app.realtime_voice.prompts import build_update_instruction
from qwenpaw.app.realtime_voice.task_bridge import VoiceAdmissionHandle
from qwenpaw.providers.realtime_voice import ProviderEvent, ProviderResponseResult


class Provider:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.connect = AsyncMock()
        self.send_audio = AsyncMock()
        self.interrupt_output = AsyncMock()
        self.close = AsyncMock()
        self.complete_tool_call = AsyncMock(return_value="tool-output-1")
        self.request_response = AsyncMock(
            return_value=ProviderResponseResult("completed", ("assistant-1",), "好的。")
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
            "arguments": json.dumps({"request_text": text}, ensure_ascii=False),
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
async def test_native_handoff_admits_exact_model_request_and_returns_receipt():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    events = coordinator.events()
    try:
        await provider.queue.put(tool_call("call-1", "截图桌面并说明重点"))
        committed = await next_kind(events, "input_turn.committed")
        await eventually(lambda: provider.complete_tool_call.await_count == 1)

        call = bridge.enqueue_input.await_args
        assert call.args == ("截图桌面并说明重点",)
        assert call.kwargs["idempotency_key"] == committed.data["turn_id"]
        assert call.kwargs["admission_mode"] == "steer"
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
async def test_repeated_native_handoff_steers_current_chat_work():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    try:
        await provider.queue.put(tool_call("call-2", "不要上传，只保存在桌面"))
        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        assert bridge.enqueue_input.await_args.kwargs["admission_mode"] == "steer"
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_duplicate_native_call_is_admitted_and_announced_once():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.start()
    try:
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
async def test_direct_realtime_answer_streams_and_persists_once():
    provider, bridge = Provider(), Bridge()
    coordinator, timeline = build_coordinator(provider, bridge)
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
            )
        )
        await provider.queue.put(
            ProviderEvent(
                "output.started",
                "o-start",
                correlation_id="response-1",
                response_origin="provider_auto",
            )
        )
        await provider.queue.put(
            ProviderEvent(
                "output.audio",
                "audio",
                audio=b"pcm",
                correlation_id="response-1",
                response_origin="provider_auto",
            )
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
            )
        )

        begin = await next_kind(events, "output.begin")
        audio = await next_kind(events, "output.audio")
        assert audio.audio == b"pcm"
        assert audio.data["output_id"] == begin.data["output_id"]
        await next_kind(events, "output.sealed")
        coordinator.playback_feedback(begin.data["output_id"], "drained")
        await eventually(lambda: timeline.append_voice_exchange.await_count == 1)
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
            )
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
            )
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
            )
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
        assert [tool.name for tool in config.tools] == ["handoff_to_chat"]
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
        result = await coordinator._present(PresentationIntent("rejected"))

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
async def test_task_owned_turn_suppresses_native_answer_and_falls_back_to_chat():
    provider, bridge = Provider(), Bridge()
    bridge.presentation_snapshots.return_value = (snapshot(status="responded"),)
    bridge.enqueue_input.return_value = admission(receipt("fallback-task"))
    coordinator, timeline = build_coordinator(provider, bridge)
    coordinator._queue_admission = AsyncMock()
    await coordinator.start()
    try:
        await provider.queue.put(
            ProviderEvent("speech.started", "speech", correlation_id="source-2")
        )
        await provider.queue.put(transcript("source-2", "只告诉我实际结果"))
        await provider.queue.put(
            ProviderEvent(
                "response.started",
                "started",
                {"input_item_id": "source-2"},
                correlation_id="response-2",
                response_origin="provider_auto",
            )
        )
        await provider.queue.put(
            ProviderEvent(
                "output_transcript.final",
                "wrong-answer",
                {"text": "还在排队"},
                correlation_id="response-2",
                response_origin="provider_auto",
            )
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
            )
        )

        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        assert bridge.enqueue_input.await_args.args == ("只告诉我实际结果",)
        assert bridge.enqueue_input.await_args.kwargs["admission_mode"] == "steer"
        assert bridge.enqueue_input.await_args.kwargs["idempotency_key"].startswith(
            "voice_fallback_"
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


@pytest.mark.asyncio
async def test_task_owned_native_tool_call_does_not_duplicate_asr_fallback():
    provider, bridge = Provider(), Bridge()
    bridge.presentation_snapshots.return_value = (snapshot(status="processing"),)
    bridge.enqueue_input.return_value = admission(receipt())
    coordinator, _ = build_coordinator(provider, bridge)
    coordinator._queue_admission = AsyncMock()
    await coordinator.start()
    try:
        await provider.queue.put(
            ProviderEvent("speech.started", "speech", correlation_id="source-3")
        )
        await provider.queue.put(transcript("source-3", "查询当前结果"))
        await provider.queue.put(
            ProviderEvent(
                "response.started",
                "started",
                {"input_item_id": "source-3"},
                correlation_id="response-3",
                response_origin="provider_auto",
            )
        )
        await provider.queue.put(
            tool_call(
                "call-3",
                "查询当前结果",
                source_id="source-3",
            )
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
            )
        )

        await eventually(lambda: bridge.enqueue_input.await_count == 1)
        assert bridge.enqueue_input.await_args.args == ("查询当前结果",)
        assert bridge.enqueue_input.await_args.kwargs["admission_mode"] == "steer"
        assert not bridge.enqueue_input.await_args.kwargs["idempotency_key"].startswith(
            "voice_fallback_"
        )
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_interrupt_only_cancels_current_speech_output():
    provider, bridge = Provider(), Bridge()
    coordinator, _ = build_coordinator(provider, bridge)
    await coordinator.interrupt()
    provider.interrupt_output.assert_awaited_once()
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
async def test_user_speech_preempts_application_presentation_and_pump_survives():
    provider, bridge = Provider(), Bridge()
    bridge.presentation_snapshots.return_value = (snapshot(),)
    coordinator, _ = build_coordinator(provider, bridge)
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
            )
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
        second = await next_kind(events, "output.begin")
        assert second.data["output_id"] != first.data["output_id"]
    finally:
        await coordinator.close()


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
        input_states=(("input-1", "completed"),),
        input_requests=(("input-1", "运行命令"),),
    )

    instruction = build_update_instruction(
        (current,),
        PresentationIntent("update", changed_ids=(progress.identity,)),
    )

    assert "实际输出是 301" in instruction
    assert "仍在排队" not in instruction
