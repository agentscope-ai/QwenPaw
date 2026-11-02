# -*- coding: utf-8 -*-
"""Optional decision-model completion checks and their legacy fallback."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from agentscope.agent import Agent
from agentscope.classifier import BinaryAnswer, ClassifierResponse
from agentscope.message import (
    DataBlock,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.constant import (
    LOOP_CONTINUATION_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)
from qwenpaw.loop.gates import StopAction, StopHandler, StopHandlerRegistration
from qwenpaw.loop.gates import rubric as module
from qwenpaw.loop.gates.iteration import IterationGate
from qwenpaw.modes.default.mode import DefaultMode
from qwenpaw.providers import ProviderManager
from qwenpaw.providers.typesafe_provider import TypeSafeProvider


def message(role, text):
    return Msg(name=role, role=role, content=[TextBlock(text=text)])


@pytest.fixture
def decision(monkeypatch):
    provider = TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        api_key="test-key",
        models=[
            {"id": model, "name": model, "model_type": "decision"}
            for model in ("global-decision", "agent-decision")
        ],
    )
    evaluate = AsyncMock(
        return_value=ClassifierResponse(
            model="global-decision",
            content={"continue": BinaryAnswer(probability=0.9)},
        ),
    )
    evaluate_impl = TypeSafeProvider.evaluate
    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
    manager = SimpleNamespace(
        default_models={
            "decision": ModelSlotConfig(
                provider_id="typesafe",
                model="global-decision",
            ),
        },
        get_provider=lambda _: provider,
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    return SimpleNamespace(
        provider=provider,
        evaluate=evaluate,
        evaluate_impl=evaluate_impl,
        manager=manager,
    )


@pytest.fixture
def context():
    agent = SimpleNamespace(
        _agent_config=AgentProfileConfig(id="test", name="Test"),
        state=SimpleNamespace(
            context=[message("user", "Fix the import and run the tests.")],
            tool_context=SimpleNamespace(activated_groups={"basic"}),
        ),
        toolkit=SimpleNamespace(
            get_tool_schemas=AsyncMock(
                return_value=[{"name": "execute_shell_command"}],
            ),
        ),
    )
    return {
        "agent": agent,
        "final_msg": message("assistant", "The import is fixed."),
        "has_tool_calls": False,
    }


@pytest.mark.parametrize("agent_slot", [False, True])
@pytest.mark.parametrize("probability", [0.1, 0.5, 0.9])
async def test_decision_controls_continuation_and_resolves_slot(
    decision,
    context,
    agent_slot,
    probability,
):
    if agent_slot:
        context["agent"]._agent_config.decision_model = ModelSlotConfig(
            provider_id="typesafe",
            model="agent-decision",
        )
    decision.evaluate.return_value.content["continue"] = BinaryAnswer(
        probability,
    )
    gate = module.QualitativeRubricGate(
        rubric="Verify the tests passed.",
        use_decision_model=True,
    )

    result = await gate.check(context)

    assert result.action == (
        StopAction.INTERRUPT_AND_CONTINUE
        if probability > 0.5
        else StopAction.BYPASS
    )
    assert not result.reset_peers
    args = decision.evaluate.call_args.kwargs
    assert args["model"] == (
        "agent-decision" if agent_slot else "global-decision"
    )
    assert args["state"]["candidate_response"] == "The import is fixed."
    assert args["state"]["completion_criteria"] == gate.build_continuation()


@pytest.mark.parametrize(
    "missing",
    ["slot", "provider", "key", "disabled", "model"],
)
async def test_unconfigured_decision_keeps_bounded_self_check(
    decision,
    context,
    missing,
):
    if missing == "slot":
        decision.manager.default_models["decision"] = None
    elif missing == "provider":
        decision.manager.get_provider = lambda _: None
    elif missing == "key":
        decision.provider.api_key = "  "
    elif missing == "disabled":
        decision.provider.enabled = False
    else:
        decision.provider.models.clear()
    gate = module.QualitativeRubricGate(
        rubric="Continue if work remains.",
        use_decision_model=True,
    )

    result = await gate.check(context)
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.reset_peers
    assert (await gate.check(context)).action == StopAction.BYPASS
    decision.evaluate.assert_not_awaited()


@pytest.mark.parametrize(
    "answer",
    [None, BinaryAnswer(float("nan")), BinaryAnswer(2), BinaryAnswer(True)],
)
async def test_invalid_decision_uses_self_check(decision, context, answer):
    decision.evaluate.return_value.content = {"continue": answer}

    gate = module.QualitativeRubricGate(use_decision_model=True)
    result = await gate.check(context)

    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.reset_peers


@pytest.mark.parametrize("failure", ["error", "timeout", "cancel"])
async def test_failure_falls_back_but_user_cancellation_propagates(
    monkeypatch,
    decision,
    context,
    failure,
):
    if failure == "timeout":
        monkeypatch.setattr(module, "_DECISION_TIMEOUT_SECONDS", 0.05)

        async def pending(**_kwargs):
            await asyncio.Event().wait()

        decision.evaluate.side_effect = pending
    else:
        decision.evaluate.side_effect = (
            asyncio.CancelledError()
            if failure == "cancel"
            else RuntimeError("offline")
        )
    gate = module.QualitativeRubricGate(use_decision_model=True)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await gate.check(context)
    else:
        result = await gate.check(context)
        assert result.action == StopAction.INTERRUPT_AND_CONTINUE
        assert result.reset_peers


async def test_tool_iterations_and_evaluation_limit_do_not_call_decision(
    decision,
    context,
):
    gate = module.QualitativeRubricGate(use_decision_model=True)
    context["has_tool_calls"] = True
    assert (await gate.check(context)).action == StopAction.BYPASS
    decision.evaluate.assert_not_awaited()
    context["has_tool_calls"] = False
    await gate.check(context)
    assert (await gate.check(context)).action == StopAction.BYPASS
    decision.evaluate.assert_awaited_once()
    gate.reset_turn()
    await gate.check(context)
    assert decision.evaluate.await_count == 2


async def test_decision_cannot_extend_iteration_budget(decision, context):
    handler = StopHandler()
    handler.register(IterationGate(max_iterations=2))
    handler.register(
        module.QualitativeRubricGate(
            max_evaluations=5,
            use_decision_model=True,
        ),
    )
    handler.reset_turn()

    assert (await handler(context)).action == StopAction.INTERRUPT_AND_CONTINUE
    stopped = await handler(context)

    assert stopped.action == StopAction.TERMINATE
    assert "Max iterations" in stopped.reason
    decision.evaluate.assert_awaited_once()


async def test_decision_receives_evidence_without_thinking_or_binary(
    decision,
    context,
):
    history = context["agent"].state.context
    history.append(
        message("user", "Only change the parser; leave the UI alone."),
    )
    history.append(
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ThinkingBlock(thinking="private reasoning"),
                ToolCallBlock(
                    id="run-tests",
                    name="execute_shell_command",
                    input='{"command":"pytest"}',
                    state="finished",
                ),
                ToolResultBlock(
                    id="run-tests",
                    name="execute_shell_command",
                    output=[
                        TextBlock(text="1 failed, 10 passed"),
                        DataBlock(
                            name="failure.png",
                            source={
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "binary-payload",
                            },
                        ),
                    ],
                    state="error",
                ),
            ],
        ),
    )
    synthetic = message("user", "Check the remaining work.")
    synthetic.metadata[QWENPAW_MESSAGE_TAG_KEY] = LOOP_CONTINUATION_MESSAGE_TAG
    history.append(synthetic)

    gate = module.QualitativeRubricGate(use_decision_model=True)
    await gate.check(context)

    state = decision.evaluate.call_args.kwargs["state"]
    serialized = json.dumps(state)
    assert "Only change the parser" in serialized
    assert "1 failed, 10 passed" in serialized
    assert "failure.png" in serialized
    assert "private reasoning" not in serialized
    assert "binary-payload" not in serialized
    assert state["conversation"][-1]["synthetic"] is True
    assert state["conversation"][0]["synthetic"] is False
    assert state["available_tools"] == [{"name": "execute_shell_command"}]


@pytest.mark.parametrize(
    "mode",
    [
        "disabled",
        "self_check",
        "unconfigured",
        "stop",
        "continue",
        "unclear",
        "low_confidence",
    ],
)
async def test_reasoning_uses_default_mode_completion_decision(
    monkeypatch,
    mock_typesafe,
    decision,
    context,
    mode,
):
    """Exercise reasoning, default gates and SDK with only HTTP mocked."""
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "global-decision"
        assert set(body["questions"]) == {"continue", "reason"}
        assert body["state"]["candidate_response"] == '{"ok":true}'
        choice = "unclear" if mode == "unclear" else "missing_answer"
        confidence = 0.45 if mode == "low_confidence" else 0.9
        return httpx2.Response(
            200,
            json={
                "model": "global-decision",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "answers": {
                    "continue": {
                        "type": "noul",
                        "noul": 0.1 if mode == "stop" else 0.9,
                    },
                    "reason": {
                        "type": "choice",
                        "choice": choice,
                        "confidence": confidence,
                        "probabilities": {choice: confidence},
                    },
                },
            },
        )

    monkeypatch.setattr(TypeSafeProvider, "evaluate", decision.evaluate_impl)
    mock_typesafe(respond)
    agent = object.__new__(QwenPawAgent)
    agent._agent_config = context["agent"]._agent_config
    rubric = agent._agent_config.running.loop.rubric
    rubric.enabled = mode != "disabled"
    rubric.use_decision_model = mode != "self_check"
    rubric.prompt = "请核对我要求的事项。"
    agent._context_manager = None
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent.name = "agent"
    agent.model = SimpleNamespace(model_key=None)
    agent._model_rejects_media = lambda: False
    agent._uses_request_time_media_normalization = lambda: False
    agent.state = context["agent"].state
    agent.state.cur_iter = 1
    agent.state.reply_id = "reply"
    agent.toolkit = context["agent"].toolkit
    handler = StopHandler()
    handler.replace(DefaultMode._build_gates(agent._agent_config.running))
    handler.reset_turn()
    agent._get_stop_handlers = lambda: [
        StopHandlerRegistration(
            plugin_id="__default_mode__",
            handler=handler,
            scope="default",
        ),
    ]
    if mode == "unconfigured":
        decision.manager.default_models["decision"] = None
    candidate = message("assistant", '{"ok":true}')

    async def model_reasoning(self, tool_choice=None):
        self.state.context.append(candidate)
        yield candidate

    monkeypatch.setattr(Agent, "_reasoning", model_reasoning)
    output = [event async for event in agent._reasoning()]

    if mode in {"disabled", "stop"}:
        assert output == [candidate]
        assert json.loads(output[0].get_text_content()) == {"ok": True}
        assert agent.state.context[-1] is candidate
    else:
        assert output == []
        assert (
            agent.state.context[-1].metadata[QWENPAW_MESSAGE_TAG_KEY]
            == LOOP_CONTINUATION_MESSAGE_TAG
        )
        expected = rubric.prompt
        if mode == "continue":
            expected += (
                "\nCheck this possible issue against the conversation "
                "and tool results before acting. "
                "The reply omits part of the requested answer."
            )
        assert agent.state.context[-1].get_text_content() == expected
        # A second natural stop is allowed once the intervention budget is spent.
        assert [event async for event in agent._reasoning()] == [candidate]
    assert len(requests) == (
        0 if mode in {"disabled", "self_check", "unconfigured"} else 1
    )
