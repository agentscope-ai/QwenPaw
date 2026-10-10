# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Manual real-model acceptance for the long-source memory build.

Runs the full P1/P2/P3 + embedding pipeline against a real, trimmed
(~25 min) copy of the WT6 acceptance material and real Creator model
backends. Billed model calls are made; select explicitly:

    CREATOR_MEMORY_REAL_SOURCE=/path/to/video.mp4 \
        pytest tests/manual/test_source_memory_real.py -m manual_real

Requires configured VLM + embedding keys and ffmpeg/ffprobe resolvable.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.enums import TaskStatus
from models import config as model_config
from services.media import source_memory

pytestmark = pytest.mark.manual_real

TRIM_SECONDS = 25 * 60


def _real_source() -> Path | None:
    raw = os.environ.get("CREATOR_MEMORY_REAL_SOURCE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


@pytest.fixture(name="trimmed_source")
def fixture_trimmed_source(tmp_path: Path) -> Path:
    source = _real_source()
    if source is None:
        pytest.skip("CREATOR_MEMORY_REAL_SOURCE not set or missing")
    if not model_config.is_embedding_configured():
        pytest.skip("embedding model is not configured")
    ffmpeg = source_memory._require_ffmpeg()
    target = tmp_path / "trimmed-25min.mp4"
    subprocess.run(  # nosec B603
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-t",
            str(TRIM_SECONDS),
            "-i",
            str(source),
            "-c",
            "copy",
            str(target),
        ],
        check=True,
        timeout=1800,
    )
    return target


def test_real_build_produces_queryable_memory(
    trimmed_source: Path,
    tmp_path: Path,
) -> None:
    probe = subprocess.run(  # nosec B603
        [
            source_memory._require_ffmpeg().replace("ffmpeg", "ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(trimmed_source),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    duration_sec = float(json.loads(probe.stdout)["format"]["duration"])
    assert duration_sec > source_memory.MEMORY_BUILD_THRESHOLD_MS / 1000

    async def build() -> None:
        segments = await asyncio.to_thread(
            source_memory._detect_segments_sync,
            trimmed_source,
            duration_sec,
        )
        assert segments, "P1 segmentation must find scene boundaries"
        service = source_memory.SourceMemoryService(
            _FakeServices(tmp_path),
        )
        job = source_memory.SourceMemoryBuildJob(
            project_id="manual-project",
            task_id="manual-task",
            authorization_id=None,
            index_id="manual-intel",
            asset_id="manual-asset",
            asset_version_id="manual-version",
            source_checksum="manual-checksum",
            duration_ms=int(duration_sec * 1000),
            local_path=str(trimmed_source),
        )
        service.executions = _NullExecutions()
        await service._execute(job)

    asyncio.run(build())

    memory_root = source_memory.memory_dir(
        tmp_path / "projects" / "manual-project",
        "manual-intel",
    )
    graph = memory_root / source_memory.GRAPH_FILENAME
    embeddings = memory_root / source_memory.EMBEDDINGS_FILENAME
    assert graph.is_file() and embeddings.is_file()

    toolkit = source_memory._load_toolkit_sync(graph, embeddings)
    summary = toolkit.get_summary()
    assert summary.get("title")
    supers = toolkit.get_super_events()
    assert supers, "P3 aggregation must produce super events"
    hits = toolkit.search_nodes("scene transition", top_k=5)
    assert hits, "hybrid retrieval must return candidates"

    # The fixed 25-minute KPL trim stably segments into 8 macros; a
    # narrow band around that catches segmentation-quality regressions.
    macros = toolkit.memory.macro_events
    assert 7 <= len(macros) <= 9, f"unexpected macro count {len(macros)}"
    # Windows: ordered, non-overlapping, covering the trimmed duration.
    windows = [
        (float(macro.time_range[0]), float(macro.time_range[1]))
        for macro in macros
    ]
    assert windows == sorted(windows), "macro windows must be ordered"
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert next_start >= prev_end, "macro windows must not overlap"
        assert next_start - prev_end <= 2.0, "gap between macros too large"
    assert windows[0][0] <= 1.0, "coverage must start at the beginning"
    covered = windows[-1][1] - windows[0][0]
    assert (
        covered >= duration_sec * 0.98
    ), f"macros cover only {covered:.1f}s of {duration_sec:.1f}s"


class _FakeServices:
    def __init__(self, root: Path) -> None:
        self.root = root
        projects_root = root / "projects"
        projects_root.mkdir(parents=True, exist_ok=True)

        class _Projects:
            @staticmethod
            def project_root(project_id: str) -> Path:
                path = projects_root / project_id
                path.mkdir(parents=True, exist_ok=True)
                return path

        self.projects = _Projects()


class _NullExecutions:
    """Task bookkeeping stub: the manual run asserts artifacts only."""

    @staticmethod
    def get_task(_project_id: str, _task_id: str):
        return SimpleNamespace(
            status=TaskStatus.QUEUED,
            last_attempt_seq=0,
        )

    def __getattr__(self, _name: str):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


def test_real_coarse_to_fine_read_extracts_frames(
    trimmed_source: Path,
) -> None:
    """WT-A2: coarse small-budget full scan, then a large-budget narrow
    window on the real source (先粗看再细看), extraction only."""
    from services.media.source_video_reader import read_video_frames_sync

    coarse = read_video_frames_sync(
        trimmed_source,
        budget="small",
        max_frames=32,
    )
    assert len(coarse["frames"]) >= 16
    span = coarse["frames"][-1][0] - coarse["frames"][0][0]
    assert span >= coarse["duration"] * 0.9, "coarse scan must cover the file"
    fine = read_video_frames_sync(
        trimmed_source,
        budget="large",
        start_ms=60_000,
        end_ms=90_000,
        max_frames=16,
    )
    assert len(fine["frames"]) >= 8
    assert fine["target_h"] * fine["target_w"] > (
        coarse["target_h"] * coarse["target_w"]
    ), "large budget must render higher resolution than small"


def test_real_observe_clip_answers_with_timestamps(
    trimmed_source: Path,
    tmp_path: Path,
) -> None:
    """WT-A1 acceptance: a real VLM watches one 30s window of the real
    source and answers with timestamped evidence (回原片核验闭环)."""
    from services.media import source_observation

    if not model_config.get_vlm_api_key().strip():
        pytest.skip("VLM model is not configured")
    service = source_observation.SourceObservationService(
        _FakeServices(tmp_path),
    )
    job = source_observation.SourceObservationJob(
        project_id="manual-project",
        task_id="manual-observe",
        logical_asset_id="manual-asset",
        version_id="manual-version",
        local_path=str(trimmed_source),
        start_ms=60_000,
        end_ms=90_000,
        question=("描述这段画面里发生了什么，并给出关键动作发生的具体时刻。"),
    )
    answer = asyncio.run(service._observe(job, trimmed_source))
    print(f"manual observe answer:\n{answer}")
    assert len(answer) > 20
    # Timestamped evidence: at least one mm:ss-style stamp in the reply.
    assert re.search(
        r"\d{1,2}[:：]\d{2}",
        answer,
    ), "observation answer must carry timestamped evidence"
