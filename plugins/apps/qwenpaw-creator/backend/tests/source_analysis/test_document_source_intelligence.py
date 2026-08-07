# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Document source flow: read_document tool + document-flavored index."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.file_asset_routes import _AssetInput, _ingest_many_sync
from domain.enums import SpecialistRole, SpecialistRunStatus
from domain.errors import ValidationError
from services.media.source_intelligence import (
    parse_source_intelligence_files,
    render_source_intelligence_files,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.execution_models import SpecialistRunRecord
from services.source_analysis import (
    SourceAgentToolContext,
    SourceMediaAnalysisService,
)
from services.source_analysis.service import (
    document_indexed_text_path,
    document_page_path,
    document_page_ref,
    resolve_document_page_ref,
)
from services.specialist_tools import FileSpecialistToolRegistry


def _pdf_bytes(pages: int = 3) -> bytes:
    import io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        for number in range(1, pages + 1):
            fig = plt.figure(figsize=(4, 3))
            fig.text(0.1, 0.5, f"Script page {number} Scene beats {number}")
            pdf.savefig(fig)
            plt.close(fig)
    return buffer.getvalue()


def _services_with_source(
    tmp_path: Path,
    *,
    name: str,
    content: bytes,
    media_type: str,
) -> tuple[CreatorFileServices, str, str]:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id="project-1", name="One"))
    result, _ = _ingest_many_sync(
        services,
        project_id="project-1",
        key="doc-asset-1",
        inputs=[
            _AssetInput(
                name=name,
                content=content,
                media_type=media_type,
            ),
        ],
        attach_source=True,
        scope="document-source-test",
    )
    item = result["items"][0]
    return services, item["assetId"], item["assetVersionId"]


def _services_with_document(
    tmp_path: Path,
) -> tuple[CreatorFileServices, str, str]:
    return _services_with_source(
        tmp_path,
        name="script.pdf",
        content=_pdf_bytes(pages=3),
        media_type="application/pdf",
    )


def _running_context(
    service: SourceMediaAnalysisService,
    services: CreatorFileServices,
    asset_id: str,
    *,
    tool_call_id: str,
) -> SourceAgentToolContext:
    run_id = "specialist-run-doc-vlm"
    try:
        service.executions.get_run("project-1", run_id)
    except Exception:  # pylint: disable=broad-except
        snapshot = services.projects.read("project-1")
        service.executions.create_specialist_run(
            SpecialistRunRecord(
                run_id=run_id,
                project_id="project-1",
                round_id="round-doc-vlm",
                role=SpecialistRole.SOURCE_INTELLIGENCE,
                target_refs=[f"asset:{asset_id}"],
                input_generation=snapshot.generation,
                input_etag=snapshot.etag,
            ),
        )
        service.executions.transition_specialist_run(
            "project-1",
            run_id,
            expected_status=SpecialistRunStatus.QUEUED,
            status=SpecialistRunStatus.RUNNING_MODEL,
        )
    return SourceAgentToolContext(
        specialist_run_id=run_id,
        tool_call_id=tool_call_id,
        assistant_message_id=f"assistant-{tool_call_id}",
        provider_message_id=f"provider-{tool_call_id}",
        provider="configured_vlm",
        model="vlm-v1",
    )


def _document_shot(page: int, description: str) -> dict:
    return {
        "startMs": (page - 1) * 1000,
        "endMs": page * 1000,
        "description": description,
        "events": [f"第{page}页要点"],
        "confidence": 0.95,
    }


