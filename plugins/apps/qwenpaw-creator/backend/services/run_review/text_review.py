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
_TEXT_MODEL_TIMEOUT_SECONDS = 60.0
_VALUE_CHAR_LIMIT = 2000
_PAYLOAD_CHAR_LIMIT = 12000

# Pointer classification: (group, stage, substring patterns). The first
# matching group in this order wins when one commit spans several groups.
_POINTER_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("strategy", "text", ("/strategy/",)),
    ("shots", "text", ("/creation/shots",)),
    ("overlay_text", "text", ("/creation/text",)),
    ("motion", "motion", ("/creation/motion",)),
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def classify_pointers(
    changed_pointers: Sequence[str],
) -> tuple[str, str, list[str]] | None:
    """Return ``(group, stage, matched_pointers)`` for the winning group."""
    for group, stage, patterns in _POINTER_GROUPS:
        matched = [
            pointer
            for pointer in changed_pointers
            if any(pattern in pointer for pattern in patterns)
        ]
        if matched:
            return group, stage, matched
    return None


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
    from vendor.mm_plugins.review_rubrics import APPEAL_RUBRIC_ROWS

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


def maybe_sync_review(  # pylint: disable=too-many-return-statements
    *,
    project_id: str,
    project_root: Path,
    project_json: Mapping[str, Any],
    changed_pointers: Sequence[str],
    transaction_id: str,
) -> dict[str, Any] | None:
    """Sync review entry for the jq_project worker thread. Fail-open.

    Returns the advisory as a JSON-ready dict to attach to the tool result,
    or ``None`` when review is off, not applicable, deduped, capped or
    failed.
    """
    try:
        from models.config import is_sync_review_enabled

        if not is_sync_review_enabled():
            return None
        classified = classify_pointers(changed_pointers)
        if classified is None:
            return None
        group, stage, matched = classified
        payload_text = _payload_text(project_json, matched)
        if not payload_text.strip():
            return None
        content_hash = hashlib.sha256(
            payload_text.encode("utf-8"),
        ).hexdigest()
        reports_root = project_root / "runtime" / "run-review"
        round_number = admission.admit_sync_review(
            reports_root,
            pointer_group=group,
            content_hash=content_hash,
        )
        if round_number is None:
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
        response = asyncio.run(_review_async(stage, payload_text))
        advisory = parse_sync_advisory(
            response,
            stage=stage,
            transaction_id=transaction_id,
            pointer_group=group,
            reviewed_pointers=matched,
            round_number=round_number,
        )
        clean = not advisory.weak_scores()
        admission.settle_sync_review(
            reports_root,
            pointer_group=group,
            content_hash=content_hash,
            clean=clean,
        )
        admission.write_json(
            reports_root
            / "sync"
            / f"{admission.safe_ref(transaction_id)}.json",
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
                "transactionId": transaction_id,
            },
            projectId=project_id,
        )
        if clean:
            return None
        return advisory.model_dump(mode="json")
    except Exception:
        # Advisory only: a review failure must never disturb the commit.
        logger.exception(
            "sync review failed for project %s txn %s",
            project_id,
            transaction_id,
        )
        return None


__all__ = [
    "classify_pointers",
    "maybe_sync_review",
    "parse_sync_advisory",
]
