# -*- coding: utf-8 -*-
"""Estimate model spend without exporting responses or credentials."""

import contextlib
import io
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import TypeGuard

from litellm import completion_cost

from .common import digest


def amount(value) -> TypeGuard[int | float]:
    """Accept finite nonnegative numbers, including an explicit zero."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def tokens(value) -> TypeGuard[int]:
    """Reject booleans, negative values and fractional token counts."""
    return type(value) is int and value >= 0


def acp_usage(output: Path, model: str) -> dict | None:
    """Sum QwenPaw's consumed usage chunks, not context occupancy updates."""
    paths = list(output.rglob(f"acp-events.jsonl"))
    if len(paths) != 1:
        return None
    inputs, outputs, chunks, cached = 0, 0, 0, 0
    complete_cache = True
    with paths[0].open(encoding=f"utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return None
            if event.get(f"event_type") != f"session_update":
                continue
            update = (event.get(f"payload") or {}).get(f"update") or {}
            if update.get(f"sessionUpdate") != f"agent_message_chunk":
                continue
            usage = (update.get(f"_meta") or {}).get(f"usage")
            if not usage:
                continue
            prompt = usage.get(f"inputTokens")
            completion = usage.get(f"outputTokens")
            if (
                not tokens(prompt)
                or not tokens(completion)
                or usage.get(f"model") not in (None, f"", model)
            ):
                return None
            read = usage.get(f"cacheReadTokens")
            write = usage.get(f"cacheWriteTokens")
            eligible = usage.get(f"cacheEligibleInputTokens")
            observed = usage.get(f"cacheUsageComplete") is True
            if observed:
                if (
                    not tokens(read)
                    or not tokens(write)
                    or not tokens(eligible)
                    or read + write > eligible
                    or write > 0
                ):
                    return None
                prompt = eligible
                cached += read
            complete_cache = complete_cache and observed
            inputs += prompt
            outputs += completion
            chunks += 1
    if not chunks:
        return None
    return {
        f"n_input_tokens": inputs,
        f"n_output_tokens": outputs,
        f"n_cache_tokens": cached if complete_cache else None,
    }


def estimate(usage: dict, model: str, prices: dict) -> dict:
    """Use pinned rates with LiteLLM, then an independent decimal fallback."""
    result: dict = {
        f"amount_usd": None,
        f"amount_cny": None,
        f"source": f"unknown",
        f"basis": f"unknown",
        f"price_sha256": digest(prices),
    }
    rate = prices[f"models"].get(model)
    prompt = usage.get(f"n_input_tokens")
    output = usage.get(f"n_output_tokens")
    cache = usage.get(f"n_cache_tokens")
    if not rate or not tokens(prompt) or not tokens(output):
        return result
    if cache is not None and (not tokens(cache) or cache > prompt):
        return result
    cached = cache if cache is not None else 0
    divisor = Decimal(str(prices[f"unit_tokens"]))
    cny = (
        Decimal(prompt - cached) * Decimal(str(rate[f"input"]))
        + Decimal(cached) * Decimal(str(rate[f"cache"]))
        + Decimal(output) * Decimal(str(rate[f"output"]))
    ) / divisor
    fx = Decimal(str(prices[f"fx"][f"cny_per_usd"]))
    fallback = float(cny / fx)
    value = None
    response = {
        f"model": model,
        f"usage": {
            f"prompt_tokens": prompt,
            f"completion_tokens": output,
            f"total_tokens": prompt + output,
            f"prompt_tokens_details": {f"cached_tokens": cached},
        },
    }
    rates = {
        f"input_cost_per_token": float(
            Decimal(str(rate[f"input"])) / divisor / fx,
        ),
        f"output_cost_per_token": float(
            Decimal(str(rate[f"output"])) / divisor / fx,
        ),
        f"cache_read_input_token_cost": float(
            Decimal(str(rate[f"cache"])) / divisor / fx,
        ),
    }
    try:
        # Only numeric usage enters LiteLLM; discard library diagnostics.
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                value = completion_cost(
                    completion_response=response,
                    model=model,
                    custom_llm_provider=f"openai",
                    custom_cost_per_token=rates,
                )
    except Exception:  # pylint: disable=broad-exception-caught
        value = None
    valid = amount(value) and math.isclose(
        value,
        fallback,
        rel_tol=1e-8,
        abs_tol=1e-12,
    )
    result.update(
        amount_usd=value if valid else fallback,
        amount_cny=float(cny),
        source=f"litellm_estimated" if valid else f"snapshot_estimated",
        basis=(
            f"upper_bound"
            if cache is None or rate[f"basis"] == f"peak_upper_bound"
            else f"list_price"
        ),
    )
    return result


def attach(receipt: dict, data: dict, output: Path) -> None:
    """Keep reported cost and estimation separate; never add them together."""
    usage = receipt[f"usage"]
    receipt[f"usage_source"] = f"harbor"
    if receipt[f"harness"] == f"QwenPaw" and not all(
        tokens(usage.get(key))
        for key in (f"n_input_tokens", f"n_output_tokens")
    ):
        recovered = acp_usage(output, receipt[f"model_id"])
        if recovered is not None:
            receipt[f"usage"] = recovered
            receipt[f"usage_source"] = f"qwenpaw_acp_meta"
    estimated = estimate(
        receipt[f"usage"],
        receipt[f"model_id"],
        data[f"prices"],
    )
    receipt[f"cost_estimate"] = estimated
    reported = receipt[f"model_cost_usd"]
    receipt[f"reported_model_cost_usd"] = reported
    if not amount(reported):
        receipt[f"model_cost_usd"] = estimated[f"amount_usd"]
        receipt[f"cost_source"] = estimated[f"source"]
    receipt[f"cost_basis"] = (
        f"reported" if amount(reported) else estimated[f"basis"]
    )
