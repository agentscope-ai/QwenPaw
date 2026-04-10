# -*- coding: utf-8 -*-
"""Tests for LearningSignalAccumulator."""
import pytest

from copaw.app.learning.signal_accumulator import (
    LearningSignalAccumulator,
    LearningSignals,
)
from copaw.config.config import SignalWeightsConfig


class TestLearningSignals:
    def test_weighted_score_defaults(self):
        signals = LearningSignals(
            tool_calls=10,
            error_recoveries=1,
            user_corrections=1,
        )
        weights = SignalWeightsConfig()  # 1, 3, 5
        assert signals.weighted_score(weights) == 10 + 3 + 5

    def test_weighted_score_custom(self):
        signals = LearningSignals(
            tool_calls=5,
            error_recoveries=2,
            user_corrections=0,
        )
        weights = SignalWeightsConfig(
            tool_call=2,
            error_recovery=10,
            user_correction=5,
        )
        assert signals.weighted_score(weights) == 10 + 20 + 0

    def test_empty_signals(self):
        signals = LearningSignals()
        weights = SignalWeightsConfig()
        assert signals.weighted_score(weights) == 0


class TestLearningSignalAccumulator:
    def test_record_and_snapshot(self):
        acc = LearningSignalAccumulator()
        acc.record_tool_calls(3)
        acc.record_tool_calls(2)
        snap = acc.snapshot()
        assert snap.tool_calls == 5
        assert snap.error_recoveries == 0

    def test_error_recovery_detection(self):
        acc = LearningSignalAccumulator()
        # First iteration: tool A fails
        acc.record_tool_calls(
            1,
            tool_names=["shell"],
            any_error=True,
        )
        # Second iteration: different tool (recovery)
        acc.record_tool_calls(
            1,
            tool_names=["read_file"],
            any_error=False,
        )
        snap = acc.snapshot()
        assert snap.error_recoveries == 1

    def test_no_recovery_same_tool(self):
        acc = LearningSignalAccumulator()
        acc.record_tool_calls(
            1,
            tool_names=["shell"],
            any_error=True,
        )
        # Same tool retried — not a recovery
        acc.record_tool_calls(
            1,
            tool_names=["shell"],
            any_error=False,
        )
        snap = acc.snapshot()
        assert snap.error_recoveries == 0

    def test_user_correction(self):
        acc = LearningSignalAccumulator()
        acc.record_user_correction()
        acc.record_user_correction()
        snap = acc.snapshot()
        assert snap.user_corrections == 2

    def test_reset(self):
        acc = LearningSignalAccumulator()
        acc.record_tool_calls(5)
        acc.record_user_correction()
        acc.reset()
        snap = acc.snapshot()
        assert snap.tool_calls == 0
        assert snap.user_corrections == 0

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("不对，换个方式", True),
            ("错了，应该用另一个", True),
            ("wrong, try something else", True),
            ("no, don't do that", True),
            ("actually, use X instead", True),
            ("好的，继续", False),
            ("谢谢", False),
            ("looks good", False),
            ("", False),
        ],
    )
    def test_is_user_correction(self, text, expected):
        assert (
            LearningSignalAccumulator.is_user_correction(text) == expected
        )
