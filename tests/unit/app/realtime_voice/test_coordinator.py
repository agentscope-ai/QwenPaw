import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.chats.replies import ChatReply, ChatReplyView

from qwenpaw.app.realtime_voice.contracts import (
    ConverseVoiceAction,
    HandoffVoiceAction,
    VoiceRunEvent,
    VoiceTaskEvent,
    VoiceTaskReceipt,
    VoiceTaskSnapshot,
)
from qwenpaw.app.realtime_voice.coordinator import VoiceCoordinator
from qwenpaw.app.realtime_voice.presentation import (
    PresentationIntent,
    PresentationQueue,
)
from qwenpaw.app.realtime_voice.prompts import snapshot_facts
from qwenpaw.app.realtime_voice.task_bridge import VoiceAdmissionHandle
from qwenpaw.app.realtime_voice.turn_commit import (
    CommittedSpokenTurn,
    SpokenTurnCommitter,
    VoiceRouteDecision,
)
from qwenpaw.providers.realtime_voice import (
    ProviderEvent,
    ProviderResponseResult,
)
from qwenpaw.runtime.reply_cycle import (
    set_reply_block_metadata,
    update_reply_block_metadata,
)


class Provider:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.connect = AsyncMock()
        self.send_audio = AsyncMock()
        self.interrupt_output = AsyncMock()
        self.close = AsyncMock()
        self.request_response = AsyncMock(
            return_value=ProviderResponseResult(
                "completed",
                ("assistant-1",),
                "好的。",
            )
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
        self.submit = AsyncMock()
        self.status = AsyncMock(return_value=snapshot("task-1"))
        self.enqueue_action = AsyncMock()
        self.observe_input = Mock()
        self.routing_snapshots = AsyncMock(return_value=())
        self.presentation_snapshots = self.routing_snapshots
        self.observe_active_run = AsyncMock(return_value=None)

    def subscribe(self):
        return self.queue

    def unsubscribe(self, _queue):
        return None


async def next_kind(events, kind):
    while True:
        event = await asyncio.wait_for(anext(events), timeout=1)
        if event.kind == kind:
            return event


async def eventually(predicate) -> None:
    for _attempt in range(500):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


@pytest.mark.asyncio
async def test_handoff_preserves_original_words_without_voice_history_write():
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_action.side_effect = [
        admission(receipt(task_id="a", task_ref="请求一")),
        admission(receipt(task_id="b", task_ref="请求二")),
    ]

    async def route(_text, **_kwargs):
        return replace(
            VoiceRouteDecision.commit(HandoffVoiceAction()),
            conversation_context=timeline.read_context.return_value,
        )

    coordinator, _, timeline = build_coordinator(provider, bridge, route)
    timeline.read_context.return_value = "公开前文403；这是受控历史，不是重新执行授权"
    await coordinator.start()
    try:
        for source, text in (
            ("first", "之前为什么失败？不要重新执行。"),
            ("second", "再告诉我对应文件名"),
        ):
            await provider.queue.put(input_segment(source, text))
            await eventually(
                lambda: bridge.enqueue_action.await_count
                == (1 if source == "first" else 2)
            )
        calls = bridge.enqueue_action.await_args_list
        assert [call.args[1] for call in calls] == [
            "之前为什么失败？不要重新执行。",
            "再告诉我对应文件名",
        ]
        assert (
            calls[0].kwargs["idempotency_key"]
            != calls[1].kwargs["idempotency_key"]
        )
        assert all(
            call.kwargs["conversation_context"]
            == timeline.read_context.return_value
            for call in calls
        )
        timeline.append_voice_exchange.assert_not_awaited()
        timeline.observe_voice_exchange.assert_not_called()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_commit_registration_does_not_wait_for_previous_history_save():
    provider, bridge = Provider(), Bridge()

    async def route(_text, **_kwargs):
        return VoiceRouteDecision.commit(
            ConverseVoiceAction()
            if _text == "What happened?"
            else HandoffVoiceAction()
        )

    bridge.enqueue_action.return_value = admission(receipt())
    coordinator, _, timeline = build_coordinator(provider, bridge, route)
    saving, release = asyncio.Event(), asyncio.Event()

    async def slow_save(*_args, **_kwargs):
        saving.set()
        await release.wait()
        return []

    timeline.append_voice_exchange.side_effect = slow_save
    await coordinator.start()
    try:
        await provider.queue.put(input_segment("first", "What happened?"))
        await asyncio.wait_for(saving.wait(), 1)
        await provider.queue.put(input_segment("later", "Do not run again"))
        await eventually(lambda: bridge.observe_input.call_count == 2)
        assert bridge.observe_input.call_args.args[1] == "Do not run again"
        await eventually(lambda: bridge.enqueue_action.await_count == 1)
        bridge.enqueue_action.assert_awaited_once()
        assert bridge.enqueue_action.await_args.args[1] == "Do not run again"
    finally:
        release.set()
        await coordinator.close()


async def acknowledge_fake_output(coordinator, provider):
    """Explicit fake Provider/renderer ACK, not real audio playback."""
    credit = coordinator._output_credit
    assert credit is not None
    for kind in ("response.started", "response.finished"):
        await provider.queue.put(
            ProviderEvent(
                kind,
                kind,
                correlation_id=credit.output_id,
                response_origin="application",
            )
        )
    await eventually(lambda: credit.sealed)
    coordinator.playback_feedback(credit.output_id, "drained")


@pytest.mark.asyncio
async def test_converse_purpose_does_not_assert_task_category_or_mutation():
    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(provider, bridge, [])
    instruction = await coordinator._presentation_instruction(
        PresentationIntent("converse")
    )
    assert "本轮是普通对话或知识问答" not in instruction
    assert "不要把内部回复方式当作用户意图或任务类型" in instruction
    assert "信息不足时不要补造前文" in instruction
    assert "本轮没有提交或更改任务" in instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("referenced", [False, True])
async def test_admission_uses_accepted_words_without_waiting_for_task_state(
    referenced,
):
    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(provider, bridge, [])
    original = "更正报告的范围，只查询，不要重做。" if referenced else "准备季度报告。"
    action = (
        HandoffVoiceAction("内部任务九") if referenced else HandoffVoiceAction()
    )
    turn = CommittedSpokenTurn(
        turn_id="turn",
        text=original,
        source_ids=("source",),
        origin="semantic",
        action=action,
    )
    await coordinator._queue_admission(turn, receipt(task_ref="内部任务九"))
    intent = await coordinator._presentation_queue.get()
    assert intent.kind == "admission"
    assert intent.history_user_text == original
    await coordinator._present(intent)
    instruction = provider.created_messages[-2][2]
    assert original in instruction
    assert '"accepted": true' in instruction
    assert '"request_kind": "message"' in instruction
    assert "内部任务九" not in instruction
    assert "接收补充不代表已经修改、重新执行或取消了操作" in instruction
    bridge.presentation_snapshots.assert_not_awaited()
    bridge.enqueue_action.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["update"])
