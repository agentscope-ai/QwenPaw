# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Review loop tests: stubbed VLM pass/revise states, round cap, switch off."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.config import is_self_review_enabled
from schemas.render_review import (
    AudioProfile,
    RenderReviewReport,
    ReviewDimension,
    ReviewFinding,
    ReviewFrame,
)
from services.media_files import local_execution
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
)
from services.render_review import review as review_module
from services.render_review.protocol import MAX_REVIEW_ROUNDS
from services.runtime_files.media_probe import MediaProbe
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

pytestmark = pytest.mark.unit

PROJECT_ID = "project-render-review"
TARGET_REF = "timeline:main"
SLOT_ID = "slot:render"


def _vlm_response(*, verdict_major_failure: bool) -> str:
    findings = []
    for dimension in ReviewDimension:
        failed = (
            verdict_major_failure and dimension is ReviewDimension.ENGINEERING
        )
        findings.append(
            {
                "dimension": dimension.value,
                "passed": not failed,
                "severity": "major" if failed else "minor",
                "evidence_timestamp_ms": 1000 if failed else None,
                "suggestion": "移除 1s 处黑帧" if failed else "",
            },
        )
    return json.dumps(
        {
            "findings": findings,
            "verdict": "revise" if verdict_major_failure else "pass",
        },
        ensure_ascii=False,
    )


@pytest.fixture()
def services(tmp_path: Path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Render Review")
    services.projects.create(project)
    services.sessions.create_project_runtime(PROJECT_ID)
    return services


@pytest.fixture()
def stubbed_evidence(tmp_path: Path, monkeypatch):
    frame_path = tmp_path / "stub-frame.jpg"
    frame_path.write_bytes(b"\xff\xd8\xff\xd9")

    def fake_extract(video_path, *, max_frames=24, output_dir=None):
        del video_path, max_frames, output_dir
        return [
            ReviewFrame(timestamp_ms=0, image_path=str(frame_path)),
            ReviewFrame(timestamp_ms=2000, image_path=str(frame_path)),
        ]

    def fake_audio(video_path):
        del video_path
        return AudioProfile(has_audio=True, integrated_lufs=-19.0)

    def fake_probe(target):
        del target
        return MediaProbe(duration_seconds=2.0, has_audio=True)

    monkeypatch.setattr(review_module, "extract_review_frames", fake_extract)
    monkeypatch.setattr(review_module, "probe_audio_profile", fake_audio)
    monkeypatch.setattr(review_module, "probe_media", fake_probe)


def _stub_vlm(monkeypatch, responses: list[str]) -> list[dict]:
    calls: list[dict] = []

    async def fake_chat_completion(content, **kwargs):
        calls.append({"content": content, "kwargs": kwargs})
        index = min(len(calls), len(responses)) - 1
        return responses[index]

    monkeypatch.setattr(review_module, "chat_completion", fake_chat_completion)
    return calls


def _publish_selected(
    services: CreatorFileServices,
    video_id: str,
    *,
    project_id: str = PROJECT_ID,
) -> None:
    """Commit ``video_id`` as the selected render of the timeline slot.

    Mirrors what a successful COMPOSE_FINAL_VIDEO commit leaves behind so
    the fail-closed freshness check can prove the reviewed video is the
    currently selected artifact.
    """
    snapshot = services.projects.read(project_id)
    candidate = snapshot.project.model_dump(mode="json")
    assets = candidate["assets"]
    file_id = f"file-{video_id}"
    created_at = candidate["created_at"]
    assets["files_by_id"][file_id] = {
        "file_id": file_id,
        "kind": "artifact_payload",
        "relative_uri": f"assets/artifacts/{file_id}.mp4",
        "sha256": "0" * 64,
        "size_bytes": 4,
        "media_type": "video/mp4",
        "created_at": created_at,
    }
    assets["artifact_versions_by_id"][video_id] = {
        "version_id": video_id,
        "slot_id": SLOT_ID,
        "kind": "final_video",
        "owner_ref": TARGET_REF,
        "name": "final",
        "file_id": file_id,
        "checksum": "0" * 64,
        "based_on_generation": 0,
        "created_at": created_at,
    }
    slot = assets["artifact_slots_by_id"].get(SLOT_ID) or {
        "slot_id": SLOT_ID,
        "kind": "final_video",
        "owner_ref": TARGET_REF,
        "version_ids": [],
        "selected_version_id": None,
    }
    if video_id not in slot["version_ids"]:
        slot["version_ids"].append(video_id)
    slot["selected_version_id"] = video_id
    assets["artifact_slots_by_id"][SLOT_ID] = slot
    services.commits.commit(
        base=snapshot,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )


def _run_round(
    services: CreatorFileServices,
    video_id: str,
    *,
    publish_selected: bool = True,
):
    video_path = (
        services.projects.project_root(PROJECT_ID)
        / "assets"
        / "artifacts"
        / f"{video_id}.mp4"
    )
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"stub")
    if publish_selected:
        _publish_selected(services, video_id)
    return asyncio.run(
        review_module.run_review_loop(
            services,
            project_id=PROJECT_ID,
            video_path=video_path,
            video_id=video_id,
            target_ref=TARGET_REF,
            slot_id=SLOT_ID,
        ),
    )


