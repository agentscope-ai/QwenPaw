# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
import pytest

from api.dependencies import project_file_services
from api.file_asset_routes import (
    _AssetInput,
    _ingest_many_sync,
    _register_remote_asset_sync,
)
from api.file_execution_routes import _cancel_task_sync
from api.file_source_intelligence_routes import router as source_router
from domain.enums import SpecialistRole, SpecialistRunStatus, TaskStatus
from domain.errors import StorageIntegrityError, ValidationError
from models.asr_model import ASRResult, ASRSegment
from schemas.assets import (
    SourceAgentIntelligenceInput,
    SourceMediaMetadata,
    SourceModelRunRef,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    IndexedFile,
    Project,
    SourceAssetVersion,
)
from services.project_files.store import ProjectNotFound
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from services.source_analysis import (
    DefaultSourceMediaAnalyzer,
    SourceAgentToolContext,
    SourceAnalyzerConfigurationError,
    SourceAnalyzerOutput,
    SourceMediaAnalysisInput,
    SourceMediaAnalysisService,
    clear_source_analysis_service_registry,
    recover_interrupted_source_analysis,
    shutdown_source_analysis_services,
    source_analysis_service,
)
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskAttemptStatus,
)


def _services_with_source(
    tmp_path: Path,
) -> tuple[CreatorFileServices, str, str]:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id="project-1", name="One"))
    result, _ = _ingest_many_sync(
        services,
        project_id="project-1",
        key="asset-1",
        inputs=[
            _AssetInput(
                name="source.mp4",
                content=b"verified-source-bytes",
                media_type="video/mp4",
            ),
        ],
        attach_source=True,
        scope="source-analysis-test",
    )
    item = result["items"][0]
    return services, item["assetId"], item["assetVersionId"]


def _output(evidence_ref: str) -> SourceAnalyzerOutput:
    coverage = {
        "visual": {
            "mode": "available",
            "producer": "model_native",
            "ratio": 1.0,
        },
        "asr": {"mode": "unavailable", "producer": None, "ratio": None},
        "ocr": {"mode": "unavailable", "producer": None, "ratio": None},
        "audio": {"mode": "unavailable", "producer": None, "ratio": None},
    }
    run = SourceModelRunRef(id="fake-run-1", provider="fake", model="fake-v1")
    return SourceAnalyzerOutput(
        raw={
            "summary": "海边日落与人物行走",
            "coverage": coverage,
            "shots": [
                {
                    "id": "shot-000001",
                    "startMs": 0,
                    "endMs": 5000,
                    "description": "人物在海边日落中行走",
                    "events": ["行走", "日落"],
                    "keyframeRef": evidence_ref,
                    "confidence": 0.9,
                    "modelRunId": run.id,
                    "evidenceFrameRefs": [evidence_ref],
                },
            ],
            "transcript": [],
            "words": [],
            "ocrSegments": [],
            "audioEvents": [],
            "entities": [],
            "semanticEntries": [
                {
                    "id": "semantic-000001",
                    "text": "海边 日落 人物 行走",
                    "tags": ["海边", "日落"],
                    "confidence": 0.9,
                    "modelRunId": run.id,
                    "evidenceFrameRefs": [evidence_ref],
                },
            ],
        },
        media=SourceMediaMetadata(
            mediaKind="video",
            mediaType="video/mp4",
            durationMs=5000,
            width=1920,
            height=1080,
        ),
        model_runs=(run,),
        coverage_policy=coverage,
        provenance_refs=(evidence_ref,),
    )


class FakeAnalyzer:
    def __init__(self) -> None:
        self.observed_bytes: bytes | None = None
        self.observed_path: Path | None = None

    async def analyze(
        self,
        request: SourceMediaAnalysisInput,
    ) -> SourceAnalyzerOutput:
        self.observed_bytes = request.local_path.read_bytes()
        self.observed_path = request.local_path
        return _output(request.evidence_ref)


class BlockingAnalyzer(FakeAnalyzer):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(
        self,
        request: SourceMediaAnalysisInput,
    ) -> SourceAnalyzerOutput:
        self.observed_bytes = request.local_path.read_bytes()
        self.observed_path = request.local_path
        self.started.set()
        await self.release.wait()
        return _output(request.evidence_ref)


