# -*- coding: utf-8 -*-
"""On-disk 'updating' markers for plugin directory swaps."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..utils.io_utils import write_json_atomic

logger = logging.getLogger(__name__)


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
) -> None:
    """Record an in-flight directory swap so boot can restore it."""
    write_json_atomic(
        marker_path(plugin_id),
        {
            "plugin_id": plugin_id,
            "status": "updating",
            "backup_path": str(backup_path),
            "target_path": str(target_path),
        },
    )


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
    if data.get("status") != "updating":
        return None
    plugin_id = str(data.get("plugin_id") or path.stem)
    backup = Path(data.get("backup_path") or "")
    target = Path(data.get("target_path") or "")
    if not backup.exists() or not target:
        logger.warning(
            "Update marker for '%s' has no usable backup; leaving it",
            plugin_id,
        )
        return None
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    shutil.move(str(backup), str(target))
    path.unlink(missing_ok=True)
    logger.warning(
        "Restored plugin '%s' from interrupted update backup",
        plugin_id,
    )
    return plugin_id
