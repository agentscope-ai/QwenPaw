# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DefaultMode gate ownership and lifecycle."""
from __future__ import annotations

import asyncio
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.agent import ReActConfig
from agentscope.tool import Toolkit
from agentscope.event import ReplyEndEvent
from agentscope.classifier import (
    BinaryAnswer,
    ChoiceAnswer,
)
from agentscope.message import (
    AssistantMsg,
    DataBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    URLSource,
    UserMsg,
)

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.config.config import AgentProfileConfig, RubricGateConfig
from qwenpaw.loop.gates import StopAction
from qwenpaw.loop.gates import rubric as rubric_module
from qwenpaw.loop.gates.doom_loop import DoomLoopGate
from qwenpaw.loop.gates.iteration import IterationGate
from qwenpaw.modes.default import DefaultMode, resolve_max_iterations
from qwenpaw.providers import typesafe_provider


@pytest.fixture(autouse=True)
def _force_session_id():
    with scoped_session_id("test-session"):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_disabled_iteration_runs_past_native_limit(monkeypatch, cancel):
    config = AgentProfileConfig(id="default", name="Default")
    config.running.loop.iteration.enabled = False
    mode = DefaultMode()
    workspace = SimpleNamespace(plugins=SimpleNamespace(stop_handlers=[]))
    mode.setup(workspace)
    await mode.on_turn_start(SimpleNamespace(agent_config=config))
    agent = QwenPawAgent(
        name="QwenPaw",
        model=SimpleNamespace(
            context_size=100000,
            formatter=SimpleNamespace(supported_input_media_types=set()),
        ),
        system_prompt="",
        toolkit=Toolkit(tools=[]),
        react_config=ReActConfig(
            max_iters=resolve_max_iterations(config.running) or sys.maxsize,
        ),
        middlewares=[],
        agent_config=config,
        stop_handlers=tuple(workspace.plugins.stop_handlers),
    )
    calls = 0
    reached = asyncio.Event()

    async def model_events(_tool_choice):
        nonlocal calls
        calls += 1
        if calls == 120:
            reached.set()
            if cancel:
                await asyncio.Future()
            yield AssistantMsg(name="QwenPaw", content="finished")

    # Stub model IO; exercise QwenPaw gates and AgentScope's real reply loop.
    monkeypatch.setattr(agent, "_reasoning_events", model_events)
    monkeypatch.setattr(agent, "compress_context", AsyncMock())
    events = []

    async def consume():
        async for event in agent.reply_stream(
            UserMsg(name="user", content="continue"),
        ):
            events.append(event)

    task = asyncio.create_task(consume())
    if cancel:
        await asyncio.wait_for(reached.wait(), timeout=5)
        task.cancel()
    await asyncio.wait_for(task, timeout=5)
    assert calls == 120
    reasons = [
        event.finished_reason
        for event in events
        if isinstance(event, ReplyEndEvent)
    ]
    assert reasons == ["interrupted" if cancel else "completed"]


def _running_config(
    max_iters=100,
    doom_enabled=True,
    rubric_enabled=True,
    iteration_enabled=True,
):
    doom_stage = SimpleNamespace(
        after=3,
        action="stop",
        prompt="doom",
    )
    doom = SimpleNamespace(
        enabled=doom_enabled,
        window_size=3,
        similarity_threshold=1.0,
        stages=[doom_stage],
    )
    iteration = SimpleNamespace(
        enabled=iteration_enabled,
        max_iterations=max_iters,
    )
    rubric = RubricGateConfig(
        enabled=rubric_enabled,
        prompt="continue working",
        max_interventions=1,
    )
    loop = SimpleNamespace(
        iteration=iteration,
        doom_loop=doom,
        rubric=rubric,
    )
    return SimpleNamespace(
        max_iters=max_iters,
        loop=loop,
    )


def _workspace():
    plugins = SimpleNamespace(stop_handlers=[])
    return SimpleNamespace(plugins=plugins)


def _context(config, agent=None):
    return SimpleNamespace(
        agent_config=SimpleNamespace(running=config),
        agent=agent,
    )


def _find_gate(mode, gate_type):
    return next(
        gate for gate in mode.handler.gates if isinstance(gate, gate_type)
    )