class RemoteFakeAnalyzer:
    def __init__(self) -> None:
        self.observed_url: str | None = None
        self.observed_local_path: Path | None = None

    async def analyze(
        self,
        request: SourceMediaAnalysisInput,
    ) -> SourceAnalyzerOutput:
        self.observed_url = request.source_url
        self.observed_local_path = request.local_path
        return _output(request.evidence_ref)


def _dispatch(
    service: SourceMediaAnalysisService,
    asset_id: str,
    command_id: str,
):
    return service.dispatch(
        project_id="project-1",
        target_ref=f"asset:{asset_id}",
        command_id=command_id,
        start=False,
    )


def test_fake_provider_publishes_one_canonical_index_and_read_apis(
    tmp_path,
) -> None:
    services, asset_id, asset_version_id = _services_with_source(tmp_path)
    analyzer = FakeAnalyzer()
    service = SourceMediaAnalysisService(services, analyzer=analyzer)

    async def scenario():
        dispatch = await _dispatch(service, asset_id, "analyze-1")
        completed = await service.execute(dispatch.job)
        replay = await _dispatch(service, asset_id, "analyze-1")
        return dispatch, completed, replay

    dispatch, completed, replay = asyncio.run(scenario())
    assert completed.status is TaskStatus.SUCCEEDED
    assert replay.task.status is TaskStatus.SUCCEEDED
    assert replay.job.input_generation == dispatch.job.input_generation
    assert analyzer.observed_bytes == b"verified-source-bytes"
    assert analyzer.observed_path is not None
    assert not analyzer.observed_path.exists()

    snapshot = services.projects.read("project-1")
    source = next(iter(snapshot.project.sources.sources.items.values()))
    intelligence_id = source.current_intelligence_version_id
    assert snapshot.generation == 2
    assert intelligence_id == dispatch.job.intelligence_version_id
    intelligence = snapshot.project.assets.intelligence_versions_by_id[
        intelligence_id
    ]
    assert intelligence.source_asset_version_id == asset_version_id
    indexed = snapshot.project.assets.files_by_id[intelligence.file_id]
    assert indexed.kind == "source_intelligence"
    assert indexed.relative_uri.endswith(f"/{intelligence_id}.json")
    assert service.load("project-1", asset_id).summary == "海边日落与人物行走"
    query = service.query("project-1", asset_id, "日落")
    assert {item.kind for item in query.items} >= {
        "summary",
        "shot",
        "semantic",
    }

    app = FastAPI()
    app.include_router(source_router)
    app.dependency_overrides[project_file_services] = lambda: services

    async def read_api():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            current = await client.get(
                f"/projects/project-1/assets/{asset_id}/understanding",
            )
            exact = await client.get(
                f"/projects/project-1/assets/{asset_id}/understanding/{intelligence_id}",
            )
            queried = await client.get(
                f"/projects/project-1/assets/{asset_id}/source-index/query",
                params={"query": "日落"},
            )
        return current, exact, queried

    current, exact, queried = asyncio.run(read_api())
    assert (
        current.status_code == exact.status_code == queried.status_code == 200
    )
    assert current.json()["id"] == exact.json()["id"] == intelligence_id
    assert queried.json()["items"]


def test_url_backed_source_is_analyzed_before_runtime_cache_exists(
    tmp_path,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id="project-1", name="One"))
    item = _register_remote_asset_sync(
        services,
        project_id="project-1",
        key="remote-source",
        url="https://assets.example/source.mp4",
        requested_name="source.mp4",
        attach_source=True,
        scope="POST-assets",
    )
    analyzer = RemoteFakeAnalyzer()
    service = SourceMediaAnalysisService(services, analyzer=analyzer)

    async def scenario():
        dispatch = await _dispatch(service, item["assetId"], "analyze-remote")
        return dispatch, await service.execute(dispatch.job)

    dispatch, completed = asyncio.run(scenario())
    assert dispatch.job.indexed_file is None
    assert completed.status is TaskStatus.SUCCEEDED
    assert analyzer.observed_local_path is None
    assert analyzer.observed_url == "https://assets.example/source.mp4"
    project = services.projects.read("project-1").project
    assert (
        project.assets.source_versions_by_id[item["assetVersionId"]].file_id
        is None
    )
    source = next(iter(project.sources.sources.items.values()))
    assert source.current_intelligence_version_id is not None


