# -*- coding: utf-8 -*-
"""Collect workspace artifacts around one runtime turn."""

from __future__ import annotations

import logging

from ..agents.artifacts import (
    ArtifactTurn,
    resolve_artifact_roots,
)
from ..config.context import get_current_project_dir
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase
from .base import LifecycleHook

logger = logging.getLogger(__name__)

_ARTIFACT_TURN_KEY = "workspace_artifact_turn"
_MANIFEST_KEY = "workspace_artifact_manifest"
_ROOT_MAPPINGS_KEY = "workspace_artifact_roots"

_resolve_artifact_roots = resolve_artifact_roots


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
            turn = ArtifactTurn(
                coordinator=getattr(
                    ctx.workspace,
                    "artifact_coordinator",
                    None,
                ),
                workspace_dir=ctx.workspace_dir,
                project_dir=get_current_project_dir(),
                agent_id=ctx.agent_id,
                session_id=ctx.session_id,
                turn_id=ctx.extras.get("turn_id", ctx.session_id),
            )
            ctx.extras[_ARTIFACT_TURN_KEY] = turn
            await turn.begin()
        except Exception:
            logger.debug("workspace artifact pre-scan failed", exc_info=True)
        return HookResult()


class WorkspaceArtifactsFinalizeHook(LifecycleHook):
    """Collect the final workspace state before session persistence."""

    name = "workspace_artifacts_finalize"
    priority = 80
    phase = Phase.FINALIZE_TURN
    before = ("session_save",)

    async def run(self, ctx: HookContext) -> HookResult:
        """Store a serialized manifest for the runtime and save hook."""
        turn = ctx.extras.get(_ARTIFACT_TURN_KEY)
        if turn is None:
            return HookResult()
        try:
            manifest = await turn.finalize()
            if manifest is not None:
                ctx.extras[_MANIFEST_KEY] = manifest
                ctx.extras[_ROOT_MAPPINGS_KEY] = turn.root_mappings
        except Exception:
            logger.debug("workspace artifact post-scan failed", exc_info=True)
        return HookResult()


class WorkspaceArtifactsCleanupHook(LifecycleHook):
    """Clear the active artifact collector on every runtime exit path."""

    name = "workspace_artifacts_cleanup"
    priority = 100
    phase = Phase.FINALLY

    async def run(self, ctx: HookContext) -> HookResult:
        turn = ctx.extras.pop(_ARTIFACT_TURN_KEY, None)
        if turn is not None:
            await turn.cleanup()
        return HookResult()


__all__ = [
    "WorkspaceArtifactsCleanupHook",
    "WorkspaceArtifactsFinalizeHook",
    "WorkspaceArtifactsHook",
]
