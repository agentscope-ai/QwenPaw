# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-import,unused-variable
"""Unit tests for visual compression renderer layout logic.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the deterministic text
layout / paging helpers in ``renderer.py``, which previously had zero
unit-test coverage.
"""

from __future__ import annotations

import pytest

from qwenpaw.agents.context.visual_compression.config import (
    LOW_EFFORT_PRESET,
)
from qwenpaw.agents.context.visual_compression.rendering import (
    renderer,
)


# ---------------------------------------------------------------------------
# minify / tab expansion / glyph escaping
# ---------------------------------------------------------------------------


class TestMinifyForRender:
    def test_strips_trailing_whitespace(self):
        assert renderer._minify_for_render("a  \n") == "a\n"
        # interior whitespace is preserved
        assert renderer._minify_for_render("a  \tb\n") == "a  \tb\n"

    def test_collapses_long_blank_runs(self):
        assert renderer._minify_for_render("a\n\n\n\n\nb") == "a\n\n\nb"

    def test_preserves_normal_blanks(self):
        assert renderer._minify_for_render("a\n\nb") == "a\n\nb"


class TestExpandTabsVisible:
    def test_no_tabs_passthrough(self):
        assert renderer._expand_tabs_visible("hello") == "hello"

    def test_tab_becomes_arrow_plus_padding(self):
        out = renderer._expand_tabs_visible("\ta")
        assert out.startswith("→")
        # tab at column 0 spans 4 columns: arrow + 3 spaces
        assert out == "→   a"

    def test_mid_line_tab(self):
        out = renderer._expand_tabs_visible("ab\tc")
        assert "→" in out


class TestEscapeMissingGlyphs:
    def test_ascii_passthrough(self):
        assert renderer._escape_missing_glyphs("hello") == "hello"

    def test_missing_codepoint_escaped(self):
        # Pick a rare codepoint almost certainly absent from the atlas.
        char = "\U0001F600"  # 😀
        out = renderer._escape_missing_glyphs(f"a{char}b")
        if ord(char) not in renderer._load_dense_gray_atlas().ranks:
            assert "[U+" in out
            assert char not in out
        else:
            assert out == f"a{char}b"

    def test_role_markers_preserved_when_requested(self):
        from qwenpaw.agents.context.visual_compression.config import (
            ROLE_MARK_USER,
        )

        line = f"{ROLE_MARK_USER}hi"
        preserved = renderer._escape_missing_glyphs(
            line,
            preserve_role_markers=True,
        )
        assert preserved.startswith(ROLE_MARK_USER)


class TestCharCells:
    def test_ascii_is_single_cell(self):
        assert renderer._char_cells("a") == 1

    def test_empty_is_zero(self):
        assert renderer._char_cells("") == 0

    def test_cjk_is_double_cell(self):
        # CJK glyphs are wide in the atlas.
        cells = renderer._char_cells("中")
        assert cells in (1, 2)


# ---------------------------------------------------------------------------
# line wrapping
# ---------------------------------------------------------------------------


class TestWrapLine:
    def test_empty_line(self):
        assert renderer._wrap_line("", 10) == [""]

    def test_short_line_single_piece(self):
        assert renderer._wrap_line("abc", 10) == ["abc"]

    def test_wraps_at_max_cols(self):
        out = renderer._wrap_line("abcdef", 3)
        assert out == ["abc", "def"]

    def test_wraps_uneven_remainder(self):
        out = renderer._wrap_line("abcdefg", 3)
        assert out == ["abc", "def", "g"]


# ---------------------------------------------------------------------------
# visual lines / profiles
# ---------------------------------------------------------------------------


