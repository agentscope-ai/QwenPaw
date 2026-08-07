# -*- coding: utf-8 -*-
"""Collect workspace artifacts around one runtime turn."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..agents.artifacts import (
    ArtifactCollectorGroup,
    ArtifactRoot,
    capture_workspace_snapshot,
    reset_current_artifact_collector,
    serialize_manifest,
    set_current_artifact_collector,
)
from ..config.context import get_current_project_dir
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase
from ..utils.io_utils import run_sync_io
from .base import LifecycleHook

logger = logging.getLogger(__name__)

_COLLECTOR_KEY = "workspace_artifact_collector"
_MANIFEST_KEY = "workspace_artifact_manifest"
_COLLECTOR_TOKEN_KEY = "workspace_artifact_collector_token"
_TURN_LOCK_KEY = "workspace_artifact_turn_lock"


def _resolve_artifact_roots(
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
    """Build collectors and initial snapshots in one worker task."""
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
) -> dict | None:
    """Capture, merge, and serialize final root snapshots."""
    after = {
        root: capture_workspace_snapshot(path)
        for root, path in collector.roots.items()
    }
    collection = collector.collect(after)
    if not collection.artifacts and not collection.changes:
        return None
    return serialize_manifest(
        collection,
        agent_id=agent_id,
        chat_id=session_id,
        turn_id=turn_id,
    )


def _release_turn_lock(ctx: HookContext) -> None:
    """Release this turn's workspace lock exactly once."""
    lock = ctx.extras.pop(_TURN_LOCK_KEY, None)
    if lock is not None and lock.locked():
        lock.release()


class WorkspaceArtifactsHook(LifecycleHook):
    """Capture the initial workspace state outside the event loop."""

    name = "workspace_artifacts"
    priority = 20
    phase = Phase.PRE_DISPATCH

    async def run(self, ctx: HookContext) -> HookResult:
        """Capture the initial workspace state for the current turn."""
        if ctx.workspace_dir is None:
            return HookResult()
        lock = getattr(ctx.workspace, "artifact_turn_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(ctx.workspace, "artifact_turn_lock", lock)
        await lock.acquire()
        ctx.extras[_TURN_LOCK_KEY] = lock
        try:
            roots = _resolve_artifact_roots(
                ctx.workspace_dir,
                get_current_project_dir(),
            )
            collector = await run_sync_io(
                _create_collector,
                roots,
            )
            ctx.extras[_COLLECTOR_KEY] = collector
            token = set_current_artifact_collector(collector)
            ctx.extras[_COLLECTOR_TOKEN_KEY] = token
        except asyncio.CancelledError:
            _release_turn_lock(ctx)
            raise
        except Exception:
            logger.debug("workspace artifact pre-scan failed", exc_info=True)
            _release_turn_lock(ctx)
        return HookResult()


class WorkspaceArtifactsFinalizeHook(LifecycleHook):
    """Collect the final workspace state before session persistence."""

    name = "workspace_artifacts_finalize"
    priority = 80
    phase = Phase.POST_RESPONSE
    before = ("session_save",)

    async def run(self, ctx: HookContext) -> HookResult:
        """Store a serialized manifest for the runtime and save hook."""
        collector = ctx.extras.get(_COLLECTOR_KEY)
        if collector is None:
            return HookResult()
        try:
            manifest = await run_sync_io(
                _collect_manifest,
                collector,
                agent_id=ctx.agent_id,
                session_id=ctx.session_id,
                turn_id=ctx.extras.get("turn_id", ctx.session_id),
            )
            if manifest is not None:
                ctx.extras[_MANIFEST_KEY] = manifest
        except Exception:
            logger.debug("workspace artifact post-scan failed", exc_info=True)
        return HookResult()


class WorkspaceArtifactsCleanupHook(LifecycleHook):
    """Clear the active artifact collector on every runtime exit path."""

    name = "workspace_artifacts_cleanup"
    priority = 100
    phase = Phase.FINALLY

    async def run(self, ctx: HookContext) -> HookResult:
        token = ctx.extras.pop(_COLLECTOR_TOKEN_KEY, None)
        if token is not None:
            reset_current_artifact_collector(token)
        _release_turn_lock(ctx)
        return HookResult()


__all__ = [
    "WorkspaceArtifactsCleanupHook",
    "WorkspaceArtifactsFinalizeHook",
    "WorkspaceArtifactsHook",
]
