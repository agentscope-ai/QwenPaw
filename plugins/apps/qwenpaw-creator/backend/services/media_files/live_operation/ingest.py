# -*- coding: utf-8 -*-
"""Publish live-operation output as ordinary Project source material.

A recorded take is not a new kind of thing: it is source footage, exactly
like a video a user uploaded. Publishing it through the same asset path means
observe_source_clip can watch it, an Edit Element can cut it, and the compose
pipeline can render it, with no new element or creation type anywhere.

The take manifest travels beside its video as an indexed Project file, so the
coordinates and instants motion design needs stay attached to the footage
they describe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from services.project_files.assets import AssetAlreadyExists, AssetFileStore
from services.project_files.models import IndexedFile, SourceAssetVersion

logger = logging.getLogger(__name__)

TAKE_SOURCE_KIND = "live_operation_take"
SCREENSHOT_SOURCE_KIND = "live_operation_screenshot"
MANIFEST_SCHEMA_NAME = "creator.live_operation.take_manifest"
_MANIFEST_MEDIA_TYPE = "application/json"
_IMAGE_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class PublishedTake:
    """One take as the model and the timeline now see it."""

    take_id: str
    label: str
    workspace_ref: str
    logical_asset_id: str
    source_asset_version_id: str
    manifest_file_id: str
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "takeId": self.take_id,
            "label": self.label,
            "workspaceRef": self.workspace_ref,
            "logicalAssetId": self.logical_asset_id,
            "sourceAssetVersionId": self.source_asset_version_id,
            "manifestFileId": self.manifest_file_id,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class PublishedImage:
    """One screenshot the agent captured, now a Project asset."""

    workspace_ref: str
    logical_asset_id: str
    source_asset_version_id: str
    file_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspaceRef": self.workspace_ref,
            "logicalAssetId": self.logical_asset_id,
            "sourceAssetVersionId": self.source_asset_version_id,
            "fileId": self.file_id,
        }


def stable_id(kind: str, project_id: str, identity: str) -> str:
    """Derive a deterministic id so re-publishing the same bytes no-ops."""
    digest = hashlib.sha256(
        f"live-operation:{kind}:{project_id}:{identity}".encode("utf-8"),
    ).hexdigest()
    return f"{kind}-{digest[:32]}"


def stage_and_publish_file(
    store: AssetFileStore,
    *,
    content: bytes,
    relative_uri: str,
    checksum: str,
    staging_id: str,
) -> None:
    """Write one payload into the Project's asset tree atomically."""
    staged = store.stage_bytes(content, staging_id=staging_id)
    try:
        store.publish(
            staged,
            relative_uri,
            expected_sha256=checksum,
            expected_size_bytes=len(content),
        )
    except AssetAlreadyExists:
        store.abandon(staged)


def build_take_records(
    *,
    project_id: str,
    take_id: str,
    label: str,
    video: bytes,
    manifest_payload: bytes,
    duration_seconds: float | None,
    request_id: str,
    created_at: datetime | None = None,
) -> tuple[IndexedFile, IndexedFile, SourceAssetVersion, str]:
    """Describe one take as Project records, without touching the Project."""
    created_at = created_at or datetime.now(UTC)
    video_checksum = hashlib.sha256(video).hexdigest()
    manifest_checksum = hashlib.sha256(manifest_payload).hexdigest()
    logical_asset_id = stable_id("asset", project_id, video_checksum)
    version_id = stable_id("asset-version", project_id, video_checksum)
    video_file_id = stable_id("file", project_id, video_checksum)
    manifest_file_id = stable_id("file", project_id, manifest_checksum)
    video_file = IndexedFile(
        file_id=video_file_id,
        kind="source_original",
        relative_uri=PurePosixPath(
            "assets",
            "sources",
            f"{video_file_id}.mp4",
        ).as_posix(),
        sha256=video_checksum,
        size_bytes=len(video),
        media_type="video/mp4",
        created_at=created_at,
    )
    manifest_file = IndexedFile(
        file_id=manifest_file_id,
        kind="source_intelligence",
        relative_uri=PurePosixPath(
            "assets",
            "sources",
            f"{manifest_file_id}.json",
        ).as_posix(),
        sha256=manifest_checksum,
        size_bytes=len(manifest_payload),
        media_type=_MANIFEST_MEDIA_TYPE,
        schema_name=MANIFEST_SCHEMA_NAME,
        schema_version=1,
        created_at=created_at,
    )
    version = SourceAssetVersion(
        version_id=version_id,
        logical_asset_id=logical_asset_id,
        name=(label or f"Live operation {take_id}")[:160],
        file_id=video_file_id,
        checksum=video_checksum,
        media_kind="video",
        media_type="video/mp4",
        duration_seconds=duration_seconds,
        created_at=created_at,
        metadata={
            "sourceKind": TAKE_SOURCE_KIND,
            "takeId": take_id,
            "requestId": request_id,
            # The sidecar id is the whole reason facts survive publication:
            # motion design reads it to place emphasis on real coordinates.
            "manifestFileId": manifest_file_id,
            "manifestSchema": MANIFEST_SCHEMA_NAME,
        },
    )
    return video_file, manifest_file, version, logical_asset_id


