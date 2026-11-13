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
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.execution_models import SpecialistRunRecord
from services.source_analysis import (
    SourceAgentToolContext,
    SourceMediaAnalysisService,
)
from services.source_analysis.service import (
    document_indexed_text_path,
    resolve_document_page_ref,
)


def _pdf_bytes(pages: int = 3, *, text: str | None = None) -> bytes:
    import io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        for number in range(1, pages + 1):
            fig = plt.figure(figsize=(4, 3))
            fig.text(
                0.1,
                0.5,
                text or f"Script page {number} Scene beats {number}",
            )
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
            _AssetInput(name=name, content=content, media_type=media_type),
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


def _read_then_commit(
    service: SourceMediaAnalysisService,
    services: CreatorFileServices,
    asset_id: str,
    version_id: str,
    *,
    tag: str,
    shots: list[dict],
    between_read_and_commit=None,
    mutate_stored=None,
    extra_arguments: dict | None = None,
):
    """Shared read -> (mutate) -> commit flow for document tests."""
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
                **(extra_arguments or {}),
            },
        )
        return read_result, committed

    return asyncio.run(scenario())


def test_document_commit_produces_document_index(tmp_path) -> None:
    services, asset_id, version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="doc",
        shots=[
            _document_shot(1, "封面页：标题与主角介绍。"),
            _document_shot(2, "第二页：冲突展开的场景节拍。"),
            _document_shot(3, "第三页：结尾与情绪收束。"),
        ],
        extra_arguments={
            "summary": "三页剧本：逐页给出场景节拍与关键动作。",
            "semanticEntries": [
                {
                    "text": "第 2 页给出冲突场景的节拍列表",
                    "tags": ["page-2", "冲突"],
                    "confidence": 0.9,
                },
            ],
        },
    )

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
    assert read_result["format"] == "pdf"
    assert read_result["pageCount"] == 3
    assert "Scene beats 2" in read_result["textExcerpt"]
    resolved = resolve_document_page_ref(
        services.projects.project_root("project-1"),
        read_result["pageImageRefs"][0],
    )
    assert resolved is not None and resolved[1] == 1
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

    # Admission boundary: a fileRef outside the admitted asset is rejected.
    async def out_of_boundary():
        return await service.read_source_document(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            arguments={"fileRef": "asset-version:another-project-version"},
            context=_running_context(
                service,
                services,
                asset_id,
                tool_call_id="doc-call-boundary",
            ),
        )

    with pytest.raises(ValidationError, match="准入边界"):
        asyncio.run(out_of_boundary())


def test_document_commit_rejects_wrong_page_intervals(tmp_path) -> None:
    services, asset_id, version_id = _services_with_document(tmp_path)
    service = SourceMediaAnalysisService(services)
    with pytest.raises(ValidationError, match="页伪"):
        _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag="doc-mismatch",
            shots=[_document_shot(1, "只有一页的提交")],
        )


_LONG_TEXT_MARKER = "结尾彩蛋：星光电影院重新亮灯。"


def _long_text_body() -> bytes:
    # A text source larger than the 20k model excerpt: the deterministic
    # semantic index must still contain content past the excerpt boundary.
    body = "\n\n".join(
        f"段落 {number}：" + "剧情推进。" * 120 for number in range(1, 50)
    )
    content = f"{body}\n\n{_LONG_TEXT_MARKER}\n"
    assert len(content) > 25_000
    return content.encode("utf-8")


def test_long_text_source_enters_document_flow_end_to_end(tmp_path) -> None:
    # The tool result stays bounded for model context, while the indexed
    # text is persisted separately with honest coverage numbers.
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="long-script.txt",
        content=_long_text_body(),
        media_type="text/plain",
    )
    snapshot = services.projects.read("project-1")
    assert (
        snapshot.project.assets.source_versions_by_id[version_id].media_kind
        == "document"
    )
    service = SourceMediaAnalysisService(services)
    read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="long-txt",
        shots=[_document_shot(1, "全文概括。")],
    )
    assert committed["status"] == "SUCCEEDED"
    index = service.load("project-1", asset_id)
    assert index.media.media_kind == "document"
    assert index.media.document is not None
    assert len(read_result["textExcerpt"]) <= 20_000
    assert read_result["textCoverage"]["extractedChars"] > 25_000
    assert (
        read_result["textCoverage"]["indexedChars"]
        == read_result["textCoverage"]["extractedChars"]
    )
    assert _LONG_TEXT_MARKER not in read_result["textExcerpt"]
    doc_text = [
        item for item in index.semantic_entries if "document-text" in item.tags
    ]
    assert any(_LONG_TEXT_MARKER in item.text for item in doc_text)
    # Text-extraction coverage is persisted on the ocr modality.
    ocr = index.coverage["ocr"]
    assert ocr.mode == "available"
    assert ocr.producer == "document_reader"
    assert ocr.ratio == 1.0


