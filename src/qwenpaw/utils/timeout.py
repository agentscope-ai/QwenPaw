# -*- coding: utf-8 -*-
"""Shared positive-timeout parsing for tool args and console chat tasks."""
from __future__ import annotations

import math
import sys
from typing import Any

from qwenpaw.constant import DEFAULT_STREAM_TASK_TIMEOUT_SECONDS

# asyncio.sleep converts its delay to float. Integers above this (e.g.
# 10**1000) raise OverflowError in the timeout guard and leave the task
# unbounded. Keep ints exact below this ceiling so 2**53+1 still echoes.
MAX_STREAM_TASK_TIMEOUT_SECONDS = int(sys.float_info.max)


def _ensure_sleepable_timeout(seconds: int, err: str) -> None:
    """Reject values that asyncio.sleep cannot use as a finite delay."""
    if seconds > MAX_STREAM_TASK_TIMEOUT_SECONDS:
        raise ValueError(err)
    try:
        as_float = float(seconds)
    except OverflowError as exc:
        raise ValueError(err) from exc
    if not math.isfinite(as_float):
        raise ValueError(err)


def parse_positive_timeout_seconds(
    value: Any,
    *,
    field_name: str = "timeout",
) -> int:
    """Parse a required timeout value to positive ``int`` seconds.

    Accepts ``int`` / ``float`` / numeric strings (LLM mis-serialization).
    Rejects ``None``, bools, non-numeric values, non-positive timeouts, and
    values that overflow ``asyncio.sleep`` (non-finite / too large to convert
    to float). Does not apply a default — callers decide what ``None`` means.
    Integers that pass are returned exactly, not coerced through float.
    """
    err = (
        f"'{field_name}' must be a positive number (seconds), "
        f"got {value!r}"
    )
    # bool is an int subclass — do not treat True/False as 1/0 seconds.
    if isinstance(value, bool):
        raise ValueError(err)
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(err)
        _ensure_sleepable_timeout(value, err)
        return value
    if isinstance(value, float):
        as_float = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(err)
        try:
            as_float = float(text)
        except (ValueError, OverflowError) as exc:
            raise ValueError(err) from exc
    else:
        raise ValueError(err)
    if not math.isfinite(as_float):
        raise ValueError(err)
    # Truncation can turn (0, 1) into 0 — reject after int(), not before.
    as_int = int(as_float)
    if as_int <= 0:
        raise ValueError(err)
    _ensure_sleepable_timeout(as_int, err)
    return as_int


def resolve_stream_task_timeout(
    raw_timeout: Any,
    *,
    field_name: str = "timeout",
    default_seconds: int = DEFAULT_STREAM_TASK_TIMEOUT_SECONDS,
) -> int:
    """Resolve background chat-task timeout in seconds.

    ``None`` (omitted / null) uses ``default_seconds``. Otherwise parses via
    :func:`parse_positive_timeout_seconds`. Omitting timeout is never
    unbounded; callers that need a longer budget must pass an explicit
    positive value.
    """
    if raw_timeout is None:
        return int(default_seconds)
    return parse_positive_timeout_seconds(
        raw_timeout,
        field_name=field_name,
    )