def _feedback_messages(services: CreatorFileServices) -> list:
    session = services.sessions.get_project_session_snapshot(PROJECT_ID)
    messages = services.sessions.list_messages(
        PROJECT_ID,
        session.session_id,
        after_seq=0,
        limit=None,
    )
    return [
        item for item in messages if item.source == "render_review_feedback"
    ]


def test_pass_verdict_closes_chain_without_feedback(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=False)])
    report = _run_round(services, "video-pass-1")
    assert report is not None
    assert report.verdict == "pass"
    assert report.round == 1

    review_dir = (
        services.projects.project_root(PROJECT_ID)
        / "runtime"
        / "render-review"
    )
    report_path = review_dir / "video-pass-1" / "round-1.json"
    assert report_path.is_file()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["verdict"] == "pass"
    assert persisted["round"] == 1

    chain = json.loads(
        (review_dir / "chain-timeline-main.json").read_text(encoding="utf-8"),
    )
    assert chain["status"] == "closed"
    assert _feedback_messages(services) == []


def test_revise_verdict_sends_feedback_and_caps_rounds(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=True)])

    for round_number in range(1, MAX_REVIEW_ROUNDS + 1):
        report = _run_round(services, f"video-revise-{round_number}")
        assert report is not None
        assert report.verdict == "revise"
        assert report.round == round_number

    feedback = _feedback_messages(services)
    # Feedback goes out for every revise round except the final one.
    assert len(feedback) == MAX_REVIEW_ROUNDS - 1
    first_text = feedback[0].content_parts[0].text or ""
    assert "render_review_feedback" in first_text
    assert "ai_editing_director" in first_text
    assert TARGET_REF in first_text
    assert feedback[0].metadata["renderReview"]["round"] == 1

    review_dir = (
        services.projects.project_root(PROJECT_ID)
        / "runtime"
        / "render-review"
    )
    chain = json.loads(
        (review_dir / "chain-timeline-main.json").read_text(encoding="utf-8"),
    )
    assert chain["status"] == "closed"
    assert chain["rounds_completed"] == MAX_REVIEW_ROUNDS

    # The chain is spent: a fourth compose starts a fresh chain at round 1.
    report = _run_round(services, "video-revise-4")
    assert report is not None
    assert report.round == 1


def test_duplicate_video_review_is_skipped(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=True)])
    first = _run_round(services, "video-dup-1")
    assert first is not None
    duplicate = _run_round(services, "video-dup-1")
    assert duplicate is None
    assert len(_feedback_messages(services)) == 1


def test_unparsable_vlm_response_never_raises(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    calls = _stub_vlm(monkeypatch, ["这不是 JSON", "还是不是 JSON"])
    report = _run_round(services, "video-broken-1")
    assert report is None
    assert len(calls) == 2
    assert _feedback_messages(services) == []


def test_schedule_render_review_tolerates_bad_result(services) -> None:
    # Missing fields must be ignored without raising.
    review_module.schedule_render_review(
        services,
        project_id=PROJECT_ID,
        published_result={"commandType": "COMPOSE_FINAL_VIDEO"},
    )


def test_self_review_switch_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("CREATOR_SELF_REVIEW_ENABLED", raising=False)
    assert is_self_review_enabled() is False
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "1")
    assert is_self_review_enabled() is True
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "off")
    assert is_self_review_enabled() is False


