# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Review loop tests: stubbed VLM pass/revise states, round cap, claims."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from schemas.render_review import (
    AudioProfile,
    RenderReviewReport,
    ReviewDimension,
    ReviewFinding,
    ReviewFrame,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.render_review import review as review_module
from services.render_review.protocol import MAX_REVIEW_ROUNDS
from services.runtime_files.media_probe import MediaProbe
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

pytestmark = pytest.mark.unit

PROJECT_ID = "project-render-review"
TARGET_REF = "timeline:main"
SLOT_ID = "slot:render"


def _vlm_response(*, verdict_major_failure: bool) -> str:
    failed = ReviewDimension.ENGINEERING if verdict_major_failure else None
    findings = [
        {
            "dimension": dim.value,
            "passed": dim is not failed,
            "severity": "major" if dim is failed else "minor",
            "evidence_timestamp_ms": 1000 if dim is failed else None,
            "suggestion": "移除 1s 处黑帧" if dim is failed else "",
        }
        for dim in ReviewDimension
    ]
    return json.dumps(
        {
            "findings": findings,
            "verdict": "revise" if verdict_major_failure else "pass",
        },
        ensure_ascii=False,
    )


def _revise_report(video_id: str, round_number: int) -> RenderReviewReport:
    payload = json.loads(_vlm_response(verdict_major_failure=True))
    return RenderReviewReport(
        video_ref=f"artifact-version:{video_id}",
        round=round_number,
        findings=[ReviewFinding(**item) for item in payload["findings"]],
        verdict="revise",
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

    def fake_extract(*_args, **_kwargs):
        return [
            ReviewFrame(timestamp_ms=ts, image_path=str(frame_path))
            for ts in (0, 2000)
        ]

    monkeypatch.setattr(review_module, "extract_review_frames", fake_extract)
    monkeypatch.setattr(
        review_module,
        "probe_audio_profile",
        lambda _p: AudioProfile(has_audio=True, integrated_lufs=-19.0),
    )
    monkeypatch.setattr(
        review_module,
        "probe_media",
        lambda _t: MediaProbe(duration_seconds=2.0, has_audio=True),
    )


def _stub_vlm(monkeypatch, responses: list[str]) -> list[dict]:
    calls: list[dict] = []

    async def fake_chat_completion(content, **kwargs):
        calls.append({"content": content, "kwargs": kwargs})
        index = min(len(calls), len(responses)) - 1
        return responses[index]

    monkeypatch.setattr(review_module, "chat_completion", fake_chat_completion)
    return calls


def _publish_selected(services: CreatorFileServices, video_id: str) -> None:
    snapshot = services.projects.read(PROJECT_ID)
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


def _video_path(services: CreatorFileServices, video_id: str) -> Path:
    path = (
        services.projects.project_root(PROJECT_ID)
        / "assets"
        / "artifacts"
        / f"{video_id}.mp4"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"stub")
    return path


def _run_round(services: CreatorFileServices, video_id: str):
    video_path = _video_path(services, video_id)
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


def _admit(reports_root, video_id: str):
    return review_module._admit_round(
        reports_root,
        target_ref=TARGET_REF,
        video_id=video_id,
    )


def _finalize(services, reports_root, admitted, video_id, slot_id=SLOT_ID):
    return review_module._finalize_round(
        services,
        reports_root,
        project_id=PROJECT_ID,
        target_ref=TARGET_REF,
        chain_id=admitted[1],
        round_number=admitted[0],
        video_id=video_id,
        slot_id=slot_id,
        report=_revise_report(video_id, admitted[0]),
    )


def _chain_state(services) -> dict:
    reports_root = review_module._reports_root(services, PROJECT_ID)
    chain_path = review_module._chain_path(reports_root, TARGET_REF)
    return json.loads(chain_path.read_text(encoding="utf-8"))


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


def test_revise_verdict_sends_feedback_and_caps_rounds(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=True)])

    for round_number in range(1, MAX_REVIEW_ROUNDS + 1):
        report = _run_round(services, f"video-revise-{round_number}")
        assert report.verdict == "revise"
        assert report.round == round_number

    feedback = _feedback_messages(services)
    assert len(feedback) == MAX_REVIEW_ROUNDS - 1
    first_text = feedback[0].content_parts[0].text or ""
    assert "render_review_feedback" in first_text
    assert "ai_editing_director" in first_text
    assert TARGET_REF in first_text
    assert feedback[0].metadata["renderReview"]["round"] == 1

    chain = _chain_state(services)
    assert chain["status"] == "closed"
    assert chain["rounds_completed"] == MAX_REVIEW_ROUNDS

    # The chain is spent: a fourth compose starts a fresh chain at round 1.
    report = _run_round(services, "video-revise-4")
    assert report.round == 1


