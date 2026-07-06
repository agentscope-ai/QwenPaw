# -*- coding: utf-8 -*-
"""Status bar: compact token formatting and the in-flight estimate marker."""

from __future__ import annotations

# ``bar`` is a fine local name for a StatusBar widget under test.
# pylint: disable=disallowed-name

import pytest
from rich.text import Text

from qwenpaw.cli.tui.widgets.status_bar import (
    _CTX_AMBER,
    _CTX_GREEN,
    _CTX_RED,
    StatusBar,
    _append_ctx_bar,
    _fmt_count,
)

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def _ctx_bar(used: int, size: int, threshold: float = 0.0) -> Text:
    """Render just the context-usage bar into a fresh Text."""
    t = Text()
    _append_ctx_bar(t, used, size, threshold)
    return t


def _ctx_styles(t: Text) -> list[str]:
    return [str(span.style) for span in t.spans]


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


def test_version_renders_in_status_bar():
    bar = StatusBar()
    bar.set(qwenpaw_version="1.1.10")
    summary = bar.summary
    assert "QwenPaw 1.1.10" in summary
    # Only QwenPaw's version is shown; the TUI version was removed.
    assert "TUI" not in summary


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


# --- context-usage bar -------------------------------------------------------


def test_ctx_bar_hidden_when_window_or_occupancy_unknown():
    # Window unknown (size==0): a denominator-less bar is meaningless.
    assert _ctx_bar(123_000, 0).plain == ""
    # Occupancy not yet reported (used==0): hidden.
    assert _ctx_bar(0, 1_000_000).plain == ""
    # And it stays out of the full status line.
    bar = StatusBar()
    bar.set(used=0, size=0)
    assert "ctx" not in bar.summary


def test_ctx_bar_renders_bar_and_label():
    t = _ctx_bar(123_000, 1_000_000)  # ~12%
    assert "ctx" in t.plain
    assert "█" in t.plain  # at least one filled cell
    assert "123k / 1M" in t.plain  # used / size label via _fmt_count
    # No percentage and no compaction marker — the bar itself is the signal.
    assert "%" not in t.plain
    assert "╵" not in t.plain


def test_ctx_bar_color_ramps_with_occupancy():
    green = _ctx_styles(_ctx_bar(300_000, 1_000_000))  # 30%
    amber = _ctx_styles(_ctx_bar(700_000, 1_000_000))  # 70%
    red = _ctx_styles(_ctx_bar(950_000, 1_000_000))  # 95%
    assert any(_CTX_GREEN in s for s in green)
    assert any(_CTX_AMBER in s for s in amber)
    assert any(_CTX_RED in s for s in red)


def test_ctx_bar_fill_is_always_ten_cells():
    # Fill region is exactly the fixed track width across the ratio range,
    # so line.cell_len stays correct for the status bar's right-alignment.
    for used, size in [
        (50, 1_000_000),
        (300_000, 1_000_000),
        (1_000_000, 1_000_000),
        (2_000_000, 1_000_000),
    ]:
        plain = _ctx_bar(used, size).plain
        fill = plain[plain.index("[") + 1 : plain.index("]")]
        assert len(fill) == 10, (used, size, fill)


def test_ctx_bar_clamps_when_used_exceeds_size():
    t = _ctx_bar(2_000_000, 1_000_000)  # stale over-report
    # Full bar, red, no overflow of the fixed 10-cell track.
    assert t.plain.count("█") == 10
    assert any(_CTX_RED in s for s in _ctx_styles(t))


def test_ctx_bar_tiny_ratio_stays_visible():
    t = _ctx_bar(50, 1_000_000)  # 0.005%
    assert "█" in t.plain  # at least one cell, never an empty bar


def _ctx_fill(t: Text) -> str:
    """The bracketed fill region of a rendered bar."""
    p = t.plain
    return p[p.index("[") + 1 : p.index("]")]


def test_ctx_bar_marker_shown_below_threshold():
    # The tick marks the configured compaction point while occupancy is below.
    assert "╵" in _ctx_bar(300_000, 1_000_000, 0.8).plain


def test_ctx_bar_marker_absorbed_at_and_above_threshold():
    assert "╵" not in _ctx_bar(800_000, 1_000_000, 0.8).plain  # exactly at
    assert "╵" not in _ctx_bar(950_000, 1_000_000, 0.8).plain  # above


def test_ctx_bar_marker_visible_through_lead_in_zone():
    # Regression: the tick must stay visible in [0.75, 0.80) (it previously
    # vanished at 0.75 because visibility was gated on the rounded fill count
    # rather than the true ratio).
    for used in (750_000, 760_000, 790_000, 799_000):
        assert "╵" in _ctx_bar(used, 1_000_000, 0.8).plain, used


def test_ctx_bar_marker_position_tracks_threshold():
    # Marker cell index == round(threshold * width); low fixed occupancy so
    # the tick is always shown.
    assert _ctx_fill(_ctx_bar(150_000, 1_000_000, 0.5)).index("╵") == 5
    assert _ctx_fill(_ctx_bar(150_000, 1_000_000, 0.8)).index("╵") == 8
    assert _ctx_fill(_ctx_bar(150_000, 1_000_000, 0.9)).index("╵") == 9


def test_ctx_bar_no_marker_when_threshold_unknown_or_invalid():
    # threshold == 0 (compaction disabled / not reported) -> no tick.
    assert "╵" not in _ctx_bar(300_000, 1_000_000, 0.0).plain
    # Out-of-range thresholds are ignored too.
    assert "╵" not in _ctx_bar(300_000, 1_000_000, 1.0).plain


def test_ctx_bar_fill_stays_ten_cells_with_marker():
    for used in (50, 300_000, 750_000, 799_000):
        assert len(_ctx_fill(_ctx_bar(used, 1_000_000, 0.8))) == 10, used
