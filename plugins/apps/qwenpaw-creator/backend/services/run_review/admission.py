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
from typing import Any, Mapping
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

# Advisory rounds per artifact slot (media) / per pointer group (sync).
MAX_MEDIA_REVIEW_ROUNDS = 2
MAX_SYNC_REVIEW_ROUNDS = 2


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
        if rounds_completed >= MAX_MEDIA_REVIEW_ROUNDS:
            return None
        round_number = rounds_completed + 1
        now = datetime.now(UTC).isoformat()
        state.update(
            {
                "slot_id": slot_id,
                "rounds_completed": rounds_completed,
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


__all__ = [
    "MAX_MEDIA_REVIEW_ROUNDS",
    "MAX_SYNC_REVIEW_ROUNDS",
    "admit_media_round",
    "admit_sync_review",
    "finalize_media_round",
    "owner_token",
    "read_json",
    "release_media_claim",
    "safe_ref",
    "settle_sync_review",
    "write_json",
]
