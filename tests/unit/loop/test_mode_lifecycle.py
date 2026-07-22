# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for mode-owned handler selection and reset lifecycle."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.base import (
    StopAction,
    StopHandlerRegistration,
)
from qwenpaw.loop.gates.handler import StopHandler
from qwenpaw.loop.gates.rubric import QualitativeRubricGate
from qwenpaw.loop.gates.runner import _filter_by_scope
from qwenpaw.modes.goal.goal_mode import GoalMode, GoalSession
from qwenpaw.modes.mission import MissionMode
from qwenpaw.modes.mission.gates import MissionGate
from qwenpaw.modes.mission.state import write_loop_config
from qwenpaw.runtime.runtime import Runtime


def _registration(
    scope: str,
    *,
    is_active=None,
) -> StopHandlerRegistration:
    return StopHandlerRegistration(
        plugin_id=f"test-{scope}",
        handler=StopHandler(),
        name=f"{scope}-handler",
        scope=scope,
        is_active=is_active,
    )


def test_explicit_mode_scope_replaces_default_scope():
    """An active mode handler suppresses the default handler."""
    default = _registration("default")
    goal = _registration("goal", is_active=lambda: True)

    selected = _filter_by_scope([default, goal])

    assert selected == [goal]


def test_inactive_mode_scope_keeps_default_scope():
    """An inactive mode handler leaves the default handler selected."""
    default = _registration("default")
    goal = _registration("goal", is_active=lambda: False)

    selected = _filter_by_scope([default, goal])

    assert selected == [default]


def test_unscoped_plugin_handler_is_always_selected():
    """Unscoped plugin handlers remain available with explicit modes."""
    plugin = _registration("")
    default = _registration("default")
    goal = _registration("goal", is_active=lambda: True)

    selected = _filter_by_scope([plugin, default, goal])

    assert selected == [plugin, goal]


@pytest.mark.asyncio
async def test_goal_reset_removes_only_current_session():
    """Conversation reset does not clear another goal conversation."""
    mode = GoalMode()
    mode._sessions["session-a"] = GoalSession(goal="first")
    mode._sessions["session-b"] = GoalSession(goal="second")
    ctx = SimpleNamespace(session_id="session-a")

    await mode.on_conversation_reset(ctx)

    assert "session-a" not in mode._sessions
    assert "session-b" in mode._sessions


@pytest.mark.asyncio
async def test_goal_activation_rejects_an_active_explicit_mode():
    """A persistent session mode must be exited before another starts."""
    mode = GoalMode()
    active = SimpleNamespace(
        name="mission",
        is_active=lambda _ctx: True,
    )
    ctx = SimpleNamespace(
        session_id="session-a",
        workspace=SimpleNamespace(
            plugins=SimpleNamespace(modes=[active, mode]),
        ),
    )

    response = await mode.commands()[0].handler(ctx, "Fix the tests")

    assert response is not None
    assert "active mission mode" in response.content[0].text
    assert mode.get_session("session-a") is None


@pytest.mark.asyncio
async def test_mission_turn_start_restores_persisted_session(tmp_path):
    """Mission state is active before stop-handler scope selection."""
    mode = MissionMode()
    mode._gate = MissionGate()
    ctx = SimpleNamespace(
        mode_state={
            "mission": {
                "active": True,
                "loop_dir": str(tmp_path),
                "phase": "execution",
            },
        },
    )

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="mission-session",
    ):
        await mode.on_turn_start(ctx)
        assert mode._is_gate_active()


@pytest.mark.asyncio
async def test_mission_state_uses_session_lifecycle_and_reset(tmp_path):
    """Stage 1 phase persists and reset clears the same mode_state."""
    write_loop_config(
        tmp_path,
        {"current_phase": "prd_generation"},
    )
    mode = MissionMode()
    mode._gate = MissionGate()
    ctx = SimpleNamespace(mode_state={})

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="mission-session",
    ):
        mode._gate.activate_for_mission(tmp_path)
        await mode.sync_persistent_state(ctx)

        assert ctx.mode_state == {
            "mission": {
                "active": True,
                "loop_dir": str(tmp_path),
                "phase": "prd_generation",
            },
        }

        write_loop_config(
            tmp_path,
            {"current_phase": "execution_confirmed"},
        )
        await mode.sync_persistent_state(ctx)

        assert ctx.mode_state["mission"]["phase"] == "execution_confirmed"

        await mode.on_conversation_reset(ctx)

        assert ctx.mode_state == {}
        assert not mode._is_gate_active()


@pytest.mark.asyncio
async def test_runtime_awaits_mode_turn_start_callbacks():
    """Runtime awaits each registered mode turn-start callback."""
    calls = []

    class _Mode:
        name = "test"

        async def on_turn_start(self, ctx):
            calls.append(ctx)

    workspace = SimpleNamespace(
        plugins=SimpleNamespace(modes=[_Mode()]),
    )
    runtime = Runtime(workspace=workspace, app_services=None)
    ctx = SimpleNamespace()

    await runtime._start_modes(ctx)

    assert calls == [ctx]


@pytest.mark.asyncio
async def test_qualitative_rubric_state_is_session_isolated():
    """Resetting one rubric session leaves another session untouched."""
    gate = QualitativeRubricGate(
        rubric="continue",
        max_evaluations=1,
    )

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-a",
    ):
        first_a = await gate.check({})

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        first_b = await gate.check({})

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-a",
    ):
        gate.reset_session()
        next_a = await gate.check({})

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        next_b = await gate.check({})

    assert first_a.action == StopAction.INTERRUPT_AND_CONTINUE
    assert first_b.action == StopAction.INTERRUPT_AND_CONTINUE
    assert next_a.action == StopAction.INTERRUPT_AND_CONTINUE
    assert next_b.action == StopAction.BYPASS