def test_materialize_after_project_delete_does_not_recreate_project(
    tmp_path,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services, analyzer=FakeAnalyzer())
    dispatch = asyncio.run(_dispatch(service, asset_id, "deleted-before-copy"))
    project_root = services.projects.project_root("project-1")

    services.projects.delete("project-1")
    assert not project_root.exists()
    with pytest.raises(ProjectNotFound):
        service._materialize_verified_input_sync(dispatch.job)
    assert not project_root.exists()


def test_materialize_rejects_symlinked_source_temp_directory(tmp_path) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services, analyzer=FakeAnalyzer())
    dispatch = asyncio.run(_dispatch(service, asset_id, "symlinked-copy"))
    external = tmp_path / "outside"
    external.mkdir()
    temp_parent = (
        services.projects.project_root("project-1")
        / "runtime"
        / "temp"
        / "source-analysis"
    )
    temp_parent.symlink_to(external, target_is_directory=True)

    with pytest.raises(StorageIntegrityError, match="symlink"):
        service._materialize_verified_input_sync(dispatch.job)
    assert list(external.iterdir()) == []


def test_changed_project_head_quarantines_late_provider_result(
    tmp_path,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    analyzer = BlockingAnalyzer()
    service = SourceMediaAnalysisService(services, analyzer=analyzer)

    async def scenario():
        dispatch = await _dispatch(service, asset_id, "analyze-stale")
        worker = asyncio.create_task(service.execute(dispatch.job))
        await analyzer.started.wait()
        base = services.projects.read("project-1")
        candidate = base.project.model_dump(mode="json")
        candidate["description"] = "user changed while provider was running"
        services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.FRONTEND_EDIT,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="frontend-change",
            round_id="round-frontend-change",
            transaction_id="commit-frontend-change",
            advance_accepted_baseline=True,
        )
        analyzer.release.set()
        return dispatch, await worker

    dispatch, completed = asyncio.run(scenario())
    assert completed.status is TaskStatus.QUARANTINED
    assert (
        service.executions.get_run(
            "project-1",
            dispatch.job.run_id,
        ).status
        is SpecialistRunStatus.STALE
    )
    quarantine = service.executions.get_quarantine_record(
        "project-1",
        dispatch.job.task_id,
    )
    assert "generation/ETag" in quarantine.reason
    project = services.projects.read("project-1").project
    assert not project.assets.intelligence_versions_by_id
    assert (
        next(
            iter(project.sources.sources.items.values()),
        ).current_intelligence_version_id
        is None
    )


