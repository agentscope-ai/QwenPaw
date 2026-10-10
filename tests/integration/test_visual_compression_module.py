# -*- coding: utf-8 -*-
"""Integration tests for the visual-compression page renderer.

Covers src/qwenpaw/agents/context/visual_compression/rendering/
renderer.py (361 uncovered lines): glyph atlas loading, character
cell width measurement, missing-glyph escaping, tab expansion,
line wrapping, text minification, column measurement, page
splitting, and PNG rendering of prepared text.
"""

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# atlas loading
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_dense_gray_atlas_loads_all_efforts() -> None:
    """Frozen glyph atlases load for low/medium/high effort."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _load_dense_gray_atlas,
    )

    for effort in ("low", "medium", "high"):
        atlas = _load_dense_gray_atlas(effort)
        assert atlas.cell_width > 0
        assert atlas.cell_height > 0
        assert len(atlas.ranks) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_dense_gray_atlas_unknown_profile_raises() -> None:
    """Unknown effort profiles raise ValueError."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _load_dense_gray_atlas,
    )

    with pytest.raises(ValueError, match="unknown frozen atlas"):
        _load_dense_gray_atlas("nonexistent-effort")


# ------------------------------------------------------------------ #
# character width measurement
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_char_cells_ascii() -> None:
    """ASCII characters occupy one cell."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _char_cells,
    )

    assert _char_cells("A") == 1
    assert _char_cells("z") == 1
    assert _char_cells(" ") == 1
    assert _char_cells("") == 0


# ------------------------------------------------------------------ #
# missing-glyph escaping
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_escape_missing_glyphs_ascii_unchanged() -> None:
    """ASCII-only lines need no escaping."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _escape_missing_glyphs,
    )

    assert _escape_missing_glyphs("hello world") == "hello world"


@pytest.mark.integration
@pytest.mark.p1
def test_escape_missing_glyphs_formats_codepoint() -> None:
    """Characters outside the atlas are escaped as [U+XXXX]."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _escape_missing_glyphs,
    )

    # Pick a codepoint guaranteed absent from a dense font atlas.
    result = _escape_missing_glyphs("\U0001F9FF")
    assert "[U+1F9FF]" in result


# ------------------------------------------------------------------ #
# tab expansion
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_expand_tabs_no_tabs_passthrough() -> None:
    """Lines without tabs pass through unchanged."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _expand_tabs_visible,
    )

    assert _expand_tabs_visible("no tabs here") == "no tabs here"


@pytest.mark.integration
@pytest.mark.p1
def test_expand_tabs_visible_glyph() -> None:
    """Tabs become visible arrow glyphs with column alignment."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _expand_tabs_visible,
    )

    result = _expand_tabs_visible("a\tb")
    assert "→" in result
    assert "\t" not in result


# ------------------------------------------------------------------ #
# text minification
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_minify_strips_trailing_whitespace() -> None:
    """Trailing spaces/tabs are removed from every line."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _minify_for_render,
    )

    assert _minify_for_render("a  \nb\t\n") == "a\nb\n"


@pytest.mark.integration
@pytest.mark.p1
def test_minify_collapses_blank_runs() -> None:
    """Runs of 4+ newlines collapse to 3."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _minify_for_render,
    )

    assert _minify_for_render("a\n\n\n\n\nb") == "a\n\n\nb"
    # 3 newlines are kept.
    assert _minify_for_render("a\n\n\nb") == "a\n\n\nb"


# ------------------------------------------------------------------ #
# column measurement
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_measure_content_columns_short_text() -> None:
    """Short lines measure to their visible width."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        measure_content_columns,
    )

    assert measure_content_columns("hi") == 2
    assert measure_content_columns("") == 1


@pytest.mark.integration
@pytest.mark.p1
def test_measure_content_columns_capped_by_preset() -> None:
    """Wide lines are capped at the preset column limit."""
    from qwenpaw.agents.context.visual_compression.config import (
        LOW_EFFORT_PRESET,
    )
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        measure_content_columns,
    )

    wide = "x" * 100000
    result = measure_content_columns(wide, preset=LOW_EFFORT_PRESET)
    assert result > 0
    assert result < 100000