def test_read_document_tool_renders_pages_and_boundaries(tmp_path) -> None:
    services, asset_id, version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="doc-call",
    )

    async def scenario():
        return await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=context,
        )

    result = asyncio.run(scenario())

    assert result["ok"] is True
    assert result["module"] == "document"
    assert result["format"] == "pdf"
    assert result["pageCount"] == 3
    assert result["pagesRendered"] == [1, 2, 3]
    assert "Scene beats 2" in result["textExcerpt"]
    project_root = services.projects.project_root("project-1")
    snapshot = services.projects.read("project-1")
    checksum = snapshot.project.assets.source_versions_by_id[
        version_id
    ].checksum
    assert result["pageImageRefs"] == [
        document_page_ref(checksum, page) for page in (1, 2, 3)
    ]
    for page in (1, 2, 3):
        assert document_page_path(project_root, checksum, page).is_file()
    resolved = resolve_document_page_ref(
        project_root,
        result["pageImageRefs"][0],
    )
    assert resolved is not None and resolved[1] == 1

    # The rendered pages are browsable through the HTTP doc-page route.
    from api.file_source_intelligence_routes import document_page_image
    from domain.errors import NotFoundError

    response = asyncio.run(
        document_page_image(
            project_id="project-1",
            checksum=checksum,
            page=1,
            services=services,
        ),
    )
    assert response.media_type == "image/png"
    with pytest.raises(NotFoundError):
        asyncio.run(
            document_page_image(
                project_id="project-1",
                checksum=checksum,
                page=99,
                services=services,
            ),
        )
    with pytest.raises(NotFoundError):
        asyncio.run(
            document_page_image(
                project_id="project-1",
                checksum="../escape",
                page=1,
                services=services,
            ),
        )


def test_read_document_rejects_out_of_boundary_file_ref(tmp_path) -> None:
    services, asset_id, _version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="doc-call-boundary",
    )

    async def scenario():
        return await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": "asset-version:another-project-version"},
            context=context,
        )

    with pytest.raises(ValidationError) as excinfo:
        asyncio.run(scenario())
    assert "准入边界" in str(excinfo.value)


def test_document_commit_produces_document_index(tmp_path) -> None:
    services, asset_id, version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="doc-read",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-doc-result",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={"tool": "read_document", "toolCallId": "doc-read"},
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="doc-commit",
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="doc-commit-1",
            context=commit_context,
            arguments={
                "summary": "三页剧本：逐页给出场景节拍与关键动作。",
                "shots": [
                    _document_shot(1, "封面页：标题与主角介绍。"),
                    _document_shot(2, "第二页：冲突展开的场景节拍。"),
                    _document_shot(3, "第三页：结尾与情绪收束。"),
                ],
                "entities": [
                    {
                        "kind": "character",
                        "label": "主角猫",
                        "description": "贯穿全剧本的核心角色",
                        "confidence": 0.9,
                    },
                ],
                "semanticEntries": [
                    {
                        "text": "第 2 页给出冲突场景的节拍列表",
                        "tags": ["page-2", "冲突"],
                        "confidence": 0.9,
                    },
                ],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )
        return read_result, committed

    read_result, committed = asyncio.run(scenario())

    assert committed["status"] == "SUCCEEDED"
    assert committed["shotCount"] == 3
    index = service.load("project-1", asset_id)
    assert index.media.media_kind == "document"
    assert index.media.document is not None
    assert index.media.document.format == "pdf"
    assert index.media.document.page_count == 3
    visual = index.coverage["visual"]
    assert visual.mode == "available"
    assert visual.producer == "document_reader"
    assert visual.ratio == 1.0
    assert [item.keyframe_ref for item in index.shots] == list(
        read_result["pageImageRefs"],
    )
    assert [(item.start_ms, item.end_ms) for item in index.shots] == [
        (0, 1000),
        (1000, 2000),
        (2000, 3000),
    ]

    # Extracted document text is indexed deterministically alongside the
    # model-authored entries, attributed to the document reader module run.
    doc_text_entries = [
        item for item in index.semantic_entries if "document-text" in item.tags
    ]
    assert doc_text_entries
    assert any("Scene beats 2" in item.text for item in doc_text_entries)
    assert "document_reader" in {run.provider for run in index.model_runs}
    model_entries = [
        item
        for item in index.semantic_entries
        if "document-text" not in item.tags
    ]
    assert len(model_entries) == 1

    # The canonical text workspace round-trips document metadata.
    files = render_source_intelligence_files(index)
    assert "documentFormat\tpdf" in files["index.txt"]
    assert parse_source_intelligence_files(files) == index


