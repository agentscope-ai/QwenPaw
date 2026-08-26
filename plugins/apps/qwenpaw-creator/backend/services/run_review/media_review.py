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
import contextlib
import functools
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

from models.vlm_model import chat_completion, multimodal_media_part
from schemas.run_review import (
    MediaReviewFinding,
    MediaReviewReport,
    ProbeFinding,
)
from services.observability.tracing import trace_event
from services.render_review.frames import extract_review_frames
from services.run_review import admission, feedback
from services.run_review.defect_bank import (
    UNIVERSAL_DEFECTS,
    build_defect_question_block,
    program_defect_hints,
)
from services.run_review.faithfulness import (
    FAITHFULNESS_SEVERITIES,
    build_faithfulness_block,
    build_faithfulness_elements,
)
from services.run_review.objective import (
    collect_image_facts,
    collect_video_facts,
    render_facts_block,
)
from services.run_review.objective.asr_bridge import transcript_sentences
from services.run_review.operator_registry import is_operator_enabled
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
_DEFECT_SEVERITIES = {
    defect.defect_id: defect.severity for defect in UNIVERSAL_DEFECTS
}
# Frame-reference tolerance for the anti-hallucination bounds check: a
# verdict citing a timestamp further than this from every evidence frame
# is describing footage the VLM never saw.
_FRAME_REF_TOLERANCE_MS = 500
_MAX_FOCUSED_FRAMES = 6

# Strong references to in-flight review tasks: the event loop only keeps
# weak references, so an unreferenced task could be garbage-collected in
# the middle of a multi-second gates/VLM round.
_ACTIVE_REVIEW_TASKS: dict[str, set["asyncio.Task[Any]"]] = {}
# Registered synchronously at scheduling time, before the detached coroutine
# gets its first event-loop turn. The unattended scheduler uses these slots as
# a short-lived dependency fence so it cannot spend on downstream media that
# this review may replace a few seconds later.
_ACTIVE_REVIEW_SLOTS: dict[str, dict[str, int]] = {}
# Publication reserves a slot before the Project commit becomes visible.
# The token is transferred to ``schedule_media_review`` after commit; this
# closes the commit-listener race where downstream R2V/compose could wake in
# the few milliseconds before the detached review was registered.
_REVIEW_RESERVATIONS: dict[str, tuple[str, str]] = {}
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


def _increment_active_slot(project_id: str, slot_id: str) -> None:
    project_slots = _ACTIVE_REVIEW_SLOTS.setdefault(project_id, {})
    project_slots[slot_id] = project_slots.get(slot_id, 0) + 1


def _decrement_active_slot(project_id: str, slot_id: str) -> None:
    project_slots = _ACTIVE_REVIEW_SLOTS.get(project_id)
    if project_slots is None:
        return
    remaining = project_slots.get(slot_id, 0) - 1
    if remaining > 0:
        project_slots[slot_id] = remaining
    else:
        project_slots.pop(slot_id, None)
    if not project_slots:
        _ACTIVE_REVIEW_SLOTS.pop(project_id, None)


def reserve_media_review(
    services: "CreatorFileServices",
    *,
    project_id: str,
    published_result: Mapping[str, Any],
) -> str | None:
    """Reserve the selected artifact slot before publishing its commit."""

    del services  # kept in the signature to mirror the scheduling boundary
    try:
        from models.config import is_media_review_enabled

        if not is_media_review_enabled():
            return None
        if (
            str(published_result.get("commandType") or "")
            not in REVIEWED_COMMANDS
        ):
            return None
        artifact = published_result.get("artifactVersion")
        if not isinstance(artifact, Mapping):
            return None
        slot_id = str(artifact.get("slot_id") or "")
        if not slot_id:
            return None
        token = f"media-review-reservation-{uuid4().hex}"
        _REVIEW_RESERVATIONS[token] = (project_id, slot_id)
        _increment_active_slot(project_id, slot_id)
        return token
    except Exception:
        logger.exception("media review reservation failed")
        return None


