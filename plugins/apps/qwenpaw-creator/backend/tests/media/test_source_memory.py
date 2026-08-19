# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Source memory trigger/artifacts/query dispatch and projection tests."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.errors import ValidationError
from schemas.assets import SourceIntelligenceIndex, SourceMemoryRef
from services.media import source_memory
from services.media.source_observation import CLIP_SIZE_BUDGET_CAP_BYTES
from services.media.source_memory import (
    SourceMemoryProjection,
    SourceMemoryService,
    load_memory_ref,
    memory_dir,
    memory_guidance_for_targets,
)
from vendored.test_video_memory_toolkit import (
    build_fixture_index,
    build_fixture_memory,
)


def _index(
    *,
    duration_ms: int = 25 * 60 * 1000,
    media_kind: str = "video",
    checksum: str = "checksum-1",
    memory_ref: SourceMemoryRef | None = None,
) -> SourceIntelligenceIndex:
    created_at = "2026-08-01T00:00:00Z"
    evidence = {
        "assetVersionId": "version-1",
        "sourceChecksum": checksum,
        "confidence": 0.9,
        "modelRunId": "run-1",
        "evidenceFrameRefs": ["asset://asset-1@version-1"],
        "createdAt": created_at,
    }
    payload = {
        "id": "intel-1",
        "assetId": "asset-1",
        "assetVersionId": "version-1",
        "sourceChecksum": checksum,
        "modelRuns": [
            {"id": "run-1", "provider": "dashscope", "model": "qwen3.7-plus"},
        ],
        "coverage": {
            "visual": {
                "mode": "available",
                "producer": "model_native",
                "ratio": 0.95,
            },
            "asr": {"mode": "unavailable"},
            "ocr": {"mode": "unavailable"},
            "audio": {"mode": "unavailable"},
        },
        "media": {
            "mediaKind": media_kind,
            "mediaType": "video/mp4",
            "durationMs": duration_ms,
        },
        "summary": "fixture summary",
        "shots": [
            {
                "id": "shot-000001",
                "startMs": 0,
                "endMs": duration_ms,
                "description": "whole video",
                "events": ["everything"],
                "keyframeRef": "asset://asset-1@version-1",
                **evidence,
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
                "text": "fixture event",
                "tags": ["fixture"],
                "startMs": 0,
                "endMs": 20000,
                **evidence,
            },
        ],
        "createdAt": created_at,
    }
    index = SourceIntelligenceIndex.model_validate(payload)
    index.memory_ref = memory_ref
    return index


