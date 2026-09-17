# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for DoomLoopGate reset behaviour."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.base import StopAction
from qwenpaw.loop.gates.doom_loop import DoomLoopGate


def _stage(after, action="stop", prompt="stop"):
    return SimpleNamespace(
        after=after,
        action=action,
        prompt=prompt,
    )


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
