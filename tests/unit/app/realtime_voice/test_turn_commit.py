import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.realtime_voice.contracts import (
    ClarifyVoiceAction,
    HandoffVoiceAction,
    VoiceTaskSnapshot,
)
from qwenpaw.app.realtime_voice.turn_commit import (
    CommittedSpokenTurn,
    PendingSpokenTurn,
    ProviderModelVoiceTurnRouter,
    SpokenTurnCommitter,
    VoiceRouteDecision,
    VoiceRoutingError,
    _parse_route,
)
from qwenpaw.config.config import ModelSlotConfig


async def next_event(events, event_type):
    while True:
        event = await asyncio.wait_for(anext(events), timeout=1)
        if isinstance(event, event_type):
            return event


def router(*decisions):
    return SimpleNamespace(route=AsyncMock(side_effect=decisions))


@pytest.mark.asyncio
async def test_slow_delegate_waits_for_finalized_continuation():
    release = asyncio.Event()
    entered = asyncio.Event()

    async def route(text, **kwargs):
        sources = kwargs["source_segments"]
        if len(sources) == 1:
            entered.set()
            await release.wait()
        return VoiceRouteDecision.commit(HandoffVoiceAction(), len(sources))

    committer = SpokenTurnCommitter(
        SimpleNamespace(route=route), continuation_grace_ms=0
    )
    accepted = []
    committer.on_commit = accepted.append
    try:
        await committer.speech_started("first")
        await committer.add_segment("first", "这个测试叫苹果")
        await entered.wait()
        await committer.speech_started("second")
        await committer.speech_stopped("second")
        release.set()
        await asyncio.sleep(0.02)
        assert accepted == []
        await committer.add_segment("second", "只调用一次工具输出301")
        event = await next_event(committer.events(), CommittedSpokenTurn)
        assert event.source_ids == ("first", "second")
        assert event.text == "这个测试叫苹果 只调用一次工具输出301"
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_final_transcripts_follow_speech_order_not_arrival_order():
    voice_router = router(VoiceRouteDecision.commit(HandoffVoiceAction(), 2))
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    try:
        await committer.speech_started("first")
        await committer.speech_stopped("first")
        await committer.speech_started("second")
        await committer.add_segment("second", "output301")
        await asyncio.sleep(0)
        voice_router.route.assert_not_awaited()
        await committer.add_segment("first", "only once")
        event = await next_event(committer.events(), CommittedSpokenTurn)
        assert event.text == "only once output301"
        assert voice_router.route.await_args.kwargs["source_segments"] == (
            "only once",
            "output301",
        )
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_confirmed_prefix_can_commit_while_new_tail_is_spoken():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def route(text, **kwargs):
        if len(kwargs["source_segments"]) == 2:
            entered.set()
            await release.wait()
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    committer = SpokenTurnCommitter(
        SimpleNamespace(route=route), continuation_grace_ms=0
    )
    try:
        await committer.add_segment("first", "run301")
        await committer.add_segment("second", "另外run602")
        await entered.wait()
        await committer.speech_started("third")
        release.set()
        first = await next_event(committer.events(), CommittedSpokenTurn)
        assert first.source_ids == ("first",)
        await committer.add_segment("third", "另外run903")
        second = await next_event(committer.events(), CommittedSpokenTurn)
        third = await next_event(committer.events(), CommittedSpokenTurn)
        assert (second.text, third.text) == ("另外run602", "另外run903")
    finally:
        await committer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_empty_and_failed_continuations_settle_without_automatic_loss(
    failed,
):
    voice_router = SimpleNamespace(
        route=AsyncMock(
            return_value=VoiceRouteDecision.commit(HandoffVoiceAction())
        )
    )
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=20)
    accepted = []
    committer.on_commit = accepted.append
    try:
        await committer.add_segment("first", "only once run301")
        await committer.speech_started("second")
        assert not await committer.commit_pending()
        if failed:
            await committer.input_failed("second")
        else:
            await committer.add_segment("second", "")
        await asyncio.sleep(0.05)
        assert bool(accepted) is not failed
        assert not committer._unsettled
        if failed:
            assert not await committer.commit_pending("native")
            assert await committer.commit_pending("manual")
            event = await next_event(committer.events(), CommittedSpokenTurn)
            assert event.text == "only once run301"
            assert event.origin == "manual"
        await committer.add_segment(
            "second", "late duplicate must not execute"
        )
        await asyncio.sleep(0)
        assert len(accepted) == 1
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_execution_grace_is_cancelled_on_new_speech_and_on_close():
    voice_router = SimpleNamespace(
        route=AsyncMock(
            return_value=VoiceRouteDecision.commit(HandoffVoiceAction())
        )
    )
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=30)
    accepted = []
    committer.on_commit = accepted.append
    await committer.add_segment("first", "run301")
    await asyncio.sleep(0.01)
    await committer.speech_started("second")
    await asyncio.sleep(0.05)
    assert not accepted
    await committer.add_segment("second", "")
    await committer.close()
    await asyncio.sleep(0.05)
    assert not accepted


