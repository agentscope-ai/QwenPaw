# -*- coding: utf-8 -*-
"""Synchronous backup creation used by the application job manager."""
from __future__ import annotations

import logging
import threading
import zipfile
from typing import Any, Callable

from .._utils.constants import META_FILE, zip_path
from .._utils.meta import finalize_backup_meta
from .._utils.signing import replace_meta_with_local_signature
from ..models import BackupMeta
from ...config.utils import load_config
from ...constant import BACKUP_DIR
from .create_helpers import add_files_to_zip

logger = logging.getLogger(__name__)


class BackupCancelled(Exception):
    """Raised when cooperative cancellation stops archive creation."""


def _compute_initial_agents(
    req_agents: list[str],
    config,
) -> tuple[list[tuple[str, Any]], list[str]]:
    """Return ``((agent_id, profile_ref) pairs, missing_agent_ids)``.

    Only agents that exist in the current config are included in the first
    list; IDs not found in the config are returned as *missing_agent_ids*
    (the agent may have been deleted since the backup scope was defined).
    """
    valid: list[tuple[str, Any]] = []
    missing: list[str] = []
    for aid in req_agents:
        ref = config.agents.profiles.get(aid)
        if ref is not None:
            valid.append((aid, ref))
        else:
            missing.append(aid)
    return valid, missing


def _write_meta_and_finalize(
    zf: zipfile.ZipFile,
    meta: BackupMeta,
    agent_count: int,
    progress: Callable[[dict[str, Any]], None],
) -> None:
    """Finalize *meta*, emit a saving event, and write meta.json into *zf*."""
    finalize_backup_meta(meta, agent_count)
    meta.accepted_via_trust = False
    meta.signature = None
    progress({"type": "saving", "percent": 90})
    zf.writestr(META_FILE, meta.model_dump_json(indent=2))


def create_backup(
    meta: BackupMeta,
    req_agents: list[str],
    progress: Callable[[dict[str, Any]], None],
    stop_event: threading.Event,
) -> BackupMeta:
    """Create one archive and return its finalized metadata.

    The caller owns the thread and task lifecycle.  This function only owns
    compression, cooperative cancellation, and atomic archive publication.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = zip_path(meta.id)
    tmp = dest.with_suffix(".tmp")
    try:
        _compress_to_tmp(meta, req_agents, progress, stop_event, tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return meta


def _compress_to_tmp(
    meta: BackupMeta,
    req_agents: list[str],
    progress: Callable[[dict[str, Any]], None],
    stop_event: threading.Event,
    tmp,
    dest,
) -> None:
    """Write backup zip to *tmp* and atomically replace *dest* on success."""
    # Remove any pre-existing tmp file from a previous crashed run so that
    # zipfile.ZipFile(..., "w") starts from a clean slate.  On Windows an
    # open handle on this path would raise OSError here rather than
    # silently appending to a stale file.
    tmp.unlink(missing_ok=True)
    if stop_event.is_set():
        raise BackupCancelled()

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        config = load_config()
        if meta.scope.include_agents:
            valid_agents, missing_agents = _compute_initial_agents(
                req_agents,
                config,
            )
        else:
            valid_agents, missing_agents = [], []
        progress(
            {"type": "start", "total_agents": len(valid_agents), "percent": 0},
        )
        if missing_agents:
            logger.warning(
                "Skipping agents not found in config: %s",
                missing_agents,
            )

        def progress_callback(current, total, agent_id):
            percent = int(10 + 75 * current / max(total, 1))
            progress(
                {
                    "type": "agent",
                    "agent_id": agent_id,
                    "index": current,
                    "total": total,
                    "percent": percent,
                },
            )

        backed_up_agents = add_files_to_zip(
            zf,
            meta,
            progress_callback,
            stop_event,
            valid_agents=valid_agents,
        )

        if stop_event.is_set():
            raise BackupCancelled()
        _write_meta_and_finalize(zf, meta, len(backed_up_agents), progress)

    if stop_event.is_set():
        raise BackupCancelled()

    signed_meta = replace_meta_with_local_signature(tmp, meta, dest_zip=dest)
    if stop_event.is_set():
        dest.unlink(missing_ok=True)
        raise BackupCancelled()
    meta.signature = signed_meta.signature
    meta.accepted_via_trust = signed_meta.accepted_via_trust
    tmp.unlink(missing_ok=True)