def _revise_report(video_id: str, round_number: int) -> RenderReviewReport:
    findings = [
        ReviewFinding(
            dimension=dimension,
            passed=dimension is not ReviewDimension.ENGINEERING,
            severity=(
                "major"
                if dimension is ReviewDimension.ENGINEERING
                else "minor"
            ),
            evidence_timestamp_ms=(
                1000 if dimension is ReviewDimension.ENGINEERING else None
            ),
            suggestion=(
                "移除黑帧" if dimension is ReviewDimension.ENGINEERING else ""
            ),
        )
        for dimension in ReviewDimension
    ]
    return RenderReviewReport(
        video_ref=f"artifact-version:{video_id}",
        round=round_number,
        findings=findings,
        verdict="revise",
    )


def test_superseding_claim_drops_stale_feedback(services) -> None:
    """An in-flight round for an older video must not mutate the timeline."""
    reports_root = review_module._reports_root(services, PROJECT_ID)
    admitted_a = review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id="video-old",
    )
    assert admitted_a == (1, admitted_a[1])
    # A newer composition supersedes the in-flight claim atomically.
    admitted_b = review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id="video-new",
    )
    assert admitted_b is not None
    outcome_a, feedback_a = review_module._finalize_round(
        services,
        reports_root,
        project_id=PROJECT_ID,
        target_ref=TARGET_REF,
        chain_id=admitted_a[1],
        round_number=admitted_a[0],
        video_id="video-old",
        slot_id=None,
        report=_revise_report("video-old", admitted_a[0]),
    )
    assert outcome_a == "superseded"
    assert feedback_a is False
    assert _feedback_messages(services) == []
    _publish_selected(services, "video-new")
    outcome_b, feedback_b = review_module._finalize_round(
        services,
        reports_root,
        project_id=PROJECT_ID,
        target_ref=TARGET_REF,
        chain_id=admitted_b[1],
        round_number=admitted_b[0],
        video_id="video-new",
        slot_id=SLOT_ID,
        report=_revise_report("video-new", admitted_b[0]),
    )
    assert outcome_b == "completed"
    assert feedback_b is True
    chain = json.loads(
        (review_module._chain_path(reports_root, TARGET_REF)).read_text(
            encoding="utf-8",
        ),
    )
    # The superseded round consumed no chain budget.
    assert chain["rounds_completed"] == 1
    assert chain["last_video_id"] == "video-new"
    assert "video-old" in chain["reviewed_video_ids"]


def test_unselected_artifact_never_receives_feedback(
    tmp_path,
    monkeypatch,
) -> None:
    """Feedback is dropped when the video is no longer the selected render."""
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Render Review")
    created_at = project.created_at
    for version_id in ("video-a", "video-b"):
        file_id = f"file-{version_id}"
        project.assets.files_by_id[file_id] = IndexedFile(
            file_id=file_id,
            kind="artifact_payload",
            relative_uri=f"assets/artifacts/{file_id}.mp4",
            sha256="0" * 64,
            size_bytes=4,
            media_type="video/mp4",
            created_at=created_at,
        )
        project.assets.artifact_versions_by_id[version_id] = ArtifactVersion(
            version_id=version_id,
            slot_id="slot:render",
            kind="final_video",
            owner_ref=TARGET_REF,
            name="final",
            file_id=file_id,
            checksum="0" * 64,
            based_on_generation=0,
            created_at=created_at,
        )
    project.assets.artifact_slots_by_id["slot:render"] = ArtifactSlot(
        slot_id="slot:render",
        kind="final_video",
        owner_ref=TARGET_REF,
        version_ids=["video-a", "video-b"],
        selected_version_id="video-b",
    )
    services.projects.create(project)
    services.sessions.create_project_runtime(PROJECT_ID)
    reports_root = review_module._reports_root(services, PROJECT_ID)
    admitted = review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id="video-a",
    )
    assert admitted is not None
    outcome, feedback_sent = review_module._finalize_round(
        services,
        reports_root,
        project_id=PROJECT_ID,
        target_ref=TARGET_REF,
        chain_id=admitted[1],
        round_number=admitted[0],
        video_id="video-a",
        slot_id="slot:render",
        report=_revise_report("video-a", admitted[0]),
    )
    assert outcome == "stale"
    assert feedback_sent is False
    assert _feedback_messages(services) == []