def release_media_review_reservation(token: str | None) -> None:
    """Release a reservation whose publication did not converge."""

    if not token:
        return
    reserved = _REVIEW_RESERVATIONS.pop(token, None)
    if reserved is not None:
        _decrement_active_slot(*reserved)


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
        settings = getattr(project, "settings", None)
        aspect_ratio = getattr(settings, "aspect_ratio", None)
        if aspect_ratio:
            # Declared frame shape feeds the machine-parameter check.
            context["aspect_ratio"] = aspect_ratio
        target_ref = context["target_ref"]
        shots: list[dict[str, Any]] = []
        planned_texts: list[str] = []
        for timeline in project.timelines.items.values():
            for element in timeline.elements_by_id.values():
                creation = element.creation
                if getattr(creation, "type", None) == "overlay":
                    text = str(getattr(creation, "text", "") or "").strip()
                    if text:
                        # Overlay strings are burned into the frame, so
                        # they are what the OCR check compares against.
                        planned_texts.append(text)
                if element.element_id not in target_ref:
                    continue
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
        if planned_texts:
            context["planned_texts"] = planned_texts[:12]
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


def _parse_probes(
    raw: Any,
    *,
    expected_ids: Mapping[str, str],
    valid_timestamps: list[int] | None,
) -> list[ProbeFinding]:
    """Normalize one ET/CT/NA probe array with anti-hallucination checks.

    ``expected_ids`` maps probe id -> default severity. An NA without a
    reason and a CT whose evidence timestamp is missing or out of the
    evidence-frame set are kept but flagged ``needs_review`` — reported
    for transparency, never counted toward the verdict (APE rule: do
    not hard-flip a suspect verdict, flag it).
    """
    probes: list[ProbeFinding] = []
    if not isinstance(raw, list):
        return probes
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        probe_id = str(item.get("probe_id") or "")
        if probe_id not in expected_ids or probe_id in seen:
            continue
        seen.add(probe_id)
        verdict = str(item.get("verdict") or "").strip().upper()
        if verdict not in ("ET", "CT", "NA"):
            continue
        timestamp = item.get("evidence_timestamp_ms")
        if not isinstance(timestamp, int) or timestamp < 0:
            timestamp = None
        reason = str(item.get("reason") or "").strip()
        suggestion = str(item.get("suggestion") or "").strip()
        needs_review = False
        if verdict == "NA" and not reason:
            # Anti-hallucination: an NA must explain itself.
            needs_review = True
        if verdict == "CT":
            if not reason or not suggestion:
                # A timestamp alone is not actionable evidence. Both the
                # observation and a concrete remediation are required before
                # a model verdict may influence automatic regeneration.
                needs_review = True
            if timestamp is None:
                needs_review = True
            elif valid_timestamps is not None and not any(
                abs(timestamp - valid) <= _FRAME_REF_TOLERANCE_MS
                for valid in valid_timestamps
            ):
                # The verdict cites a frame the VLM was never shown.
                needs_review = True
        probes.append(
            ProbeFinding(
                probe_id=probe_id,
                verdict=verdict,  # type: ignore[arg-type]
                severity=expected_ids[probe_id],  # type: ignore[arg-type]
                evidence_timestamp_ms=timestamp,
                reason=reason,
                suggestion=suggestion,
                needs_review=needs_review,
            ),
        )
    return probes