def test_setup_registers_one_default_handler():
    """Mode setup registers one default-scoped handler."""
    workspace = _workspace()
    mode = DefaultMode()

    mode.setup(workspace)

    assert len(workspace.plugins.stop_handlers) == 1
    registration = workspace.plugins.stop_handlers[0]
    assert registration.handler.__self__ is mode
    assert registration.scope == "default"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_turn_start_builds_configured_gates(enabled):
    """First turn builds gates from the current running config."""
    mode = DefaultMode()

    config = _running_config(max_iters=10000, iteration_enabled=enabled)
    await mode.on_turn_start(_context(config))

    assert len(mode.handler.gates) == (3 if enabled else 2)
    assert resolve_max_iterations(config) == (10000 if enabled else None)
    if enabled:
        gate = _find_gate(mode, IterationGate)
        assert gate._state().max_iterations == 10000


@pytest.mark.asyncio
async def test_session_configs_do_not_replace_each_others_gates():
    mode = DefaultMode()
    first_ready, second_ready = asyncio.Event(), asyncio.Event()

    async def run_session(sid, limit, ready, peer_ready):
        with scoped_session_id(sid):
            await mode.on_turn_start(
                _context(_running_config(max_iters=limit)),
            )
            handler = mode.handler
            iteration = _find_gate(mode, IterationGate)
            await iteration.check({})
            ready.set()
            await peer_ready.wait()
            assert mode.handler is handler
            assert iteration._state().max_iterations == limit
            assert iteration._state().iteration == 1
            await mode._check_stop({"has_tool_calls": True})
            assert iteration._state().iteration == 2
            return handler

    first, second = await asyncio.gather(
        run_session("first", 10000, first_ready, second_ready),
        run_session("second", 5, second_ready, first_ready),
    )
    assert first is not second


@pytest.mark.asyncio
async def test_next_turn_resets_iteration_and_doom_state():
    """A new turn resets current-session state without rebuilding gates."""
    mode = DefaultMode()
    ctx = _context(_running_config(max_iters=10))
    await mode.on_turn_start(ctx)
    iteration = _find_gate(mode, IterationGate)
    doom = _find_gate(mode, DoomLoopGate)

    for _ in range(5):
        await iteration.check({})
    doom.record("tool_a", "hash")
    assert iteration._state().iteration == 5
    assert len(doom._state().history) == 1

    await mode.on_turn_start(ctx)

    assert iteration._state().iteration == 0
    assert len(doom._state().history) == 0


@pytest.mark.asyncio
async def test_next_turn_reactivates_exhausted_iteration_gate():
    """A terminated iteration gate is active again on the next turn."""
    mode = DefaultMode()
    ctx = _context(_running_config(max_iters=1))
    await mode.on_turn_start(ctx)
    iteration = _find_gate(mode, IterationGate)

    await iteration.check({})
    assert iteration._state() is None

    await mode.on_turn_start(ctx)

    assert iteration._state() is not None
    assert iteration._state().iteration == 0


@pytest.mark.asyncio
async def test_config_change_rebuilds_without_duplicate_registration():
    """Hot-loaded config replaces gates on the existing handler."""
    workspace = _workspace()
    mode = DefaultMode()
    mode.setup(workspace)
    await mode.on_turn_start(_context(_running_config()))

    await mode.on_turn_start(
        _context(
            _running_config(
                doom_enabled=False,
                rubric_enabled=False,
            ),
        ),
    )

    assert len(mode.handler.gates) == 1
    assert len(workspace.plugins.stop_handlers) == 1


@pytest.mark.asyncio
async def test_conversation_reset_clears_session_and_pending_state():
    """Full reset tears down current gates and deferred decisions."""
    agent = SimpleNamespace(_gate_pending_stop=object())
    mode = DefaultMode()
    await mode.on_turn_start(_context(_running_config(), agent))
    iteration = _find_gate(mode, IterationGate)

    await mode.on_conversation_reset(_context(_running_config(), agent))

    assert iteration._state() is None
    assert agent._gate_pending_stop is None