def test_document_commit_requires_read_document_module(tmp_path) -> None:
    services, asset_id, _version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="doc-commit-missing",
    )

    async def scenario():
        return await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="doc-commit-missing",
            context=context,
            arguments={
                "summary": "缺少 read_document 引用的提交。",
                "shots": [_document_shot(1, "第一页")],
                "entities": [],
                "semanticEntries": [],
            },
        )

    with pytest.raises(ValidationError) as excinfo:
        asyncio.run(scenario())
    assert "read_document" in str(excinfo.value)


def test_document_commit_rejects_wrong_page_intervals(tmp_path) -> None:
    services, asset_id, version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="doc-read-mismatch",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-doc-result-mismatch",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={
                "tool": "read_document",
                "toolCallId": "doc-read-mismatch",
            },
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="doc-commit-mismatch",
        )
        return await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="doc-commit-mismatch",
            context=commit_context,
            arguments={
                "summary": "页区间错误的提交。",
                "shots": [_document_shot(1, "只有一页的提交")],
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )

    with pytest.raises(ValidationError) as excinfo:
        asyncio.run(scenario())
    assert "页伪" in str(excinfo.value)


def test_commit_tool_contract_admits_document_module_ref(tmp_path) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )
    manifest = registry.manifest_for(
        SpecialistRole.SOURCE_INTELLIGENCE,
        admitted_target_refs=["asset:doc-1"],
    )
    tools = {item["function"]["name"]: item["function"] for item in manifest}
    assert "read_document" in tools
    module_refs = tools["commit_source_intelligence"]["parameters"][
        "properties"
    ]["arguments"]["properties"]["moduleResultRefs"]
    assert set(module_refs["properties"]) == {"asr", "document"}
    assert module_refs["additionalProperties"] is False


def test_csv_source_enters_document_flow_end_to_end(tmp_path) -> None:
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="budget.csv",
        content=b"scene,cost\nopening,120\nfinale,340\n",
        media_type="text/csv",
    )
    snapshot = services.projects.read("project-1")
    version = snapshot.project.assets.source_versions_by_id[version_id]
    assert version.media_kind == "document"
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="csv-read",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-csv-result",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={"tool": "read_document", "toolCallId": "csv-read"},
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="csv-commit",
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="csv-commit-1",
            context=commit_context,
            arguments={
                "summary": "预算表：两场戏的成本对比。",
                "shots": [_document_shot(1, "预算数据表：场次与成本。")],
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )
        return read_result, committed

    read_result, committed = asyncio.run(scenario())

    assert read_result["format"] == "csv"
    assert read_result["pageCount"] == 1
    assert read_result["pagesRendered"] == [1]
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    assert index.media.media_kind == "document"
    assert index.media.document is not None
    assert index.media.document.format == "csv"
    assert index.shots[0].keyframe_ref == read_result["pageImageRefs"][0]
    doc_text = [
        item for item in index.semantic_entries if "document-text" in item.tags
    ]
    assert any("finale" in item.text for item in doc_text)


