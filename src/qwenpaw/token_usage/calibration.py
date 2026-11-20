# -*- coding: utf-8 -*-
"""Calibrate the local prompt estimate against provider-reported usage.

AgentScope's default ``count_tokens`` estimates ``utf-8 bytes / 4``. That
materially undercounts prompts dominated by digits, UUIDs, timestamps and
identifiers: Qwen-family tokenizers emit roughly one token per digit, so a
digit-heavy tool result can need 2-4x the estimate. Scroll compares that
estimate against the compaction trigger, so without calibration it keeps a
prompt that the provider already rejects as too long.

Providers report the exact prompt size in their usage block. Pairing that
number with the estimate taken for the same request yields a per-model
correction factor. Calibration is advisory and one-sided: it only scales the
estimate up (1.0-3.0x), so an unknown model, a stale pair, or an auxiliary
call can never lower the safety margin.
"""

from __future__ import annotations

from threading import Lock

_MIN_RATIO = 1.0
_MAX_RATIO = 3.0
# Titles and summaries reuse the same model at a much smaller size; their
# ratio says little about the main prompt.
_MIN_ESTIMATE_TOKENS = 4_096
# Apply a pair only while the live prompt is the same order of magnitude as
# the prompt it was measured on. After compaction the context shrinks and an
# oversized ratio would otherwise fold the recent tail away.
_MIN_PAIR_FRACTION = 0.25

_lock = Lock()
_by_model: dict[str, tuple[int, float]] = {}


def record(model_key: str | None, estimate: int, prompt_tokens: int) -> None:
    """Pair an estimate with the provider's count for the same request."""
    if not model_key or estimate < _MIN_ESTIMATE_TOKENS:
        return
    if not isinstance(prompt_tokens, int) or prompt_tokens <= 0:
        return
    ratio = min(max(prompt_tokens / estimate, _MIN_RATIO), _MAX_RATIO)
    with _lock:
        _by_model[model_key] = (estimate, ratio)


def ratio_for(model_key: str | None, estimate: int) -> float:
    """Return the correction factor to apply to *estimate*."""
    if not model_key or estimate <= 0:
        return 1.0
    with _lock:
        pair = _by_model.get(model_key)
    if pair is None:
        return 1.0
    paired_estimate, ratio = pair
    if paired_estimate < estimate * _MIN_PAIR_FRACTION:
        return 1.0
    return ratio


def clear() -> None:
    """Drop all pairs (tests and session teardown)."""
    with _lock:
        _by_model.clear()