async def test_speech_keeps_request_and_answer_without_fabricated_names(kind):
    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(provider, bridge, [])
    original = "请处理第二季度报表，结果文件叫任务一.csv。"
    correction = "改成第三季度，但是不要重做，只查刚才的结果。"
    replies = (
        ChatReply("first", "body", "run", ("a",), 1, "final", "已有结果：42。"),
        ChatReply("second", "body", "run", ("b",), 2, "final", "已有结果：42。"),
    )
    task = replace(
        snapshot("task-1", "responded", task_ref="内部任务九"),
        request=original,
        input_states=(("a", "completed"), ("b", "completed")),
        input_requests=(("a", original), ("b", correction)),
        replies=replies,
    )
    bridge.presentation_snapshots.return_value = (task,)
    instruction = await coordinator._presentation_instruction(
        PresentationIntent(kind)
    )
    assert original in instruction and correction in instruction
    assert "内部任务九" not in instruction
    assert "第1条输入" not in instruction and "第2项要求" not in instruction
    assert (
        '"request_order": 1' in instruction
        and '"request_order": 2' in instruction
    )
    assert instruction.count('"text": "已有结果：42。"') == 2
    assert "补充要求的答复返回不代表按补充要求重新执行了操作" in instruction
    assert task.replies == replies
    assert task.task_ref == "内部任务九"


@pytest.mark.asyncio
async def test_converse_keeps_current_words_without_submitting_work():
    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(provider, bridge, [])
    text = "这不是定时或周期任务。"
    await coordinator._present(PresentationIntent("converse", user_text=text))
    assert [(role, body) for _, role, body in provider.created_messages] == [
        (
            "system",
            await coordinator._presentation_instruction(
                PresentationIntent("converse")
            )
            + "\n"
            + coordinator._language_instruction,
        ),
        ("user", text),
    ]
    bridge.enqueue_action.assert_not_awaited()
    bridge.submit.assert_not_awaited()
    bridge.presentation_snapshots.assert_not_awaited()
    provider.delete_items.assert_awaited_once()


@pytest.mark.asyncio
async def test_next_converse_receives_generated_context_before_disk_save(
    tmp_path,
):
    import json
    from qwenpaw.app.chats.session import SafeJSONSession
    from qwenpaw.app.chats.timeline import ChatTimelineJournal
    from qwenpaw.app.task_tracker import TaskTracker

    chat = SimpleNamespace(
        id="chat", session_id="session", user_id="user", channel="console"
    )
    workspace = SimpleNamespace(
        session=SafeJSONSession(str(tmp_path)),
        task_tracker=TaskTracker(),
        chat_manager=SimpleNamespace(touch_chat=AsyncMock()),
    )
    timeline = ChatTimelineJournal(workspace, chat)
    provider, bridge = Provider(), Bridge()
    provider.request_response.side_effect = [
        ProviderResponseResult("completed", ("reply-1",), "植物利用阳光制造养分。"),
        ProviderResponseResult("completed", ("reply-2",), "植物用阳光做食物。"),
    ]
    coordinator = VoiceCoordinator(
        provider,
        bridge,
        SimpleNamespace(close=AsyncMock()),
        timeline,
        max_history_turns=7,
        context_max_chars=999,
    )
    save_entered, release_save = asyncio.Event(), asyncio.Event()
    append = timeline.append_voice_exchange

    async def delayed_save(*args, **kwargs):
        if args[2]:
            save_entered.set()
            await release_save.wait()
        return await append(*args, **kwargs)

    timeline.append_voice_exchange = delayed_save
    try:
        await coordinator._queue_presentation(
            PresentationIntent("converse", "q1", "什么是光合作用？"),
            persist_exchange=True,
        )
        await coordinator._present(await coordinator._presentation_queue.get())
        await asyncio.wait_for(save_entered.wait(), 1)
        await coordinator._queue_presentation(
            PresentationIntent("converse", "q2", "把刚才的解释说得更简单一点"),
            persist_exchange=True,
        )
        queued = await coordinator._presentation_queue.get()
        assert queued.timeline_order == 2
        await coordinator._present(queued)
        raw_history = provider.created_messages[-2][2]
        history = json.loads(raw_history)
        answer = next(
            m for m in history["messages"] if m["id"] == "q1_assistant"
        )
        assert answer["text"] == "植物利用阳光制造养分。"
        assert answer["persisted"] is False
        assert not any("q2" in m["input_ids"] for m in history["messages"])
        assert len(raw_history) <= 999
        assert provider.created_messages[-1][2] == queued.user_text
        assert provider.delete_items.await_count == 2
        bridge.enqueue_action.assert_not_awaited()
    finally:
        release_save.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_direct_converse_waits_for_ordered_seal_and_browser_credit():
    provider, bridge = Provider(), Bridge()
    coordinator, _, timeline = build_coordinator(provider, bridge, [])
    await coordinator.start()
    await coordinator._queue_presentation(
        PresentationIntent("converse", "first", "hello"), persist_exchange=True
    )
    await eventually(lambda: provider.request_response.await_count == 1)
    credit = coordinator._output_credit
    assert credit is not None
    # Generated history is already persisted even though playback has no ACK.
    await eventually(lambda: timeline.append_voice_exchange.await_count == 2)
    await coordinator._queue_presentation(
        PresentationIntent("update", user_text="update"),
        persist_exchange=False,
    )
    await coordinator._queue_presentation(
        PresentationIntent("converse", "query", "hello again"),
        persist_exchange=True,
    )
    bridge.presentation_snapshots.return_value = tuple(
        snapshot(f"task-{i}", "processing") for i in range(25)
    )
    assert provider.request_response.await_count == 1
    for kind in ("response.started", "output.audio", "response.finished"):
        await provider.queue.put(
            ProviderEvent(
                kind,
                kind,
                audio=b"pcm" if kind == "output.audio" else None,
                correlation_id="real-order",
                response_origin="application",
            )
        )
    await eventually(lambda: credit.sealed)
    assert provider.request_response.await_count == 1
    forwarded = list(coordinator._events._queue)
    assert [
        e.kind
        for e in forwarded
        if e.kind in {"output.begin", "output.audio", "output.sealed"}
    ] == ["output.begin", "output.audio", "output.sealed"]
    coordinator.playback_feedback("old-output", "drained")
    assert provider.request_response.await_count == 1
    coordinator.playback_feedback(credit.output_id, "drained")
    await eventually(lambda: provider.request_response.await_count == 2)
    assert provider.created_messages[-1][2] == "hello again"
    assert "共25项" not in provider.created_messages[-2][2]
    assert "request task-" not in provider.created_messages[-2][2]
    # Late response events cannot be rebound to the new output.
    await provider.queue.put(
        ProviderEvent(
            "output.audio",
            "late",
            audio=b"stale",
            correlation_id="real-order",
            response_origin="application",
        )
    )
    await asyncio.sleep(0)
    assert not any(e.audio == b"stale" for e in coordinator._events._queue)
    await coordinator.close()