def test_carriage_return_text_survives_commit_integrity_check(
    tmp_path,
) -> None:
    # Regression: the indexed text is persisted/verified byte-for-byte.
    # pdfium emits \r\n for line breaks inside a text block, and commits
    # previously failed the sha256 integrity check on every attempt
    # (read_text() collapsed \r\n to \n), locking the source-intelligence
    # agent into a retry loop.
    def _multiline_pdf() -> bytes:
        import io

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        buffer = io.BytesIO()
        with PdfPages(buffer) as pdf:
            fig = plt.figure(figsize=(4, 3))
            fig.text(
                0.1,
                0.5,
                "Scene 1: cat enters frame\n"
                "Scene 2: camera pulls back\n"
                "Scene 3: rooftop finale",
            )
            pdf.savefig(fig)
            plt.close(fig)
        return buffer.getvalue()

    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="windows-notes.pdf",
        content=_multiline_pdf(),
        media_type="application/pdf",
    )
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="cr-read",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-cr-result",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={"tool": "read_document", "toolCallId": "cr-read"},
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="cr-commit",
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="cr-commit-1",
            context=commit_context,
            arguments={
                "summary": "三场景备忘：入画、拉远、屋顶收束。",
                "shots": [_document_shot(1, "全文概括。")],
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )
        return read_result, committed

    read_result, committed = asyncio.run(scenario())

    coverage = read_result["textCoverage"]
    stored = document_indexed_text_path(
        services.projects.project_root("project-1"),
        read_result["sourceChecksum"],
        read_result["resultRef"],
    ).read_bytes()
    assert b"\r" in stored, "fixture must exercise carriage returns"
    assert len(stored.decode("utf-8")) == coverage["indexedChars"]
    assert committed["status"] == "SUCCEEDED"


def test_srt_text_only_document_flow(tmp_path) -> None:
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="dialogue.srt",
        content=(
            "1\n00:00:01,000 --> 00:00:02,500\n猫走进画面\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\n镜头拉远\n"
        ).encode("utf-8"),
        media_type="application/x-subrip",
    )
    snapshot = services.projects.read("project-1")
    version = snapshot.project.assets.source_versions_by_id[version_id]
    assert version.media_kind == "document"
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="srt-read",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-srt-result",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={"tool": "read_document", "toolCallId": "srt-read"},
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="srt-commit",
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="srt-commit-1",
            context=commit_context,
            arguments={
                "summary": "字幕全文：猫入画与镜头拉远两条台词。",
                "shots": [_document_shot(1, "字幕全文概括。")],
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )
        return read_result, committed

    read_result, committed = asyncio.run(scenario())

    assert read_result["format"] == "srt"
    assert read_result["pagesRendered"] == []
    assert read_result["pageImageRefs"] == []
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    assert index.media.media_kind == "document"
    assert index.media.document is not None
    assert index.media.document.format == "srt"
    assert index.media.document.page_count == 1
    assert [(item.start_ms, item.end_ms) for item in index.shots] == [
        (0, 1000),
    ]
    assert index.shots[0].keyframe_ref == f"asset://{asset_id}@{version_id}"
    visual = index.coverage["visual"]
    assert visual.producer == "document_reader"
    assert visual.ratio == 1.0
    doc_text = [
        item for item in index.semantic_entries if "document-text" in item.tags
    ]
    assert any("猫走进画面" in item.text for item in doc_text)


def test_full_document_text_reaches_index_beyond_excerpt(tmp_path) -> None:
    # A text source larger than the 20k model excerpt: the deterministic
    # semantic index must still contain content past the excerpt boundary.
    marker = "结尾彩蛋：星光电影院重新亮灯。"
    body = "\n\n".join(
        f"段落 {number}：" + "剧情推进。" * 120 for number in range(1, 50)
    )
    content = f"{body}\n\n{marker}\n"
    assert len(content) > 25_000
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="long-script.txt",
        content=content.encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="long-read",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-long-result",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={"tool": "read_document", "toolCallId": "long-read"},
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="long-commit",
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="long-commit-1",
            context=commit_context,
            arguments={
                "summary": "超长文本剧本的理解。",
                "shots": [_document_shot(1, "全文概括。")],
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )
        return read_result, committed

    read_result, committed = asyncio.run(scenario())

    # The tool result stays bounded for model context, while the indexed
    # text is persisted separately with honest coverage numbers.
    assert len(read_result["textExcerpt"]) <= 20_000
    assert read_result["textCoverage"]["extractedChars"] > 25_000
    assert (
        read_result["textCoverage"]["indexedChars"]
        == read_result["textCoverage"]["extractedChars"]
    )
    assert marker not in read_result["textExcerpt"]
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    doc_text = [
        item for item in index.semantic_entries if "document-text" in item.tags
    ]
    assert any(marker in item.text for item in doc_text)
    # Text-extraction coverage is persisted on the ocr modality.
    ocr = index.coverage["ocr"]
    assert ocr.mode == "available"
    assert ocr.producer == "document_reader"
    assert ocr.ratio == 1.0


