# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Per-format fixtures for the vendored document reader."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from domain.errors import ValidationError
from services.document_reader import (
    MAX_INDEXED_TEXT_CHARS,
    MAX_TEXT_EXCERPT_CHARS,
    is_supported_document,
    read_document,
)
from vendor.mm_plugins.image_budget import (
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


def _png_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        return img.size


def test_supported_extension_probe() -> None:
    assert is_supported_document("script.pdf")
    assert is_supported_document("deck.PPTX")
    assert is_supported_document("data.xlsx")
    assert is_supported_document("dialogue.srt")
    assert is_supported_document("notes.txt")
    assert not is_supported_document("archive.zip")


def test_smart_resize_never_exceeds_budget() -> None:
    # The grid snap must not push the result over the pixel budget
    # (acceptance A3: every tier stays within budget), including extreme
    # aspect ratios where the short side is clamped up to one patch.
    import itertools
    import random

    rng = random.Random(7)
    dims = [1, 2, 10, 31, 32, 33, 100, 864, 1216, 4096, 10000, 50000]
    cases = list(itertools.product(dims, dims)) + [
        (rng.randint(1, 60000), rng.randint(1, 60000)) for _ in range(500)
    ]
    for budget in ("small", "normal", "large"):
        max_pixels = budget_to_pixels(budget, IMAGE_BUDGET_TOKENS)
        for height, width in cases:
            new_h, new_w = smart_resize(
                height,
                width,
                IMAGE_MIN_PIXELS,
                max_pixels,
            )
            assert new_h % TOKEN_SIZE == 0 and new_w % TOKEN_SIZE == 0
            assert new_h >= TOKEN_SIZE and new_w >= TOKEN_SIZE
            assert new_h * new_w <= max_pixels, (budget, height, width)


def test_pdf_renders_pages_text_layer_and_grid_alignment(tmp_path) -> None:
    source = tmp_path / "script.pdf"
    _make_pdf(source, pages=3)
    result = _read(source, tmp_path / "pages")

    assert result.format == "pdf"
    assert result.page_count == 3
    assert result.pages_rendered == (1, 2, 3)
    assert len(result.page_images) == 3
    normal_budget = budget_to_pixels("normal", IMAGE_BUDGET_TOKENS)
    for page, image_path in zip(result.pages_rendered, result.page_images):
        assert image_path.name == f"page-{page:04d}.png"
        assert image_path.is_file()
        width, height = _png_size(image_path)
        assert width % TOKEN_SIZE == 0
        assert height % TOKEN_SIZE == 0
        assert width * height <= normal_budget
    assert "Creator Doc Page 1: storyboard beats" in result.text_excerpt
    assert len(result.text_excerpt) <= MAX_TEXT_EXCERPT_CHARS


def test_pdf_page_range_selection(tmp_path) -> None:
    source = tmp_path / "script.pdf"
    _make_pdf(source, pages=4)
    result = _read(source, tmp_path / "pages", pages="2,4")

    assert result.page_count == 4
    assert result.pages_rendered == (2, 4)
    assert [item.name for item in result.page_images] == [
        "page-0002.png",
        "page-0004.png",
    ]
    assert any(
        "request more via the pages parameter" in n for n in result.notes
    )
    # Full text is decoupled from the rendered page subset: pages outside
    # the range still contribute their text layer to indexed_text.
    assert "Creator Doc Page 3: storyboard beats" in result.indexed_text
    assert "Creator Doc Page 3: storyboard beats" not in result.text_excerpt


def test_pdf_full_text_covers_pages_beyond_render_cap(tmp_path) -> None:
    # CR repro: a 21-page PDF renders only 20 pages by default, but the
    # 21st page's unique text must still reach the indexed full text.
    source = tmp_path / "long.pdf"
    _make_pdf(source, pages=21)
    result = _read(source, tmp_path / "pages")

    assert result.page_count == 21
    assert result.pages_rendered == tuple(range(1, 21))
    marker = "Creator Doc Page 21: storyboard beats"
    assert marker not in result.text_excerpt
    assert marker in result.indexed_text
    assert result.extracted_chars == len(result.indexed_text)


def test_csv_full_text_covers_rows_beyond_display_cap(tmp_path) -> None:
    # CR repro: a 2002-row CSV keeps its last row in the indexed full text
    # even though the display table caps far earlier.
    source = tmp_path / "big.csv"
    rows = ["scene,cost"]
    rows += [f"scene-{number},{number}" for number in range(1, 2002)]
    rows.append("final-unique-scene,9999")
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = _read(source, tmp_path / "pages")

    assert result.format == "csv"
    assert "final-unique-scene" not in result.text_excerpt
    assert "final-unique-scene" in result.indexed_text


def test_indexed_text_bound_is_honest_about_truncation(tmp_path) -> None:
    # Indexing is intentionally bounded (the semantic index is a
    # line-oriented canonical file): oversized text is cut at the bound
    # and the coverage numbers report it instead of claiming full text.
    source = tmp_path / "huge.txt"
    filler = ("剧情推进。" * 100 + "\n") * 4200
    marker = "末尾唯一标记：星光不灭。"
    source.write_text(filler + marker + "\n", encoding="utf-8")
    result = _read(source, tmp_path / "pages")

    assert result.extracted_chars > MAX_INDEXED_TEXT_CHARS
    assert len(result.indexed_text) == MAX_INDEXED_TEXT_CHARS
    assert marker not in result.indexed_text
    assert any("indexing bound" in note for note in result.notes)
    assert all(
        "still enters the semantic index" not in note for note in result.notes
    )
    # The indexing bound is separate from renderer-stage extraction.
    assert result.extraction_complete is True
    assert result.extraction_fraction == 1.0


def test_csv_row_cap_reports_incomplete_extraction(
    tmp_path,
    monkeypatch,
) -> None:
    # CR repro: a row-capped table must not pretend complete extraction.
    # The true row total is unknowable under the capped read, so the
    # fraction is honestly unknown.
    monkeypatch.setattr(
        "vendor.mm_plugins.renderers.data.FULL_TEXT_ROW_CAP",
        50,
    )
    source = tmp_path / "big.csv"
    rows = ["scene,cost"]
    rows += [f"scene-{number},{number}" for number in range(1, 60)]
    rows.append("final-unique-scene,9999")
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = _read(source, tmp_path / "pages")

    assert "final-unique-scene" not in result.indexed_text
    assert result.extraction_complete is False
    assert result.extraction_fraction is None
    assert any("capped at 50 rows" in note for note in result.notes)


def test_pdf_text_page_cap_reports_extraction_fraction(
    tmp_path,
    monkeypatch,
) -> None:
    # With a known page total the extraction share is exact and feeds the
    # conservative coverage merge.
    monkeypatch.setattr(
        "vendor.mm_plugins.renderers.pdf.DEFAULT_MAX_TEXT_PAGES",
        2,
    )
    source = tmp_path / "script.pdf"
    _make_pdf(source, pages=4)
    result = _read(source, tmp_path / "pages")

    assert result.extraction_complete is False
    assert result.extraction_fraction == 0.5
    assert any("capped at 2 of 4 pages" in note for note in result.notes)


def test_csv_renders_table_image_and_markdown(tmp_path) -> None:
    source = tmp_path / "budget.csv"
    source.write_text(
        "scene,cost\nopening,120\nfinale,340\n",
        encoding="utf-8",
    )
    result = _read(source, tmp_path / "pages")

    assert result.format == "csv"
    assert result.page_count == 1
    assert len(result.page_images) == 1
    width, height = _png_size(result.page_images[0])
    assert width % TOKEN_SIZE == 0 and height % TOKEN_SIZE == 0
    assert "finale" in result.text_excerpt
    assert "340" in result.text_excerpt


def test_xlsx_sheets_map_to_pages(tmp_path) -> None:
    import pandas as pd

    source = tmp_path / "plan.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame({"shot": ["s1", "s2"], "len": [3, 5]}).to_excel(
            writer,
            sheet_name="Shots",
            index=False,
        )
        pd.DataFrame({"role": ["cat"], "voice": ["warm"]}).to_excel(
            writer,
            sheet_name="Cast",
            index=False,
        )
    result = _read(source, tmp_path / "pages")

    assert result.format == "xlsx"
    assert result.page_count == 2
    assert result.pages_rendered == (1, 2)
    assert len(result.page_images) == 2
    assert "Shots" in result.text_excerpt
    assert "Cast" in result.text_excerpt


