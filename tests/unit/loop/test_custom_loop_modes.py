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
    _sanitize_custom_loop_modes,
    _sanitize_loop_config,
)
from qwenpaw.loop.catalog import CompletionRubricParams, get_gate_catalog
from qwenpaw.loop.compiler import compile_loop_mode
from qwenpaw.loop.gates import (
    CompletionRubricGate,
    QualitativeRubricGate,
    StopAction,
)
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


def test_completion_rubric_defaults_require_continued_work() -> None:
    params = CompletionRubricParams()

    assert "work must continue" in params.prompt


def test_loop_config_rejects_duplicate_normalized_names() -> None:
    """Display names stay unambiguous for user-facing mode pickers."""
    with pytest.raises(
        ValidationError,
        match="Custom loop mode names must be unique",
    ):
        LoopConfig(
            custom_modes=[
                _mode(_gate("limit", "iteration")),
                CustomLoopModeConfig(
                    id="quality-copy",
                    name=" quality ",
                    slash_command="quality-copy",
                    enabled=False,
                ),
            ],
        )


def test_loop_config_rejects_unicode_casefold_names() -> None:
    """Save validation and reload sanitization use one normalization."""
    with pytest.raises(
        ValidationError,
        match="Custom loop mode names must be unique",
    ):
        LoopConfig(
            custom_modes=[
                CustomLoopModeConfig(
                    id="street",
                    name="Straße",
                    slash_command="street",
                ),
                CustomLoopModeConfig(
                    id="street-copy",
                    name="STRASSE",
                    slash_command="street-copy",
                ),
            ],
        )


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


def test_invalid_saved_custom_modes_do_not_block_loop_config(caplog) -> None:
    """Stale optional modes are skipped while valid Loop data still loads."""
    valid = _mode(_gate("limit", "iteration")).model_dump()
    stale_retry = {
        **valid,
        "id": "stale-retry",
        "name": "Stale retry",
        "slash_command": "stale-retry",
        "gates": [
            {
                "id": "retry",
                "type": "text_response_retry",
                "enabled": True,
                "params": {"max_interventions": 1},
            },
        ],
    }
    stale_completion = {
        **valid,
        "id": "stale-completion",
        "name": "Stale completion",
        "slash_command": "stale-completion",
        "gates": [
            {
                "id": "completion",
                "type": "completion_rubric",
                "enabled": True,
                "params": {"criteria": []},
            },
        ],
    }
    data = {
        "running": {
            "loop": {
                "custom_modes": [
                    valid,
                    stale_retry,
                    stale_completion,
                ],
            },
        },
    }

    _sanitize_custom_loop_modes(data, "default")
    loop = LoopConfig.model_validate(data["running"]["loop"])

    assert [mode.id for mode in loop.custom_modes] == ["quality"]
    assert "text_response_retry" in caplog.text
    assert "criteria" in caplog.text


def test_invalid_builtin_loop_data_falls_back_to_defaults(caplog) -> None:
    """Invalid built-in Loop values must not block the Agent profile."""
    data = {
        "running": {
            "loop": {
                "iteration": {
                    "enabled": True,
                    "max_iterations": 0,
                },
            },
        },
    }

    _sanitize_loop_config(data, "default")
    loop = LoopConfig.model_validate(data["running"]["loop"])

    assert loop == LoopConfig()
    assert "using defaults" in caplog.text


def test_custom_mode_rejects_conflicting_completion_gates() -> None:
    with pytest.raises(ValidationError, match="exclusive group"):
        _mode(
            _gate("qualitative", "qualitative_rubric"),
            _gate(
                "rubric",
                "completion_rubric",
            ),
        )


def test_compiler_preserves_pipeline_order() -> None:
    handler = compile_loop_mode(
        _mode(
            _gate("tools", "tool_call_budget", {"max_calls": 5}),
            _gate("limit", "iteration", {"max_iterations": 10}),
        ),
    )

    assert [gate.name for gate in handler.gates] == ["tools", "limit"]
    assert [gate.priority for gate in handler.gates] == [0, 10]


