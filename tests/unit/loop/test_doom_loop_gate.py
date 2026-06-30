# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DoomLoopGate multi-stage escalation."""
import pytest

from qwenpaw.config.config import (
    DoomLoopConfig,
    DoomLoopStageConfig,
)
from qwenpaw.loop.doom_loop import (
    DoomLoopDetector,
)
from qwenpaw.loop.gates import (
    DoomLoopGate,
    StopAction,
    StopHandler,
)


class TestDoomLoopGate:
    """Multi-stage DoomLoopGate tests."""

    def _make_gate(self, stages=None):
        detector = DoomLoopDetector(
            window_size=3,
            similarity_threshold=0.8,
        )
        if stages is None:
            stages = [
                DoomLoopStageConfig(
                    after=2,
                    action="modify_prompt",
                    prompt="Try differently",
                ),
                DoomLoopStageConfig(
                    after=4,
                    action="stop",
                    prompt="Agent stuck",
                ),
            ]
        return (
            DoomLoopGate(
                detector=detector,
                stages=stages,
            ),
            detector,
        )

    @pytest.mark.asyncio()
    async def test_no_doom_returns_none(self):
        gate, detector = self._make_gate()
        detector.record("tool_a", "h1", True)
        detector.record("tool_b", "h2", True)
        detector.record("tool_c", "h3", True)
        result = await gate.check({})
        assert result is None
        assert gate.continuation_prompt() == ""

    @pytest.mark.asyncio()
    async def test_stage1_warning(self):
        gate, detector = self._make_gate()
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)

        await gate.check({})
        assert gate._consecutive_hits == 1
        assert gate.continuation_prompt() == ""

        await gate.check({})
        assert gate._consecutive_hits == 2
        assert gate.continuation_prompt() == "Try differently"

    @pytest.mark.asyncio()
    async def test_stage2_stop(self):
        gate, detector = self._make_gate()
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)

        for _ in range(3):
            result = await gate.check({})
            assert result is None

        result = await gate.check({})
        assert result is not None
        assert result.action == StopAction.STOP
        assert "stuck" in result.reason.lower()

    @pytest.mark.asyncio()
    async def test_reset_on_ok(self):
        gate, detector = self._make_gate()
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)

        await gate.check({})
        await gate.check({})
        assert gate._consecutive_hits == 2

        detector.record("tool_b", "h2", True)
        detector.record("tool_c", "h3", True)
        detector.record("tool_d", "h4", True)
        await gate.check({})
        assert gate._consecutive_hits == 0
        assert gate.continuation_prompt() == ""

    @pytest.mark.asyncio()
    async def test_warning_in_stop_handler(self):
        gate, detector = self._make_gate()
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)

        handler = StopHandler()
        handler.register(gate)
        handler.set_continuation(
            lambda ctx: "base message",
        )

        await handler({})
        result = await handler({})
        assert result.action == StopAction.CONTINUE
        assert "Try differently" in (result.continuation_message)
        assert "base message" in (result.continuation_message)

    @pytest.mark.asyncio()
    async def test_three_stages(self):
        stages = [
            DoomLoopStageConfig(
                after=1,
                action="modify_prompt",
                prompt="Mild warning",
            ),
            DoomLoopStageConfig(
                after=3,
                action="modify_prompt",
                prompt="Strong warning",
            ),
            DoomLoopStageConfig(
                after=5,
                action="stop",
                prompt="Final stop",
            ),
        ]
        gate, detector = self._make_gate(stages)
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)
        detector.record("tool_a", "h1", True)

        await gate.check({})
        assert gate.continuation_prompt() == "Mild warning"

        await gate.check({})
        await gate.check({})
        assert gate.continuation_prompt() == "Strong warning"

        await gate.check({})
        assert gate.continuation_prompt() == "Strong warning"

        result = await gate.check({})
        assert result is not None
        assert result.action == StopAction.STOP


class TestDoomLoopConfig:
    """DoomLoopConfig model tests."""

    def test_defaults(self):
        cfg = DoomLoopConfig()
        assert cfg.enabled is True
        assert cfg.window_size == 5
        assert len(cfg.stages) == 2
        assert cfg.stages[0].after == 3
        assert cfg.stages[1].action == "stop"

    def test_custom(self):
        cfg = DoomLoopConfig(
            enabled=False,
            window_size=10,
            stages=[
                DoomLoopStageConfig(
                    after=5,
                    action="stop",
                    prompt="halt",
                ),
            ],
        )
        assert not cfg.enabled
        assert len(cfg.stages) == 1