def _read_then_commit(
    service: SourceMediaAnalysisService,
    services: CreatorFileServices,
    asset_id: str,
    version_id: str,
    *,
    tag: str,
    shots: list[dict],
    between_read_and_commit=None,
    strip_text_coverage: bool = False,
    mutate_stored=None,
):
    """Shared read -> (mutate) -> commit flow for coverage-integrity tests."""
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id=f"{tag}-read",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        stored = dict(read_result)
        if strip_text_coverage:
            stored.pop("textCoverage", None)
        if mutate_stored is not None:
            mutate_stored(stored)
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id=f"tool-{tag}-result",
            role="tool",
            content_parts=[{"type": "text", "text": json.dumps(stored)}],
            metadata={"tool": "read_document", "toolCallId": f"{tag}-read"},
        )
        if between_read_and_commit is not None:
            between_read_and_commit(read_result)
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id=f"{tag}-commit",
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id=f"{tag}-commit-1",
            context=commit_context,
            arguments={
                "summary": f"{tag} 场景的文档理解。",
                "shots": shots,
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )
        return read_result, committed

    return asyncio.run(scenario())


def test_document_commit_rejects_missing_or_tampered_indexed_text(
    tmp_path,
) -> None:
    # CR P1: a new-format result must be backed by the intact Runtime
    # indexed-text file; a silent excerpt fallback would publish coverage
    # numbers that the semantic entries do not actually satisfy.
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="notes.txt",
        content=("剧情推进。" * 6000).encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    project_root = services.projects.project_root("project-1")
    snapshot = services.projects.read("project-1")
    checksum = snapshot.project.assets.source_versions_by_id[
        version_id
    ].checksum

    def delete_runtime_text(read_result):
        document_indexed_text_path(
            project_root,
            checksum,
            read_result["resultRef"],
        ).unlink()

    with pytest.raises(ValidationError) as missing:
        _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag="doc-missing-file",
            shots=[_document_shot(1, "全文概括。")],
            between_read_and_commit=delete_runtime_text,
        )
    assert "Runtime 文件缺失" in str(missing.value)

    def tamper_runtime_text(read_result):
        path = document_indexed_text_path(
            project_root,
            checksum,
            read_result["resultRef"],
        )
        path.write_text("被替换的内容", encoding="utf-8")

    with pytest.raises(ValidationError) as tampered:
        _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag="doc-tampered-file",
            shots=[_document_shot(1, "全文概括。")],
            between_read_and_commit=tamper_runtime_text,
        )
    assert "不一致" in str(tampered.value)


def test_document_commit_rejects_partial_text_coverage(tmp_path) -> None:
    # CR P1 (fail-closed): a textCoverage missing its sha256 must reject
    # the commit outright — otherwise a same-length content swap of the
    # Runtime file would pass the remaining length-only check.
    body = "剧情推进。" * 2000
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="notes.txt",
        content=body.encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    project_root = services.projects.project_root("project-1")
    snapshot = services.projects.read("project-1")
    checksum = snapshot.project.assets.source_versions_by_id[
        version_id
    ].checksum

    def drop_sha(stored):
        stored["textCoverage"] = {
            key: value
            for key, value in stored["textCoverage"].items()
            if key != "sha256"
        }

    def swap_same_length_content(read_result):
        path = document_indexed_text_path(
            project_root,
            checksum,
            read_result["resultRef"],
        )
        original = path.read_text(encoding="utf-8")
        path.write_text("Z" * len(original), encoding="utf-8")

    with pytest.raises(ValidationError) as excinfo:
        _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag="doc-partial-coverage",
            shots=[_document_shot(1, "全文概括。")],
            between_read_and_commit=swap_same_length_content,
            mutate_stored=drop_sha,
        )
    assert "textCoverage 不合法" in str(excinfo.value)