@pytest.mark.asyncio
async def test_overload_preserves_text_without_resubmitting_admitted_work():
    provider, bridge = Provider(), Bridge()
    coordinator, _, timeline = build_coordinator(provider, bridge, [])
    coordinator._presentation_queue = PresentationQueue(1)
    await coordinator.start()
    for turn in ("first", "queued", "rejected"):
        await coordinator._queue_presentation(
            PresentationIntent("converse", turn, turn), persist_exchange=True
        )
        if turn == "first":
            await eventually(
                lambda: provider.request_response.await_count == 1
            )
    await coordinator._queue_presentation(
        PresentationIntent("admission", "admitted", task_ref="请求一"),
        persist_exchange=False,
    )
    rejected = [
        e
        for e in coordinator._events._queue
        if e.kind == "presentation.rejected"
    ]
    assert [e.data["task_admitted"] for e in rejected] == [False, True]
    await eventually(lambda: timeline.append_voice_exchange.await_count >= 3)
    assert any(
        c.args[:3] == ("rejected", "rejected", "")
        for c in timeline.append_voice_exchange.await_args_list
    )
    bridge.enqueue_action.assert_not_awaited()
    await coordinator.close()


def snapshot(
    task_id: str,
    status="processing",
    run_id="run-1",
    *,
    task_ref="请求一",
    version=2,
):
    return VoiceTaskSnapshot(
        task_id=task_id,
        task_ref=task_ref,
        status=status,
        version=version,
        request=f"request {task_id}",
        run_id=run_id,
    )


def receipt(
    task_id="task-1",
    task_ref="请求一",
    status="processing",
):
    return VoiceTaskReceipt(
        task_id=task_id,
        task_ref=task_ref,
        accepted=True,
        status=status,
    )


def admission(result: VoiceTaskReceipt) -> VoiceAdmissionHandle:
    completion = asyncio.get_running_loop().create_future()
    completion.set_result(result)
    return VoiceAdmissionHandle(completion)


def build_coordinator(provider, bridge, route, **options):
    router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(router, continuation_grace_ms=0)
    timeline = SimpleNamespace(
        reserve_order=AsyncMock(side_effect=range(1, 100)),
        append_voice_exchange=AsyncMock(return_value=[]),
        reconcile=AsyncMock(return_value=0),
        read_context=AsyncMock(return_value=""),
        observe_voice_exchange=Mock(),
    )
    coordinator = VoiceCoordinator(
        provider, bridge, committer, timeline, **options
    )
    return coordinator, router, timeline


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh-CN", "en-US"])
async def test_configured_reply_language_reaches_voice_session(language):
    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(
        provider, bridge, [], language=language
    )
    try:
        await coordinator.start()
        instructions = provider.connect.call_args.args[0].instructions
        assert f'"{language}"' in instructions
        assert "中文口语" not in instructions
        assert "不要执行任务" in instructions
        for kind in (
            "converse",
            "admission",
            "update",
            "clarify",
            "rejected",
        ):
            provider.created_messages.clear()
            await coordinator._present(PresentationIntent(kind))
            assert f'"{language}"' in provider.created_messages[0][2]
            assert (
                "quoted facts is not a language request"
                in provider.created_messages[0][2]
            )
    finally:
        await coordinator.close()


