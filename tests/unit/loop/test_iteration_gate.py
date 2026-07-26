# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for IterationGate reset behaviour."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.base import StopAction
from qwenpaw.loop.gates.iteration import IterationGate


@pytest.fixture(autouse=True)
def _force_session_id():
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="test-session",
    ):
        yield


@pytest.fixture()
def gate():
    g = IterationGate(max_iterations=5)
    g.activate()
    return g


@pytest.mark.asyncio
async def test_check_increments(gate):
    """check() increments the counter each call."""
    for _ in range(4):
        result = await gate.check({})
        assert result.action == StopAction.BYPASS
    result = await gate.check({})
    assert result.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_reset_clears_counter(gate):
    """reset_turn() sets iteration back to 0."""
    for _ in range(3):
        await gate.check({})
    gate.reset_turn()
    state = gate._state()
    assert state is not None
    assert state.iteration == 0


@pytest.mark.asyncio
async def test_reset_preserves_max(gate):
    """reset_turn() keeps max_iterations unchanged."""
    gate.reset_turn()
    state = gate._state()
    assert state.max_iterations == 5


@pytest.mark.asyncio
async def test_reset_allows_full_budget(gate):
    """After reset the full iteration budget is available."""
    for _ in range(3):
        await gate.check({})
    gate.reset_turn()
    for _ in range(4):
        result = await gate.check({})
        assert result.action == StopAction.BYPASS
    result = await gate.check({})
    assert result.action == StopAction.TERMINATE


def test_reset_when_inactive():
    """reset_turn() activates a fresh session state."""
    g = IterationGate(max_iterations=5)
    g.reset_turn()
    assert g._state() is not None


@pytest.fixture()
def gate_pair():
    """Instance with state in two sessions."""
    g = IterationGate(max_iterations=5)
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-a",
    ):
        g.activate()
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        g.activate()
    return g


@pytest.mark.asyncio
async def test_reset_session_isolation(gate_pair):
    """reset_turn() only affects the current session."""
    g = gate_pair
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-a",
    ):
        for _ in range(3):
            await g.check({})

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        for _ in range(2):
            await g.check({})

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-a",
    ):
        g.reset_turn()
        assert g._state().iteration == 0

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        assert g._state().iteration == 2


def test_reset_session_removes_only_current_session(gate_pair):
    """reset_session() removes only the current conversation state."""
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-a",
    ):
        gate_pair.reset_session()
        assert gate_pair._state() is None

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        assert gate_pair._state() is not None