def test_document_commit_rejects_null_text_coverage(tmp_path) -> None:
    # CR P1: an explicit "textCoverage": null must not be treated as a legacy
    # result. Branching on key presence sends it to the strict model, so a
    # same-length content swap of the Runtime file can no longer be committed
    # with ratio=1.0.
    body = "剧情推进。" * 2000
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="notes.txt",
        content=body.encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    project_root = services.projects.project_root("project-1")
    snapshot = services.projects.read("project-1")
    checksum = snapshot.project.assets.source_versions_by_id[
        version_id
    ].checksum

    def null_coverage(stored):
        stored["textCoverage"] = None

    def swap_same_length_content(read_result):
        path = document_indexed_text_path(
            project_root,
            checksum,
            read_result["resultRef"],
        )
        original = path.read_text(encoding="utf-8")
        path.write_text("Z" * len(original), encoding="utf-8")

    with pytest.raises(ValidationError) as excinfo:
        _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag="doc-null-coverage",
            shots=[_document_shot(1, "全文概括。")],
            between_read_and_commit=swap_same_length_content,
            mutate_stored=null_coverage,
        )
    assert "textCoverage 不合法" in str(excinfo.value)


def test_unknown_ratio_is_confined_to_document_ocr() -> None:
    # CR P2: the honest-unknown ratio must not weaken every modality's
    # frozen invariant.
    from schemas.assets import SourceCoverage

    with pytest.raises(ValueError):
        SourceCoverage.model_validate(
            {"mode": "available", "producer": "model_native", "ratio": None},
        )
    SourceCoverage.model_validate(
        {"mode": "available", "producer": "document_reader", "ratio": None},
    )


def test_text_coverage_model_is_strict_and_consistent() -> None:
    # extractionFraction must be a real float (no string coercion) and an
    # incomplete extraction must never claim full coverage.
    from schemas.assets import DocumentTextCoverage

    base = {
        "indexedChars": 10,
        "extractedChars": 10,
        "extractionComplete": True,
        "extractionFraction": 1.0,
        "sha256": "a" * 64,
    }
    DocumentTextCoverage.model_validate(base)
    with pytest.raises(ValueError):
        DocumentTextCoverage.model_validate(
            {**base, "extractionFraction": "1"},
        )
    with pytest.raises(ValueError):
        DocumentTextCoverage.model_validate(
            {**base, "extractionComplete": False},
        )
    DocumentTextCoverage.model_validate(
        {**base, "extractionComplete": False, "extractionFraction": 0.5},
    )
    DocumentTextCoverage.model_validate(
        {**base, "extractionComplete": False, "extractionFraction": None},
    )


def test_index_rejects_unknown_ratio_outside_document_ocr(tmp_path) -> None:
    # Index-level gate: tampering the canonical index.txt so a non-ocr
    # modality declares an unknown available ratio must fail to parse.
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="notes.txt",
        content="第一幕：猫信使出发。".encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    _read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="doc-scope-gate",
        shots=[_document_shot(1, "全文概括。")],
    )
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    files = render_source_intelligence_files(index)
    tampered = dict(files)
    tampered["index.txt"] = tampered["index.txt"].replace(
        "coverage\tvisual\tavailable\tdocument_reader\t1",
        "coverage\tvisual\tavailable\tdocument_reader\t-",
    )
    assert tampered["index.txt"] != files["index.txt"]
    with pytest.raises(Exception) as excinfo:
        parse_source_intelligence_files(tampered)
    assert "document ocr" in str(excinfo.value)