def input_segment(source_id: str, text: str) -> ProviderEvent:
    return ProviderEvent(
        "input_transcript.final",
        source_id,
        {"text": text},
        correlation_id=source_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_provider_terminal_settles_only_its_source_before_admission(
    failed,
):
    provider, bridge = Provider(), Bridge()
    bridge.enqueue_action.return_value = admission(receipt())
    entered, release = asyncio.Event(), asyncio.Event()

    async def route(text, **_kwargs):
        entered.set()
        await release.wait()
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    coordinator, router, _ = build_coordinator(provider, bridge, route)
    await coordinator.start()
    events = coordinator.events()
    try:
        await provider.queue.put(input_segment("first", "输出301。"))
        await asyncio.wait_for(entered.wait(), 1)
        for kind in ("speech.started", "speech.stopped"):
            await provider.queue.put(
                ProviderEvent(kind, kind, correlation_id="later")
            )
        await next_kind(events, "speech.stopped")
        release.set()
        await eventually(lambda: coordinator._committer._routing_task is None)
        bridge.enqueue_action.assert_not_awaited()
        terminal = (
            ProviderEvent(
                "input_transcript.failed", "failed", correlation_id="later"
            )
            if failed
            else input_segment("later", "")
        )
        await provider.queue.put(terminal)
        if failed:
            error = await next_kind(events, "error")
            assert error.data["code"] == "voice_transcription_failed"
            assert not coordinator._committer._unsettled
            bridge.enqueue_action.assert_not_awaited()
            assert router.route.await_count == 1
        else:
            await eventually(lambda: bridge.enqueue_action.await_count == 1)
            assert bridge.observe_input.call_args.args[1] == "输出301。"
            assert not coordinator._committer._unsettled
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_handoff_uses_ordinary_chat_bridge_and_speech_only_response():
    provider = Provider()
    bridge = Bridge()
    bridge.enqueue_action.return_value = admission(receipt())
    bridge.status.return_value = snapshot("task-1")

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision(
            "COMMIT", HandoffVoiceAction(), "quoted data"
        )

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(input_segment("source-1", "run tests"))

    committed = await next_kind(events, "input_turn.committed")
    accepted = await next_kind(events, "agent.input.accepted")
    await eventually(lambda: provider.request_response.await_count == 1)

    assert committed.data["action"] == {"type": "HANDOFF"}
    assert accepted.data["turn_id"] == committed.data["turn_id"]
    assert accepted.data["input_id"] == "task-1"
    assert accepted.data["task_ref"] == "请求一"
    assert accepted.correlation_id == committed.data["turn_id"]
    bridge.enqueue_action.assert_awaited_once_with(
        HandoffVoiceAction(),
        "run tests",
        idempotency_key=committed.data["turn_id"],
        admission_mode="queue",
        conversation_context="quoted data",
    )
    assert [role for _item, role, _text in provider.created_messages] == [
        "system",
        "user",
    ]
    await coordinator.close()


@pytest.mark.asyncio
async def test_ten_long_tasks_are_admitted_while_first_speech_is_blocked():
    provider = Provider()
    first_speech = asyncio.Event()

    async def respond():
        await first_speech.wait()
        return ProviderResponseResult("completed", transcript="已接收")

    provider.request_response.side_effect = respond
    bridge = Bridge()
    bridge.enqueue_action.side_effect = [
        admission(receipt(f"task-{index}", f"任务{index}", "queued"))
        for index in range(1, 11)
    ]
    bridge.status.side_effect = [
        snapshot(
            f"task-{index}",
            "queued",
            "",
            task_ref=f"任务{index}",
        )
        for index in range(1, 11)
    ]

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()

    for index in range(1, 11):
        text = f"长任务 {index}：分析项目并运行完整测试"
        await provider.queue.put(input_segment(f"source-{index}", text))
        await next_kind(events, "input_turn.committed")
        await next_kind(events, "agent.input.accepted")

    assert bridge.enqueue_action.await_count == 10
    assert provider.request_response.await_count == 1
    first_speech.set()
    for expected_count in range(2, 11):
        await acknowledge_fake_output(coordinator, provider)
        await eventually(
            lambda: provider.request_response.await_count == expected_count
        )
    await eventually(lambda: provider.request_response.await_count == 10)
    await coordinator.close()


@pytest.mark.asyncio
async def test_conversation_is_persisted_without_task_submission():
    provider = Provider()
    provider.request_response.return_value = ProviderResponseResult(
        "completed",
        transcript="你好，很高兴见到你。",
    )
    bridge = Bridge()

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(ConverseVoiceAction())

    coordinator, _router, timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(input_segment("source-1", "你好"))

    committed = await next_kind(events, "input_turn.committed")
    updated = await next_kind(events, "chat.history.updated")
    await eventually(lambda: timeline.append_voice_exchange.await_count == 2)
    timeline.append_voice_exchange.assert_awaited_with(
        committed.data["turn_id"],
        "你好",
        "你好，很高兴见到你。",
        timeline_order=1,
        generation_status="completed",
    )
    assert updated.data["turn_id"] == committed.data["turn_id"]
    bridge.submit.assert_not_awaited()
    await coordinator.close()


@pytest.mark.asyncio
async def test_handoff_targets_speakable_task_reference():
    provider = Provider()
    bridge = Bridge()
    bridge.enqueue_action.return_value = admission(receipt())
    bridge.status.return_value = snapshot("task-1")

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision(
            "COMMIT", HandoffVoiceAction("请求一"), "quoted data"
        )

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(input_segment("source-1", "任务一再检查一下"))

    committed = await next_kind(events, "input_turn.committed")
    await next_kind(events, "agent.input.accepted")
    bridge.enqueue_action.assert_awaited_once_with(
        HandoffVoiceAction("请求一"),
        "任务一再检查一下",
        idempotency_key=committed.data["turn_id"],
        admission_mode="queue",
        conversation_context="quoted data",
    )
    bridge.observe_input.assert_called_once_with(
        committed.data["turn_id"],
        "任务一再检查一下",
        HandoffVoiceAction("请求一"),
    )
    await coordinator.close()


@pytest.mark.asyncio
async def test_history_question_enters_agent_instead_of_voice_query_path():
    provider = Provider()
    bridge = Bridge()
    bridge.routing_snapshots.return_value = (
        snapshot("task-1", task_ref="请求一"),
    )

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(HandoffVoiceAction("请求一"))

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    bridge.enqueue_action.return_value = admission(receipt())
    await coordinator.start()
    await provider.queue.put(input_segment("source-1", "任务一怎么样了"))
    await eventually(lambda: provider.request_response.await_count == 1)

    bridge.enqueue_action.assert_awaited_once()
    assert bridge.enqueue_action.await_args.args[1] == "任务一怎么样了"
    assert '"accepted": true' in provider.created_messages[-2][2]
    assert (
        '"original_request": "request task-1"'
        not in provider.created_messages[-2][2]
    )
    _timeline.append_voice_exchange.assert_not_awaited()
    await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["admission", "update"])
async def test_system_feedback_does_not_read_history_or_replay_questions(kind):
    provider, bridge = Provider(), Bridge()
    coordinator, _, timeline = build_coordinator(provider, bridge, [])
    timeline.read_context.return_value = "公开前文"
    try:
        await coordinator._present(PresentationIntent(kind, user_text="原问题"))
        assert provider.created_messages[-1][2] == "请按本轮反馈目的，用自然口语向用户反馈以上信息。"
        assert not any(
            text == "公开前文" for _, _, text in provider.created_messages
        )
        timeline.read_context.assert_not_awaited()
        timeline.append_voice_exchange.assert_not_awaited()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["response", "cancel", "message"])
