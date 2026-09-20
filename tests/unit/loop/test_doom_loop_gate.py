# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for DoomLoopGate reset behaviour."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.config.config import DoomLoopStageConfig
from qwenpaw.loop.catalog import get_gate_catalog
from qwenpaw.loop.gates.base import StopAction
from qwenpaw.loop.gates.doom_loop import DoomLoopGate


def _stage(after, action="stop", prompt="stop"):
    return DoomLoopStageConfig(
        after=after,
        action=action,
        prompt=prompt,
    )


def test_catalog_create_passes_validated_stage_objects():
    """Catalog factory must hand DoomLoopStageConfig objects to the gate,
    preserving the gate's object-based contract (no dict representation)."""
    gate = get_gate_catalog().create("doom_loop", {})
    assert isinstance(gate, DoomLoopGate)
    assert len(gate._stages) == 2
    for stage in gate._stages:
        assert isinstance(stage, DoomLoopStageConfig)
    # Sorted by .after ascending (catalog default: 3 then 4).
    assert [s.after for s in gate._stages] == [3, 4]


@pytest.mark.asyncio
async def test_catalog_stop_stage_uses_stage_prompt():
    """Catalog-constructed gate drives stop with stage prompt."""
    gate = get_gate_catalog().create("doom_loop", {})
    gate.activate(None)
    gate._ensure_state()

    stop_stage = next(s for s in gate._stages if s.action == "stop")

    # First window of repeated calls triggers the warning stage
    # (consecutive_hits is seeded with window_size on first detection).
    for _ in range(gate._window_size):
        gate.record("tool_a", "hash1")
    warning = await gate.check({"iteration": 0})
    assert warning.action == StopAction.INTERRUPT_AND_CONTINUE

    # Second window escalates to the stop stage (consecutive_hits += 1).
    for _ in range(gate._window_size):
        gate.record("tool_a", "hash1")
    terminal = await gate.check({"iteration": 1})

    assert terminal.action == StopAction.TERMINATE
    assert terminal.reason == stop_stage.prompt


@pytest.mark.asyncio
async def test_text_only_round_does_not_escalate_stale_tool_evidence(gate):
    """A text response cannot advance a retained tool-call repetition."""
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    content=[
                        {
                            "type": "tool_call",
                            "name": "tool_a",
                            "input": {"command": "same"},
                        },
                    ],
                ),
            ],
        ),
    )

    for iteration in range(1, 3):
        result = await gate.check(
            {
                "agent": agent,
                "iteration": iteration,
                "has_tool_calls": True,
            },
        )
        assert result.action == StopAction.BYPASS

    warning = await gate.check(
        {
            "agent": agent,
            "iteration": 3,
            "has_tool_calls": True,
        },
    )
    assert warning.action == StopAction.INTERRUPT_AND_CONTINUE

    agent.state.context = [
        SimpleNamespace(
            content=[{"type": "text", "text": "Done."}],
        ),
    ]
    text_result = await gate.check(
        {
            "agent": agent,
            "iteration": 4,
            "has_tool_calls": False,
            "final_msg": agent.state.context[-1],
        },
    )

    assert text_result.action == StopAction.BYPASS
    assert gate._ensure_state().consecutive_hits == 0
    assert not gate._ensure_state().history


@pytest.mark.asyncio
async def test_rechecking_same_evidence_does_not_advance_stages(gate):
    """Repeated checks of one window are idempotent."""
    for _ in range(3):
        gate.record("tool_a", "hash1")

    warning = await gate.check({"iteration": 0})
    repeated_check = await gate.check({"iteration": 0})

    assert warning.action == StopAction.INTERRUPT_AND_CONTINUE
    assert repeated_check.action == StopAction.BYPASS
    assert gate._ensure_state().consecutive_hits == 3


@pytest.fixture(autouse=True)
def _force_session_id():
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="test-session",
    ):
        yield


@pytest.fixture()
def gate():
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[
            _stage(3, "modify_prompt", "warning"),
            _stage(6, "stop", "doom stop"),
        ],
    )
    g.activate(None)
    g._ensure_state()
    return g


def test_reset_clears_history(gate):
    """reset() empties the history deque."""
    gate.record("tool_a", "hash1")
    gate.record("tool_a", "hash1")
    assert len(gate._ensure_state().history) == 2
    gate.reset_turn()
    assert len(gate._ensure_state().history) == 0


def test_reset_clears_counters(gate):
    """reset() zeroes consecutive_hits and prompt."""
    state = gate._ensure_state()
    state.consecutive_hits = 5
    state.prompt = "some warning"
    state.last_recorded_iter = 10
    gate.reset_turn()
    state = gate._ensure_state()
    assert state.consecutive_hits == 0
    assert state.prompt == ""
    assert state.last_recorded_iter == -1


def test_reset_keeps_gate_active(gate):
    """reset() does NOT deactivate the gate."""
    gate.reset_turn()
    assert gate._state() is not None


@pytest.mark.asyncio
async def test_no_false_positive_after_reset(gate):
    """After reset, fresh calls don't trigger doom loop."""
    for _ in range(3):
        gate.record("tool_a", "hash1")
    gate.reset_turn()
    gate.record("tool_b", "hash2")
    result = await gate.check({"iteration": 0})
    assert result.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_cross_request_no_bleed(gate):
    """Simulates two user requests: reset prevents bleed."""
    for _ in range(3):
        gate.record("search", "abc")

    result = await gate.check({"iteration": 3})
    assert result is not None

    gate.reset_turn()
    gate.record("search", "abc")
    result = await gate.check({"iteration": 1})
    assert result.action == StopAction.BYPASS


def test_reset_when_no_state():
    """reset_turn() is a no-op when gate has no state."""
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[],
    )
    g.reset_turn()


@pytest.mark.asyncio
async def test_session_isolation():
    """reset() only affects current session."""
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[
            _stage(3, "stop", "doom"),
        ],
    )
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s1",
    ):
        g._ensure_state()
        g.record("t", "h")
        g.record("t", "h")

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s2",
    ):
        g._ensure_state()
        g.record("t", "h")

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s1",
    ):
        g.reset_turn()
        assert len(g._state().history) == 0

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s2",
    ):
        assert len(g._state().history) == 1
