# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DefaultMode gate ownership and lifecycle."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.classifier import (
    BinaryAnswer,
    ChoiceAnswer,
)
from agentscope.message import (
    AssistantMsg,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    UserMsg,
)

from qwenpaw.config.config import RubricGateConfig
from qwenpaw.loop.gates import StopAction
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


async def test_jev_is_opt_in_and_can_allow_a_text_response(decision_check):
    ctx, resolve, evaluate = decision_check
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
    assert (await mode.handler(ctx)).action == StopAction.TERMINATE
    evaluate.assert_awaited_once()
    request = evaluate.call_args.kwargs
    assert set(request["questions"]) == {"continue", "reason"}
    assert request["state"]["candidate_response"] == "I will export it."
    (result,) = request["state"]["conversation"][1]["content"]
    assert result["state"] == "error" and result["output"] == "File not found"


async def test_jev_reason_and_fallback_share_the_intervention_limit(
    decision_check,
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
    assert _find_gate(mode, IterationGate)._state().iteration == 1

    resolve.side_effect = typesafe_provider.TypeSafeEvaluationError("No model")
    result = await mode.handler(ctx)
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message == rubric.prompt
    assert (await mode.handler(ctx)).action == StopAction.TERMINATE
    assert resolve.call_count == 2
    evaluate.assert_awaited_once()