async def test_converse_context_items_are_released_on_generation_failure(
    failure,
):
    provider, bridge = Provider(), Bridge()
    coordinator, _, timeline = build_coordinator(provider, bridge, [])
    timeline.read_context.return_value = "公开前文"
    exception = asyncio.CancelledError if failure == "cancel" else RuntimeError
    if failure == "message":
        create = provider.create_message

        async def fail_question(role, text):
            if text == "原问题":
                raise RuntimeError("message failed")
            return await create(role, text)

        provider.create_message = fail_question
    else:
        provider.request_response.side_effect = exception("generation failed")
    try:
        with pytest.raises(exception):
            await coordinator._present(
                PresentationIntent(
                    "converse",
                    user_text="原问题",
                )
            )
        expected = {item_id for item_id, _, _ in provider.created_messages}
        assert "message-2" in expected
        provider.delete_items.assert_awaited_once_with(expected)
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_interrupt_only_cancels_current_speech_output():
    provider = Provider()
    bridge = Bridge()

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(ConverseVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    await coordinator.interrupt()

    provider.interrupt_output.assert_awaited_once_with()
    bridge.submit.assert_not_awaited()
    await coordinator.close()


@pytest.mark.asyncio
async def test_provider_auto_output_is_filtered():
    provider = Provider()
    bridge = Bridge()

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(ConverseVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(input_segment("input", "hello"))
    await next_kind(events, "output.begin")
    await provider.queue.put(
        ProviderEvent(
            "response.started",
            "started",
            correlation_id="app-1",
            response_origin="application",
        )
    )
    await provider.queue.put(
        ProviderEvent(
            "output_transcript.final",
            "auto",
            {"text": "must not leak"},
            response_origin="provider_auto",
        )
    )
    await provider.queue.put(
        ProviderEvent(
            "output_transcript.final",
            "application",
            {"text": "visible"},
            correlation_id="app-1",
            response_origin="application",
        )
    )

    event = await next_kind(events, "output_transcript.final")
    assert event.data["text"] == "visible"
    await coordinator.close()


@pytest.mark.asyncio
async def test_missing_source_identity_is_visible_and_not_submitted():
    provider = Provider()
    bridge = Bridge()

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(
        ProviderEvent("input_transcript.final", "event", {"text": "run"})
    )

    error = await next_kind(events, "error")
    assert error.data["code"] == "missing_turn_identity"
    bridge.submit.assert_not_awaited()
    await coordinator.close()


@pytest.mark.asyncio
async def test_task_completion_updates_ui_and_queues_speech():
    provider = Provider()
    bridge = Bridge()

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(ConverseVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    bridge.routing_snapshots.return_value = (
        snapshot("task-1", "responded", version=3),
    )
    await bridge.queue.put(
        VoiceTaskEvent(snapshot("task-1", "responded", version=3))
    )
    updated = await next_kind(events, "agent.task.updated")
    await bridge.queue.put(VoiceRunEvent("run-1", "completed"))
    completed = await next_kind(events, "agent.run.completed")
    await eventually(lambda: provider.request_response.await_count == 1)

    assert updated.data["status"] == "responded"
    assert completed.data["status"] == "completed"
    assert (
        '"original_request": "request task-1"'
        in provider.created_messages[-2][2]
    )
    assert '"state": "本轮答复已返回"' in provider.created_messages[-2][2]
    assert "业务是否成功以对应正文为准" in provider.created_messages[-2][2]
    await coordinator.close()


@pytest.mark.asyncio
async def test_same_reply_phase_and_run_end_do_not_repeat_answer():
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, AsyncMock())
    events = coordinator.events()
    pump = asyncio.create_task(coordinator._pump_bridge_events())
    reply = ChatReply("m", "b", "run", ("input",), 1, "progress", "42")
    first = replace(
        snapshot("task-1", "processing", version=1), replies=(reply,)
    )
    cases = [
        (first, {"m:b"}),
        (
            replace(
                first, version=2, replies=(replace(reply, phase="final"),)
            ),
            set(),
        ),
        (
            replace(
                first,
                version=3,
                status="responded",
                replies=(replace(reply, phase="final", persisted=True),),
            ),
            set(),
        ),
        # A new reply identity is still new even if its answer text is equal.
        (
            replace(
                first,
                version=4,
                replies=(reply, replace(reply, block_id="next")),
            ),
            {"m:next"},
        ),
        # Failure remains meaningful, but must not replay the old answer.
        (replace(first, version=5, status="failed"), {"task:task-1"}),
    ]
    try:
        for current, expected in cases:
            await bridge.queue.put(VoiceTaskEvent(current))
            await next_kind(events, "agent.task.updated")
            assert coordinator._announce_changes == expected
            coordinator._announce_changes.clear()
        bridge.presentation_snapshots.return_value = (cases[-1][0],)
        notice = await coordinator._presentation_instruction(
            PresentationIntent("update", changed_ids=("task:task-1",))
        )
        assert '"text": "42"' not in notice
        assert "本轮处理失败" in notice
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await coordinator.close()


@pytest.mark.parametrize("terminal_first", [False, True])
async def test_reply_error_is_scoped_and_not_reannounced_on_save(
    terminal_first,
):
    from agentscope.message import Msg, TextBlock
    from qwenpaw.app.chats.replies import project_replies

    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, AsyncMock())
    events = coordinator.events()
    pump = asyncio.create_task(coordinator._pump_bridge_events())
    block = TextBlock(
        id="b",
        text="模型未生成可用答复，请稍后重试。",
    )
    msg = Msg(
        id="m",
        name="assistant",
        role="assistant",
        content=[block],
    )
    set_reply_block_metadata(
        msg,
        block,
        {
            "run_id": "run",
            "responds_to_input_ids": ["failed-input"],
            "reply_phase": "final",
            "reply_error": "empty_response",
        },
    )
    [reply] = project_replies([msg]).values()
    first = replace(
        snapshot("task-1", "failed" if terminal_first else "processing"),
        input_states=(
            ("failed-input", "failed" if terminal_first else "processing"),
        ),
        input_requests=(("failed-input", "打印口令"),),
        run_id="run",
    )
    try:
        for version, current in enumerate(
            (
                first,
                replace(first, replies=(reply,)),
                replace(
                    first,
                    status="failed",
                    input_states=(("failed-input", "failed"),),
                    replies=(replace(reply, persisted=True),),
                ),
            ),
            1,
        ):
            current = replace(current, version=version)
            await bridge.queue.put(VoiceTaskEvent(current))
            await next_kind(events, "agent.task.updated")
            if version == 2:
                assert coordinator._announce_changes == {"m:b"}
            if version == 3:
                assert not coordinator._announce_changes
            facts = snapshot_facts((current,))
            assert '"state": "执行失败"' not in facts
            if version >= 2:
                assert '"stage": "answer_generation"' in facts
                assert '"code": "empty_response"' in facts
                bridge.presentation_snapshots.return_value = (current,)
                instruction = await coordinator._presentation_instruction(
                    PresentationIntent("update", changed_ids=(reply.identity,))
                )
                assert "本轮是答复异常通知" in instruction
                assert "本轮是结果反馈" not in instruction
                assert "不要将答复生成失败解释为工具未执行" in instruction
            coordinator._announce_changes.clear()
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await coordinator.close()


async def test_error_change_notifies_without_text_change():
    from agentscope.message import Msg, TextBlock
    from qwenpaw.app.chats.replies import project_replies

    coordinator, _, _ = build_coordinator(Provider(), Bridge(), AsyncMock())
    events = coordinator.events()
    pump = asyncio.create_task(coordinator._pump_bridge_events())
    block = TextBlock(id="b", text="失败")
    msg = Msg(
        id="m",
        name="assistant",
        role="assistant",
        content=[block],
    )
    set_reply_block_metadata(
        msg,
        block,
        {
            "responds_to_input_ids": ["input"],
            "reply_phase": "final",
        },
    )
    try:
        for version, code in enumerate(
            ("empty_response", "future_error", "future_error"), 1
        ):
            update_reply_block_metadata(msg, block, {"reply_error": code})
            [reply] = project_replies([msg]).values()
            await coordinator._bridge_events.put(
                VoiceTaskEvent(
                    replace(
                        snapshot("task-1", "processing", version=version),
                        replies=(reply,),
                    )
                )
            )
            await next_kind(events, "agent.task.updated")
            assert coordinator._announce_changes == (
                {"m:b"} if version < 3 else set()
            )
            coordinator._announce_changes.clear()
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await coordinator.close()


@pytest.mark.asyncio
async def test_live_reply_handoff_does_not_reannounce_previous_blocks():
    from agentscope.message import Msg, TextBlock

    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, AsyncMock())
    events = coordinator.events()
    pump = asyncio.create_task(coordinator._pump_bridge_events())
    view = ChatReplyView()
    messages = []
    try:
        for index in range(1, 4):
            block = TextBlock(id=str(index), text=str(200 + index))
            msg = Msg(
                id="shared",
                name="assistant",
                role="assistant",
                content=[block],
            )
            set_reply_block_metadata(
                msg,
                block,
                {
                    "responds_to_input_ids": [str(index)],
                    "run_id": "run",
                    "timeline_order": index,
                    "reply_phase": "final",
                },
            )
            messages.append(msg)
            view.observe(msg, "run")
            current = replace(
                snapshot("task-1", "processing", version=index),
                replies=view.capture({}),
            )
            await bridge.queue.put(VoiceTaskEvent(current))
            await next_kind(events, "agent.task.updated")
            assert coordinator._announce_changes == {f"shared:{index}"}
            coordinator._announce_changes.clear()
        view.saved("run")
        disk = {
            "agent": {
                "state": {
                    "context": [m.model_dump(mode="json") for m in messages]
                }
            }
        }
        current = replace(
            current, version=4, status="responded", replies=view.capture(disk)
        )
        await bridge.queue.put(VoiceTaskEvent(current))
        await next_kind(events, "agent.task.updated")
        assert not coordinator._announce_changes
        assert [r.text for r in current.replies] == ["201", "202", "203"]
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await coordinator.close()


