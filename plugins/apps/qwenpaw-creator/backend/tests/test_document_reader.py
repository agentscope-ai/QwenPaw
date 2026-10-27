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
    read_document_text,
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


def _make_mixed_pdf(path: Path) -> None:
    """Page 1 selectable text; page 2 rasterized dialogue (no text layer)."""
    import io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from PIL import ImageDraw

    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(4, 3))
        fig.text(0.08, 0.5, "SCENE ONE. Cover: a selectable text page.")
        pdf.savefig(fig)
        plt.close(fig)

        img = Image.new("RGB", (600, 200), "white")
        ImageDraw.Draw(img).text(
            (20, 80),
            "SCENE TWO. Alice: the missing ending must be in the script.",
            fill="black",
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        fig2 = plt.figure(figsize=(4, 3))
        ax = fig2.add_axes([0, 0, 1, 1])
        ax.axis("off")
        ax.imshow(Image.open(buf))
        pdf.savefig(fig2)
        plt.close(fig2)


def _make_text_then_blank_pdf(path: Path) -> None:
    """Page 1 selectable text; page 2 genuinely blank (no text, no image)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(4, 3))
        fig.text(0.08, 0.5, "SCENE ONE. Cover: a selectable text page.")
        pdf.savefig(fig)
        plt.close(fig)
        blank = plt.figure(figsize=(4, 3))
        pdf.savefig(blank)
        plt.close(blank)


def _make_text_then_vector_pdf(path: Path) -> None:
    """Page 1 selectable text; page 2 = text outlined to curves (转曲).

    A producer that outlines the body text into vector paths leaves no text
    layer and no raster image -- only many small glyph-shaped paths.  Such a
    page looks blank to a text/image check, yet its body cannot be extracted,
    so it must be reported rather than silently dropped.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle

    rng = random.Random(20261022)
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(4, 3))
        fig.text(0.08, 0.5, "SCENE ONE. Cover: a selectable text page.")
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: 40 varied glyph-like vector shapes, no text layer.  Varied
        # geometry keeps matplotlib from batching them into a single path, the
        # way real outlined text emits one path per glyph stroke.
        fig2 = plt.figure(figsize=(4, 3))
        ax = fig2.add_axes([0, 0, 1, 1])
        ax.axis("off")
        for _ in range(40):
            ax.add_patch(
                Rectangle(
                    (rng.random() * 0.8, rng.random() * 0.8),
                    0.01 + rng.random() * 0.03,
                    0.04 + rng.random() * 0.05,
                    facecolor="black",
                    edgecolor="none",
                ),
            )
        pdf.savefig(fig2)
        plt.close(fig2)


def _make_text_then_merged_outline_pdf(path: Path) -> None:
    """Page 1 selectable text; page 2 = 转曲 body merged into ONE path.

    Some producers (Ghostscript/ps2pdf, Illustrator/InDesign flatten) outline
    the text and merge every glyph into a single vector path.  The page then
    has no text layer, no raster image and only *one* non-background path, so
    an object-count check alone would call it blank -- yet that path carries
    many segments (the merged glyph outlines) and its body cannot be
    extracted, so it must still be reported.
    """
    import math

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Polygon

    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(4, 3))
        fig.text(0.08, 0.5, "SCENE ONE. Cover: a selectable text page.")
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: one closed polygon with many vertices => a single path with
        # many segments, the shape a merged 转曲 outline takes.  No text layer.
        fig2 = plt.figure(figsize=(4, 3))
        ax = fig2.add_axes([0, 0, 1, 1])
        ax.axis("off")
        points = [
            (
                0.5 + 0.3 * math.cos(2 * math.pi * i / 40),
                0.5 + 0.3 * math.sin(2 * math.pi * i / 40),
            )
            for i in range(40)
        ]
        ax.add_patch(
            Polygon(
                points,
                closed=True,
                facecolor="black",
                edgecolor="none",
            ),
        )
        pdf.savefig(fig2)
        plt.close(fig2)