def _write_fixture_memory(project_root: Path, index_id: str) -> Path:
    directory = memory_dir(project_root, index_id)
    directory.mkdir(parents=True)
    memory = build_fixture_memory()
    embedding_index, nodes, _ = build_fixture_index(memory)
    memory.save(str(directory / "graph_memory.json"))
    embedding_index.save(str(directory / "embeddings.npz"))
    (directory / "memory_meta.json").write_text(
        json.dumps(
            {
                "indexId": index_id,
                "assetId": "asset-1",
                "assetVersionId": "version-1",
                "sourceChecksum": "checksum-1",
                "builtAt": "2026-08-01T01:00:00Z",
                "macroCount": 2,
                "superCount": 1,
                "nodeCount": len(nodes),
                "graphPath": "graph_memory.json",
                "embeddingsPath": "embeddings.npz",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return directory


def _service(tmp_path: Path) -> SourceMemoryService:
    project_root = tmp_path / "projects" / "project-1"
    project_root.mkdir(parents=True, exist_ok=True)
    services = SimpleNamespace(
        root=tmp_path,
        projects=SimpleNamespace(
            project_root=lambda project_id: tmp_path / "projects" / project_id,
        ),
    )
    return SourceMemoryService(services)


# ── trigger gating ──────────────────────────────────────────────────────────


def test_should_build_requires_video_over_threshold(
    tmp_path,
    monkeypatch,
) -> None:
    del monkeypatch
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    assert service.should_build(_index(), project_root)
    assert not service.should_build(
        _index(duration_ms=10 * 60 * 1000),
        project_root,
    )
    short_image = _index(media_kind="image", duration_ms=25 * 60 * 1000)
    assert not service.should_build(short_image, project_root)


def test_should_build_degrades_without_embedding_configuration(
    tmp_path,
    monkeypatch,
) -> None:
    # A missing embedding backend no longer blocks the build: the
    # pipeline persists a BM25-only text index instead.
    service = _service(tmp_path)
    monkeypatch.setattr(
        source_memory.model_config,
        "is_embedding_configured",
        lambda: False,
    )
    assert service.should_build(
        _index(),
        tmp_path / "projects" / "project-1",
    )


def test_should_build_skips_when_memory_already_built(
    tmp_path,
    monkeypatch,
) -> None:
    del monkeypatch
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    _write_fixture_memory(project_root, "intel-1")
    assert not service.should_build(_index(), project_root)


def test_threshold_env_override(monkeypatch) -> None:
    assert source_memory.memory_build_threshold_ms() == 20 * 60 * 1000
    monkeypatch.setenv("CREATOR_MEMORY_BUILD_THRESHOLD_MS", "5000")
    assert source_memory.memory_build_threshold_ms() == 5000
    monkeypatch.setenv("CREATOR_MEMORY_BUILD_THRESHOLD_MS", "bogus")
    assert source_memory.memory_build_threshold_ms() == 20 * 60 * 1000


# ── artifact hydration & checksum invalidation ──────────────────────────────


def test_load_memory_ref_reads_meta(tmp_path) -> None:
    project_root = tmp_path / "projects" / "project-1"
    _write_fixture_memory(project_root, "intel-1")
    ref = load_memory_ref(project_root, "intel-1", "checksum-1")
    assert ref is not None
    assert ref.macro_count == 2
    assert ref.graph_path == (
        "runtime/source-intelligence/intel-1/memory/graph_memory.json"
    )
    assert ref.embeddings_path.endswith("embeddings.npz")


def test_load_memory_ref_invalidated_by_checksum(tmp_path) -> None:
    project_root = tmp_path / "projects" / "project-1"
    _write_fixture_memory(project_root, "intel-1")
    assert load_memory_ref(project_root, "intel-1", "other-checksum") is None
    assert load_memory_ref(project_root, "intel-2", "checksum-1") is None


def test_load_memory_ref_requires_graph_artifact(tmp_path) -> None:
    project_root = tmp_path / "projects" / "project-1"
    directory = _write_fixture_memory(project_root, "intel-1")
    # A missing embeddings.npz only degrades retrieval to BM25; the ref
    # stays hydrated as long as the graph artifact survives.
    (directory / "embeddings.npz").unlink()
    assert load_memory_ref(project_root, "intel-1", "checksum-1") is not None
    (directory / "graph_memory.json").unlink()
    assert load_memory_ref(project_root, "intel-1", "checksum-1") is None


# ── index serialization contract ────────────────────────────────────────────


def test_index_dump_omits_absent_memory_ref() -> None:
    dumped = _index().model_dump(mode="json", by_alias=True)
    assert "memoryRef" not in dumped
    assert "memory_ref" not in dumped


def test_index_dump_includes_hydrated_memory_ref() -> None:
    ref = SourceMemoryRef(
        graphPath="runtime/source-intelligence/intel-1/memory/g.json",
        embeddingsPath="runtime/source-intelligence/intel-1/memory/e.npz",
        builtAt="2026-08-01T01:00:00Z",
        macroCount=7,
    )
    dumped = _index(memory_ref=ref).model_dump(mode="json", by_alias=True)
    assert dumped["memoryRef"]["macroCount"] == 7
    assert dumped["memoryRef"]["builtAt"] == "2026-08-01T01:00:00Z"


# ── projection ───────────────────────────────────────────────────────────────


def test_projection_drafts_validate_schema() -> None:
    memory = build_fixture_memory()
    projection = SourceMemoryProjection(
        indexId="intel-1",
        summary=SourceMemoryService._projection_summary(memory),
        semanticEntries=SourceMemoryService._projection_entries(memory),
    )
    assert projection.producer == "source_memory"
    assert "Fixture Video" in projection.summary
    assert projection.semantic_entries
    entry = projection.semantic_entries[0]
    assert entry.start_ms == 0
    assert entry.end_ms == 620_000
    assert entry.tags == ["orange cat"]


# ── prompt guidance ──────────────────────────────────────────────────────────


def test_memory_guidance_unavailable_without_project() -> None:
    guidance = memory_guidance_for_targets(None, None, ["asset:asset-1"])
    assert "query_source_memory" in guidance
    assert "available=false" in guidance


def test_memory_guidance_available_with_built_memory(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects" / "project-1"
    _write_fixture_memory(project_root, "intel-1")
    intelligence = SimpleNamespace(
        intelligence_version_id="intel-1",
        source_checksum="checksum-1",
    )
    project = SimpleNamespace(
        sources=SimpleNamespace(
            sources=SimpleNamespace(
                items={
                    "source-1": SimpleNamespace(
                        logical_asset_id="asset-1",
                        current_intelligence_version_id="intel-1",
                    ),
                },
            ),
        ),
        assets=SimpleNamespace(
            intelligence_versions_by_id={"intel-1": intelligence},
        ),
    )
    guidance = memory_guidance_for_targets(
        project_root,
        project,
        ["asset:asset-1"],
    )
    assert "hitWindowsMs" in guidance
    other = memory_guidance_for_targets(
        project_root,
        project,
        ["asset:asset-other"],
    )
    assert "available=false" in other


# ── query dispatch ───────────────────────────────────────────────────────────


class _FakeAnalysis:
    def __init__(self, index: SourceIntelligenceIndex) -> None:
        self._index = index

    def load(self, project_id: str, logical_asset_id: str):
        del project_id, logical_asset_id
        return self._index


def _query_service(
    tmp_path,
    monkeypatch,
    *,
    with_memory: bool = True,
) -> SourceMemoryService:
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    ref = None
    if with_memory:
        _write_fixture_memory(project_root, "intel-1")
        ref = load_memory_ref(project_root, "intel-1", "checksum-1")
        assert ref is not None
    index = _index(memory_ref=ref)
    import services.source_analysis as source_analysis_module

    monkeypatch.setattr(
        source_analysis_module,
        "source_analysis_service",
        lambda services: _FakeAnalysis(index),
    )

    async def no_embedding(query_text: str):
        del query_text
        return None

    monkeypatch.setattr(service, "_embed_query", no_embedding)
    return service


def _run_query(service: SourceMemoryService, **kwargs):
    return asyncio.run(
        service.query_memory(
            project_id="project-1",
            logical_asset_id="asset-1",
            **kwargs,
        ),
    )


def test_query_memory_reports_unavailable_without_memory(
    tmp_path,
    monkeypatch,
) -> None:
    service = _query_service(tmp_path, monkeypatch, with_memory=False)
    result = _run_query(service, query_type="summary")
    assert result["ok"] is True
    assert result["available"] is False
    assert "reason" in result


def test_query_memory_dispatches_all_nine_types(
    tmp_path,
    monkeypatch,
) -> None:
    service = _query_service(tmp_path, monkeypatch)

    summary = _run_query(service, query_type="summary")
    assert summary["result"]["title"] == "Fixture Video"

    supers = _run_query(service, query_type="super_events")
    assert supers["result"][0]["super_id"] == "super_00"

    macros = _run_query(service, query_type="macro_events")
    assert len(macros["result"]) == 2
    filtered = _run_query(
        service,
        query_type="macro_events",
        macro_id="super_00",
    )
    assert len(filtered["result"]) == 2

    subgraph = _run_query(
        service,
        query_type="subgraph",
        macro_id="macro_0000",
    )
    assert subgraph["result"]["macro_id"] == "macro_0000"
    assert subgraph["hitWindowsMs"] == [
        {"macroId": "macro_0000", "startMs": 0, "endMs": 300_000},
    ]

    nodes = _run_query(
        service,
        query_type="search_nodes",
        query="teamfight dragon",
    )
    assert nodes["result"]["results"][0]["node_id"] == "macro_0001:ev_101"
    assert {
        "macroId": "macro_0001",
        "startMs": 300_000,
        "endMs": 620_000,
    } in nodes["hitWindowsMs"]

    ocr = _run_query(
        service,
        query_type="search_ocr",
        query="Team Blue scoreboard",
    )
    assert ocr["result"][0]["macro_id"] == "macro_0000"

    asr = _run_query(service, query_type="search_asr", query="团战 零换五")
    assert asr["result"][0]["macro_id"] == "macro_0001"

    by_time = _run_query(
        service,
        query_type="by_time",
        start_ms=310_000,
        end_ms=400_000,
    )
    assert [item["macro_id"] for item in by_time["result"]] == [
        "macro_0001",
    ]

    enumerated = _run_query(
        service,
        query_type="enumerate",
        query="cat teamfight",
    )
    assert enumerated["result"]["total_matches"] > 0


def test_query_memory_degrades_to_bm25_without_embeddings_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    # Regression for the degraded-retrieval ladder: with the .npz gone,
    # search_nodes must still answer from a BM25 index rebuilt out of
    # graph_memory.json instead of erroring out.
    service = _query_service(tmp_path, monkeypatch)
    directory = memory_dir(tmp_path / "projects" / "project-1", "intel-1")
    (directory / "embeddings.npz").unlink()
    nodes = _run_query(
        service,
        query_type="search_nodes",
        query="teamfight dragon",
    )
    assert nodes["available"] is True
    assert nodes["result"]["results"][0]["node_id"] == "macro_0001:ev_101"
    asr = _run_query(service, query_type="search_asr", query="团战 零换五")
    assert asr["result"][0]["macro_id"] == "macro_0001"


def test_query_memory_validates_arguments(tmp_path, monkeypatch) -> None:
    service = _query_service(tmp_path, monkeypatch)
    with pytest.raises(ValidationError):
        _run_query(service, query_type="bogus")
    with pytest.raises(ValidationError):
        _run_query(service, query_type="search_asr")
    with pytest.raises(ValidationError):
        _run_query(service, query_type="subgraph")
    with pytest.raises(ValidationError):
        _run_query(service, query_type="by_time", start_ms=10, end_ms=10)


def test_build_datetime_marker_is_timezone_aware() -> None:
    ref = SourceMemoryRef(
        graphPath="a",
        embeddingsPath="b",
        builtAt=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        macroCount=1,
    )
    assert ref.macro_count == 1


# ── CR remediation regressions ──────────────────────────────────────────────


def _memory_ref() -> SourceMemoryRef:
    return SourceMemoryRef(
        graphPath="runtime/source-intelligence/intel-1/memory/"
        "graph_memory.json",
        embeddingsPath="runtime/source-intelligence/intel-1/memory/"
        "embeddings.npz",
        builtAt="2026-08-01T01:00:00Z",
        macroCount=2,
    )


def _write_fixture_projection(
    directory: Path,
    *,
    reviewed: bool = True,
) -> None:
    payload = {
        "indexId": "intel-1",
        "summary": "memory digest of the whole video",
        "semanticEntries": [
            {
                "text": "Super event one: rooftop exploration",
                "tags": ["memory"],
                "startMs": 0,
                "endMs": 60000,
                "confidence": 0.6,
            },
        ],
    }
    if reviewed:
        payload["review"] = {
            "status": "approved",
            "model": "qwen3.7-plus",
            "reviewedAt": "2026-08-01T01:30:00Z",
        }
    projection = SourceMemoryProjection.model_validate(payload)
    (directory / "projection.json").write_text(
        json.dumps(
            projection.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_clip_budget_derives_from_transport_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        source_memory.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 4 * 1024 * 1024,
    )
    budget = source_memory._clip_size_budget_bytes()
    assert budget == int(4 * 1024 * 1024 * 3 / 4) - 64 * 1024
    # A generous transport limit is capped at the conservative default.
    monkeypatch.setattr(
        source_memory.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 64 * 1024 * 1024,
    )
    assert (
        source_memory._clip_size_budget_bytes()
        == CLIP_SIZE_BUDGET_CAP_BYTES - 64 * 1024
    )
    # Limits too small for any workable clip are a configuration error
    # instead of a budget that transport would later refuse.
    monkeypatch.setattr(
        source_memory.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 100 * 1024,
    )
    with pytest.raises(ValidationError):
        source_memory._clip_size_budget_bytes()


def test_index_transcript_reuses_available_empty_asr(
    tmp_path,
    monkeypatch,
) -> None:
    # Available-but-empty ASR coverage (silent source) must be reused,
    # not re-billed; missing coverage must allow transcription.
    service = _service(tmp_path)
    job = source_memory.SourceMemoryBuildJob(
        project_id="project-1",
        task_id="task-1",
        authorization_id=None,
        index_id="intel-1",
        asset_id="asset-1",
        asset_version_id="version-1",
        source_checksum="checksum-1",
        duration_ms=25 * 60 * 1000,
        local_path=str(tmp_path / "video.mp4"),
    )

    def fake_service(coverage_mode: str):
        index = SimpleNamespace(
            coverage={"asr": SimpleNamespace(mode=coverage_mode)},
            transcript=[],
        )
        return SimpleNamespace(load=lambda *args: index)

    import services.source_analysis as source_analysis_module

    monkeypatch.setattr(
        source_analysis_module,
        "source_analysis_service",
        lambda _services: fake_service("available"),
    )
    available, transcript = asyncio.run(service._index_transcript(job))
    assert available is True
    assert transcript == []

    monkeypatch.setattr(
        source_analysis_module,
        "source_analysis_service",
        lambda _services: fake_service("unavailable"),
    )
    available, transcript = asyncio.run(service._index_transcript(job))
    assert available is False


class _RecordingExecutions:
    def __init__(self, task) -> None:
        self.task = task
        self.attempts: list[dict] = []
        self.transitions: list[dict] = []

    def get_task(self, _project_id, _task_id):
        return self.task

    def list_tasks(self, _project_id):
        return [self.task]

    def list_attempts(self, _project_id, _task_id):
        return [SimpleNamespace(attempt_id="attempt-1")]

    def append_attempt(self, _project_id, _task_id, **kwargs):
        self.attempts.append(kwargs)
        if kwargs["status"].name == "FAILED":
            self.task = SimpleNamespace(
                **{**self.task.__dict__, "status": _task_status("FAILED")},
            )

    def transition_task(self, _project_id, _task_id, **kwargs):
        self.transitions.append(kwargs)
        self.task = SimpleNamespace(
            **{**self.task.__dict__, "status": kwargs["status"]},
        )
        return self.task


def _task_status(name: str):
    from domain.enums import TaskStatus

    return TaskStatus[name]


def _running_task(tmp_path: Path) -> SimpleNamespace:
    from domain.enums import TaskKind

    return SimpleNamespace(
        project_id="project-1",
        task_id="task-1",
        kind=TaskKind.SOURCE_MEMORY_BUILD,
        status=_task_status("RUNNING"),
        last_attempt_seq=1,
        metadata={
            "analysisVersionId": "intel-1",
            "localPath": str(tmp_path / "video.mp4"),
            "sourceChecksum": "checksum-1",
            "assetVersionId": "version-1",
            "targetRef": "asset:asset-1",
            "durationMs": 25 * 60 * 1000,
            "authorizationId": "auth-1",
        },
    )


def test_recover_fail_closes_without_durable_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    task = _running_task(tmp_path)
    executions = _RecordingExecutions(task)
    service.executions = executions
    monkeypatch.setattr(
        service.services.projects,
        "list",
        lambda: [SimpleNamespace(project_id="project-1")],
        raising=False,
    )
    spawned: list = []
    monkeypatch.setattr(service, "_spawn", spawned.append)

    service.recover_interrupted()

    # Attempt closed as FAILED, but no automatic re-queue/spawn: a
    # rebuild without artifacts requires a fresh authorization.
    assert executions.attempts[-1]["status"].name == "FAILED"
    assert not executions.transitions
    assert not spawned


def test_recover_requeues_when_artifacts_are_durable(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    _write_fixture_memory(project_root, "intel-1")
    task = _running_task(tmp_path)
    executions = _RecordingExecutions(task)
    service.executions = executions
    monkeypatch.setattr(
        service.services.projects,
        "list",
        lambda: [SimpleNamespace(project_id="project-1")],
        raising=False,
    )
    spawned: list = []
    monkeypatch.setattr(service, "_spawn", spawned.append)

    service.recover_interrupted()

    assert executions.transitions[-1]["status"].name == "QUEUED"
    assert len(spawned) == 1


def test_execute_converges_on_existing_artifacts(tmp_path) -> None:
    # A QUEUED task whose artifacts are already durable must succeed
    # without touching the media pipeline (no replayed billed calls).
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    _write_fixture_memory(project_root, "intel-1")
    task = SimpleNamespace(
        project_id="project-1",
        task_id="task-1",
        status=_task_status("QUEUED"),
        last_attempt_seq=2,
    )
    executions = _RecordingExecutions(task)
    service.executions = executions
    job = source_memory.SourceMemoryBuildJob(
        project_id="project-1",
        task_id="task-1",
        authorization_id="auth-1",
        index_id="intel-1",
        asset_id="asset-1",
        asset_version_id="version-1",
        source_checksum="checksum-1",
        duration_ms=25 * 60 * 1000,
        local_path=str(tmp_path / "missing.mp4"),
    )
    asyncio.run(service._execute(job))
    statuses = [item["status"].name for item in executions.attempts]
    assert statuses == ["RUNNING", "SUCCEEDED"]
    assert executions.attempts[-1]["output"]["converged"] is True


def test_merge_projection_semantics_folds_drafts(tmp_path) -> None:
    project_root = tmp_path / "projects" / "project-1"
    directory = _write_fixture_memory(project_root, "intel-1")
    _write_fixture_projection(directory)
    index = _index(memory_ref=_memory_ref())
    before = len(index.semantic_entries)

    source_memory.merge_projection_semantics(project_root, index)

    added = index.semantic_entries[before:]
    assert [entry.id for entry in added] == ["sem-mem-summary", "sem-mem-000"]
    assert all(
        entry.model_run_id == source_memory.SOURCE_MEMORY_RUN_ID
        for entry in added
    )
    assert any(
        run.id == source_memory.SOURCE_MEMORY_RUN_ID
        for run in index.model_runs
    )
    # Idempotent on repeated loads.
    source_memory.merge_projection_semantics(project_root, index)
    assert len(index.semantic_entries) == before + 2


def test_merge_projection_semantics_requires_matching_checksum(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects" / "project-1"
    directory = _write_fixture_memory(project_root, "intel-1")
    _write_fixture_projection(directory)
    index = _index(checksum="checksum-other", memory_ref=_memory_ref())
    before = len(index.semantic_entries)
    source_memory.merge_projection_semantics(project_root, index)
    assert len(index.semantic_entries) == before


def test_merge_projection_semantics_noop_without_memory_ref(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects" / "project-1"
    index = _index()
    source_memory.merge_projection_semantics(project_root, index)
    assert all(
        entry.model_run_id != source_memory.SOURCE_MEMORY_RUN_ID
        for entry in index.semantic_entries
    )


def test_merge_projection_requires_approved_review(tmp_path) -> None:
    # Fail-close: unreviewed drafts never reach the index surfaces.
    project_root = tmp_path / "projects" / "project-1"
    directory = _write_fixture_memory(project_root, "intel-1")
    _write_fixture_projection(directory, reviewed=False)
    index = _index(memory_ref=_memory_ref())
    before = len(index.semantic_entries)
    summary_before = index.summary
    source_memory.merge_projection_semantics(project_root, index)
    assert len(index.semantic_entries) == before
    assert index.summary == summary_before


def test_merge_projection_appends_reviewed_summary(tmp_path) -> None:
    project_root = tmp_path / "projects" / "project-1"
    directory = _write_fixture_memory(project_root, "intel-1")
    _write_fixture_projection(directory)
    index = _index(memory_ref=_memory_ref())
    source_memory.merge_projection_semantics(project_root, index)
    assert "[长素材记忆摘要 · 已审校]" in index.summary
    assert "memory digest of the whole video" in index.summary
    # Idempotent: the marker is appended once even across repeat loads.
    source_memory.merge_projection_semantics(project_root, index)
    assert index.summary.count("[长素材记忆摘要 · 已审校]") == 1


def test_review_projection_approves_or_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    draft = SourceMemoryProjection(
        indexId="intel-1",
        summary="draft digest",
        semanticEntries=[
            {
                "text": "Super event one",
                "tags": ["memory"],
                "startMs": 0,
                "endMs": 60000,
                "confidence": 0.6,
            },
        ],
    )

    async def good_chat(_content, **_kwargs):
        return json.dumps(
            {
                "summary": "reviewed digest",
                "semanticEntries": [
                    {
                        "entryId": "entry-0",
                        "text": "Super event one (reviewed)",
                        "tags": ["memory"],
                        "startMs": 0,
                        "endMs": 60000,
                        "confidence": 0.7,
                    },
                ],
            },
        )

    monkeypatch.setattr(
        source_memory.vlm_model,
        "chat_completion",
        good_chat,
    )
    monkeypatch.setattr(
        source_memory.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )
    reviewed = asyncio.run(service._review_projection(draft))
    assert reviewed.review is not None
    assert reviewed.review.status == "approved"
    assert reviewed.summary == "reviewed digest"
    assert reviewed.semantic_entries[0].start_ms == 0
    assert reviewed.semantic_entries[0].end_ms == 60000

    async def bad_chat(_content, **_kwargs):
        raise RuntimeError("vlm unavailable")

    monkeypatch.setattr(
        source_memory.vlm_model,
        "chat_completion",
        bad_chat,
    )
    fallback = asyncio.run(service._review_projection(draft))
    assert fallback.review is None
    assert fallback.summary == "draft digest"


def test_review_projection_rejects_tampered_windows_and_new_entries(
    tmp_path,
    monkeypatch,
) -> None:
    """A hallucinating reviewer must never earn the approved stamp.

    The reviewer may only edit text/tags/confidence or drop entries;
    moved time windows or invented entries fail the review closed and
    the drafts stay unreviewed (never merged into the index surfaces).
    """

    service = _service(tmp_path)
    draft = SourceMemoryProjection(
        indexId="intel-1",
        summary="draft digest",
        semanticEntries=[
            {
                "text": "Super event one",
                "tags": ["memory"],
                "startMs": 0,
                "endMs": 60000,
                "confidence": 0.6,
            },
            {
                "text": "Super event two",
                "tags": ["memory"],
                "startMs": 60000,
                "endMs": 120000,
                "confidence": 0.6,
            },
        ],
    )
    monkeypatch.setattr(
        source_memory.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )

    async def moved_window_chat(_content, **_kwargs):
        return json.dumps(
            {
                "summary": "tampered digest",
                "semanticEntries": [
                    {
                        "entryId": "entry-0",
                        "text": "Super event one",
                        "tags": ["memory"],
                        "startMs": 5000,
                        "endMs": 65000,
                        "confidence": 0.9,
                    },
                ],
            },
        )

    monkeypatch.setattr(
        source_memory.vlm_model,
        "chat_completion",
        moved_window_chat,
    )
    tampered = asyncio.run(service._review_projection(draft))
    assert tampered.review is None
    assert tampered.summary == "draft digest"

    async def invented_entry_chat(_content, **_kwargs):
        return json.dumps(
            {
                "summary": "tampered digest",
                "semanticEntries": [
                    {
                        "entryId": "entry-0",
                        "text": "Super event one",
                        "tags": ["memory"],
                        "startMs": 0,
                        "endMs": 60000,
                        "confidence": 0.6,
                    },
                    {
                        "entryId": "entry-999",
                        "text": "Invented event",
                        "tags": ["memory"],
                        "startMs": 120000,
                        "endMs": 180000,
                        "confidence": 0.9,
                    },
                ],
            },
        )

    monkeypatch.setattr(
        source_memory.vlm_model,
        "chat_completion",
        invented_entry_chat,
    )
    invented = asyncio.run(service._review_projection(draft))
    assert invented.review is None

    async def dropping_chat(_content, **_kwargs):
        return json.dumps(
            {
                "summary": "clean digest",
                "semanticEntries": [
                    {
                        "entryId": "entry-1",
                        "text": "Super event two (kept)",
                        "tags": ["memory"],
                        "startMs": 60000,
                        "endMs": 120000,
                        "confidence": 0.8,
                    },
                ],
            },
        )

    monkeypatch.setattr(
        source_memory.vlm_model,
        "chat_completion",
        dropping_chat,
    )
    kept = asyncio.run(service._review_projection(draft))
    assert kept.review is not None
    assert kept.review.status == "approved"
    assert len(kept.semantic_entries) == 1
    assert kept.semantic_entries[0].start_ms == 60000
    assert kept.semantic_entries[0].end_ms == 120000


# ── retrieval methodology guidance & enumerate tuning ───────────────────────


def test_memory_guidance_carries_query_construction_protocol() -> None:
    guidance = source_memory._MEMORY_GUIDANCE_AVAILABLE
    # Upstream SKILL.md retrieval-quality rules must reach the agent.
    assert "陈述句" in guidance
    assert "minCosine" in guidance
    assert "scope=project" in guidance
    assert "enumerate" in guidance
    assert "top-k" in guidance


def test_query_memory_passes_enumerate_tuning(tmp_path, monkeypatch) -> None:
    service = _query_service(tmp_path, monkeypatch)
    captured: dict = {}
    original = source_memory.MemoryToolkit.enumerate_events

    def spy(self, query, min_cosine=0.5, max_results=120, **kwargs):
        captured["min_cosine"] = min_cosine
        captured["max_results"] = max_results
        return original(
            self,
            query,
            min_cosine=min_cosine,
            max_results=max_results,
            **kwargs,
        )

    monkeypatch.setattr(source_memory.MemoryToolkit, "enumerate_events", spy)
    _run_query(
        service,
        query_type="enumerate",
        query="teamfight",
        min_cosine=0.2,
        max_results=7,
    )
    assert captured == {"min_cosine": 0.2, "max_results": 7}
    # Out-of-range values clamp instead of erroring.
    _run_query(
        service,
        query_type="enumerate",
        query="teamfight",
        min_cosine=5.0,
        max_results=9999,
    )
    assert captured == {"min_cosine": 1.0, "max_results": 300}


# ── chunk planning & stage checkpoints ──────────────────────────────────────


def test_chunk_plan_splits_and_folds_short_tail() -> None:
    assert source_memory._chunk_plan(1800.0) == [(0.0, 1800.0)]
    assert source_memory._chunk_plan(7300.0) == [
        (0.0, 3600.0),
        (3600.0, 7200.0),
        (7200.0, 7300.0),
    ]
    # A tail shorter than MIN_SCENE_SEC folds into the previous chunk.
    assert source_memory._chunk_plan(7210.0) == [
        (0.0, 3600.0),
        (3600.0, 7210.0),
    ]


def test_checkpoint_roundtrip_is_checksum_gated(tmp_path) -> None:
    path = tmp_path / "ckpt.json"
    source_memory._write_checkpoint(path, "checksum-1", {"a": 1})
    assert source_memory._load_checkpoint(path, "checksum-1") == {"a": 1}
    # A different source invalidates the checkpoint silently.
    assert source_memory._load_checkpoint(path, "checksum-2") is None
    path.write_text("not json", encoding="utf-8")
    assert source_memory._load_checkpoint(path, "checksum-1") is None


def test_has_build_checkpoint_matches_segments_or_subgraphs(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects" / "project-1"
    assert not source_memory.has_build_checkpoint(
        project_root,
        "intel-1",
        "checksum-1",
    )
    directory = source_memory.build_dir(project_root, "intel-1")
    source_memory._write_checkpoint(
        directory
        / source_memory.SUBGRAPH_CHECKPOINT_DIRNAME
        / ("macro_0000.json"),
        "checksum-1",
        {"micro_events": []},
    )
    assert source_memory.has_build_checkpoint(
        project_root,
        "intel-1",
        "checksum-1",
    )
    # Stale checksum means a different source: no resume.
    assert not source_memory.has_build_checkpoint(
        project_root,
        "intel-1",
        "checksum-2",
    )


def test_extract_subgraph_resumes_from_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    from vendor.media_toolkit.video_memory.schema import MacroEvent

    service = _service(tmp_path)
    ckpt_dir = tmp_path / "subgraphs"
    payload = {
        "micro_events": [
            {
                "event_id": "ev_1",
                "event_type": "action",
                "time_range": [1.0, 2.0],
                "subject": "cat",
                "object": "",
                "action": "jumps",
                "description": "cat jumps",
            },
        ],
        "entities": [],
        "on_screen_texts": [],
        "edges": [],
    }
    source_memory._write_checkpoint(
        ckpt_dir / "macro_0000.json",
        "checksum-1",
        payload,
    )

    def must_not_clip(*_args, **_kwargs):
        raise AssertionError("checkpointed macro must not re-clip")

    monkeypatch.setattr(
        source_memory,
        "_clip_segment_for_transport_sync",
        must_not_clip,
    )
    macro = MacroEvent(
        macro_id="macro_0000",
        label="scene",
        time_range=[10.0, 40.0],
    )
    asyncio.run(
        service._extract_subgraph(
            macro,
            tmp_path / "missing.mp4",
            tmp_path,
            asyncio.Semaphore(1),
            ckpt_dir,
            "checksum-1",
        ),
    )
    assert macro.subgraph is not None
    # Relative checkpoint times shift onto the macro window on resume.
    assert macro.subgraph.micro_events[0].time_range == [11.0, 12.0]


def test_extract_subgraph_persists_checkpoint_before_apply(
    tmp_path,
    monkeypatch,
) -> None:
    from vendor.media_toolkit.video_memory.schema import MacroEvent

    service = _service(tmp_path)
    ckpt_dir = tmp_path / "subgraphs"

    def fake_clip(_local, out_path, _start, _end):
        out_path.write_bytes(b"clip")
        return out_path

    async def fake_chat(_content, **_kwargs):
        return json.dumps(
            {
                "micro_events": [
                    {
                        "event_id": "ev_1",
                        "event_type": "action",
                        "time_range": [1.0, 2.0],
                        "subject": "cat",
                        "object": "",
                        "action": "jumps",
                        "description": "cat jumps",
                    },
                ],
                "entities": [],
                "on_screen_texts": [],
                "edges": [],
            },
        )

    monkeypatch.setattr(
        source_memory,
        "_clip_segment_for_transport_sync",
        fake_clip,
    )
    monkeypatch.setattr(source_memory.vlm_model, "chat_completion", fake_chat)
    macro = MacroEvent(
        macro_id="macro_0000",
        label="scene",
        time_range=[10.0, 40.0],
    )
    asyncio.run(
        service._extract_subgraph(
            macro,
            tmp_path / "video.mp4",
            tmp_path,
            asyncio.Semaphore(1),
            ckpt_dir,
            "checksum-1",
        ),
    )
    assert macro.subgraph.micro_events[0].time_range == [11.0, 12.0]
    # Checkpoint keeps the raw RELATIVE payload (written pre-apply).
    stored = source_memory._load_checkpoint(
        ckpt_dir / "macro_0000.json",
        "checksum-1",
    )
    assert stored["micro_events"][0]["time_range"] == [1.0, 2.0]


def test_recover_requeues_when_checkpoints_exist(
    tmp_path,
    monkeypatch,
) -> None:
    # Interrupted mid-P2 with durable per-macro checkpoints: the resumed
    # attempt only spends on the remaining macros, so it re-queues.
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    directory = source_memory.build_dir(project_root, "intel-1")
    source_memory._write_checkpoint(
        directory
        / source_memory.SUBGRAPH_CHECKPOINT_DIRNAME
        / ("macro_0000.json"),
        "checksum-1",
        {"micro_events": []},
    )
    task = _running_task(tmp_path)
    executions = _RecordingExecutions(task)
    service.executions = executions
    monkeypatch.setattr(
        service.services.projects,
        "list",
        lambda: [SimpleNamespace(project_id="project-1")],
        raising=False,
    )
    spawned: list = []
    monkeypatch.setattr(service, "_spawn", spawned.append)

    service.recover_interrupted()

    assert executions.transitions[-1]["status"].name == "QUEUED"
    assert len(spawned) == 1


# ── transport-aware clip encoding ────────────────────────────────────────────


def test_clip_transport_moved_to_source_observation() -> None:
    # The transport-aware clip encode dispatch moved to
    # services.media.source_observation (covered by
    # tests/media/test_source_observation.py); source_memory keeps
    # patchable private aliases for its build call sites.
    from services.media import source_observation

    assert (
        source_memory._clip_segment_for_transport_sync
        is source_observation.clip_segment_for_transport_sync
    )


# ── project-scope merged memory ──────────────────────────────────────────────


def _merged_service(tmp_path, monkeypatch) -> SourceMemoryService:
    project_root = tmp_path / "projects" / "project-1"
    project_root.mkdir(parents=True, exist_ok=True)
    _write_fixture_memory(project_root, "intel-1")
    _write_fixture_memory(project_root, "intel-2")
    project = SimpleNamespace(
        sources=SimpleNamespace(
            sources=SimpleNamespace(
                items={
                    "src-1": SimpleNamespace(
                        logical_asset_id="asset-1",
                        current_intelligence_version_id="iv-1",
                    ),
                    "src-2": SimpleNamespace(
                        logical_asset_id="asset-2",
                        current_intelligence_version_id="iv-2",
                    ),
                },
            ),
        ),
        assets=SimpleNamespace(
            intelligence_versions_by_id={
                "iv-1": SimpleNamespace(
                    intelligence_version_id="intel-1",
                    source_checksum="checksum-1",
                ),
                "iv-2": SimpleNamespace(
                    intelligence_version_id="intel-2",
                    source_checksum="checksum-1",
                ),
            },
        ),
    )
    services = SimpleNamespace(
        root=tmp_path,
        projects=SimpleNamespace(
            project_root=lambda project_id: tmp_path / "projects" / project_id,
            read=lambda project_id: SimpleNamespace(project=project),
        ),
    )
    service = SourceMemoryService(services)

    async def no_embedding(query_text: str):
        del query_text
        return None

    monkeypatch.setattr(service, "_embed_query", no_embedding)
    return service


def test_project_scope_merges_all_built_memories(
    tmp_path,
    monkeypatch,
) -> None:
    service = _merged_service(tmp_path, monkeypatch)
    result = _run_query(
        service,
        query_type="search_asr",
        query="团战 零换五",
        scope="project",
    )
    assert result["scope"] == "project"
    assert result["sources"] == [
        {"prefix": "s1", "assetId": "asset-1"},
        {"prefix": "s2", "assetId": "asset-2"},
    ]
    hit_macros = {item["macro_id"] for item in result["result"]}
    assert {"s1_macro_0001", "s2_macro_0001"} <= hit_macros
    windows = {
        (item["macroId"], item.get("assetId"))
        for item in result["hitWindowsMs"]
    }
    assert ("s1_macro_0001", "asset-1") in windows
    assert ("s2_macro_0001", "asset-2") in windows

    # Prefixed super/subgraph drilldowns keep working across sources.
    filtered = _run_query(
        service,
        query_type="macro_events",
        macro_id="s2_super_00",
        scope="project",
    )
    assert {item["macro_id"] for item in filtered["result"]} == {
        "s2_macro_0000",
        "s2_macro_0001",
    }
    subgraph = _run_query(
        service,
        query_type="subgraph",
        macro_id="s1_macro_0000",
        scope="project",
    )
    assert subgraph["result"]["macro_id"] == "s1_macro_0000"


def test_project_scope_rejects_by_time_and_requires_memories(
    tmp_path,
    monkeypatch,
) -> None:
    service = _merged_service(tmp_path, monkeypatch)
    with pytest.raises(ValidationError):
        _run_query(
            service,
            query_type="by_time",
            start_ms=0,
            end_ms=1000,
            scope="project",
        )
    with pytest.raises(ValidationError):
        _run_query(service, query_type="summary", scope="bogus")

    # No built memories in the project: explicit validation error.
    project_root = tmp_path / "projects" / "project-1"
    import shutil as _shutil

    _shutil.rmtree(memory_dir(project_root, "intel-1"))
    _shutil.rmtree(memory_dir(project_root, "intel-2"))
    with pytest.raises(ValidationError):
        _run_query(service, query_type="summary", scope="project")


def test_project_scope_degrades_to_bm25_on_mixed_embeddings(
    tmp_path,
    monkeypatch,
) -> None:
    # One source loses its npz: the merged index degrades to BM25-only
    # instead of failing or silently dropping that source's nodes.
    service = _merged_service(tmp_path, monkeypatch)
    project_root = tmp_path / "projects" / "project-1"
    (memory_dir(project_root, "intel-2") / "embeddings.npz").unlink()
    result = _run_query(
        service,
        query_type="search_asr",
        query="团战 零换五",
        scope="project",
    )
    assert {"s1_macro_0001", "s2_macro_0001"} <= {
        item["macro_id"] for item in result["result"]
    }


def test_list_built_memories_skips_sources_without_memory(tmp_path) -> None:
    project_root = tmp_path / "projects" / "project-1"
    project_root.mkdir(parents=True, exist_ok=True)
    _write_fixture_memory(project_root, "intel-1")
    project = SimpleNamespace(
        sources=SimpleNamespace(
            sources=SimpleNamespace(
                items={
                    "src-1": SimpleNamespace(
                        logical_asset_id="asset-1",
                        current_intelligence_version_id="iv-1",
                    ),
                    "src-2": SimpleNamespace(
                        logical_asset_id="asset-2",
                        current_intelligence_version_id=None,
                    ),
                },
            ),
        ),
        assets=SimpleNamespace(
            intelligence_versions_by_id={
                "iv-1": SimpleNamespace(
                    intelligence_version_id="intel-1",
                    source_checksum="checksum-1",
                ),
            },
        ),
    )
    assert source_memory.list_built_memories(project_root, project) == [
        ("asset-1", "intel-1", "checksum-1"),
    ]


def test_execute_runs_chunked_pipeline_with_segment_checkpoints(
    tmp_path,
    monkeypatch,
) -> None:
    # 7300s source → 3 detection chunks; chunk 1 is pre-checkpointed and
    # must not be re-detected. Macro ids stay globally sequential and
    # the build directory is removed once artifacts are durable.
    from vendor.media_toolkit.video_memory.schema import (
        MicroEvent as VendorMicroEvent,
        Subgraph as VendorSubgraph,
        SuperEvent,
        VideoRoot,
    )

    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    local_path = tmp_path / "video.mp4"
    local_path.write_bytes(b"video")
    task = SimpleNamespace(
        project_id="project-1",
        task_id="task-1",
        status=_task_status("QUEUED"),
        last_attempt_seq=0,
    )
    service.executions = _RecordingExecutions(task)
    job = source_memory.SourceMemoryBuildJob(
        project_id="project-1",
        task_id="task-1",
        authorization_id=None,
        index_id="intel-1",
        asset_id="asset-1",
        asset_version_id="version-1",
        source_checksum="checksum-1",
        duration_ms=7_300_000,
        local_path=str(local_path),
    )
    ckpt_root = source_memory.build_dir(project_root, "intel-1")
    source_memory._write_checkpoint(
        ckpt_root / source_memory.SEGMENTS_CHECKPOINT_FILENAME,
        "checksum-1",
        {"0-3600": [[0.0, 1800.0], [1800.0, 3600.0]]},
    )

    detected: list[tuple[float, float]] = []

    def fake_detect(_path, start_sec, end_sec):
        detected.append((start_sec, end_sec))
        return [(start_sec, end_sec)]

    async def fake_transcript(_job):
        return True, []

    async def fake_extract(macro, *_args):
        macro.subgraph = VendorSubgraph(
            macro_id=macro.macro_id,
            micro_events=[
                VendorMicroEvent(
                    event_id=f"{macro.macro_id}:ev",
                    event_type="action",
                    time_range=list(macro.time_range),
                    subject="cat",
                    object="",
                    action="walks",
                    description="stub event",
                    macro_id=macro.macro_id,
                ),
            ],
        )

    async def fake_aggregate(macros, _call_llm):
        root = VideoRoot(title="t", description="d")
        supers = [
            SuperEvent(
                super_id="super_00",
                label="all",
                sub_macro_ids=[m.macro_id for m in macros],
                time_range=[0.0, 7300.0],
            ),
        ]
        return root, supers, [], []

    async def fake_review(draft):
        return draft

    monkeypatch.setattr(source_memory, "_detect_segments_sync", fake_detect)
    monkeypatch.setattr(service, "_index_transcript", fake_transcript)
    monkeypatch.setattr(service, "_extract_subgraph", fake_extract)
    monkeypatch.setattr(source_memory, "aggregate_hierarchy", fake_aggregate)
    monkeypatch.setattr(service, "_review_projection", fake_review)
    monkeypatch.setattr(
        source_memory.model_config,
        "is_embedding_configured",
        lambda: False,
    )

    asyncio.run(service._execute(job))

    # Chunk 1 came from the checkpoint; only chunks 2 and 3 detected.
    assert detected == [(3600.0, 7200.0), (7200.0, 7300.0)]
    ref = load_memory_ref(project_root, "intel-1", "checksum-1")
    assert ref is not None
    assert ref.macro_count == 4  # 2 checkpointed + 2 detected
    graph = json.loads(
        (memory_dir(project_root, "intel-1") / "graph_memory.json").read_text(
            encoding="utf-8",
        ),
    )
    assert [m["macro_id"] for m in graph["macro_events"]] == [
        "macro_0000",
        "macro_0001",
        "macro_0002",
        "macro_0003",
    ]
    assert not ckpt_root.exists()


def test_ffmpeg_invocations_detach_stdin() -> None:
    # A background-job host delivers SIGTTIN to any child reading the
    # TTY: every ffmpeg subprocess must run with stdin detached or the
    # whole build silently stops (observed live: clips stuck in "TN").
    # The clip encoders live in source_observation; source_memory keeps
    # its own P1 frame-seek invocation.
    import inspect

    from services.media import source_observation

    for module, expected_runs in (
        (source_memory, 1),
        (source_observation, 2),
    ):
        source = inspect.getsource(module)
        runs = source.count("subprocess.run(")
        detached = source.count("stdin=subprocess.DEVNULL")
        assert runs == expected_runs
        assert detached == runs
