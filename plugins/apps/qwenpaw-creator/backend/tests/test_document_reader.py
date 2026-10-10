# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Per-format fixtures for the vendored document reader."""

from __future__ import annotations

import asyncio
import itertools
import random
from pathlib import Path

from PIL import Image
import pytest

from domain.errors import ValidationError
from services.document_reader import (
    MAX_INDEXED_TEXT_CHARS,
    is_supported_document,
    read_document,
)
from vendor.media_toolkit.image_budget import (
    IMAGE_BUDGET_TOKENS,
    IMAGE_MIN_PIXELS,
    TOKEN_SIZE,
    budget_to_pixels,
    smart_resize,
)


def _make_pdf(path: Path, pages: int = 3) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    with PdfPages(path) as pdf:
        for number in range(1, pages + 1):
            fig = plt.figure(figsize=(4, 3))
            fig.text(0.1, 0.5, f"Creator Doc Page {number}: storyboard beats")
            pdf.savefig(fig)
            plt.close(fig)


def _read(path: Path, output_dir: Path, **kwargs):
    return asyncio.run(read_document(path, output_dir=output_dir, **kwargs))


def _write_csv(path: Path, rows: int) -> None:
    lines = ["scene,cost"] + [f"scene-{n},{n}" for n in range(1, rows)]
    lines.append("final-unique-scene,9999")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_smart_resize_never_exceeds_budget() -> None:
    # The grid snap must never overshoot the tier's pixel budget (A3).
    rng = random.Random(7)
    dims = [1, 2, 10, 31, 32, 33, 100, 864, 1216, 4096, 10000, 50000]
    cases = list(itertools.product(dims, dims)) + [
        (rng.randint(1, 60000), rng.randint(1, 60000)) for _ in range(500)
    ]
    for budget in ("small", "normal", "large"):
        max_pixels = budget_to_pixels(budget, IMAGE_BUDGET_TOKENS)
        for height, width in cases:
            h, w = smart_resize(height, width, IMAGE_MIN_PIXELS, max_pixels)
            assert h % TOKEN_SIZE == 0 and w % TOKEN_SIZE == 0
            assert h >= TOKEN_SIZE and w >= TOKEN_SIZE
            assert h * w <= max_pixels, (budget, height, width)


def test_pdf_render_grid_alignment_page_range_and_text_cap(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "script.pdf"
    _make_pdf(source, pages=4)
    result = _read(source, tmp_path / "pages")

    assert result.format == "pdf" and result.page_count == 4
    assert result.pages_rendered == (1, 2, 3, 4)
    normal_budget = budget_to_pixels("normal", IMAGE_BUDGET_TOKENS)
    for page, image_path in zip(result.pages_rendered, result.page_images):
        assert image_path.name == f"page-{page:04d}.png"
        with Image.open(image_path) as img:
            width, height = img.size
        assert width % TOKEN_SIZE == 0 and height % TOKEN_SIZE == 0
        assert width * height <= normal_budget
    assert "Creator Doc Page 1: storyboard beats" in result.text_excerpt
    subset = _read(source, tmp_path / "subset", pages="2,4")
    assert subset.pages_rendered == (2, 4)
    # Full text is decoupled from the render subset: pages outside the
    # range still contribute their text layer to indexed_text.
    marker = "Creator Doc Page 3: storyboard beats"
    assert marker in subset.indexed_text
    assert marker not in subset.text_excerpt
    # With a known page total a text-page cap reports the exact share.
    target = "vendor.media_toolkit.renderers.pdf.DEFAULT_MAX_TEXT_PAGES"
    monkeypatch.setattr(target, 2)
    capped = _read(source, tmp_path / "capped")
    assert capped.extraction_complete is False
    assert capped.extraction_fraction == 0.5
    assert any("capped at 2 of 4 pages" in note for note in capped.notes)


def test_csv_display_cap_and_row_cap_extraction_reporting(
    tmp_path,
    monkeypatch,
) -> None:
    # CR repro: a 2002-row CSV keeps its last row in the indexed full
    # text even though the display table caps far earlier.
    source = tmp_path / "big.csv"
    _write_csv(source, 2002)
    result = _read(source, tmp_path / "pages")

    assert result.format == "csv" and result.page_count == 1
    assert len(result.page_images) == 1
    assert "final-unique-scene" not in result.text_excerpt
    assert "final-unique-scene" in result.indexed_text
    # CR repro: a row-capped table must not pretend complete extraction;
    # the true row total is unknowable, so the fraction is None.
    target = "vendor.media_toolkit.renderers.data.FULL_TEXT_ROW_CAP"
    monkeypatch.setattr(target, 50)
    capped = _read(source, tmp_path / "capped")
    assert "final-unique-scene" not in capped.indexed_text
    assert capped.extraction_complete is False
    assert capped.extraction_fraction is None
    assert any("capped at 50 rows" in note for note in capped.notes)


def test_indexed_text_bound_is_honest_about_truncation(tmp_path) -> None:
    # Indexing is intentionally bounded: oversized text is cut at the
    # bound and the coverage numbers report it, not "full text".
    source = tmp_path / "huge.txt"
    marker = "末尾唯一标记：星光不灭。"
    text = ("剧情推进。" * 100 + "\n") * 4200 + marker + "\n"
    source.write_text(text, encoding="utf-8")
    result = _read(source, tmp_path / "pages")

    assert result.extracted_chars > MAX_INDEXED_TEXT_CHARS
    assert len(result.indexed_text) == MAX_INDEXED_TEXT_CHARS
    assert marker not in result.indexed_text
    assert any("indexing bound" in note for note in result.notes)
    # The indexing bound is separate from renderer-stage extraction.
    assert result.extraction_complete is True


def test_xlsx_sheets_map_to_pages(tmp_path) -> None:
    import pandas as pd

    source = tmp_path / "plan.xlsx"
    frame = pd.DataFrame({"shot": ["s1", "s2"], "len": [3, 5]})
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Shots", index=False)
        frame.to_excel(writer, sheet_name="Cast", index=False)
    result = _read(source, tmp_path / "pages")

    assert result.format == "xlsx" and result.page_count == 2
    assert result.pages_rendered == (1, 2)
    assert "Shots" in result.text_excerpt and "Cast" in result.text_excerpt


def test_text_only_renderer_srt(tmp_path) -> None:
    srt = tmp_path / "dialogue.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\n猫走进画面\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n镜头拉远\n",
        encoding="utf-8",
    )
    result = _read(srt, tmp_path / "pages")
    assert result.format == "srt" and result.page_images == ()
    assert "2 entries" in result.text_excerpt
    assert "猫走进画面" in result.text_excerpt


def test_readable_errors_for_unsupported_inputs(tmp_path, monkeypatch):
    assert is_supported_document("deck.PPTX")
    assert not is_supported_document("archive.zip")
    zipped = tmp_path / "bundle.zip"
    zipped.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValidationError, match="unsupported document format"):
        _read(zipped, tmp_path / "pages")
    target = "services.document_reader._resolve_soffice"
    monkeypatch.setattr(target, lambda: None)
    docx = tmp_path / "brief.docx"
    docx.write_bytes(b"PK\x03\x04fake-docx")
    with pytest.raises(ValidationError, match="LibreOffice is required"):
        _read(docx, tmp_path / "pages")
    monkeypatch.delenv("CREATOR_DOC_READER_WEB_ENABLED", raising=False)
    html = tmp_path / "page.html"
    html.write_text("<html><body>hello</body></html>", encoding="utf-8")
    with pytest.raises(ValidationError, match="WEB_ENABLED"):
        _read(html, tmp_path / "pages")
