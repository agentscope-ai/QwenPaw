# -*- coding: utf-8 -*-
"""Backend-neutral lifecycle for one artifact-producing turn."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from ...utils.io_utils import run_sync_io
from .collector import ArtifactCollectorGroup
from .context import (
    reset_current_artifact_collector,
    set_current_artifact_collector,
)
from .coordinator import ArtifactCoordinator, ArtifactTurnHandle
from .models import ArtifactRoot
from .serializer import serialize_manifest
from .snapshot import capture_workspace_snapshot


def resolve_artifact_roots(
    workspace_dir: Path,
    project_dir: Path | None,
) -> dict[ArtifactRoot, Path]:
    """Return non-overlapping roots pinned for one runtime turn."""
    workspace_root = workspace_dir.expanduser().resolve()
    if project_dir is None:
        return {"workspace": workspace_root}

    project_root = project_dir.expanduser().resolve()
    if project_root == workspace_root or project_root.is_relative_to(
        workspace_root,
    ):
        return {"workspace": workspace_root}
    if workspace_root.is_relative_to(project_root):
        return {"project": project_root}
    return {
        "workspace": workspace_root,
        "project": project_root,
    }


def _create_collector(
    roots: dict[ArtifactRoot, Path],
) -> ArtifactCollectorGroup:
    before = {
        root: capture_workspace_snapshot(path) for root, path in roots.items()
    }
    return ArtifactCollectorGroup(roots, before)


def _collect_manifest(
    collector: ArtifactCollectorGroup,
    *,
    agent_id: str,
    session_id: str,
    turn_id: str,
    include_snapshot_changes: bool = True,
    root_refs: dict[ArtifactRoot, str] | None = None,
) -> dict | None:
    after = {
        root: capture_workspace_snapshot(path)
        for root, path in collector.roots.items()
    }
    collection = collector.collect(
        after,
        include_snapshot_changes=include_snapshot_changes,
    )
    if (
        not collection.artifacts
        and not collection.changes
        and not collection.truncated
    ):
        return None
    return serialize_manifest(
        collection,
        agent_id=agent_id,
        chat_id=session_id,
        turn_id=turn_id,
        root_refs=root_refs,
    )


def _get_coordinator(workspace: Any) -> ArtifactCoordinator:
    coordinator = getattr(workspace, "artifact_coordinator", None)
    if coordinator is None:
        coordinator = ArtifactCoordinator()
        setattr(workspace, "artifact_coordinator", coordinator)
    return coordinator


class ArtifactTurn:
    """Own artifact state shared by native and third-party backends."""

    def __init__(
        self,
        *,
        workspace: Any,
        workspace_dir: Path,
        project_dir: Path | None,
        agent_id: str,
        session_id: str,
        turn_id: str,
    ) -> None:
        self._workspace = workspace
        self._workspace_dir = workspace_dir
        self._project_dir = project_dir
        self._roots: dict[ArtifactRoot, Path] = {}
        self._agent_id = agent_id
        self._session_id = session_id
        self._turn_id = turn_id
        self._coordinator = _get_coordinator(workspace)
        self._root_refs: dict[ArtifactRoot, str] = {}
        self._handle: ArtifactTurnHandle | None = None
        self._collector: ArtifactCollectorGroup | None = None
        self._collector_token = None
        self._manifest: dict | None = None
        self._finalized = False

    @property
    def collector(self) -> ArtifactCollectorGroup | None:
        """Return the active collector for compatibility and tests."""
        return self._collector

    @property
    def manifest(self) -> dict | None:
        """Return the finalized manifest, if the turn produced one."""
        return self._manifest

    @property
    def root_mappings(self) -> dict[str, dict[str, str]]:
        """Return trusted root mappings for session persistence."""
        return {
            self._root_refs[root]: {
                "root": root,
                "path": str(path),
            }
            for root, path in self._roots.items()
        }

    async def begin(self) -> None:
        """Capture initial state and expose the collector to file tools."""
        if self._collector is not None:
            return
        self._roots = await run_sync_io(
            resolve_artifact_roots,
            self._workspace_dir,
            self._project_dir,
        )
        self._root_refs = {
            root: f"root_{uuid.uuid4().hex}" for root in self._roots
        }
        self._handle = await self._coordinator.begin(
            self._turn_id,
            self._roots,
        )
        try:
            self._collector = await run_sync_io(
                _create_collector,
                self._roots,
            )
            self._collector_token = set_current_artifact_collector(
                self._collector,
            )
        except BaseException:
            await self._coordinator.finish(self._handle)
            self._handle = None
            raise

    async def finalize(self) -> dict | None:
        """Collect and serialize final state exactly once."""
        if self._finalized:
            return self._manifest
        self._finalized = True
        if self._collector is None:
            return None
        self._manifest = await run_sync_io(
            _collect_manifest,
            self._collector,
            agent_id=self._agent_id,
            session_id=self._session_id,
            turn_id=self._turn_id,
            include_snapshot_changes=not (
                self._handle is not None and self._handle.overlapped
            ),
            root_refs=self._root_refs,
        )
        return self._manifest

    async def cleanup(self) -> None:
        """Reset ContextVar state and remove the active turn."""
        token = self._collector_token
        self._collector_token = None
        if token is not None:
            reset_current_artifact_collector(token)
        await self._coordinator.finish(self._handle)
        self._handle = None


__all__ = ["ArtifactTurn", "resolve_artifact_roots"]