@pytest.mark.asyncio
async def test_committed_task_admission_outlives_voice_session_close():
    provider = Provider()
    bridge = Bridge()
    admission_started = asyncio.Event()
    release_admission = asyncio.Event()
    admission_cancelled = False
    completion = asyncio.get_running_loop().create_future()

    async def complete_admission():
        nonlocal admission_cancelled
        admission_started.set()
        try:
            await release_admission.wait()
        except asyncio.CancelledError:
            admission_cancelled = True
            raise
        completion.set_result(receipt())

    bridge.enqueue_action.return_value = VoiceAdmissionHandle(completion)
    bridge_admission = asyncio.create_task(complete_admission())

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(input_segment("source-1", "run slow task"))

    await next_kind(events, "input_turn.committed")
    await asyncio.wait_for(admission_started.wait(), timeout=1)
    await coordinator.close()

    assert not admission_cancelled
    release_admission.set()
    await asyncio.wait_for(bridge_admission, timeout=1)
    assert (await VoiceAdmissionHandle(completion).wait()).accepted


@pytest.mark.asyncio
async def test_task_state_presentation_does_not_depend_on_provider_snapshot():
    provider = Provider()
    provider.delete_items.side_effect = RuntimeError("snapshot unavailable")
    bridge = Bridge()
    bridge.routing_snapshots.return_value = (
        snapshot("task-0", task_ref="任务零"),
    )

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(ConverseVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()

    await bridge.queue.put(
        VoiceTaskEvent(
            snapshot("task-1", "responded", task_ref="请求一", version=1),
        ),
    )
    await next_kind(events, "agent.task.updated")
    await eventually(lambda: provider.request_response.await_count == 1)

    bridge.routing_snapshots.return_value = (
        snapshot("task-2", "responded", task_ref="请求二", version=1),
    )
    await bridge.queue.put(
        VoiceTaskEvent(
            snapshot("task-2", "responded", task_ref="请求二", version=1),
        ),
    )
    await next_kind(events, "agent.task.updated")
    await acknowledge_fake_output(coordinator, provider)
    await eventually(lambda: provider.request_response.await_count == 2)

    assert (
        '"original_request": "request task-2"'
        in provider.created_messages[-2][2]
    )
    assert '"state": "本轮答复已返回"' in provider.created_messages[-2][2]
    await coordinator.close()


@pytest.mark.asyncio
async def test_presentation_failure_revokes_output_but_preserves_later_input():
    provider = Provider()
    provider.request_response.side_effect = [
        RuntimeError("temporary presentation failure"),
        ProviderResponseResult(
            "completed",
            ("assistant-2",),
            "第二轮恢复正常。",
        ),
    ]
    bridge = Bridge()

    async def route(_text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(ConverseVoiceAction())

    coordinator, _router, timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()

    await provider.queue.put(input_segment("source-1", "第一轮"))
    await next_kind(events, "input_turn.committed")
    failed = await next_kind(events, "error")
    assert failed.data["code"] == "voice_presentation_failed"

    await provider.queue.put(input_segment("source-2", "第二轮"))
    await next_kind(events, "input_turn.committed")
    rejected = await next_kind(events, "presentation.rejected")
    assert rejected.data["code"] == "voice_output_unavailable"
    updated = await next_kind(events, "chat.history.updated")
    assert updated.data["turn_id"]
    assert provider.request_response.await_count == 1
    assert timeline.append_voice_exchange.await_count == 2
    assert timeline.append_voice_exchange.await_args.args[1:3] == ("第二轮", "")
    await coordinator.close()


@pytest.mark.asyncio
async def test_admission_backpressure_rejects_without_false_commit():
    provider = Provider()
    bridge = Bridge()
    bridge.enqueue_action.side_effect = OverflowError("admission queue full")

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    coordinator, _router, _timeline = build_coordinator(
        provider,
        bridge,
        route,
    )
    await coordinator.start()
    events = coordinator.events()
    await provider.queue.put(input_segment("source-1", "run task"))

    rejected = await next_kind(events, "input_turn.rejected")
    await eventually(lambda: provider.request_response.await_count == 1)

    assert rejected.data["message"] == "admission queue full"
    queued_kinds = [event.kind for event in tuple(coordinator._events._queue)]
    assert "input_turn.committed" not in queued_kinds
    assert "error" not in queued_kinds
    await coordinator.close()


def test_facts_keep_pending_inputs_separate_from_reply_source():
    from dataclasses import replace
    from qwenpaw.app.chats.replies import ChatReply

    task = replace(
        snapshot("task-1", "processing"),
        input_states=(
            ("a", "completed"),
            ("b", "queued"),
            ("c", "queued"),
        ),
        input_requests=(
            ("a", "第一步201"),
            ("b", "第二步202"),
            ("c", "第三步203"),
        ),
        replies=(
            ChatReply("m", "b", "run", ("a",), 1, "final", "任务一完成，结果201"),
        ),
    )
    facts = snapshot_facts([task])
    scope, source = facts.split("对应请求的Agent原文", 1)
    assert "第二步202" in scope and "第三步203" in scope
    assert '"other_requests_pending"' in scope
    assert '"text":' not in scope
    assert '"request_order": 1, "request": "第一步201"' in source
    assert (
        '"request_order": 2' not in source
        and '"request_order": 3' not in source
    )
    assert "任务一完成，结果201" in source
    assert "原文说完成只适用于其请求范围，不是整个任务完成" in facts


def test_waiting_facts_do_not_imply_user_action():
    from dataclasses import replace

    task = replace(
        snapshot("task-1", "waiting"),
        input_states=(("input", "waiting"),),
        background_work=({"execution": "running", "delivery": "pending"},),
    )
    facts = snapshot_facts([task])
    assert '"state": "请求正在等待后续处理"' in facts
    assert '"execution": "running", "delivery": "pending"' in facts
    assert "等待外部操作或用户处理" not in facts
    assert "只有正文明确请求用户处理时才能要求用户操作" in facts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,phase,purpose",
    [
        ("admission", "progress", "本轮是接收确认"),
        ("admission", "final", "本轮是接收确认"),
        ("update", "progress", "本轮是进度或状态反馈"),
        ("update", "incomplete", "本轮是进度或状态反馈"),
        ("update", "final", "本轮是结果反馈"),
    ],
)
async def test_feedback_purpose_respects_intent_and_reply_phase(
    kind,
    phase,
    purpose,
):
    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(provider, bridge, [])
    old = ChatReply("old", "b", "run", ("a",), 1, "final", "旧答案201")
    current = ChatReply("new", "b", "run", ("b",), 2, phase, "当前反馈")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1"),
            input_states=(("a", "completed"), ("b", "processing")),
            input_requests=(("a", "先做第一步"), ("b", "再做第二步")),
            replies=(old, current),
        ),
    )
    instruction = await coordinator._presentation_instruction(
        PresentationIntent(kind, changed_ids=(current.identity,))
    )
    assert instruction.startswith(purpose)
    assert "旧答案201" not in instruction
    assert "不附带全部任务计数" in instruction
    assert '"inputs"' not in instruction
    assert '"version"' not in instruction
    assert "第1条输入" not in instruction
    assert "先说具体事项的结果" not in instruction
    assert "只提供答案内容" not in instruction
    assert "只表达结果" not in instruction
    assert "原请求中的目标、参数和预期输出不是实际执行结果" in instruction


