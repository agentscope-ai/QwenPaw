# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Real-call acceptance tests for the document reader (WT3 A-group).

Run explicitly:

    pytest -m manual_real tests/manual/test_real_document_reader.py -v

Fixtures: point ``CREATOR_DOC_FIXTURES`` at a directory containing the
acceptance material (script PDF, storyboard PPTX, XLSX/CSV, SRT, .py).
Missing fixtures that can be synthesized locally are generated on the fly;
the PPTX case is skipped without a provided fixture.

Rendered pages land under ``CREATOR_DOC_MANUAL_OUT`` (default:
``.manual-doc-reader/`` next to this file) — open them manually to judge
visual quality, per the acceptance rules.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil

import pytest

from services.document_reader import read_document
from services.runtime_files.runtime_dependencies import resolve_libreoffice
from vendor.mm_plugins.image_budget import (
    IMAGE_BUDGET_TOKENS,
    IMAGE_MIN_PIXELS,
    TOKEN_SIZE,
    budget_to_pixels,
)

pytestmark = pytest.mark.manual_real

_FIXTURES = Path(
    os.environ.get("CREATOR_DOC_FIXTURES")
    or Path(__file__).parent / "fixtures",
)
_OUTPUT = Path(
    os.environ.get("CREATOR_DOC_MANUAL_OUT")
    or Path(__file__).parent / ".manual-doc-reader",
)


def _read(path: Path, case: str, **kwargs):
    output_dir = _OUTPUT / case
    if output_dir.exists():
        shutil.rmtree(output_dir)
    result = asyncio.run(read_document(path, output_dir=output_dir, **kwargs))
    print(f"[{case}] pages under {output_dir} — open them to verify visually")
    return result


def _assert_page_geometry(image_path: Path, budget: str) -> None:
    from PIL import Image

    with Image.open(image_path) as img:
        width, height = img.size
    assert width % TOKEN_SIZE == 0 and height % TOKEN_SIZE == 0, image_path
    max_pixels = budget_to_pixels(budget, IMAGE_BUDGET_TOKENS)
    assert (
        width * height <= max_pixels
    ), f"{image_path} {width}x{height} exceeds {budget} budget {max_pixels}"


def _script_pdf() -> Path:
    provided = _FIXTURES / "last-light-script.pdf"
    if provided.is_file():
        return provided
    generated = _OUTPUT / "generated" / "script.pdf"
    if not generated.is_file():
        generated.parent.mkdir(parents=True, exist_ok=True)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        from vendor.mm_plugins.renderers import configure_matplotlib_cjk

        configure_matplotlib_cjk()
        with PdfPages(generated) as pdf:
            for number in range(1, 7):
                fig = plt.figure(figsize=(8.27, 11.69))
                fig.text(0.1, 0.9, f"《最后一束光》 第 {number} 场", fontsize=18)
                fig.text(0.1, 0.8, f"场次 {number} · 老电影院前厅 · 黄昏", fontsize=12)
                fig.text(0.1, 0.6, f"林夏：这是第 {number} 页的对白。", fontsize=11)
                pdf.savefig(fig)
                plt.close(fig)
    return generated


def test_a1_pdf_full_render_geometry_and_text_layer() -> None:
    source = _script_pdf()
    result = _read(source, "a1-pdf")
    assert result.format == "pdf"
    assert result.page_count >= 6
    assert list(result.pages_rendered) == list(
        range(1, min(result.page_count, 20) + 1),
    )
    for image_path in result.page_images:
        _assert_page_geometry(image_path, "normal")
    assert result.text_excerpt.strip()


def test_a2_page_range_selection() -> None:
    result = _read(_script_pdf(), "a2-pages", pages="2-3")
    assert result.pages_rendered == (2, 3)
    assert [item.name for item in result.page_images] == [
        "page-0002.png",
        "page-0003.png",
    ]


def test_a3_budget_tiers_within_budget_and_increasing() -> None:
    source = _script_pdf()
    sizes: dict[str, int] = {}
    for budget in ("small", "normal", "large"):
        result = _read(source, f"a3-{budget}", pages="2", budget=budget)
        image_path = result.page_images[0]
        _assert_page_geometry(image_path, budget)
        from PIL import Image

        with Image.open(image_path) as img:
            sizes[budget] = img.size[0] * img.size[1]
    assert sizes["small"] <= sizes["normal"] <= sizes["large"]
    assert sizes["small"] >= IMAGE_MIN_PIXELS // 2


