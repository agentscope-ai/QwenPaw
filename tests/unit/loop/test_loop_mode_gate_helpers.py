# -*- coding: utf-8 -*-
"""Tests for loop gates shared by explicit loop modes."""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.loop.gates.doom_loop import DoomLoopGate
from qwenpaw.loop.gates.rubric import QualitativeRubricGate
from qwenpaw.modes.goal.helpers import (
    create_completion_gate,
    create_doom_loop_gate,
)


def _workspace(
    *,
    doom_enabled: bool = True,
    doom_in_loop_modes: bool = True,
    rubric_enabled: bool = True,
    rubric_in_loop_modes: bool = True,
    include_config: bool = True,
) -> SimpleNamespace:
    doom_loop = SimpleNamespace(
        enabled=doom_enabled,
        in_loop_modes=doom_in_loop_modes,
        window_size=3,
        similarity_threshold=1.0,
        stages=[
            SimpleNamespace(
                after=3,
                action="stop",
                prompt="doom",
            ),
        ],
    )
    rubric = SimpleNamespace(
        enabled=rubric_enabled,
        in_loop_modes=rubric_in_loop_modes,
        prompt="continue",
        max_interventions=1,
    )
    config = SimpleNamespace(
        running=SimpleNamespace(
            loop=SimpleNamespace(
                doom_loop=doom_loop,
                rubric=rubric,
            ),
        ),
    )
    if include_config:
        return SimpleNamespace(config=config)
    return SimpleNamespace()


def test_create_doom_loop_gate_requires_enabled_in_loop_config() -> None:
    """Doom gate requires workspace config and in-loop opt-in."""
    assert create_doom_loop_gate(SimpleNamespace()) is None
    assert (
        create_doom_loop_gate(
            _workspace(include_config=False),
        )
        is None
    )
    assert (
        create_doom_loop_gate(
            _workspace(doom_enabled=False),
        )
        is None
    )
    assert (
        create_doom_loop_gate(
            _workspace(doom_in_loop_modes=False),
        )
        is None
    )

    gate = create_doom_loop_gate(_workspace())

    assert isinstance(gate, DoomLoopGate)


def test_create_completion_gate_requires_enabled_in_loop_config() -> None:
    """Completion gate requires workspace config and in-loop opt-in."""
    assert create_completion_gate(SimpleNamespace()) is None
    assert (
        create_completion_gate(
            _workspace(include_config=False),
        )
        is None
    )
    assert (
        create_completion_gate(
            _workspace(rubric_enabled=False),
        )
        is None
    )
    assert (
        create_completion_gate(
            _workspace(rubric_in_loop_modes=False),
        )
        is None
    )

    gate = create_completion_gate(_workspace())

    assert isinstance(gate, QualitativeRubricGate)
