# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Render self-review loop: frame evidence → VLM review → advisory feedback.

The loop is an adviser, never a gate: it runs detached after a final
composition is published, writes its reports under the Project's
``runtime/render-review/`` directory and, on a revise verdict, hands the
structured findings to the next AI editing director specialist run as a
turn user message (admitted through the durable session boundary). After
``MAX_REVIEW_ROUNDS`` the chain closes and delivery proceeds regardless of
the verdict, with the reports retained beside the render.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

from models.vlm_model import chat_completion, multimodal_media_part
from schemas.render_review import RenderReviewReport
from services.observability.tracing import trace_event
from services.render_review.frames import (
    RenderReviewError,
    extract_review_frames,
    probe_audio_profile,
)
from services.render_review.protocol import (
    MAX_REVIEW_ROUNDS,
    build_review_user_text,
    findings_feedback_payload,
    parse_review_report,
    review_system_prompt,
)
from services.runtime_files import (
    MessageChannel,
    MessageClassification,
    RequestAdmissionConflict,
    RuntimeSessionNotFound,
)
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.media_probe import probe_media
from utils.exceptions import ModelError
from utils.logger import setup_logger

if TYPE_CHECKING:
    from services.project_files.facade import CreatorFileServices

logger = setup_logger("creator.render_review")

_TRACE_COMPONENT = "render_review"
_VLM_ATTEMPTS = 2
_UNSAFE_REF_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
# Lease identity: claims are owned by one event loop of one process. A
# claim whose owner is gone (crashed process OR a shut-down loop whose
# cleanup callbacks never ran) is reclaimed immediately by the next
# schedule, independent of any asyncio cleanup having executed.
_PROCESS_TOKEN = uuid4().hex
_LOOP_TOKEN_ATTR = "_render_review_owner_token"
# A same-owner claim older than this is treated as hung and reclaimable.
_CLAIM_TTL_SECONDS = 30 * 60
# Bounded dedup history of already-reviewed artifact versions per chain file.
_REVIEWED_HISTORY_LIMIT = 50
# Audio source metadata that marks a narration/voiceover track. TTS assets
# record sourceKind=tts_generation; explicit role labels are honoured too.
_VOICEOVER_SOURCE_KINDS = frozenset({"tts_generation"})
_VOICEOVER_ROLES = frozenset({"voiceover", "narration", "dialogue"})


def _reports_root(services: "CreatorFileServices", project_id: str) -> Path:
    return (
        services.projects.project_root(project_id)
        / "runtime"
        / "render-review"
    )