# ------------------------------------------------------------------ #
# reflow and preparation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_reflow_preserves_hard_breaks() -> None:
    """Hard line breaks become visible return glyphs."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        reflow_for_render,
    )

    result = reflow_for_render("line1\nline2")
    assert "↵" in result
    assert "\n" not in result


@pytest.mark.integration
@pytest.mark.p1
def test_prepare_render_text_matches_reflow() -> None:
    """prepare_render_text delegates to reflow_for_render."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        prepare_render_text,
        reflow_for_render,
    )

    text = "a\nb\tc"
    assert prepare_render_text(text) == reflow_for_render(text)


# ------------------------------------------------------------------ #
# page geometry
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_render_rows_per_page_positive() -> None:
    """Rows per page are a positive, bounded number."""
    from qwenpaw.agents.context.visual_compression.config import (
        LOW_EFFORT_PRESET,
    )
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        render_rows_per_page,
    )

    rows = render_rows_per_page(LOW_EFFORT_PRESET, columns=80)
    assert rows >= 1


@pytest.mark.integration
@pytest.mark.p1
def test_split_visual_pages_line_limit() -> None:
    """Lines split into pages honoring the row limit."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _split_visual_pages,
    )

    lines = [f"line{i}" for i in range(10)]
    pages = _split_visual_pages(lines, max_lines=3, max_chars=10_000)
    assert len(pages) == 4
    assert sum(len(p) for p in pages) == 10


@pytest.mark.integration
@pytest.mark.p1
def test_split_visual_pages_char_limit() -> None:
    """Long lines force splits by the character budget."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _split_visual_pages,
    )

    lines = ["x" * 50 for _ in range(4)]
    pages = _split_visual_pages(lines, max_lines=100, max_chars=100)
    assert len(pages) >= 2


@pytest.mark.integration
@pytest.mark.p1
def test_split_visual_pages_empty() -> None:
    """No input yields a single empty page."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        _split_visual_pages,
    )

    assert _split_visual_pages([], max_lines=10, max_chars=100) == [[]]


# ------------------------------------------------------------------ #
# page counting
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_page_count_short_text_single_page() -> None:
    """A short text fits on one page."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        page_count_for_text,
    )

    assert page_count_for_text("hello world") == 1


@pytest.mark.integration
@pytest.mark.p1
def test_page_count_grows_with_text() -> None:
    """Longer texts need more pages."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        page_count_for_text,
    )

    short = page_count_for_text("hello")
    long_text = "word " * 20000
    assert page_count_for_text(long_text) > short


# ------------------------------------------------------------------ #
# PNG rendering
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_render_text_pages_produces_png() -> None:
    """Rendering yields PNG pages with positive dimensions."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        render_text_pages,
    )

    pages = render_text_pages("hello world\nsecond line")
    assert len(pages) >= 1
    page = pages[0]
    assert page.png.startswith(b"\x89PNG")
    assert page.width > 0
    assert page.height > 0


@pytest.mark.integration
@pytest.mark.p1
def test_render_text_pages_sha256_stable() -> None:
    """Rendered page hashes are stable across renders (cache)."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        render_text_pages,
    )

    first = render_text_pages("stable content")[0].sha256
    second = render_text_pages("stable content")[0].sha256
    assert first == second
    assert len(first) == 64


@pytest.mark.integration
@pytest.mark.p1
def test_render_text_pages_max_pages_bound() -> None:
    """max_pages bounds the number of returned pages."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        render_text_pages,
    )

    long_text = "row of words " * 3000
    pages = render_text_pages(long_text, max_pages=2)
    assert len(pages) <= 2


@pytest.mark.integration
@pytest.mark.p1
def test_render_cache_info_counters() -> None:
    """Cache info reports hits and misses."""
    from qwenpaw.agents.context.visual_compression.rendering.renderer import (
        render_cache_info,
        render_text_pages,
    )

    render_text_pages("cache probe content")
    info = render_cache_info()
    assert info.hits >= 0
    assert info.misses >= 0