def test_unparsable_vlm_response_fails_closed_and_frees_claim(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    calls = _stub_vlm(monkeypatch, ["这不是 JSON", "还是不是 JSON"])
    report = _run_round(services, "video-broken-1")
    assert report is None
    assert len(calls) == 2
    assert _feedback_messages(services) == []
    # The failed round released its claim: the passing retry closes it.
    assert not _chain_state(services).get("claim")
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=False)])
    report = _run_round(services, "video-broken-1")
    assert report.verdict == "pass"
    assert _chain_state(services)["status"] == "closed"
    assert _feedback_messages(services) == []


def test_superseding_claim_drops_stale_feedback(services) -> None:
    """An in-flight round for an older video must not mutate the timeline."""
    reports_root = review_module._reports_root(services, PROJECT_ID)
    admitted_a = _admit(reports_root, "video-old")
    assert admitted_a == (1, admitted_a[1])
    admitted_b = _admit(reports_root, "video-new")
    assert admitted_b is not None
    outcome_a, feedback_a = _finalize(
        services,
        reports_root,
        admitted_a,
        "video-old",
        slot_id=None,
    )
    assert outcome_a == "superseded"
    assert feedback_a is False
    assert _feedback_messages(services) == []
    _publish_selected(services, "video-new")
    outcome_b, feedback_b = _finalize(
        services,
        reports_root,
        admitted_b,
        "video-new",
    )
    assert outcome_b == "completed"
    assert feedback_b is True
    chain = _chain_state(services)
    # The superseded round consumed no chain budget.
    assert chain["rounds_completed"] == 1
    assert chain["last_video_id"] == "video-new"


def test_selection_switch_between_check_and_admit_aborts_feedback(
    services,
    monkeypatch,
) -> None:
    """The admission guard closes the check-then-admit race window."""
    _publish_selected(services, "video-race-1")
    reports_root = review_module._reports_root(services, PROJECT_ID)
    admitted = _admit(reports_root, "video-race-1")
    assert admitted is not None
    real_resolver = review_module._selected_slot_version
    calls = {"count": 0}

    def racing_resolver(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_resolver(*args, **kwargs)
        return "video-race-2"

    monkeypatch.setattr(
        review_module,
        "_selected_slot_version",
        racing_resolver,
    )
    outcome, feedback_sent = _finalize(
        services,
        reports_root,
        admitted,
        "video-race-1",
    )
    assert outcome == "stale"
    assert feedback_sent is False
    assert _feedback_messages(services) == []


def test_cancelled_admission_never_strands_claim(
    services,
    stubbed_evidence,
    monkeypatch,
) -> None:
    """A cancel while the claim is held must release it for replay."""
    _stub_vlm(monkeypatch, [_vlm_response(verdict_major_failure=False)])
    claim_written = threading.Event()
    release_gate = threading.Event()
    real_admit = review_module._admit_round

    def slow_admit(*args, **kwargs):
        result = real_admit(*args, **kwargs)
        claim_written.set()
        release_gate.wait(5)
        return result

    monkeypatch.setattr(review_module, "_admit_round", slow_admit)
    reports_root = review_module._reports_root(services, PROJECT_ID)
    chain_path = review_module._chain_path(reports_root, TARGET_REF)

    async def scenario() -> None:
        task = asyncio.create_task(
            review_module.run_review_loop(
                services,
                project_id=PROJECT_ID,
                video_path=_video_path(services, "video-cancel-1"),
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
        for _ in range(20):
            await asyncio.sleep(0.05)
            state = json.loads(chain_path.read_text(encoding="utf-8"))
            if not state.get("claim"):
                break

    asyncio.run(scenario())
    monkeypatch.setattr(review_module, "_admit_round", real_admit)
    assert not _chain_state(services).get("claim")
    assert _run_round(services, "video-cancel-1").verdict == "pass"


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
    admitted = _admit(reports_root, "video-crash-1")
    assert admitted == (1, "chain-crashed")
    chain = _chain_state(services)
    assert chain["claim"]["owner"] == review_module._PROCESS_TOKEN


def test_schedule_gate_and_dedup(services, monkeypatch) -> None:
    """The single scheduling point filters switch, command and shape."""
    calls: list[str] = []

    async def fake_loop(*args, **kwargs):
        calls.append(kwargs["video_id"])
        return None

    monkeypatch.setattr(review_module, "run_review_loop", fake_loop)

    def schedule(res: dict) -> None:
        review_module.schedule_render_review(
            services,
            project_id=PROJECT_ID,
            published_result=res,
        )

    result = {
        "commandType": "COMPOSE_FINAL_VIDEO",
        "targetRef": TARGET_REF,
        "indexedFile": {"relative_uri": "assets/artifacts/f.mp4"},
        "artifactVersion": {"version_id": "video-gate-1", "slot_id": SLOT_ID},
    }

    async def drive() -> None:
        monkeypatch.delenv("CREATOR_SELF_REVIEW_ENABLED", raising=False)
        schedule(result)
        monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "1")
        schedule({**result, "commandType": "EXECUTE_EDIT"})
        # Missing fields must be ignored without raising.
        schedule({"commandType": "COMPOSE_FINAL_VIDEO"})
        schedule(result)
        await asyncio.sleep(0)

    asyncio.run(drive())
    assert calls == ["video-gate-1"]
