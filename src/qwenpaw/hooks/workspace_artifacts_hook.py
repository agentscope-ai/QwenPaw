"""Collect workspace artifacts around one runtime turn."""

from __future__ import annotations

import logging

from ..agents.artifacts import (
    ArtifactCollector,
    capture_workspace_snapshot,
    set_current_artifact_collector,
)
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase
from .base import LifecycleHook

logger = logging.getLogger(__name__)


class WorkspaceArtifactsHook(LifecycleHook):
    """Capture and merge user-visible files without delaying a response."""

    name = "workspace_artifacts"
    priority = 20
    phase = Phase.PRE_DISPATCH

    async def run(self, ctx: HookContext) -> HookResult:
        """Capture the initial workspace state for the current turn."""
        if ctx.workspace_dir is None:
            return HookResult()
        try:
            before = capture_workspace_snapshot(ctx.workspace_dir)
            ctx.extras["workspace_artifact_collector"] = ArtifactCollector(
                ctx.workspace_dir,
                before,
            )
            set_current_artifact_collector(
                ctx.extras["workspace_artifact_collector"],
            )
        except Exception:
            logger.debug("workspace artifact pre-scan failed", exc_info=True)
        return HookResult()

    async def collect(self, ctx: HookContext) -> dict | None:
        """Collect the final state and return a serialized manifest."""
        collector = ctx.extras.get("workspace_artifact_collector")
        if collector is None:
            return None
        try:
            after = capture_workspace_snapshot(ctx.workspace_dir)
            collection = collector.collect(after)
            if not collection.artifacts and not collection.changes:
                return None
            from ..agents.artifacts.serializer import serialize_manifest

            return serialize_manifest(
                collection,
                agent_id=ctx.agent_id,
                chat_id=ctx.session_id,
                turn_id=ctx.extras.get("turn_id", ctx.session_id),
            )
        except Exception:
            logger.debug("workspace artifact post-scan failed", exc_info=True)
            return None
        finally:
            set_current_artifact_collector(None)


__all__ = ["WorkspaceArtifactsHook"]
