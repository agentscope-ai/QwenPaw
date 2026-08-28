# -*- coding: utf-8 -*-
"""Tests for structured desktop startup metrics."""

import json

from qwenpaw.tauri import startup_metrics


def test_mark_is_silent_when_metrics_are_disabled(monkeypatch, capsys):
    monkeypatch.delenv(startup_metrics.STARTUP_METRIC_ENV, raising=False)

    startup_metrics.mark("ready")

    assert capsys.readouterr().out == ""


def test_mark_emits_structured_metric(monkeypatch, capsys):
    monkeypatch.setenv(startup_metrics.STARTUP_METRIC_ENV, "true")

    startup_metrics.mark("port_bound", port=12345)

    output = capsys.readouterr().out.strip()
    assert output.startswith(startup_metrics.STARTUP_METRIC_PREFIX)
    payload = json.loads(
        output.removeprefix(
            startup_metrics.STARTUP_METRIC_PREFIX,
        ),
    )
    assert payload["event"] == "port_bound"
    assert payload["port"] == 12345
    assert payload["pid"] > 0
    assert payload["elapsed_ms"] >= 0
