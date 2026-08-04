# -*- coding: utf-8 -*-
"""Merge explicit file registrations with workspace snapshot changes."""

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from .models import (
    ArtifactCollection,
    ArtifactChangeKind,
    PreviewKind,
    WorkspaceArtifact,
    WorkspaceChange,
    WorkspaceSnapshot,
)
from .snapshot import diff_workspace_snapshots

_IMAGE_EXTENSIONS = frozenset(
    {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"},
)
_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown", ".mdx"})
_CSV_EXTENSIONS = frozenset({".csv", ".tsv"})
_MIME_TYPE_OVERRIDES = {
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".tsv": "text/tab-separated-values",
}
_TEXT_EXTENSIONS = frozenset(
    {
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".log",
        ".py",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    },
)


@dataclass(frozen=True, slots=True)
class ArtifactLimits:
    """Limits applied after merging all discovery sources."""

    max_artifacts: int = 100

    def __post_init__(self) -> None:
        if self.max_artifacts < 1:
            raise ValueError(
                f"max_artifacts must be positive: {self.max_artifacts}",
            )


def _preview_kind(extension: str) -> PreviewKind:
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension == ".pdf":
        return "pdf"
    if extension in _MARKDOWN_EXTENSIONS:
        return "markdown"
    if extension in _CSV_EXTENSIONS:
        return "csv"
    if extension in _TEXT_EXTENSIONS:
        return "text"
    return "none"


class ArtifactCollector:
    """Collect user-visible files produced during one workspace turn."""

    def __init__(
        self,
        workspace_dir: Path,
        before: WorkspaceSnapshot,
        *,
        limits: ArtifactLimits | None = None,
    ) -> None:
        self._workspace_dir = workspace_dir.resolve()
        self._before = before
        self._limits = limits or ArtifactLimits()
        self._explicit_paths: set[str] = set()

    def register(self, file_path: str | Path) -> bool:
        """Register a regular file when it remains inside the workspace."""
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = self._workspace_dir / candidate
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(self._workspace_dir)
        except (OSError, ValueError):
            return False
        if not resolved.is_file() or resolved.is_symlink():
            return False
        self._explicit_paths.add(relative.as_posix())
        return True

    def collect(
        self,
        after: WorkspaceSnapshot,
    ) -> ArtifactCollection:
        """Merge registrations and snapshot changes into a bounded result."""
        changes = list(diff_workspace_snapshots(self._before, after))
        change_by_path = {change.path: change.change for change in changes}
        artifact_paths = {
            change.path for change in changes if change.change != "deleted"
        }
        artifact_paths.update(self._explicit_paths)

        artifacts: list[WorkspaceArtifact] = []
        for relative_path in sorted(artifact_paths):
            state = after.files.get(relative_path)
            if state is None:
                continue
            raw_change = change_by_path.get(relative_path, "modified")
            change: ArtifactChangeKind = (
                "created" if raw_change == "created" else "modified"
            )
            path = Path(relative_path)
            extension = path.suffix.lower()
            mime_type = _MIME_TYPE_OVERRIDES.get(extension)
            if mime_type is None:
                mime_type = mimetypes.guess_type(path.name)[0]
            artifacts.append(
                WorkspaceArtifact(
                    path=relative_path,
                    name=path.name,
                    extension=extension,
                    mime_type=mime_type or "application/octet-stream",
                    size=state.size,
                    modified_ns=state.modified_ns,
                    change=change,
                    preview=_preview_kind(extension),
                ),
            )

        truncated = after.truncated
        if len(artifacts) > self._limits.max_artifacts:
            artifacts = artifacts[: self._limits.max_artifacts]
            truncated = True

        for relative_path in sorted(self._explicit_paths):
            if relative_path not in change_by_path:
                changes.append(WorkspaceChange(relative_path, "modified"))
        changes.sort(key=lambda item: item.path)

        return ArtifactCollection(
            artifacts=tuple(artifacts),
            changes=tuple(changes),
            truncated=truncated,
        )
