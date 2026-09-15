import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.realtime_voice.contracts import (
    ClarifyVoiceAction,
    DelegateVoiceAction,
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
async def test_failed_input_registration_keeps_words_for_manual_retry():
    from unittest.mock import Mock
    decision = VoiceRouteDecision.commit(DelegateVoiceAction("shortened"))
    committer = SpokenTurnCommitter(router(decision, decision))
    committer.on_commit = Mock(side_effect=RuntimeError("closed"))
    events = committer.events()
    try:
        await committer.add_segment("source", "original words with constraints")
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
        VoiceRouteDecision.commit(DelegateVoiceAction("计算 123 加 456")),
    )
    committer = SpokenTurnCommitter(voice_router)
    events = committer.events()

    await committer.add_segment("item-1", "请帮我计算一百二十三加上")
    pending = await next_event(events, PendingSpokenTurn)
    while pending.state != "waiting":
        pending = await next_event(events, PendingSpokenTurn)

    await committer.add_segment("item-2", "四百五十六，只回答结果。")
    committed = await next_event(events, CommittedSpokenTurn)

    assert committed.source_ids == ("item-1", "item-2")
    assert committed.text.endswith("四百五十六，只回答结果。")
    assert committed.action == DelegateVoiceAction("计算 123 加 456")
    await committer.close()


@pytest.mark.asyncio
async def test_commit_keeps_later_speech_as_a_separate_candidate():
    release = asyncio.Event()

    async def route(text, *, force_commit=False):
        del force_commit
        if text == "first":
            await release.wait()
            return VoiceRouteDecision.commit(DelegateVoiceAction("first"))
        return VoiceRouteDecision.commit(DelegateVoiceAction("second"))

    voice_router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(voice_router)
    events = committer.events()

    await committer.add_segment("item-1", "first")
    await asyncio.sleep(0)
    await committer.add_segment("item-2", "second")
    release.set()

    first = await next_event(events, CommittedSpokenTurn)
    second = await next_event(events, CommittedSpokenTurn)
    assert (first.text, second.text) == ("first", "second")
    assert voice_router.route.await_count == 2
    await committer.close()


@pytest.mark.asyncio
async def test_commit_routes_each_backlogged_segment_separately():
    release = asyncio.Event()

    async def route(text, *, force_commit=False):
        del force_commit
        if text == "task-0":
            await release.wait()
        return VoiceRouteDecision.commit(DelegateVoiceAction(text))

    voice_router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(voice_router)
    events = committer.events()

    for index in range(10):
        await committer.add_segment(f"item-{index}", f"task-{index}")
        if index == 0:
            await asyncio.sleep(0)
    release.set()

    committed = [await next_event(events, CommittedSpokenTurn) for _ in range(10)]
    assert [turn.text for turn in committed] == [f"task-{index}" for index in range(10)]
    assert voice_router.route.await_count == 10
    await committer.close()


@pytest.mark.asyncio
async def test_wait_reclassifies_candidate_with_following_segment():
    release = asyncio.Event()

    async def route(text, *, force_commit=False):
        del force_commit
        if text == "first":
            await release.wait()
            return VoiceRouteDecision.wait()
        return VoiceRouteDecision.commit(DelegateVoiceAction(text))

    voice_router = SimpleNamespace(route=AsyncMock(side_effect=route))
    committer = SpokenTurnCommitter(voice_router)
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
    committer = SpokenTurnCommitter(voice_router)
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
    assert voice_router.route.await_args.kwargs == {"force_commit": True}
    await committer.close()


@pytest.mark.asyncio
async def test_manual_commit_never_leaves_an_illegal_wait_pending():
    voice_router = router(
        VoiceRouteDecision.wait(),
        VoiceRouteDecision.wait(),
    )
    committer = SpokenTurnCommitter(voice_router)
    events = committer.events()

    await committer.add_segment("item-1", "请帮我计算一百二十三加上")
    pending = await next_event(events, PendingSpokenTurn)
    while pending.state != "waiting":
        pending = await next_event(events, PendingSpokenTurn)
    assert await committer.commit_pending("manual") is True

    committed = await next_event(events, CommittedSpokenTurn)
    assert committed.origin == "manual"
    assert committed.action == ClarifyVoiceAction(
        "请补充或重新说明需要提交的完整请求。"
    )
    await committer.close()


