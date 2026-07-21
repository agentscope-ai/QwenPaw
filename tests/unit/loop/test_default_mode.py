# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DefaultMode gate ownership and lifecycle."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.doom_loop import DoomLoopGate
from qwenpaw.loop.gates.iteration import IterationGate
from qwenpaw.modes.default import DefaultMode


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
    agent = SimpleNamespace(
        _gate_pending_stop=object(),
        _gate_pending_continue="continue",
    )
    mode = DefaultMode()
    await mode.on_turn_start(_context(_running_config(), agent))
    iteration = _find_gate(mode, IterationGate)

    mode.on_conversation_reset(_context(_running_config(), agent))

    assert iteration._state() is None
    assert agent._gate_pending_stop is None
    assert agent._gate_pending_continue is None
