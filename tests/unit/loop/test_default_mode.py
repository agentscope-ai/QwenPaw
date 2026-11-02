# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DefaultMode gate ownership and lifecycle."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.classifier import (
    BinaryAnswer,
    ChoiceAnswer,
    ClassifierResponse,
)
from agentscope.message import (
    AssistantMsg,
    DataBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    UserMsg,
)

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.constant import (
    LOOP_CONTINUATION_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)
from qwenpaw.loop.gates import StopAction
from qwenpaw.loop.gates import rubric as rubric_module
from qwenpaw.loop.gates.doom_loop import DoomLoopGate
from qwenpaw.loop.gates.iteration import IterationGate
from qwenpaw.modes.default import DefaultMode
from qwenpaw.providers import typesafe_provider


@pytest.fixture(autouse=True)
def _force_session_id():
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="test-session",
    ):
        yield


def _running_config(
    max_iters=100,
    doom_enabled=True,
    rubric_enabled=True,
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
        enabled=True,
        max_iterations=max_iters,
    )
    rubric = SimpleNamespace(
        enabled=rubric_enabled,
        use_decision_model=False,
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
    assert registration.handler is mode.handler
    assert registration.scope == "default"


@pytest.mark.asyncio
async def test_turn_start_builds_configured_gates():
    """First turn builds gates from the current running config."""
    mode = DefaultMode()

    await mode.on_turn_start(_context(_running_config()))

    assert len(mode.handler.gates) == 3
    assert _find_gate(mode, IterationGate)._state() is not None


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
    profile = AgentProfileConfig(id="test", name="Test")
    profile.running.loop.rubric.enabled = True
    profile.running.loop.rubric.prompt = "Check remaining work."
    profile.decision_model = ModelSlotConfig(
        provider_id="typesafe",
        model="jev-test",
    )
    provider = typesafe_provider.TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        api_key="test",
        models=[{"id": "jev-test", "name": "Test", "model_type": "decision"}],
    )
    resolve = Mock(return_value=(provider, "jev-test"))
    evaluate = AsyncMock(
        return_value=ClassifierResponse(model="jev-test", content={}),
    )
    monkeypatch.setattr(typesafe_provider, "resolve_decision_model", resolve)
    monkeypatch.setattr(type(provider), "evaluate", evaluate)
    agent = SimpleNamespace(
        _agent_config=profile,
        state=SimpleNamespace(
            context=[UserMsg("user", "Export the report.")],
            tool_context=SimpleNamespace(activated_groups=set()),
        ),
        toolkit=SimpleNamespace(get_tool_schemas=AsyncMock(return_value=[])),
    )
    ctx = {
        "agent": agent,
        "final_msg": AssistantMsg("agent", "I will export it."),
    }
    return profile, ctx, resolve, evaluate


@pytest.mark.parametrize(
    ("probability", "choice", "confidence", "should_continue", "expect_hint"),
    [
        (0.5, "promised_action", 0.9, False, False),
        (0.9, "promised_action", 0.9, True, True),
        (0.9, "promised_action", 0.5, True, False),
        (0.9, "unclear", 0.9, True, False),
    ],
)
async def test_jev_stops_or_forwards_the_reason(
    decision_check,
    probability,
    choice,
    confidence,
    should_continue,
    expect_hint,
):
    profile, ctx, resolve, evaluate = decision_check
    rubric = profile.running.loop.rubric
    rubric.use_decision_model = True
    mode = DefaultMode()
    await mode.on_turn_start(_context(profile.running))
    evaluate.return_value.content = {
        "continue": BinaryAnswer(probability),
        "reason": ChoiceAnswer(choice, confidence, {choice: confidence}),
    }

    await mode.handler({**ctx, "has_tool_calls": True})
    resolve.assert_not_called()
    result = await mode.handler(ctx)
    resolve.assert_called_once_with(profile.decision_model)
    evaluate.assert_awaited_once()
    request = evaluate.call_args.kwargs
    assert set(request["questions"]) == {"continue", "reason"}
    assert request["model"] == "jev-test"
    assert request["state"]["candidate_response"] == "I will export it."
    assert request["state"]["completion_criteria"] == rubric.prompt
    assert _find_gate(mode, IterationGate)._state().iteration == 2
    if should_continue:
        assert result.action == StopAction.INTERRUPT_AND_CONTINUE
        expected = rubric.prompt
        if expect_hint:
            expected += (
                "\nCheck this possible issue against the conversation and tool "
                "results before acting. A requested action was promised but "
                "has not been performed."
            )
        assert result.continuation_message == expected
    else:
        assert result.action == StopAction.TERMINATE
    assert (await mode.handler(ctx)).action == StopAction.TERMINATE
    evaluate.assert_awaited_once()