@pytest.fixture
def decision_check(monkeypatch):
    provider = Mock(evaluate=AsyncMock())
    resolve = Mock(return_value=(provider, "jev-test"))
    monkeypatch.setattr(typesafe_provider, "resolve_decision_model", resolve)
    history = [
        UserMsg("user", "Export the report."),
        AssistantMsg(
            "agent",
            [
                ThinkingBlock(thinking="private reasoning"),
                ToolResultBlock(
                    id="export-1",
                    name="export",
                    state="error",
                    output=[TextBlock(text="File not found")],
                ),
            ],
        ),
    ]
    agent = SimpleNamespace(
        _agent_config=SimpleNamespace(decision_model=None),
        state=SimpleNamespace(
            context=history,
            summary="",
            tool_context=SimpleNamespace(activated_groups=set()),
        ),
        toolkit=SimpleNamespace(get_tool_schemas=AsyncMock(return_value=[])),
    )
    return (
        {
            "agent": agent,
            "final_msg": AssistantMsg("agent", "I will export it."),
        },
        resolve,
        provider.evaluate,
    )


async def test_jev_is_opt_in_and_preserves_self_check(decision_check):
    ctx, resolve, evaluate = decision_check
    ctx["agent"].toolkit.get_tool_schemas.return_value = [
        {
            "type": "function",
            "function": {
                "name": "export",
                "description": "Export the report.\nParameter details.",
                "parameters": {"type": "object"},
            },
        },
    ]
    config = _running_config()
    mode = DefaultMode()
    await mode.on_turn_start(_context(config))
    assert (
        await mode.handler(ctx)
    ).continuation_message == config.loop.rubric.prompt
    resolve.assert_not_called()

    config.loop.rubric.use_decision_model = True
    await mode.on_turn_start(_context(config))
    await mode.handler({**ctx, "has_tool_calls": True})
    resolve.assert_not_called()
    evaluate.return_value.content = {"continue": BinaryAnswer(0.5)}
    result = await mode.handler(ctx)
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message == config.loop.rubric.prompt
    assert (await mode.handler(ctx)).action == StopAction.TERMINATE
    evaluate.assert_awaited_once()
    request = evaluate.call_args.kwargs
    assert set(request["questions"]) == {"continue", "reason"}
    assert request["state"]["available_tools"] == [
        {"name": "export", "description": "Export the report."},
    ]
    assert request["state"]["candidate_response"] == "I will export it."
    (result,) = request["state"]["conversation"][1]["content"]
    assert result["state"] == "error" and result["output"] == "File not found"


@pytest.mark.parametrize("phase", ["resolver", "client", "request", "cleanup"])
@pytest.mark.parametrize(
    "cancel",
    [False, True],
    ids=["timeout", "user_cancel"],
)
async def test_jev_deadline_does_not_wait_for_provider_cleanup(
    decision_check,
    monkeypatch,
    phase,
    cancel,
):
    ctx, resolve, _ = decision_check
    provider = typesafe_provider.TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
    )
    started = asyncio.Event()
    release_async = asyncio.Event()
    release_sync = threading.Event()
    loop = asyncio.get_running_loop()

    def block_initialization():
        loop.call_soon_threadsafe(started.set)
        assert release_sync.wait(5), "Initialization was not released"

    async def evaluate(*_args, **_kwargs):
        if phase == "request":
            started.set()
            try:
                await release_async.wait()
            except asyncio.CancelledError:
                # A late provider result must not delay fallback or cancellation.
                await release_async.wait()
        return SimpleNamespace(
            content={
                "continue": BinaryAnswer(0.9),
                "reason": ChoiceAnswer("promised_action", 0.9, {}),
            },
        )

    async def close():
        if phase == "cleanup":
            started.set()
            await release_async.wait()

    classifier = AsyncMock(side_effect=evaluate)
    classifier.client = SimpleNamespace(aclose=AsyncMock(side_effect=close))

    def create(*_args, **_kwargs):
        if phase == "client":
            block_initialization()
        return classifier

    def resolve_model(*_args):
        if phase == "resolver":
            block_initialization()
        return provider, "jev-test"

    resolve.side_effect = resolve_model
    monkeypatch.setattr(
        typesafe_provider.TypeSafeProvider,
        "as_decision_model",
        create,
    )
    monkeypatch.setattr(
        typesafe_provider.TypeSafeProvider,
        "validate_model_selection",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        rubric_module,
        "_DECISION_TIMEOUT_SECONDS",
        5 if cancel else 0.2,
    )
    config = _running_config()
    config.loop.rubric.use_decision_model = True
    mode = DefaultMode()
    await mode.on_turn_start(_context(config))
    previous_tasks = set(rubric_module._pending_decision_tasks)
    call = asyncio.create_task(mode.handler(ctx))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        if cancel:
            call.cancel()
        done, _ = await asyncio.wait({call}, timeout=1)
        assert call in done, "The caller waited for blocked provider work"
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                call.result()
        else:
            result = call.result()
            assert result.continuation_message == config.loop.rubric.prompt
            assert (await mode.handler(ctx)).action == StopAction.TERMINATE
        pending = rubric_module._pending_decision_tasks - previous_tasks
        assert len(pending) == 1
        assert not next(iter(pending)).done()
    finally:
        release_sync.set()
        release_async.set()
        if not call.done():
            call.cancel()
        pending = rubric_module._pending_decision_tasks - previous_tasks
        await asyncio.wait_for(
            asyncio.gather(call, *pending, return_exceptions=True),
            timeout=2,
        )
    assert rubric_module._pending_decision_tasks == previous_tasks
    resolve.assert_called_once()
    if phase == "resolver":
        classifier.client.aclose.assert_not_awaited()
    else:
        classifier.client.aclose.assert_awaited_once()
    assert classifier.await_count == (
        1 if phase in {"request", "cleanup"} else 0
    )


