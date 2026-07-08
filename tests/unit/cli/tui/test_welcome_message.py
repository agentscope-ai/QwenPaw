# -*- coding: utf-8 -*-
"""Welcome logo rendering."""

from __future__ import annotations

# Tests exercise the widget's private rendering helpers directly.
# pylint: disable=protected-access

import pytest

from qwenpaw.cli.tui.widgets.messages import (
    WelcomeMessage,
    _bounce,
    _bright_dot_hex,
    _relative_luminance,
)

pytestmark = [pytest.mark.unit, pytest.mark.p1]

_PALETTE = ("#071b2c", "#101f3c", "#163857")


def test_welcome_logo_palette_changes_rendered_colors():
    welcome = WelcomeMessage(("#071b2c", "#101f3c", "#163857"))
    before = {str(span.style) for span in welcome._render_body().spans}

    welcome._set_palette_colors(("#281b19", "#38261f", "#563722"))
    rendered = welcome._render_body()
    after = {str(span.style) for span in rendered.spans}

    assert "█" in rendered.plain
    assert before != after
    assert "#ff9d4d" not in after


def test_welcome_message_shows_workspace_and_project_dirs():
    welcome = WelcomeMessage(
        _PALETTE,
        workspace_dir="/tmp/qwenpaw/workspaces/default",
        project_dir="/tmp/project",
    )

    plain = welcome.content.plain
    assert (
        "Agent directory (sessions, memory & skills): "
        "/tmp/qwenpaw/workspaces/default"
    ) in plain
    assert "Project directory: /tmp/project" in plain


def test_welcome_logo_gradient_animates_vertically():
    welcome = WelcomeMessage(("#071b2c", "#101f3c", "#163857"))
    first = [welcome._gradient_color(row) for row in range(4)]

    welcome._frame += 1
    second = [welcome._gradient_color(row) for row in range(4)]

    assert len(set(first)) == 4
    assert first != second


def test_welcome_logo_dots_are_brighter_than_current_letter_color():
    welcome = WelcomeMessage(("#071b2c", "#101f3c", "#163857"))

    for frame in range(6):
        welcome._frame = frame
        letter_color = welcome._gradient_color(1)
        dot_color = _bright_dot_hex(letter_color)

        assert _relative_luminance(dot_color) > _relative_luminance(
            letter_color,
        )


def test_welcome_logo_rows_use_a_single_flat_color():
    """No per-cell emboss: each row's letter blocks share one gradient color.

    The old bevel shading tinted nearly every block lighter/darker, which read
    as grainy "low-resolution" noise on a 6-row block font. The blocks in a row
    should now all carry that row's flat gradient tone (only the eye dots,
    which are deliberately brightened, may differ).
    """
    welcome = WelcomeMessage(("#071b2c", "#101f3c", "#163857"))
    # Row 1 ("███   ███ ...") is all letter strokes, no dots.
    row = welcome._render_pixel_rows()[1]
    block_colors = {
        str(span.style)
        for span in row.spans
        if row.plain[span.start : span.end] == "█"
    }
    assert block_colors == {welcome._gradient_color(1)}


def test_logo_splits_into_one_segment_per_glyph():
    """The wordmark hops letter by letter, so it must segment cleanly.

    "QwenPaw" is seven glyphs (the paw prints ride on the second "a"), so the
    blank-column split must yield exactly seven column spans.
    """
    welcome = WelcomeMessage(_PALETTE)
    assert len(welcome._segments) == 7
    # Spans are ordered left to right and never overlap.
    for (_, end), (start, _) in zip(
        welcome._segments,
        welcome._segments[1:],
    ):
        assert end <= start


def test_hop_animation_settles_to_the_static_logo():
    """Once every letter lands, the frame matches the resting logo exactly."""
    welcome = WelcomeMessage(_PALETTE)

    frame, settled = welcome._compose_frame(welcome._ANIM_CAP)
    static = welcome._render_body()

    assert settled is True

    def trimmed(text):
        return [line.rstrip() for line in text.plain.split("\n")]

    assert trimmed(frame) == trimmed(static)
    assert frame.plain.count("█") == static.plain.count("█")


def test_hop_animation_starts_off_canvas_and_fills_in():
    """Letters drop in: the first frame is empty, the last is full."""
    welcome = WelcomeMessage(_PALETTE)

    first = welcome._compose_frame(0.0)[0].plain.count("█")
    midway = welcome._compose_frame(0.8)[0].plain.count("█")
    final = welcome._compose_frame(welcome._ANIM_CAP)[0].plain.count("█")

    # Nothing has dropped in yet on frame zero; the logo assembles over time.
    assert first == 0
    assert first < midway < final


def test_bounce_drops_in_then_comes_to_rest():
    drop = 9.0
    # Before its start (negative time) the ball waits at full drop height.
    assert _bounce(-0.5, drop, 80.0, 0.5) == drop
    # It never dips below the floor while bouncing...
    samples = [_bounce(t / 100, drop, 80.0, 0.5) for t in range(400)]
    assert min(samples) >= 0.0
    # ...and it has come to rest well before the animation cap.
    assert _bounce(3.0, drop, 80.0, 0.5) == 0.0
