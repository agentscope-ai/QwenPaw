# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Source memory trigger/artifacts/query dispatch and projection tests."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vendored.test_video_memory_toolkit import (
    build_fixture_index,
    build_fixture_memory,
)

import services.source_analysis as source_analysis_module
from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from schemas.assets import SourceIntelligenceIndex, SourceMemoryRef
from services.media import source_memory, source_observation
from services.media.source_memory import (
    SourceMemoryProjection,
    SourceMemoryService,
    load_memory_ref,
    memory_dir,
)
from vendor.media_toolkit.video_memory.schema import (
    MacroEvent,
    MicroEvent,
    Subgraph,
    SuperEvent,
    VideoRoot,
)


def _index(
    *,
    duration_ms: int = 25 * 60 * 1000,
    media_kind: str = "video",
    checksum: str = "checksum-1",
    memory_ref: SourceMemoryRef | None = None,
) -> SourceIntelligenceIndex:
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
            **{k: {"mode": "unavailable"} for k in ("asr", "ocr", "audio")},
        },
        "media": {
            "mediaKind": media_kind,
            "mediaType": "video/mp4",
            "durationMs": duration_ms,
        },
        "summary": "fixture summary",
        "shots": [],
        "transcript": [],
        "words": [],
        "ocrSegments": [],
        "audioEvents": [],
        "entities": [],
        "semanticEntries": [],
        "createdAt": "2026-08-01T00:00:00Z",
    }
    index = SourceIntelligenceIndex.model_validate(payload)
    index.memory_ref = memory_ref
    return index