@pytest.mark.asyncio
async def test_automatic_facts_are_scoped_without_history_query_branch():
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    answer = ChatReply("m", "b", "run", ("a",), 1, "final", "结果201")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1"),
            input_states=(("a", "processing"), ("b", "queued")),
            input_requests=(("a", "计算第一项"), ("b", "计算第二项")),
            replies=(answer,),
        ),
        snapshot("task-2", task_ref="请求二"),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent("update", changed_ids=(answer.identity,))
    )
    assert '"text": "结果201"' in notice
    assert '"request_order": 1, "request": "计算第一项"' in notice
    assert '"other_requests_pending"' in notice
    assert "计算第二项" in notice and "正在排队" in notice
    assert "正在运行，尚未完成" not in notice
    assert "共2项" not in notice and "请求二" not in notice
    assert '"persisted"' not in notice and '"id": "m:b"' not in notice

    admission_notice = await coordinator._presentation_instruction(
        PresentationIntent("admission", task_ref="请求一")
    )
    assert '"accepted": true' in admission_notice
    assert "结果201" not in admission_notice
    assert "计算第一项" not in admission_notice
    assert "正在运行，尚未完成" not in admission_notice

    await coordinator.start()
    session = coordinator._provider.connect.call_args.args[0]
    assert "已接收不等于已经开始执行" in session.instructions
    assert "检索未命中不证明请求不存在" in session.instructions
    assert "已接收只表示后台开始处理" not in session.instructions
    await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["waiting", "failed", "cancelled"])