@pytest.mark.parametrize("count", [0, -1, 3, True, "1", None])
def test_route_rejects_invalid_consumed_prefix(count):
    with pytest.raises(ValueError, match="invalid source range"):
        _parse_route(
            json.dumps({"type": "HANDOFF", "consumed_segments": count}),
            task_refs=set(),
            force_commit=False,
            source_count=2,
        )


def test_old_route_envelope_is_not_silently_accepted():
    with pytest.raises(ValueError):
        _parse_route(
            '{"decision":"COMMIT","action":{"type":"STATUS"}}',
            task_refs=set(),
            force_commit=False,
        )


@pytest.mark.asyncio
async def test_failed_input_registration_keeps_words_for_manual_retry():
    from unittest.mock import Mock

    decision = VoiceRouteDecision.commit(HandoffVoiceAction())
    committer = SpokenTurnCommitter(
        router(decision, decision), continuation_grace_ms=0
    )
    committer.on_commit = Mock(side_effect=RuntimeError("closed"))
    events = committer.events()
    try:
        await committer.add_segment(
            "source", "original words with constraints"
        )
        pending = await next_event(events, PendingSpokenTurn)
        while pending.state != "needs_confirmation":
            pending = await next_event(events, PendingSpokenTurn)
        assert pending.text == "original words with constraints"
        assert pending.error == "voice_input_unavailable"
        committer.on_commit = Mock()
        await committer.commit_pending()
        committed = await next_event(events, CommittedSpokenTurn)
        assert committed.text == pending.text
        committer.on_commit.assert_called_once_with(committed)
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_wait_then_commit_merges_all_source_segments():
    voice_router = router(
        VoiceRouteDecision.wait(),
        VoiceRouteDecision.commit(HandoffVoiceAction(), 2),
    )
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    events = committer.events()

    await committer.add_segment("item-1", "请帮我计算一百二十三加上")
    pending = await next_event(events, PendingSpokenTurn)
    while pending.state != "waiting":
        pending = await next_event(events, PendingSpokenTurn)

    await committer.add_segment("item-2", "四百五十六，只回答结果。")
    committed = await next_event(events, CommittedSpokenTurn)

    assert committed.source_ids == ("item-1", "item-2")
    assert committed.text.endswith("四百五十六，只回答结果。")
    assert committed.action == HandoffVoiceAction()
    await committer.close()


@pytest.mark.asyncio
async def test_commit_keeps_later_speech_as_a_separate_candidate():
    release = asyncio.Event()

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        if text == "first":
            await release.wait()
            return VoiceRouteDecision.commit(HandoffVoiceAction())
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    voice_router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    events = committer.events()

    await committer.add_segment("item-1", "first")
    await asyncio.sleep(0)
    await committer.add_segment("item-2", "second")
    release.set()

    first = await next_event(events, CommittedSpokenTurn)
    second = await next_event(events, CommittedSpokenTurn)
    assert (first.text, second.text) == ("first", "second")
    assert voice_router.route.await_count == 3
    await committer.close()


@pytest.mark.asyncio
async def test_commit_routes_each_backlogged_segment_separately():
    release = asyncio.Event()

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        if text == "task-0":
            await release.wait()
        return VoiceRouteDecision.commit(HandoffVoiceAction())

    voice_router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    events = committer.events()

    for index in range(10):
        await committer.add_segment(f"item-{index}", f"task-{index}")
        if index == 0:
            await asyncio.sleep(0)
    release.set()

    committed = [
        await next_event(events, CommittedSpokenTurn) for _ in range(10)
    ]
    assert [turn.text for turn in committed] == [
        f"task-{index}" for index in range(10)
    ]
    assert voice_router.route.await_count == 11
    await committer.close()