def test_unverifiable_selection_suppresses_feedback(services) -> None:
    """No slot / unreadable Project means no proof of freshness: fail closed."""
    reports_root = review_module._reports_root(services, PROJECT_ID)
    admitted = review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id="video-unverified",
    )
    assert admitted is not None
    outcome, feedback_sent = review_module._finalize_round(
        services,
        reports_root,
        project_id=PROJECT_ID,
        target_ref=TARGET_REF,
        chain_id=admitted[1],
        round_number=admitted[0],
        video_id="video-unverified",
        slot_id=SLOT_ID,
        report=_revise_report("video-unverified", admitted[0]),
    )
    assert outcome == "unverified"
    assert feedback_sent is False
    assert _feedback_messages(services) == []


def test_selection_switch_between_check_and_admit_aborts_feedback(
    services,
    monkeypatch,
) -> None:
    """The admission guard closes the check-then-admit race window."""
    _publish_selected(services, "video-race-1")
    reports_root = review_module._reports_root(services, PROJECT_ID)
    admitted = review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id="video-race-1",
    )
    assert admitted is not None
    real_resolver = review_module._selected_slot_version
    calls = {"count": 0}

    def racing_resolver(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # Pre-check still sees the reviewed video as selected.
            return real_resolver(*args, **kwargs)
        # A concurrent compose switched the selection before the durable
        # feedback write (the guard re-runs inside the lifecycle boundary).
        return "video-race-2"

    monkeypatch.setattr(
        review_module,
        "_selected_slot_version",
        racing_resolver,
    )
    outcome, feedback_sent = review_module._finalize_round(
        services,
        reports_root,
        project_id=PROJECT_ID,
        target_ref=TARGET_REF,
        chain_id=admitted[1],
        round_number=admitted[0],
        video_id="video-race-1",
        slot_id=SLOT_ID,
        report=_revise_report("video-race-1", admitted[0]),
    )
    assert calls["count"] >= 2
    assert outcome == "stale"
    assert feedback_sent is False
    assert _feedback_messages(services) == []


def test_cancel_during_admission_releases_persisted_claim(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    """A cancel landing while the admission thread runs must not strand it.

    The worker persists the claim, then the awaiting task is cancelled
    before the result reaches the coroutine; the settle path must release
    the claim from the worker's outcome so a same-process replay is not
    blocked until the TTL.
    """
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=False)])
    reports_root = review_module._reports_root(services, PROJECT_ID)
    chain_path = review_module._chain_path(reports_root, TARGET_REF)
    claim_written = threading.Event()
    release_gate = threading.Event()
    real_admit = review_module._admit_round

    def slow_admit(*args, **kwargs):
        result = real_admit(*args, **kwargs)
        claim_written.set()
        # Hold the worker past the cancellation point.
        release_gate.wait(5)
        return result

    monkeypatch.setattr(review_module, "_admit_round", slow_admit)

    async def scenario() -> None:
        video_path = (
            services.projects.project_root(PROJECT_ID)
            / "assets"
            / "artifacts"
            / "video-cancel-1.mp4"
        )
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"stub")
        task = asyncio.create_task(
            review_module.run_review_loop(
                services,
                project_id=PROJECT_ID,
                video_path=video_path,
                video_id="video-cancel-1",
                target_ref=TARGET_REF,
                slot_id=SLOT_ID,
            ),
        )
        await asyncio.to_thread(claim_written.wait, 5)
        task.cancel()
        release_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Let the settle done-callback run on the loop.
        for _ in range(20):
            await asyncio.sleep(0.05)
            state = json.loads(chain_path.read_text(encoding="utf-8"))
            if not state.get("claim"):
                break

    asyncio.run(scenario())
    state = json.loads(chain_path.read_text(encoding="utf-8"))
    assert not state.get("claim")
    monkeypatch.setattr(review_module, "_admit_round", real_admit)
    # Same-process replay reviews the video immediately (no TTL wait).
    report = _run_round(services, "video-cancel-1")
    assert report is not None and report.verdict == "pass"


