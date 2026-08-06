# -*- coding: utf-8 -*-
"""Collect workspace artifacts around one runtime turn."""

from __future__ import annotations

import logging
from pathlib import Path

from ..agents.artifacts import (
    ArtifactCollector,
    capture_workspace_snapshot,
    serialize_manifest,
    set_current_artifact_collector,
)
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase
from ..utils.io_utils import run_sync_io
from .base import LifecycleHook

logger = logging.getLogger(__name__)

_COLLECTOR_KEY = "workspace_artifact_collector"
_MANIFEST_KEY = "workspace_artifact_manifest"


def _create_collector(workspace_dir: Path) -> ArtifactCollector:
    """Build a collector and its initial snapshot in one worker task."""
    before = capture_workspace_snapshot(workspace_dir)
    return ArtifactCollector(workspace_dir, before)


def _collect_manifest(
    collector: ArtifactCollector,
    workspace_dir: Path,
    *,
    agent_id: str,
    session_id: str,
    turn_id: str,
) -> dict | None:
    """Capture, merge, and serialize one final workspace snapshot."""
    after = capture_workspace_snapshot(workspace_dir)
    collection = collector.collect(after)
    if not collection.artifacts and not collection.changes:
        return None
    return serialize_manifest(
        collection,
        agent_id=agent_id,
        chat_id=session_id,
        turn_id=turn_id,
    )


class WorkspaceArtifactsHook(LifecycleHook):
    """Capture the initial workspace state outside the event loop."""

    name = "workspace_artifacts"
    priority = 20
    phase = Phase.PRE_DISPATCH

    async def run(self, ctx: HookContext) -> HookResult:
        """Capture the initial workspace state for the current turn."""
        if ctx.workspace_dir is None:
            return HookResult()
        try:
            collector = await run_sync_io(
                _create_collector,
                ctx.workspace_dir,
            )
            ctx.extras[_COLLECTOR_KEY] = collector
            set_current_artifact_collector(collector)
        except Exception:
            logger.debug("workspace artifact pre-scan failed", exc_info=True)
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
        workspace_dir = ctx.workspace_dir
        if collector is None or workspace_dir is None:
            return HookResult()
        try:
            manifest = await run_sync_io(
                _collect_manifest,
                collector,
                workspace_dir,
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
        del ctx
        set_current_artifact_collector(None)
        return HookResult()


__all__ = [
    "WorkspaceArtifactsCleanupHook",
    "WorkspaceArtifactsFinalizeHook",
    "WorkspaceArtifactsHook",
]
