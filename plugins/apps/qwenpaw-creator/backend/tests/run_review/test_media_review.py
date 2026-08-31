# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Async media review: admission, parsing, scheduling and the image loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
)
from services.run_review import admission
from services.run_review import media_review as media_module

pytestmark = pytest.mark.unit

_FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(_FFMPEG is None, reason="needs ffmpeg")

PROJECT_ID = "project-media-review"
SLOT_ID = "element:e1:storyboard"
VERSION_ID = "artifact-version-img-1"

VIDEO_CHECKS = (
    "devices type_fonts composition_safety "
    "motion_quality technical watch_once"
).split()
IMAGE_CHECKS = "devices type_fonts composition_safety craft".split()


def _findings(keys: list[str], fail_key: str | None = None, **extra) -> str:
    findings = []
    for key in keys:
        entry = {
            "check_key": key,
            "passed": key != fail_key,
            "severity": "major" if key == fail_key else "minor",
            "evidence_timestamp_ms": None,
            "suggestion": "",
        }
        if key == fail_key:
            entry |= extra
        findings.append(entry)
    return json.dumps({"findings": findings}, ensure_ascii=False)


def _video_fail() -> str:
    return _findings(
        VIDEO_CHECKS,
        "technical",
        evidence_timestamp_ms=1200,
        suggestion="移除中段黑帧",
    )


def _parse(text: str, *, kind: str, gate_block=None, stats=None):
    return media_module.parse_media_report(
        text,
        kind=kind,
        artifact_ref="artifact-version:v1",
        round_number=1,
        gate_block=gate_block,
        stats=stats,
    )


def test_parse_media_report_evidence_discipline() -> None:
    report = _parse(_video_fail(), kind="element_video")
    assert report.verdict == "revise"
    assert [i.check_key for i in report.failed_findings()] == ["technical"]
    # Fail-closed: findings without evidence discipline cannot stand.
    no_ts = _findings(VIDEO_CHECKS, "technical", suggestion="移除中段黑帧")
    assert _parse(no_ts, kind="element_video").verdict == "pass"
    no_hint = _findings(IMAGE_CHECKS, "craft")
    assert _parse(no_hint, kind="image").verdict == "pass"
    # Every rubric check must be present.
    payload = json.loads(_findings(IMAGE_CHECKS))
    payload["findings"] = payload["findings"][:2]
    with pytest.raises(ValueError):
        _parse(json.dumps(payload), kind="image")


def _admit(root: Path, version: str, owner: str = "owner-a"):
    return admission.admit_media_round(
        root,
        slot_id=SLOT_ID,
        version_id=version,
        owner=owner,
    )


def _finalize(root: Path, version: str, owner: str = "owner-a") -> bool:
    return admission.finalize_media_round(
        root,
        slot_id=SLOT_ID,
        version_id=version,
        owner=owner,
        counted=True,
    )


def test_media_admission_rounds_dedup_and_ownership(tmp_path: Path) -> None:
    root = tmp_path / "run-review"
    assert _admit(root, "v1") == 1
    # A live claim dedups replays and a foreign owner cannot finalize it.
    assert _admit(root, "v1") is None
    assert not _finalize(root, "v1", owner="owner-b")
    assert _finalize(root, "v1")
    assert _admit(root, "v1") is None, "reviewed versions never re-admit"
    assert _admit(root, "v2") == 2
    assert _finalize(root, "v2")
    # The slot's advisory budget is spent after MAX_MEDIA_REVIEW_ROUNDS.
    assert _admit(root, "v3") is None