def test_shutdown_cancelling_all_tasks_does_not_strand_claim(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    """Loop shutdown cancels the shielded admission task itself.

    Both the outer review task and the inner admission task are cancelled
    (as ``asyncio.run`` shutdown does), so no done-callback ever learns the
    worker's outcome while the ``to_thread`` worker still persists the
    claim afterwards. The per-loop lease must make the very next schedule
    — running on a new event loop in the same process — reclaim the claim
    immediately instead of waiting for the 30-minute TTL.
    """
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=False)])
    reports_root = review_module._reports_root(services, PROJECT_ID)
    chain_path = review_module._chain_path(reports_root, TARGET_REF)
    claim_written = threading.Event()
    release_gate = threading.Event()
    real_admit = review_module._admit_round

    def slow_admit(*args, **kwargs):
        result = real_admit(*args, **kwargs)
        claim_written.set()
        # Persist past both cancellations before returning.
        release_gate.wait(5)
        return result

    monkeypatch.setattr(review_module, "_admit_round", slow_admit)

    async def scenario() -> None:
        video_path = (
            services.projects.project_root(PROJECT_ID)
            / "assets"
            / "artifacts"
            / "video-shutdown-1.mp4"
        )
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"stub")
        task = asyncio.create_task(
            review_module.run_review_loop(
                services,
                project_id=PROJECT_ID,
                video_path=video_path,
                video_id="video-shutdown-1",
                target_ref=TARGET_REF,
                slot_id=SLOT_ID,
            ),
        )
        await asyncio.to_thread(claim_written.wait, 5)
        # Simulate event-loop shutdown: cancel every pending task,
        # including the shielded admission task, before the worker returns.
        current = asyncio.current_task()
        for pending in asyncio.all_tasks():
            if pending is not current:
                pending.cancel()
        release_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    # The worker persisted the claim before any cleanup path could learn
    # its outcome; only the dead loop's lease token guards it now.
    state = json.loads(chain_path.read_text(encoding="utf-8"))
    assert state.get("claim")
    monkeypatch.setattr(review_module, "_admit_round", real_admit)
    # Replay in a fresh scheduling context reclaims immediately (no TTL).
    report = _run_round(services, "video-shutdown-1")
    assert report is not None and report.verdict == "pass"


def test_claim_from_dead_process_is_reclaimed(services) -> None:
    """A crash-leftover claim must not suppress the recovery schedule."""
    reports_root = review_module._reports_root(services, PROJECT_ID)
    chain_path = review_module._chain_path(reports_root, TARGET_REF)
    review_module._write_json(
        chain_path,
        {
            "chain_id": "chain-crashed",
            "target_ref": TARGET_REF,
            "rounds_completed": 0,
            "status": "open",
            "reviewed_video_ids": [],
            "claim": {
                "video_id": "video-crash-1",
                "round": 1,
                "owner": "dead-process-token",
                "claimed_at": "2026-08-04T00:00:00+00:00",
            },
        },
    )
    admitted = review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id="video-crash-1",
    )
    assert admitted == (1, "chain-crashed")
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    assert chain["claim"]["owner"] == review_module._PROCESS_TOKEN


def test_derive_plan_context_target_forms_and_audio_roles(services) -> None:
    """Both target forms resolve; only narration-role audio counts."""
    from services.project_files.models import (
        AudioCreation,
        SourceAssetVersion,
        Timeline,
        TimelineElement,
        TimelineSpan,
    )

    project = Project.new(project_id="project-ctx", name="ctx")
    for suffix, metadata in (
        ("bgm", {}),
        ("vo", {"sourceKind": "tts_generation"}),
    ):
        file_id = f"file-{suffix}"
        project.assets.files_by_id[file_id] = IndexedFile(
            file_id=file_id,
            kind="source_original",
            relative_uri=f"assets/sources/{file_id}.wav",
            sha256="0" * 64,
            size_bytes=4,
            media_type="audio/wav",
            created_at=project.created_at,
        )
        project.assets.source_versions_by_id[
            f"asset-version-{suffix}"
        ] = SourceAssetVersion(
            version_id=f"asset-version-{suffix}",
            logical_asset_id=f"asset:{suffix}",
            name=suffix,
            file_id=file_id,
            checksum="0" * 64,
            media_kind="audio",
            media_type="audio/wav",
            created_at=project.created_at,
            metadata=metadata,
        )

    def timeline_with(*suffixes: str) -> Timeline:
        elements = {
            f"audio:{suffix}": TimelineElement(
                element_id=f"audio:{suffix}",
                span=TimelineSpan(start_tick=0, duration_tick=1000),
                creation=AudioCreation(
                    source_asset_version_id=f"asset-version-{suffix}",
                ),
            )
            for suffix in suffixes
        }
        return Timeline(
            timeline_id="timeline:main",
            elements_by_id=elements,
        )

    project.timelines.items["timeline:main"] = timeline_with("bgm")
    project.timelines.order.append("timeline:main")
    # A plain music bed is not a narration expectation.
    for ref in ("timeline:timeline:main", "timeline:main"):
        context = review_module.derive_plan_context(project, ref)
        assert context["expects_voiceover"] is False, ref
    # A TTS-generated source marks the narration expectation, and both
    # supported target forms resolve the same timeline.
    project.timelines.items["timeline:main"] = timeline_with("bgm", "vo")
    for ref in ("timeline:timeline:main", "timeline:main"):
        context = review_module.derive_plan_context(project, ref)
        assert context["expects_voiceover"] is True, ref


