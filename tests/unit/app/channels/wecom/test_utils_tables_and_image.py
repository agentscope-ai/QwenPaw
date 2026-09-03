# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.app.channels.wecom.utils`.

Covers GFM table normalisation for the WeCom renderer (including the
code-fence passthrough) and the image compression pipeline that keeps
uploads under the WeCom size limit.
"""
# pylint: disable=protected-access
from __future__ import annotations

import builtins
import io
import random
from unittest.mock import patch

import pytest
from PIL import Image

from qwenpaw.app.channels.wecom import utils as wecom_utils
from qwenpaw.app.channels.wecom.utils import (
    _format_table,
    compress_image_for_wecom,
    format_markdown_tables,
)


def _write_png(path, size=(64, 64), mode="RGB", fill=(200, 30, 30)):
    """Write a solid-colour PNG (compresses to almost nothing)."""
    image = Image.new(mode, size, fill)
    if mode == "P":
        image = image.convert("P")
    image.save(path, format="PNG")
    return path


def _jpeg_size(image, quality: int, scale: float | None = None) -> int:
    """Return the JPEG byte size PIL would produce for this input.

    Used to derive limits that sit just above/below a specific rung of
    the quality ladder, so the assertions stay exact even if a different
    Pillow build produces slightly different byte counts.
    """
    target = image.convert("RGB")
    if scale is not None:
        target = target.resize(
            (int(target.width * scale), int(target.height * scale)),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    target.save(buffer, format="JPEG", quality=quality, optimize=True)
    return len(buffer.getvalue())


def _write_noisy_png(path, size=(400, 400), mode="RGB", alpha=None, seed=7):
    """Write a high-entropy PNG that survives JPEG conversion.

    Solid colours compress far below any realistic limit, so the
    quality/resize ladder is never exercised.  Noise keeps the PNG large
    and every JPEG attempt measurably bigger than the byte-level limits
    the tests assert on.
    """
    rng = random.Random(seed)
    if mode == "P":
        image = Image.frombytes(
            "RGB",
            size,
            rng.randbytes(size[0] * size[1] * 3),
        ).convert("P")
    else:
        image = Image.frombytes(
            mode,
            size,
            rng.randbytes(size[0] * size[1] * Image.getmodebands(mode)),
        )
    if alpha is not None:
        image.putalpha(Image.new("L", size, alpha))
    image.save(path, format="PNG")
    return path


def _jpeg_size(image, quality: int, scale: float | None = None) -> int:
    """Return the JPEG byte size PIL would produce for this input.

    Used to derive limits that sit just above/below a specific rung of
    the quality ladder, so the assertions stay exact even if a different
    Pillow build produces slightly different byte counts.
    """
    target = image.convert("RGB")
    if scale is not None:
        target = target.resize(
            (int(target.width * scale), int(target.height * scale)),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    target.save(buffer, format="JPEG", quality=quality, optimize=True)
    return len(buffer.getvalue())


# ---------------------------------------------------------------------------
# _format_table
# ---------------------------------------------------------------------------


class TestFormatTable:
    def test_empty_input_is_returned_unchanged(self):
        assert _format_table([]) == []

    def test_columns_are_padded_to_widest_cell(self):
        formatted = _format_table(
            ["| name | b |", "| --- | --- |", "| 1 | 22 |"],
        )

        assert formatted == [
            "| name | b  |",
            "| ---- | --- |",
            "| 1    | 22 |",
        ]

    def test_separator_row_is_rebuilt_from_widths(self):
        formatted = _format_table(
            ["| name | value |", "|---|---|", "| long-name | v |"],
        )

        # The rebuilt separator matches the widest cell per column and is
        # never shorter than three dashes.
        assert formatted[1] == "| --------- | ----- |"

    def test_separator_has_minimum_three_dashes(self):
        formatted = _format_table(["| a | b |", "| - | - |", "| 1 | 2 |"])

        assert formatted[1] == "| --- | --- |"

    def test_alignment_colons_in_separator_are_discarded(self):
        formatted = _format_table(["| a | b |", "|:---|---:|", "| 1 | 2 |"])

        assert set(formatted[1]) <= set("|- ")

    def test_rows_without_leading_trailing_pipe(self):
        formatted = _format_table(["a | b", "--- | ---", "1 | 2"])

        assert formatted[0] == "| a | b |"
        assert formatted[2] == "| 1 | 2 |"

    def test_ragged_rows_are_padded_with_empty_cells(self):
        formatted = _format_table(["| a | b | c |", "| --- |", "| 1 |"])

        assert all(row.count("|") == 4 for row in formatted)
        assert formatted[2] == "| 1 |   |   |"

    def test_cells_are_trimmed(self):
        formatted = _format_table(["|  a  |   b|", "| --- | --- |"])

        assert formatted[0] == "| a | b |"

    def test_single_row_table_gets_a_separator(self):
        formatted = _format_table(["| only |"])

        assert formatted == ["| only |", "| ---- |"]

    def test_table_without_separator_row_is_left_alone(self):
        """No separator detected -> every line is parsed as a data row."""
        formatted = _format_table(["| a | b |", "| 1 | 2 |"])

        assert len(formatted) == 3  # header, rebuilt separator, data row
        assert formatted[0] == "| a | b |"
        assert formatted[2] == "| 1 | 2 |"

    def test_lines_with_no_cells_are_dropped(self):
        formatted = _format_table(["| a |", "| --- |", "|"])

        assert formatted == ["| a |", "| --- |"]

    def test_only_unparsable_lines_return_input(self):
        """A pipe-only line yields no cells, so nothing is reformatted."""
        lines = ["|", "|"]

        assert _format_table(lines) == lines

    def test_whitespace_only_separator_is_detected(self):
        formatted = _format_table(["| a |", "|   |   |", "| 1 |"])

        assert formatted[1] == "| --- |"

    def test_unicode_cells_are_padded_by_character_count(self):
        formatted = _format_table(
            ["| 名 | v |", "| --- | --- |", "| 名字 | v |"],
        )

        # Width is the character count of the widest cell (2 for column 1).
        assert formatted == [
            "| 名  | v |",
            "| --- | --- |",
            "| 名字 | v |",
        ]


# ---------------------------------------------------------------------------
# format_markdown_tables
# ---------------------------------------------------------------------------


class TestFormatMarkdownTables:
    def test_plain_text_is_untouched(self):
        text = "hello\nworld"

        assert format_markdown_tables(text) == text

    def test_empty_text(self):
        assert format_markdown_tables("") == ""

    def test_table_is_reformatted(self):
        text = "| a | b |\n|---|---|\n| 1 | 22 |"

        assert format_markdown_tables(text) == (
            "| a | b  |\n| --- | --- |\n| 1 | 22 |"
        )

    def test_surrounding_text_is_preserved(self):
        text = "before\n| name |\n| --- |\n| 1 |\nafter"

        # Widths come from data rows only (the separator is rebuilt).
        assert format_markdown_tables(text) == (
            "before\n| name |\n| ---- |\n| 1    |\nafter"
        )

    def test_pipes_inside_code_fence_are_left_alone(self):
        text = "```\n| a | b |\n| 1 | 2 |\n```"

        assert format_markdown_tables(text) == text

    def test_code_fence_with_language_marker(self):
        text = "```python\nx = a | b\n```"

        assert format_markdown_tables(text) == text

    def test_table_after_a_closed_fence_is_formatted(self):
        text = "```\nnot | a | table\n```\n| name |\n| --- |\n| 1 |"

        assert format_markdown_tables(text) == (
            "```\nnot | a | table\n```\n| name |\n| ---- |\n| 1    |"
        )

    def test_unterminated_fence_suppresses_later_tables(self):
        text = "```\n| a |\n| --- |\n| 1 |"

        assert format_markdown_tables(text) == text

    def test_table_stops_at_a_fence_line(self):
        text = "| name |\n| --- |\n```\n| b |"

        # The fence opens a block, so the trailing row passes through.
        assert format_markdown_tables(text) == (
            "| name |\n| ---- |\n```\n| b |"
        )

    def test_two_tables_in_one_message(self):
        text = (
            "| name |\n| --- |\n| 1 |\n\nmid\n\n| value |\n| --- |\n| 22 |"
        )

        result = format_markdown_tables(text)

        assert result == (
            "| name |\n| ---- |\n| 1    |\n\nmid\n\n"
            "| value |\n| ----- |\n| 22    |"
        )

    def test_line_without_pipe_but_with_table_word_is_untouched(self):
        text = "a table follows:"

        assert format_markdown_tables(text) == text

    def test_trailing_newline_is_preserved(self):
        text = "| a |\n| --- |\n"

        assert format_markdown_tables(text).endswith("\n")

    def test_indented_fence_is_detected(self):
        text = "  ```\n| a |\n  ```"

        assert format_markdown_tables(text) == text


# ---------------------------------------------------------------------------
# compress_image_for_wecom
# ---------------------------------------------------------------------------


class TestCompressImageUnderLimit:
    def test_small_file_is_returned_verbatim(self, tmp_path):
        path = _write_png(tmp_path / "small.png")
        original = path.read_bytes()

        data, name = compress_image_for_wecom(str(path))

        assert data == original
        assert name == "small.png"

    def test_explicit_max_size_above_file_size(self, tmp_path):
        path = _write_png(tmp_path / "small.png")

        data, name = compress_image_for_wecom(
            str(path),
            max_size=10 * 1024 * 1024,
        )

        assert data == path.read_bytes()
        assert name == "small.png"

    def test_path_object_is_accepted(self, tmp_path):
        path = _write_png(tmp_path / "small.png")

        data, name = compress_image_for_wecom(path)

        assert data == path.read_bytes()
        assert name == "small.png"


class TestCompressImageOverLimit:
    def test_compressed_to_jpeg_with_new_name(self, tmp_path):
        path = _write_noisy_png(tmp_path / "big.png")
        limit = _jpeg_size(Image.open(path), 30)

        data, name = compress_image_for_wecom(str(path), max_size=limit)

        assert name == "big.jpg"
        assert len(data) <= limit
        assert Image.open(io.BytesIO(data)).format == "JPEG"

    def test_accepts_the_first_quality_that_fits(self, tmp_path):
        """The ladder stops as soon as a quality level fits."""
        path = _write_noisy_png(tmp_path / "big.png")
        image = Image.open(path)
        # Just below the best quality so attempt #1 misses and #2 hits.
        limit = _jpeg_size(image, 85) - 1
        assert _jpeg_size(image, 70) <= limit, "ladder precondition"

        saved = []
        real_save = Image.Image.save

        def recording_save(self, fp, *args, **kwargs):
            saved.append(kwargs.get("quality"))
            return real_save(self, fp, *args, **kwargs)

        with patch.object(Image.Image, "save", recording_save):
            data, name = compress_image_for_wecom(str(path), max_size=limit)

        assert saved == [85, 70]
        assert len(data) <= limit
        assert name == "big.jpg"

    def test_quality_ladder_runs_in_descending_order(self, tmp_path):
        path = _write_noisy_png(tmp_path / "big.png")
        limit = _jpeg_size(Image.open(path), 30) - 1

        saved = []
        real_save = Image.Image.save

        def recording_save(self, fp, *args, **kwargs):
            saved.append(kwargs.get("quality"))
            return real_save(self, fp, *args, **kwargs)

        with patch.object(Image.Image, "save", recording_save):
            compress_image_for_wecom(str(path), max_size=limit)

        # No quality fits; every attempt runs, then resizing takes over.
        assert saved[:4] == [85, 70, 50, 30]
        assert saved[4:] == [70] * (len(saved) - 4)

    def test_resize_path_when_quality_is_not_enough(self, tmp_path):
        path = _write_noisy_png(tmp_path / "big.png", size=(600, 600))
        image = Image.open(path)
        limit = _jpeg_size(image, 30) - 1
        first_resize = _jpeg_size(
            image.resize((450, 450), Image.Resampling.LANCZOS),
            70,
        )
        assert first_resize <= limit, "resize precondition"

        sizes = []
        real_resize = Image.Image.resize

        def recording_resize(self, size, *args, **kwargs):
            sizes.append(size)
            return real_resize(self, size, *args, **kwargs)

        with patch.object(Image.Image, "resize", recording_resize):
            data, name = compress_image_for_wecom(str(path), max_size=limit)

        assert name == "big.jpg"
        # The first scale that fits is accepted; the rest never run.
        assert sizes == [(450, 450)]
        assert len(data) <= limit

    def test_resize_scales_progressively(self, tmp_path):
        path = _write_noisy_png(tmp_path / "big.png", size=(800, 800))

        sizes = []
        real_resize = Image.Image.resize

        def recording_resize(self, size, *args, **kwargs):
            sizes.append(size)
            return real_resize(self, size, *args, **kwargs)

        with patch.object(Image.Image, "resize", recording_resize):
            compress_image_for_wecom(str(path), max_size=1)

        assert sizes == [(600, 600), (400, 400), (200, 200)]

    def test_smallest_version_is_returned_when_limit_is_unreachable(
        self,
        tmp_path,
    ):
        """Nothing fits: the smallest JPEG is still returned, not the PNG."""
        path = _write_noisy_png(tmp_path / "big.png")
        original = path.read_bytes()

        data, name = compress_image_for_wecom(str(path), max_size=1)

        assert name == "big.jpg"
        assert data != original
        assert len(data) < len(original)
        assert Image.open(io.BytesIO(data)).format == "JPEG"

    @pytest.mark.parametrize("mode", ["RGBA", "LA", "L", "P"])
    def test_non_rgb_modes_are_converted(self, tmp_path, mode):
        path = _write_noisy_png(tmp_path / f"mode-{mode}.png", mode=mode)
        limit = _jpeg_size(Image.open(path), 30)

        data, name = compress_image_for_wecom(str(path), max_size=limit)

        assert name == f"mode-{mode}.jpg"
        assert Image.open(io.BytesIO(data)).mode == "RGB"

    def test_rgba_transparency_gets_white_background(self, tmp_path):
        # Fully transparent noise: the RGB channels keep the PNG large,
        # the zero alpha channel must paint it white before JPEG.
        path = _write_noisy_png(
            tmp_path / "transparent.png",
            size=(300, 300),
            mode="RGBA",
            alpha=0,
        )
        limit = _jpeg_size(Image.open(path), 30)

        data, _ = compress_image_for_wecom(str(path), max_size=limit)

        converted = Image.open(io.BytesIO(data)).convert("RGB")
        assert converted.getpixel((150, 150)) == (255, 255, 255)

    def test_pil_unavailable_falls_back_to_original(self, tmp_path):
        path = _write_noisy_png(tmp_path / "big.png", size=(300, 300))
        original = path.read_bytes()
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("no PIL")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            data, name = compress_image_for_wecom(str(path), max_size=64)

        assert data == original
        assert name == "big.png"

    def test_corrupt_image_falls_back_to_original(self, tmp_path):
        path = tmp_path / "broken.png"
        path.write_bytes(b"not an image at all" * 400)

        data, name = compress_image_for_wecom(str(path), max_size=64)

        assert data == path.read_bytes()
        assert name == "broken.png"

    def test_save_failure_falls_back_to_original(self, tmp_path):
        path = _write_noisy_png(tmp_path / "big.png")
        original = path.read_bytes()

        with patch.object(
            Image.Image,
            "save",
            side_effect=OSError("disk full"),
        ):
            data, name = compress_image_for_wecom(str(path), max_size=2048)

        assert data == original
        assert name == "big.png"

    def test_default_limit_matches_wecom_constant(self):
        assert wecom_utils._WECOM_IMAGE_MAX_SIZE == pytest.approx(
            1.9 * 1024 * 1024,
        )