def parse_media_report(
    text: str,
    *,
    kind: str,
    artifact_ref: str,
    round_number: int,
    gate_block: Mapping[str, Any] | None,
    stats: Mapping[str, Any] | None,
    expected_defects: Mapping[str, str] | None = None,
    expected_faith: Mapping[str, str] | None = None,
    valid_timestamps: list[int] | None = None,
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
    defect_findings = _parse_probes(
        payload.get("defect_findings"),
        expected_ids=dict(expected_defects or {}),
        valid_timestamps=valid_timestamps,
    )
    faithfulness_findings = _parse_probes(
        payload.get("faithfulness_findings"),
        expected_ids=dict(expected_faith or {}),
        valid_timestamps=valid_timestamps,
    )
    has_major = any(
        not item.passed and item.severity == "major" for item in findings
    ) or any(
        probe.verdict == "CT"
        and probe.severity == "major"
        and not probe.needs_review
        for probe in (*defect_findings, *faithfulness_findings)
    )
    return MediaReviewReport(
        artifact_ref=artifact_ref,
        kind=kind,  # type: ignore[arg-type]
        round=round_number,
        gate_block=dict(gate_block) if gate_block else None,
        stats=dict(stats) if stats else None,
        findings=findings,
        defect_findings=defect_findings,
        faithfulness_findings=faithfulness_findings,
        verdict="revise" if has_major else "pass",
        created_at=datetime.now(UTC),
    )


async def _to_thread_or_join(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Run ``fn`` in a worker thread; cancellation waits for a live worker.

    ``asyncio.to_thread`` detaches on cancellation: the awaiting task stops
    but the thread keeps decoding media or writing frames. A running thread
    cannot be interrupted, so the honest contract is to join it — the caller
    only regains control (and releases claims or frame directories) once the
    worker has actually finished.
    """
    loop = asyncio.get_running_loop()
    inner = loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
    try:
        return await asyncio.shield(inner)
    except asyncio.CancelledError:
        with contextlib.suppress(BaseException):
            await inner
        raise


async def _gather_or_cancel(*awaitables: Any) -> list[Any]:
    """gather() that stops the remaining legs when one raises.

    Plain ``asyncio.gather`` leaves siblings running after the first
    failure. Async legs (for example a paid ASR call) are cancelled;
    thread legs submitted via :func:`_to_thread_or_join` cannot be
    interrupted and are joined instead, so no decode/ffmpeg worker is
    still running when the error propagates to the caller.
    """
    tasks = [asyncio.ensure_future(item) for item in awaitables]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _video_objective_facts(
    media_path: Path,
    plan_context: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Tier-0 objective facts for one element video (fail-open)."""
    try:
        shots = plan_context.get("planned_shots") or []
        planned_duration = sum(
            float(shot.get("duration_seconds") or 0.0)
            for shot in shots
            if isinstance(shot, Mapping)
        )
        # The transcript only feeds ASR-backed facts, which need at least
        # one cut to measure against; a single-shot element (the common
        # case) would burn the ASR call for a "nothing to compare" note.
        transcript = None
        predecoded_gray_samples = None
        if is_operator_enabled("av_sync"):
            multi_shot = len(shots) >= 2
            if not multi_shot:
                predecoded_gray_samples, multi_shot = await _to_thread_or_join(
                    _gray_samples_and_has_cuts,
                    media_path,
                )
            if multi_shot:
                transcript = await transcript_sentences(media_path)
        return await _to_thread_or_join(
            collect_video_facts,
            media_path,
            expected_duration_seconds=planned_duration or None,
            expected_aspect=plan_context.get("aspect_ratio"),
            expected_texts=plan_context.get("planned_texts"),
            planned_shot_count=len(shots) or None,
            transcript_sentences=transcript,
            predecoded_gray_samples=predecoded_gray_samples,
        )
    except Exception:  # noqa: BLE001 - facts are advisory-only
        logger.exception("objective facts collection failed")
        return None


def _gray_samples_and_has_cuts(media_path: Path):
    """Decode once and return both reusable samples and the cut decision."""
    try:
        from services.run_review.objective import video_index as index_ops
        from services.run_review.objective.media_io import sample_gray_frames

        samples = sample_gray_frames(media_path)
        index = index_ops.build_video_index(samples)
        return samples, int(index.get("cut_count") or 0) > 0
    except Exception:  # noqa: BLE001 - unknown means "do not spend ASR"
        logger.warning("cut pre-check failed for %s", media_path)
        return None, False


def _has_cuts(media_path: Path) -> bool:
    """Compatibility wrapper for callers that only need the decision."""
    _, has_cuts = _gray_samples_and_has_cuts(media_path)
    return has_cuts


async def _image_objective_facts(
    media_path: Path,
) -> dict[str, Any] | None:
    """Tier-0 objective facts for one still image (fail-open)."""
    try:
        return await _to_thread_or_join(collect_image_facts, media_path)
    except Exception:  # noqa: BLE001 - facts are advisory-only
        logger.exception("image objective facts failed")
        return None


def _focused_frame_targets(
    objective_facts: Mapping[str, Any] | None,
) -> list[tuple[int, str]]:
    """Program-located timestamps worth a zoomed-in look (stage one of
    the two-stage judge): freeze suspicion midpoint, the first suspect
    consistency pair, and a dense trio inside the longest shot so motion
    trends are visible (sparse uniform sampling cannot show a push/pan).
    """
    if not objective_facts:
        return []
    targets: list[tuple[int, str]] = []
    index = objective_facts.get("video_index") or {}
    if isinstance(index, Mapping):
        freezes = index.get("freeze_segments") or []
        if freezes and isinstance(freezes[0], Mapping):
            segment = freezes[0]
            midpoint = (
                int(segment.get("start_ms") or 0)
                + int(segment.get("end_ms") or 0)
            ) // 2
            targets.append((midpoint, "冻结嫌疑段中点"))
    consistency = objective_facts.get("cross_shot_consistency") or {}
    if isinstance(consistency, Mapping):
        for pair in (consistency.get("suspect_pairs") or [])[:1]:
            if isinstance(pair, Mapping):
                targets.append(
                    (int(pair.get("frame_a_ms") or 0), "主体一致嫌疑帧A"),
                )
                targets.append(
                    (int(pair.get("frame_b_ms") or 0), "主体一致嫌疑帧B"),
                )
    if isinstance(index, Mapping):
        scenes = index.get("scenes") or []
        spans = [
            scene
            for scene in scenes
            if isinstance(scene, Mapping)
            and int(scene.get("end_ms") or 0) - int(scene.get("start_ms") or 0)
            > 1000
        ]
        if spans:
            longest = max(
                spans,
                key=lambda scene: int(scene["end_ms"])
                - int(scene["start_ms"]),
            )
            start = int(longest["start_ms"])
            span = int(longest["end_ms"]) - start
            for fraction in (0.3, 0.5, 0.7):
                targets.append(
                    (start + int(span * fraction), "最长镜头运镜观察"),
                )
    return targets


def _extract_focused_frames(
    media_path: Path,
    targets: list[tuple[int, str]],
    frames_dir: Path,
    existing_ts: list[int],
) -> list[dict[str, Any]]:
    """Materialize focused frames as JPEGs; dedupe against uniform ones."""
    if not targets:
        return []
    try:
        from services.runtime_files.runtime_dependencies import (
            resolve_ffmpeg,
        )
        from vendor.media_toolkit.video_read import (
            extract_frames_by_seeking,
        )

        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            return []
        picked: list[tuple[int, str]] = []
        taken = list(existing_ts)
        for timestamp, label in targets:
            if any(abs(timestamp - other) <= 400 for other in taken):
                continue
            picked.append((timestamp, label))
            taken.append(timestamp)
            if len(picked) >= _MAX_FOCUSED_FRAMES:
                break
        if not picked:
            return []
        # Focused frames ride the same token budget as the uniform ones;
        # sending them at source resolution would blow the prompt up by
        # up to six full-size JPEGs.
        from services.runtime_files.media_probe import probe_media
        from vendor.media_toolkit.image_budget import (
            VIDEO_BUDGET_TOKENS,
            VIDEO_MIN_PIXELS,
            budget_to_pixels,
            smart_resize,
        )

        probe = probe_media(str(media_path))
        target_h, target_w = smart_resize(
            probe.height or 720,
            probe.width or 1280,
            VIDEO_MIN_PIXELS,
            budget_to_pixels("normal", VIDEO_BUDGET_TOKENS),
        )
        extracted = extract_frames_by_seeking(
            ffmpeg,
            str(media_path),
            [timestamp / 1000.0 for timestamp, _ in picked],
            target_h=target_h,
            target_w=target_w,
        )
        frames_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        by_second = {
            round(timestamp / 1000.0, 1): (timestamp, label)
            for timestamp, label in picked
        }
        for seconds, payload in extracted:
            match = by_second.get(seconds)
            if match is None:
                continue
            timestamp, label = match
            path = frames_dir / f"focused-{timestamp}.jpg"
            path.write_bytes(payload)
            results.append(
                {
                    "timestamp_ms": timestamp,
                    "image_path": str(path),
                    "label": label,
                },
            )
        return results
    except Exception:  # noqa: BLE001 - focused frames are best-effort
        logger.exception("focused frame extraction failed")
        return []


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
    # pylint: disable=too-many-branches,too-many-statements
    gate_block: dict[str, Any] | None = None
    stats: dict[str, Any] = {}
    objective_facts: dict[str, Any] | None = None
    probe_sections: list[str] = []
    expected_defects: dict[str, str] = {}
    expected_faith: dict[str, str] = {}
    valid_timestamps: list[int] | None = None
    if kind == "element_video":
        # Gates, frame stats, evidence frames and the objective facts are
        # four independent passes over the same file; the focused frames
        # below are the only step that needs their results. A failing leg
        # cancels the async facts pass (so a paid ASR call cannot outlive
        # the round) and joins the decode threads before the error
        # propagates, so no worker still reads this media or writes
        # frames_dir after this call returns.
        block, sampled, frames, objective_facts = await _gather_or_cancel(
            _to_thread_or_join(review_gates.run_review_gates, media_path),
            _to_thread_or_join(frame_stats.sample_stats, media_path),
            _to_thread_or_join(
                extract_review_frames,
                media_path,
                max_frames=_VIDEO_REVIEW_FRAMES,
                output_dir=frames_dir,
            ),
            _video_objective_facts(media_path, plan_context),
        )
        gate_block = block.to_dict()
        stats = {**sampled, "judgment": frame_stats.judge_stats(sampled)}
        focused = (
            await asyncio.to_thread(
                _extract_focused_frames,
                media_path,
                _focused_frame_targets(objective_facts),
                frames_dir,
                [frame.timestamp_ms for frame in frames],
            )
            if is_operator_enabled("focused_frames")
            else []
        )
        planned_shots = plan_context.get("planned_shots") or []
        index_facts = (objective_facts or {}).get("video_index") or {}
        multi_shot = len(planned_shots) >= 2 or bool(
            isinstance(index_facts, Mapping)
            and int(index_facts.get("cut_count") or 0) >= 1,
        )
        if is_operator_enabled("defect_bank"):
            probe_sections.append(
                build_defect_question_block(multi_shot_expected=multi_shot),
            )
            expected_defects = dict(_DEFECT_SEVERITIES)
            hints = program_defect_hints(objective_facts)
            if hints:
                probe_sections.append(hints)
        faith_elements = (
            build_faithfulness_elements(
                plan_context,
                objective_facts=objective_facts,
            )
            if is_operator_enabled("faithfulness")
            else []
        )
        if faith_elements:
            probe_sections.append(build_faithfulness_block(faith_elements))
            # Graded like the defect bank: a wrong/missing subject or a
            # scrambled shot order breaks the shot (major), while tone,
            # framing and camera-move drift are notes (minor) that never
            # force a regeneration on their own.
            expected_faith = {
                element["key"]: FAITHFULNESS_SEVERITIES.get(
                    element["key"],
                    "minor",
                )
                for element in faith_elements
            }
        system_prompt = build_scene_check_system_prompt(
            include_probes=bool(expected_defects or expected_faith),
        )
        frame_lines = "\n".join(
            f"- 第 {index + 1} 张图 = t={frame.timestamp_ms}ms"
            for index, frame in enumerate(frames)
        )
        if focused:
            frame_lines += "\n" + "\n".join(
                f"- 第 {len(frames) + index + 1} 张图 ="
                f" t={item['timestamp_ms']}ms"
                f"（聚焦帧：{item['label']}）"
                for index, item in enumerate(focused)
            )
        image_paths = [frame.image_path for frame in frames] + [
            item["image_path"] for item in focused
        ]
        valid_timestamps = [frame.timestamp_ms for frame in frames] + [
            item["timestamp_ms"] for item in focused
        ]
    else:
        sampled, objective_facts = await _gather_or_cancel(
            _to_thread_or_join(frame_stats.image_stats, media_path),
            _image_objective_facts(media_path),
        )
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
    facts_lines = ""
    if objective_facts:
        stats = {**stats, "objective_facts": objective_facts}
        facts_lines = "\n\n" + render_facts_block(objective_facts)
    probe_lines = ""
    if probe_sections:
        probe_lines = "\n\n" + "\n\n".join(probe_sections)
    user_text = (
        "请按检查协议审阅这个生成产物。\n\n"
        + "【计划上下文】\n"
        + json.dumps(dict(plan_context), ensure_ascii=False)
        + "\n\n【画面统计（vendored frame stats）】\n"
        + json.dumps(
            {
                key: value
                for key, value in stats.items()
                if key != "objective_facts"
            },
            ensure_ascii=False,
        )
        + gate_lines
        + facts_lines
        + probe_lines
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
            # The probe checklists (16 bank questions + faithfulness
            # elements) add ~20 verdict objects to the response.
            # The probe run answers up to 16 defect + 5 faithfulness
            # questions on top of the six protocol rows; a truncated
            # reply is unparsable and both retries would resend the same
            # prompt, so the ceiling has to fit the whole array.
            max_tokens=4600 if probe_sections else 1800,
        )
        try:
            report = parse_media_report(
                response,
                kind=kind,
                artifact_ref=artifact_ref,
                round_number=round_number,
                gate_block=gate_block,
                stats=stats,
                expected_defects=expected_defects or None,
                expected_faith=expected_faith or None,
                valid_timestamps=valid_timestamps,
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
    reservation_token: str | None = None,
) -> None:
    """Detach an advisory review round for a published media artifact.

    Single idempotent scheduling point: every successful convergence path
    (fresh generation, idempotent replay, crash recovery) may call it; the
    review-side admission dedups already-reviewed versions.
    """
    # A reservation always names a non-empty slot, so the empty pair reads as
    # "nothing reserved" and keeps the release path free of optional unpacking.
    reserved_project, reserved_slot = (
        _REVIEW_RESERVATIONS.pop(reservation_token, ("", ""))
        if reservation_token
        else ("", "")
    )
    reservation_transferred = False
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
        slot_id = str(artifact.get("slot_id") or "")
        if reserved_slot and (reserved_project, reserved_slot) == (
            project_id,
            slot_id,
        ):
            # The active count was installed before Project publication.
            reservation_transferred = True
        else:
            if reserved_slot:
                _decrement_active_slot(reserved_project, reserved_slot)
                reserved_slot = ""
            if slot_id:
                _increment_active_slot(project_id, slot_id)

        def _log_outcome(done: asyncio.Task[Any]) -> None:
            project_tasks = _ACTIVE_REVIEW_TASKS.get(project_id)
            if project_tasks is not None:
                project_tasks.discard(done)
                if not project_tasks:
                    _ACTIVE_REVIEW_TASKS.pop(project_id, None)
            project_slots = _ACTIVE_REVIEW_SLOTS.get(project_id)
            if project_slots is not None and slot_id:
                _decrement_active_slot(project_id, slot_id)
            # A clean review changes no Project field, so the commit listener
            # has nothing to wake on. Re-evaluate the graph after every
            # terminal review; feedback-driven outcomes are harmlessly
            # deduplicated by the scheduler fingerprint.
            try:
                from services.file_agent_runtime.registry import (
                    get_creator_agent_runtime,
                )

                runtime = get_creator_agent_runtime()
                if (
                    runtime is not None
                    and runtime.services.root == services.root
                ):
                    runtime.work_scheduler.wake(project_id)
            except Exception:  # noqa: BLE001 - advisory wake is best-effort
                logger.exception("failed to wake scheduler after media review")
            if not done.cancelled() and done.exception() is not None:
                logger.error(
                    "media review task crashed: %s",
                    done.exception(),
                )

        task.add_done_callback(_log_outcome)
    except Exception:
        # Scheduling must never disturb the publishing path.
        logger.exception("media review scheduling failed")
    finally:
        if reserved_slot and not reservation_transferred:
            _decrement_active_slot(reserved_project, reserved_slot)


def cancel_project_media_reviews(project_id: str) -> None:
    """Synchronously signal all advisory review tasks for one Project."""

    for task in _ACTIVE_REVIEW_TASKS.pop(project_id, set()):
        task.cancel()
    for token, reserved in list(_REVIEW_RESERVATIONS.items()):
        if reserved[0] == project_id:
            _REVIEW_RESERVATIONS.pop(token, None)
    _ACTIVE_REVIEW_SLOTS.pop(project_id, None)


def active_media_review_slots(project_id: str) -> frozenset[str]:
    """Return slots whose selected artifact is still under async review."""

    return frozenset(_ACTIVE_REVIEW_SLOTS.get(project_id, {}))


__all__ = [
    "REVIEWED_COMMANDS",
    "active_media_review_slots",
    "parse_media_report",
    "cancel_project_media_reviews",
    "release_media_review_reservation",
    "reserve_media_review",
    "review_media_artifact",
    "run_media_review_loop",
    "schedule_media_review",
]
