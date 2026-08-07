# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
"""Multi-format document reading built on vendored Qwen-MM-Plugins renderers.

Renders a local document into page images (persisted by the caller-supplied
output directory) plus a bounded text excerpt.  Page images are meant to be
injected into the outer VLM context through the existing multimodal message
mechanism — never returned inline as base64.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Literal

from domain.errors import ValidationError
from vendor.mm_plugins.image_budget import (
    IMAGE_BUDGET_TOKENS,
    IMAGE_MIN_PIXELS,
    budget_to_pixels,
    smart_resize,
)
from vendor.mm_plugins.renderers import (
    DEFAULT_MAX_PAGES,
    SUPPORTED_EXTENSIONS,
    get_renderer,
    renderer_module_name,
)

DocumentBudget = Literal["small", "normal", "large"]

# Bounded text payload returned to the model alongside page images.
MAX_TEXT_EXCERPT_CHARS = 20_000

# Character bound for the indexed extracted text. The semantic index is a
# line-oriented canonical workspace file, so indexing is intentionally
# bounded rather than unlimited; the ratio of indexed to extracted text is
# reported as coverage instead of claiming completeness.
MAX_INDEXED_TEXT_CHARS = 2_000_000

# Web/HTML rendering needs Playwright; keep it off unless explicitly enabled.
DOC_READER_WEB_ENABLED_ENV = "CREATOR_DOC_READER_WEB_ENABLED"

SUPPORTED_DOCUMENT_EXTENSIONS = SUPPORTED_EXTENSIONS


@dataclass(frozen=True, slots=True)
class DocumentReadResult:
    format: str
    page_count: int
    pages_rendered: tuple[int, ...]
    page_images: tuple[Path, ...]
    text_excerpt: str
    # Bounded extracted text destined for the semantic index (NOT claimed
    # to be complete): extraction is capped per renderer (pages/rows) and
    # indexing at MAX_INDEXED_TEXT_CHARS. extracted_chars carries the
    # pre-cap size so callers can persist the coverage ratio.
    indexed_text: str
    extracted_chars: int
    # Renderer-stage extraction coverage: complete means no page/row cap
    # was hit; fraction is the known extracted share (None when the true
    # total is unknowable, e.g. a row-capped CSV read).
    extraction_complete: bool
    extraction_fraction: float | None
    notes: tuple[str, ...]


def is_supported_document(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS


def _web_rendering_enabled() -> bool:
    value = os.environ.get(DOC_READER_WEB_ENABLED_ENV, "0").strip().casefold()
    return value not in {"", "0", "false", "no", "off"}


def _resolve_soffice() -> str | None:
    from services.runtime_files.runtime_dependencies import resolve_libreoffice

    return resolve_libreoffice()


def _persist_page_image(
    img: Any,
    *,
    output_dir: Path,
    page: int,
    max_pixels: int,
) -> Path:
    """Resize one page image to the token budget and persist it as PNG."""
    from PIL import Image

    width, height = img.size
    target_h, target_w = smart_resize(
        height,
        width,
        IMAGE_MIN_PIXELS,
        max_pixels,
    )
    if (target_w, target_h) != (width, height):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    if img.mode not in {"RGB", "RGBA", "L"}:
        img = img.convert("RGB")
    destination = output_dir / f"page-{page:04d}.png"
    img.save(destination, format="PNG")
    return destination


def _read_document_sync(
    file_path: Path,
    *,
    output_dir: Path,
    pages: str | None,
    budget: DocumentBudget,
    max_pages: int,
) -> DocumentReadResult:
    if not file_path.is_file():
        raise ValidationError(f"document file does not exist: {file_path}")
    ext = file_path.suffix.lower()
    module_name = renderer_module_name(ext)
    if module_name is None:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise ValidationError(
            f"unsupported document format '{ext or file_path.name}'; "
            f"supported extensions: {supported}",
        )
    if module_name == "web" and not _web_rendering_enabled():
        raise ValidationError(
            "HTML rendering is disabled by default; set "
            f"{DOC_READER_WEB_ENABLED_ENV}=1 and install Playwright "
            "(pip install playwright && playwright install chromium) "
            "to enable it",
        )

    opts: dict[str, Any] = {"budget": budget, "max_pages": max_pages}
    if pages:
        opts["pages"] = pages
    if module_name == "office":
        opts["soffice"] = _resolve_soffice()

    renderer = get_renderer(ext)
    assert renderer is not None  # registry guarantees module presence
    try:
        blocks = renderer(str(file_path), **opts)
    except (RuntimeError, ValueError) as error:
        raise ValidationError(str(error)) from error

    doc_format = ext.lstrip(".")
    page_count = 1
    pages_rendered: list[int] = []
    notes: list[str] = []
    text_parts: list[str] = []
    full_text_parts: list[str] = []
    page_images: list[Path] = []
    extraction_complete = True
    extraction_fraction: float | None = 1.0

    max_pixels = budget_to_pixels(budget, IMAGE_BUDGET_TOKENS)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_sequence = 0
    for block in blocks:
        block_type = block.get("type")
        if block_type == "meta":
            doc_format = str(block.get("format") or doc_format)
            page_count = max(1, int(block.get("page_count") or 1))
            pages_rendered = [
                int(item) for item in block.get("pages_rendered") or []
            ]
        elif block_type == "image":
            image_sequence += 1
            page = int(block.get("page") or image_sequence)
            page_images.append(
                _persist_page_image(
                    block["image"],
                    output_dir=output_dir,
                    page=page,
                    max_pixels=max_pixels,
                ),
            )
        elif block_type == "text":
            text = str(block.get("text") or "").strip()
            if text:
                text_parts.append(text)
        elif block_type == "full_text":
            text = str(block.get("text") or "").strip()
            if text:
                full_text_parts.append(text)
        elif block_type == "extraction_note":
            extraction_complete = False
            note = str(block.get("text") or "").strip()
            if note:
                notes.append(note)
            total = block.get("total")
            extracted = block.get("extracted")
            if (
                extraction_fraction is not None
                and isinstance(total, int)
                and isinstance(extracted, int)
                and total > 0
            ):
                extraction_fraction = min(
                    extraction_fraction,
                    extracted / total,
                )
            else:
                # The true total is unknown: the honest fraction is too.
                extraction_fraction = None

    if not pages_rendered:
        pages_rendered = sorted(
            {
                int(str(path.stem).removeprefix("page-"))
                for path in page_images
            },
        )
    if page_count > len(pages_rendered) and page_images:
        notes.append(
            f"rendered {len(pages_rendered)} of {page_count} pages; "
            "request more via the pages parameter",
        )

    text_excerpt = "\n\n".join(text_parts)
    # Renderers emitting dedicated full_text blocks decouple indexing from
    # the rendered/display scope; others index exactly what was rendered.
    indexed_text = (
        "\n\n".join(full_text_parts) if full_text_parts else text_excerpt
    )
    extracted_chars = len(indexed_text)
    if extracted_chars > MAX_INDEXED_TEXT_CHARS:
        indexed_text = indexed_text[:MAX_INDEXED_TEXT_CHARS]
        notes.append(
            "extracted text exceeds the indexing bound: indexed "
            f"{MAX_INDEXED_TEXT_CHARS} of {extracted_chars} characters "
            "(see text coverage)",
        )
    if len(text_excerpt) > MAX_TEXT_EXCERPT_CHARS:
        text_excerpt = text_excerpt[:MAX_TEXT_EXCERPT_CHARS]
        notes.append(
            f"text excerpt truncated to {MAX_TEXT_EXCERPT_CHARS} characters"
            "; the extracted text is indexed separately (see text coverage)",
        )

    return DocumentReadResult(
        format=doc_format,
        page_count=page_count,
        pages_rendered=tuple(pages_rendered),
        page_images=tuple(page_images),
        text_excerpt=text_excerpt,
        indexed_text=indexed_text,
        extracted_chars=extracted_chars,
        extraction_complete=extraction_complete,
        extraction_fraction=(
            extraction_fraction if not extraction_complete else 1.0
        ),
        notes=tuple(notes),
    )


async def read_document(
    file_path: Path,
    *,
    output_dir: Path,
    pages: str | None = None,
    budget: DocumentBudget = "normal",
    max_pages: int = DEFAULT_MAX_PAGES,
) -> DocumentReadResult:
    """Render `file_path` into page images + text excerpt under `output_dir`."""
    return await asyncio.to_thread(
        _read_document_sync,
        file_path,
        output_dir=output_dir,
        pages=pages,
        budget=budget,
        max_pages=max_pages,
    )


__all__ = [
    "DOC_READER_WEB_ENABLED_ENV",
    "DocumentBudget",
    "DocumentReadResult",
    "MAX_INDEXED_TEXT_CHARS",
    "MAX_TEXT_EXCERPT_CHARS",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "is_supported_document",
    "read_document",
]