def test_a4_pptx_via_libreoffice() -> None:
    source = _FIXTURES / "last-light-storyboard.pptx"
    if not source.is_file():
        pytest.skip(f"provide a storyboard PPTX at {source}")
    if resolve_libreoffice() is None:
        pytest.skip("LibreOffice is not installed")
    result = _read(source, "a4-pptx")
    assert result.page_count >= 5
    assert len(result.page_images) == len(result.pages_rendered)
    for image_path in result.page_images:
        _assert_page_geometry(image_path, "normal")
    print("[a4] compare pages against the original PPTX manually (CJK text!)")


def test_a5_xlsx_and_csv_tables() -> None:
    xlsx = _FIXTURES / "production-plan.xlsx"
    if not xlsx.is_file():
        import pandas as pd

        xlsx = _OUTPUT / "generated" / "plan.xlsx"
        xlsx.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            pd.DataFrame({"镜头": ["s1", "s2"], "时长": [3, 5]}).to_excel(
                writer,
                sheet_name="镜头表",
                index=False,
            )
            pd.DataFrame({"场景": ["前厅"], "预算": [1200]}).to_excel(
                writer,
                sheet_name="预算表",
                index=False,
            )
    result = _read(xlsx, "a5-xlsx")
    assert result.page_count >= 2
    assert len(result.page_images) == result.page_count
    for image_path in result.page_images:
        _assert_page_geometry(image_path, "normal")
    print("[a5] open the sheet images — CJK header cells must be readable")

    csv = _OUTPUT / "generated" / "shots.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text("场次,内容\n1,老电影院前厅\n2,城中村天台\n", encoding="utf-8")
    csv_result = _read(csv, "a5-csv")
    assert "老电影院前厅" in csv_result.text_excerpt
    assert len(csv_result.page_images) == 1


def test_a6_text_formats_match_source() -> None:
    srt = _OUTPUT / "generated" / "dialogue.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\n猫走进画面\n",
        encoding="utf-8",
    )
    result = _read(srt, "a6-srt")
    assert "猫走进画面" in result.text_excerpt

    code = _OUTPUT / "generated" / "sample_reader.py"
    code.write_text("def read_scene():\n    return '场景 1'\n", encoding="utf-8")
    code_result = _read(code, "a6-py")
    assert "def read_scene()" in code_result.text_excerpt
    assert "场景 1" in code_result.text_excerpt


def test_a8_out_of_boundary_file_ref_rejected(tmp_path) -> None:
    """Acceptance A8: refs outside the admitted asset boundary are refused."""
    from api.file_asset_routes import _AssetInput, _ingest_many_sync
    from domain.errors import ValidationError
    from services.project_files.facade import CreatorFileServices
    from services.project_files.models import Project
    from services.source_analysis import (
        SourceAgentToolContext,
        SourceMediaAnalysisService,
    )

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id="p-a8", name="A8"))
    result, _ = _ingest_many_sync(
        services,
        project_id="p-a8",
        key="a8-doc",
        inputs=[
            _AssetInput(
                name="script.pdf",
                content=_script_pdf().read_bytes(),
                media_type="application/pdf",
            ),
        ],
        attach_source=True,
        scope="manual-a8",
    )
    asset_id = result["items"][0]["assetId"]
    service = SourceMediaAnalysisService(services)
    context = SourceAgentToolContext(
        specialist_run_id="manual-a8-run",
        tool_call_id="manual-a8-call",
        assistant_message_id="manual-a8-assistant",
        provider_message_id="manual-a8-provider",
        provider="manual",
        model="manual",
    )

    async def scenario():
        return await service.read_source_document(
            project_id="p-a8",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": "asset-version:outside-boundary"},
            context=context,
        )

    with pytest.raises(ValidationError) as excinfo:
        asyncio.run(scenario())
    assert "准入边界" in str(excinfo.value)
    print(f"[a8] rejection message: {excinfo.value}")


def test_a9_missing_libreoffice_degrades_readably(monkeypatch) -> None:
    from domain.errors import ValidationError

    monkeypatch.setattr(
        "services.document_reader._resolve_soffice",
        lambda: None,
    )
    pptx = _OUTPUT / "generated" / "fake.pptx"
    pptx.parent.mkdir(parents=True, exist_ok=True)
    pptx.write_bytes(b"PK\x03\x04fake")
    with pytest.raises(ValidationError) as excinfo:
        _read(pptx, "a9-missing-pptx")
    assert "LibreOffice is required" in str(excinfo.value)
    assert "brew install --cask libreoffice" in str(excinfo.value)
    pdf_after = _read(_script_pdf(), "a9-pdf-still-works", pages="2")
    assert pdf_after.pages_rendered == (2,)
