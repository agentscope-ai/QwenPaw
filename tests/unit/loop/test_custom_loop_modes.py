# -*- coding: utf-8 -*-
"""Tests for declarative custom loop modes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agentscope.message import Msg, TextBlock
from pydantic import ValidationError

from qwenpaw.config.config import (
    CustomLoopModeConfig,
    GateInstanceConfig,
    LoopConfig,
)
from qwenpaw.loop.catalog import get_gate_catalog
from qwenpaw.loop.compiler import compile_loop_mode
from qwenpaw.loop.gates import CompletionRubricGate, StopAction
from qwenpaw.loop.gates.limits import (
    TimeoutGate,
    TokenBudgetGate,
    ToolCallBudgetGate,
)
from qwenpaw.modes.custom_loop import (
    CustomLoopController,
    DeclarativeLoopMode,
    LoopModeActivationStore,
    load_custom_loop_modes,
)
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry


def _gate(
    gate_id: str,
    gate_type: str,
    params: dict | None = None,
) -> GateInstanceConfig:
    return GateInstanceConfig(
        id=gate_id,
        type=gate_type,
        params=params or {},
    )


def _mode(*gates: GateInstanceConfig) -> CustomLoopModeConfig:
    return CustomLoopModeConfig(
        id="quality",
        name="Quality",
        slash_command="quality",
        enabled=True,
        gates=list(gates),
    )


def test_loop_config_accepts_multiple_custom_modes() -> None:
    config = LoopConfig(
        custom_modes=[
            _mode(_gate("limit", "iteration")),
            CustomLoopModeConfig(
                id="research",
                name="Research",
                slash_command="research",
                enabled=True,
                gates=[_gate("timeout", "timeout")],
            ),
        ],
    )

    assert [mode.id for mode in config.custom_modes] == [
        "quality",
        "research",
    ]


def test_loop_config_rejects_gate_outside_builtin_catalog() -> None:
    with pytest.raises(ValidationError, match="Unknown built-in gate type"):
        LoopConfig(
            custom_modes=[
                CustomLoopModeConfig(
                    id="unsafe",
                    name="Unsafe",
                    slash_command="unsafe",
                    enabled=False,
                    gates=[
                        GateInstanceConfig(
                            id="python",
                            type="python_gate",
                            enabled=False,
                        ),
                    ],
                ),
            ],
        )


def test_custom_mode_rejects_conflicting_completion_gates() -> None:
    with pytest.raises(ValidationError, match="conflicts"):
        _mode(
            _gate("retry", "text_response_retry"),
            _gate(
                "rubric",
                "completion_rubric",
                {
                    "criteria": [
                        {
                            "id": "done",
                            "description": "The request is complete",
                        },
                    ],
                },
            ),
        )


def test_compiler_preserves_pipeline_order() -> None:
    handler = compile_loop_mode(
        _mode(
            _gate("time", "timeout", {"max_seconds": 60}),
            _gate("limit", "iteration", {"max_iterations": 10}),
        ),
    )

    assert [gate.name for gate in handler.gates] == ["time", "limit"]
    assert [gate.priority for gate in handler.gates] == [0, 10]


def test_compiler_validates_disabled_gate_configuration() -> None:
    mode = CustomLoopModeConfig(
        id="invalid",
        name="Invalid",
        slash_command="invalid",
        enabled=False,
        gates=[
            GateInstanceConfig(
                id="unknown",
                type="not_registered",
                enabled=False,
            ),
        ],
    )

    with pytest.raises(ValueError, match="Unknown built-in gate type"):
        compile_loop_mode(mode)


def test_catalog_contains_only_seven_builtin_gates() -> None:
    entries = get_gate_catalog().describe()

    assert {entry["type"] for entry in entries} == {
        "iteration",
        "doom_loop",
        "token_budget",
        "timeout",
        "tool_call_budget",
        "text_response_retry",
        "completion_rubric",
    }


class _FakeModel:
    def __init__(self, content: dict) -> None:
        self.content = content

    async def generate_structured_output(self, **kwargs):  # noqa: ANN003
        del kwargs
        return SimpleNamespace(content=self.content)


def _rubric_context(content: dict) -> dict:
    state = SimpleNamespace(
        context=[
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="Finish the task")],
            ),
        ],
    )
    agent = SimpleNamespace(model=_FakeModel(content), state=state)
    final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="Completed")],
    )
    return {
        "agent": agent,
        "final_msg": final,
        "has_tool_calls": False,
        "iteration": 1,
    }


@pytest.mark.asyncio
async def test_completion_rubric_passes_required_criterion() -> None:
    gate = CompletionRubricGate(
        criteria=[
            {
                "id": "done",
                "description": "The request is complete",
                "required": True,
                "weight": 1.0,
            },
        ],
    )
    gate.reset_turn()

    result = await gate.check(
        _rubric_context(
            {
                "criteria": [
                    {
                        "id": "done",
                        "passed": True,
                        "score": 1.0,
                        "evidence": ["Completed"],
                        "feedback": "",
                    },
                ],
            },
        ),
    )

    assert result.action == StopAction.TERMINATE
    assert "passed" in result.reason


@pytest.mark.asyncio
async def test_completion_rubric_requests_bounded_revision() -> None:
    gate = CompletionRubricGate(
        criteria=[
            {
                "id": "done",
                "description": "The request is complete",
                "required": True,
                "weight": 1.0,
            },
        ],
        max_revisions=1,
    )
    gate.reset_turn()
    context = _rubric_context(
        {
            "criteria": [
                {
                    "id": "done",
                    "passed": False,
                    "score": 0.2,
                    "evidence": [],
                    "feedback": "Run verification",
                },
            ],
        },
    )

    first = await gate.check(context)
    second = await gate.check(context)

    assert first.action == StopAction.INTERRUPT_AND_CONTINUE
    assert "Run verification" in gate.build_continuation()
    assert second.action == StopAction.TERMINATE
    assert "1 revisions" in second.reason


@pytest.mark.asyncio
async def test_custom_mode_command_activates_current_session() -> None:
    config = _mode(_gate("limit", "iteration"))
    store = LoopModeActivationStore()
    mode = DeclarativeLoopMode(config, store)
    plugins = SimpleNamespace(
        slash_command_registry=SlashCommandRegistry(),
        stop_handlers=[],
        modes=[mode],
    )
    workspace = SimpleNamespace(plugins=plugins)
    mode.setup(workspace)
    message = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="/quality verify it")],
    )
    ctx = SimpleNamespace(
        session_id="session-a",
        input_msgs=[message],
        workspace=workspace,
    )

    response = await mode.commands()[0].handler(ctx, "verify it")

    assert response is None
    assert store.current("session-a") == "quality"
    assert message.content[0].text == "verify it"


@pytest.mark.asyncio
async def test_switching_custom_mode_resets_previous_handler() -> None:
    store = LoopModeActivationStore()
    quality = DeclarativeLoopMode(
        _mode(_gate("quality-limit", "iteration")),
        store,
    )
    research_config = CustomLoopModeConfig(
        id="research",
        name="Research",
        slash_command="research",
        enabled=True,
        gates=[_gate("research-limit", "iteration")],
    )
    research = DeclarativeLoopMode(research_config, store)
    quality.handler.reset_session = MagicMock()
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(modes=[quality, research]),
    )
    ctx = SimpleNamespace(
        session_id="session-a",
        input_msgs=[],
        workspace=workspace,
    )

    await quality.commands()[0].handler(ctx, "")
    await research.commands()[0].handler(ctx, "")

    assert store.current("session-a") == "research"
    quality.handler.reset_session.assert_called_once()


@pytest.mark.asyncio
async def test_mode_off_clears_activation_and_handler_state() -> None:
    store = LoopModeActivationStore()
    quality = DeclarativeLoopMode(
        _mode(_gate("quality-limit", "iteration")),
        store,
    )
    quality.handler.reset_session = MagicMock()
    controller = CustomLoopController(store)
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(modes=[quality, controller]),
    )
    ctx = SimpleNamespace(
        session_id="session-a",
        input_msgs=[],
        workspace=workspace,
    )
    store.activate("session-a", "quality")

    response = await controller.commands()[0].handler(ctx, "off")

    assert store.current("session-a") is None
    assert "disabled" in response.content[0].text
    quality.handler.reset_session.assert_called_once()


@pytest.mark.asyncio
async def test_custom_mode_rejects_active_builtin_mode() -> None:
    store = LoopModeActivationStore()
    custom = DeclarativeLoopMode(
        _mode(_gate("quality-limit", "iteration")),
        store,
    )
    goal = SimpleNamespace(
        name="goal",
        is_active=lambda ctx: True,
    )
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(modes=[goal, custom]),
    )
    ctx = SimpleNamespace(
        session_id="session-a",
        input_msgs=[],
        workspace=workspace,
    )

    response = await custom.commands()[0].handler(ctx, "verify it")

    assert store.current("session-a") is None
    assert "End the active goal mode" in response.content[0].text


def test_loader_registers_multiple_enabled_modes() -> None:
    quality = _mode(_gate("limit", "iteration"))
    research = CustomLoopModeConfig(
        id="research",
        name="Research",
        slash_command="research",
        enabled=True,
        gates=[_gate("time", "timeout")],
    )
    disabled = CustomLoopModeConfig(
        id="draft",
        name="Draft",
        slash_command="draft",
        enabled=False,
    )
    config = SimpleNamespace(
        running=SimpleNamespace(
            loop=SimpleNamespace(
                custom_modes=[quality, research, disabled],
            ),
        ),
    )
    workspace = SimpleNamespace(
        config=config,
        plugins=WorkspacePlugins(),
    )

    load_custom_loop_modes(workspace)

    assert [mode.name for mode in workspace.plugins.modes] == [
        "custom:quality",
        "custom:research",
        "custom-loop-control",
    ]
    assert workspace.plugins.slash_command_registry.names() == [
        "mode",
        "quality",
        "research",
    ]


@pytest.mark.asyncio
async def test_token_budget_accumulates_each_iteration(monkeypatch) -> None:
    gate = TokenBudgetGate(max_total_tokens=10)
    gate.reset_turn()
    monkeypatch.setattr(
        gate,
        "_current_usage",
        lambda: {"prompt_tokens": 4, "completion_tokens": 2},
    )

    first = await gate.check({"iteration": 1})
    second = await gate.check({"iteration": 2})

    assert first.action == StopAction.BYPASS
    assert second.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_timeout_gate_uses_monotonic_boundary(monkeypatch) -> None:
    values = iter([14.0, 16.0])
    monkeypatch.setattr(
        "qwenpaw.loop.gates.limits.time",
        SimpleNamespace(monotonic=lambda: next(values)),
    )
    gate = TimeoutGate(max_seconds=5)
    gate.activate(SimpleNamespace(started_at=10.0))

    before = await gate.check({})
    after = await gate.check({})

    assert before.action == StopAction.BYPASS
    assert after.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_tool_call_budget_enforces_per_tool_limit() -> None:
    gate = ToolCallBudgetGate(max_calls=10, per_tool={"search": 1})
    gate.reset_turn()
    message = SimpleNamespace(
        content=[{"type": "tool_call", "name": "search"}],
    )
    agent = SimpleNamespace(state=SimpleNamespace(context=[message]))

    result = await gate.check({"iteration": 1, "agent": agent})

    assert result.action == StopAction.TERMINATE
    assert "search" in result.reason
