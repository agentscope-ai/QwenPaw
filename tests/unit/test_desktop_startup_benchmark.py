# -*- coding: utf-8 -*-
"""Tests for the packaged desktop startup benchmark."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "benchmarks"
    / "desktop_startup"
    / "run_backend_benchmark.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "desktop_startup_benchmark",
    _SCRIPT_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
benchmark = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(benchmark)


def _run(value: float) -> dict[str, Any]:
    return {
        "success": True,
        "wall_elapsed_ms": value,
        "metrics": {},
    }


def test_parse_metric_line_accepts_embedded_metric() -> None:
    line = (
        "prefix QWENPAW_STARTUP_METRIC "
        '{"elapsed_ms":12.5,"event":"python_entry","pid":7}'
    )

    assert benchmark.parse_metric_line(line) == {
        "elapsed_ms": 12.5,
        "event": "python_entry",
        "pid": 7,
    }


@pytest.mark.parametrize(
    "line",
    [
        "ordinary output",
        "QWENPAW_STARTUP_METRIC invalid",
        "QWENPAW_STARTUP_METRIC []",
        'QWENPAW_STARTUP_METRIC {"elapsed_ms":1}',
    ],
)
def test_parse_metric_line_rejects_invalid_payload(line: str) -> None:
    assert benchmark.parse_metric_line(line) is None


def test_parse_backend_port_accepts_ready_announcement() -> None:
    line = 'QWENPAW_BACKEND_READY {"port":8088}'

    assert benchmark.parse_backend_port(line) == 8088


@pytest.mark.parametrize(
    "line",
    [
        "ordinary output",
        "QWENPAW_BACKEND_READY invalid",
        'QWENPAW_BACKEND_READY {"port":0}',
        'QWENPAW_BACKEND_READY {"port":70000}',
    ],
)
def test_parse_backend_port_rejects_invalid_payload(line: str) -> None:
    assert benchmark.parse_backend_port(line) is None


def test_percentile_interpolates_values() -> None:
    assert benchmark.percentile([100.0, 200.0, 300.0], 0.5) == 200.0
    assert benchmark.percentile([100.0, 200.0], 0.95) == 195.0


def test_summarize_runs_ignores_failures() -> None:
    runs = [
        _run(100.0),
        _run(200.0),
        {"success": False},
    ]

    summary = benchmark.summarize_runs(runs)

    assert summary == {
        "requested_runs": 3,
        "successful_runs": 2,
        "failed_runs": 1,
        "wall_elapsed_ms": {
            "min": 100.0,
            "p50": 150.0,
            "p90": 190.0,
            "p95": 195.0,
            "max": 200.0,
        },
    }
