# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/core/qwen_media_toolkit_core/renderers/pdf.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render PDF pages as image + text content blocks via pypdfium2 (raster + text).

Creator modifications: page images are returned as PIL images tagged with
1-based page numbers; base64 encoding, budget resizing and response-size
capping moved to ``services/document_reader.py``. Full-text extraction is
decoupled from the rendered page range: every page's text layer (up to
``max_text_pages``) is emitted as ``full_text`` blocks for deterministic
indexing regardless of which pages were rasterized.
"""

from __future__ import annotations

from typing import Any

from vendor.media_toolkit.renderers import (
    DEFAULT_MAX_PAGES,
    meta_block,
    parse_pages,
)

# Text-layer extraction covers the whole document independently from the
# rasterized page subset, bounded for pathological page counts.
DEFAULT_MAX_TEXT_PAGES = 500


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    """Render document pages as content blocks (image + extracted text per page)."""
    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise RuntimeError(
            "Missing dependency pypdfium2 — install with: pip install pypdfium2",
        ) from error

    dpi = opts.get("dpi", 150)
    max_pages = opts.get("max_pages", DEFAULT_MAX_PAGES)
    max_text_pages = opts.get("max_text_pages", DEFAULT_MAX_TEXT_PAGES)

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    doc_type = opts.get("doc_type") or ext.upper() or "DOC"

    doc = pdfium.PdfDocument(path)
    try:
        total = len(doc)

        pages_str = opts.get("pages")
        if pages_str:
            page_indices = parse_pages(pages_str, total)
        else:
            page_indices = list(range(min(total, max_pages)))

        text_indices = sorted(
            set(page_indices) | set(range(min(total, max_text_pages))),
        )
        page_texts = _extract_page_texts(doc, text_indices)

        blocks: list[dict[str, Any]] = [
            meta_block(
                doc_type.lower(),
                total,
                [idx + 1 for idx in page_indices],
            ),
        ]
        blocks.append(
            {
                "type": "text",
                "text": (
                    f"Total pages: {total} | "
                    f"Showing pages: {_format_range(page_indices)}"
                ),
            },
        )
        for idx in page_indices:
            img = _render_pdf_page(doc[idx], dpi)
            blocks.append(
                {
                    "type": "image",
                    "image": img,
                    "page": idx + 1,
                    "label": f"[Page {idx + 1} View]",
                },
            )
            page_text = page_texts.get(idx, "").strip()
            if page_text:
                blocks.append(
                    {
                        "type": "text",
                        "text": f"[Page {idx + 1} Extracted Text]\n{page_text}",
                        "page": idx + 1,
                    },
                )
        for idx in text_indices:
            page_text = page_texts.get(idx, "").strip()
            if page_text:
                blocks.append(
                    {
                        "type": "full_text",
                        "text": f"[Page {idx + 1}]\n{page_text}",
                        "page": idx + 1,
                    },
                )
        if total > max_text_pages:
            # Structured extraction coverage so the caller can report an
            # honest ratio instead of claiming completeness.
            blocks.append(
                {
                    "type": "extraction_note",
                    "text": (
                        f"text extraction capped at {max_text_pages} of "
                        f"{total} pages"
                    ),
                    "unit": "pages",
                    "extracted": max_text_pages,
                    "total": total,
                },
            )
        return blocks
    finally:
        doc.close()


def _render_pdf_page(page, dpi: int = 150):
    """Rasterize a pypdfium2 PdfPage to a PIL Image at `dpi` (scale = dpi / 72)."""
    return page.render(scale=dpi / 72).to_pil()


def _extract_page_texts(doc, page_indices: list[int]) -> dict[int, str]:
    """Extract each page's text layer (0-based keys) via pypdfium2's text API.

    Reuses the already-open document (no second file open) — same PDFium
    backend as rendering.
    """
    texts: dict[int, str] = {}
    total = len(doc)
    for idx in page_indices:
        if not 0 <= idx < total:
            continue
        try:
            textpage = doc[idx].get_textpage()
            try:
                text = textpage.get_text_bounded()
            finally:
                textpage.close()
        except Exception:  # pylint: disable=broad-except
            continue
        if text and text.strip():
            texts[idx] = text
    return texts


def _format_range(indices: list[int]) -> str:
    """Format 0-based page indices as a compact 1-based range, e.g. [0,1,2,4] -> "1-3, 5"."""
    if not indices:
        return ""
    groups: list[list[int]] = []
    for idx in sorted(indices):
        page = idx + 1
        if groups and page == groups[-1][-1] + 1:
            groups[-1].append(page)
        else:
            groups.append([page])
    return ", ".join(
        str(g[0]) if len(g) == 1 else f"{g[0]}-{g[-1]}" for g in groups
    )
