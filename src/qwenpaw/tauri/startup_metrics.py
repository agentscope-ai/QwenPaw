# -*- coding: utf-8 -*-
"""Dependency-light startup metrics for the packaged desktop backend."""

from __future__ import annotations

import json
import os
import time
from typing import Any


STARTUP_METRIC_ENV = "QWENPAW_DESKTOP_STARTUP_METRICS"
STARTUP_METRIC_PREFIX = "QWENPAW_STARTUP_METRIC "

_ORIGIN_NS = time.perf_counter_ns()


def enabled() -> bool:
    """Return whether structured desktop startup metrics are enabled."""
    value = os.environ.get(STARTUP_METRIC_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def mark(event: str, **fields: Any) -> None:
    """Emit one machine-readable startup event to standard output."""
    if not enabled():
        return
    elapsed_ns = time.perf_counter_ns() - _ORIGIN_NS
    payload = {
        "event": event,
        "elapsed_ms": round(elapsed_ns / 1_000_000, 3),
        "pid": os.getpid(),
        **fields,
    }
    print(
        f"{STARTUP_METRIC_PREFIX}"
        f"{json.dumps(payload, separators=(',', ':'), sort_keys=True)}",
        flush=True,
    )