def _make_header_plus_scan_pdf(path: Path) -> None:
    """Page 1 selectable text; page 2 = copyable header + rasterized body.

    The running header is a real text layer, so a naive "page has any text"
    test would call page 2 complete -- yet the dialogue only exists inside the
    full-page image.  This is the mixed page that must still be reported.
    """
    import io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from PIL import ImageDraw

    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(4, 3))
        fig.text(0.08, 0.5, "SCENE ONE. Cover: a selectable text page.")
        pdf.savefig(fig)
        plt.close(fig)

        img = Image.new("RGB", (600, 400), "white")
        ImageDraw.Draw(img).text(
            (20, 150),
            "SCENE TWO. Alice: the missing ending must be in the script.",
            fill="black",
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        fig2 = plt.figure(figsize=(4, 3))
        # A copyable running header: sparse text that must not mask the scan.
        fig2.text(0.1, 0.93, "Page 2 - Screenplay")
        ax = fig2.add_axes([0, 0, 1, 0.85])
        ax.axis("off")
        ax.imshow(Image.open(buf))
        pdf.savefig(fig2)
        plt.close(fig2)


def _make_tiled_scan_pdf(path: Path) -> None:
    """Page 1 selectable text; page 2 = copyable header + body split in tiles.

    A producer that slices a scanned body into several image tiles defeats a
    "largest single image" coverage test: no one tile dominates the page, yet
    together they cover it.  The accumulated coverage must still be reported.
    """
    import io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from PIL import ImageDraw

    def _tile(text: str) -> io.BytesIO:
        img = Image.new("RGB", (300, 500), "white")
        ImageDraw.Draw(img).text((20, 230), text, fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(4, 3))
        fig.text(0.08, 0.5, "SCENE ONE. Cover: a selectable text page.")
        pdf.savefig(fig)
        plt.close(fig)

        fig2 = plt.figure(figsize=(4, 3))
        # A copyable running header: sparse text that must not mask the scan.
        fig2.text(0.1, 0.94, "Page 2 - Screenplay")
        left = fig2.add_axes([0.03, 0.05, 0.47, 0.85])
        left.axis("off")
        left.imshow(Image.open(_tile("SCENE TWO. Alice: the")), aspect="auto")
        right = fig2.add_axes([0.5, 0.05, 0.47, 0.85])
        right.axis("off")
        right.imshow(
            Image.open(_tile("missing ending stays")),
            aspect="auto",
        )
        pdf.savefig(fig2)
        plt.close(fig2)


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


def test_pdf_reports_image_only_pages_as_unextractable(tmp_path) -> None:
    """混合扫描 PDF：图片正文页被逐页报告，空白页不被误报。

    用真实 pypdfium2 解析（不是伪造的提取结果）：第 2 页把台词栅格化成
    图片、没有文字层，渲染器仍报 extraction_complete=True，但
    unextractable_pages 精确指出第 2 页——直登据此拒绝，不再静默丢正文。
    """
    mixed = tmp_path / "mixed.pdf"
    _make_mixed_pdf(mixed)
    result = read_document_text(mixed)
    # 关键：complete 标志本身证明不了内容完整（它只对页数上限敏感）。
    assert result.extraction_complete is True
    assert result.unextractable_pages == (2,)
    assert "SCENE TWO" not in result.indexed_text

    # 全文字层 PDF：没有无法抽取的页。
    text_pdf = tmp_path / "text.pdf"
    _make_pdf(text_pdf, pages=2)
    assert not read_document_text(text_pdf).unextractable_pages

    # 文字页 + 真·空白页：空白页不被误报，正常文档不会被误拒。
    blank_pdf = tmp_path / "blank.pdf"
    _make_text_then_blank_pdf(blank_pdf)
    assert not read_document_text(blank_pdf).unextractable_pages


def test_pdf_reports_vector_outline_pages_as_unextractable(tmp_path) -> None:
    """转曲正文页：无文字层、无图片，只有矢量轮廓，仍须逐页报告。

    回归：此前无文字层的页面只在有栅格图片时才报告，于是矢量转曲
    正文（文字被轮廓化成 path）被当成空白页，直登静默丢掉整页正文。
    现在非背景矢量对象达到阈值的页面被逐页报告，直登据此拒绝；
    真·空白页（只有一个满页背景 path）不被误报。
    """
    doc = tmp_path / "vector.pdf"
    _make_text_then_vector_pdf(doc)
    result = read_document_text(doc)
    # complete 标志证明不了内容完整（它只对页数上限敏感）。
    assert result.extraction_complete is True
    # 第 2 页是转曲正文：无文字层、无图片，只有矢量轮廓 -> 被报告。
    assert result.unextractable_pages == (2,)
    # 第 1 页的可复制正文仍被抽出（证明只是转曲页被拒，不是全文失败）。
    assert "SCENE ONE" in result.indexed_text


def test_pdf_reports_merged_outline_pages_as_unextractable(tmp_path) -> None:
    """合并转曲页：整页字形被并成单个 path，仍须逐页报告。

    回归：仅按矢量对象个数判定会漏掉“整页轮廓合并成一个 path”的
    常见转曲产物（Ghostscript/ps2pdf、Illustrator 拼合）——对象数只有 1，
    够不到阈值 3，页面被当成空白、正文静默丢失。现在单个 path 的
    segment 数达阈值即判为正文；真·空白页背景只有 ~4-5 段不误报。
    """
    doc = tmp_path / "merged.pdf"
    _make_text_then_merged_outline_pdf(doc)
    result = read_document_text(doc)
    assert result.extraction_complete is True
    # 第 2 页只有单个合并轮廓 path（对象数不足）-> 靠 segment 数被报告。
    assert result.unextractable_pages == (2,)
    assert "SCENE ONE" in result.indexed_text


def test_pdf_reports_scanned_body_behind_a_copyable_header(tmp_path) -> None:
    """可复制页眉 + 扫描正文页：页眉有文字层也证明不了正文完整。

    回归：此前只要页面有任意可提取文字就跳过图片覆盖检查，于是「可复制
    页码/页眉 + 扫描正文」被当成完整文字剧本，正文台词被静默丢弃。现在
    含未覆盖扫描图像的混合页（稀疏文字 + 整页图片）被逐页报告，直登据此
    拒绝；纯文字封面页不受影响。
    """
    doc = tmp_path / "header_scan.pdf"
    _make_header_plus_scan_pdf(doc)
    result = read_document_text(doc)

    # complete 标志仍证明不了内容完整（它只对页数上限敏感）。
    assert result.extraction_complete is True
    # 第 2 页有可复制页眉（文字层存在），但正文在整页图片里 -> 被报告。
    assert result.unextractable_pages == (2,)
    # 栅格化的台词没有进索引文本（证明正文确实抽不出）。
    assert "missing ending" not in result.indexed_text
    # 可复制页眉本身仍被抽出（证明该页确有文字层，不是纯图片页）。
    assert "Page 2" in result.indexed_text


def test_pdf_reports_tiled_scan_behind_a_copyable_header(tmp_path) -> None:
    """分块扫描正文 + 可复制页眉：单块都不主导，合起来仍须被报告。

    回归：覆盖率此前只取「单张最大图片」，于是被切成多块的整页扫描
    （每块低于阈值）+ 稀疏页眉被当成完整文字剧本，正文被静默丢弃。
    现在按图片 bounds 累加/封顶计算覆盖率，分块扫描页同样被逐页报告，
    直登据此拒绝；纯文字封面页不受影响。
    """
    doc = tmp_path / "tiled_scan.pdf"
    _make_tiled_scan_pdf(doc)
    result = read_document_text(doc)

    # complete 标志仍证明不了内容完整（它只对页数上限敏感）。
    assert result.extraction_complete is True
    # 第 2 页有可复制页眉（文字层存在），但正文被切成多块图片 -> 被报告。
    assert result.unextractable_pages == (2,)
    # 栅格化的台词没有进索引文本（证明正文确实抽不出）。
    assert "missing ending" not in result.indexed_text
    # 可复制页眉本身仍被抽出（证明该页确有文字层，不是纯图片页）。
    assert "Page 2" in result.indexed_text


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