def test_carriage_return_text_survives_commit_integrity_check(
    tmp_path,
) -> None:
    # Regression: the indexed text is persisted/verified byte-for-byte.
    # pdfium emits \r\n for line breaks inside a text block, and commits
    # previously failed the sha256 integrity check on every attempt
    # (read_text() collapsed \r\n to \n), locking the source-intelligence
    # agent into a retry loop.
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="windows-notes.pdf",
        content=_pdf_bytes(
            pages=1,
            text="Scene 1: cat enters frame\nScene 2: camera pulls back\nScene 3: rooftop finale",
        ),
        media_type="application/pdf",
    )
    service = SourceMediaAnalysisService(services)
    read_result, committed = _read_then_commit(
        service,
        services,
        asset_id,
        version_id,
        tag="cr",
        shots=[_document_shot(1, "全文概括。")],
    )

    coverage = read_result["textCoverage"]
    stored = document_indexed_text_path(
        services.projects.project_root("project-1"),
        read_result["sourceChecksum"],
        read_result["resultRef"],
    ).read_bytes()
    assert b"\r" in stored, "fixture must exercise carriage returns"
    assert len(stored.decode("utf-8")) == coverage["indexedChars"]
    assert committed["status"] == "SUCCEEDED"


@pytest.mark.parametrize(
    ("tag", "break_runtime", "coverage_mutation", "message"),
    [
        pytest.param(
            "doc-missing-file",
            "delete",
            None,
            "Runtime 文件缺失",
            id="missing-runtime-file",
        ),
        pytest.param(
            "doc-tampered-file",
            "tamper",
            None,
            "不一致",
            id="tampered-runtime-file",
        ),
        pytest.param(
            "doc-null-coverage",
            "swap",
            "null",
            "textCoverage 不合法",
            id="coverage-null",
        ),
    ],
)
def test_document_commit_fails_closed_on_indexed_text_integrity(
    tmp_path,
    tag,
    break_runtime,
    coverage_mutation,
    message,
) -> None:
    # Fail-close: a new-format result must be backed by the intact Runtime
    # indexed-text file, and an explicit "textCoverage": null must hit the
    # strict model instead of the legacy branch — otherwise a same-length
    # content swap could be committed with ratio=1.0.
    services, asset_id, version_id = _services_with_source(
        tmp_path,
        name="notes.txt",
        content=("剧情推进。" * 2000).encode("utf-8"),
        media_type="text/plain",
    )
    service = SourceMediaAnalysisService(services)
    project_root = services.projects.project_root("project-1")
    checksum = (
        services.projects.read("project-1")
        .project.assets.source_versions_by_id[version_id]
        .checksum
    )

    def break_runtime_text(read_result):
        path = document_indexed_text_path(
            project_root,
            checksum,
            read_result["resultRef"],
        )
        if break_runtime == "delete":
            path.unlink()
        elif break_runtime == "tamper":
            path.write_text("被替换的内容", encoding="utf-8")
        else:  # same-length content swap
            path.write_text(
                "Z" * len(path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )

    def mutate_stored(stored):
        stored["textCoverage"] = None

    with pytest.raises(ValidationError, match=message):
        _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag=tag,
            shots=[_document_shot(1, "全文概括。")],
            between_read_and_commit=break_runtime_text,
            mutate_stored=mutate_stored if coverage_mutation else None,
        )


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
    assert ocr.ratio == pytest.approx(5000 / coverage["extractedChars"])
    assert all(
        marker not in item.text
        for item in index.semantic_entries
        if "document-text" in item.tags
    )


def test_one_specialist_run_commits_multiple_assets(tmp_path) -> None:
    """A batch delegation commits several assets from one run.

    Round provenance (caused_by_request_id) is immutable per Round, so
    each commit must own its Round; reusing the specialist run id across
    commits rejected every asset after the first.
    """

    services, first_asset, first_version = _services_with_document(tmp_path)
    result, _ = _ingest_many_sync(
        services,
        project_id="project-1",
        key="doc-asset-2",
        inputs=[
            _AssetInput(
                name="script-two.pdf",
                content=_pdf_bytes(pages=2),
                media_type="application/pdf",
            ),
        ],
        attach_source=True,
        scope="document-source-test",
    )
    second_asset = result["items"][0]["assetId"]
    second_version = result["items"][0]["assetVersionId"]
    service = SourceMediaAnalysisService(services)

    for ordinal, (asset_id, version_id, page_count) in enumerate(
        [(first_asset, first_version, 3), (second_asset, second_version, 2)],
        start=1,
    ):
        _read_result, committed = _read_then_commit(
            service,
            services,
            asset_id,
            version_id,
            tag=f"doc-batch-{ordinal}",
            shots=[
                _document_shot(page, f"第 {page} 页节拍。")
                for page in range(1, page_count + 1)
            ],
            extra_arguments={"summary": f"第 {ordinal} 份剧本：逐页节拍。"},
        )
        assert committed["status"] == "SUCCEEDED"
    assert service.load("project-1", first_asset).summary.startswith("第 1")
    assert service.load("project-1", second_asset).summary.startswith("第 2")
