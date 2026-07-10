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
    """reset() sets iteration back to 0."""
    for _ in range(3):
        await gate.check({})
    gate.reset()
    state = gate._state()
    assert state is not None
    assert state.iteration == 0


@pytest.mark.asyncio
async def test_reset_preserves_max(gate):
    """reset() keeps max_iterations unchanged."""
    gate.reset()
    state = gate._state()
    assert state.max_iterations == 5


@pytest.mark.asyncio
async def test_reset_allows_full_budget(gate):
    """After reset the full iteration budget is available."""
    for _ in range(3):
        await gate.check({})
    gate.reset()
    for _ in range(4):
        result = await gate.check({})
        assert result.action == StopAction.BYPASS
    result = await gate.check({})
    assert result.action == StopAction.TERMINATE


def test_reset_when_inactive():
    """reset() is a no-op when no session state."""
    g = IterationGate(max_iterations=5)
    g.reset()


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
    """reset() only affects the current session."""
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
        g.reset()
        assert g._state().iteration == 0

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="session-b",
    ):
        assert g._state().iteration == 2