@pytest.mark.asyncio
async def test_duplicate_source_id_is_ignored():
    voice_router = router(VoiceRouteDecision.wait())
    committer = SpokenTurnCommitter(voice_router)

    await committer.add_segment("item-1", "same")
    await asyncio.sleep(0)
    await committer.add_segment("item-1", "same")

    assert voice_router.route.await_count == 1
    await committer.close()


def test_parse_route_rejects_unknown_task_reference():
    with pytest.raises(ValueError, match="unknown task_ref"):
        _parse_route(
            '{"decision":"COMMIT","action":{"type":"FOLLOW_UP",'
            '"task_ref":"任务二","instruction":"继续"}}',
            task_refs={"任务一"},
            force_commit=False,
        )


def test_parse_route_keeps_full_delegate_request():
    decision = _parse_route(
        '{"decision":"COMMIT","action":{"type":"DELEGATE",'
        '"request":"检查项目并运行测试"}}',
        task_refs=set(),
        force_commit=False,
    )

    assert decision.action == DelegateVoiceAction("检查项目并运行测试")
    assert decision.action.public_dict() == {"type": "DELEGATE"}


def test_manual_route_maps_illegal_wait_to_safe_clarification():
    decision = _parse_route(
        '{"decision":"WAIT"}',
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
        VoiceRouteDecision.commit(DelegateVoiceAction("计算 123 加 456")),
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
    await committer.speech_started()
    await asyncio.sleep(0.15)
    await committer.add_segment("item-2", "四百五十六")

    committed = await next_event(events, CommittedSpokenTurn)
    assert committed.text == "请帮我计算一百二十三加上 四百五十六"
    assert committed.action == DelegateVoiceAction("计算 123 加 456")
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
async def test_router_freezes_public_context_and_preserves_request(force_commit):
    context = AsyncMock(return_value='{"messages":[{"text":"BLUE_CAT"}]}')
    original = context.return_value
    action = {"type": "DELEGATE", "request": "Print that phrase once"}

    async def respond(messages, **kwargs):
        context.return_value = '{"messages":[{"text":"RED_CAT"}]}'
        return {"text": json.dumps(action if force_commit else {
            "decision": "COMMIT", "action": action,
        })}

    model = AsyncMock(side_effect=respond)
    voice_router = provider_router(model)
    voice_router._conversation_context = context
    decision = await voice_router.route("Print that phrase once", force_commit=force_commit)
    context.assert_awaited_once_with()
    assert decision.conversation_context == original
    prompt = model.await_args.args[0][1].content[0].text
    assert original in prompt and "RED_CAT" not in prompt
    assert prompt.endswith("TRANSCRIPT:\nPrint that phrase once")
    assert decision.action == DelegateVoiceAction("Print that phrase once")
    assert "conversation_context" not in decision.action.public_dict()


@pytest.mark.parametrize("action", [DelegateVoiceAction("Print it"), ClarifyVoiceAction("which file")])
async def test_committer_carries_candidate_context_through_commit_and_grace(action):
    from types import SimpleNamespace

    committer = SpokenTurnCommitter(SimpleNamespace(route=AsyncMock(
        return_value=VoiceRouteDecision("COMMIT", action, "frozen context"),
    )), continuation_grace_ms=1)
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
async def test_router_receives_all_admitted_steps_and_input_states(force_commit):
    model = AsyncMock(return_value={"text": '{"decision":"WAIT"}'})
    voice_router = provider_router(model)
    voice_router._task_context.return_value = (
        VoiceTaskSnapshot(
            task_id="task", task_ref="任务一", status="processing",
            request="first step", version=1,
            input_requests=(("a", "first step"), ("b", "second step"),
                            ("c", "third step")),
            input_states=(("a", "completed"), ("b", "completed"),
                          ("c", "processing")),
        ),
    )
    await voice_router.route("任务一三步的结果是什么", force_commit=force_commit)
    messages = model.await_args.args[0]
    content = messages[1].content[0].text
    context = json.loads(content.split("TASKS:\n")[1].split("\nTRANSCRIPT:")[0])
    assert context["omitted_tasks"] == 0
    task = context["tasks"][0]
    assert task["input_count"] == 3
    assert task["omitted_inputs"] == 0
    assert [(i["input_id"], i["request"], i["state"]) for i in task["inputs"]] == [
        ("a", "first step", "completed"),
        ("b", "second step", "completed"),
        ("c", "third step", "processing"),
    ]
    assert "STATUS" in messages[0].content[0].text
    rules = messages[0].content[0].text
    assert "admitted work needs more information or user action" in rules
    assert "input/step within a" in rules
    assert "does not authorize guessing a target" in rules


async def test_router_context_marks_omitted_tasks_inputs_and_request_text():
    model = AsyncMock(return_value={"text": '{"decision":"WAIT"}'})
    voice_router = provider_router(model)
    voice_router._task_context.return_value = tuple(
        VoiceTaskSnapshot(
            task_id=str(n), task_ref=f"任务{n}", status="processing", version=1,
            request="first",
            input_requests=tuple((str(i), "x" * 600) for i in range(25)),
        ) for n in range(25)
    )
    await voice_router.route("当前进度")
    content = model.await_args.args[0][1].content[0].text
    context = json.loads(content.split("TASKS:\n")[1].split("\nTRANSCRIPT:")[0])
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
            '{"decision":"COMMIT","action":{"type":"FOLLOW_UP",'
            '"task_ref":"unknown","instruction":"continue"}}',
            "invalid_route",
            "object_prefix",
        ),
    ],
)
async def test_router_diagnoses_output_without_logging_content(raw, kind, shape):
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
    assert voice_router._model is model  # Parse failures retain existing policy.


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
    model = AsyncMock(return_value={"text": '{"decision":"WAIT"}'})
    voice_router = provider_router(model)
    assert await voice_router.route("unfinished") == VoiceRouteDecision.wait()
    assert model.call_args.kwargs == {
        "tools": None,
        "max_tokens": 256,
        "disable_thinking": True,
    }


