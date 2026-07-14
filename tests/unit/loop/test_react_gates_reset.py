# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for register_react_gates new-turn reset."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.handler import StopHandler
from qwenpaw.loop.react_gates import (
    _reset_gates_for_new_turn,
    register_react_gates,
)


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


def test_first_call_registers_gates():
    """First call registers gates on workspace."""
    ws = _workspace()
    cfg = _running_config()
    handler = register_react_gates(ws, cfg)
    assert isinstance(handler, StopHandler)
    assert len(handler.gates) >= 2
    assert ws._react_gates_registered is True


@pytest.mark.asyncio
async def test_second_call_resets_iteration():
    """Second call resets IterationGate counter."""
    ws = _workspace()
    cfg = _running_config(max_iters=10)
    handler = register_react_gates(ws, cfg)

    from qwenpaw.loop.gates.iteration import (
        IterationGate,
    )

    iter_gate = None
    for g in handler.gates:
        if isinstance(g, IterationGate):
            iter_gate = g
            break
    assert iter_gate is not None

    for _ in range(5):
        await iter_gate.check({})
    assert iter_gate._state().iteration == 5

    register_react_gates(ws, cfg)
    assert iter_gate._state().iteration == 0


@pytest.mark.asyncio
async def test_second_call_resets_doom_loop():
    """Second call resets DoomLoopGate history."""
    ws = _workspace()
    cfg = _running_config()
    handler = register_react_gates(ws, cfg)

    from qwenpaw.loop.gates.doom_loop import (
        DoomLoopGate,
    )

    doom_gate = None
    for g in handler.gates:
        if isinstance(g, DoomLoopGate):
            doom_gate = g
            break
    assert doom_gate is not None

    doom_gate.record("tool_a", "h1")
    doom_gate.record("tool_a", "h1")
    assert len(doom_gate._ensure_state().history) == 2

    register_react_gates(ws, cfg)
    assert len(doom_gate._ensure_state().history) == 0


def test_reset_gates_for_new_turn_helper():
    """_reset_gates_for_new_turn calls reset on all."""
    from qwenpaw.loop.gates.base import StopGate

    class _Tracked(StopGate):
        def __init__(self):
            self.was_reset = False

        @property
        def name(self):
            return "tracked"

        async def check(self, ctx):
            return None

        def reset(self):
            self.was_reset = True

    handler = StopHandler()
    g1 = _Tracked()
    g2 = _Tracked()
    handler.register(g1)
    handler.register(g2)

    _reset_gates_for_new_turn(handler)
    assert g1.was_reset
    assert g2.was_reset
