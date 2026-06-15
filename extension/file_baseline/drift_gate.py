# -*- coding: utf-8
"""Content-hash gate: skip drift emission when bytes still match approved baseline."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapter import SoulGuardianAdapter

logger = logging.getLogger(__name__)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return sha256_bytes(b"")
    return sha256_bytes(path.read_bytes())


def status_shas_for_path(
    status: dict,
    rel_path: str,
) -> tuple[str, str]:
    by_path = {
        str(item.get("path") or ""): item
        for item in status.get("files", [])
    }
    info = by_path.get(rel_path, {})
    approved = str(info.get("approvedSha") or "")
    current = str(info.get("currentSha") or "")
    return approved, current


def content_matches_baseline(
    *,
    approved_sha256: str,
    current_sha256: str,
) -> bool:
    """Return True when both SHAs are present and equal."""
    if not approved_sha256 or not current_sha256:
        return False
    return approved_sha256 == current_sha256


def path_status_from_adapter(
    adapter: "SoulGuardianAdapter",
    *,
    workspace_root: Path,
    state_dir: Path,
    rel_path: str,
) -> tuple[str, str]:
    status = adapter.status(workspace_root=workspace_root, state_dir=state_dir)
    return status_shas_for_path(status, rel_path)


def should_skip_drift_emit(
    *,
    approved_sha256: str,
    current_sha256: str,
    agent_id: str,
    rel_path: str,
    provenance: str,
) -> bool:
    if content_matches_baseline(
        approved_sha256=approved_sha256,
        current_sha256=current_sha256,
    ):
        logger.info(
            "file_baseline_drift_skipped agent_id=%s path=%s provenance=%s "
            "reason=content_matches_baseline sha256=%s",
            agent_id,
            rel_path,
            provenance,
            current_sha256[:12],
        )
        return True
    return False
