# -*- coding: utf-8 -*-
"""Auto-migrate existing ~/.copaw/ layout to multi-workspace structure.

On first run after the upgrade, moves workspace-scoped files/dirs
into ``workspaces/default/`` and creates ``workspaces.json``.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .manager import (
    WorkspaceManager,
    _WORKSPACE_DIRS,
    _WORKSPACE_FILES,
)

logger = logging.getLogger(__name__)

_DEFAULT_WS_NAME = "default"


def ensure_workspace_layout(root: Path) -> WorkspaceManager:
    """Ensure the multi-workspace directory layout exists.

    If ``workspaces.json`` does not exist, migrates the legacy flat
    layout into a ``workspaces/default/`` workspace.

    Returns:
        A ready-to-use WorkspaceManager instance.
    """
    mgr = WorkspaceManager(root=root)
    if mgr.is_migrated():
        return mgr

    logger.info("Migrating legacy layout to multi-workspace structure …")

    ws = mgr.create(name=_DEFAULT_WS_NAME)
    ws_path = root / "workspaces" / ws.path

    # Move workspace-scoped directories.
    for dirname in _WORKSPACE_DIRS:
        src = root / dirname
        if src.exists() and src.is_dir():
            dst = ws_path / dirname
            if not dst.exists():
                shutil.move(str(src), str(dst))
                logger.debug("Moved dir %s → %s", src, dst)

    # Move workspace-scoped files.
    for filename in _WORKSPACE_FILES:
        src = root / filename
        if src.exists() and src.is_file():
            dst = ws_path / filename
            if not dst.exists():
                shutil.move(str(src), str(dst))
                logger.debug("Moved file %s → %s", src, dst)

    # Create global/ directory for shared resources.
    global_dir = root / "global"
    global_dir.mkdir(parents=True, exist_ok=True)

    # Move global files into global/ (if they exist at root level).
    for name in ("providers.json", "tokens.json"):
        src = root / name
        if src.exists() and src.is_file():
            dst = global_dir / name
            if not dst.exists():
                shutil.move(str(src), str(dst))
                logger.debug("Moved global %s → %s", src, dst)

    mgr.activate(ws.id)
    logger.info(
        "Migration complete: default workspace [%s] created at %s",
        ws.id,
        ws_path,
    )
    return mgr
