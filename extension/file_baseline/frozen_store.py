# -*- coding: utf-8
"""Immutable frozen snapshots of approved baseline files (trust anchor copies)."""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .drift_gate import sha256_file
from .paths import agent_state_dir, file_baseline_root, frozen_agent_dir
from .write_context import is_file_baseline_maintenance

logger = logging.getLogger(__name__)

_ANCHORS_NAME = "trust_anchors.json"


def trust_anchors_path(working_dir: Path) -> Path:
    return file_baseline_root(working_dir) / _ANCHORS_NAME


def frozen_approved_path(working_dir: Path, agent_id: str, rel_path: str) -> Path:
    normalized = rel_path.replace("\\", "/")
    return frozen_agent_dir(working_dir, agent_id) / "approved" / normalized


@dataclass(frozen=True)
class FrozenEntry:
    workspace_sha256: str
    approved_snapshot_sha256: str
    frozen_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_anchors(working_dir: Path) -> dict[str, Any]:
    path = trust_anchors_path(working_dir)
    if not path.is_file():
        return {"version": 1, "agents": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"version": 1, "agents": {}}
    data.setdefault("version", 1)
    data.setdefault("agents", {})
    return data


def _save_anchors(working_dir: Path, data: dict[str, Any]) -> None:
    if not is_file_baseline_maintenance():
        raise RuntimeError("trust anchors may only be updated under maintenance context")
    path = trust_anchors_path(working_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    from .os_readonly import temporary_os_writable

    writable: list[Path] = []
    anchors_file = trust_anchors_path(working_dir)
    if anchors_file.is_file():
        writable.append(anchors_file)
    with temporary_os_writable(writable):
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)


def get_frozen_entry(
    working_dir: Path,
    agent_id: str,
    rel_path: str,
) -> FrozenEntry | None:
    data = _load_anchors(working_dir)
    agent_data = data.get("agents", {}).get(agent_id, {})
    entry = agent_data.get(rel_path.replace("\\", "/"))
    if not isinstance(entry, dict):
        return None
    workspace_sha = str(entry.get("workspace_sha256") or "")
    approved_sha = str(entry.get("approved_snapshot_sha256") or "")
    frozen_at = str(entry.get("frozen_at") or "")
    if not workspace_sha or not approved_sha:
        return None
    return FrozenEntry(
        workspace_sha256=workspace_sha,
        approved_snapshot_sha256=approved_sha,
        frozen_at=frozen_at,
    )


def sync_frozen_agent_paths(
    working_dir: Path,
    agent_id: str,
    *,
    workspace: Path,
    state_dir: Path,
    rel_paths: list[str],
) -> None:
    """Copy approved snapshots to frozen/ and update trust anchors (maintenance only)."""
    if not rel_paths:
        return
    if not is_file_baseline_maintenance():
        raise RuntimeError("frozen sync requires maintenance context")

    data = _load_anchors(working_dir)
    agents = data.setdefault("agents", {})
    agent_data = agents.setdefault(agent_id, {})
    now = _utc_now()

    for rel_path in rel_paths:
        normalized = rel_path.replace("\\", "/")
        live_approved = state_dir / "approved" / normalized
        frozen_path = frozen_approved_path(working_dir, agent_id, normalized)
        workspace_target = workspace / normalized

        if live_approved.is_file():
            frozen_path.parent.mkdir(parents=True, exist_ok=True)
            from .os_readonly import temporary_os_writable

            writable: list[Path] = []
            if frozen_path.is_file():
                writable.append(frozen_path)
            with temporary_os_writable(writable):
                shutil.copy2(live_approved, frozen_path)
            approved_sha = sha256_file(live_approved)
        elif frozen_path.is_file():
            approved_sha = sha256_file(frozen_path)
        else:
            logger.warning(
                "frozen_sync_skip agent_id=%s path=%s reason=no_approved_snapshot",
                agent_id,
                normalized,
            )
            continue

        workspace_sha = sha256_file(workspace_target) if workspace_target.is_file() else ""
        agent_data[normalized] = {
            "workspace_sha256": workspace_sha,
            "approved_snapshot_sha256": approved_sha,
            "frozen_at": now,
        }
        logger.info(
            "frozen_sync agent_id=%s path=%s workspace_sha=%s approved_sha=%s",
            agent_id,
            normalized,
            workspace_sha[:12],
            approved_sha[:12],
        )

    _save_anchors(working_dir, data)