async def test_scoped_speech_retains_background_and_failure_boundaries(state):
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    reply = ChatReply("m", "b", "run", ("unknown",), 1, "final", "请提供目标文件。")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1", state),
            replies=(reply,),
            background_work=({"execution": "running", "delivery": "pending"},),
        ),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent("update", changed_ids=(reply.identity,))
    )
    assert "请提供目标文件。" in notice
    assert '"execution": "running", "delivery": "pending"' in notice
    assert '"request_order": null, "request": null' in notice
    assert "不是请求名称或用户主题" in notice
    assert "正文未取得的已接收请求" not in notice
    if state != "waiting":
        expected = "本轮处理失败" if state == "failed" else "已经取消"
        assert f'"state": "{expected}"' in notice


@pytest.mark.asyncio
async def test_scoped_speech_keeps_coalesced_media_and_independent_replies():
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    replies = (
        ChatReply("m", "a", "run", ("a",), 1, "final", "201"),
        ChatReply(
            "m",
            "b",
            "run",
            ("b",),
            2,
            "final",
            "",
            media_refs=(("image", "/media/result.png"),),
        ),
        ChatReply("m", "c", "run", ("c",), 3, "final", "旧203"),
    )
    bridge.presentation_snapshots.return_value = (
        replace(snapshot("task-1"), replies=replies),
    )
    instruction = await coordinator._presentation_instruction(
        PresentationIntent("update", changed_ids=("m:a", "m:b"))
    )
    assert '"text": "201"' in instruction
    assert '"/media/result.png"' in instruction
    assert "旧203" not in instruction
    assert '"request_order": null' in instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["processing", "failed", "cancelled"])
async def test_speech_separates_current_scope_from_unchanged_reply_source(
    state,
):
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    reply = ChatReply("m", "b", "run", ("a",), 1, "final", "任务一已完成，结果201。")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1", state),
            input_states=(("a", "completed"), ("b", "queued")),
            input_requests=(("a", "先计算第一项"), ("b", "再计算第二项")),
            replies=(reply,),
            background_work=({"execution": "running", "delivery": "pending"},),
        ),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent("update", changed_ids=(reply.identity,))
    )
    scope, source = notice.split("对应请求的Agent原文", 1)
    assert "先计算第一项" in scope and "再计算第二项" in scope
    assert '"other_requests_pending"' in scope
    assert '"execution": "running"' in scope
    assert '"text":' not in scope
    assert '"text": "任务一已完成，结果201。"' in source
    assert '"request_order": 1, "request": "先计算第一项"' in source
    assert reply.text == "任务一已完成，结果201。"
    assert "以下是唯一权威任务状态" not in notice
    if state != "processing":
        assert ("本轮处理失败" if state == "failed" else "已经取消") in scope


@pytest.mark.asyncio
async def test_speech_keeps_reply_attributed_after_scope_separation():
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    reply = ChatReply("m", "b", "run", ("a",), 1, "final", "结果201")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1"),
            replies=(reply,),
            input_requests=(("a", "计算第一项"),),
        ),
        replace(
            snapshot("task-2", task_ref="请求二"),
            replies=(replace(reply, message_id="n", text="结果202"),),
            input_requests=(("a", "计算另一项"),),
        ),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent("update")
    )
    first, second = notice.split('"original_request": "request task-2"', 1)
    assert '"text": "结果201"' in first and '"text": "结果202"' not in first
    assert '"request": "计算另一项"' in second
    assert '"text": "结果202"' in second


@pytest.mark.asyncio
async def test_automatic_scope_distinguishes_repeated_request_text():
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    reply = ChatReply("m", "b", "run", ("b",), 1, "final", "实际输出201")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1"),
            input_states=(("a", "completed"), ("b", "completed")),
            input_requests=(("a", "再算一次"), ("b", "再算一次")),
            replies=(reply,),
        ),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent("update")
    )
    assert '"request_order": 2' in notice
    assert '"request_order": 1' not in notice
    assert '"text": "实际输出201"' in notice


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["admission", "update"])
async def test_concise_system_feedback_preserves_answers_not_length_limits(
    kind,
):
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    text = "答案细节" * 600 + "：report-a.pdf，12 MB；上传失败。"
    reply = ChatReply("m", "b", "run", ("a",), 1, "final", text)
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1"),
            replies=(reply,),
            input_states=(("a", "completed"),),
            input_requests=(("a", "告诉我名称和大小"),),
        ),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent(kind)
    )
    assert "不减少用户所需信息" in notice
    if kind != "admission":
        assert text in notice
    if kind == "update":
        assert "没有待处理事项时直接结束" in notice
        assert "哪部分尚待处理" not in notice


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["failed", "cancelled"])
async def test_terminal_notice_excludes_past_progress_but_keeps_results(state):
    bridge = Bridge()
    coordinator, _, _ = build_coordinator(Provider(), bridge, [])
    result = ChatReply("m", "a", "run", ("a",), 1, "final", "已取得结果201")
    progress = ChatReply("m", "b", "run", ("b",), 2, "progress", "第二步已开始执行")
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1", state),
            replies=(result, progress),
            background_work=({"execution": "running", "delivery": "pending"},),
        ),
    )
    notice = await coordinator._presentation_instruction(
        PresentationIntent("update")
    )
    assert "第二步已开始执行" not in notice
    assert "已取得结果201" in notice
    assert '"execution": "running"' in notice
    assert bridge.presentation_snapshots.return_value[0].replies == (
        result,
        progress,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_automatic_result_feedback_is_not_a_status_only_question(
    completed,
):
    from dataclasses import replace
    from qwenpaw.app.chats.replies import ChatReply

    provider, bridge = Provider(), Bridge()
    coordinator, _, _ = build_coordinator(provider, bridge, [])
    bridge.presentation_snapshots.return_value = (
        replace(
            snapshot("task-1", "responded"),
            background_work=(
                {
                    "execution": "completed" if completed else "running",
                    "delivery": "delivered" if completed else "pending",
                },
            ),
            replies=(ChatReply("m", "b", "run", ("input",), 1, "final", "42"),)
            if completed
            else (),
        ),
    )
    instruction = await coordinator._presentation_instruction(
        PresentationIntent("update")
    )
    assert ("本轮是结果反馈" in instruction) is completed
    if completed:
        assert "42" in instruction
        assert "回答状态问题" not in instruction
    # Exercise the actual request, not just its system instruction: a later
    # user-role status question used to override the intended result feedback.
    for kind in ("admission", "update"):
        await coordinator._present(PresentationIntent(kind))
        assert provider.created_messages[-1][2] == ("请按本轮反馈目的，用自然口语向用户反馈以上信息。")
