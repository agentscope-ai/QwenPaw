# -*- coding: utf-8 -*-
"""Tests for provider-driven prompt-token calibration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock
from agentscope.model import ChatResponse
from agentscope.model._model_usage import ChatUsage

from qwenpaw.agents.context import _as_internals
from qwenpaw.token_usage import calibration
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


@pytest.fixture(autouse=True)
def _clean_calibration():
    calibration.clear()
    yield
    calibration.clear()


def test_ratio_scales_digit_heavy_prompts_up():
    calibration.record("local:qwen", 10_000, 14_200)

    assert calibration.ratio_for("local:qwen", 9_000) == pytest.approx(1.42)


def test_ratio_never_scales_down():
    calibration.record("local:qwen", 10_000, 6_000)

    assert calibration.ratio_for("local:qwen", 10_000) == 1.0


def test_ratio_is_clamped_to_three():
    calibration.record("local:qwen", 10_000, 40_000)

    assert calibration.ratio_for("local:qwen", 10_000) == 3.0


def test_small_estimates_are_ignored():
    calibration.record("local:qwen", 4_095, 8_000)

    assert calibration.ratio_for("local:qwen", 4_095) == 1.0


def test_unknown_model_is_identity():
    assert calibration.ratio_for(None, 100_000) == 1.0
    assert calibration.ratio_for("other:model", 100_000) == 1.0


def test_much_smaller_auxiliary_pair_is_not_applied():
    calibration.record("local:qwen", 20_000, 34_000)

    assert calibration.ratio_for("local:qwen", 100_000) == 1.0


def test_larger_pair_still_applies_after_compaction():
    calibration.record("local:qwen", 60_000, 90_000)

    assert calibration.ratio_for("local:qwen", 15_000) == pytest.approx(1.5)


class _CountingModel:
    model_key = "local:qwen"

    async def count_tokens(self, **kwargs):
        return 10_000


class _Agent:
    model = _CountingModel()


class _UnkeyedModel:
    async def count_tokens(self, **kwargs):
        return 10_000


class _UnkeyedAgent:
    model = _UnkeyedModel()


async def test_count_helper_applies_calibration():
    calibration.record("local:qwen", 10_000, 14_000)

    tokens = await _as_internals.count_model_input_tokens(
        _Agent(),
        {"messages": [], "tools": []},
    )

    assert tokens == 14_000


async def test_count_helper_without_model_key_is_identity():
    tokens = await _as_internals.count_model_input_tokens(
        _UnkeyedAgent(),
        {"messages": [], "tools": []},
    )

    assert tokens == 10_000


class _RecordingInnerModel:
    def __init__(self, estimate: int, prompt_tokens: int) -> None:
        self.model = "qwen"
        self.credential = None
        self.parameters = SimpleNamespace()
        self.stream = True
        self.context_size = 131_072
        self.formatter = None
        self._estimate = estimate
        self._usage = ChatUsage(
            input_tokens=prompt_tokens,
            output_tokens=10,
            time=0.0,
        )

    async def count_tokens(self, messages, tools):
        return self._estimate

    async def __call__(self, **kwargs):
        return ChatResponse(
            content=[TextBlock(type="text", text="ok")],
            is_last=True,
            usage=self._usage,
        )


async def test_wrapper_pairs_usage_with_its_own_estimate(monkeypatch):
    captured: list = []
    monkeypatch.setattr(
        "qwenpaw.token_usage.model_wrapper.get_token_usage_manager",
        lambda: SimpleNamespace(enqueue=captured.append),
    )

    wrapper = TokenRecordingModelWrapper(
        "local",
        _RecordingInnerModel(estimate=5_000, prompt_tokens=7_000),
    )
    await wrapper(messages=["m"])

    # The wrapper pairs the estimate taken for this exact request with the
    # provider's count, so the next Scroll decision is in provider tokens.
    assert calibration.ratio_for("local:qwen", 5_000) == pytest.approx(1.4)
    assert captured
