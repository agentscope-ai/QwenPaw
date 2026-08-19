# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), github/main commit f9d5741.
# Upstream path: src/capabilities/core/qwen_media_toolkit_core/renderers/drawio.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render DrawIO (.drawio) diagrams to images via SVG synthesis + resvg.

Creator modifications: ``lxml`` replaced by the stdlib ``xml.etree`` (no
new dependency; DrawIO files are small, trusted local uploads already
size-capped by the asset layer); SVG rasterization reuses this registry's
``svg`` renderer helper; emits meta + PIL image blocks per diagram page
instead of upstream base64 blocks.
"""

from __future__ import annotations

import base64
import urllib.parse
import zlib
from typing import Any
from xml.etree import ElementTree  # nosec B405 - local size-capped uploads
from xml.sax.saxutils import escape


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    from vendor.media_toolkit.renderers import (
        DEFAULT_MAX_PAGES,
        meta_block,
        parse_pages,
    )
    from vendor.media_toolkit.renderers.svg import _svg_to_image

    tree = ElementTree.parse(path)  # nosec B314
    root = tree.getroot()

    diagrams = root.findall(".//diagram")
    if not diagrams:
        raise ValueError("No diagrams found in DrawIO file")

    pages = opts.get("pages")
    indices = (
        parse_pages(pages, len(diagrams))
        if pages
        else list(
            range(
                min(len(diagrams), opts.get("max_pages", DEFAULT_MAX_PAGES)),
            ),
        )
    )
    content: list[dict[str, Any]] = [
        meta_block("drawio", len(diagrams), [i + 1 for i in indices]),
    ]

    for i in indices:
        diagram = diagrams[i]
        svg_content = _diagram_to_svg(diagram)
        if not svg_content:
            continue
        img = _svg_to_image(svg_string=svg_content, dpi=150)
        name = diagram.get("name", f"Diagram {i + 1}")
        content.append(
            {
                "type": "image",
                "image": img,
                "page": i + 1,
                "label": f"[{name}]",
            },
        )

    if len(content) == 1:
        raise ValueError(
            "Failed to extract renderable content from DrawIO file",
        )
    return content


def _diagram_to_svg(diagram) -> str | None:
    """Extract diagram content and convert to SVG."""
    text = (diagram.text or "").strip()
    if not text:
        mx = diagram.find(".//mxGraphModel")
        if mx is not None:
            return _mxgraph_to_svg(mx)
        return None

    try:
        decoded = base64.b64decode(text)
        xml_str = zlib.decompress(decoded, -zlib.MAX_WBITS).decode("utf-8")
    except Exception:
        try:
            xml_str = urllib.parse.unquote(text)
        except Exception:
            return None

    try:
        inner = ElementTree.fromstring(xml_str.encode("utf-8"))  # nosec B314
        if inner.tag == "mxGraphModel":
            return _mxgraph_to_svg(inner)
    except Exception:
        pass

    return None


def _mxgraph_to_svg(mx_model) -> str:
    """Convert mxGraphModel XML to a basic SVG representation."""
    cells = mx_model.findall(".//mxCell")

    svg_elements = []
    max_x, max_y = 100.0, 100.0

    for cell in cells:
        geom = cell.find("mxGeometry")
        if geom is None:
            continue

        x = float(geom.get("x", 0))
        y = float(geom.get("y", 0))
        w = float(geom.get("width", 0))
        h = float(geom.get("height", 0))

        max_x = max(max_x, x + w + 20)
        max_y = max(max_y, y + h + 20)

        style = cell.get("style", "")
        label = cell.get("value", "")
        is_edge = cell.get("edge") == "1"

        if is_edge:
            source_x = x
            source_y = y
            target_x = x + w if w else x + 100
            target_y = y + h if h else y
            svg_elements.append(
                f'<line x1="{source_x}" y1="{source_y}" x2="{target_x}" y2="{target_y}" '
                f'stroke="#333" stroke-width="1.5" marker-end="url(#arrow)"/>',
            )
        elif w > 0 and h > 0:
            fill = "#ffffff"
            stroke = "#333333"
            if "rounded=1" in style:
                svg_elements.append(
                    f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" ry="8" '
                    f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
                )
            elif "ellipse" in style:
                cx, cy = x + w / 2, y + h / 2
                svg_elements.append(
                    f'<ellipse cx="{cx}" cy="{cy}" rx="{w / 2}" ry="{h / 2}" '
                    f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
                )
            elif "rhombus" in style:
                points = (
                    f"{x + w / 2},{y} {x + w},{y + h / 2} "
                    f"{x + w / 2},{y + h} {x},{y + h / 2}"
                )
                svg_elements.append(
                    f'<polygon points="{points}" fill="{fill}" '
                    f'stroke="{stroke}" stroke-width="1.5"/>',
                )
            else:
                svg_elements.append(
                    f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                    f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
                )

            if label:
                tx = x + w / 2
                ty = y + h / 2
                font_size = min(14, max(8, int(h * 0.3)))
                svg_elements.append(
                    f'<text x="{tx}" y="{ty}" text-anchor="middle" dominant-baseline="central" '
                    f'font-family="sans-serif" font-size="{font_size}">{escape(label)}</text>',
                )

    arrow_marker = (
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#333"/></marker></defs>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{max_x}" height="{max_y}" '
        f'viewBox="0 0 {max_x} {max_y}">'
        f"{arrow_marker}"
        f'<rect width="100%" height="100%" fill="white"/>'
        f"{''.join(svg_elements)}"
        f"</svg>"
    )