def test_failed_round_releases_claim_for_retry(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    _stub_vlm(monkeypatch, ["不是 JSON", "还不是 JSON"])
    assert _run_round(services, "video-retry-1") is None
    reports_root = review_module._reports_root(services, PROJECT_ID)
    chain = json.loads(
        review_module._chain_path(reports_root, TARGET_REF).read_text(
            encoding="utf-8",
        ),
    )
    assert not chain.get("claim")
    # The same video can be rescheduled after the failure.
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=False)])
    report = _run_round(services, "video-retry-1")
    assert report is not None and report.verdict == "pass"


def test_schedule_gate_and_dedup(services, monkeypatch) -> None:
    """The single scheduling point filters switch, command and shape."""
    calls: list[str] = []

    async def fake_loop(*args, **kwargs):
        calls.append(kwargs["video_id"])
        return None

    monkeypatch.setattr(review_module, "run_review_loop", fake_loop)
    result = {
        "commandType": "COMPOSE_FINAL_VIDEO",
        "targetRef": TARGET_REF,
        "indexedFile": {"relative_uri": "assets/artifacts/f.mp4"},
        "artifactVersion": {
            "version_id": "video-gate-1",
            "slot_id": "slot:render",
        },
    }

    async def drive() -> None:
        monkeypatch.delenv("CREATOR_SELF_REVIEW_ENABLED", raising=False)
        review_module.schedule_render_review(
            services,
            project_id=PROJECT_ID,
            published_result=result,
        )
        monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "1")
        review_module.schedule_render_review(
            services,
            project_id=PROJECT_ID,
            published_result={**result, "commandType": "EXECUTE_EDIT"},
        )
        review_module.schedule_render_review(
            services,
            project_id=PROJECT_ID,
            published_result=result,
        )
        await asyncio.sleep(0)

    asyncio.run(drive())
    assert calls == ["video-gate-1"]


def test_result_from_task_routes_every_success_through_review(
    services,
    monkeypatch,
) -> None:
    """Replay/recovery convergences share the same scheduling point."""
    scheduled: list[str] = []

    def fake_schedule(_services, *, project_id, published_result):
        del project_id
        scheduled.append(published_result["artifactVersion"]["version_id"])

    monkeypatch.setattr(
        local_execution,
        "schedule_render_review",
        fake_schedule,
    )
    service = object.__new__(local_execution.FileLocalMediaExecutionService)
    service.services = services
    task = SimpleNamespace(
        task_id="task-1",
        run_id="run-1",
        project_id=PROJECT_ID,
        result={
            "commandType": "COMPOSE_FINAL_VIDEO",
            "targetRef": TARGET_REF,
            "transactionId": "txn-1",
            "projectEtag": "etag-1",
            "projectGeneration": 3,
            "indexedFile": {"relative_uri": "assets/artifacts/f.mp4"},
            "artifactVersion": {
                "version_id": "artifact-version-replay",
                "slot_id": "slot:render",
                "kind": "final_video",
                "owner_ref": TARGET_REF,
                "name": "final",
                "file_id": "file-1",
                "checksum": "0" * 64,
                "based_on_generation": 1,
                "created_at": "2026-08-03T00:00:00Z",
            },
        },
    )
    outcome = service._result_from_task(task, replayed=True)
    assert outcome.artifact_version_id == "artifact-version-replay"
    assert outcome.replayed is True
    assert scheduled == ["artifact-version-replay"]