@pytest.mark.asyncio
async def test_wait_reclassifies_candidate_with_following_segment():
    release = asyncio.Event()

    async def route(text, *, force_commit=False, source_segments=()):
        del force_commit
        if text == "first":
            await release.wait()
            return VoiceRouteDecision.wait()
        return VoiceRouteDecision.commit(
            HandoffVoiceAction(), len(source_segments)
        )

    voice_router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    events = committer.events()
    await committer.add_segment("item-1", "first")
    await asyncio.sleep(0)
    await committer.add_segment("item-2", "second")
    release.set()

    committed = await next_event(events, CommittedSpokenTurn)
    assert committed.text == "first second"
    assert voice_router.route.await_count == 2
    await committer.close()


@pytest.mark.asyncio
async def test_router_failure_preserves_text_for_manual_commit():
    voice_router = router(
        RuntimeError("model unavailable"),
        VoiceRouteDecision.commit(ClarifyVoiceAction("目标文件")),
    )
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    events = committer.events()

    await committer.add_segment("item-1", "处理它")
    pending = await next_event(events, PendingSpokenTurn)
    while pending.state != "needs_confirmation":
        pending = await next_event(events, PendingSpokenTurn)
    assert pending.text == "处理它"
    assert pending.error == "voice_router_unavailable"

    assert await committer.commit_pending("manual") is True
    committed = await next_event(events, CommittedSpokenTurn)
    assert committed.origin == "manual"
    assert committed.action == ClarifyVoiceAction("目标文件")
    assert voice_router.route.await_args.kwargs == {
        "force_commit": True,
        "source_segments": ("处理它",),
    }
    await committer.close()


@pytest.mark.asyncio
async def test_manual_commit_never_leaves_an_illegal_wait_pending():
    voice_router = router(
        VoiceRouteDecision.wait(),
        VoiceRouteDecision.wait(),
    )
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    events = committer.events()

    await committer.add_segment("item-1", "请帮我计算一百二十三加上")
    pending = await next_event(events, PendingSpokenTurn)
    while pending.state != "waiting":
        pending = await next_event(events, PendingSpokenTurn)
    assert await committer.commit_pending("manual") is True

    committed = await next_event(events, CommittedSpokenTurn)
    assert committed.origin == "manual"
    assert committed.action == ClarifyVoiceAction("请补充或重新说明需要提交的完整请求。")
    await committer.close()


@pytest.mark.asyncio
async def test_duplicate_source_id_is_ignored():
    voice_router = router(VoiceRouteDecision.wait())
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)

    await committer.add_segment("item-1", "same")
    await asyncio.sleep(0)
    await committer.add_segment("item-1", "same")

    assert voice_router.route.await_count == 1
    await committer.close()


@pytest.mark.parametrize(
    "reference, expected", [("请求一", "请求一"), ("请求二", ""), ("", "")]
)
def test_parse_route_optional_reference_is_not_an_admission_requirement(
    reference, expected
):
    decision = _parse_route(
        json.dumps(
            {"type": "HANDOFF", "consumed_segments": 1, "task_ref": reference}
        ),
        task_refs={"请求一"},
        force_commit=False,
    )
    assert decision.action == HandoffVoiceAction(expected)
    assert decision.consumed_segments == 1


@pytest.mark.parametrize("reference", [None, True, 7, [], {}])
def test_parse_route_rejects_nontext_reference(reference):
    with pytest.raises(ValueError, match="task_ref must be text"):
        _parse_route(
            json.dumps(
                {
                    "type": "HANDOFF",
                    "consumed_segments": 1,
                    "task_ref": reference,
                }
            ),
            task_refs=set(),
            force_commit=False,
        )


@pytest.mark.parametrize(
    "legacy",
    [
        {"type": "DELEGATE", "request": "run"},
        {"type": "FOLLOW_UP", "task_ref": "请求一", "instruction": "continue"},
        {"type": "STATUS", "task_ref": "请求一"},
        {"type": "HANDOFF", "request": "rewritten"},
        {"type": "HANDOFF", "instruction": "rewritten"},
    ],
)
def test_parse_route_rejects_legacy_or_rewritten_request_actions(legacy):
    with pytest.raises(ValueError, match="action fields are invalid"):
        _parse_route(
            json.dumps({**legacy, "consumed_segments": 1}),
            task_refs={"请求一"},
            force_commit=False,
        )