def test_catalog_contains_only_seven_builtin_gates() -> None:
    entries = get_gate_catalog().describe()

    assert {entry["type"] for entry in entries} == {
        "iteration",
        "doom_loop",
        "token_budget",
        "timeout",
        "tool_call_budget",
        "qualitative_rubric",
        "completion_rubric",
    }
    groups = {entry["type"]: entry["exclusive_group"] for entry in entries}
    assert groups["qualitative_rubric"] == "completion_rubric"
    assert groups["completion_rubric"] == "completion_rubric"
    assert groups["iteration"] is None


def _rubric_context() -> tuple[dict, Msg]:
    state = SimpleNamespace(
        context=[
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="Finish the task")],
            ),
        ],
    )
    agent = SimpleNamespace(state=state)
    final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="Completed")],
    )
    return (
        {
            "agent": agent,
            "final_msg": final,
            "has_tool_calls": False,
            "iteration": 1,
        },
        final,
    )


@pytest.mark.asyncio
async def test_qualitative_rubric_only_revises_text_responses() -> None:
    gate = QualitativeRubricGate(
        rubric="Check every explicit requirement.",
        max_evaluations=1,
    )
    gate.reset_turn()
    context, _candidate = _rubric_context()

    context["has_tool_calls"] = True
    tool_result = await gate.check(context)
    context["has_tool_calls"] = False
    revision = await gate.check(context)
    finished = await gate.check(context)
    still_finished = await gate.check(context)

    assert tool_result.action == StopAction.BYPASS
    assert revision.action == StopAction.INTERRUPT_AND_CONTINUE
    assert gate.build_continuation() == "Check every explicit requirement."
    assert finished.action == StopAction.BYPASS
    assert still_finished.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_completion_rubric_accepts_configured_signal() -> None:
    gate = CompletionRubricGate(
        prompt="The request is complete.",
        completion_signal="DONE",
    )
    gate.reset_turn()
    context, candidate = _rubric_context()

    request = await gate.check(context)
    context["final_msg"] = Msg(
        name="assistant",
        role="assistant",
        content=[
            TextBlock(
                type="text",
                text="  done \n",
            ),
        ],
    )
    result = await gate.check(context)

    assert request.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.action == StopAction.TERMINATE
    assert result.final_message is candidate
    assert "passed" in result.reason


@pytest.mark.asyncio
async def test_completion_rubric_requests_bounded_revision() -> None:
    gate = CompletionRubricGate(
        prompt="The request is complete.",
        max_evaluations=2,
    )
    gate.reset_turn()
    context, _candidate = _rubric_context()

    await gate.check(context)
    evaluation_prompt = gate.build_continuation()
    assert "Do not merely report" in evaluation_prompt

    context["final_msg"] = Msg(
        name="assistant",
        role="assistant",
        content=[
            TextBlock(
                type="text",
                text="NOT COMPLETED",
            ),
        ],
    )
    revision = await gate.check(context)
    assert gate.build_continuation() == evaluation_prompt

    context["has_tool_calls"] = True
    tool_result = await gate.check(context)
    context["has_tool_calls"] = False
    context["final_msg"] = Msg(
        name="assistant",
        role="assistant",
        content=[
            TextBlock(
                type="text",
                text="Task is still incomplete",
            ),
        ],
    )
    stopped = await gate.check(context)

    assert revision.action == StopAction.INTERRUPT_AND_CONTINUE
    assert tool_result.action == StopAction.BYPASS
    assert stopped.action == StopAction.TERMINATE
    assert "2 evaluations" in stopped.reason


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
async def test_switching_custom_mode_requires_explicit_exit() -> None:
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

    assert store.current("session-a") == "quality"
    quality.handler.reset_session.assert_not_called()


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
        gates=[_gate("tools", "tool_call_budget")],
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
async def test_timeout_gate_stops_only_when_boundary_is_checked(
    monkeypatch,
) -> None:
    values = iter([15.0, 16.0])
    monkeypatch.setattr(
        "qwenpaw.loop.gates.limits.time",
        SimpleNamespace(monotonic=lambda: next(values)),
    )
    gate = TimeoutGate(max_seconds=2)
    gate.activate(SimpleNamespace(started_at=14.0))

    before_limit = await gate.check({"iteration": 1})
    at_next_boundary = await gate.check({"iteration": 2})

    assert before_limit.action == StopAction.BYPASS
    assert at_next_boundary.action == StopAction.TERMINATE
    assert "Loop time limit" in at_next_boundary.reason


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
