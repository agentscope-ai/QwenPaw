# -*- coding: utf-8 -*-
"""Welcome logo rendering."""

from __future__ import annotations

# Tests exercise the widget's private rendering helpers directly.
# pylint: disable=protected-access

from qwenpaw.cli.tui.widgets.messages import (
    WelcomeMessage,
    _bright_dot_hex,
    _relative_luminance,
)


def test_welcome_logo_palette_changes_rendered_colors():
    welcome = WelcomeMessage(("#071b2c", "#101f3c", "#163857"))
    before = {str(span.style) for span in welcome._render_body().spans}

    welcome._set_palette_colors(("#281b19", "#38261f", "#563722"))
    rendered = welcome._render_body()
    after = {str(span.style) for span in rendered.spans}

    assert "█" in rendered.plain
    assert before != after
    assert "#ff9d4d" not in after


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