def test_parse_route_handoff_carries_no_model_rewritten_request():
    decision = _parse_route(
        '{"type":"HANDOFF","consumed_segments":1}',
        task_refs=set(),
        force_commit=False,
    )

    assert decision.action == HandoffVoiceAction()
    assert decision.action.public_dict() == {"type": "HANDOFF"}


def test_manual_route_maps_illegal_wait_to_safe_clarification():
    decision = _parse_route(
        '{"type":"WAIT"}',
        task_refs=set(),
        force_commit=True,
    )

    assert decision == VoiceRouteDecision.commit(
        ClarifyVoiceAction("请补充或重新说明需要提交的完整请求。")
    )


@pytest.mark.asyncio
async def test_semantic_clarification_waits_for_a_following_segment():
    voice_router = router(
        VoiceRouteDecision.commit(ClarifyVoiceAction("缺少计算内容")),
        VoiceRouteDecision.commit(HandoffVoiceAction(), 2),
    )
    committer = SpokenTurnCommitter(
        voice_router,
        continuation_grace_ms=100,
    )
    events = committer.events()

    await committer.add_segment("item-1", "请帮我计算一百二十三加上")
    pending = await next_event(events, PendingSpokenTurn)
    while pending.state != "waiting":
        pending = await next_event(events, PendingSpokenTurn)
    await committer.speech_started("item-2")
    await asyncio.sleep(0.15)
    await committer.add_segment("item-2", "四百五十六")

    committed = await next_event(events, CommittedSpokenTurn)
    assert committed.text == "请帮我计算一百二十三加上 四百五十六"
    assert committed.action == HandoffVoiceAction()
    await committer.close()


@pytest.mark.asyncio
async def test_semantic_clarification_commits_after_configured_grace():
    voice_router = router(
        VoiceRouteDecision.commit(ClarifyVoiceAction("目标文件")),
    )
    committer = SpokenTurnCommitter(
        voice_router,
        continuation_grace_ms=10,
    )
    events = committer.events()

    await committer.add_segment("item-1", "处理它")
    committed = await next_event(events, CommittedSpokenTurn)

    assert committed.action == ClarifyVoiceAction("目标文件")
    assert committed.origin == "semantic"
    await committer.close()


def provider_router(model):
    result = ProviderModelVoiceTurnRouter(
        "default",
        ModelSlotConfig(provider_id="test", model="router"),
        AsyncMock(return_value=()),
    )
    result._model = model
    return result


@pytest.mark.parametrize("force_commit", [False, True])
async def test_router_freezes_public_context_and_preserves_request(
    force_commit,
):
    context = AsyncMock(return_value='{"messages":[{"text":"BLUE_CAT"}]}')
    original = context.return_value
    action = {"type": "HANDOFF"}

    async def respond(messages, **kwargs):
        context.return_value = '{"messages":[{"text":"RED_CAT"}]}'
        return {"text": json.dumps({**action, "consumed_segments": 1})}

    model = AsyncMock(side_effect=respond)
    voice_router = provider_router(model)
    voice_router._conversation_context = context
    decision = await voice_router.route(
        "Print that phrase once", force_commit=force_commit
    )
    context.assert_awaited_once_with()
    assert decision.conversation_context == original
    prompt = model.await_args.args[0][1].content[0].text
    assert original in prompt and "RED_CAT" not in prompt
    assert json.loads(prompt.split("TRANSCRIPT:\n", 1)[1]) == {
        "explicit_submit": force_commit,
        "segments": ["Print that phrase once"],
    }
    assert decision.action == HandoffVoiceAction()
    assert "conversation_context" not in decision.action.public_dict()


@pytest.mark.parametrize(
    "action", [HandoffVoiceAction(), ClarifyVoiceAction("which file")]
)
async def test_committer_carries_candidate_context_through_commit_and_grace(
    action,
):
    from types import SimpleNamespace

    committer = SpokenTurnCommitter(
        SimpleNamespace(
            route=AsyncMock(
                return_value=VoiceRouteDecision(
                    "COMMIT", action, "frozen context"
                ),
            )
        ),
        continuation_grace_ms=1,
    )
    try:
        events = committer.events()
        await committer.add_segment("source-1", "original utterance")
        event = await next_event(events, CommittedSpokenTurn)
        assert event.conversation_context == "frozen context"
        assert event.text == "original utterance"
        assert event.source_ids == ("source-1",)
    finally:
        await committer.close()


