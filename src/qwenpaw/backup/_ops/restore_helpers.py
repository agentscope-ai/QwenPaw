# -*- coding: utf-8 -*-
"""Pure-function helpers for restore operations.

These functions are free of ``self`` so they can be unit-tested in isolation.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .._utils.constants import PREFIX_SECRETS, PREFIX_WORKSPACES
from ...constant import BACKUP_DIR, SECRET_DIR, WORKING_DIR

logger = logging.getLogger(__name__)

_MASTER_KEY = ".master_key"


def collect_workspace_agents_from_zip(zf: zipfile.ZipFile) -> set[str]:
    """Return the set of agent IDs whose workspaces are stored in *zf*."""
    agents: set[str] = set()
    for info in zf.infolist():
        if info.filename.startswith(PREFIX_WORKSPACES) and not info.is_dir():
            parts = info.filename.split("/", 3)
            if len(parts) >= 4:
                agents.add(parts[2])
    return agents


def resolve_workspace_dst(
    aid: str,
    ref,  # AgentProfileRef | None
    default_workspace_dir: str | None,
) -> tuple[Path, bool]:
    """Return ``(destination_path, is_new_agent)``.

    ``is_new_agent`` is ``True`` when *ref* is ``None`` (agent not present in
    the current config).  The caller is responsible for registering a new
    ``AgentProfileRef`` in ``config.agents.profiles`` when ``is_new_agent``
    is ``True``.

    When *ref* exists but its ``workspace_dir`` does not exist locally (e.g.
    the backup was made on a different machine), we fall back to the default
    location rather than extracting files into a stale cross-host path.  The
    caller's ``_apply_workspace_paths_and_save`` will then persist the
    corrected path back into config.

    All returned paths are fully resolved (absolute, symlinks expanded) so
    that ``str(dst)`` is always canonical regardless of which branch is taken.
    """
    if ref is not None:
        dst = Path(ref.workspace_dir).expanduser()
        if dst.exists():
            return dst.resolve(), False
        # Existing agent in config but local path is absent (cross-machine
        # restore or manually deleted directory) – fall through to defaults.

    if default_workspace_dir:
        dst = Path(default_workspace_dir).expanduser() / aid
    else:
        dst = Path(WORKING_DIR) / "workspaces" / aid

    # Resolve even when the directory does not yet exist so that the returned
    # path string is always in fully-qualified, canonical form.
    try:
        return dst.resolve(), ref is None
    except OSError:
        # resolve() can fail on some platforms when parts of the path don't
        # exist; fall back to absolute path without symlink expansion.
        return dst.absolute(), ref is None


def rewrite_agent_workspace_dir(dst: Path, aid: str) -> None:
    """Rewrite ``workspace_dir`` inside ``{dst}/agent.json`` to *dst*.

    Corrects cross-device path drift (e.g. different username or WORKING_DIR
    on the source machine) for both new and pre-existing agents.

    The write is performed atomically: the new content is first written to a
    sibling ``.tmp`` file, then renamed over the original so a mid-write crash
    never leaves a truncated or empty ``agent.json``.
    """
    agent_json_path = dst / "agent.json"
    if not agent_json_path.is_file():
        return
    tmp_path = agent_json_path.with_suffix(".json.tmp")
    try:
        with open(agent_json_path, "r", encoding="utf-8") as f:
            agent_data = json.load(f)
        agent_data["workspace_dir"] = str(dst)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(agent_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, agent_json_path)
        logger.debug("Rewrote workspace_dir in agent.json for agent '%s'", aid)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        logger.warning(
            "Failed to rewrite workspace_dir in agent.json for agent '%s'",
            aid,
        )


def handle_master_key_conflict(
    zf: zipfile.ZipFile,
    bak_dir: Path | None = None,
) -> Path | None:
    """Back up the current master key when the backup's key differs.

    If the backup contains a ``.master_key`` that does not match the one
    currently on disk, the existing key is copied to
    ``BACKUP_DIR/_pre_restore_keys/<UTC-timestamp>.master_key.bak``
    (or *bak_dir* if provided) so that credentials encrypted with the old
    key can still be decrypted if needed.

    The bak file is intentionally written **outside** SECRET_DIR so that it
    is not clobbered by the subsequent ``extract_to_tmp`` + ``commit_tmp`` that
    replaces the entire secrets directory.

    Returns the path of the backup file, or ``None`` if no backup was needed.
    """
    master_key_zip_entry = f"{PREFIX_SECRETS}{_MASTER_KEY}"
    current_master_key = SECRET_DIR / _MASTER_KEY

    if not (
        current_master_key.is_file() and master_key_zip_entry in zf.namelist()
    ):
        return None

    with zf.open(master_key_zip_entry) as f:
        backup_mk_bytes = f.read()
    with open(current_master_key, "rb") as f:
        current_mk_bytes = f.read()

    if backup_mk_bytes == current_mk_bytes:
        return None

    if bak_dir is None:
        bak_dir = BACKUP_DIR / "_pre_restore_keys"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = bak_dir / f"{ts}.master_key.bak"
    try:
        bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current_master_key, bak)
        return bak
    except OSError as exc:
        logger.error(
            "Failed to back up current master_key before restore: %s",
            exc,
        )
        return None