def test_cancelled_task_quarantines_provider_result_without_project_commit(
    tmp_path,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    analyzer = BlockingAnalyzer()
    service = SourceMediaAnalysisService(services, analyzer=analyzer)

    async def scenario():
        dispatch = await _dispatch(service, asset_id, "analyze-cancel")
        worker = asyncio.create_task(service.execute(dispatch.job))
        await analyzer.started.wait()
        await asyncio.to_thread(
            _cancel_task_sync,
            services,
            "project-1",
            dispatch.job.task_id,
            "stop",
        )
        analyzer.release.set()
        return dispatch, await worker

    dispatch, completed = asyncio.run(scenario())
    assert completed.status is TaskStatus.CANCELLED
    assert (
        service.executions.get_run(
            "project-1",
            dispatch.job.run_id,
        ).status
        is SpecialistRunStatus.CANCELLED
    )
    service.executions.get_quarantine_record("project-1", dispatch.job.task_id)
    project = services.projects.read("project-1").project
    assert project.generation == 1
    assert not project.assets.intelligence_versions_by_id


def test_default_inner_provider_is_removed_in_favor_of_outer_vlm_commit(
    tmp_path,
    monkeypatch,
) -> None:
    del monkeypatch
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-probed-when-config-is-missing")
    version = SourceAssetVersion(
        version_id="version-1",
        logical_asset_id="asset-1",
        name="source.mp4",
        file_id="file-1",
        checksum="a" * 64,
        media_kind="video",
        media_type="video/mp4",
        created_at=datetime.now(UTC),
    )
    indexed = IndexedFile(
        file_id="file-1",
        kind="source_original",
        relative_uri="assets/sources/source.mp4",
        sha256="a" * 64,
        size_bytes=source.stat().st_size,
        media_type="video/mp4",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(
        SourceAnalyzerConfigurationError,
        match="outer Source Intelligence VLM must call commit_source_intelligence",
    ):
        asyncio.run(
            DefaultSourceMediaAnalyzer().analyze(
                SourceMediaAnalysisInput(
                    project_id="project-1",
                    source_id="source-1",
                    logical_asset_id="asset-1",
                    source_version=version,
                    indexed_file=indexed,
                    local_path=source,
                    evidence_ref="asset://asset-1@version-1",
                ),
            ),
        )


def test_legacy_dispatch_fails_closed_without_calling_an_inner_vlm(
    tmp_path,
    monkeypatch,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    monkeypatch.setattr(
        "services.runtime_files.media_probe.resolve_ffprobe",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "services.runtime_files.media_probe.resolve_ffmpeg",
        lambda: None,
    )
    service = SourceMediaAnalysisService(
        services,
        analyzer=DefaultSourceMediaAnalyzer(),
    )

    async def scenario():
        dispatch = await _dispatch(service, asset_id, "missing-ffprobe")
        completed = await service.execute(dispatch.job)
        replay = await service.execute(dispatch.job)
        return dispatch, completed, replay

    dispatch, completed, replay = asyncio.run(scenario())
    assert completed.status is replay.status is TaskStatus.FAILED
    assert completed.error == {
        "code": "SOURCEANALYZERCONFIGURATIONERROR",
        "message": (
            "Direct inner Source VLM analysis has been removed; the outer Source "
            "Intelligence VLM must call commit_source_intelligence"
        ),
        "retryable": False,
    }
    assert (
        service.executions.get_run(
            "project-1",
            dispatch.job.run_id,
        ).status
        is SpecialistRunStatus.FAILED
    )
    assert [
        attempt.status
        for attempt in service.executions.list_attempts(
            "project-1",
            dispatch.job.task_id,
        )
    ] == [TaskAttemptStatus.RUNNING, TaskAttemptStatus.FAILED]


def test_outer_vlm_commit_persists_timeline_and_merges_exact_asr_result(
    tmp_path,
    monkeypatch,
) -> None:
    services, asset_id, version_id = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services)
    snapshot = services.projects.read("project-1")
    source_run_id = "specialist-run-outer-vlm"
    service.executions.create_specialist_run(
        SpecialistRunRecord(
            run_id=source_run_id,
            project_id="project-1",
            round_id="round-outer-vlm",
            role=SpecialistRole.SOURCE_INTELLIGENCE,
            target_refs=[f"asset:{asset_id}"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
        ),
    )
    service.executions.transition_specialist_run(
        "project-1",
        source_run_id,
        expected_status=SpecialistRunStatus.QUEUED,
        status=SpecialistRunStatus.RUNNING_MODEL,
    )
    monkeypatch.setattr(
        "services.source_analysis.service._probe_media",
        lambda _path, version: SourceMediaMetadata(
            mediaKind=version.media_kind,
            mediaType=version.media_type,
            durationMs=10_000,
            width=1920,
            height=1080,
        ),
    )
    monkeypatch.setattr(
        "services.source_analysis.service.model_config.get_asr_api_key",
        lambda: "configured",
    )

    async def fake_transcribe(_media_uri):
        return ASRResult(
            provider="fake-asr",
            model="asr-v1",
            segments=(ASRSegment(1000, 2500, "保持向前走"),),
        )

    monkeypatch.setattr(
        "services.source_analysis.service.asr_model.transcribe",
        fake_transcribe,
    )
    asr_context = SourceAgentToolContext(
        specialist_run_id=source_run_id,
        tool_call_id="asr-call",
        assistant_message_id="assistant-asr",
        provider_message_id="provider-asr",
        provider="configured_vlm",
        model="vlm-v1",
    )

    async def scenario():
        asr = await service.transcribe_source_audio(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            context=asr_context,
        )
        service.executions.append_specialist_message(
            "project-1",
            source_run_id,
            message_id="tool-asr-result",
            role="tool",
            content_parts=[{"type": "text", "text": json.dumps(asr)}],
            metadata={
                "tool": "transcribe_source_audio",
                "toolCallId": "asr-call",
            },
        )
        committed = await service.commit_agent_intelligence(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="outer-vlm-commit",
            context=SourceAgentToolContext(
                specialist_run_id=source_run_id,
                tool_call_id="commit-call",
                assistant_message_id="assistant-commit",
                provider_message_id="provider-vlm-commit",
                provider="configured_vlm",
                model="vlm-v1",
            ),
            arguments={
                "summary": "人物在十秒视频中持续向前行走，画面由全景过渡到中景。",
                "shots": [
                    {
                        "startMs": 0,
                        "endMs": 5000,
                        "description": "全景固定机位，人物从远处进入并向前行走。",
                        "events": ["进入画面", "向前行走"],
                        "confidence": 0.95,
                    },
                    {
                        "startMs": 5000,
                        "endMs": 10_000,
                        "description": "中景继续跟随人物，动作持续至视频结尾。",
                        "events": ["持续行走", "接近镜头"],
                        "confidence": 0.93,
                    },
                ],
                "entities": [
                    {
                        "kind": "person",
                        "label": "主要人物",
                        "description": "全程可见并持续移动",
                        "startMs": 0,
                        "endMs": 10_000,
                        "confidence": 0.96,
                    },
                ],
                "semanticEntries": [
                    {
                        "startMs": 0,
                        "endMs": 5000,
                        "text": "人物从远处进入并开始行走",
                        "tags": ["进入", "行走", "全景"],
                        "confidence": 0.95,
                    },
                    {
                        "startMs": 5000,
                        "endMs": 10_000,
                        "text": "人物继续接近镜头直至结尾",
                        "tags": ["接近镜头", "中景", "行走"],
                        "confidence": 0.93,
                    },
                ],
                "moduleResultRefs": {"asr": asr["resultRef"]},
            },
        )
        return asr, committed

    asr, committed = asyncio.run(scenario())
    assert committed["status"] == "SUCCEEDED"
    assert committed["shotCount"] == 2
    index = service.load("project-1", asset_id)
    assert index.asset_version_id == version_id
    assert [(item.start_ms, item.end_ms) for item in index.shots] == [
        (0, 5000),
        (5000, 10_000),
    ]
    assert index.transcript[0].text == "保持向前走"
    assert index.transcript[0].model_run_id == asr["modelRun"]["id"]
    assert [item.model for item in index.model_runs] == ["vlm-v1", "asr-v1"]


def test_outer_vlm_commit_resolves_remote_cache_media_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id="project-1", name="One"))
    item = _register_remote_asset_sync(
        services,
        project_id="project-1",
        key="remote-cached-source",
        url="https://assets.example/cat.mp4",
        requested_name="cat.mp4",
        attach_source=True,
        scope="POST-assets",
    )
    cache_path = tmp_path / "cat-cache.mp4"
    cache_path.write_bytes(b"cached-source")
    monkeypatch.setattr(
        "services.source_analysis.service.resolve_remote_cache",
        lambda *_args, **_kwargs: SimpleNamespace(path=cache_path),
    )
    monkeypatch.setattr(
        "services.source_analysis.service._probe_media",
        lambda path, version: SourceMediaMetadata(
            mediaKind=version.media_kind,
            mediaType=version.media_type,
            durationMs=3_502_567,
            width=640,
            height=360,
        ),
    )
    service = SourceMediaAnalysisService(services)

    resolved = service._resolve_agent_source_sync(
        "project-1",
        f"asset:{item['assetId']}",
    )

    assert resolved[2].version_id == item["assetVersionId"]
    assert resolved[4] == cache_path
    assert resolved[6].duration_ms == 3_502_567


def test_video_coverage_error_reports_actual_duration_and_required_coverage() -> (
    None
):
    media = SourceMediaMetadata(
        mediaKind="video",
        mediaType="video/mp4",
        durationMs=19_867,
        width=1280,
        height=720,
    )
    payload = SourceAgentIntelligenceInput.model_validate(
        {
            "summary": "宠物在户外移动，当前只记录到部分时间线。",
            "shots": [
                {
                    "startMs": 0,
                    "endMs": 15_000,
                    "description": "低角度镜头记录宠物穿过户外场地。",
                    "events": ["向前移动"],
                    "confidence": 0.9,
                },
            ],
            "entities": [],
            "semanticEntries": [
                {
                    "startMs": 0,
                    "endMs": 15_000,
                    "text": "宠物穿过户外场地",
                    "tags": ["宠物", "户外"],
                    "confidence": 0.9,
                },
            ],
        },
    )

    with pytest.raises(ValidationError) as caught:
        SourceMediaAnalysisService._assert_agent_ranges(payload, media)

    message = str(caught.value)
    assert "19867ms" in message
    assert "75.5%" in message
    assert "17881ms" in message
    assert "不得根据文件大小猜测时长" in message


def test_long_video_commit_accepts_natural_shots_and_requires_precise_semantics() -> (
    None
):
    media = SourceMediaMetadata(
        mediaKind="video",
        mediaType="video/mp4",
        durationMs=600_000,
        width=640,
        height=360,
    )

    def payload(
        duration_ms: int,
        shot_count: int,
        precise_semantic_count: int,
    ):
        boundaries = [
            round(index * duration_ms / shot_count)
            for index in range(shot_count + 1)
        ]
        shots = [
            {
                "startMs": boundaries[index],
                "endMs": boundaries[index + 1],
                "description": (f"连续场景 {index + 1}，记录主体动作、构图和画质变化。"),
                "events": [f"状态变化 {index + 1}"],
                "confidence": 0.9,
            }
            for index in range(shot_count)
        ]
        semantics = [
            {
                "startMs": index * 30_000,
                "endMs": index * 30_000 + 20_000,
                "text": f"精确事件 {index + 1}",
                "tags": ["event", f"event-{index + 1}"],
                "confidence": 0.9,
            }
            for index in range(precise_semantic_count)
        ]
        semantics.append(
            {
                "startMs": 0,
                "endMs": duration_ms,
                "text": "全局镜头特征",
                "tags": ["global", "camera"],
                "confidence": 0.8,
            },
        )
        return SourceAgentIntelligenceInput.model_validate(
            {
                "summary": "十分钟长视频的完整多粒度理解。",
                "shots": shots,
                "entities": [],
                "semanticEntries": semantics,
            },
        )

    with pytest.raises(ValidationError, match="至少需要 4 条"):
        SourceMediaAnalysisService._assert_agent_ranges(
            payload(600_000, 6, 3),
            media,
        )
    assert (
        SourceMediaAnalysisService._assert_agent_ranges(
            payload(600_000, 6, 4),
            media,
        )
        == 1.0
    )

    long_media = media.model_copy(update={"duration_ms": 3_502_567})
    assert (
        SourceMediaAnalysisService._assert_agent_ranges(
            payload(3_502_567, 21, 6),
            long_media,
        )
        == 1.0
    )


def test_analyze_endpoint_rejects_removed_inner_vlm_path(
    tmp_path,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    app = FastAPI()
    app.include_router(source_router)
    app.dependency_overrides[project_file_services] = lambda: services

    async def submit():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                f"/projects/project-1/assets/{asset_id}/analyze",
                headers={"Idempotency-Key": "analyze-command"},
                json={
                    "clientRequestId": "analyze-command",
                },
            )

    response = asyncio.run(submit())
    assert response.status_code == 409
    assert "outer Source Intelligence VLM" in response.json()["detail"]


def test_source_admission_replay_repairs_run_created_before_task(
    tmp_path,
    monkeypatch,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services, analyzer=FakeAnalyzer())
    create_task = service.executions.create_task
    attempts = 0

    def fail_first_task_create(record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated task write interruption")
        return create_task(record)

    monkeypatch.setattr(
        service.executions,
        "create_task",
        fail_first_task_create,
    )
    with pytest.raises(OSError, match="task write interruption"):
        asyncio.run(_dispatch(service, asset_id, "repair-orphan-run"))

    replay = asyncio.run(_dispatch(service, asset_id, "repair-orphan-run"))
    assert replay.run.run_id == replay.job.run_id
    assert replay.task.task_id == replay.job.task_id
    assert replay.task.run_id == replay.run.run_id
    assert attempts == 2


def test_startup_recovery_repairs_then_fails_closed_orphan_source_run(
    tmp_path,
    monkeypatch,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services, analyzer=FakeAnalyzer())
    create_task = service.executions.create_task

    def interrupted_task_create(_record):
        raise OSError("simulated admission interruption")

    monkeypatch.setattr(
        service.executions,
        "create_task",
        interrupted_task_create,
    )
    with pytest.raises(OSError, match="admission interruption"):
        asyncio.run(_dispatch(service, asset_id, "startup-repair-orphan-run"))
    monkeypatch.setattr(service.executions, "create_task", create_task)

    assert recover_interrupted_source_analysis(services) == 1
    replay = asyncio.run(
        _dispatch(service, asset_id, "startup-repair-orphan-run"),
    )
    assert replay.task.status is TaskStatus.FAILED
    assert replay.run.status is SpecialistRunStatus.FAILED
    assert replay.task.error["code"] == "SOURCE_ANALYSIS_PROCESS_RESTARTED"


def test_startup_recovery_converges_project_commit_before_task_completion(
    tmp_path,
    monkeypatch,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services, analyzer=FakeAnalyzer())
    complete_task = service._complete_task_sync

    def interrupted_completion(_job, _published):
        raise OSError("simulated completion write interruption")

    monkeypatch.setattr(service, "_complete_task_sync", interrupted_completion)
    dispatch = asyncio.run(_dispatch(service, asset_id, "recover-published"))
    with pytest.raises(OSError, match="completion write interruption"):
        asyncio.run(service.execute(dispatch.job))

    project = services.projects.read("project-1").project
    assert (
        next(
            iter(project.sources.sources.items.values()),
        ).current_intelligence_version_id
        == dispatch.job.intelligence_version_id
    )
    assert (
        service.executions.get_task(
            "project-1",
            dispatch.job.task_id,
        ).status
        is TaskStatus.RUNNING
    )
    assert (
        service.executions.get_run(
            "project-1",
            dispatch.job.run_id,
        ).status
        is SpecialistRunStatus.RUNNING_MODEL
    )

    monkeypatch.setattr(service, "_complete_task_sync", complete_task)
    assert recover_interrupted_source_analysis(services) == 1
    assert recover_interrupted_source_analysis(services) == 0
    assert (
        service.executions.get_task(
            "project-1",
            dispatch.job.task_id,
        ).status
        is TaskStatus.SUCCEEDED
    )
    assert (
        service.executions.get_run(
            "project-1",
            dispatch.job.run_id,
        ).status
        is SpecialistRunStatus.SUCCEEDED
    )


def test_startup_recovery_fails_closed_queued_and_running_source_tasks(
    tmp_path,
) -> None:
    services, asset_id, _ = _services_with_source(tmp_path)
    service = SourceMediaAnalysisService(services, analyzer=FakeAnalyzer())

    async def prepare():
        queued = await _dispatch(service, asset_id, "queued-before-restart")
        running = await _dispatch(service, asset_id, "running-before-restart")
        service.executions.transition_run(
            "project-1",
            running.job.run_id,
            expected_status=SpecialistRunStatus.QUEUED,
            status=SpecialistRunStatus.RUNNING_MODEL,
        )
        service.executions.append_attempt(
            "project-1",
            running.job.task_id,
            event_id=f"{running.job.attempt_id}-running",
            attempt_id=running.job.attempt_id,
            status=TaskAttemptStatus.RUNNING,
            input={
                "sourceAssetVersionId": running.job.source_version.version_id,
            },
        )
        return queued, running

    queued, running = asyncio.run(prepare())
    assert recover_interrupted_source_analysis(services) == 2
    assert recover_interrupted_source_analysis(services) == 0
    for dispatch in (queued, running):
        task = service.executions.get_task("project-1", dispatch.job.task_id)
        run = service.executions.get_run("project-1", dispatch.job.run_id)
        assert task.status is TaskStatus.FAILED
        assert task.error["code"] == "SOURCE_ANALYSIS_PROCESS_RESTARTED"
        assert run.status is SpecialistRunStatus.FAILED
    assert [
        item.status
        for item in service.executions.list_attempts(
            "project-1",
            running.job.task_id,
        )
    ] == [TaskAttemptStatus.RUNNING, TaskAttemptStatus.FAILED]


def test_shutdown_cancels_and_awaits_registered_source_workers(
    tmp_path,
) -> None:
    clear_source_analysis_service_registry()
    services, asset_id, _ = _services_with_source(tmp_path)
    analyzer = BlockingAnalyzer()

    async def scenario():
        service = source_analysis_service(services)
        service.analyzer = analyzer
        dispatch = await service.dispatch(
            project_id="project-1",
            target_ref=f"asset:{asset_id}",
            command_id="shutdown-running",
            start=True,
        )
        await analyzer.started.wait()
        await shutdown_source_analysis_services()
        return service, dispatch

    service, dispatch = asyncio.run(scenario())
    assert (
        service.executions.get_task(
            "project-1",
            dispatch.job.task_id,
        ).status
        is TaskStatus.CANCELLED
    )
    assert (
        service.executions.get_run(
            "project-1",
            dispatch.job.run_id,
        ).status
        is SpecialistRunStatus.CANCELLED
    )
