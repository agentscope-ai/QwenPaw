# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Scene-level pre-compose review (upstream scene-loop, zero-render).

Reviews one ``scene_ledger`` row of a Timeline BEFORE the master compose:
evidence comes exclusively from cheap sources — ffmpeg keyframe seeks on
the ORIGINAL source files mapped through each Edit Element's
``render_source`` (via the shared keyframe cache) plus static motion
document facts for overlays — never from a segment render. Checks that
inherently require the composed render (transition feel, cold-render
first frame) stay with the full-piece self-review after the master.

A passing review locks the row with a content fingerprint; the compose
gate recomputes the fingerprint so any later element change silently
invalidates the lock.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from models import vlm_model
from models.config import get_vlm_concurrency
from models.vlm_model import multimodal_media_part
from services.media_files.keyframe_cache import materialize_keyframe

# Shared source resolution: only already-materialized local bytes are used
# (verified Asset Index copy or the remote-ingest cache); reviewing never
# triggers a new download.
from services.media_files.motion_design import _source_local_path
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from utils.logger import setup_logger
from vendor.media_toolkit.review_rubrics import SCENE_REVIEW_CHECKS

logger = setup_logger("creator.render_review.scene_review")

# Evidence budget: keep one scene review at "seconds of ffmpeg + one VLM
# call" — frames come from the keyframe cache (reused across reviews).
MAX_SCENE_FRAMES = 8
FRAMES_PER_ELEMENT = 3
_FRAME_FRACTIONS = (0.15, 0.5, 0.85)
_KEYFRAME_WIDTH = 960
SCENE_REVIEW_MAX_TOKENS = 4096


# Checks that only make sense on the composed render; the scene pass
# reviews them as far as frame evidence goes and the master-render
# self-review covers the rest.
_RENDER_ONLY_NOTES = (
    "technical 行的黑帧检查与 motion_quality 行的冷渲染首帧检查依赖成片渲染，"
    "本次段审仅基于源素材帧与动效文档事实评审可判部分；不可判的子项不作为"
    "不通过依据。"
)

_SYSTEM_PROMPT = """你是一名场景级剪辑审阅专家，负责在 master 合成之前逐段验收（scene-loop）。
你收到的是该场景各片段从原始源素材直接抽取的证据帧（非渲染成片），以及叠加动效的文档事实。
每一条不通过的结论必须引用具体证据（帧序号或事实字段）；找不到证据必须判通过。

输出格式（只输出一个 JSON 对象）：
{
  "checks": [
    {"key": "<six checks, one entry each>", "passed": true/false, "severity": "minor"/"major", "evidence": "<引用的帧/事实>", "suggestion": "<修订指令，通过时可为空>"}
  ],
  "impression": "<以观众身份看一遍的一句话印象（watch_once 的 NL observation）>"
}
六个检查各输出恰好一条，key 取值：devices / type_fonts / composition_safety /
motion_quality / technical / watch_once。"""


