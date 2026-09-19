# -*- coding: utf-8 -*-
"""Verified Creator media reads for Host artifact publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from services.project_files.assets import AssetFileError, AssetFileStore
from services.project_files.models import ArtifactVersion, IndexedFile

from qwenpaw.pawapp.artifacts import MAX_ARTIFACT_BYTES


class CreatorArtifactMismatch(RuntimeError):
    pass


class CreatorArtifactUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedCreatorArtifact:
    source: dict[str, object]
    content: bytes


def read_verified_creator_artifact(
    project_root: Path,
    *,
    version: ArtifactVersion,
    indexed: IndexedFile,
    expected_owner_ref: str,
    expected_task_id: str,
    source_id: str | None = None,
    publication_path: str | None = None,
) -> VerifiedCreatorArtifact:
    publication_shape_valid = (
        version.file_id == indexed.file_id
        and version.checksum == indexed.sha256
        and len(version.version_id) <= 256
        and len(indexed.relative_uri) <= 4096
        and len(indexed.media_type) <= 256
        and indexed.media_type.casefold().startswith("video/")
        and 0 < indexed.size_bytes <= MAX_ARTIFACT_BYTES
    )
    if (
        version.owner_ref != expected_owner_ref
        or version.metadata.get("taskId") != expected_task_id
        or not publication_shape_valid
    ):
        raise CreatorArtifactMismatch

    try:
        content = AssetFileStore(project_root).read_verified(indexed)
    except (AssetFileError, OSError, ValueError):
        raise CreatorArtifactUnavailable from None

    suffix = PurePosixPath(indexed.relative_uri).suffix
    name = version.name.strip()
    invalid_name = (
        not name
        or name in {".", ".."}
        or any(char in name for char in "/\\\x00")
    )
    if invalid_name:
        name = f"{version.version_id}{suffix}"
    elif suffix and not name.casefold().endswith(suffix.casefold()):
        name += suffix
    if len(name) > 512:
        name = f"{version.version_id}{suffix}"

    return VerifiedCreatorArtifact(
        source={
            "source_id": source_id or version.version_id,
            "name": name,
            "path": publication_path or indexed.relative_uri,
            "media_type": indexed.media_type,
            "size_bytes": indexed.size_bytes,
            "digest": f"sha256:{indexed.sha256}",
        },
        content=content,
    )


__all__ = [
    "CreatorArtifactMismatch",
    "CreatorArtifactUnavailable",
    "VerifiedCreatorArtifact",
    "read_verified_creator_artifact",
]
