# -*- coding: utf-8 -*-
"""Verify cost fallback, cache accounting and safe ACP extraction."""

import json
from pathlib import Path

import pytest

from scripts.bench import cost
from scripts.bench.common import load


@pytest.fixture(name=f"prices")
def prices_fixture():
    return load(Path(f".github/bench/prices.yaml"))


def usage(cache=400):
    return {
        f"n_input_tokens": 1000,
        f"n_output_tokens": 100,
        f"n_cache_tokens": cache,
    }


def test_real_litellm_cache_pricing(prices):
    result = cost.estimate(usage(), f"qwen3.8-27b", prices)
    assert result[f"source"] == f"litellm_estimated"
    assert result[f"amount_cny"] == pytest.approx(0.00324)
    assert result[f"amount_usd"] == pytest.approx(0.00324 / 6.7351)
    assert result[f"basis"] == f"list_price"


@pytest.mark.parametrize(f"bad", [None, float(f"nan"), -1, 0])
def test_invalid_litellm_result_uses_snapshot(monkeypatch, prices, bad):
    monkeypatch.setattr(cost, f"completion_cost", lambda **kw: bad)
    result = cost.estimate(usage(), f"qwen3.8-27b", prices)
    assert result[f"source"] == f"snapshot_estimated"
    assert result[f"amount_usd"] == pytest.approx(0.00324 / 6.7351)


def test_litellm_exception_uses_snapshot(monkeypatch, prices):
    def fail(**kwargs):
        raise ValueError(f"Unsupported model")

    monkeypatch.setattr(cost, f"completion_cost", fail)
    result = cost.estimate(usage(), f"qwen3.8-27b", prices)
    assert result[f"source"] == f"snapshot_estimated"


def test_unknown_cache_and_peak_prices_are_upper_bounds(prices):
    result = cost.estimate(usage(None), f"qwen3.8-27b", prices)
    assert result[f"amount_cny"] == pytest.approx(0.0042)
    assert result[f"basis"] == f"upper_bound"
    result = cost.estimate(usage(), f"deepseek-v4.1-flash", prices)
    assert result[f"basis"] == f"upper_bound"


@pytest.mark.parametrize(
    f"field,value",
    [
        (f"n_input_tokens", None),
        (f"n_input_tokens", True),
        (f"n_output_tokens", -1),
        (f"n_cache_tokens", 1001),
    ],
)
def test_invalid_usage_stays_unknown(prices, field, value):
    data = usage()
    data[field] = value
    assert cost.estimate(data, f"qwen3.8-27b", prices)[f"source"] == f"unknown"


def test_reasoning_not_added_twice(prices):
    data = usage()
    data[f"reasoning_tokens"] = 70
    assert cost.estimate(data, f"qwen3.8-27b", prices)[
        f"amount_cny"
    ] == pytest.approx(0.00324)


def event(prompt=100, complete=True):
    return {
        f"event_type": f"session_update",
        f"payload": {
            f"update": {
                f"sessionUpdate": f"agent_message_chunk",
                f"_meta": {
                    f"usage": {
                        f"model": f"qwen3.8-27b",
                        f"inputTokens": prompt,
                        f"outputTokens": 10,
                        f"cacheReadTokens": 40,
                        f"cacheWriteTokens": 0,
                        f"cacheEligibleInputTokens": prompt,
                        f"cacheUsageComplete": complete,
                    },
                },
            },
        },
    }


def test_acp_sums_consumed_chunks_ignores_context(tmp_path):
    context = {
        f"event_type": f"session_update",
        f"payload": {
            f"update": {
                f"sessionUpdate": f"usage_update",
                f"used": 999999,
            },
        },
    }
    path = tmp_path / f"acp-events.jsonl"
    path.write_text(f"\n".join(map(json.dumps, [event(), context, event()])))
    assert cost.acp_usage(tmp_path, f"qwen3.8-27b") == {
        f"n_input_tokens": 200,
        f"n_output_tokens": 20,
        f"n_cache_tokens": 80,
    }
    path.write_text(f"\n".join(map(json.dumps, [event(), event(100, False)])))
    assert cost.acp_usage(tmp_path, f"qwen3.8-27b")[f"n_cache_tokens"] is None


def test_reported_zero_has_priority(tmp_path, prices):
    receipt = {
        f"harness": f"QwenPaw",
        f"usage": usage(),
        f"model_id": f"qwen3.8-27b",
        f"model_cost_usd": 0,
        f"cost_source": f"harbor_reported",
    }
    cost.attach(receipt, {f"prices": prices}, tmp_path)
    assert receipt[f"model_cost_usd"] == 0
    assert receipt[f"cost_basis"] == f"reported"
    assert receipt[f"cost_estimate"][f"amount_usd"] > 0