@pytest.mark.parametrize("force_commit", [False, True])
async def test_router_receives_all_admitted_steps_and_input_states(
    force_commit,
):
    model = AsyncMock(return_value={"text": '{"type":"WAIT"}'})
    voice_router = provider_router(model)
    voice_router._task_context.return_value = (
        VoiceTaskSnapshot(
            task_id="task",
            task_ref="请求一",
            status="processing",
            request="first step",
            version=1,
            input_requests=(
                ("a", "first step"),
                ("b", "second step"),
                ("c", "third step"),
            ),
            input_states=(
                ("a", "completed"),
                ("b", "completed"),
                ("c", "processing"),
            ),
        ),
    )
    await voice_router.route("任务一三步的结果是什么", force_commit=force_commit)
    messages = model.await_args.args[0]
    content = messages[1].content[0].text
    context = json.loads(
        content.split("TASKS:\n")[1].split("\nTRANSCRIPT:")[0]
    )
    assert context["omitted_tasks"] == 0
    task = context["tasks"][0]
    assert task["input_count"] == 3
    assert task["omitted_inputs"] == 0
    assert [
        (i["input_id"], i["request"], i["state"]) for i in task["inputs"]
    ] == [
        ("a", "first step", "completed"),
        ("b", "second step", "completed"),
        ("c", "third step", "processing"),
    ]
    rules = messages[0].content[0].text
    assert "HANDOFF" in rules and "STATUS" not in rules
    assert "not a prerequisite" in rules
    assert "Do not guess references" in rules
    assert "original words" in rules
    assert "Determine completeness BEFORE" in rules
    assert "consume the lead-in AND the goal" in rules


async def test_router_context_marks_omitted_tasks_inputs_and_request_text():
    model = AsyncMock(return_value={"text": '{"type":"WAIT"}'})
    voice_router = provider_router(model)
    voice_router._task_context.return_value = tuple(
        VoiceTaskSnapshot(
            task_id=str(n),
            task_ref=f"任务{n}",
            status="processing",
            version=1,
            request="first",
            input_requests=tuple((str(i), "x" * 600) for i in range(25)),
        )
        for n in range(25)
    )
    await voice_router.route("当前进度")
    content = model.await_args.args[0][1].content[0].text
    context = json.loads(
        content.split("TASKS:\n")[1].split("\nTRANSCRIPT:")[0]
    )
    assert context["omitted_tasks"] == 5
    assert len(context["tasks"]) == 20
    task = context["tasks"][-1]
    assert task["input_count"] == 25
    assert task["omitted_inputs"] == 5
    assert len(task["inputs"]) == 20
    assert task["inputs"][0]["input_index"] == 1
    assert task["inputs"][-1]["input_index"] == 25
    assert all(i["request_truncated"] for i in task["inputs"])
    assert all(i["state"] == "unknown" for i in task["inputs"])


@pytest.mark.parametrize(
    "raw,kind,shape",
    [
        ("", "empty_output", "empty"),
        (" \n ", "empty_output", "whitespace"),
        ("not JSON", "invalid_json", "other"),
        ('```json\n{"decision":"WAIT"}\n```', "invalid_json", "code_fence"),
        ('{"decision":', "invalid_json", "object_prefix"),
        ('{"decision":"UNKNOWN"}', "invalid_route", "object_prefix"),
        ("[]", "invalid_route", "array_prefix"),
        (
            '{"type":"FOLLOW_UP","consumed_segments":1,'
            '"task_ref":"unknown","instruction":"continue"}',
            "invalid_route",
            "object_prefix",
        ),
    ],
)
async def test_router_diagnoses_output_without_logging_content(
    raw, kind, shape
):
    model = AsyncMock(
        return_value={
            "content": [
                {"type": "thinking", "thinking": "secret reasoning"},
                {"type": "text", "text": raw},
            ],
            "is_last": True,
            "finished_reason": "completed",
            "usage": {"input_tokens": 80, "output_tokens": 256},
        }
    )
    voice_router = provider_router(model)
    with pytest.raises(VoiceRoutingError) as caught:
        await voice_router.route("private request")
    details = caught.value.diagnostics
    assert details["failure"] == kind
    assert details["output_shape"] == shape
    assert details["output_chars"] == len(raw)
    assert details["provider_id"] == "test"
    assert details["model"] == "router"
    assert details["saw_final_response"] is True
    assert details["call_completed"] is True
    assert details["first_response_ms"] >= 0
    assert details["model_finished_reason"] == "completed"
    assert details["upstream_finish_reason"] is None
    assert details["block_types"] == ["text", "thinking"]
    assert details["output_tokens"] == 256
    assert details["elapsed_ms"] >= 0
    assert "private request" not in json.dumps(details)
    assert "secret reasoning" not in json.dumps(details)
    if kind != "invalid_route":
        assert isinstance(details["json_error_position"], int)
        assert details["json_error_message"]
    else:
        assert details["validation_error"]
    assert (
        voice_router._model is model
    )  # Parse failures retain existing policy.