def restore_workspace_from_frozen(
    working_dir: Path,
    agent_id: str,
    *,
    workspace: Path,
    rel_path: str,
) -> bool:
    """Restore workspace file from frozen approved snapshot. Returns True when copied."""
    normalized = rel_path.replace("\\", "/")
    frozen_path = frozen_approved_path(working_dir, agent_id, normalized)
    if not frozen_path.is_file():
        return False
    target = workspace / normalized
    target.parent.mkdir(parents=True, exist_ok=True)
    from .os_readonly import temporary_os_writable

    writable: list[Path] = []
    if target.is_file():
        writable.append(target)
    with temporary_os_writable(writable):
        shutil.copy2(frozen_path, target)
    logger.info(
        "frozen_restore_workspace agent_id=%s path=%s sha256=%s",
        agent_id,
        normalized,
        sha256_file(target)[:12],
    )
    return True


def live_approved_matches_frozen(
    working_dir: Path,
    agent_id: str,
    state_dir: Path,
    rel_path: str,
) -> bool:
    entry = get_frozen_entry(working_dir, agent_id, rel_path)
    if entry is None:
        return True
    live = state_dir / "approved" / rel_path.replace("\\", "/")
    if not live.is_file():
        return False
    try:
        return sha256_file(live) == entry.approved_snapshot_sha256
    except OSError:
        return False


def repair_mutable_state_from_frozen(
    working_dir: Path,
    agent_id: str,
    *,
    state_dir: Path,
    rel_paths: list[str],
) -> list[str]:
    """Copy frozen approved back into mutable state_dir for drifted paths."""
    if not is_file_baseline_maintenance():
        raise RuntimeError("state repair requires maintenance context")
    repaired: list[str] = []
    for rel_path in rel_paths:
        normalized = rel_path.replace("\\", "/")
        if live_approved_matches_frozen(working_dir, agent_id, state_dir, normalized):
            continue
        frozen_path = frozen_approved_path(working_dir, agent_id, normalized)
        if not frozen_path.is_file():
            continue
        live = state_dir / "approved" / normalized
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frozen_path, live)
        repaired.append(normalized)
        logger.warning(
            "frozen_repair_mutable_approved agent_id=%s path=%s sha256=%s",
            agent_id,
            normalized,
            sha256_file(live)[:12],
        )
    return repaired


def snapshot_state_hashes(
    working_dir: Path,
    agent_id: str,
    rel_paths: list[str],
) -> dict[str, str]:
    """Return map of logical keys -> sha256 for mutable + frozen state files."""
    state_dir = agent_state_dir(working_dir, agent_id)
    out: dict[str, str] = {}
    baselines = state_dir / "baselines.json"
    if baselines.is_file():
        try:
            out["baselines.json"] = sha256_file(baselines)
        except OSError:
            out["baselines.json"] = ""
    for rel_path in rel_paths:
        normalized = rel_path.replace("\\", "/")
        live = state_dir / "approved" / normalized
        key = f"approved/{normalized}"
        if live.is_file():
            try:
                out[key] = sha256_file(live)
            except OSError:
                out[key] = ""
    anchors = trust_anchors_path(working_dir)
    if anchors.is_file():
        try:
            out["trust_anchors.json"] = sha256_file(anchors)
        except OSError:
            out["trust_anchors.json"] = ""
    return out


def detect_state_hash_drift(
    before: dict[str, str],
    after: dict[str, str],
) -> list[str]:
    drifted: list[str] = []
    for key, old_sha in before.items():
        new_sha = after.get(key)
        if new_sha is not None and new_sha != old_sha:
            drifted.append(key)
    for key in after:
        if key not in before and after[key]:
            drifted.append(key)
    return drifted
