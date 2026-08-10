# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/core/qwen_mm_plugins_core/renderers/svg.py
#   with svg_to_image inlined from src/shared/image.py.
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render SVG files to an image content block via resvg (resvg-py)."""

from __future__ import annotations

import io
from typing import Any


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    """Rasterize an SVG file to a single image content block."""
    from vendor.mm_plugins.renderers import meta_block

    dpi = opts.get("dpi", 150)
    doc_type = opts.get("doc_type") or "SVG"

    try:
        img = _svg_to_image(svg_path=path, dpi=dpi)
    except ImportError as error:
        raise RuntimeError(
            "Missing dependency resvg-py — install with: pip install resvg-py",
        ) from error

    return [
        meta_block(doc_type.lower(), 1, [1]),
        {"type": "image", "image": img, "page": 1, "label": "[SVG View]"},
    ]


def _svg_to_image(
    svg_string: str | None = None,
    svg_path: str | None = None,
    dpi: int = 150,
):
    """Rasterize an SVG (string or file path) to a PIL Image via resvg (zoom = dpi / 96).

    Composites onto an opaque white background so transparent SVGs don't show
    a bare alpha channel (which most viewers paint black).
    """
    import resvg_py
    from PIL import Image

    png = bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg_string,
            svg_path=svg_path,
            zoom=dpi / 96,
        ),
    )
    img = Image.open(io.BytesIO(png))
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    return img
