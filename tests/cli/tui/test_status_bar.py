# -*- coding: utf-8 -*-
"""Status bar: compact token formatting and the in-flight estimate marker."""

from __future__ import annotations

from qwenpaw.cli.tui.widgets.status_bar import StatusBar, _fmt_count


def test_fmt_count_compacts_large_numbers():
    assert _fmt_count(0) == "0"
    assert _fmt_count(842) == "842"
    assert _fmt_count(6370) == "6.4k"
    assert _fmt_count(6000) == "6k"  # trailing .0 trimmed
    assert _fmt_count(1_540_000) == "1.54M"
    assert _fmt_count(2_000_000) == "2M"


def test_token_counts_rendered_compactly():
    bar = StatusBar()
    bar.set(tok_in=1200, tok_out=6370)
    summary = bar.summary
    assert "↑1.2k" in summary
    assert "↓6.4k" in summary
    assert "~" not in summary  # exact, not an estimate


def test_initial_state_is_starting_not_ready():
    bar = StatusBar()
    summary = bar.summary
    assert "starting" in summary
    assert "ready" not in summary


def test_versions_render_in_status_bar():
    bar = StatusBar(tui_version="0.1.0")
    bar.set(qwenpaw_version="1.1.10")
    summary = bar.summary
    assert "QwenPaw 1.1.10" in summary
    assert "TUI 0.1.0" in summary


def test_estimate_is_marked_with_tilde():
    bar = StatusBar()
    bar.set(tok_in=1200, tok_out=512, tok_out_approx=True)
    assert "↓~512" in bar.summary


def test_input_not_shown_as_zero_during_first_stream():
    # Before any usage arrives, input is unknown — show only the output
    # estimate, never "↑0".
    bar = StatusBar()
    bar.set(tok_in=0, tok_out=10, tok_out_approx=True)
    summary = bar.summary
    assert "↓~10" in summary
    assert "↑" not in summary


def test_active_state_uses_spinner_glyph():
    bar = StatusBar()
    bar.set(state="thinking")
    assert "thinking" in bar.summary
    assert "● thinking" not in bar.summary