@pytest.mark.parametrize("block_summary", [False, True])
async def test_jev_includes_summary_and_omits_inline_media(
    decision_check,
    block_summary,
):
    ctx, _, evaluate = decision_check
    agent = ctx["agent"]
    summary = "The user requires the report at output/final.csv."
    image = DataBlock(
        name="report.png",
        source=URLSource(
            url="data:image/png;base64,aGVsbG8=",
            media_type="image/png",
        ),
    )
    agent.state.summary = (
        [TextBlock(text=summary), image] if block_summary else summary
    )
    agent.state.context[0].content.append(image)
    agent.state.context[1].content[-1].output.append(image)
    config = _running_config()
    config.loop.rubric.use_decision_model = True
    mode = DefaultMode()
    await mode.on_turn_start(_context(config))
    evaluate.return_value.content = {"continue": BinaryAnswer(0.1)}

    await mode.handler(ctx)

    state = evaluate.call_args.kwargs["state"]
    assert summary in state["conversation_summary"]
    assert "aGVsbG8=" not in str(state)
    assert "report.png" in state["conversation"][0]["content"][-1]["text"]
    assert "report.png" in state["conversation"][1]["content"][-1]["output"]


@pytest.mark.parametrize(
    "unavailable",
    [False, True],
    ids=["no_issue", "unavailable"],
)
async def test_jev_reason_lasts_one_self_check_within_the_shared_limit(
    decision_check,
    unavailable,
):
    ctx, resolve, evaluate = decision_check
    config = _running_config()
    rubric = config.loop.rubric
    rubric.use_decision_model = True
    rubric.max_interventions = 2
    mode = DefaultMode()
    await mode.on_turn_start(_context(config))
    evaluate.return_value.content = {
        "continue": BinaryAnswer(0.9),
        "reason": ChoiceAnswer(
            "promised_action",
            0.9,
            {"promised_action": 0.9},
        ),
    }
    result = await mode.handler(ctx)
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message == (
        f"{rubric.prompt}\nCheck this possible issue against the conversation "
        "and tool results before acting. A requested action was promised but "
        "has not been performed."
    )
    assert _find_gate(mode, IterationGate)._state().iteration == 0

    if unavailable:
        resolve.side_effect = typesafe_provider.TypeSafeEvaluationError(
            "No model",
        )
    else:
        evaluate.return_value.content = {"continue": BinaryAnswer(0.1)}
    result = await mode.handler(ctx)
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message == rubric.prompt
    assert (await mode.handler(ctx)).action == StopAction.TERMINATE
    assert resolve.call_count == 2
    assert evaluate.await_count == (1 if unavailable else 2)


@pytest.mark.parametrize(
    ("probability", "confidence"),
    [(1.2, 0.9), (0.9, 1.2), (0.9, True), (0.9, 0.5)],
)
async def test_jev_requires_two_confident_answers(
    decision_check,
    probability,
    confidence,
):
    ctx, _, evaluate = decision_check
    config = _running_config()
    config.loop.rubric.use_decision_model = True
    mode = DefaultMode()
    await mode.on_turn_start(_context(config))
    evaluate.return_value.content = {
        "continue": BinaryAnswer(probability),
        "reason": ChoiceAnswer("missing_result", confidence, {}),
    }

    result = await mode.handler(ctx)

    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message == config.loop.rubric.prompt
    evaluate.assert_awaited_once()
