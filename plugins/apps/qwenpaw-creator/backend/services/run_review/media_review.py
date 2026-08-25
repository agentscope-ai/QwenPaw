# -*- coding: utf-8 -*-
"""Async bypass review of generated image/element-video artifacts.

Mirrors the render-review scheduling contract (PR #77): every successful
convergence of a reviewed command may call :func:`schedule_media_review`;
the switch, the command filter and the already-reviewed dedup all live on
the review side, publishing is never blocked, and feedback lands as a
RUNTIME mutation-instruction message that drives the next revision run.

Objective evidence comes from the vendored upstream gates (ffprobe →
loudness → black, ``review_gates``) and frame statistics (``frame_stats``);
the VLM pass follows the vendored scene-review checks.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from models.vlm_model import chat_completion, multimodal_media_part
from schemas.run_review import MediaReviewFinding, MediaReviewReport
from services.observability.tracing import trace_event
from services.render_review.frames import extract_review_frames
from services.run_review import admission, feedback
from services.run_review.rubric_prompts import (
    build_image_check_system_prompt,
    build_scene_check_system_prompt,
)
from services.runtime_files import RequestAdmissionConflict
from utils.logger import setup_logger
from vendor.media_toolkit import frame_stats, review_gates

if TYPE_CHECKING:
    from services.project_files.facade import CreatorFileServices

logger = setup_logger("creator.run_review.media")

_TRACE_COMPONENT = "run_review"
_VLM_ATTEMPTS = 2
_VIDEO_REVIEW_FRAMES = 8
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

_IMAGE_CHECK_KEYS = ("devices", "type_fonts", "composition_safety", "craft")

# Strong references to in-flight review tasks: the event loop only keeps
# weak references, so an unreferenced task could be garbage-collected in
# the middle of a multi-second gates/VLM round.
_ACTIVE_REVIEW_TASKS: dict[str, set["asyncio.Task[Any]"]] = {}
_VIDEO_CHECK_KEYS = (
    "devices",
    "type_fonts",
    "composition_safety",
    "motion_quality",
    "technical",
    "watch_once",
)

# commandType -> review kind for the artifacts this bypass covers. The
# final render (COMPOSE_FINAL_VIDEO) stays with the render_review module.
REVIEWED_COMMANDS: dict[str, str] = {
    "GENERATE_ASSET": "image",
    "GENERATE_STORYBOARD_IMAGE": "image",
    "GENERATE_R2V_VIDEO": "element_video",
}


def _reports_root(services: "CreatorFileServices", project_id: str) -> Path:
    return (
        services.projects.project_root(project_id) / "runtime" / "run-review"
    )


def _project_is_live(
    services: "CreatorFileServices",
    project_id: str,
) -> bool:
    root = services.projects.project_root(project_id)
    return root.is_dir() and (root / "project.json").is_file()


def _derive_plan_context(
    services: "CreatorFileServices",
    project_id: str,
    published: Mapping[str, Any],
) -> dict[str, Any]:
    """Best-effort plan context for the devices check. Never raises."""
    artifact = published.get("artifactVersion") or {}
    context: dict[str, Any] = {
        "command": str(published.get("commandType") or ""),
        "target_ref": str(published.get("targetRef") or ""),
        "artifact_name": str(
            artifact.get("name") if isinstance(artifact, Mapping) else "",
        ),
    }
    try:
        snapshot = services.projects.read(project_id)
        project = snapshot.project
        context["project_brief"] = project.description
        target_ref = context["target_ref"]
        shots: list[dict[str, Any]] = []
        for timeline in project.timelines.items.values():
            for element in timeline.elements_by_id.values():
                if element.element_id not in target_ref:
                    continue
                creation = element.creation
                items = getattr(creation, "shots", None)
                if items is None:
                    continue
                for shot in items.items.values():
                    shots.append(
                        {
                            "shot_id": shot.shot_id,
                            "description": shot.description,
                            "dialogue": shot.dialogue,
                            "duration_seconds": shot.duration_seconds,
                        },
                    )
        if shots:
            context["planned_shots"] = shots[:12]
    except Exception:
        logger.exception("plan context derivation failed for %s", project_id)
    return context


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("media review response contains no JSON object")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("media review response JSON is not an object")
    return payload


def parse_media_report(
    text: str,
    *,
    kind: str,
    artifact_ref: str,
    round_number: int,
    gate_block: Mapping[str, Any] | None,
    stats: Mapping[str, Any] | None,
) -> MediaReviewReport:
    """Parse the VLM response; verdict is derived deterministically."""
    expected = _IMAGE_CHECK_KEYS if kind == "image" else _VIDEO_CHECK_KEYS
    payload = _extract_json_object(text)
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list) or not raw_findings:
        raise ValueError("media review response has no findings list")
    findings: list[MediaReviewFinding] = []
    seen: set[str] = set()
    for item in raw_findings:
        if not isinstance(item, Mapping):
            continue
        entry = dict(item)
        check_key = str(entry.get("check_key") or "")
        if check_key not in expected or check_key in seen:
            continue
        seen.add(check_key)
        if entry.get("severity") not in ("minor", "major"):
            entry["severity"] = "minor"
        timestamp = entry.get("evidence_timestamp_ms")
        if not isinstance(timestamp, int) or timestamp < 0:
            entry["evidence_timestamp_ms"] = None
        entry.setdefault("suggestion", "")
        if entry.get("suggestion") is None:
            entry["suggestion"] = ""
        finding = MediaReviewFinding.model_validate(entry)
        # Evidence discipline: a failure must carry evidence — a timestamp
        # for video, at least a concrete suggestion for still images.
        if not finding.passed:
            has_evidence = (
                finding.evidence_timestamp_ms is not None
                if kind == "element_video"
                else bool(finding.suggestion.strip())
            )
            if not has_evidence:
                finding = finding.model_copy(
                    update={"passed": True, "suggestion": ""},
                )
        findings.append(finding)
    missing = [key for key in expected if key not in seen]
    if missing:
        raise ValueError(
            "media review response missing checks: " + ", ".join(missing),
        )
    has_major = any(
        not item.passed and item.severity == "major" for item in findings
    )
    return MediaReviewReport(
        artifact_ref=artifact_ref,
        kind=kind,  # type: ignore[arg-type]
        round=round_number,
        gate_block=dict(gate_block) if gate_block else None,
        stats=dict(stats) if stats else None,
        findings=findings,
        verdict="revise" if has_major else "pass",
        created_at=datetime.now(UTC),
    )


async def review_media_artifact(
    *,
    kind: str,
    media_path: Path,
    artifact_ref: str,
    round_number: int,
    plan_context: Mapping[str, Any],
    frames_dir: Path,
) -> MediaReviewReport:
    """Run gates/stats plus the VLM scene checks for one artifact."""
    gate_block: dict[str, Any] | None = None
    stats: dict[str, Any] = {}
    if kind == "element_video":
        block = await asyncio.to_thread(
            review_gates.run_review_gates,
            media_path,
        )
        gate_block = block.to_dict()
        sampled = await asyncio.to_thread(
            frame_stats.sample_stats,
            media_path,
        )
        stats = {**sampled, "judgment": frame_stats.judge_stats(sampled)}
        frames = await asyncio.to_thread(
            extract_review_frames,
            media_path,
            max_frames=_VIDEO_REVIEW_FRAMES,
            output_dir=frames_dir,
        )
        system_prompt = build_scene_check_system_prompt()
        frame_lines = "\n".join(
            f"- 第 {index + 1} 张图 = t={frame.timestamp_ms}ms"
            for index, frame in enumerate(frames)
        )
        image_paths = [frame.image_path for frame in frames]
    else:
        sampled = await asyncio.to_thread(frame_stats.image_stats, media_path)
        stats = {**sampled, "judgment": frame_stats.judge_stats(sampled)}
        system_prompt = build_image_check_system_prompt()
        frame_lines = "- 第 1 张图 = 待审阅图像"
        image_paths = [str(media_path)]
    gate_lines = ""
    if gate_block is not None:
        gate_lines = "\n\n【门禁证据块（vendored review gates）】\n" + json.dumps(
            gate_block,
            ensure_ascii=False,
        )
    user_text = (
        "请按检查协议审阅这个生成产物。\n\n"
        + "【计划上下文】\n"
        + json.dumps(dict(plan_context), ensure_ascii=False)
        + "\n\n【画面统计（vendored frame stats）】\n"
        + json.dumps(stats, ensure_ascii=False)
        + gate_lines
        + "\n\n【证据图列表】\n"
        + frame_lines
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for path in image_paths:
        content.append(multimodal_media_part(Path(path).as_uri(), "image"))
    report: MediaReviewReport | None = None
    last_error: Exception | None = None
    for attempt in range(_VLM_ATTEMPTS):
        response = await chat_completion(
            content,
            system_prompt=system_prompt,
            max_tokens=1800,
        )
        try:
            report = parse_media_report(
                response,
                kind=kind,
                artifact_ref=artifact_ref,
                round_number=round_number,
                gate_block=gate_block,
                stats=stats,
            )
            break
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "media review response unparsable (attempt %d): %s",
                attempt + 1,
                exc,
            )
    if report is None:
        raise ValueError(
            f"media review response invalid after {_VLM_ATTEMPTS} attempts:"
            f" {last_error}",
        )
    return report


def _finalize_round(
    services: "CreatorFileServices",
    reports_root: Path,
    *,
    project_id: str,
    slot_id: str,
    version_id: str,
    target_ref: str,
    command: str,
    round_number: int,
    report: MediaReviewReport,
    owner: str | None = None,
) -> tuple[str, bool]:
    """Freshness-guarded finalization; mirrors the render_review contract."""
    owner = owner or admission.owner_token()
    needs_feedback = report.verdict == "revise"
    outcome = "completed"
    feedback_sent = False
    if needs_feedback:

        def _resolve_selected() -> str | None:
            try:
                return feedback.selected_slot_version(
                    services,
                    project_id,
                    version_id=version_id,
                    slot_id=slot_id,
                )
            except Exception:
                logger.exception("failed to resolve selected artifact")
                return None

        if _resolve_selected() != version_id:
            outcome = "stale"
        else:
            try:
                feedback_sent = feedback.admit_feedback(
                    services,
                    project_id=project_id,
                    report=report,
                    target_ref=target_ref,
                    command=command,
                    version_id=version_id,
                    freshness_guard=(
                        lambda: _resolve_selected() == version_id
                    ),
                )
            except RequestAdmissionConflict:
                outcome = "stale"
                feedback_sent = False
    settled = admission.finalize_media_round(
        reports_root,
        slot_id=slot_id,
        version_id=version_id,
        owner=owner,
        counted=outcome == "completed",
    )
    if not settled:
        outcome = "superseded"
        _ = round_number
    return outcome, feedback_sent


async def run_media_review_loop(
    services: "CreatorFileServices",
    *,
    project_id: str,
    published: Mapping[str, Any],
    kind: str,
) -> MediaReviewReport | None:
    """One advisory review round for a freshly published media artifact."""
    artifact = published.get("artifactVersion") or {}
    indexed = published.get("indexedFile") or {}
    version_id = str(artifact.get("version_id") or "")
    slot_id = str(artifact.get("slot_id") or "")
    target_ref = str(published.get("targetRef") or "")
    command = str(published.get("commandType") or "")
    relative_uri = str(indexed.get("relative_uri") or "")
    reports_root = _reports_root(services, project_id)
    owner = admission.owner_token()
    admitted: int | None = None
    try:
        admitted = await asyncio.to_thread(
            admission.admit_media_round,
            reports_root,
            slot_id=slot_id,
            version_id=version_id,
            owner=owner,
        )
        if admitted is None:
            trace_event(
                "run_review.media_skipped",
                component=_TRACE_COMPONENT,
                attributes={
                    "artifactRef": f"artifact-version:{version_id}",
                    "reason": "already_reviewed_or_budget_spent",
                },
                projectId=project_id,
            )
            return None
        media_path = services.projects.project_root(project_id) / relative_uri
        plan_context = await asyncio.to_thread(
            _derive_plan_context,
            services,
            project_id,
            published,
        )
        frames_dir = (
            reports_root
            / "media"
            / admission.safe_ref(version_id)
            / f"frames-round-{admitted}"
        )
        report = await review_media_artifact(
            kind=kind,
            media_path=media_path,
            artifact_ref=f"artifact-version:{version_id}",
            round_number=admitted,
            plan_context=plan_context,
            frames_dir=frames_dir,
        )
        if not _project_is_live(services, project_id):
            return None
        await asyncio.to_thread(
            admission.write_json,
            reports_root
            / "media"
            / admission.safe_ref(version_id)
            / f"round-{admitted}.json",
            report.model_dump(mode="json"),
        )
        outcome, feedback_sent = await asyncio.to_thread(
            _finalize_round,
            services,
            reports_root,
            project_id=project_id,
            slot_id=slot_id,
            version_id=version_id,
            target_ref=target_ref,
            command=command,
            round_number=admitted,
            report=report,
            owner=owner,
        )
        if feedback_sent:
            # Lazy import: the runtime registry pulls in the driver and
            # would create an import cycle at module load time.
            from services.file_agent_runtime.registry import (
                notify_creator_agent_runtime,
            )

            notify_creator_agent_runtime(project_id)
        trace_event(
            "run_review.media_round_completed",
            component=_TRACE_COMPONENT,
            attributes={
                "artifactRef": report.artifact_ref,
                "kind": kind,
                "round": admitted,
                "verdict": report.verdict,
                "outcome": outcome,
                "feedbackSent": feedback_sent,
            },
            projectId=project_id,
        )
        return report
    except asyncio.CancelledError:
        if admitted is not None and _project_is_live(services, project_id):
            admission.release_media_claim(
                reports_root,
                slot_id=slot_id,
                version_id=version_id,
                owner=owner,
            )
        raise
    except Exception as exc:
        # Advisory only: a review failure must never disturb delivery.
        logger.exception("media review loop failed for %s", version_id)
        if admitted is not None and _project_is_live(services, project_id):
            await asyncio.to_thread(
                admission.release_media_claim,
                reports_root,
                slot_id=slot_id,
                version_id=version_id,
                owner=owner,
            )
        trace_event(
            "run_review.media_failed",
            component=_TRACE_COMPONENT,
            status="error",
            attributes={
                "artifactRef": f"artifact-version:{version_id}",
                "errorType": type(exc).__name__,
                "error": str(exc)[:500],
            },
            projectId=project_id,
        )
        return None


def schedule_media_review(
    services: "CreatorFileServices",
    *,
    project_id: str,
    published_result: Mapping[str, Any],
) -> None:
    """Detach an advisory review round for a published media artifact.

    Single idempotent scheduling point: every successful convergence path
    (fresh generation, idempotent replay, crash recovery) may call it; the
    review-side admission dedups already-reviewed versions.
    """
    try:
        from models.config import is_media_review_enabled

        if not is_media_review_enabled():
            return
        kind = REVIEWED_COMMANDS.get(
            str(published_result.get("commandType") or ""),
        )
        if kind is None:
            return
        indexed = published_result.get("indexedFile")
        artifact = published_result.get("artifactVersion")
        if not isinstance(indexed, Mapping) or not isinstance(
            artifact,
            Mapping,
        ):
            return
        if not str(indexed.get("relative_uri") or "") or not str(
            artifact.get("version_id") or "",
        ):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "media review scheduling skipped: no running event loop",
            )
            return
        task = asyncio.create_task(
            run_media_review_loop(
                services,
                project_id=project_id,
                published=dict(published_result),
                kind=kind,
            ),
        )
        _ACTIVE_REVIEW_TASKS.setdefault(project_id, set()).add(task)

        def _log_outcome(done: asyncio.Task[Any]) -> None:
            project_tasks = _ACTIVE_REVIEW_TASKS.get(project_id)
            if project_tasks is not None:
                project_tasks.discard(done)
                if not project_tasks:
                    _ACTIVE_REVIEW_TASKS.pop(project_id, None)
            if not done.cancelled() and done.exception() is not None:
                logger.error(
                    "media review task crashed: %s",
                    done.exception(),
                )

        task.add_done_callback(_log_outcome)
    except Exception:
        # Scheduling must never disturb the publishing path.
        logger.exception("media review scheduling failed")


def cancel_project_media_reviews(project_id: str) -> None:
    """Synchronously signal all advisory review tasks for one Project."""

    for task in _ACTIVE_REVIEW_TASKS.pop(project_id, set()):
        task.cancel()


__all__ = [
    "REVIEWED_COMMANDS",
    "parse_media_report",
    "cancel_project_media_reviews",
    "review_media_artifact",
    "run_media_review_loop",
    "schedule_media_review",
]
