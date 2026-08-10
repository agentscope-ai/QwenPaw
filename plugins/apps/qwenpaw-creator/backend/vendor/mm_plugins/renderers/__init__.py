# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path:
#   src/capabilities/core/qwen_mm_plugins_core/renderers/__init__.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Renderer registry: maps file extensions to render functions.

Creator modifications: the registry is trimmed to shipped formats, renderers
return content blocks carrying PIL images (``{"type": "image", "image": ...,
"page": ...}``) plus a leading ``{"type": "meta", ...}`` block instead of
base64 MCP blocks, and intermediate-PDF caching is caller-owned.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from . import code

# Default page/surface cap for multi-page renderers when the caller gives
# no `pages`.
DEFAULT_MAX_PAGES = 20

# ext -> (module_name_relative_to_this_package, function_name)
_REGISTRY: dict[str, tuple[str, str]] = {
    # PDF (pypdfium2) + SVG (resvg)
    ".pdf": ("pdf", "render"),
    ".svg": ("svg", "render"),
    # Office (LibreOffice -> PDF -> pypdfium2)
    ".doc": ("office", "render"),
    ".docx": ("office", "render"),
    ".ppt": ("office", "render"),
    ".pptx": ("office", "render"),
    ".vsdx": ("office", "render"),
    # Data tables
    ".csv": ("data", "render"),
    ".xlsx": ("data", "render"),
    # Web / HTML (config-gated by the caller; Playwright optional)
    ".html": ("web", "render"),
    ".htm": ("web", "render"),
    ".mhtml": ("web", "render"),
    # Subtitles (returns text, not images)
    ".srt": ("subtitle", "render"),
    ".vtt": ("subtitle", "render"),
    ".ass": ("subtitle", "render"),
    # Jupyter notebooks
    ".ipynb": ("notebook", "render"),
    # Plain text / logs — rendered as an unhighlighted fenced block by the
    # code renderer
    ".txt": ("code", "render"),
    ".text": ("code", "render"),
    ".log": ("code", "render"),
    ".md": ("code", "render"),
}

# The code renderer highlights ~30 languages; register every one not already
# claimed by a more specific renderer so document reading accepts a
# .py/.json/… file.
for _ext in code._EXT_TO_LANG:  # pylint: disable=protected-access
    _REGISTRY.setdefault(_ext, ("code", "render"))

SUPPORTED_EXTENSIONS = frozenset(_REGISTRY)


def get_renderer(ext: str) -> Callable[..., list[dict[str, Any]]] | None:
    """Return the render function for a file extension, or None."""
    ext = ext.lower()
    spec = _REGISTRY.get(ext)
    if spec is None:
        return None
    mod_name, func_name = spec
    mod = importlib.import_module(f".{mod_name}", package=__name__)
    return getattr(mod, func_name)


def renderer_module_name(ext: str) -> str | None:
    """Return the registry module name for an extension without importing it."""
    spec = _REGISTRY.get(ext.lower())
    return spec[0] if spec is not None else None


def meta_block(
    doc_format: str,
    page_count: int,
    pages_rendered: list[int],
) -> dict[str, Any]:
    """Leading block describing the rendered document (Creator addition)."""
    return {
        "type": "meta",
        "format": doc_format,
        "page_count": page_count,
        "pages_rendered": list(pages_rendered),
    }


def fig_to_image(fig, pad_inches: float = 0.1):
    """Rasterize a matplotlib Figure to a PIL Image, closing the figure."""

    import io

    import matplotlib.pyplot as plt
    from PIL import Image

    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=150,
        bbox_inches="tight",
        pad_inches=pad_inches,
    )
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


# CJK-capable sans families across macOS / Linux / Windows, best first.
_CJK_FONT_CANDIDATES = (
    "PingFang SC",
    "Hiragino Sans GB",
    "Heiti SC",
    "Arial Unicode MS",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "Microsoft YaHei",
    "SimHei",
)


def configure_matplotlib_cjk() -> None:
    """Prefer an installed CJK font so table images keep non-Latin text.

    Creator addition: matplotlib's default DejaVu Sans has no CJK glyphs,
    which turns Chinese spreadsheet content into tofu boxes.
    """
    try:
        from matplotlib import font_manager, rcParams
    except ImportError:
        return
    installed = {font.name for font in font_manager.fontManager.ttflist}
    chosen = [name for name in _CJK_FONT_CANDIDATES if name in installed]
    if not chosen:
        return
    current = [
        name for name in rcParams["font.sans-serif"] if name not in chosen
    ]
    rcParams["font.sans-serif"] = chosen + current
    rcParams["axes.unicode_minus"] = False


def parse_pages(pages_str: str, total_pages: int) -> list[int]:
    """Parse a page range string into 0-based page indices.

    Accepts: "1-5", "3", "1,3,5-8".  Input is 1-based, output is 0-based.
    """
    result = []
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = max(1, int(start_s.strip()))
            end = min(total_pages, int(end_s.strip()))
            result.extend(range(start - 1, end))
        else:
            idx = int(part.strip()) - 1
            if 0 <= idx < total_pages:
                result.append(idx)
    if result:
        return sorted(set(result))
    return list(range(min(total_pages, DEFAULT_MAX_PAGES)))