def _write_fixture_memory(project_root: Path, index_id: str) -> Path:
    directory = memory_dir(project_root, index_id)
    directory.mkdir(parents=True)
    memory = build_fixture_memory()
    embedding_index, _nodes, _ = build_fixture_index(memory)
    memory.save(str(directory / "graph_memory.json"))
    embedding_index.save(str(directory / "embeddings.npz"))
    (directory / "memory_meta.json").write_text(
        json.dumps(
            {
                "indexId": index_id,
                "sourceChecksum": "checksum-1",
                "builtAt": "2026-08-01T01:00:00Z",
                "macroCount": 2,
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


def test_should_build_gates_and_memory_ref_lifecycle(tmp_path) -> None:
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    assert service.should_build(_index(), project_root)
    assert not service.should_build(
        _index(duration_ms=10 * 60 * 1000),
        project_root,
    )
    # Already-built memory short-circuits the trigger.
    directory = _write_fixture_memory(project_root, "intel-1")
    assert not service.should_build(_index(), project_root)
    ref = load_memory_ref(project_root, "intel-1", "checksum-1")
    assert ref is not None
    assert ref.macro_count == 2
    # Checksum mismatch / missing graph invalidates the ref.
    assert load_memory_ref(project_root, "intel-1", "other-checksum") is None
    (directory / "graph_memory.json").unlink()
    assert load_memory_ref(project_root, "intel-1", "checksum-1") is None


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
    assert result["available"] is False
    with pytest.raises(ValidationError):
        _run_query(service, query_type="bogus")


@pytest.mark.parametrize(
    ("kwargs", "expect"),
    [
        pytest.param(
            {"query_type": "subgraph", "macro_id": "macro_0000"},
            lambda r: r["result"]["macro_id"] == "macro_0000"
            and r["hitWindowsMs"]
            == [{"macroId": "macro_0000", "startMs": 0, "endMs": 300_000}],
            id="subgraph",
        ),
        pytest.param(
            {"query_type": "search_nodes", "query": "teamfight dragon"},
            lambda r: r["result"]["results"][0]["node_id"]
            == "macro_0001:ev_101"
            and {"macroId": "macro_0001", "startMs": 300_000, "endMs": 620_000}
            in r["hitWindowsMs"],
            id="search_nodes",
        ),
        pytest.param(
            {"query_type": "by_time", "start_ms": 310_000, "end_ms": 400_000},
            lambda r: [i["macro_id"] for i in r["result"]] == ["macro_0001"],
            id="by_time",
        ),
    ],
)
def test_query_memory_dispatches_each_query_type(
    tmp_path,
    monkeypatch,
    kwargs,
    expect,
) -> None:
    service = _query_service(tmp_path, monkeypatch)
    assert expect(_run_query(service, **kwargs))


def test_query_memory_degrades_to_bm25_without_embeddings_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    # Degraded-retrieval ladder regression: with the .npz gone, search
    # must answer from a BM25 index rebuilt from the graph.
    service = _query_service(tmp_path, monkeypatch)
    directory = memory_dir(tmp_path / "projects" / "project-1", "intel-1")
    (directory / "embeddings.npz").unlink()
    nodes = _run_query(
        service,
        query_type="search_nodes",
        query="teamfight dragon",
    )
    assert nodes["result"]["results"][0]["node_id"] == "macro_0001:ev_101"
    asr = _run_query(service, query_type="search_asr", query="团战 零换五")
    assert asr["result"][0]["macro_id"] == "macro_0001"


def _memory_ref() -> SourceMemoryRef:
    return SourceMemoryRef(
        graphPath="runtime/source-intelligence/intel-1/memory/graph_memory.json",
        embeddingsPath="runtime/source-intelligence/intel-1/memory/embeddings.npz",
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
    (directory / "projection.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_job(
    tmp_path: Path,
    **overrides,
) -> source_memory.SourceMemoryBuildJob:
    kwargs = {
        "project_id": "project-1",
        "task_id": "task-1",
        "authorization_id": None,
        "index_id": "intel-1",
        "asset_id": "asset-1",
        "asset_version_id": "version-1",
        "source_checksum": "checksum-1",
        "duration_ms": 25 * 60 * 1000,
        "local_path": str(tmp_path / "video.mp4"),
    }
    kwargs.update(overrides)
    return source_memory.SourceMemoryBuildJob(**kwargs)


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
                **{**self.task.__dict__, "status": TaskStatus.FAILED},
            )

    def transition_task(self, _project_id, _task_id, **kwargs):
        self.transitions.append(kwargs)
        self.task = SimpleNamespace(
            **{**self.task.__dict__, "status": kwargs["status"]},
        )
        return self.task


def _running_task(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        project_id="project-1",
        task_id="task-1",
        kind=TaskKind.SOURCE_MEMORY_BUILD,
        status=TaskStatus.RUNNING,
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


@pytest.mark.parametrize(
    "durable",
    ["none", "checkpoint"],
)
def test_recover_requeues_only_with_durable_artifacts(
    tmp_path,
    monkeypatch,
    durable,
) -> None:
    # Without durable artifacts the attempt closes as FAILED (a rebuild
    # needs a fresh authorization); durable per-macro checkpoints let
    # the resumed attempt spend only on remaining macros, so it re-queues.
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    if durable == "checkpoint":
        directory = source_memory.build_dir(project_root, "intel-1")
        source_memory._write_checkpoint(
            directory
            / source_memory.SUBGRAPH_CHECKPOINT_DIRNAME
            / "macro_0000.json",
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

    if durable == "none":
        assert executions.attempts[-1]["status"].name == "FAILED"
        assert not spawned
    else:
        assert executions.transitions[-1]["status"].name == "QUEUED"
        assert len(spawned) == 1


def test_merge_projection_folds_reviewed_drafts_and_summary(
    tmp_path,
) -> None:
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
    assert "[长素材记忆摘要 · 已审校]" in index.summary
    # Idempotent on repeated loads.
    source_memory.merge_projection_semantics(project_root, index)
    assert len(index.semantic_entries) == before + 2


@pytest.mark.parametrize(
    "case",
    ["checksum_mismatch", "unreviewed"],
)
def test_merge_projection_skips_ineligible_drafts(tmp_path, case) -> None:
    # Fail-close: unreviewed or stale-checksum drafts never merge.
    project_root = tmp_path / "projects" / "project-1"
    directory = _write_fixture_memory(project_root, "intel-1")
    _write_fixture_projection(directory, reviewed=case != "unreviewed")
    if case == "checksum_mismatch":
        index = _index(checksum="checksum-other", memory_ref=_memory_ref())
    else:
        index = _index(memory_ref=_memory_ref())
    before = len(index.semantic_entries)
    summary_before = index.summary
    source_memory.merge_projection_semantics(project_root, index)
    assert len(index.semantic_entries) == before
    assert index.summary == summary_before


_REVIEW_CASES: dict[str, tuple[str, list[tuple]] | None] = {
    "approved": (
        "reviewed digest",
        [("entry-0", "Super event one (reviewed)", 0, 60000, 0.7)],
    ),
    "vlm_error": None,
    "moved_window": (
        "tampered digest",
        [("entry-0", "Super event one", 5000, 65000, 0.9)],
    ),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_CASES))
def test_review_projection_approves_or_fails_closed(
    tmp_path,
    monkeypatch,
    case,
) -> None:
    # A hallucinating reviewer must never earn the approved stamp:
    # moved windows or invented entries fail closed, and a reviewer
    # transport failure falls back to the unreviewed draft.
    service = _service(tmp_path)
    spec = _REVIEW_CASES[case]
    response = None
    if spec is not None:
        response = {
            "summary": spec[0],
            "semanticEntries": [
                {
                    "entryId": e[0],
                    "text": e[1],
                    "tags": ["memory"],
                    "startMs": e[2],
                    "endMs": e[3],
                    "confidence": e[4],
                }
                for e in spec[1]
            ],
        }
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
    monkeypatch.setattr(
        source_memory.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )

    async def chat(_content, **_kwargs):
        if response is None:
            raise RuntimeError("vlm unavailable")
        return json.dumps(response)

    monkeypatch.setattr(source_memory.vlm_model, "chat_completion", chat)
    reviewed = asyncio.run(service._review_projection(draft))
    if case == "approved":
        assert reviewed.review is not None
        assert reviewed.review.status == "approved"
        assert reviewed.summary == "reviewed digest"
        assert reviewed.semantic_entries[0].start_ms == 0
    else:
        assert reviewed.review is None
        assert reviewed.summary == "draft digest"


def test_extract_subgraph_checkpoints_then_resumes_without_reclip(
    tmp_path,
    monkeypatch,
) -> None:
    # First extraction persists the raw RELATIVE payload before macro
    # offsets apply; a resumed macro answers from the checkpoint without
    # re-clipping (no replayed billed call). Stale checksums invalidate.
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
            },
        )

    monkeypatch.setattr(
        source_memory,
        "_clip_segment_for_transport_sync",
        fake_clip,
    )
    monkeypatch.setattr(source_memory.vlm_model, "chat_completion", fake_chat)

    def extract(macro: MacroEvent) -> None:
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

    def make_macro() -> MacroEvent:
        return MacroEvent(
            macro_id="macro_0000",
            label="scene",
            time_range=[10.0, 40.0],
        )

    macro = make_macro()
    extract(macro)
    assert macro.subgraph.micro_events[0].time_range == [11.0, 12.0]
    ckpt_path = ckpt_dir / "macro_0000.json"
    stored = source_memory._load_checkpoint(ckpt_path, "checksum-1")
    assert stored["micro_events"][0]["time_range"] == [1.0, 2.0]
    assert source_memory._load_checkpoint(ckpt_path, "checksum-2") is None

    def must_not_clip(*_args, **_kwargs):
        raise AssertionError("checkpointed macro must not re-clip")

    monkeypatch.setattr(
        source_memory,
        "_clip_segment_for_transport_sync",
        must_not_clip,
    )
    resumed = make_macro()
    extract(resumed)
    assert resumed.subgraph.micro_events[0].time_range == [11.0, 12.0]


def test_execute_runs_chunked_pipeline_with_segment_checkpoints(
    tmp_path,
    monkeypatch,
) -> None:
    # 7300s source → 3 detection chunks; chunk 1 is pre-checkpointed and
    # must not be re-detected. Macro ids stay globally sequential.
    service = _service(tmp_path)
    project_root = tmp_path / "projects" / "project-1"
    local_path = tmp_path / "video.mp4"
    local_path.write_bytes(b"video")
    task = SimpleNamespace(
        project_id="project-1",
        task_id="task-1",
        status=TaskStatus.QUEUED,
        last_attempt_seq=0,
    )
    service.executions = _RecordingExecutions(task)
    job = _build_job(
        tmp_path,
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
        macro.subgraph = Subgraph(
            macro_id=macro.macro_id,
            micro_events=[
                MicroEvent(
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

    assert detected == [(3600.0, 7200.0), (7200.0, 7300.0)]
    ref = load_memory_ref(project_root, "intel-1", "checksum-1")
    assert ref.macro_count == 4  # 2 checkpointed + 2 detected
    assert not ckpt_root.exists()


def test_ffmpeg_invocations_detach_stdin() -> None:
    # A background-job host delivers SIGTTIN to any child reading the
    # TTY: ffmpeg must run with stdin detached or the whole build
    # silently stops (observed live: clips stuck in "TN").
    for module, expected_runs in (
        (source_memory, 1),
        (source_observation, 2),
    ):
        source = inspect.getsource(module)
        runs = source.count("subprocess.run(")
        detached = source.count("stdin=subprocess.DEVNULL")
        assert runs == expected_runs
        assert detached == runs
