# -*- coding: utf-8 -*-
"""WorkspaceManager — create, list, activate, delete workspaces."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from .models import WorkspaceInfo, WorkspacesFile

logger = logging.getLogger(__name__)

# Directories that belong to a workspace (moved during migration).
_WORKSPACE_DIRS = (
    "active_skills",
    "customized_skills",
    "memory",
    "sessions",
    "custom_channels",
)

# Files that belong to a workspace (moved during migration).
_WORKSPACE_FILES = (
    "config.json",
    "jobs.json",
    "chats.json",
    "HEARTBEAT.md",
    "audit.jsonl",
)

# Directories/files that stay global (not moved).
_GLOBAL_ITEMS = (
    "models",
    "providers.json",
    "tokens.json",
    "workspaces.json",
    "workspaces",
    "global",
    "envs.json",
)


class WorkspaceManager:
    """Manages multiple workspaces under WORKING_DIR.

    Directory layout::

        ~/.copaw/
        ├── workspaces.json
        ├── global/          (providers, tokens — shared)
        ├── models/          (local models — shared)
        └── workspaces/
            ├── <ws_id>/     (per-workspace config, jobs, memory, …)
            └── …
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._ws_dir = root / "workspaces"
        self._registry_path = root / "workspaces.json"
        self._data: WorkspacesFile = WorkspacesFile()
        self._load()

    # -- public API -----------------------------------------------------------

    def create(self, name: str) -> WorkspaceInfo:
        """Create a new workspace and return its info."""
        ws = WorkspaceInfo(name=name)
        ws.path = ws.id
        ws_path = self._ws_dir / ws.id
        ws_path.mkdir(parents=True, exist_ok=True)
        self._data.workspaces.append(ws)
        # If this is the only workspace, activate it.
        if len(self._data.workspaces) == 1:
            ws.is_active = True
            self._data.active_id = ws.id
        self._save()
        logger.info("Created workspace [%s] name=%s", ws.id, name)
        return ws

    def list_workspaces(self) -> List[WorkspaceInfo]:
        """Return all workspace entries."""
        return list(self._data.workspaces)

    def get_active(self) -> Optional[WorkspaceInfo]:
        """Return the currently active workspace, or None."""
        for ws in self._data.workspaces:
            if ws.id == self._data.active_id:
                return ws
        return None

    def get_active_path(self) -> Path:
        """Return the filesystem path of the active workspace.

        Falls back to WORKING_DIR itself if no workspace is configured
        (pre-migration compatibility).
        """
        active = self.get_active()
        if active:
            return self._ws_dir / active.path
        return self._root

    def activate(self, workspace_id: str) -> bool:
        """Set *workspace_id* as active. Returns True if found."""
        for ws in self._data.workspaces:
            ws.is_active = ws.id == workspace_id
        found = any(ws.id == workspace_id for ws in self._data.workspaces)
        if found:
            self._data.active_id = workspace_id
            self._save()
            logger.info("Activated workspace [%s]", workspace_id)
        return found

    def delete(self, workspace_id: str) -> bool:
        """Delete a workspace by id. Cannot delete the active workspace."""
        if workspace_id == self._data.active_id:
            logger.warning("Cannot delete active workspace [%s]", workspace_id)
            return False
        before = len(self._data.workspaces)
        ws_to_delete = None
        for ws in self._data.workspaces:
            if ws.id == workspace_id:
                ws_to_delete = ws
                break
        if ws_to_delete is None:
            return False
        self._data.workspaces.remove(ws_to_delete)
        if len(self._data.workspaces) < before:
            # Remove workspace directory.
            ws_path = self._ws_dir / ws_to_delete.path
            if ws_path.exists():
                shutil.rmtree(ws_path, ignore_errors=True)
            self._save()
            logger.info("Deleted workspace [%s]", workspace_id)
            return True
        return False

    def is_migrated(self) -> bool:
        """Check if the workspace registry exists (migration completed)."""
        return self._registry_path.exists()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        if not self._registry_path.exists():
            self._data = WorkspacesFile()
            return
        try:
            raw = json.loads(self._registry_path.read_text(encoding="utf-8"))
            self._data = WorkspacesFile.model_validate(raw)
        except Exception:
            logger.exception("Failed to load workspaces.json")
            self._data = WorkspacesFile()

    def _save(self) -> None:
        try:
            self._registry_path.parent.mkdir(parents=True, exist_ok=True)
            data = self._data.model_dump()
            self._registry_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save workspaces.json")