@pytest.mark.parametrize(
    "failure,kind,status",
    [
        (TimeoutError(), "timeout", None),
        (ConnectionError("secret-body"), "model_error", None),
        (
            RuntimeError("Streaming response failed: [502] secret-body"),
            "upstream_error",
            502,
        ),
    ],
)
async def test_router_diagnoses_call_failures(failure, kind, status):
    voice_router = provider_router(AsyncMock(side_effect=failure))
    with pytest.raises(VoiceRoutingError) as caught:
        await voice_router.route("private request")
    details = caught.value.diagnostics
    assert details["failure"] == kind
    assert details["http_status"] == status
    assert details["response_count"] == 0
    assert details["first_response_ms"] is None
    assert details["call_completed"] is False
    assert details["phase"] == "call"
    assert "secret-body" not in json.dumps(details)
    assert voice_router._model is None


async def test_router_keeps_partial_diagnostics_on_real_deadline(monkeypatch):
    import qwenpaw.app.realtime_voice.turn_commit as module

    monkeypatch.setattr(module, "_ROUTER_TIMEOUT_SECONDS", 0.01)
    closed = asyncio.Event()

    async def model(messages, **kwargs):
        async def stream():
            try:
                yield {"text": '{"decision":', "is_last": False}
                await asyncio.Event().wait()
            finally:
                closed.set()

        return stream()

    voice_router = provider_router(model)
    with pytest.raises(VoiceRoutingError) as caught:
        await voice_router.route("private request")
    details = caught.value.diagnostics
    assert details["failure"] == "timeout"
    assert details["response_count"] == 1
    assert details["output_chars"] == 12
    assert details["saw_final_response"] is False
    assert details["upstream_finish_reason"] is None
    assert closed.is_set()


async def test_diagnostics_do_not_change_success_or_model_arguments():
    model = AsyncMock(return_value={"text": '{"type":"WAIT"}'})
    voice_router = provider_router(model)
    assert await voice_router.route("unfinished") == VoiceRouteDecision.wait()
    assert model.call_args.kwargs == {
        "tools": None,
        "max_tokens": 256,
        "disable_thinking": True,
    }