def test_srt_subtitle_text_only(tmp_path) -> None:
    source = tmp_path / "dialogue.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\n猫走进画面\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n镜头拉远\n",
        encoding="utf-8",
    )
    result = _read(source, tmp_path / "pages")

    assert result.format == "srt"
    assert result.page_images == ()
    assert "2 entries" in result.text_excerpt
    assert "猫走进画面" in result.text_excerpt


def test_plain_text_uses_code_renderer(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("act one\nact two\n", encoding="utf-8")
    result = _read(source, tmp_path / "pages")

    assert result.format == "txt"
    assert result.page_images == ()
    assert "act two" in result.text_excerpt


def test_unsupported_extension_gives_readable_error(tmp_path) -> None:
    source = tmp_path / "bundle.zip"
    source.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValidationError) as excinfo:
        _read(source, tmp_path / "pages")
    assert "unsupported document format" in str(excinfo.value)


def test_docx_without_libreoffice_degrades_readably(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "services.document_reader._resolve_soffice",
        lambda: None,
    )
    source = tmp_path / "brief.docx"
    source.write_bytes(b"PK\x03\x04fake-docx")
    with pytest.raises(ValidationError) as excinfo:
        _read(source, tmp_path / "pages")
    assert "LibreOffice is required" in str(excinfo.value)


def test_html_rendering_disabled_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CREATOR_DOC_READER_WEB_ENABLED", raising=False)
    source = tmp_path / "page.html"
    source.write_text("<html><body>hello</body></html>", encoding="utf-8")
    with pytest.raises(ValidationError) as excinfo:
        _read(source, tmp_path / "pages")
    assert "CREATOR_DOC_READER_WEB_ENABLED" in str(excinfo.value)
