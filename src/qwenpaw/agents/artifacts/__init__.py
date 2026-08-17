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
from .coordinator import ArtifactCoordinator, ArtifactTurnHandle
from .lifecycle import ArtifactTurn, resolve_artifact_roots
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
from .serializer import parse_manifest, serialize_manifest
from .session import (
    MAX_WORKSPACE_ARTIFACT_MANIFESTS,
    merge_artifact_manifests,
    merge_artifact_root_mappings,
)

__all__ = [
    "ArtifactCollection",
    "ArtifactCollector",
    "ArtifactCollectorGroup",
    "ArtifactCoordinator",
    "ArtifactLimits",
    "ArtifactRoot",
    "ArtifactTurn",
    "ArtifactTurnHandle",
    "MAX_WORKSPACE_ARTIFACT_MANIFESTS",
    "SnapshotLimits",
    "WorkspaceArtifact",
    "WorkspaceChange",
    "WorkspaceFileState",
    "WorkspaceSnapshot",
    "capture_workspace_snapshot",
    "diff_workspace_snapshots",
    "parse_manifest",
    "merge_artifact_manifests",
    "merge_artifact_root_mappings",
    "register_current_artifact",
    "reset_current_artifact_collector",
    "resolve_artifact_roots",
    "serialize_manifest",
    "set_current_artifact_collector",
]