def build_image_records(
    *,
    project_id: str,
    name: str,
    content: bytes,
    media_type: str,
    request_id: str,
    created_at: datetime | None = None,
) -> tuple[IndexedFile, SourceAssetVersion, str]:
    """Describe one captured screenshot as Project records."""
    created_at = created_at or datetime.now(UTC)
    checksum = hashlib.sha256(content).hexdigest()
    logical_asset_id = stable_id("asset", project_id, checksum)
    version_id = stable_id("asset-version", project_id, checksum)
    file_id = stable_id("file", project_id, checksum)
    normalized_media_type = media_type.split(";", 1)[0].strip().casefold()
    suffix = _IMAGE_SUFFIXES.get(normalized_media_type, ".img")
    indexed = IndexedFile(
        file_id=file_id,
        kind="source_original",
        relative_uri=PurePosixPath(
            "assets",
            "sources",
            f"{file_id}{suffix}",
        ).as_posix(),
        sha256=checksum,
        size_bytes=len(content),
        media_type=normalized_media_type or "application/octet-stream",
        created_at=created_at,
    )
    version = SourceAssetVersion(
        version_id=version_id,
        logical_asset_id=logical_asset_id,
        name=name[:160],
        file_id=file_id,
        checksum=checksum,
        media_kind="image",
        media_type=normalized_media_type or "application/octet-stream",
        created_at=created_at,
        metadata={
            "sourceKind": SCREENSHOT_SOURCE_KIND,
            "requestId": request_id,
        },
    )
    return indexed, version, logical_asset_id


def read_take_manifest(
    project: Any,
    store: AssetFileStore,
    version: SourceAssetVersion | Mapping[str, Any],
) -> dict[str, Any] | None:
    """Load the manifest attached to one source version, when it has one.

    Footage without a manifest is not an error: user-uploaded material simply
    has no recorded facts, and motion design then works from frames alone.
    """
    metadata = (
        version.metadata
        if isinstance(version, SourceAssetVersion)
        else version.get("metadata")
    )
    if not isinstance(metadata, Mapping):
        return None
    file_id = str(metadata.get("manifestFileId") or "")
    if not file_id:
        return None
    files = getattr(getattr(project, "assets", None), "files_by_id", None)
    if not isinstance(files, Mapping):
        return None
    indexed = files.get(file_id)
    if indexed is None:
        return None
    try:
        import json

        with store.open_verified(indexed) as stream:
            payload = json.loads(stream.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - a damaged sidecar must not break edit
        logger.debug("take manifest unreadable: %s", file_id, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def resolve_local_path(root: Path, indexed: IndexedFile) -> Path:
    """Return the on-disk location of one published Project file."""
    return root / Path(indexed.relative_uri)


__all__ = [
    "MANIFEST_SCHEMA_NAME",
    "PublishedImage",
    "PublishedTake",
    "SCREENSHOT_SOURCE_KIND",
    "TAKE_SOURCE_KIND",
    "build_image_records",
    "build_take_records",
    "read_take_manifest",
    "resolve_local_path",
    "stable_id",
    "stage_and_publish_file",
]
