# -*- coding: utf-8 -*-
"""Immutable models used by workspace artifact discovery."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

ChangeKind = Literal["created", "modified", "deleted"]
ArtifactChangeKind = Literal["created", "modified"]
ArtifactRoot = Literal["workspace", "project"]
PreviewKind = Literal[
    "image",
    "pdf",
    "markdown",
    "csv",
    "text",
    "none",
]


@dataclass(frozen=True, slots=True)
class WorkspaceFileState:
    """Metadata sufficient to compare a regular workspace file."""

    size: int
    modified_ns: int
    fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """A bounded immutable view of regular files in one workspace."""

    files: Mapping[str, WorkspaceFileState]
    truncated: bool = False
    fingerprints_truncated: bool = False

    @classmethod
    def create(
        cls,
        files: Mapping[str, WorkspaceFileState],
        *,
        truncated: bool = False,
        fingerprints_truncated: bool = False,
    ) -> "WorkspaceSnapshot":
        """Copy and freeze snapshot entries in deterministic path order."""
        ordered = dict(sorted(files.items()))
        return cls(
            MappingProxyType(ordered),
            truncated,
            fingerprints_truncated,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    """One normalized path changed during a chat turn."""

    path: str
    change: ChangeKind
    root: ArtifactRoot = "workspace"


@dataclass(frozen=True, slots=True)
class WorkspaceArtifact:
    """User-visible metadata for one existing workspace file."""

    path: str
    name: str
    extension: str
    mime_type: str
    size: int
    modified_ns: int
    change: ArtifactChangeKind
    preview: PreviewKind
    root: ArtifactRoot = "workspace"


@dataclass(frozen=True, slots=True)
class ArtifactCollection:
    """Merged artifact files and all workspace changes for one turn."""

    artifacts: tuple[WorkspaceArtifact, ...]
    changes: tuple[WorkspaceChange, ...]
    truncated: bool = False
