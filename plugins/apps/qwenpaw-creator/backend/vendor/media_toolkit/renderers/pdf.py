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

# A page whose extractable text is under this many characters cannot hold a
# real script body: it is a running header, a page number or a short title.
_SPARSE_PAGE_TEXT_CHARS = 80
# Raster images covering at least this fraction of the page *in total* are a
# full-page scan (the body lives in the raster), not a small decorative
# picture or logo.
_DOMINANT_IMAGE_COVERAGE = 0.6
# A no-text-layer page that draws at least this many *non-background* vector
# objects (paths / shadings / forms) carries visible body content that cannot
# be extracted as text -- text outlined to curves (转曲) or vector art.  A
# genuinely blank page paints at most a single full-page background path, so
# it stays below this threshold and is never rejected.
_MIN_VECTOR_CONTENT_OBJECTS = 3
# A vector object whose bounds cover at least this fraction of the page is a
# background fill or a page border, not body content, and is excluded from the
# count above.
_BACKGROUND_VECTOR_COVERAGE = 0.95
# A single vector path carrying at least this many segments is text outlined to
# curves and merged into one object (Ghostscript/ps2pdf, Illustrator/InDesign
# flatten), so one such path is body content even when the object count stays
# at 1.  A blank page's full-page background is a rectangle of only ~4-5
# segments, far below this, so it is never mistaken for a merged outline.
_MIN_MERGED_OUTLINE_SEGMENTS = 12


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
        page_texts, text_gaps = _extract_page_texts(doc, text_indices)

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
        # Pages with visible content but no extractable text layer are
        # reported one by one, so a text-only caller (script direct-landing)
        # can refuse to land half a script instead of silently dropping the
        # scanned/rasterized pages.  Genuinely blank pages are not gaps.
        for idx, reason in text_gaps:
            blocks.append(
                {
                    "type": "page_text_gap",
                    "page": idx + 1,
                    "reason": reason,
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


def _extract_page_texts(
    doc,
    page_indices: list[int],
) -> tuple[dict[int, str], list[tuple[int, str]]]:
    """Extract each page's text layer (0-based keys) via pypdfium2's text API.

    Reuses the already-open document (no second file open) — same PDFium
    backend as rendering.

    Returns ``(texts, gaps)``.  ``texts`` maps a page index to its extracted
    text (only pages that yielded a non-empty text layer).  ``gaps`` lists
    ``(page_index, reason)`` for pages whose *visible* content could not be
    turned into text: ``"extraction-failed"`` when pdfium's text API raised,
    ``"image-only"`` when the page has no text layer yet carries a raster
    image (a scanned/rasterized page), or ``"vector-content"`` when the page
    has neither a text layer nor a raster image yet draws many non-background
    vector objects (text outlined to curves / 转曲, or vector art).  A page
    with no text, no raster image and no body vector content is genuinely
    blank and is deliberately *not* a gap, so ordinary documents with blank
    pages are never rejected.
    """
    texts: dict[int, str] = {}
    gaps: list[tuple[int, str]] = []
    total = len(doc)
    for idx in page_indices:
        if not 0 <= idx < total:
            continue
        page = doc[idx]
        try:
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_bounded()
            finally:
                textpage.close()
        except Exception:  # pylint: disable=broad-except
            # The text layer could not be read at all; the page may still
            # carry content, so report it rather than skipping it silently.
            gaps.append((idx, "extraction-failed"))
            continue
        if text and text.strip():
            texts[idx] = text
            # A copyable running header or page number must not be mistaken
            # for a complete text layer.  When the page body sits in a
            # full-page raster image yet only sparse text (header / page
            # number / short title) is extractable, report the page so a
            # text-only caller (script direct-landing) refuses to land half a
            # script instead of silently dropping the scanned body.  A dense
            # text layer (a properly OCR'd scan) or a small decorative image
            # is deliberately *not* a gap.
            if _page_text_is_sparse(text) and (
                _dominant_image_coverage(page) >= _DOMINANT_IMAGE_COVERAGE
            ):
                gaps.append((idx, "image-body-uncovered"))
        elif _page_has_image_object(page):
            # Visible raster content with no text layer: a scanned page.
            gaps.append((idx, "image-only"))
        elif (
            _page_non_background_vector_objects(page)
            >= _MIN_VECTOR_CONTENT_OBJECTS
        ):
            # No text layer and no raster image, yet the page draws many
            # non-background vector objects: text outlined to curves (转曲)
            # or vector art.  Its body cannot be extracted as text, so report
            # it instead of treating it as blank and silently dropping it.  A
            # genuinely blank page carries only a background path and stays
            # below the threshold.
            gaps.append((idx, "vector-content"))
    return texts, gaps


def _page_has_image_object(page) -> bool:
    """True when a pypdfium2 page carries at least one raster image object."""
    try:
        import pypdfium2 as pdfium

        for _ in page.get_objects(filter=(pdfium.raw.FPDF_PAGEOBJ_IMAGE,)):
            return True
    except Exception:  # pylint: disable=broad-except
        return False
    return False


def _page_non_background_vector_objects(page) -> int:
    """Count visible non-background vector objects (paths/shadings/forms).

    Text outlined to curves (转曲) leaves no text layer and no raster image,
    only vector paths -- either one path per glyph stroke (many objects) or,
    when the exporter merges them (Ghostscript/ps2pdf, Illustrator flatten), a
    single path carrying many segments.  A blank page still paints one
    full-page background rectangle, so full-page objects are excluded from the
    count, and a path only counts as a merged outline once its segment count
    clears ``_MIN_MERGED_OUTLINE_SEGMENTS`` -- such a path short-circuits to the
    object threshold so a lone merged outline still reports.  Returns ``0`` when
    the page carries no vector object or its bounds cannot be read.
    """
    try:
        import pypdfium2 as pdfium

        area = page.get_width() * page.get_height()
        count = 0
        for obj in page.get_objects(
            filter=(
                pdfium.raw.FPDF_PAGEOBJ_PATH,
                pdfium.raw.FPDF_PAGEOBJ_SHADING,
                pdfium.raw.FPDF_PAGEOBJ_FORM,
            ),
        ):
            if area <= 0:
                count += 1
                continue
            try:
                left, bottom, right, top = obj.get_bounds()
            except Exception:  # pylint: disable=broad-except
                count += 1
                continue
            coverage = (max(0.0, right - left) * max(0.0, top - bottom)) / area
            if coverage < _BACKGROUND_VECTOR_COVERAGE:
                count += 1
            # A single path with many segments is a merged outline (转曲): one
            # such object is body content even though the count stays at 1.  A
            # blank page's background rectangle has only ~4-5 segments.
            if (
                pdfium.raw.FPDFPageObj_GetType(obj)
                == pdfium.raw.FPDF_PAGEOBJ_PATH
            ):
                try:
                    segments = pdfium.raw.FPDFPath_CountSegments(obj)
                except Exception:  # pylint: disable=broad-except
                    segments = 0
                if segments >= _MIN_MERGED_OUTLINE_SEGMENTS:
                    return max(count, _MIN_VECTOR_CONTENT_OBJECTS)
        return count
    except Exception:  # pylint: disable=broad-except
        return 0


def _page_text_is_sparse(text: str) -> bool:
    """True when a page's text layer is too short to be a real script body."""
    return len(text.strip()) < _SPARSE_PAGE_TEXT_CHARS


def _dominant_image_coverage(page) -> float:
    """Total fraction of the page area covered by raster image objects.

    Accumulates every image's area (capped at the whole page) instead of
    keeping only the largest single one, so a scanned body a producer split
    into several tiles still counts as a full-page scan.  Overlapping images
    can double-count, which only ever pushes a page *toward* the
    dominant-image threshold; under the sparse-text conjunction that stays
    conservative -- a dense text layer (a properly OCR'd scan) short-circuits
    before this runs, and a plain text page with only small decorative
    pictures stays well below the threshold.  Returns ``0.0`` when the page
    carries no image, or its bounds cannot be read.
    """
    try:
        import pypdfium2 as pdfium

        page_area = page.get_width() * page.get_height()
        if page_area <= 0:
            return 0.0
        covered = 0.0
        for obj in page.get_objects(filter=(pdfium.raw.FPDF_PAGEOBJ_IMAGE,)):
            try:
                left, bottom, right, top = obj.get_bounds()
            except Exception:  # pylint: disable=broad-except
                continue
            covered += max(0.0, right - left) * max(0.0, top - bottom)
        return min(1.0, covered / page_area)
    except Exception:  # pylint: disable=broad-except
        return 0.0


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