def _chain_path(reports_root: Path, target_ref: str) -> Path:
    safe_ref = _UNSAFE_REF_CHARS.sub("-", target_ref).strip("-") or "target"
    return reports_root / f"chain-{safe_ref}.json"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f"{path.name}.tmp-{uuid4().hex[:8]}")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(staging, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _chain_lock(reports_root: Path, target_ref: str) -> CrossProcessFileLock:
    chain_path = _chain_path(reports_root, target_ref)
    chain_path.parent.mkdir(parents=True, exist_ok=True)
    return CrossProcessFileLock(
        chain_path.with_name(f"{chain_path.name}.lock"),
    )


def _owner_token() -> str:
    """Lease token for the current scheduling context.

    Bound to the running event loop (falling back to the bare process token
    in synchronous contexts): a claim written on a loop that has since shut
    down carries a token no future caller can present, so it is treated as
    abandoned even though the worker thread persisted it after every
    asyncio cleanup path was cancelled.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _PROCESS_TOKEN
    token = getattr(loop, _LOOP_TOKEN_ATTR, None)
    if not isinstance(token, str):
        token = f"{_PROCESS_TOKEN}-{uuid4().hex[:8]}"
        setattr(loop, _LOOP_TOKEN_ATTR, token)
    return token


def _claim_is_live(claim: Mapping[str, Any], *, owner: str) -> bool:
    """Whether an existing claim still belongs to a live review.

    A claim leased by another owner token (crashed process or a dead event
    loop) is a leftover: the loop that wrote it cannot complete anymore, so
    the next schedule reclaims it immediately instead of waiting for the
    TTL.
    """
    if str(claim.get("owner") or "") != owner:
        return False
    raw = str(claim.get("claimed_at") or "")
    try:
        claimed_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    age = (datetime.now(UTC) - claimed_at).total_seconds()
    return 0 <= age < _CLAIM_TTL_SECONDS


def _admit_round(
    reports_root: Path,
    *,
    target_ref: str,
    video_id: str,
    owner: str | None = None,
) -> tuple[int, str] | None:
    """Atomically claim the next round, or return ``None`` when not due.

    The claim is persisted before any review work starts so concurrent
    schedules cannot double-book a round; a claim for an older video is
    superseded by the newer composition, and the superseded loop drops its
    findings at finalization. ``owner`` is the caller's lease token (this
    function runs in a worker thread, so the scheduling loop resolves it).
    """
    owner = owner or _owner_token()
    chain_path = _chain_path(reports_root, target_ref)
    with _chain_lock(reports_root, target_ref):
        state = _read_json(chain_path) or {}
        reviewed = [
            str(item) for item in state.get("reviewed_video_ids") or []
        ]
        if video_id in reviewed or video_id == str(
            state.get("last_video_id") or "",
        ):
            return None
        claim = state.get("claim") or {}
        if claim.get("video_id") == video_id and _claim_is_live(
            claim,
            owner=owner,
        ):
            # The same video is already being reviewed (replayed schedule).
            return None
        if state.get("status") == "open":
            rounds_completed = int(state.get("rounds_completed") or 0)
            if rounds_completed >= MAX_REVIEW_ROUNDS:
                return None
            chain_id = (
                str(state.get("chain_id") or "") or f"chain-{uuid4().hex[:12]}"
            )
            round_number = rounds_completed + 1
        else:
            # Absent or closed chain: a fresh composition starts a new chain
            # while the reviewed-history dedup carries over.
            state = {}
            chain_id = f"chain-{uuid4().hex[:12]}"
            round_number = 1
        now = datetime.now(UTC).isoformat()
        state.update(
            {
                "chain_id": chain_id,
                "target_ref": target_ref,
                "rounds_completed": int(state.get("rounds_completed") or 0),
                "status": "open",
                "reviewed_video_ids": reviewed,
                "claim": {
                    "video_id": video_id,
                    "round": round_number,
                    "owner": owner,
                    "claimed_at": now,
                },
                "updated_at": now,
            },
        )
        _write_json(chain_path, state)
    return round_number, chain_id


def _release_claim(
    reports_root: Path,
    *,
    target_ref: str,
    video_id: str,
    owner: str | None = None,
) -> None:
    """Best-effort claim release after a failed review round.

    Only the matching claim is cleared: a claim for a different video or a
    different owner belongs to another (possibly newer) review.
    """
    owner = owner or _owner_token()
    chain_path = _chain_path(reports_root, target_ref)
    try:
        with _chain_lock(reports_root, target_ref):
            state = _read_json(chain_path) or {}
            claim = state.get("claim") or {}
            if (
                claim.get("video_id") != video_id
                or str(claim.get("owner") or "") != owner
            ):
                return
            state["claim"] = None
            state["updated_at"] = datetime.now(UTC).isoformat()
            _write_json(chain_path, state)
    except Exception:
        logger.exception("failed to release render review claim")


def _selected_slot_version(
    services: "CreatorFileServices",
    project_id: str,
    *,
    video_id: str,
    slot_id: str | None,
) -> str | None:
    """Return the currently selected ArtifactVersion of the render slot."""
    snapshot = services.projects.read(project_id)
    slots = snapshot.project.assets.artifact_slots_by_id
    slot = None
    if slot_id:
        slot = slots.get(slot_id)
    if slot is None:
        slot = next(
            (item for item in slots.values() if video_id in item.version_ids),
            None,
        )
    return slot.selected_version_id if slot is not None else None


def _finalize_round(
    services: "CreatorFileServices",
    reports_root: Path,
    *,
    project_id: str,
    target_ref: str,
    chain_id: str,
    round_number: int,
    video_id: str,
    slot_id: str | None,
    report: RenderReviewReport,
    owner: str | None = None,
) -> tuple[str, bool]:
    """Re-validate freshness and admit feedback atomically.

    Returns ``(outcome, feedback_sent)`` where outcome is ``completed``,
    ``superseded`` (a newer composition claimed the chain while the VLM ran),
    ``stale`` (the reviewed video is no longer the selected artifact) or
    ``unverified`` (freshness could not be proven). The final selection
    check runs as an admission guard inside the session store's Project
    lifecycle boundary — the same boundary every composition commit takes —
    so the selected version cannot change between the check and the durable
    feedback write. Feedback is fail-closed: no proof of freshness means no
    mutation instruction. Non-``completed`` findings keep their report but
    never mutate the current timeline and never consume a chain round.
    """
    chain_path = _chain_path(reports_root, target_ref)
    owner = owner or _owner_token()
    with _chain_lock(reports_root, target_ref):
        state = _read_json(chain_path) or {}
        claim = state.get("claim") or {}
        now = datetime.now(UTC).isoformat()
        reviewed = [
            str(item) for item in state.get("reviewed_video_ids") or []
        ]
        if video_id not in reviewed:
            reviewed.append(video_id)
        reviewed = reviewed[-_REVIEWED_HISTORY_LIMIT:]
        if (
            claim.get("video_id") != video_id
            or str(claim.get("owner") or "") != owner
        ):
            state["reviewed_video_ids"] = reviewed
            state["updated_at"] = now
            _write_json(chain_path, state)
            return "superseded", False
        needs_feedback = (
            report.verdict == "revise" and round_number < MAX_REVIEW_ROUNDS
        )
        outcome = "completed"
        feedback_sent = False
        if needs_feedback:

            def _resolve_selected() -> str | None:
                # Fail closed: an unreadable Project or a missing slot is no
                # proof of freshness, so no mutation instruction goes out.
                try:
                    return _selected_slot_version(
                        services,
                        project_id,
                        video_id=video_id,
                        slot_id=slot_id,
                    )
                except Exception:
                    logger.exception(
                        "failed to resolve selected artifact version",
                    )
                    return None

            selected = _resolve_selected()
            if selected is None:
                outcome = "unverified"
            elif selected != video_id:
                outcome = "stale"
            else:
                try:
                    feedback_sent = _admit_feedback(
                        services,
                        project_id=project_id,
                        report=report,
                        target_ref=target_ref,
                        chain_id=chain_id,
                        freshness_guard=(
                            lambda: _resolve_selected() == video_id
                        ),
                    )
                except RequestAdmissionConflict:
                    # A concurrent compose switched the selected render
                    # between the pre-check and the durable write.
                    outcome = "stale"
        if outcome != "completed":
            state.update(
                {
                    "claim": None,
                    "reviewed_video_ids": reviewed,
                    "updated_at": now,
                },
            )
            _write_json(chain_path, state)
            return outcome, False
        keep_open = needs_feedback
        state.update(
            {
                "chain_id": chain_id,
                "target_ref": target_ref,
                "rounds_completed": round_number,
                "status": "open" if keep_open else "closed",
                "last_video_id": video_id,
                "last_verdict": report.verdict,
                "reviewed_video_ids": reviewed,
                "claim": None,
                "updated_at": now,
            },
        )
        _write_json(chain_path, state)
        return "completed", feedback_sent


def _is_voiceover_audio(project: Any, creation: Any) -> bool:
    """Whether an audio element is a narration track, by source authority.

    ``AudioCreation`` has no role semantics (BGM and SFX use the same
    shape), so narration is recognized from the referenced source version:
    TTS-generated assets carry ``metadata.sourceKind="tts_generation"`` and
    explicit role labels are honoured. Plain music beds never count.
    """
    version_id = str(getattr(creation, "source_asset_version_id", "") or "")
    if not version_id:
        return False
    sources = getattr(
        getattr(project, "assets", None),
        "source_versions_by_id",
        None,
    )
    source = (sources or {}).get(version_id)
    if source is None:
        return False
    metadata = getattr(source, "metadata", None) or {}
    if str(metadata.get("sourceKind") or "") in _VOICEOVER_SOURCE_KINDS:
        return True
    role = str(
        metadata.get("audioRole") or metadata.get("role") or "",
    ).casefold()
    return role in _VOICEOVER_ROLES


def derive_plan_context(project: Any, target_ref: str) -> dict[str, Any]:
    """Derive the review plan context from authoritative Project data.

    ``expects_voiceover`` and ``expects_subtitles`` come from the actual
    timeline plan (narration-role audio elements / text overlays), never
    from annotations, so the live compose path and the eval harness share
    one context source. ``project_brief`` carries the user's stated goal so
    the reviewer can flag a delivery that silently dropped a requested
    narration track.
    """
    context: dict[str, Any] = {"timeline_ref": target_ref}
    settings = getattr(project, "settings", None)
    if settings is not None:
        context["content_type"] = getattr(settings, "content_type", None)
        context["target_duration_seconds"] = getattr(
            settings,
            "target_duration_seconds",
            None,
        )
    brief = str(getattr(project, "description", "") or "").strip()
    if brief:
        context["project_brief"] = brief[:300]
    timelines = getattr(getattr(project, "timelines", None), "items", None)
    timelines = timelines or {}
    # Canonical Timeline IDs already carry the ``timeline:`` prefix, so both
    # ``timeline:timeline:main`` and the bare ``timeline:main`` resolve
    # (mirrors local_execution._target_timeline).
    stripped = target_ref.partition(":")[2] or target_ref
    timeline = timelines.get(stripped) or timelines.get(target_ref)
    expects_voiceover = False
    expects_subtitles = False
    if timeline is not None:
        for element in timeline.elements_by_id.values():
            if not getattr(element, "enabled", True):
                continue
            creation = getattr(element, "creation", None)
            kind = getattr(creation, "type", None)
            if kind == "audio":
                if _is_voiceover_audio(project, creation):
                    expects_voiceover = True
            elif kind == "overlay":
                overlay_kind = getattr(creation, "overlay_kind", "")
                text = str(getattr(creation, "text", "") or "").strip()
                if overlay_kind in ("pet_os", "interview_summary") and text:
                    expects_subtitles = True
    context["expects_voiceover"] = expects_voiceover
    context["expects_subtitles"] = expects_subtitles
    return context


def _plan_context(
    services: "CreatorFileServices",
    project_id: str,
    target_ref: str,
) -> dict[str, Any]:
    try:
        snapshot = services.projects.read(project_id)
    except Exception:
        return {"timeline_ref": target_ref}
    return derive_plan_context(snapshot.project, target_ref)


async def review_render(
    services: "CreatorFileServices",
    *,
    project_id: str,
    video_path: Path,
    video_id: str,
    round_number: int = 1,
    plan_context: Mapping[str, Any] | None = None,
) -> RenderReviewReport:
    """Run one review round and persist the report beside the render."""
    reports_root = _reports_root(services, project_id)
    video_dir = reports_root / video_id
    frames = await asyncio.to_thread(
        extract_review_frames,
        video_path,
        output_dir=video_dir / f"frames-round-{round_number}",
    )
    audio_profile = await asyncio.to_thread(probe_audio_profile, video_path)
    probe = await asyncio.to_thread(probe_media, str(video_path))
    context = dict(plan_context or {})
    user_text = build_review_user_text(
        frames=frames,
        audio_profile=audio_profile,
        video_duration_seconds=probe.duration_seconds,
        plan_context=context,
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for frame in frames:
        content.append(
            multimodal_media_part(Path(frame.image_path).as_uri(), "image"),
        )
    video_ref = f"artifact-version:{video_id}"
    report: RenderReviewReport | None = None
    last_error: Exception | None = None
    for attempt in range(_VLM_ATTEMPTS):
        try:
            response_text = await chat_completion(
                content,
                system_prompt=review_system_prompt(),
                temperature=0.2,
                max_tokens=2400,
            )
        except ModelError as exc:
            # Transient provider/network failures get one more attempt;
            # the loop stays advisory either way.
            last_error = exc
            logger.warning(
                "render review VLM call failed (attempt %d): %s",
                attempt + 1,
                exc,
            )
            await asyncio.sleep(2 * (attempt + 1))
            continue
        try:
            report = parse_review_report(
                response_text,
                video_ref=video_ref,
                round_number=round_number,
            )
            break
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "render review response unparsable (attempt %d): %s",
                attempt + 1,
                exc,
            )
    if report is None:
        raise RenderReviewError(
            f"review response invalid after {_VLM_ATTEMPTS} attempts: {last_error}",
        )
    await asyncio.to_thread(
        _write_json,
        video_dir / f"round-{round_number}.json",
        report.model_dump(mode="json"),
    )
    trace_event(
        "render_review.report",
        component=_TRACE_COMPONENT,
        attributes={
            "videoRef": video_ref,
            "round": round_number,
            "verdict": report.verdict,
            "failedDimensions": [
                item.dimension.value for item in report.failed_findings()
            ],
            "frameCount": len(frames),
            "hasAudio": audio_profile.has_audio,
        },
        projectId=project_id,
    )
    return report


def _feedback_message_text(
    report: RenderReviewReport,
    *,
    target_ref: str,
) -> str:
    payload = findings_feedback_payload(report)
    return (
        f"【成片自我审阅反馈 · 第 {report.round}/{MAX_REVIEW_ROUNDS} 轮】\n"
        f"成片 {report.video_ref} 未通过自我审阅。请委派 ai_editing_director "
        f"修订 {target_ref}：仅修复下列结构化审阅发现中列出的问题，不要扩大改动"
        "范围，修订完成后重新合成成片。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _admit_feedback(
    services: "CreatorFileServices",
    *,
    project_id: str,
    report: RenderReviewReport,
    target_ref: str,
    chain_id: str,
    freshness_guard: Any = None,
) -> bool:
    """Admit the findings as a durable turn message for the next editing run.

    ``freshness_guard`` re-runs inside the session store's Project lifecycle
    boundary; a ``False`` result aborts with ``RequestAdmissionConflict`` so
    a concurrent compose can never be mutated by findings for a superseded
    render.
    """
    try:
        session = services.sessions.get_project_session_snapshot(project_id)
    except RuntimeSessionNotFound:
        logger.info(
            "render review feedback skipped: project %s has no runtime session",
            project_id,
        )
        return False
    conversations = services.sessions.list_conversations(
        project_id,
        session.session_id,
    )
    default = next(
        (item for item in conversations if item.is_default),
        conversations[0] if conversations else None,
    )
    if default is None:
        return False
    request_id = f"render-review-{chain_id}-round-{report.round}"
    services.sessions.admit_user_request(
        project_id,
        session.session_id,
        default.conversation_id,
        request_id=request_id,
        client_message_id=request_id,
        content_parts=[
            {
                "type": "text",
                "text": _feedback_message_text(report, target_ref=target_ref),
            },
        ],
        source="render_review_feedback",
        channel=MessageChannel.RUNTIME,
        classification=MessageClassification.MUTATION_INSTRUCTION,
        metadata={"renderReview": findings_feedback_payload(report)},
        admission_guard=freshness_guard,
    )
    return True


def _settle_cancelled_admission(
    admission: "asyncio.Task[tuple[int, str] | None] | None",
    admitted: tuple[int, str] | None,
    reports_root: Path,
    *,
    target_ref: str,
    video_id: str,
    owner: str,
) -> None:
    """Release whatever claim a cancelled loop may have persisted.

    ``asyncio.to_thread`` keeps running after the awaiting task is
    cancelled, so the admission worker can write a claim while ``admitted``
    is still ``None`` in the coroutine. The release therefore follows the
    worker's real outcome: immediately when known, via a done-callback
    otherwise. This is best-effort promptness only — during event-loop
    shutdown even the shielded task gets cancelled and the callback never
    learns the worker's result; correctness is then carried by the
    per-loop lease: the dead loop's claim token can never be presented
    again, so the next schedule reclaims the claim immediately.
    """
    if admitted is not None:
        _release_claim(
            reports_root,
            target_ref=target_ref,
            video_id=video_id,
            owner=owner,
        )
        return
    if admission is None:
        return

    def _cleanup(done: "asyncio.Future[tuple[int, str] | None]") -> None:
        try:
            if (
                not done.cancelled()
                and done.exception() is None
                and done.result() is not None
            ):
                _release_claim(
                    reports_root,
                    target_ref=target_ref,
                    video_id=video_id,
                    owner=owner,
                )
        except Exception:
            logger.exception(
                "failed to settle cancelled render review claim",
            )

    if admission.done():
        _cleanup(admission)
    else:
        admission.add_done_callback(_cleanup)


async def run_review_loop(
    services: "CreatorFileServices",
    *,
    project_id: str,
    video_path: Path,
    video_id: str,
    target_ref: str,
    slot_id: str | None = None,
) -> RenderReviewReport | None:
    """Run one advisory review round for a freshly published final render."""
    reports_root = _reports_root(services, project_id)
    # The lease token is bound to this event loop: if shutdown cancels
    # every task (including the shielded admission) and the worker still
    # persists a claim afterwards, no future scheduling context can carry
    # this token, so the claim is reclaimed on the next schedule.
    owner = _owner_token()
    admitted: tuple[int, str] | None = None
    admission: "asyncio.Task[tuple[int, str] | None] | None" = None
    try:
        # Shielded so a cancellation delivered mid-admission cannot orphan
        # a claim the worker thread already persisted; the cancel handler
        # settles the claim from the worker's real outcome.
        admission = asyncio.ensure_future(
            asyncio.to_thread(
                _admit_round,
                reports_root,
                target_ref=target_ref,
                video_id=video_id,
                owner=owner,
            ),
        )
        admitted = await asyncio.shield(admission)
        if admitted is None:
            trace_event(
                "render_review.skipped",
                component=_TRACE_COMPONENT,
                attributes={
                    "videoRef": f"artifact-version:{video_id}",
                    "reason": "already_reviewed_or_chain_spent",
                },
                projectId=project_id,
            )
            return None
        round_number, chain_id = admitted
        plan_context = await asyncio.to_thread(
            _plan_context,
            services,
            project_id,
            target_ref,
        )
        report = await review_render(
            services,
            project_id=project_id,
            video_path=video_path,
            video_id=video_id,
            round_number=round_number,
            plan_context=plan_context,
        )
        outcome, feedback_sent = await asyncio.to_thread(
            _finalize_round,
            services,
            reports_root,
            project_id=project_id,
            target_ref=target_ref,
            chain_id=chain_id,
            round_number=round_number,
            video_id=video_id,
            slot_id=slot_id,
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
            "render_review.round_completed",
            component=_TRACE_COMPONENT,
            attributes={
                "videoRef": report.video_ref,
                "round": round_number,
                "verdict": report.verdict,
                "outcome": outcome,
                "feedbackSent": feedback_sent,
            },
            projectId=project_id,
        )
        return report
    except asyncio.CancelledError:
        # Shutdown/cancellation must not leave a live-looking claim behind;
        # the per-loop lease covers process death and loop shutdown, this
        # covers ordinary task cancellation promptly.
        _settle_cancelled_admission(
            admission,
            admitted,
            reports_root,
            target_ref=target_ref,
            video_id=video_id,
            owner=owner,
        )
        raise
    except Exception as exc:
        # Advisory only: a review failure must never disturb delivery.
        logger.exception("render review loop failed for %s", video_id)
        if admitted is not None:
            await asyncio.to_thread(
                _release_claim,
                reports_root,
                target_ref=target_ref,
                video_id=video_id,
                owner=owner,
            )
        trace_event(
            "render_review.failed",
            component=_TRACE_COMPONENT,
            status="error",
            attributes={
                "videoRef": f"artifact-version:{video_id}",
                "errorType": type(exc).__name__,
                "error": str(exc)[:500],
            },
            projectId=project_id,
        )
        return None


def schedule_render_review(
    services: "CreatorFileServices",
    *,
    project_id: str,
    published_result: Mapping[str, Any],
) -> None:
    """Detach a review round for a successful COMPOSE_FINAL_VIDEO result.

    This is the single idempotent scheduling point: every successful
    convergence path (fresh render, idempotent replay, fingerprint reuse and
    crash recovery) may call it; the review-side round admission dedups
    already-reviewed and in-flight artifact versions.
    """
    try:
        from models.config import is_self_review_enabled

        if not is_self_review_enabled():
            return
        if str(published_result.get("commandType") or "") != (
            "COMPOSE_FINAL_VIDEO"
        ):
            return
        indexed = published_result.get("indexedFile")
        artifact = published_result.get("artifactVersion")
        if not isinstance(indexed, Mapping) or not isinstance(
            artifact,
            Mapping,
        ):
            return
        relative_uri = str(indexed.get("relative_uri") or "")
        video_id = str(artifact.get("version_id") or "")
        slot_id = str(artifact.get("slot_id") or "") or None
        target_ref = str(published_result.get("targetRef") or "")
        if not relative_uri or not video_id or not target_ref:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "render review scheduling skipped: no running event loop",
            )
            return
        video_path = services.projects.project_root(project_id) / relative_uri
        task = asyncio.create_task(
            run_review_loop(
                services,
                project_id=project_id,
                video_path=video_path,
                video_id=video_id,
                target_ref=target_ref,
                slot_id=slot_id,
            ),
        )

        def _log_outcome(done: asyncio.Task[Any]) -> None:
            if not done.cancelled() and done.exception() is not None:
                logger.error(
                    "render review task crashed: %s",
                    done.exception(),
                )

        task.add_done_callback(_log_outcome)
    except Exception:
        # Never let advisory scheduling break the compose result path.
        logger.exception(
            "failed to schedule render review for project %s",
            project_id,
        )


__all__ = [
    "derive_plan_context",
    "review_render",
    "run_review_loop",
    "schedule_render_review",
]