def test_superseded_media_review_still_consumes_physical_budget(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run-review"
    assert _admit(root, "v-old") == 1
    assert _admit(root, "v-new") == 2
    assert (
        admission.finalize_media_round(
            root,
            slot_id=SLOT_ID,
            version_id="v-old",
            owner="owner-a",
            counted=False,
        )
        is False
    )
    assert _finalize(root, "v-new")
    assert _admit(root, "v-third") is None
    state = admission.read_json(
        root / "media" / f"state-{admission.safe_ref(SLOT_ID)}.json",
    )
    assert state["attempts_started"] == admission.MAX_MEDIA_REVIEW_ROUNDS


def test_repair_budget_is_atomic_idempotent_and_hard_capped(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run-review"
    target = "element:e1"
    for index in range(1, admission.MAX_REPAIR_ATTEMPTS + 1):
        assert admission.admit_repair_attempts(
            root,
            target_refs=[target],
            attempt_id=f"repair-{index}",
        ) == {target: index}
    # Replaying an admitted action is free and returns its original number.
    assert admission.admit_repair_attempts(
        root,
        target_refs=[target],
        attempt_id="repair-2",
    ) == {target: 2}
    assert (
        admission.admit_repair_attempts(
            root,
            target_refs=[target],
            attempt_id="repair-4",
        )
        is None
    )
    # Multi-target admission is all-or-nothing when one target is spent.
    assert (
        admission.admit_repair_attempts(
            root,
            target_refs=[target, "element:e2"],
            attempt_id="repair-multi",
        )
        is None
    )
    state = admission.read_json(root / "repair-budget" / "state.json")
    assert "element:e2" not in state["targets"]


def test_legacy_media_history_migrates_to_physical_cap(tmp_path: Path) -> None:
    root = tmp_path / "run-review"
    state_path = root / "media" / f"state-{admission.safe_ref(SLOT_ID)}.json"
    admission.write_json(
        state_path,
        {
            "slot_id": SLOT_ID,
            "rounds_completed": 0,
            "reviewed_version_ids": ["legacy-1", "legacy-2"],
            "claim": None,
        },
    )
    assert _admit(root, "after-upgrade") is None


def _published(relative_uri: str) -> dict:
    return {
        "commandType": "GENERATE_STORYBOARD_IMAGE",
        "targetRef": "element:e1",
        "transactionId": "txn-img-1",
        "indexedFile": {"relative_uri": relative_uri},
        "artifactVersion": {
            "version_id": VERSION_ID,
            "slot_id": SLOT_ID,
            "name": "分镜图 1",
        },
    }


def _schedule(published: dict) -> None:
    media_module.schedule_media_review(
        SimpleNamespace(),
        project_id=PROJECT_ID,
        published_result=published,
    )


def test_schedule_respects_switch_and_filters(monkeypatch) -> None:
    monkeypatch.delenv("CREATOR_MEDIA_REVIEW_ENABLED", raising=False)
    started: list[str] = []

    async def fake_loop(services, *, project_id, published, kind):
        started.append(kind)

    monkeypatch.setattr(media_module, "run_media_review_loop", fake_loop)

    async def _run() -> None:
        _schedule(_published("assets/artifacts/a.png"))
        assert not media_module._ACTIVE_REVIEW_TASKS, "off means no task"
        monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
        skipped = _published("assets/artifacts/a.png")
        skipped["commandType"] = "COMPOSE_FINAL_VIDEO"
        _schedule(skipped)
        _schedule(_published("assets/artifacts/a.png"))
        # In-flight tasks stay strongly referenced until they settle.
        assert len(media_module._ACTIVE_REVIEW_TASKS) == 1
        assert media_module.active_media_review_slots(PROJECT_ID) == {
            SLOT_ID,
        }
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not media_module._ACTIVE_REVIEW_TASKS
        assert not media_module.active_media_review_slots(PROJECT_ID)

    asyncio.run(_run())
    assert started == ["image"]


def test_schedule_review_fence_is_reference_counted(monkeypatch) -> None:
    """One completed review must not release a sibling's scheduler fence."""

    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
    releases = [asyncio.Event(), asyncio.Event()]
    started = 0

    async def fake_loop(services, *, project_id, published, kind):
        nonlocal started
        mine = started
        started += 1
        await releases[mine].wait()

    monkeypatch.setattr(media_module, "run_media_review_loop", fake_loop)

    async def _run() -> None:
        first = _published("assets/artifacts/a.png")
        second = _published("assets/artifacts/b.png")
        second["artifactVersion"]["version_id"] = "artifact-version-img-2"
        _schedule(first)
        _schedule(second)
        assert media_module.active_media_review_slots(PROJECT_ID) == {
            SLOT_ID,
        }
        await asyncio.sleep(0)
        assert started == 2

        releases[0].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert media_module.active_media_review_slots(PROJECT_ID) == {
            SLOT_ID,
        }

        releases[1].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not media_module.active_media_review_slots(PROJECT_ID)

    asyncio.run(_run())


def test_prepublication_reservation_closes_commit_listener_race(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
    release = asyncio.Event()

    async def fake_loop(services, *, project_id, published, kind):
        await release.wait()

    monkeypatch.setattr(media_module, "run_media_review_loop", fake_loop)

    async def _run() -> None:
        published = _published("assets/artifacts/precommit.png")
        token = media_module.reserve_media_review(
            SimpleNamespace(),
            project_id=PROJECT_ID,
            published_result=published,
        )
        assert token is not None
        # This is the interval in which Project publication wakes the work
        # scheduler. The slot must already be visible before schedule() runs.
        assert media_module.active_media_review_slots(PROJECT_ID) == {SLOT_ID}
        media_module.schedule_media_review(
            SimpleNamespace(),
            project_id=PROJECT_ID,
            published_result=published,
            reservation_token=token,
        )
        assert media_module.active_media_review_slots(PROJECT_ID) == {SLOT_ID}
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not media_module.active_media_review_slots(PROJECT_ID)

    asyncio.run(_run())


def _make_media(path: Path, *, video: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [_FFMPEG, "-y", "-hide_banner", "-f", "lavfi"]
    if video:
        command += ["-i", "color=c=red:s=192x108:d=3", "-f", "lavfi"]
        command += ["-i", "sine=frequency=440:sample_rate=44100:d=3"]
        command += ["-shortest", "-pix_fmt", "yuv420p", "-vf"]
        command += [
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:"
            "enable='between(t,1,2)'",
        ]
    else:
        command += ["-i", "color=c=red:s=64x64:d=1", "-frames:v", "1"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, timeout=120)


def _publish_project(services, *, video: bool = False) -> str:
    kind = "element_video" if video else "r2v_storyboard_image"
    suffix = "mp4" if video else "png"
    project = Project.new(project_id=PROJECT_ID, name="Media Review")
    created_at = project.created_at
    relative_uri = f"assets/artifacts/file-media-1.{suffix}"
    root = services.projects.project_root(PROJECT_ID)
    # Stage the payload first so the checksum matches the index.
    staging = Path(f"{root}-staging.{suffix}")
    _make_media(staging, video=video)
    payload = staging.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    project.assets.files_by_id["file-media-1"] = IndexedFile(
        file_id="file-media-1",
        kind="artifact_payload",
        relative_uri=relative_uri,
        sha256=sha,
        size_bytes=len(payload),
        media_type="video/mp4" if video else "image/png",
        created_at=created_at,
    )
    project.assets.artifact_versions_by_id[VERSION_ID] = ArtifactVersion(
        version_id=VERSION_ID,
        slot_id=SLOT_ID,
        kind=kind,
        owner_ref="element:e1",
        name="分镜视频 1" if video else "分镜图 1",
        file_id="file-media-1",
        checksum=sha,
        based_on_generation=0,
        created_at=created_at,
    )
    project.assets.artifact_slots_by_id[SLOT_ID] = ArtifactSlot(
        slot_id=SLOT_ID,
        kind=kind,
        owner_ref="element:e1",
        version_ids=[VERSION_ID],
        selected_version_id=VERSION_ID,
    )
    services.projects.create(project)
    destination = root / relative_uri
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(destination)
    return relative_uri


def _setup_loop(tmp_path, monkeypatch, *, video: bool = False):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
    relative_uri = _publish_project(services, video=video)
    services.sessions.create_project_runtime(PROJECT_ID)
    return services, relative_uri


def _stub_vlm(monkeypatch, responses: list[str]) -> list[dict]:
    calls: list[dict] = []

    async def fake_chat_completion(content, **kwargs):
        calls.append({"content": content, "kwargs": kwargs})
        return responses[min(len(calls), len(responses)) - 1]

    monkeypatch.setattr(media_module, "chat_completion", fake_chat_completion)
    return calls


def _run_loop(services, relative_uri, *, kind="image"):
    return asyncio.run(
        media_module.run_media_review_loop(
            services,
            project_id=PROJECT_ID,
            published=_published(relative_uri),
            kind=kind,
        ),
    )


def _feedback_messages(services) -> list:
    session = services.sessions.get_project_session_snapshot(PROJECT_ID)
    messages = services.sessions.list_messages(
        PROJECT_ID,
        session.session_id,
        after_seq=0,
        limit=None,
    )
    return [m for m in messages if m.source == "run_review_feedback"]


@requires_ffmpeg
def test_image_loop_retries_dedups_and_drops_stale_feedback(
    tmp_path,
    monkeypatch,
) -> None:
    services, relative_uri = _setup_loop(tmp_path, monkeypatch)

    async def _boom(content, **kwargs):
        raise RuntimeError("VLM exploded")

    monkeypatch.setattr(media_module, "chat_completion", _boom)
    assert _run_loop(services, relative_uri) is None
    # The claim was released, but the failed paid attempt remains consumed.
    calls = _stub_vlm(
        monkeypatch,
        [_findings(IMAGE_CHECKS, "craft", suggestion="手指畸变，重新生成")],
    )
    # Selection moved on mid-flight: revise recorded, feedback dropped.
    monkeypatch.setattr(
        media_module.feedback,
        "selected_slot_version",
        lambda *args, **kwargs: "artifact-version-newer",
    )
    report = _run_loop(services, relative_uri)
    assert report.verdict == "revise"
    assert report.round == 2
    assert _feedback_messages(services) == []
    assert _run_loop(services, relative_uri) is None
    assert len(calls) == 1, "the same version is never reviewed twice"


@requires_ffmpeg
def test_element_video_loop_embeds_gate_block(
    tmp_path,
    monkeypatch,
) -> None:
    """The video loop runs gates + frames + stats and delivers feedback."""
    services, relative_uri = _setup_loop(tmp_path, monkeypatch, video=True)
    calls = _stub_vlm(monkeypatch, [_video_fail()])
    report = _run_loop(services, relative_uri, kind="element_video")
    assert report.verdict == "revise"
    # The interior black was caught objectively before the VLM even ran.
    black = next(
        gate for gate in report.gate_block["gates"] if gate["name"] == "black"
    )
    assert black["metrics"]["interior_gaps"]
    assert report.gate_block["passed"] is False
    assert "门禁证据块" in calls[0]["content"][0]["text"]
    assert "分镜视频" in _feedback_messages(services)[0].content_parts[0].text


def test_gather_or_cancel_joins_thread_workers_before_raising() -> None:
    """A failed leg must not leave decode threads running unattended.

    asyncio.to_thread detaches on cancellation, so _gather_or_cancel could
    return (and the review loop release its media claim) while an ffmpeg
    or decode worker still reads the file. The thread legs are joined:
    the error propagates only after the worker has actually finished.
    """
    import threading

    release = threading.Event()
    finished = threading.Event()

    def slow_worker() -> str:
        release.wait(timeout=10)
        finished.set()
        return "done"

    async def failing_leg() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("probe failed")

    async def scenario() -> None:
        # The happy path still returns results and surfaces worker errors.
        assert await media_module._to_thread_or_join(lambda: 41 + 1) == 42

        loop = asyncio.get_running_loop()
        loop.call_later(0.1, release.set)
        with pytest.raises(RuntimeError, match="probe failed"):
            await media_module._gather_or_cancel(
                media_module._to_thread_or_join(slow_worker),
                failing_leg(),
            )
        assert (
            finished.is_set()
        ), "the error propagated before the thread worker finished"

    asyncio.run(scenario())