def test_legacy_result_without_text_coverage_falls_back(tmp_path) -> None:
    # Legacy tool results (no textCoverage) keep working: the excerpt
    # fallback indexes what it has and reports full coverage.
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="notes.txt",
        content="第一幕：猫信使出发。".encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    project_root = services.projects.project_root("project-1")
    snapshot = services.projects.read("project-1")
    checksum = snapshot.project.assets.source_versions_by_id[
        version_id
    ].checksum

    def delete_runtime_text(read_result):
        document_indexed_text_path(
            project_root,
            checksum,
            read_result["resultRef"],
        ).unlink()

    _read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="doc-legacy",
        shots=[_document_shot(1, "全文概括。")],
        between_read_and_commit=delete_runtime_text,
        strip_text_coverage=True,
    )
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    assert index.coverage["ocr"].mode == "available"
    assert index.coverage["ocr"].ratio == 1.0
    assert any(
        "猫信使出发" in item.text
        for item in index.semantic_entries
        if "document-text" in item.tags
    )


def test_truncated_indexing_persists_partial_ocr_ratio(
    tmp_path,
    monkeypatch,
) -> None:
    # Indexing truncation must surface as coverage.ocr.ratio < 1 and the
    # cut tail must not appear in the semantic entries.
    monkeypatch.setattr(
        "services.document_reader.MAX_INDEXED_TEXT_CHARS",
        5000,
    )
    marker = "末尾唯一标记：星光不灭。"
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="long.txt",
        content=("剧情推进。" * 1600 + marker).encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="doc-truncated",
        shots=[_document_shot(1, "全文概括。")],
    )
    coverage = read_result["textCoverage"]
    assert coverage["indexedChars"] == 5000
    assert coverage["extractedChars"] > 5000
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    ocr = index.coverage["ocr"]
    assert ocr.mode == "available"
    assert ocr.producer == "document_reader"
    assert ocr.ratio == pytest.approx(
        5000 / coverage["extractedChars"],
    )
    assert all(
        marker not in item.text
        for item in index.semantic_entries
        if "document-text" in item.tags
    )


def test_unknown_extraction_total_yields_unknown_ratio(
    tmp_path,
    monkeypatch,
) -> None:
    # A row-capped table has an unknowable extraction total: coverage
    # stays available but the ratio is honestly unknown (None).
    monkeypatch.setattr(
        "vendor.mm_plugins.renderers.data.FULL_TEXT_ROW_CAP",
        50,
    )
    rows = ["scene,cost"]
    rows += [f"scene-{number},{number}" for number in range(1, 62)]
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="big.csv",
        content=("\n".join(rows) + "\n").encode("utf-8"),
        media_type="text/csv",
    )
    service = SourceMediaAnalysisService(services)
    read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="doc-unknown-total",
        shots=[_document_shot(1, "数据表概括。")],
    )
    assert read_result["textCoverage"]["extractionComplete"] is False
    assert read_result["textCoverage"]["extractionFraction"] is None
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    ocr = index.coverage["ocr"]
    assert ocr.mode == "available"
    assert ocr.producer == "document_reader"
    assert ocr.ratio is None


def test_srt_text_only_commit_rejects_page_image_intervals(tmp_path) -> None:
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="dialogue.srt",
        content=b"1\n00:00:01,000 --> 00:00:02,500\nhello\n",
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    read_context = _running_context(
        service,
        services,
        asset_id,
        tool_call_id="srt-read-bad",
    )

    async def scenario():
        read_result = await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": f"asset-version:{version_id}"},
            context=read_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            read_context.specialist_run_id,
            message_id="tool-srt-result-bad",
            role="tool",
            content_parts=[
                {"type": "text", "text": json.dumps(read_result)},
            ],
            metadata={"tool": "read_document", "toolCallId": "srt-read-bad"},
        )
        commit_context = _running_context(
            service,
            services,
            asset_id,
            tool_call_id="srt-commit-bad",
        )
        return await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="srt-commit-bad",
            context=commit_context,
            arguments={
                "summary": "页区间错误的文本型提交。",
                "shots": [
                    _document_shot(1, "第一页"),
                    _document_shot(2, "不存在的第二页"),
                ],
                "entities": [],
                "semanticEntries": [],
                "moduleResultRefs": {"document": read_result["resultRef"]},
            },
        )

    with pytest.raises(ValidationError) as excinfo:
        asyncio.run(scenario())
    assert "页伪" in str(excinfo.value)