@pytest.mark.parametrize(
    "case",
    ["opted_out", "unconfigured", "invalid", "timeout"],
)
async def test_jev_fallback_preserves_the_bounded_self_check(
    decision_check,
    monkeypatch,
    case,
):
    profile, ctx, resolve, evaluate = decision_check
    rubric = profile.running.loop.rubric
    if case != "opted_out":
        rubric.use_decision_model = True
    if case == "unconfigured":
        resolve.side_effect = typesafe_provider.TypeSafeEvaluationError(
            "No model",
        )
    elif case == "invalid":
        evaluate.return_value.content["continue"] = BinaryAnswer(float("nan"))
    elif case == "timeout":
        monkeypatch.setattr(rubric_module, "_DECISION_TIMEOUT_SECONDS", 0.1)

        async def stalled(**_kwargs):
            await asyncio.Event().wait()

        evaluate.side_effect = stalled
    mode = DefaultMode()
    await mode.on_turn_start(_context(profile.running))
    result = await mode.handler(ctx)
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message == rubric.prompt
    assert _find_gate(mode, IterationGate)._state().iteration == 0
    assert (await mode.handler(ctx)).action == StopAction.TERMINATE
    if case == "opted_out":
        resolve.assert_not_called()
    assert evaluate.await_count == (
        0 if case in {"opted_out", "unconfigured"} else 1
    )


async def test_jev_respects_user_cancellation(decision_check):
    profile, ctx, _, evaluate = decision_check
    profile.running.loop.rubric.use_decision_model = True
    evaluate.side_effect = asyncio.CancelledError()
    mode = DefaultMode()
    await mode.on_turn_start(_context(profile.running))
    with pytest.raises(asyncio.CancelledError):
        await mode.handler(ctx)


async def test_jev_receives_tool_evidence_without_thinking_or_binary(
    decision_check,
):
    profile, ctx, _, evaluate = decision_check
    profile.running.loop.rubric.use_decision_model = True
    screenshot = DataBlock(
        name="error.png",
        source={
            "type": "base64",
            "media_type": "image/png",
            "data": "binary-payload",
        },
    )
    history = ctx["agent"].state.context
    history.append(
        AssistantMsg(
            "agent",
            [
                ThinkingBlock(thinking="private reasoning"),
                ToolResultBlock(
                    id="export-1",
                    name="export",
                    state="error",
                    output=[TextBlock(text="File not found"), screenshot],
                ),
            ],
        ),
    )
    history.append(
        UserMsg(
            "user",
            "Check again.",
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: LOOP_CONTINUATION_MESSAGE_TAG,
            },
        ),
    )
    mode = DefaultMode()
    await mode.on_turn_start(_context(profile.running))
    await mode.handler(ctx)

    conversation = evaluate.call_args.kwargs["state"]["conversation"]
    assert [msg["synthetic"] for msg in conversation] == [False, False, True]
    serialized = json.dumps(conversation)
    assert "File not found" in serialized and "error.png" in serialized
    assert (
        "private reasoning" not in serialized
        and "binary-payload" not in serialized
    )