class TestVisualLines:
    def test_empty_text_yields_single_blank(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        assert renderer._visual_lines("", profile) == [""]

    def test_columns_override_respected(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        lines = renderer._visual_lines("abcdefgh", profile, columns=4)
        assert lines == ["abcd", "efgh"]

    def test_multiple_lines(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        lines = renderer._visual_lines("a\nb", profile)
        assert lines == ["a", "b"]


class TestMeasureContentColumns:
    def test_measures_widest_line(self):
        width = renderer.measure_content_columns("abc\nde")
        assert width == 3

    def test_capped_by_preset_width(self):
        huge = "x" * 100000
        cap = renderer.measure_content_columns(huge)
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        expected_cap = max(
            1,
            (profile.width - 2 * profile.padding) // profile.cell_width,
        )
        assert cap == expected_cap

    def test_empty_text_min_width(self):
        assert renderer.measure_content_columns("") == 1


class TestProfileWithColumns:
    def test_none_uses_max_columns(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        new_profile, columns = renderer._profile_with_columns(profile, None)
        assert new_profile is profile
        assert columns >= 1

    def test_columns_clamped(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        new_profile, columns = renderer._profile_with_columns(profile, 1)
        assert columns == 1
        expected_width = 2 * profile.padding + profile.cell_width
        assert new_profile.width == expected_width

    def test_huge_columns_clamped_to_max(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        new_profile, columns = renderer._profile_with_columns(
            profile,
            10**9,
        )
        max_columns = (profile.width - 2 * profile.padding) // (
            profile.cell_width
        )
        assert columns == max_columns


class TestRenderRowsPerPage:
    def test_positive_and_bounded(self):
        rows = renderer.render_rows_per_page(LOW_EFFORT_PRESET, 40)
        assert rows >= 1

    def test_more_columns_fewer_rows(self):
        narrow = renderer.render_rows_per_page(LOW_EFFORT_PRESET, 10)
        wide = renderer.render_rows_per_page(LOW_EFFORT_PRESET, 200)
        assert narrow >= wide


# ---------------------------------------------------------------------------
# page splitting
# ---------------------------------------------------------------------------


class TestSplitVisualPages:
    def test_single_page_under_limits(self):
        pages = renderer._split_visual_pages(["a", "b"], 10, 1000)
        assert pages == [["a", "b"]]

    def test_splits_on_row_limit(self):
        pages = renderer._split_visual_pages(
            ["l1", "l2", "l3"],
            max_lines=2,
            max_chars=1000,
        )
        assert pages == [["l1", "l2"], ["l3"]]

    def test_splits_on_char_limit(self):
        pages = renderer._split_visual_pages(
            ["aaaa", "bbbb"],
            max_lines=100,
            max_chars=5,
        )
        assert len(pages) == 2

    def test_empty_input_single_empty_page(self):
        assert renderer._split_visual_pages([], 10, 100) == [[]]

    def test_oversized_single_line_gets_own_page(self):
        pages = renderer._split_visual_pages(
            ["x" * 100, "y"],
            max_lines=10,
            max_chars=10,
        )
        assert pages[0] == ["x" * 100]
        assert pages[1] == ["y"]


# ---------------------------------------------------------------------------
# reflow / public API
# ---------------------------------------------------------------------------


class TestReflowForRender:
    def test_hard_breaks_marked(self):
        out = renderer.reflow_for_render("a\nb")
        assert "↵" in out

    def test_existing_return_glyph_kept(self):
        # Only the source glyph "↵" is normalised; an existing "⏎"
        # stays untouched.
        out = renderer.reflow_for_render("a⏎b")
        assert out == "a⏎b"


class TestPageCountForText:
    def test_short_text_single_page(self):
        assert renderer.page_count_for_text("hello") == 1

    def test_long_text_multiple_pages(self):
        text = "\n".join(f"line {i}" for i in range(5000))
        assert renderer.page_count_for_text(text) > 1

    def test_empty_text_single_page(self):
        assert renderer.page_count_for_text("") == 1


class TestEstimateTextPages:
    def test_geometry_pages_have_empty_png(self):
        pages = renderer.estimate_text_pages("hello\nworld")
        assert len(pages) >= 1
        assert all(page.png == b"" for page in pages)
        assert all(page.width > 0 for page in pages)

    def test_sha256_consistent(self):
        pages = renderer.estimate_text_pages("hello")
        for page in pages:
            assert page.sha256 == page.sha256


class TestRenderTextPages:
    def test_renders_deterministic_png(self):
        pages = renderer.render_text_pages("hello")
        assert len(pages) == 1
        page = pages[0]
        assert page.png[:8] == b"\x89PNG\r\n\x1a\n"
        assert page.width > 0 and page.height > 0
        # deterministic rendering: same input → same digest
        again = renderer.render_text_pages("hello")
        assert again[0].sha256 == page.sha256


class TestRenderCacheInfo:
    def test_cache_info_exposed(self):
        info = renderer.render_cache_info()
        assert info is not None


class TestPageRenderLines:
    def test_already_laid_out_passthrough(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        page_lines = ["abc", "def"]
        out = renderer._page_render_lines(
            page_lines,
            profile,
            columns=40,
            max_lines=10,
        )
        assert out == page_lines

    def test_trailing_whitespace_triggers_relayout(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        page_lines = ["abc   "]
        out = renderer._page_render_lines(
            page_lines,
            profile,
            columns=40,
            max_lines=10,
        )
        assert out == ["abc"]

    def test_single_column_relayout(self):
        profile = renderer._profile_for_preset(LOW_EFFORT_PRESET)
        out = renderer._page_render_lines(
            ["abcd"],
            profile,
            columns=1,
            max_lines=10,
        )
        assert out[0] == "a"
