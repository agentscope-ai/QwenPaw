# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw_channel_wecom.utils`.

Covers GFM table normalisation for the WeCom renderer (including the
code-fence passthrough) and the image compression pipeline that keeps
uploads under the WeCom size limit.
"""
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/wecom"))

import builtins
import io
import random
from unittest.mock import patch

import pytest
from PIL import Image

from qwenpaw_channel_wecom.utils import (
    compress_image_for_wecom,
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


# ---------------------------------------------------------------------------
# format_markdown_tables
# ---------------------------------------------------------------------------




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