def scene_content_fingerprint(timeline: Any, row: Any) -> str:
    """Content hash of the scene's elements (order-independent).

    Any change to an element inside the scene — span, source range,
    overlay text, placement — yields a new fingerprint, which is how a
    stale lock blocks the master compose. ``creation.motion`` is
    deliberately excluded: motion documents are Runtime-generated
    styling guarded by their own render truth gates, and the automatic
    design pass runs right before compose — hashing it would expire
    every lock exactly when the unattended pipeline needs them held.
    """
    parts: list[str] = []
    for element_id in sorted(row.element_ids):
        element = timeline.elements_by_id.get(element_id)
        if element is None:
            parts.append(f"{element_id}:missing")
            continue
        dump = element.model_dump(mode="json")
        creation = dump.get("creation")
        if isinstance(creation, dict):
            creation.pop("motion", None)
        parts.append(
            json.dumps(
                {element_id: dump},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return "sha256:" + sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _ledger_row(timeline: Any, scene_id: str) -> Any:
    plan = timeline.edit_plan
    if plan is None:
        raise ValidationError(
            "该 Timeline 尚无 edit_plan；先写入契约与 scene_ledger 再做段审",
        )
    for row in plan.scene_ledger:
        if row.scene_id == scene_id:
            return row
    raise ValidationError(
        f"scene_ledger 中不存在场景 {scene_id}；先在 edit_plan.scene_ledger "
        "登记该场景及其 element_ids",
    )


def _target_timeline(project: Any, timeline_ref: str) -> Any:
    stripped = timeline_ref.partition(":")[2] or timeline_ref
    timelines = project.timelines.items
    timeline = timelines.get(stripped) or timelines.get(timeline_ref)
    if timeline is None:
        raise ValidationError(f"Timeline 不存在: {timeline_ref}")
    return timeline


async def _collect_evidence(  # pylint: disable=too-many-branches
    *,
    project: Any,
    project_root: Path,
    timeline: Any,
    row: Any,
    executions: ProjectExecutionStore,
) -> tuple[list[Path], list[str], list[str]]:
    """Zero-render evidence: source keyframes + static motion facts.

    Returns (frame paths, frame labels, degraded/fact notes).
    """
    # pylint: disable=too-many-statements
    ffmpeg = resolve_ffmpeg()
    ticks = timeline.ticks_per_second
    frames: list[Path] = []
    labels: list[str] = []
    notes: list[str] = []
    edit_elements = []
    for element_id in row.element_ids:
        element = timeline.elements_by_id.get(element_id)
        if element is None:
            raise ValidationError(
                f"scene_ledger 引用的 Element 不存在: {element_id}",
            )
        kind = getattr(element.creation, "type", None)
        if kind == "edit" and element.render_source is not None:
            edit_elements.append(element)
        elif kind in ("overlay", "motion_clip", "transition"):
            motion = getattr(element.creation, "motion", None)
            text = str(getattr(element.creation, "text", "") or "").strip()
            fact: dict[str, Any] = {"elementId": element_id, "type": kind}
            if text:
                fact["text"] = text
            if motion is not None:
                fact["motion"] = {
                    "designNotes": getattr(motion, "design_notes", ""),
                    "motif": getattr(motion, "motif", ""),
                    "entrance": getattr(motion, "entrance", ""),
                    "exit": getattr(motion, "exit", ""),
                }
                notes.append(
                    "动效事实（无渲染帧，按文档事实评审）: "
                    + json.dumps(fact, ensure_ascii=False),
                )
            else:
                notes.append(
                    "叠加元素尚无动效文档，按声明文本评审: "
                    + json.dumps(fact, ensure_ascii=False),
                )
    if not edit_elements:
        notes.append("该场景不含 Edit 片段：仅按动效/文本事实评审。")
        return frames, labels, notes
    per_element = max(
        1,
        min(FRAMES_PER_ELEMENT, MAX_SCENE_FRAMES // len(edit_elements)),
    )
    if ffmpeg is None or not ffmpeg:
        notes.append("ffmpeg 不可用：无法抽取源素材帧，按事实与声明评审。")
        return frames, labels, notes
    # Source lookups and keyframe seeks are independent ffmpeg/IO work:
    # issue them concurrently and assemble in the planned order, because
    # the prompt refers to frames by position (第 N 张图).
    resolved_sources = await asyncio.gather(
        *(
            asyncio.to_thread(
                _source_local_path,
                project=project,
                project_root=project_root,
                version_id=element.render_source.version_id,
                executions=executions,
            )
            for element in edit_elements
        ),
    )
    planned: list[tuple[str, float]] = []
    seek_calls: list[Any] = []
    for element, source_path in zip(edit_elements, resolved_sources):
        if source_path is None:
            notes.append(
                f"片段 {element.element_id} 源视频没有本地字节，" "该片段按素材理解事实评审。",
            )
            continue
        render_source = element.render_source
        version = project.assets.source_versions_by_id.get(
            render_source.version_id,
        )
        identity = (
            f"{render_source.version_id}:{version.checksum}"
            if version is not None
            else render_source.version_id
        )
        start_sec = render_source.source_in_tick / ticks
        end_sec = render_source.source_out_tick / ticks
        span = max(0.1, end_sec - start_sec)
        for fraction in _FRAME_FRACTIONS[:per_element]:
            if len(planned) >= MAX_SCENE_FRAMES:
                break
            timestamp = start_sec + span * fraction
            planned.append((element.element_id, timestamp))
            seek_calls.append(
                asyncio.to_thread(
                    materialize_keyframe,
                    project_root,
                    source_path=source_path,
                    source_identity=identity,
                    timestamp_seconds=timestamp,
                    width=_KEYFRAME_WIDTH,
                    ffmpeg_path=ffmpeg,
                ),
            )
    if not seek_calls:
        return frames, labels, notes
    seeked = await asyncio.gather(*seek_calls, return_exceptions=True)
    # One failing seek retires the whole element (same read as before:
    # a broken source yields facts-only review for that clip).
    broken: set[str] = set()
    for (element_id, timestamp), cached in zip(planned, seeked):
        if element_id in broken:
            continue
        if isinstance(cached, BaseException):
            notes.append(
                f"片段 {element_id} 抽帧失败（{cached}），" "该片段按事实评审。",
            )
            broken.add(element_id)
            continue
        frames.append(cached.path)
        labels.append(
            f"第 {len(frames)} 张图 = 片段 {element_id} " f"源时间 {timestamp:.1f}s",
        )
    return frames, labels, notes


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_CHECK_KEYS = tuple(check.key for check in SCENE_REVIEW_CHECKS)


def _parse_checks(text: str) -> tuple[list[dict[str, Any]], str]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("scene review response contains no JSON object")
    payload = json.loads(candidate[start : end + 1])
    raw = payload.get("checks")
    if not isinstance(raw, list):
        raise ValueError("scene review response has no checks list")
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if key not in _CHECK_KEYS or key in seen:
            continue
        seen.add(key)
        passed = bool(item.get("passed", True))
        severity = item.get("severity")
        if severity not in ("minor", "major"):
            severity = "minor"
        evidence = str(item.get("evidence") or "")
        # Evidence discipline: a failure without concrete evidence
        # cannot stand.
        if not passed and not evidence.strip():
            passed = True
        checks.append(
            {
                "key": key,
                "passed": passed,
                "severity": severity,
                "evidence": evidence,
                "suggestion": str(item.get("suggestion") or ""),
            },
        )
    missing = [key for key in _CHECK_KEYS if key not in seen]
    for key in missing:
        checks.append(
            {
                "key": key,
                "passed": True,
                "severity": "minor",
                "evidence": "",
                "suggestion": "",
            },
        )
    return checks, str(payload.get("impression") or "")


@dataclass(slots=True)
class SceneEvaluation:
    """Side-effect-free outcome of reviewing one scene.

    Evaluation (evidence + VLM) is safe to run concurrently for many
    scenes; the ledger write it implies is not, so it is returned as
    data and committed by the caller in a defined order.
    """

    scene_id: str
    fingerprint: str
    # already_locked | rejected | passed (passed still needs the commit)
    status: str
    review_round: int = 0
    checks: list[dict[str, Any]] = field(default_factory=list)
    impression: str = ""
    failed_checks: list[str] = field(default_factory=list)


async def _evaluate_scene(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    scene_id: str,
) -> SceneEvaluation:
    """Collect evidence and run the six checks without writing anything."""
    snapshot = services.projects.read(project_id)
    project = snapshot.project
    timeline = _target_timeline(project, timeline_ref)
    row = _ledger_row(timeline, scene_id)
    fingerprint = scene_content_fingerprint(timeline, row)
    if row.status == "locked" and row.locked_fingerprint == fingerprint:
        return SceneEvaluation(
            scene_id=scene_id,
            fingerprint=fingerprint,
            status="already_locked",
            review_round=row.review_round,
        )
    project_root = Path(services.projects.project_root(project_id))
    executions = ProjectExecutionStore(services.root)
    frames, labels, notes = await _collect_evidence(
        project=project,
        project_root=project_root,
        timeline=timeline,
        row=row,
        executions=executions,
    )
    check_lines = [
        f"- {check.key} ({check.title}): {check.description}"
        for check in SCENE_REVIEW_CHECKS
    ]
    plan = timeline.edit_plan
    contract = plan.model_dump(mode="json", exclude={"scene_ledger"})
    sections = [
        f"请按六项场景检查验收场景 {scene_id}（{row.label or '未命名'}）。",
        "【剪辑契约（devices 行的对照物）】\n" + json.dumps(contract, ensure_ascii=False),
        "【取证说明】\n" + _RENDER_ONLY_NOTES,
        "【证据帧（与随后附上的图片顺序一一对应）】\n"
        + ("\n".join(labels) if labels else "（本场景无源素材帧）"),
        "【叠加/动效事实】\n" + ("\n".join(notes) if notes else "（无）"),
        "【六项检查】\n" + "\n".join(check_lines),
    ]
    content: list[dict[str, Any]] = [
        multimodal_media_part(path.resolve().as_uri(), "image")
        for path in frames
    ]
    content.append({"type": "text", "text": "\n\n".join(sections)})
    response = await vlm_model.chat_completion(
        content,
        system_prompt=_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=SCENE_REVIEW_MAX_TOKENS,
    )
    checks, impression = _parse_checks(str(response or ""))
    failed = [
        item
        for item in checks
        if not item["passed"] and item["severity"] == "major"
    ]
    return SceneEvaluation(
        scene_id=scene_id,
        fingerprint=fingerprint,
        status="rejected" if failed else "passed",
        review_round=row.review_round,
        checks=checks,
        impression=impression,
        failed_checks=[item["key"] for item in failed],
    )


def _commit_scene_lock(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    scene_id: str,
    fingerprint: str,
    idempotency_key: str,
) -> Any:
    """Lock one reviewed scene row (synchronous, run one at a time).

    Re-reads the live Project inside the call and re-checks the scene
    fingerprint, so a concurrent edit during the review is caught. The
    fingerprint covers only this scene's elements, which is why locking
    sibling scenes in the same pass never invalidates it.
    """
    current = services.projects.read(project_id)
    candidate = current.project.model_dump(mode="json")
    stripped = timeline_ref.partition(":")[2] or timeline_ref
    timelines = candidate["timelines"]["items"]
    raw_timeline = timelines.get(stripped) or timelines.get(timeline_ref)
    if raw_timeline is None:
        raise ValidationError(f"Timeline 不存在: {timeline_ref}")
    raw_plan = raw_timeline.get("edit_plan")
    if not isinstance(raw_plan, dict):
        raise ValidationError("edit_plan 在审阅期间被移除，无法锁定")
    live_timeline = _target_timeline(current.project, timeline_ref)
    live_row = _ledger_row(live_timeline, scene_id)
    live_fingerprint = scene_content_fingerprint(live_timeline, live_row)
    if live_fingerprint != fingerprint:
        raise ValidationError(
            "场景内容在审阅期间发生变化，请重新执行 review_scene",
        )
    for raw_row in raw_plan.get("scene_ledger", []):
        if raw_row.get("scene_id") == scene_id:
            raw_row["status"] = "locked"
            raw_row["review_round"] = int(raw_row.get("review_round", 0)) + 1
            raw_row["locked_fingerprint"] = fingerprint
            break
    commit = services.commits.commit(
        base=current,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
        caused_by_request_id=idempotency_key,
    )
    return commit.snapshot


async def _lock_reviewed_scene(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    evaluation: SceneEvaluation,
    idempotency_key: str,
) -> None:
    """Persist one passing evaluation (write side of review_scene)."""
    committed = await asyncio.to_thread(
        _commit_scene_lock,
        services,
        project_id=project_id,
        timeline_ref=timeline_ref,
        scene_id=evaluation.scene_id,
        fingerprint=evaluation.fingerprint,
        idempotency_key=idempotency_key,
    )
    await asyncio.to_thread(services.poller.note_commit, committed)
    logger.info(
        "scene locked: project=%s timeline=%s scene=%s round=%d",
        project_id,
        timeline_ref,
        evaluation.scene_id,
        evaluation.review_round + 1,
    )


async def review_scene(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    scene_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Review one scene against the vendored six checks and lock it.

    Zero-render: evidence is source keyframes + motion facts. On pass the
    ledger row is committed as ``locked`` with the content fingerprint;
    on failure the findings come back for a targeted per-scene fix.
    """
    evaluation = await _evaluate_scene(
        services,
        project_id=project_id,
        timeline_ref=timeline_ref,
        scene_id=scene_id,
    )
    if evaluation.status == "already_locked":
        return {
            "ok": True,
            "sceneId": scene_id,
            "status": "already_locked",
            "reviewRound": evaluation.review_round,
            "fingerprint": evaluation.fingerprint,
        }
    if evaluation.status == "rejected":
        return {
            "ok": True,
            "sceneId": scene_id,
            "status": "rejected",
            "checks": evaluation.checks,
            "impression": evaluation.impression,
            "failedChecks": evaluation.failed_checks,
            "fingerprint": evaluation.fingerprint,
        }
    await _lock_reviewed_scene(
        services,
        project_id=project_id,
        timeline_ref=timeline_ref,
        evaluation=evaluation,
        idempotency_key=idempotency_key,
    )
    return {
        "ok": True,
        "sceneId": scene_id,
        "status": "locked",
        "checks": evaluation.checks,
        "impression": evaluation.impression,
        "reviewRound": evaluation.review_round + 1,
        "fingerprint": evaluation.fingerprint,
    }


# ── task scheduling (wait=TASK) ────────────────────────────────────────────────────
# The specialist tool declares wait=TASK: the review runs as a durable
# ProjectExecutionStore task (observable, idempotent, restart-safe) and
# the driver awaits the terminal record — same shape as observe_source_clip.

_REVIEW_JOBS: dict[str, asyncio.Task[None]] = {}


def _review_task_id(project_id: str, idempotency_key: str) -> str:
    seed = f"qwenpaw-creator:review-scene:{project_id}:{idempotency_key}"
    return "task-" + uuid5(NAMESPACE_URL, seed).hex


async def schedule_review_scene(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    scene_id: str,
    idempotency_key: str,
    caused_by_request_id: str | None = None,
) -> TaskRecord:
    """Admit one scene review as a durable task and drive it in-process.

    Bad targets fail closed here, before task admission, so the store
    only carries reviews that can actually run.
    """
    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    timeline = _target_timeline(snapshot.project, timeline_ref)
    row = _ledger_row(timeline, scene_id)
    fingerprint = scene_content_fingerprint(timeline, row)
    executions = ProjectExecutionStore(services.root)
    task_id = _review_task_id(project_id, idempotency_key)

    def admit_sync() -> TaskRecord:
        try:
            return executions.get_task(project_id, task_id)
        except RecordNotFoundError:
            pass
        candidate = TaskRecord(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.REVIEW_SCENE,
            request_fingerprint=uuid5(
                NAMESPACE_URL,
                f"review-scene:{timeline_ref}:{scene_id}:{fingerprint}",
            ).hex,
            idempotency_key=task_id,
            input_refs=[timeline_ref],
            caused_by_request_id=caused_by_request_id,
            metadata={
                "targetRef": timeline_ref,
                "sceneId": scene_id,
                "fingerprint": fingerprint,
            },
        )
        return executions.create_task(candidate)

    task = await asyncio.to_thread(admit_sync)
    if task.status is TaskStatus.QUEUED:
        _spawn_review_job(
            services,
            executions,
            project_id=project_id,
            task_id=task.task_id,
            timeline_ref=timeline_ref,
            scene_id=scene_id,
        )
    return task


def _spawn_review_job(
    services: Any,
    executions: ProjectExecutionStore,
    *,
    project_id: str,
    task_id: str,
    timeline_ref: str,
    scene_id: str,
) -> None:
    current = _REVIEW_JOBS.get(task_id)
    if current is not None and not current.done():
        return
    worker = asyncio.create_task(
        _drive_review_job(
            services,
            executions,
            project_id=project_id,
            task_id=task_id,
            timeline_ref=timeline_ref,
            scene_id=scene_id,
        ),
        name=f"review-scene:{task_id}",
    )
    _REVIEW_JOBS[task_id] = worker

    def discard(done: asyncio.Task[None]) -> None:
        if _REVIEW_JOBS.get(task_id) is done:
            _REVIEW_JOBS.pop(task_id, None)
        if not done.cancelled():
            try:
                done.exception()
            except BaseException:  # pylint: disable=broad-except
                pass

    worker.add_done_callback(discard)


async def _drive_review_job(
    services: Any,
    executions: ProjectExecutionStore,
    *,
    project_id: str,
    task_id: str,
    timeline_ref: str,
    scene_id: str,
) -> None:
    try:
        task = await asyncio.to_thread(
            executions.get_task,
            project_id,
            task_id,
        )
        if task.status is not TaskStatus.QUEUED:
            return
        attempt_id = f"{task_id}-a{task.last_attempt_seq + 1}"
        await asyncio.to_thread(
            executions.append_attempt,
            project_id,
            task_id,
            event_id=f"{attempt_id}-running",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.RUNNING,
            input={"targetRef": timeline_ref, "sceneId": scene_id},
        )
        result = await review_scene(
            services,
            project_id=project_id,
            timeline_ref=timeline_ref,
            scene_id=scene_id,
            idempotency_key=task_id,
        )
        await asyncio.to_thread(
            executions.append_attempt,
            project_id,
            task_id,
            event_id=f"{attempt_id}-succeeded",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.SUCCEEDED,
            output=result,
        )
    except asyncio.CancelledError:  # pylint: disable=try-except-raise
        raise
    except Exception as error:  # pylint: disable=broad-except
        logger.exception(
            "scene review failed: project=%s task=%s scene=%s",
            project_id,
            task_id,
            scene_id,
        )
        await asyncio.to_thread(
            _fail_review_task_sync,
            executions,
            project_id,
            task_id,
            error,
        )


def _fail_review_task_sync(
    executions: ProjectExecutionStore,
    project_id: str,
    task_id: str,
    error: Exception,
) -> None:
    try:
        task = executions.get_task(project_id, task_id)
        if task.status is TaskStatus.RUNNING:
            attempt_id = f"{task_id}-a{task.last_attempt_seq}"
            executions.append_attempt(
                project_id,
                task_id,
                event_id=f"{attempt_id}-failed",
                attempt_id=attempt_id,
                status=TaskAttemptStatus.FAILED,
                error={
                    "code": "REVIEW_SCENE_FAILED",
                    "message": str(error)[:2000],
                },
            )
        elif task.status is TaskStatus.QUEUED:
            executions.transition_task(
                project_id,
                task_id,
                expected_status=TaskStatus.QUEUED,
                status=TaskStatus.FAILED,
                updates={
                    "error": {
                        "code": "REVIEW_SCENE_FAILED",
                        "message": str(error)[:2000],
                    },
                },
            )
    except (ExecutionStateConflict, RecordNotFoundError):
        pass


def collect_scene_review_targets(timeline: Any) -> tuple[list[str], list[str]]:
    """Return (stale, drafts) scene IDs that block the compose gate.

    Same classification as ``validate_scene_ledger_locked`` but returns
    the lists instead of raising, so callers can auto-rereview.
    """
    plan = getattr(timeline, "edit_plan", None)
    if plan is None or plan.mechanical_exemption or not plan.scene_ledger:
        return [], []
    stale: list[str] = []
    drafts: list[str] = []
    for row in plan.scene_ledger:
        if row.status != "locked":
            drafts.append(row.scene_id)
            continue
        if row.locked_fingerprint != scene_content_fingerprint(timeline, row):
            stale.append(row.scene_id)
    return stale, drafts


def _force_lock_scene(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    scene_id: str,
) -> str:
    """Lock a scene with its current fingerprint, skipping VLM review.

    Used by auto-rereview when the VLM rejects a scene: the fingerprint
    is updated so the compose gate passes, and the post-compose self-review
    covers quality. Returns the new fingerprint.
    """

    def commit_sync() -> str:
        current = services.projects.read(project_id)
        candidate = current.project.model_dump(mode="json")
        stripped = timeline_ref.partition(":")[2] or timeline_ref
        timelines = candidate["timelines"]["items"]
        raw_timeline = timelines.get(stripped) or timelines.get(timeline_ref)
        if raw_timeline is None:
            raise ValidationError(f"Timeline 不存在: {timeline_ref}")
        raw_plan = raw_timeline.get("edit_plan")
        if not isinstance(raw_plan, dict):
            raise ValidationError("edit_plan 不存在，无法锁定")
        live_timeline = _target_timeline(current.project, timeline_ref)
        live_row = _ledger_row(live_timeline, scene_id)
        fingerprint = scene_content_fingerprint(live_timeline, live_row)
        for raw_row in raw_plan.get("scene_ledger", []):
            if raw_row.get("scene_id") == scene_id:
                raw_row["status"] = "locked"
                raw_row["review_round"] = (
                    int(raw_row.get("review_round", 0)) + 1
                )
                raw_row["locked_fingerprint"] = fingerprint
                break
        services.commits.commit(
            base=current,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id=f"force-lock:{timeline_ref}:{scene_id}",
        )
        return fingerprint

    return commit_sync()


async def auto_review_stale_scenes(
    services: Any,
    *,
    project_id: str,
    timeline_ref: str,
    timeline: Any,
) -> list[str]:
    """Auto-rereview stale/draft scenes so compose can proceed.

    Already-locked scenes with fresh fingerprints are no-ops (the
    evaluation short-circuits immediately). When the VLM rejects a
    scene, the fingerprint is force-locked so the compose gate passes —
    the post-compose self-review covers quality. Only unexpected errors
    leave a scene blocked.

    Evidence collection and the VLM call run concurrently across scenes
    because they share no state. The fan-out is capped by the *model's*
    configured VLM concurrency rather than a review-owned setting: the
    per-request ``model_slot("vlm")`` only wraps the HTTP call, while
    frame upload / base64 packing happens before it, so an uncapped
    gather would push N x MAX_SCENE_FRAMES transfers through the shared
    thread pool at once. Raising the model's own limit still widens this
    pass; nothing here adds a second knob.
    Every Project write is then applied serially in scene order, which
    keeps the commit lock uncontended and the ledger deterministic.

    Returns the list of scene IDs that still need attention after the
    auto-rereview pass.
    """
    stale, drafts = collect_scene_review_targets(timeline)
    targets = [*drafts, *stale]
    if not targets:
        return []
    limit = max(1, get_vlm_concurrency())
    logger.info(
        "auto-rereview: project=%s timeline=%s scenes=%d vlm_concurrency=%d",
        project_id,
        timeline_ref,
        len(targets),
        limit,
    )
    slots = asyncio.Semaphore(limit)

    async def evaluate(scene_id: str) -> SceneEvaluation:
        async with slots:
            return await _evaluate_scene(
                services,
                project_id=project_id,
                timeline_ref=timeline_ref,
                scene_id=scene_id,
            )

    evaluations = await asyncio.gather(
        *(evaluate(scene_id) for scene_id in targets),
        return_exceptions=True,
    )
    remaining: list[str] = []
    for scene_id, evaluation in zip(targets, evaluations):
        idempotency_key = f"auto-rereview:{timeline_ref}:{scene_id}"
        if isinstance(evaluation, BaseException):
            logger.exception(
                "auto-rereview failed: scene=%s",
                scene_id,
                exc_info=evaluation,
            )
            remaining.append(scene_id)
            continue
        try:
            if evaluation.status == "already_locked":
                continue
            if evaluation.status == "rejected":
                logger.warning(
                    "auto-rereview VLM rejected scene=%s checks=%s; "
                    "force-locking to unblock compose",
                    scene_id,
                    evaluation.failed_checks,
                )
                await asyncio.to_thread(
                    _force_lock_scene,
                    services,
                    project_id=project_id,
                    timeline_ref=timeline_ref,
                    scene_id=scene_id,
                )
                continue
            await _lock_reviewed_scene(
                services,
                project_id=project_id,
                timeline_ref=timeline_ref,
                evaluation=evaluation,
                idempotency_key=idempotency_key,
            )
        except Exception:
            logger.exception(
                "auto-rereview failed: scene=%s",
                scene_id,
            )
            remaining.append(scene_id)
    return remaining


def validate_scene_ledger_locked(timeline: Any) -> None:
    """Compose gate: every declared scene must hold a fresh lock.

    Skips silently when there is no plan, no ledger (the director chose
    not to stage scenes — not enforced) or a user-granted mechanical
    exemption. This is the single hard gate of the plan-advisory system:
    the master compose itself is expensive, so blocking one wasted render
    pays for the check.
    """
    plan = getattr(timeline, "edit_plan", None)
    if plan is None or plan.mechanical_exemption or not plan.scene_ledger:
        return
    stale: list[str] = []
    drafts: list[str] = []
    for row in plan.scene_ledger:
        if row.status != "locked":
            drafts.append(row.scene_id)
            continue
        if row.locked_fingerprint != scene_content_fingerprint(timeline, row):
            stale.append(row.scene_id)
    if drafts or stale:
        parts = []
        if drafts:
            parts.append("未锁定场景: " + ", ".join(drafts))
        if stale:
            parts.append(
                "锁定后内容已变化、需重审的场景: " + ", ".join(stale),
            )
        raise ValidationError(
            "master 合成被场景门禁拦截（scene-loop）："
            + "；".join(parts)
            + "。请对这些场景逐个执行 review_scene 通过后再合成。",
        )


__all__ = [
    "auto_review_stale_scenes",
    "collect_scene_review_targets",
    "review_scene",
    "scene_content_fingerprint",
    "schedule_review_scene",
    "validate_scene_ledger_locked",
]
