# -*- coding: utf-8 -*-
"""Workspace artifact discovery for chat turns."""

from .collector import (
    ArtifactCollector,
    ArtifactCollectorGroup,
    ArtifactLimits,
)
from .context import (
    register_current_artifact,
    reset_current_artifact_collector,
    set_current_artifact_collector,
)
from .models import (
    ArtifactCollection,
    ArtifactRoot,
    WorkspaceArtifact,
    WorkspaceChange,
    WorkspaceFileState,
    WorkspaceSnapshot,
)
from .snapshot import (
    SnapshotLimits,
    capture_workspace_snapshot,
    diff_workspace_snapshots,
)
from .serializer import serialize_manifest

__all__ = [
    "ArtifactCollection",
    "ArtifactCollector",
    "ArtifactCollectorGroup",
    "ArtifactLimits",
    "ArtifactRoot",
    "SnapshotLimits",
    "WorkspaceArtifact",
    "WorkspaceChange",
    "WorkspaceFileState",
    "WorkspaceSnapshot",
    "capture_workspace_snapshot",
    "diff_workspace_snapshots",
    "register_current_artifact",
    "reset_current_artifact_collector",
    "serialize_manifest",
    "set_current_artifact_collector",
]
