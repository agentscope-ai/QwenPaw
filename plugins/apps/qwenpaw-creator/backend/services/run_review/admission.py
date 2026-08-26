# -*- coding: utf-8 -*-
"""Round admission and loop safety for the in-run review bypass.

The async media side reuses the render-review claim semantics (PR #77):
per-slot state files under a cross-process lock, a bounded reviewed-version
history for idempotent replay, and a lease token bound to process + event
loop so a claim written by a dead loop is reclaimed on the next schedule.

The sync side is simpler: it runs inline inside the jq_project tool worker,
so it only needs a content-hash dedup plus a per-pointer-group round cap to
prevent an advisory ping-pong; the counter resets whenever a review comes
back clean.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from services.runtime_files.locking import CrossProcessFileLock
from utils.logger import setup_logger

logger = setup_logger("creator.run_review.admission")

_UNSAFE_REF_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_PROCESS_TOKEN = uuid4().hex
_LOOP_TOKEN_ATTR = "_run_review_owner_token"
_CLAIM_TTL_SECONDS = 30 * 60
_REVIEWED_HISTORY_LIMIT = 50
_SYNC_HASH_HISTORY_LIMIT = 20
_SYNC_FENCE_TTL_SECONDS = 5 * 60

# Advisory rounds per artifact slot (media) / per pointer group (sync).
MAX_MEDIA_REVIEW_ROUNDS = 2
MAX_SYNC_REVIEW_ROUNDS = 2
# Automated repair delegations per durable target. This is deliberately a
# physical-attempt budget: an admitted specialist consumes one attempt even if
# it later fails, is superseded, or produces a stale artifact. Otherwise the
# exact expensive paths the cap is meant to bound can reset it indefinitely.
MAX_REPAIR_ATTEMPTS = 3


def safe_ref(ref: str) -> str:
    return _UNSAFE_REF_CHARS.sub("-", ref).strip("-") or "target"


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f"{path.name}.tmp-{uuid4().hex[:8]}")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(staging, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def owner_token() -> str:
    """Lease token bound to the running event loop (render-review scheme)."""
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
    if str(claim.get("owner") or "") != owner:
        return False
    raw = str(claim.get("claimed_at") or "")
    try:
        claimed_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    age = (datetime.now(UTC) - claimed_at).total_seconds()
    return 0 <= age < _CLAIM_TTL_SECONDS


# ── Async media admission (per artifact slot) ────────────────────────────────


def _media_state_path(reports_root: Path, slot_id: str) -> Path:
    return reports_root / "media" / f"state-{safe_ref(slot_id)}.json"


def _media_lock(reports_root: Path, slot_id: str) -> CrossProcessFileLock:
    path = _media_state_path(reports_root, slot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return CrossProcessFileLock(path.with_name(f"{path.name}.lock"))


def admit_media_round(
    reports_root: Path,
    *,
    slot_id: str,
    version_id: str,
    owner: str | None = None,
) -> int | None:
    """Atomically claim the next advisory round for one artifact version.

    Returns the round number, or ``None`` when the version was already
    reviewed, another live claim holds it, or the slot's advisory budget is
    spent. A newer version always supersedes an in-flight claim.
    """
    owner = owner or owner_token()
    state_path = _media_state_path(reports_root, slot_id)
    with _media_lock(reports_root, slot_id):
        state = read_json(state_path) or {}
        reviewed = [
            str(item) for item in state.get("reviewed_version_ids") or []
        ]
        if version_id in reviewed:
            return None
        claim = state.get("claim") or {}
        if claim.get("version_id") == version_id and _claim_is_live(
            claim,
            owner=owner,
        ):
            return None
        rounds_completed = int(state.get("rounds_completed") or 0)
        attempts_started = max(
            rounds_completed,
            int(state.get("attempts_started") or 0),
            # Migration for pre-physical-budget state: every durable reviewed
            # version proves that one attempt already started, including
            # superseded versions which older code did not count as rounds.
            len(reviewed),
        )
        if attempts_started >= MAX_MEDIA_REVIEW_ROUNDS:
            return None
        # Consume the physical budget before any evidence/VLM work starts.
        # Superseded, cancelled and failed reviews still incurred wall time
        # and possibly provider cost, so finalization never refunds this.
        round_number = attempts_started + 1
        now = datetime.now(UTC).isoformat()
        state.update(
            {
                "slot_id": slot_id,
                "rounds_completed": rounds_completed,
                "attempts_started": round_number,
                "reviewed_version_ids": reviewed,
                "claim": {
                    "version_id": version_id,
                    "round": round_number,
                    "owner": owner,
                    "claimed_at": now,
                },
                "updated_at": now,
            },
        )
        write_json(state_path, state)
    return round_number


def release_media_claim(
    reports_root: Path,
    *,
    slot_id: str,
    version_id: str,
    owner: str | None = None,
) -> None:
    """Best-effort claim release after a failed review round."""
    owner = owner or owner_token()
    state_path = _media_state_path(reports_root, slot_id)
    try:
        with _media_lock(reports_root, slot_id):
            state = read_json(state_path) or {}
            claim = state.get("claim") or {}
            if (
                claim.get("version_id") != version_id
                or str(claim.get("owner") or "") != owner
            ):
                return
            state["claim"] = None
            state["updated_at"] = datetime.now(UTC).isoformat()
            write_json(state_path, state)
    except Exception:
        logger.exception("failed to release media review claim")


def finalize_media_round(
    reports_root: Path,
    *,
    slot_id: str,
    version_id: str,
    owner: str | None = None,
    counted: bool,
) -> bool:
    """Settle a finished round; only the owning claim may finalize.

    ``counted=False`` (superseded/stale outcome) records the version as
    reviewed without consuming the slot's advisory budget.
    """
    owner = owner or owner_token()
    state_path = _media_state_path(reports_root, slot_id)
    with _media_lock(reports_root, slot_id):
        state = read_json(state_path) or {}
        claim = state.get("claim") or {}
        if (
            claim.get("version_id") != version_id
            or str(claim.get("owner") or "") != owner
        ):
            return False
        reviewed = [
            str(item) for item in state.get("reviewed_version_ids") or []
        ]
        if version_id not in reviewed:
            reviewed.append(version_id)
        state["reviewed_version_ids"] = reviewed[-_REVIEWED_HISTORY_LIMIT:]
        if counted:
            state["rounds_completed"] = (
                int(state.get("rounds_completed") or 0) + 1
            )
        state["claim"] = None
        state["updated_at"] = datetime.now(UTC).isoformat()
        write_json(state_path, state)
    return True


# ── Sync admission (per pointer group, inline in the tool worker) ────────────


def _sync_state_path(reports_root: Path) -> Path:
    return reports_root / "sync" / "state.json"


def _sync_lock(reports_root: Path) -> CrossProcessFileLock:
    path = _sync_state_path(reports_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return CrossProcessFileLock(path.with_name(f"{path.name}.lock"))


def admit_sync_review(
    reports_root: Path,
    *,
    pointer_group: str,
    content_hash: str,
) -> int | None:
    """Admit one inline advisory for a pointer group, or ``None`` to skip.

    Identical content is never re-reviewed, and each group carries at most
    ``MAX_SYNC_REVIEW_ROUNDS`` consecutive advisories; the counter resets
    when a clean review is recorded (see :func:`settle_sync_review`).
    """
    state_path = _sync_state_path(reports_root)
    with _sync_lock(reports_root):
        state = read_json(state_path) or {}
        group = state.get(pointer_group) or {}
        hashes = [str(item) for item in group.get("hashes") or []]
        if content_hash in hashes:
            return None
        rounds = int(group.get("rounds") or 0)
        if rounds >= MAX_SYNC_REVIEW_ROUNDS:
            return None
        return rounds + 1


def settle_sync_review(
    reports_root: Path,
    *,
    pointer_group: str,
    content_hash: str,
    clean: bool,
) -> None:
    """Record a delivered advisory (or a clean pass, which resets the cap)."""
    state_path = _sync_state_path(reports_root)
    with _sync_lock(reports_root):
        state = read_json(state_path) or {}
        group = state.get(pointer_group) or {}
        hashes = [str(item) for item in group.get("hashes") or []]
        if content_hash not in hashes:
            hashes.append(content_hash)
        group["hashes"] = hashes[-_SYNC_HASH_HISTORY_LIMIT:]
        group["rounds"] = 0 if clean else int(group.get("rounds") or 0) + 1
        group["updated_at"] = datetime.now(UTC).isoformat()
        state[pointer_group] = group
        write_json(state_path, state)


# ── Sync scheduling fence (registered before Project publication) ─────────


def _sync_fence_dir(reports_root: Path) -> Path:
    return reports_root / "sync" / "fences"


def _sync_blocker_dir(reports_root: Path) -> Path:
    return reports_root / "sync" / "blockers"


def begin_sync_fence(
    reports_root: Path,
    *,
    project_id: str,
    reviewed_pointers: Sequence[str],
    token: str | None = None,
) -> str:
    """Persist a pre-commit fence that blocks dependent media dispatch.

    The file exists before the candidate Project is published. Therefore an
    unrelated media completion, a startup sweep, or any other concurrent wake
    cannot observe the new creative text and spend on it while its inline
    review is still running.
    """

    fence_token = token or f"sync-fence-{uuid4().hex}"
    write_json(
        _sync_fence_dir(reports_root) / f"{safe_ref(fence_token)}.json",
        {
            "token": fence_token,
            "project_id": project_id,
            "reviewed_pointers": sorted(set(reviewed_pointers)),
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    return fence_token


def end_sync_fence(reports_root: Path, token: str) -> None:
    """Best-effort release of one pre-commit sync-review fence."""

    path = _sync_fence_dir(reports_root) / f"{safe_ref(token)}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("failed to release sync-review fence %s", token)


def hold_sync_blocker(
    reports_root: Path,
    *,
    project_id: str,
    pointer_group: str,
    reviewed_pointers: Sequence[str],
    round_number: int,
) -> None:
    """Keep dependent media gated while an advisory still needs repair.

    The short-lived pre-commit fence only protects the time spent inside the
    inline reviewer.  A weak advisory must also protect the following agent
    turn; otherwise the scheduler starts paid generation from the rejected
    prompt before the model can apply the feedback.  One blocker per pointer
    group is enough because a newer repair supersedes the older content.
    """

    write_json(
        _sync_blocker_dir(reports_root) / f"{safe_ref(pointer_group)}.json",
        {
            "token": f"sync-blocker-{safe_ref(pointer_group)}",
            "project_id": project_id,
            "pointer_group": pointer_group,
            "reviewed_pointers": sorted(set(reviewed_pointers)),
            "round": round_number,
            "kind": "awaiting_repair",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


def clear_sync_blocker(reports_root: Path, *, pointer_group: str) -> None:
    """Release the unresolved-advisory blocker for one pointer group."""

    path = _sync_blocker_dir(reports_root) / f"{safe_ref(pointer_group)}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception(
            "failed to release sync-review blocker %s",
            pointer_group,
        )


def active_sync_fences(reports_root: Path) -> tuple[dict[str, Any], ...]:
    """Return live fences and garbage-collect crash leftovers.

    Inline review is fail-open. A process crash cannot leave the unattended
    scheduler permanently blocked, so a fence older than the review timeout
    envelope is ignored and removed.
    """

    now = datetime.now(UTC)
    active: list[dict[str, Any]] = []
    try:
        paths = [
            *_sync_fence_dir(reports_root).glob("*.json"),
            *_sync_blocker_dir(reports_root).glob("*.json"),
        ]
    except OSError:
        return ()
    for path in paths:
        payload = read_json(path)
        raw_created = str((payload or {}).get("created_at") or "")
        try:
            created = datetime.fromisoformat(raw_created)
            age = (now - created).total_seconds()
        except (TypeError, ValueError):
            age = _SYNC_FENCE_TTL_SECONDS + 1
        if payload is not None and 0 <= age < _SYNC_FENCE_TTL_SECONDS:
            active.append(payload)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to prune stale sync fence %s", path)
    return tuple(active)


def sync_fence_expiry_delay(
    fences: Sequence[Mapping[str, Any]],
) -> float | None:
    """Seconds until the oldest live sync fence becomes fail-open."""

    now = datetime.now(UTC)
    remaining: list[float] = []
    for payload in fences:
        try:
            created = datetime.fromisoformat(
                str(payload.get("created_at") or ""),
            )
        except ValueError:
            continue
        remaining.append(
            max(
                0.05,
                _SYNC_FENCE_TTL_SECONDS
                - (now - created).total_seconds()
                + 0.05,
            ),
        )
    return min(remaining) if remaining else None


# ── Durable automated-repair budget (per target, physical attempts) ────


def _repair_budget_path(reports_root: Path) -> Path:
    return reports_root / "repair-budget" / "state.json"


def _repair_budget_lock(reports_root: Path) -> CrossProcessFileLock:
    path = _repair_budget_path(reports_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return CrossProcessFileLock(path.with_name(f"{path.name}.lock"))


def admit_repair_attempts(
    reports_root: Path,
    *,
    target_refs: Sequence[str],
    attempt_id: str,
) -> dict[str, int] | None:
    """Atomically admit one automated repair delegation for all targets.

    ``attempt_id`` makes replay idempotent. The all-or-nothing update avoids
    partially consuming a multi-target delegation when one target is already
    spent. Returned values are the 1-based physical attempt numbers.
    """

    targets = sorted({str(item) for item in target_refs if str(item)})
    if not targets:
        return {}
    path = _repair_budget_path(reports_root)
    with _repair_budget_lock(reports_root):
        state = read_json(path) or {}
        entries = state.get("targets")
        if not isinstance(entries, dict):
            entries = {}
        result: dict[str, int] = {}
        for target_ref in targets:
            entry = entries.get(target_ref)
            if not isinstance(entry, dict):
                entry = {}
            attempt_ids = [
                str(item) for item in entry.get("attempt_ids") or []
            ]
            if attempt_id in attempt_ids:
                result[target_ref] = attempt_ids.index(attempt_id) + 1
                continue
            if len(attempt_ids) >= MAX_REPAIR_ATTEMPTS:
                return None
            result[target_ref] = len(attempt_ids) + 1
        now = datetime.now(UTC).isoformat()
        for target_ref in targets:
            entry = entries.get(target_ref)
            if not isinstance(entry, dict):
                entry = {}
            attempt_ids = [
                str(item) for item in entry.get("attempt_ids") or []
            ]
            if attempt_id not in attempt_ids:
                attempt_ids.append(attempt_id)
            entries[target_ref] = {
                "target_ref": target_ref,
                "attempt_ids": attempt_ids[-MAX_REPAIR_ATTEMPTS:],
                "attempts_started": len(attempt_ids),
                "updated_at": now,
            }
        state.update({"targets": entries, "updated_at": now})
        write_json(path, state)
    return result


__all__ = [
    "MAX_MEDIA_REVIEW_ROUNDS",
    "MAX_REPAIR_ATTEMPTS",
    "MAX_SYNC_REVIEW_ROUNDS",
    "active_sync_fences",
    "admit_media_round",
    "admit_repair_attempts",
    "admit_sync_review",
    "begin_sync_fence",
    "clear_sync_blocker",
    "end_sync_fence",
    "finalize_media_round",
    "hold_sync_blocker",
    "owner_token",
    "read_json",
    "release_media_claim",
    "safe_ref",
    "settle_sync_review",
    "sync_fence_expiry_delay",
    "write_json",
]
