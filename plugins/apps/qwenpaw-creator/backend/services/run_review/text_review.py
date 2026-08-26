# -*- coding: utf-8 -*-
"""Synchronous in-run review of freshly committed text/motion artifacts.

Runs inline inside the ``jq_project`` tool worker (a ``to_thread`` context):
when the sync switch is on and the commit touched reviewable creative text,
the changed values are scored against the vendored Appeal rubric and the
advisory is attached to the tool result, so the model sees it on its very
next turn of the same run. Strictly advisory and fail-open: any review
problem only logs — the commit result is never disturbed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from schemas.run_review import RubricScore, SyncReviewAdvisory
from services.observability.tracing import trace_event
from services.run_review import admission
from services.run_review.rubric_prompts import (
    STAGE_RUBRIC_ROWS,
    build_appeal_system_prompt,
)
from utils.logger import setup_logger

logger = setup_logger("creator.run_review.text")

_TRACE_COMPONENT = "run_review"
# Real-model observation (2026-08-20): the DogFooding proxy can take
# >60s per text completion when the agent's own turn runs concurrently;
# 60s produced spurious ReadTimeouts on the very first live commit.
_TEXT_MODEL_TIMEOUT_SECONDS = 120.0
_VALUE_CHAR_LIMIT = 2000
_PAYLOAD_CHAR_LIMIT = 12000
_PERSISTENT_MEDIA_GATE_GROUPS = frozenset(
    {"shots", "overlay_text", "motion"},
)

# Pointer classification: (group, stage, substring patterns). The first
# matching group in this order wins when one commit spans several groups.
# Generation-driving shot/prompt text must win over the broader strategy
# fields: it is the content the pre-generation fence is specifically meant
# to validate before storyboard/R2V spend begins.
_POINTER_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "shots",
        "text",
        (
            "/creation/shots",
            "/creation/intent",
            "/creation/narrative",
            "/creation/continuity",
            "/creation/storyboard_prompt",
            "/creation/video_prompt",
            "/creation/script",
            "/creation/reason",
            "/creation/prompt",
        ),
    ),
    ("strategy", "text", ("/strategy/",)),
    ("overlay_text", "text", ("/creation/text",)),
    ("motion", "motion", ("/creation/motion",)),
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def classify_pointers(
    changed_pointers: Sequence[str],
) -> tuple[str, str, list[str]] | None:
    """Return ``(group, stage, matched_pointers)`` for the winning group."""
    groups = classify_pointer_groups(changed_pointers)
    return groups[0] if groups else None


def classify_pointer_groups(
    changed_pointers: Sequence[str],
) -> list[tuple[str, str, list[str]]]:
    """Return every affected review group in stable priority order."""

    groups: list[tuple[str, str, list[str]]] = []
    for group, stage, patterns in _POINTER_GROUPS:
        matched = [
            pointer
            for pointer in changed_pointers
            if any(pattern in pointer for pattern in patterns)
        ]
        if matched:
            groups.append((group, stage, matched))
    return groups


def _has_reviewable_content(value: Any) -> bool:
    """Whether a changed subtree contains creative text worth reviewing."""

    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_reviewable_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_reviewable_content(item) for item in value)
    return False


def reviewable_changed_pointers(
    project_json: Mapping[str, Any],
    changed_pointers: Sequence[str],
) -> list[str]:
    """Expand structural parent changes into reviewable creative pointers.

    The Project diff intentionally emits one parent pointer when an entire
    Element is created. The old substring-only classifier therefore missed
    the exact first commit that made storyboard/video nodes READY. Walk only
    each changed subtree, stop at the first reviewable boundary, and return
    stable synthetic pointers without changing the public Project diff.
    """

    expanded: list[str] = []

    def walk(value: Any, pointer: str) -> None:
        if classify_pointers([pointer]) is not None:
            if _has_reviewable_content(value):
                expanded.append(pointer)
            return
        if isinstance(value, Mapping):
            for key in sorted(value):
                token = str(key).replace("~", "~0").replace("/", "~1")
                child = f"{pointer}/{token}" if pointer else f"/{token}"
                walk(value[key], child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                child = f"{pointer}/{index}" if pointer else f"/{index}"
                walk(item, child)

    for pointer in changed_pointers:
        value = _resolve_pointer(project_json, pointer)
        if value is None:
            continue
        walk(value, pointer)
    return list(dict.fromkeys(expanded))


def _resolve_pointer(document: Mapping[str, Any], pointer: str) -> Any:
    """RFC 6901 resolution; returns ``None`` when the path is gone."""
    current: Any = document
    if not pointer.startswith("/"):
        return None
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return None
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _payload_text(
    project_json: Mapping[str, Any],
    pointers: Sequence[str],
) -> str:
    sections: list[str] = []
    total = 0
    for pointer in pointers:
        value = _resolve_pointer(project_json, pointer)
        if value is None:
            continue
        rendered = json.dumps(value, ensure_ascii=False)
        if len(rendered) > _VALUE_CHAR_LIMIT:
            rendered = rendered[:_VALUE_CHAR_LIMIT] + "…(truncated)"
        section = f"{pointer}:\n{rendered}"
        total += len(section)
        if total > _PAYLOAD_CHAR_LIMIT:
            break
        sections.append(section)
    return "\n\n".join(sections)


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("sync review response contains no JSON object")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("sync review response JSON is not an object")
    return payload


def parse_sync_advisory(
    text: str,
    *,
    stage: str,
    transaction_id: str,
    pointer_group: str,
    reviewed_pointers: Sequence[str],
    round_number: int,
) -> SyncReviewAdvisory:
    """Parse the model output; ``ok`` is derived deterministically."""
    payload = _extract_json_object(text)
    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, list) or not raw_scores:
        raise ValueError("sync review response has no scores list")
    expected_rows = {row.key: row for row in _stage_rows(stage)}
    scores: list[RubricScore] = []
    seen: set[str] = set()
    for item in raw_scores:
        if not isinstance(item, Mapping):
            continue
        row_key = str(item.get("row_key") or "")
        row = expected_rows.get(row_key)
        if row is None or row_key in seen:
            continue
        seen.add(row_key)
        try:
            score = int(item.get("score"))
        except (TypeError, ValueError):
            score = 10
        score = max(0, min(10, score))
        finding = str(item.get("finding") or "")
        # Evidence discipline: a weak score without a cited finding cannot
        # stand (upstream: no evidence-free failures).
        ok = score > 5 or not finding.strip()
        scores.append(
            RubricScore(
                row_key=row_key,
                name=row.name,
                score=score,
                ok=ok,
                # Advisory hygiene: passing rows carry no finding/suggestion,
                # so the agent only ever sees actionable weak-row evidence.
                finding=finding if not ok else "",
                suggestion=str(item.get("suggestion") or "") if not ok else "",
            ),
        )
    missing = [key for key in expected_rows if key not in seen]
    if missing:
        raise ValueError(
            "sync review response missing rubric rows: " + ", ".join(missing),
        )
    return SyncReviewAdvisory(
        transaction_id=transaction_id,
        pointer_group=pointer_group,
        reviewed_pointers=list(reviewed_pointers),
        round=round_number,
        scores=scores,
        summary=str(payload.get("summary") or ""),
        created_at=datetime.now(UTC),
    )


def _stage_rows(stage: str):
    from vendor.media_toolkit.review_rubrics import APPEAL_RUBRIC_ROWS

    indexes = STAGE_RUBRIC_ROWS.get(stage, (0, 1, 2))
    return [row for row in APPEAL_RUBRIC_ROWS if row.index in indexes]


async def _review_async(stage: str, payload_text: str) -> str:
    from models.text_model import chat_completion

    return await chat_completion(
        "请按逐行打分制审阅以下本次提交变更的创作文本：\n\n" + payload_text,
        system_prompt=build_appeal_system_prompt(stage),
        temperature=0.2,
        max_tokens=1800,
        timeout=_TEXT_MODEL_TIMEOUT_SECONDS,
    )


async def _review_and_script(
    stage: str,
    payload_text: str,
    strategy_payload: str,
    shots_payload: str,
) -> tuple[str, dict[str, Any] | None]:
    """Appeal review plus (for shots commits) the script-to-shots check.

    The two calls run concurrently on the worker's private loop; the
    script check is fail-open internally and never raises.
    """
    if not strategy_payload or not shots_payload:
        return await _review_async(stage, payload_text), None
    from services.run_review.script_review import run_script_check

    response, script_check = await asyncio.gather(
        _review_async(stage, payload_text),
        run_script_check(
            strategy_payload=strategy_payload,
            shots_payload=shots_payload,
        ),
    )
    return response, script_check


def _script_check_enabled() -> bool:
    from services.run_review.operator_registry import is_operator_enabled

    return is_operator_enabled("script_check")


def _strategy_payload(project_json: Mapping[str, Any]) -> str:
    """Serialized creative strategy; empty when nothing is filled in."""
    strategy = project_json.get("strategy")
    if not isinstance(strategy, Mapping):
        return ""
    filled = {
        key: value
        for key, value in strategy.items()
        if isinstance(value, str) and value.strip()
    }
    if not filled:
        return ""
    return json.dumps(filled, ensure_ascii=False)


def _admit_sync_review_jobs(
    project_json: Mapping[str, Any],
    classified: Sequence[tuple[str, str, list[str]]],
    *,
    reports_root: Path,
    failed_groups: set[str],
) -> list[dict[str, Any]]:
    """Admit every affected group and describe the review call it needs.

    A group already reviewed at the same content hash (or over its round
    cap) is dropped by admission. ``failed_groups`` collects the durable
    blockers so an outer failure can release them.
    """

    jobs: list[dict[str, Any]] = []
    for group, stage, matched in classified:
        payload_text = _payload_text(project_json, matched)
        if not payload_text.strip():
            continue
        content_hash = hashlib.sha256(
            payload_text.encode("utf-8"),
        ).hexdigest()
        round_number = admission.admit_sync_review(
            reports_root,
            pointer_group=group,
            content_hash=content_hash,
        )
        if round_number is None:
            continue
        failed_groups.add(group)
        jobs.append(
            {
                "group": group,
                "stage": stage,
                "matched": matched,
                "payload_text": payload_text,
                "content_hash": content_hash,
                "round_number": round_number,
            },
        )
    return jobs


def _settle_sync_review_job(
    job: Mapping[str, Any],
    response: Any,
    *,
    project_id: str,
    reports_root: Path,
    transaction_id: str,
    gate_token: str | None,
    multi: bool,
    failed_groups: set[str],
) -> dict[str, Any] | None:
    """Settle one group's round; return its advisory when not clean.

    Fail-open per group: a failed call or an unparsable verdict releases
    that group's blocker and leaves the other groups untouched.
    """

    from services.run_review.script_review import script_check_has_findings

    group = str(job["group"])
    stage = str(job["stage"])
    matched = list(job["matched"])
    content_hash = str(job["content_hash"])
    round_number = int(job["round_number"])
    if isinstance(response, BaseException):
        admission.clear_sync_blocker(reports_root, pointer_group=group)
        failed_groups.discard(group)
        logger.error(
            "sync review group failed for project %s txn %s group %s: %s",
            project_id,
            transaction_id,
            group,
            response,
        )
        return None
    try:
        response_text, script_check = response
        advisory = parse_sync_advisory(
            response_text,
            stage=stage,
            transaction_id=transaction_id,
            pointer_group=group,
            reviewed_pointers=matched,
            round_number=round_number,
        )
        if script_check is not None:
            advisory = advisory.model_copy(
                update={"script_check": script_check},
            )
        clean = not advisory.weak_scores() and not script_check_has_findings(
            script_check,
        )
        admission.settle_sync_review(
            reports_root,
            pointer_group=group,
            content_hash=content_hash,
            clean=clean,
        )
        # A weak inline review must remain effective during the next
        # agent turn. A clean follow-up or the hard cap releases it.
        if (
            clean
            or round_number >= admission.MAX_SYNC_REVIEW_ROUNDS
            or group not in _PERSISTENT_MEDIA_GATE_GROUPS
        ):
            admission.clear_sync_blocker(reports_root, pointer_group=group)
        elif gate_token is not None:
            admission.hold_sync_blocker(
                reports_root,
                project_id=project_id,
                pointer_group=group,
                reviewed_pointers=matched,
                round_number=round_number,
            )
        report_name = admission.safe_ref(transaction_id)
        if multi:
            report_name += f"-{admission.safe_ref(group)}"
        admission.write_json(
            reports_root / "sync" / f"{report_name}.json",
            advisory.model_dump(mode="json"),
        )
        trace_event(
            "run_review.sync_advisory",
            component=_TRACE_COMPONENT,
            attributes={
                "pointerGroup": group,
                "stage": stage,
                "round": round_number,
                "clean": clean,
                "scriptFindings": script_check_has_findings(script_check),
                "transactionId": transaction_id,
            },
            projectId=project_id,
        )
        failed_groups.discard(group)
        return None if clean else advisory.model_dump(mode="json")
    except Exception:  # noqa: BLE001 - per-group advisory fail-open
        admission.clear_sync_blocker(reports_root, pointer_group=group)
        failed_groups.discard(group)
        logger.exception(
            "sync review group parse/settle failed for project %s "
            "txn %s group %s",
            project_id,
            transaction_id,
            group,
        )
        return None


def _merge_sync_advisories(
    delivered: Sequence[dict[str, Any]],
    transaction_id: str,
) -> dict[str, Any] | None:
    """One tool-result payload for however many groups spoke up."""

    if not delivered:
        return None
    if len(delivered) == 1:
        return delivered[0]
    return {
        "transaction_id": transaction_id,
        "pointer_group": "multiple",
        "reviewed_pointers": list(
            dict.fromkeys(
                pointer
                for item in delivered
                for pointer in item.get("reviewed_pointers") or []
            ),
        ),
        "round": max(int(item.get("round") or 0) for item in delivered),
        "advisories": list(delivered),
        "summary": "；".join(
            str(item.get("summary") or "") for item in delivered
        ),
    }


def maybe_sync_review(  # pylint: disable=too-many-locals,too-many-statements
    *,
    project_id: str,
    project_root: Path,
    project_json: Mapping[str, Any],
    changed_pointers: Sequence[str],
    transaction_id: str,
    gate_token: str | None = None,
) -> dict[str, Any] | None:
    """Sync review entry for the jq_project worker thread. Fail-open.

    Returns the advisory as a JSON-ready dict to attach to the tool result,
    or ``None`` when review is off, not applicable, deduped, capped or
    failed.
    """
    reports_root = project_root / "runtime" / "run-review"
    failed_groups: set[str] = set()
    try:
        from models.config import is_sync_review_enabled

        if not is_sync_review_enabled():
            return None
        expanded_pointers = reviewable_changed_pointers(
            project_json,
            changed_pointers,
        )
        classified = classify_pointer_groups(expanded_pointers)
        if not classified:
            return None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            # Inline review needs its own loop; inside a running loop this
            # worker cannot block on one, so the advisory is skipped.
            logger.warning("sync review skipped: called on a running loop")
            return None

        jobs = _admit_sync_review_jobs(
            project_json,
            classified,
            reports_root=reports_root,
            failed_groups=failed_groups,
        )
        if not jobs:
            return None

        shots_pointers = [
            pointer
            for pointer in changed_pointers
            if "/creation/shots" in pointer
        ]
        shots_payload = _payload_text(project_json, shots_pointers)
        script_strategy = (
            _strategy_payload(project_json)
            if shots_payload and _script_check_enabled()
            else ""
        )

        async def review_all() -> list[Any]:
            # A mixed repair often updates strategy and generation prompts in
            # the same atomic commit.  Review every affected group in
            # parallel: selecting only one left the other group's durable
            # blocker orphaned until its five-minute crash TTL.
            return list(
                await asyncio.gather(
                    *(
                        _review_and_script(
                            str(job["stage"]),
                            str(job["payload_text"]),
                            script_strategy if job["group"] == "shots" else "",
                            shots_payload if job["group"] == "shots" else "",
                        )
                        for job in jobs
                    ),
                    return_exceptions=True,
                ),
            )

        responses = asyncio.run(review_all())

        delivered: list[dict[str, Any]] = []
        multi = len(jobs) > 1
        for job, response in zip(jobs, responses, strict=True):
            advisory_payload = _settle_sync_review_job(
                job,
                response,
                project_id=project_id,
                reports_root=reports_root,
                transaction_id=transaction_id,
                gate_token=gate_token,
                multi=multi,
                failed_groups=failed_groups,
            )
            if advisory_payload is not None:
                delivered.append(advisory_payload)

        return _merge_sync_advisories(delivered, transaction_id)
    except Exception:
        # Advisory only: a review failure must never disturb the commit.
        for failed_group in failed_groups:
            admission.clear_sync_blocker(
                reports_root,
                pointer_group=failed_group,
            )
        logger.exception(
            "sync review failed for project %s txn %s",
            project_id,
            transaction_id,
        )
        return None


__all__ = [
    "classify_pointer_groups",
    "classify_pointers",
    "maybe_sync_review",
    "parse_sync_advisory",
    "reviewable_changed_pointers",
]