async def test_cancelled_route_is_not_reported_as_failure(caplog):
    voice_router = provider_router(AsyncMock(side_effect=asyncio.CancelledError))
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
    model = AsyncMock(side_effect=[first, {"text": '{"type":"CONVERSE"}'}])
    voice_router = provider_router(model)
    committer = SpokenTurnCommitter(voice_router)
    try:
        events = committer.events()
        await committer.add_segment("source-1", secret)
        pending = await next_event(events, PendingSpokenTurn)
        while pending.state != "needs_confirmation":
            pending = await next_event(events, PendingSpokenTurn)
        assert pending.text == secret
        assert pending.error == "voice_router_unavailable"
        records = [r for r in caplog.records if "Voice routing failed" in r.message]
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


async def test_router_setup_error_is_distinct_from_provider_failure(monkeypatch):
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


async def test_observer_tolerates_unknown_blocks_and_preserves_reported_reason():
    model = AsyncMock(
        return_value={
            "content": [{"type": {"unexpected": "secret"}}, {"text": "{broken"}],
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
        await provider_router(AsyncMock(return_value=response)).route("request")
    details = caught.value.diagnostics
    assert details["failure"] == "empty_output"
    assert details["block_types"] == ["thinking"]
    assert details["output_tokens"] == 256
    assert details["model_finished_reason"] == "completed"
    assert details["upstream_finish_reason"] is None
    assert "private reasoning" not in json.dumps(details)
