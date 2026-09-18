# -*- coding: utf-8 -*-
"""On-disk 'updating' markers for plugin directory swaps."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..utils.io_utils import write_json_atomic
from .safe_fs import parse_optional_absolute, safe_remove

logger = logging.getLogger(__name__)

STATUS_PREPARED = "prepared"
STATUS_UPDATING = "updating"
STATUS_COMMITTED = "committed"


def updates_dir() -> Path:
    """Return the update-marker directory (created on demand)."""
    from ..constant import WORKING_DIR

    path = Path(WORKING_DIR) / "plugin_updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def marker_path(plugin_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in plugin_id)
    return updates_dir() / f"{safe}.json"


def write_updating_marker(
    plugin_id: str,
    *,
    backup_path: Path,
    target_path: Path,
    staging_path: Path | None = None,
    status: str = STATUS_PREPARED,
) -> None:
    """Record an in-flight directory swap so boot can restore it."""
    payload: dict[str, Any] = {
        "plugin_id": plugin_id,
        "status": status,
        "backup_path": str(backup_path),
        "target_path": str(target_path),
    }
    if staging_path is not None:
        payload["staging_path"] = str(staging_path)
    write_json_atomic(marker_path(plugin_id), payload)


def mark_update_committed(plugin_id: str) -> None:
    """Persist committed before leftover backups are deleted."""
    path = marker_path(plugin_id)
    if not path.is_file():
        return
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["status"] = STATUS_COMMITTED
    write_json_atomic(path, data)


def update_marker_status(plugin_id: str) -> str | None:
    """Return the on-disk update-marker status, if any."""
    path = marker_path(plugin_id)
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    status = str(data.get("status") or "").strip()
    return status or None


def clear_updating_marker(plugin_id: str) -> None:
    path = marker_path(plugin_id)
    if path.is_file():
        path.unlink()


def recover_interrupted_updates(owns_commit=None) -> list[str]:
    """Restore plugin dirs still marked updating. Returns restored ids."""
    from ..constant import WORKING_DIR

    root = Path(WORKING_DIR) / "plugin_updates"
    if not root.is_dir():
        return []
    restored: list[str] = []
    for path in sorted(root.glob("*.json")):
        plugin_id = _peek_marker_plugin_id(path)
        if (
            plugin_id
            and owns_commit is not None
            and not owns_commit(plugin_id)
        ):
            continue
        restored_id = _restore_one_marker(path)
        if restored_id:
            restored.append(restored_id)
    return restored


def _peek_marker_plugin_id(path: Path) -> str | None:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return str(data.get("plugin_id") or path.stem) or None


def _restore_one_marker(path: Path) -> str | None:
    try:
        data: dict[str, Any] = json.loads(
            path.read_text(encoding="utf-8"),
        )
    except (OSError, json.JSONDecodeError):
        logger.warning("Corrupt update marker at %s", path)
        return None
    status = str(data.get("status") or "")
    plugin_id = str(data.get("plugin_id") or path.stem)
    backup = parse_optional_absolute(data.get("backup_path"))
    target = parse_optional_absolute(data.get("target_path"))
    staging = parse_optional_absolute(data.get("staging_path"))
    if status == STATUS_COMMITTED:
        if backup is not None:
            safe_remove(backup, purpose="drop committed update backup")
        if staging is not None:
            safe_remove(staging, purpose="drop committed update staging")
        path.unlink(missing_ok=True)
        return None
    if status not in {STATUS_PREPARED, STATUS_UPDATING}:
        return None
    if staging is not None:
        safe_remove(staging, purpose="drop prepared update staging")
    if backup is None or target is None or not backup.exists():
        logger.warning(
            "Update marker for '%s' has no usable backup; leaving it",
            plugin_id,
        )
        return None
    if target.exists() and not backup.exists():
        path.unlink(missing_ok=True)
        return None
    if target.exists():
        safe_remove(target, purpose="remove partial update target")
    shutil.move(str(backup), str(target))
    path.unlink(missing_ok=True)
    logger.warning(
        "Restored plugin '%s' from interrupted update backup",
        plugin_id,
    )
    return plugin_id