async def test_cancelled_route_is_not_reported_as_failure(caplog):
    voice_router = provider_router(
        AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await voice_router.route("private request")
    assert voice_router._model is None
    assert not caplog.records


@pytest.mark.parametrize("upstream_error", [False, True])
async def test_failure_log_is_private_and_manual_recovery_is_unchanged(
    caplog,
    upstream_error,
):
    secret = "sk-private-example user-private-text"
    first = (
        RuntimeError(f"Streaming response failed: [502] {secret}")
        if upstream_error
        else {"text": secret}
    )
    model = AsyncMock(
        side_effect=[
            first,
            {"text": '{"type":"CONVERSE","consumed_segments":1}'},
        ]
    )
    voice_router = provider_router(model)
    committer = SpokenTurnCommitter(voice_router, continuation_grace_ms=0)
    try:
        events = committer.events()
        await committer.add_segment("source-1", secret)
        pending = await next_event(events, PendingSpokenTurn)
        while pending.state != "needs_confirmation":
            pending = await next_event(events, PendingSpokenTurn)
        assert pending.text == secret
        assert pending.error == "voice_router_unavailable"
        records = [
            r for r in caplog.records if "Voice routing failed" in r.message
        ]
        assert len(records) == 1
        details = json.loads(records[0].message.split(": ", 1)[1])
        assert details["failure"] == (
            "upstream_error" if upstream_error else "invalid_json"
        )
        assert details["origin"] == "semantic"
        assert details["source_count"] == 1
        assert len(details["source_fingerprint"]) == 16
        assert "source-1" not in records[0].message
        assert secret not in caplog.text
        assert records[0].exc_info is None
        voice_router._model = model
        assert await committer.commit_pending("manual")
        committed = await next_event(events, CommittedSpokenTurn)
        assert committed.text == secret
        assert committed.source_ids == ("source-1",)
        assert committed.action.type == "CONVERSE"
    finally:
        await committer.close()


async def test_router_setup_error_is_distinct_from_provider_failure(
    monkeypatch,
):
    voice_router = provider_router(None)

    def fail():
        raise RuntimeError("secret configuration")

    monkeypatch.setattr(voice_router, "_model_instance", fail)
    with pytest.raises(VoiceRoutingError) as caught:
        await voice_router.route("request")
    assert caught.value.diagnostics["failure"] == "setup_error"
    assert "secret configuration" not in json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize("response", [None, {"content": []}])
async def test_missing_content_is_empty_not_transport_failure(response):
    voice_router = provider_router(AsyncMock(return_value=response))
    with pytest.raises(VoiceRoutingError) as caught:
        await voice_router.route("request")
    assert caught.value.diagnostics["failure"] == "empty_output"
    assert caught.value.diagnostics["call_completed"] is True


async def test_empty_stream_is_recorded_without_inventing_completion():
    async def model(messages, **kwargs):
        async def stream():
            for chunk in []:
                yield chunk

        return stream()

    with pytest.raises(VoiceRoutingError) as caught:
        await provider_router(model).route("request")
    details = caught.value.diagnostics
    assert details["failure"] == "empty_output"
    assert details["response_count"] == 0
    assert details["call_completed"] is True
    assert details["saw_final_response"] is False


async def test_observer_tolerates_unknown_blocks_and_preserves_reason():
    model = AsyncMock(
        return_value={
            "content": [
                {"type": {"unexpected": "secret"}},
                {"text": "{broken"},
            ],
            "finish_reason": "length",
            "finished_reason": "completed",
            "usage": {"input_tokens": "private", "output_tokens": None},
        }
    )
    with pytest.raises(VoiceRoutingError) as caught:
        await provider_router(model).route("request")
    details = caught.value.diagnostics
    assert details["failure"] == "invalid_json"
    assert details["block_types"] == ["other"]
    assert details["upstream_finish_reason"] == "length"
    assert "private" not in json.dumps(details)
    assert "secret" not in json.dumps(details)


async def test_router_observes_real_agentscope_response_without_text():
    from agentscope.model import ChatResponse
    from agentscope.model._model_usage import ChatUsage

    response = ChatResponse(
        content=[{"type": "thinking", "thinking": "private reasoning"}],
        is_last=True,
        usage=ChatUsage(input_tokens=80, output_tokens=256, time=0.1),
    )
    with pytest.raises(VoiceRoutingError) as caught:
        await provider_router(AsyncMock(return_value=response)).route(
            "request"
        )
    details = caught.value.diagnostics
    assert details["failure"] == "empty_output"
    assert details["block_types"] == ["thinking"]
    assert details["output_tokens"] == 256
    assert details["model_finished_reason"] == "completed"
    assert details["upstream_finish_reason"] is None
    assert "private reasoning" not in json.dumps(details)


@pytest.mark.parametrize("force_commit", [False, True])
def test_unfinished_clarification_requires_explicit_submit(force_commit):
    decision = _parse_route(
        '{"type":"CLARIFY","consumed_segments":1,'
        '"missing_information":"请继续说明具体要求"}',
        task_refs=set(),
        force_commit=force_commit,
    )
    if force_commit:
        assert decision.action == ClarifyVoiceAction("请继续说明具体要求")
    else:
        assert decision == VoiceRouteDecision.wait()


async def test_automatic_clarification_preserves_leadin_for_goal():
    voice_router = provider_router(
        AsyncMock(
            side_effect=[
                {
                    "text": '{"type":"CLARIFY","consumed_segments":1,'
                    '"missing_information":"具体要求"}',
                },
                {"text": '{"type":"HANDOFF","consumed_segments":2}'},
            ],
        ),
    )
    introduction = "I am submitting the next request."
    goal = "Calculate 18 plus 7."
    assert (
        await voice_router.route(
            introduction,
            source_segments=(introduction,),
        )
        == VoiceRouteDecision.wait()
    )
    decision = await voice_router.route(
        introduction + " " + goal,
        source_segments=(introduction, goal),
    )
    assert decision.action == HandoffVoiceAction()
    assert decision.consumed_segments == 2
