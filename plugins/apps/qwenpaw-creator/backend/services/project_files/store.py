# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=try-except-raise,too-many-branches,too-many-statements
"""Filesystem ProjectStore for the single ``project.json`` authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
from typing import Any, Final
from uuid import uuid4

from pydantic import ValidationError
from domain.errors import (
    BadRequestError,
    NotFoundError,
    SourceAssetInUseError,
)
from services.runtime_files.atomic_store import (
    atomic_replace_path,
    fsync_directory as runtime_fsync_directory,
)
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.path_safety import is_link_path, is_link_stat
from services.storage_root import require_creator_data_root
from utils.logger import setup_logger

from .models import (
    ArtifactVersionRenderSource,
    AudioCreation,
    EditCreation,
    I2VCreation,
    OverlayCreation,
    Project,
    R2VCreation,
    S2VCreation,
    SourceVersionRenderSource,
    Timeline,
    TimelineElement,
)
from .archive import write_project_archive
from .serialization import (
    CanonicalJsonError,
    load_project_json_with_source,
    project_etag,
    project_file_bytes,
)

logger = setup_logger("store")


DEFAULT_MAX_PROJECT_JSON_BYTES = 32 * 1024 * 1024
_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Projects materialized from plugin-bundled inspiration examples carry this
# marker file so listing keeps them out of the user's own project shelf while
# every id-addressed route still serves them normally.
BUILTIN_EXAMPLE_MARKER: Final = ".builtin-example"
PROJECT_SUMMARY_RECORD: Final = "runtime/summary.json"
SUMMARY_RECORD_SCHEMA: Final = 1
LIST_SUMMARY_CACHE_ENV: Final = "CREATOR_LIST_SUMMARY_CACHE"
# Fields the listing projection treats as required strings. A damaged
# record must be a miss, never an authority: ``_cached_summary`` checks
# each one before handing it to a dataclass whose annotations are
# compile-time only, so a ``name=42`` would otherwise sail through and
# blow up later in ``list(sort_by="name")`` with an AttributeError on
# ``s.name.lower()`` -- which the surrounding ``except (KeyError,
# TypeError, ValueError)`` does not catch. ``str.lower()`` is not the
# only consumer (HomePage renders name and scenario, the API returns
# etag), so a corrupt field would 500 the whole listing rather than
# downgrade to a full read.
SUMMARY_REQUIRED_STR_FIELDS: Final = (
    "name",
    "description",
    "scenario",
    "aspectRatio",
    "resolution",
    "etag",
)
SUMMARY_OPTIONAL_STR_FIELDS: Final = (
    "contentType",
    "coverVersionId",
    "coverVersionSource",
    "finalVideoVersionId",
)
# ISO datetimes need more than ``isinstance(str)``: ``datetime.fromisoformat``
# happily produces a naive value from ``"2026-11-12T10:00:00"`` (no offset),
# and mixing it with a warm aware datetime in a later listing raises
# ``TypeError: can't compare offset-naive and offset-aware datetimes`` --
# outside this method's try/except, in ``list()``'s sort. Every Project
# document persists in UTC, so a cached timestamp without tzinfo is damage
# and must fall back to a full read (review #243 / #255 follow-up P2).
SUMMARY_TZAWARE_DATETIME_FIELDS: Final = (
    "createdAt",
    "updatedAt",
)


class ProjectStoreError(RuntimeError):
    """Base error for Project filesystem operations."""


class ProjectNotFound(ProjectStoreError):
    pass


class ProjectAlreadyExists(ProjectStoreError):
    pass


class ProjectConflict(ProjectStoreError):
    pass


class ProjectIntegrityError(ProjectStoreError):
    pass


class UnsafeProjectPath(ProjectStoreError):
    pass


class InvalidProjectId(UnsafeProjectPath):
    """The caller supplied a malformed id, as opposed to a damaged store.

    Kept under UnsafeProjectPath so existing handlers that skip unusable
    directory names keep working, while routes can single it out as a client
    input mistake rather than a storage fault.
    """


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    project: Project
    etag: str
    generation: int
    # The exact persisted source document ``etag`` was hashed from, when this
    # snapshot was read from disk; None for snapshots built in memory (create /
    # replace / review) whose ``model_dump`` already is the authority that
    # ``project_etag`` hashed. A commit boundary writes this as ``base.json``
    # so it and ``etag`` share one representation even after a load-time repair
    # changed a stored field. See serialization.load_project_json_with_source.
    # Auxiliary to identity: a snapshot read back from disk represents the same
    # state as one built in memory, so it is excluded from equality/repr.
    source_document: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    project_id: str
    name: str
    description: str
    scenario: str
    aspect_ratio: str
    resolution: str
    content_type: str | None
    generation: int
    created_at: datetime
    updated_at: datetime
    etag: str
    cover_version_id: str | None = None
    cover_version_source: str | None = None
    final_video_version_id: str | None = None


def _project_json_stamp(entry: Path) -> tuple[int, int] | None:
    """``(mtime_ns, size)`` of one Project document, None when unreadable.

    The same fingerprint the reconcile fast path trusts: a commit replaces
    ``project.json`` by rename, so either field moving means the bytes moved.
    """

    try:
        info = (entry / "project.json").stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _list_summary_cache_enabled() -> bool:
    """``CREATOR_LIST_SUMMARY_CACHE=0`` restores the always-read listing."""

    raw = os.environ.get(LIST_SUMMARY_CACHE_ENV, "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


# Storyboard frames represent a Project best; character/scene reference images
# are the next best thing before falling back to any rendered or uploaded image.
_COVER_ARTIFACT_KINDS: Final = ("r2v_storyboard_image", "visual_asset_image")
# Editing Projects usually own no still at all, so a rendered cut or an uploaded
# clip supplies the cover through a keyframe instead of staying empty.
_COVER_VIDEO_ARTIFACT_KINDS: Final = ("final_video", "element_video")

_SNAPSHOT_TIMELINE_PREFIX: Final = "snapshot:"


def _timeline_reference_record(
    timeline: Timeline,
    element: TimelineElement,
    ref_kind: str,
    *,
    detachable: bool,
) -> dict[str, Any]:
    """Describe one blocking timeline reference for ``ASSET_IN_USE`` details.

    ``pointer`` reproduces the historical English message fragment exactly
    (snapshot references keep their ``<snapshot timeline id>/`` prefix), so
    log scrapers and existing assertions keep matching while the UI reads the
    named fields instead of parsing internal ids out of a sentence.
    """

    is_snapshot = timeline.timeline_id.startswith(_SNAPSHOT_TIMELINE_PREFIX)
    return {
        "timelineId": timeline.timeline_id,
        "timelineName": timeline.name
        or timeline.title
        or timeline.timeline_id,
        "isSnapshot": is_snapshot,
        "elementId": element.element_id,
        "elementLabel": element.label
        or element.element_id.removeprefix("elem:"),
        "creationType": element.creation.type,
        "refKind": ref_kind,
        "detachable": detachable,
        "pointer": (f"{timeline.timeline_id}/" if is_snapshot else "")
        + f"{ref_kind}:{element.element_id}",
    }


def _asset_in_use_message(
    version_id: str,
    references: list[dict[str, Any]],
) -> str:
    """The historical conflict sentence built from structured references."""

    return (
        f"Cannot delete source asset version {version_id}: "
        f"actively used in timeline by "
        f"{[reference['pointer'] for reference in references]}"
    )


def _cover_reference(project: Project) -> tuple[str, str] | None:
    """Pick a stable preview image for *project* from its asset index.

    Returns the version id plus the media family serving it: ``artifact`` or
    ``source`` for images, ``artifact_frame`` or ``source_frame`` when the cover
    must be extracted from a video.  ``None`` means the Project holds no visual
    media at all.  The oldest candidate wins so the cover does not shuffle while
    a Project keeps generating new frames.
    """

    files = project.assets.files_by_id

    def _is_image(file_id: str | None) -> bool:
        if file_id is None:
            return False
        indexed = files.get(file_id)
        return bool(indexed and indexed.media_type.startswith("image/"))

    def _is_video(file_id: str | None) -> bool:
        if file_id is None:
            return False
        indexed = files.get(file_id)
        return bool(indexed and indexed.media_type.startswith("video/"))

    def _oldest(candidates: list[Any]) -> Any:
        return min(
            candidates,
            key=lambda version: (version.created_at, version.version_id),
        )

    artifacts = list(project.assets.artifact_versions_by_id.values())
    images = [version for version in artifacts if _is_image(version.file_id)]
    for kind in (*_COVER_ARTIFACT_KINDS, None):
        candidates = [
            version
            for version in images
            if kind is None or version.kind == kind
        ]
        if candidates:
            return _oldest(candidates).version_id, "artifact"
    sources = list(project.assets.source_versions_by_id.values())
    image_sources = [
        version
        for version in sources
        if version.media_kind == "image" and _is_image(version.file_id)
    ]
    if image_sources:
        return _oldest(image_sources).version_id, "source"
    videos = [version for version in artifacts if _is_video(version.file_id)]
    for kind in (*_COVER_VIDEO_ARTIFACT_KINDS, None):
        candidates = [
            version
            for version in videos
            if kind is None or version.kind == kind
        ]
        if candidates:
            return _oldest(candidates).version_id, "artifact_frame"
    # Uploaded clips may still live in the remote cache only; the keyframe route
    # reports that as "not cached yet" and the card keeps its placeholder.
    video_sources = [
        version for version in sources if version.media_kind == "video"
    ]
    if video_sources:
        return _oldest(video_sources).version_id, "source_frame"
    return None


def _final_video_reference(project: Project) -> str | None:
    """Pick the newest rendered final cut of *project*, if any."""

    files = project.assets.files_by_id
    candidates = [
        version
        for version in project.assets.artifact_versions_by_id.values()
        if version.kind == "final_video"
        and version.file_id is not None
        and (indexed := files.get(version.file_id)) is not None
        and indexed.media_type.startswith("video/")
    ]
    if not candidates:
        return None
    newest = max(
        candidates,
        key=lambda version: (version.created_at, version.version_id),
    )
    return newest.version_id


class ProjectStore:
    """Own Project directories below one fixed, absolute data root.

    The store performs schema/path validation and crash-safe byte replacement.
    It does not create Runtime change sets and does not assign generations;
    callers of :meth:`replace` supply those values after their commit policy.
    Cross-process serialization is likewise owned by the commit boundary.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        max_project_json_bytes: int = DEFAULT_MAX_PROJECT_JSON_BYTES,
    ) -> None:
        raw_root = Path(root).expanduser()
        if not raw_root.is_absolute():
            raise UnsafeProjectPath(
                "ProjectStore root must be an absolute path",
            )
        if max_project_json_bytes <= 0:
            raise ValueError("max_project_json_bytes must be positive")
        raw_root.mkdir(parents=True, exist_ok=True)
        self.root = raw_root.resolve(strict=True)
        if not self.root.is_dir():
            raise UnsafeProjectPath("ProjectStore root must be a directory")
        self.max_project_json_bytes = max_project_json_bytes
        self._lock = threading.RLock()

    def project_root(self, project_id: str) -> Path:
        return self.root / _safe_project_id(project_id)

    def project_path(self, project_id: str) -> Path:
        return self.project_root(project_id) / "project.json"

    def create(
        self,
        project: Project,
        *,
        initialize_staged_project: Callable[[Path], None] | None = None,
    ) -> ProjectSnapshot:
        """Stage a complete Project directory, then publish it atomically.

        ``initialize_staged_project`` runs against the private staged Project
        directory after ``project.json`` has been written and before the
        directory is made discoverable.  Project lifecycle services use this
        hook to bootstrap Runtime files atomically with the Project authority:
        an exception removes the staging tree, so readers never observe a
        Project without its required Runtime aggregate.
        """

        candidate = _validated_project(project)
        project_root = self.project_root(candidate.project_id)
        payload = self._checked_payload(candidate)
        staging_root = self.root / ".staging"
        # Keep the private staged directory name short: Runtime bootstrap
        # writes deeply nested temp files inside it, and a long name here
        # pushes those paths past the Windows MAX_PATH (260) limit.  The
        # name is never parsed; publication renames it to the project id.
        staged_project = staging_root / f"p{uuid4().hex}"

        # Keep one global lock order across lifecycle operations and commit
        # publication: lifecycle lock first, then the in-process store lock.
        # The reverse order here could deadlock with a commit that already
        # owns the lifecycle lock and is entering ``replace()``.
        with self.lifecycle_lock(candidate.project_id), self._lock:
            staging_root.mkdir(mode=0o700, exist_ok=True)
            try:
                try:
                    project_root.lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise ProjectAlreadyExists(
                        f"Project already exists: {candidate.project_id}",
                    )
                staged_project.mkdir(mode=0o700)
                (staged_project / "assets").mkdir(mode=0o700)
                (staged_project / "observability").mkdir(mode=0o700)
                (staged_project / "observability" / "logs").mkdir(mode=0o700)
                (staged_project / "observability" / "traces").mkdir(mode=0o700)
                (staged_project / "runtime").mkdir(mode=0o700)
                (staged_project / "runtime" / "temp").mkdir(mode=0o700)
                self._validate_asset_paths(staged_project, candidate)
                self._atomic_write(staged_project, payload)
                if initialize_staged_project is not None:
                    initialize_staged_project(staged_project)
                _fsync_directory(staged_project)
                try:
                    # Unlike os.replace, rename must not replace another
                    # process's already-published Project directory.
                    os.rename(staged_project, project_root)
                except OSError as exc:
                    try:
                        project_root.lstat()
                    except FileNotFoundError:
                        raise
                    raise ProjectAlreadyExists(
                        f"Project already exists: {candidate.project_id}",
                    ) from exc
                _fsync_directory(self.root)
                _fsync_directory(staging_root)
            except Exception:
                # Once the directory rename succeeds, preserve the published
                # Project even if a later directory fsync reports failure.
                shutil.rmtree(staged_project, ignore_errors=True)
                raise
        logger.info("project created: %s", candidate.project_id)
        return _snapshot(candidate)

    def read(self, project_id: str) -> ProjectSnapshot:
        """Load and validate the current Project authority."""

        safe_id = _safe_project_id(project_id)
        project_root = self.root / safe_id
        self._require_real_project_directory(project_root, safe_id)
        target = project_root / "project.json"
        try:
            target_stat = target.lstat()
        except FileNotFoundError as exc:
            raise ProjectNotFound(f"Project not found: {safe_id}") from exc
        if is_link_stat(target_stat) or not stat.S_ISREG(
            target_stat.st_mode,
        ):
            raise ProjectIntegrityError(
                "project.json must be a regular, non-symlink file",
            )
        try:
            payload = target.read_bytes()
        except OSError as exc:
            raise ProjectIntegrityError(
                f"Cannot read Project: {safe_id}",
            ) from exc
        if len(payload) > self.max_project_json_bytes:
            raise ProjectIntegrityError(
                f"project.json exceeds {self.max_project_json_bytes} bytes",
            )
        try:
            (
                project,
                source_etag,
                source_document,
            ) = load_project_json_with_source(payload)
        except CanonicalJsonError as exc:
            raise ProjectIntegrityError(
                f"Invalid project.json for {safe_id}",
            ) from exc
        if project.project_id != safe_id:
            raise ProjectIntegrityError(
                f"Project identity mismatch: directory={safe_id}, file={project.project_id}",
            )
        self._validate_asset_paths(project_root, project)
        return ProjectSnapshot(
            project=project,
            etag=source_etag,
            generation=project.generation,
            source_document=source_document,
        )

    def replace(
        self,
        project_id: str,
        project: Project,
        expected_etag: str,
    ) -> ProjectSnapshot:
        """CAS-publish a fully prepared Project through atomic replacement.

        The caller owns business diffing, protected-field derivation and the
        cross-process lock. This method rechecks identity, ETag and monotonic
        Project metadata immediately before publishing the supplied snapshot.
        """

        safe_id = _safe_project_id(project_id)
        candidate = _validated_project(project)
        if candidate.project_id != safe_id:
            raise ProjectConflict(
                "candidate project_id does not match target Project",
            )
        payload = self._checked_payload(candidate)

        with self._lock:
            current = self.read(safe_id)
            if current.etag != expected_etag:
                raise ProjectConflict(
                    f"Project ETag conflict: expected={expected_etag}, actual={current.etag}",
                )
            if candidate.generation != current.generation + 1:
                raise ProjectConflict(
                    "candidate generation must be exactly current generation + 1",
                )
            if candidate.created_at != current.project.created_at:
                raise ProjectConflict("candidate cannot change created_at")
            if candidate.updated_at < current.project.updated_at:
                raise ProjectConflict(
                    "candidate updated_at cannot move backwards",
                )

            project_root = self.project_root(safe_id)
            self._validate_asset_paths(project_root, candidate)
            self._atomic_write(project_root, payload)
        return _snapshot(candidate)

    def remove_source_asset_version(
        self,
        project_id: str,
        version_id: str,
        force: bool = False,
    ) -> ProjectSnapshot:
        """Remove a source asset version and its unreferenced files.

        This removes the version from source_versions_by_id, removes any
        file_id / thumbnail_file_id entries from files_by_id that are no
        longer referenced by any remaining metadata, and deletes the
        corresponding on-disk files.

        References that BLOCK deletion (asset is actively used):
        - TimelineElement render_source → element depends on this version
        - AudioCreation.source_asset_version_id → audio track uses this
        - R2VCreation storyboard/video_reference_version_ids
        - OverlayCreation.reference_version_ids
        - I2VCreation.first_frame_version_id
        - S2VCreation.portrait_version_id / audio_version_id

        Automatic snapshot timelines count here too: a snapshot freezes the
        timeline/element objects only, so it still points at this same source
        version and its on-disk file. Deleting the file would make that
        history permanently unrestorable.

        References that are auto-cleaned (safe to detach):
        - ProjectSource.selected_asset_version_id → replaced or source removed
        - SourceIntelligenceVersion → deleted alongside the source version
        - CharacterVoice.sample_source_version_id → cleared to None
        - VisualVariant / CastLineup refs → version removed from list

        ``force=True`` additionally clears the *detachable* timeline references
        (first frame, digital-human inputs, storyboard/overlay references and
        plain render sources) instead of refusing, so an asset that a shot
        still points at can be dropped. Snapshot timelines are cleared too,
        which is the honest cost: rolling that snapshot back afterwards
        restores the Element without this input. Audio and Edit Elements are
        never half-detached — their schema requires the exact version — so a
        force delete over them still fails with ``ASSET_IN_USE`` and the user
        has to delete the Element first.
        """
        safe_id = _safe_project_id(project_id)

        with self._lock:
            current = self.read(safe_id)
            project = current.project

            if version_id not in project.assets.source_versions_by_id:
                raise NotFoundError(
                    f"Source asset version not found: {version_id}",
                )

            # Check for timeline-level references that block deletion
            timeline_refs = self._find_timeline_references(project, version_id)
            if timeline_refs:
                # Without force every reference blocks; with force only the
                # references no Element can survive without do. Half-clearing
                # an audio or Edit Element would persist an invalid Project.
                blocking = (
                    timeline_refs
                    if not force
                    else [
                        ref for ref in timeline_refs if not ref["detachable"]
                    ]
                )
                if blocking:
                    raise SourceAssetInUseError(
                        _asset_in_use_message(version_id, blocking),
                        details={
                            "versionId": version_id,
                            "timelineReferences": blocking,
                        },
                    )

            version = project.assets.source_versions_by_id[version_id]
            candidate_file_ids: list[str] = []
            if version.file_id is not None:
                candidate_file_ids.append(version.file_id)
            if version.thumbnail_file_id is not None:
                candidate_file_ids.append(version.thumbnail_file_id)
            if version.native_model_file_id is not None:
                candidate_file_ids.append(version.native_model_file_id)
            # Step 2 of _detach_source_version_refs drops every intelligence
            # version built from this source version, but those records own a
            # file too. Collect their file ids while the records still exist:
            # afterwards nothing references them, so they would keep sitting on
            # disk while remaining in the index forever (an orphan the
            # unindexed-file sweep cannot even find).
            for (
                intelligence
            ) in project.assets.intelligence_versions_by_id.values():
                if (
                    intelligence.source_asset_version_id == version_id
                    and intelligence.file_id is not None
                ):
                    candidate_file_ids.append(intelligence.file_id)

            # Remove the version from metadata
            remaining_versions = {
                vid: v
                for vid, v in project.assets.source_versions_by_id.items()
                if vid != version_id
            }
            updated_assets = project.assets.model_copy(
                update={
                    "source_versions_by_id": remaining_versions,
                },
            )
            updated_project = project.model_copy(
                update={
                    "assets": updated_assets,
                    "generation": project.generation + 1,
                    "updated_at": datetime.now(UTC),
                },
            )

            # Auto-clean non-timeline dangling references
            updated_project = self._detach_source_version_refs(
                updated_project,
                version_id,
            )
            if timeline_refs:
                # force path: every reference left is detachable.
                (
                    updated_project,
                    affected_timeline_ids,
                    affected_element_ids,
                ) = self._detach_timeline_references(
                    updated_project,
                    version_id,
                )
                updated_project = self._mark_force_delete_impacts(
                    updated_project,
                    affected_timeline_ids,
                    affected_element_ids,
                )

            # Determine which file_ids are no longer referenced by any
            # remaining metadata and can be deleted from disk.
            project_root = self.project_root(safe_id)
            files_to_delete = self._collect_deletable_files(
                updated_project,
                candidate_file_ids,
            )

            # Remove unreferenced files from the index
            if files_to_delete:
                remaining_files = {
                    fid: f
                    for fid, f in updated_project.assets.files_by_id.items()
                    if fid not in files_to_delete
                }
                final_assets = updated_project.assets.model_copy(
                    update={"files_by_id": remaining_files},
                )
                updated_project = updated_project.model_copy(
                    update={"assets": final_assets},
                )

            payload = self._checked_payload(updated_project)
            self._validate_asset_paths(project_root, updated_project)
            self._atomic_write(project_root, payload)

            # Delete the actual files from disk after metadata is updated
            for file_id, relative_uri in files_to_delete.items():
                self._delete_asset_file(project_root, relative_uri, file_id)

        return _snapshot(updated_project)

    def _collect_deletable_files(
        self,
        project: Project,
        candidate_file_ids: list[str],
    ) -> dict[str, str]:
        """Return file_ids that are no longer referenced by any metadata.

        Returns a mapping of file_id -> relative_uri for each candidate
        that is not referenced by any remaining asset version, artifact
        version, intelligence version, or other index entry.
        """
        if not candidate_file_ids:
            return {}

        # Build the set of all file_ids still referenced by any metadata
        referenced: set[str] = set()

        # Files referenced by remaining source versions
        for version in project.assets.source_versions_by_id.values():
            if version.file_id is not None:
                referenced.add(version.file_id)
            if version.thumbnail_file_id is not None:
                referenced.add(version.thumbnail_file_id)
            if version.native_model_file_id is not None:
                referenced.add(version.native_model_file_id)

        # Files referenced by source intelligence versions
        for version in project.assets.intelligence_versions_by_id.values():
            if version.file_id is not None:
                referenced.add(version.file_id)

        # Files referenced by artifact versions
        for version in project.assets.artifact_versions_by_id.values():
            if version.file_id is not None:
                referenced.add(version.file_id)
            if version.thumbnail_file_id is not None:
                referenced.add(version.thumbnail_file_id)

        # Files referenced by visual variants (character lineup refs)
        for entity in project.visual.entities.items.values():
            for variant in entity.variants.items.values():
                for fid in variant.reference_asset_version_ids or []:
                    ref_version = project.assets.source_versions_by_id.get(fid)
                    if ref_version is not None:
                        if ref_version.file_id is not None:
                            referenced.add(ref_version.file_id)
                        if ref_version.thumbnail_file_id is not None:
                            referenced.add(
                                ref_version.thumbnail_file_id,
                            )
                        if ref_version.native_model_file_id is not None:
                            referenced.add(
                                ref_version.native_model_file_id,
                            )

        # Files referenced by cast lineups
        for lineup in project.visual.cast_lineups.items.values():
            for fid in lineup.reference_asset_version_ids or []:
                ref_version = project.assets.source_versions_by_id.get(fid)
                if ref_version is not None:
                    if ref_version.file_id is not None:
                        referenced.add(ref_version.file_id)
                    if ref_version.thumbnail_file_id is not None:
                        referenced.add(ref_version.thumbnail_file_id)
                    if ref_version.native_model_file_id is not None:
                        referenced.add(ref_version.native_model_file_id)

        # Files referenced by the index itself (files_by_id entries that
        # are not candidates for deletion remain referenced)
        result: dict[str, str] = {}
        for file_id in candidate_file_ids:
            if file_id in referenced:
                continue
            indexed = project.assets.files_by_id.get(file_id)
            if indexed is not None:
                result[file_id] = indexed.relative_uri
        return result

    def _delete_asset_file(
        self,
        project_root: Path,
        relative_uri: str,
        file_id: str,
    ) -> None:
        """Delete one asset file from disk.  Best-effort; logs on failure."""
        try:
            parts = PurePosixPath(relative_uri).parts
            candidate = project_root.joinpath(*parts)
            # Safety: ensure the resolved path is still within assets/
            resolved = candidate.resolve(strict=False)
            assets_root = (project_root / "assets").resolve(strict=True)
            resolved.relative_to(assets_root)
            candidate.unlink(missing_ok=True)
            logger.info(
                "asset file deleted: file_id=%s uri=%s",
                file_id,
                relative_uri,
            )
        except Exception:
            logger.warning(
                "failed to delete asset file: file_id=%s uri=%s",
                file_id,
                relative_uri,
                exc_info=True,
            )

    def _find_timeline_references(
        self,
        project: Project,
        version_id: str,
    ) -> list[dict[str, Any]]:
        """Find timeline-level references that block deletion.

        Returns one record per timeline Element that actively uses the given
        source version. If non-empty, deletion should be blocked to prevent
        data corruption. Snapshot timelines count too (see
        ``remove_source_asset_version``), and their records carry the snapshot
        timeline id so a conflict explains which piece of history is holding
        the asset.

        ``detachable`` separates what a force delete may clear in place from
        what it may not: an Edit Element must keep a source-range
        ``render_source`` and an audio Element must keep the exact version on
        both ``creation`` and ``render_source`` (``Project._validate_graph``
        enforces all three), so only deleting the Element frees those bytes.
        A text-free overlay joins them once this version is its only payload:
        ``OverlayCreation`` itself requires ``text``, a ``prompt`` or a
        reference version, so clearing it would leave a Project that cannot be
        written back and the asset would become permanently undeletable.
        """
        references: list[dict[str, Any]] = []
        for timeline in project.timelines.items.values():
            for element in timeline.elements_by_id.values():
                creation = element.creation
                pinned = isinstance(creation, (AudioCreation, EditCreation))
                if not pinned and isinstance(creation, OverlayCreation):
                    pinned = not (
                        creation.text.strip()
                        or creation.prompt.strip()
                        or any(
                            version_id != reference
                            for reference in (
                                creation.reference_version_ids or []
                            )
                        )
                    )

                # Check render_source (SourceVersionRenderSource only)
                render_source = element.render_source
                if (
                    isinstance(render_source, SourceVersionRenderSource)
                    and not isinstance(
                        render_source,
                        ArtifactVersionRenderSource,
                    )
                    and render_source.version_id == version_id
                ):
                    references.append(
                        _timeline_reference_record(
                            timeline,
                            element,
                            "render-source",
                            detachable=not pinned,
                        ),
                    )

                # R2VCreation references
                if isinstance(creation, R2VCreation):
                    if version_id in (
                        creation.storyboard_reference_version_ids or []
                    ):
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "r2v-storyboard-ref",
                                detachable=True,
                            ),
                        )
                    if version_id in (
                        creation.video_reference_version_ids or []
                    ):
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "r2v-video-ref",
                                detachable=True,
                            ),
                        )
                # I2VCreation reference
                elif isinstance(creation, I2VCreation):
                    if creation.first_frame_version_id == version_id:
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "i2v-first-frame",
                                detachable=True,
                            ),
                        )
                # S2VCreation inputs are consumed directly by r2v_execution
                # without ever being copied into an owned version, so dropping
                # the file here would break an active digital-human shot.
                elif isinstance(creation, S2VCreation):
                    if creation.portrait_version_id == version_id:
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "s2v-portrait",
                                detachable=True,
                            ),
                        )
                    if creation.audio_version_id == version_id:
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "s2v-drive-audio",
                                detachable=True,
                            ),
                        )
                # OverlayCreation references
                elif isinstance(creation, OverlayCreation):
                    if version_id in (creation.reference_version_ids or []):
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "overlay-ref",
                                detachable=not pinned,
                            ),
                        )
                # AudioCreation references
                elif isinstance(creation, AudioCreation):
                    if creation.source_asset_version_id == version_id:
                        references.append(
                            _timeline_reference_record(
                                timeline,
                                element,
                                "audio-source",
                                detachable=False,
                            ),
                        )

        return references

    def _detach_timeline_references(
        self,
        project: Project,
        version_id: str,
    ) -> tuple[Project, set[str], set[str]]:
        """Clear every detachable timeline reference to a deleted version.

        Snapshot timelines are walked too: a frozen pointer to bytes that are
        about to disappear would let a later rollback restore an Element whose
        asset is already gone, so history loses this one input rather than
        becoming permanently unrestorable.

        Returns the updated Project together with the sets of timeline and
        element ids whose content changed, so the caller can derive the edit
        impact (stale flags on rendered outputs) from the cleared references.
        """
        affected_timeline_ids: set[str] = set()
        affected_element_ids: set[str] = set()
        timeline_updates: dict = {}
        for timeline_id, timeline in project.timelines.items.items():
            element_updates: dict = {}
            for element_id, element in timeline.elements_by_id.items():
                detached = self._detach_element_references(element, version_id)
                if detached is not None:
                    element_updates[element_id] = detached
                    affected_element_ids.add(element_id)
            if element_updates:
                affected_timeline_ids.add(timeline_id)
                # Element ids stay untouched, so the collection identity check
                # in EntityCollection keeps holding after the swap.
                timeline_updates[timeline_id] = timeline.model_copy(
                    update={
                        "elements_by_id": {
                            **timeline.elements_by_id,
                            **element_updates,
                        },
                    },
                )
        if not timeline_updates:
            return project, set(), set()
        return (
            project.model_copy(
                update={
                    "timelines": project.timelines.model_copy(
                        update={
                            "items": {
                                **project.timelines.items,
                                **timeline_updates,
                            },
                        },
                    ),
                },
            ),
            affected_timeline_ids,
            affected_element_ids,
        )

    @staticmethod
    def _mark_force_delete_impacts(
        project: Project,
        affected_timeline_ids: set[str],
        affected_element_ids: set[str],
    ) -> Project:
        """Mark rendered outputs stale after force-clearing source references.

        Detaching a source version from timeline elements changes the creative
        material those elements and their timelines represent, so the Project's
        previously selected final renders no longer describe the current state.
        This method marks every affected final_video and element-level output
        artifact version as ``stale`` so ``derive_work_graph`` correctly reports
        compose as STALE / READY instead of DONE.
        """
        if not affected_timeline_ids and not affected_element_ids:
            return project

        artifact_slots = project.assets.artifact_slots_by_id
        artifact_versions = project.assets.artifact_versions_by_id
        invalidated_version_ids: set[str] = set()

        # Timeline-level: the final cut of every touched timeline is
        # stale.  The artifact slot owner_ref is f"timeline:{timeline_id}"
        # (matching edit_impact._mark_timeline_render_stale).
        for timeline_id in affected_timeline_ids:
            for slot_id, slot in artifact_slots.items():
                if (
                    slot.owner_ref == f"timeline:{timeline_id}"
                    and slot.kind == "final_video"
                    and slot.selected_version_id is not None
                ):
                    version = artifact_versions.get(
                        slot.selected_version_id,
                    )
                    if version is not None and not version.stale:
                        invalidated_version_ids.add(
                            slot.selected_version_id,
                        )

        # Element-level: regeneration outputs of every cleared element.
        for element_id in affected_element_ids:
            for slot_id in (
                f"element:{element_id}:storyboard",
                f"element:{element_id}:video",
                f"element:{element_id}:main",
            ):
                slot = artifact_slots.get(slot_id)
                if slot is not None and slot.selected_version_id is not None:
                    version = artifact_versions.get(
                        slot.selected_version_id,
                    )
                    if version is not None and not version.stale:
                        invalidated_version_ids.add(
                            slot.selected_version_id,
                        )

        if not invalidated_version_ids:
            return project

        updated_versions: dict[str, Any] = {}
        for vid in invalidated_version_ids:
            version = artifact_versions[vid]
            updated_versions[vid] = version.model_copy(
                update={
                    "stale": True,
                    "stale_reason": "素材已删除，需要重新生成",
                },
            )
        return project.model_copy(
            update={
                "assets": project.assets.model_copy(
                    update={
                        "artifact_versions_by_id": {
                            **artifact_versions,
                            **updated_versions,
                        },
                    },
                ),
            },
        )

    @staticmethod
    def _detach_element_references(
        element: TimelineElement,
        version_id: str,
    ) -> TimelineElement | None:
        """Return *element* with this source version cleared, or None.

        Only ever called for detachable references: audio and Edit Elements are
        refused before reaching here because their schema requires the version.
        """
        creation = element.creation
        updates: dict[str, Any] = {}

        render_source = element.render_source
        if (
            isinstance(render_source, SourceVersionRenderSource)
            and not isinstance(render_source, ArtifactVersionRenderSource)
            and render_source.version_id == version_id
            and not isinstance(creation, (AudioCreation, EditCreation))
        ):
            updates["render_source"] = None

        if isinstance(creation, R2VCreation):
            for field_name in (
                "storyboard_reference_version_ids",
                "video_reference_version_ids",
            ):
                refs = list(getattr(creation, field_name) or [])
                if version_id in refs:
                    creation = creation.model_copy(
                        update={
                            field_name: [r for r in refs if r != version_id],
                        },
                    )
        elif isinstance(creation, I2VCreation):
            if creation.first_frame_version_id == version_id:
                creation = creation.model_copy(
                    update={"first_frame_version_id": None},
                )
        elif isinstance(creation, S2VCreation):
            s2v_updates: dict[str, Any] = {}
            if creation.portrait_version_id == version_id:
                s2v_updates["portrait_version_id"] = None
            if creation.audio_version_id == version_id:
                s2v_updates["audio_version_id"] = None
            if s2v_updates:
                creation = creation.model_copy(update=s2v_updates)
        elif isinstance(creation, OverlayCreation):
            refs = list(creation.reference_version_ids or [])
            if version_id in refs:
                remaining = [r for r in refs if r != version_id]
                keeps_payload = bool(
                    remaining
                    or creation.text.strip()
                    or creation.prompt.strip(),
                )
                if keeps_payload:
                    creation = creation.model_copy(
                        update={"reference_version_ids": remaining},
                    )
                # Otherwise this version is the whole payload of a text-free
                # overlay and the reference stays: the caller refused the force
                # delete above, and silently dropping the Element's content
                # would be the worse failure.
        # AudioCreation.source_asset_version_id is a required EntityId: this
        # Element is never detached, so nothing is cleared here.

        if creation is not element.creation:
            updates["creation"] = creation
        if not updates:
            return None
        return element.model_copy(update=updates)

    def _detach_source_version_refs(
        self,
        project: Project,
        version_id: str,
    ) -> Project:
        """Auto-clean dangling references to a deleted source version.

        Clears / removes references in:
        - ProjectSource.selected_asset_version_id → replaced with another
          version of the same logical asset, or the ProjectSource is removed
        - SourceIntelligenceVersion → deleted alongside the source version
        - CharacterVoice.sample_source_version_id → cleared to None
        - VisualVariant.reference_asset_version_ids → version removed
        - VisualCastLineup.reference_asset_version_ids → version removed
        """
        updates: dict = {}

        # Intelligence versions keyed to the deleted source version. Step 2
        # removes them, so any source pointer into one of these must be cleared
        # in the SAME batch; otherwise `Project._validate_graph` sees a dangling
        # `current_intelligence_version_id` and the write raises a 500 instead of
        # completing the deletion.
        dropped_intel_ids = {
            iid
            for iid, iv in project.assets.intelligence_versions_by_id.items()
            if iv.source_asset_version_id == version_id
        }

        # 1. Fix ProjectSource.selected_asset_version_id
        #    selected_asset_version_id is a required EntityId (not optional).
        #    When the selected version is deleted, pick another version with
        #    the same logical_asset_id; if none remains, remove the source.
        replaced_sources: dict = {}
        removed_source_ids: set[str] = set()
        for source_id, source in project.sources.sources.items.items():
            if source.selected_asset_version_id == version_id:
                # Find another version with the same logical_asset_id
                replacement = None
                for vid, ver in project.assets.source_versions_by_id.items():
                    if (
                        vid != version_id
                        and ver.logical_asset_id == source.logical_asset_id
                    ):
                        replacement = vid
                        break
                if replacement:
                    pointer_update: dict = {
                        "selected_asset_version_id": replacement,
                    }
                    if (
                        source.current_intelligence_version_id
                        in dropped_intel_ids
                    ):
                        pointer_update[
                            "current_intelligence_version_id"
                        ] = None
                    replaced_sources[source_id] = source.model_copy(
                        update=pointer_update,
                    )
                else:
                    removed_source_ids.add(source_id)
        if replaced_sources or removed_source_ids:
            new_source_items = {
                sid: s
                for sid, s in project.sources.sources.items.items()
                if sid not in removed_source_ids
            }
            new_source_items.update(replaced_sources)
            new_collection = project.sources.sources.model_copy(
                update={
                    "items": new_source_items,
                    "order": [
                        oid
                        for oid in project.sources.sources.order
                        if oid not in removed_source_ids
                    ],
                },
            )
            updates["sources"] = project.sources.model_copy(
                update={"sources": new_collection},
            )

        # 2. Delete SourceIntelligenceVersions that depend on this version
        remaining_intel = {
            iid: iv
            for iid, iv in (project.assets.intelligence_versions_by_id.items())
            if iv.source_asset_version_id != version_id
        }
        if len(remaining_intel) != len(
            project.assets.intelligence_versions_by_id,
        ):
            updates["assets"] = project.assets.model_copy(
                update={
                    "intelligence_versions_by_id": remaining_intel,
                },
            )

        # Work on the possibly-updated project
        current = project.model_copy(update=updates) if updates else project

        # 3. Clear CharacterVoice.sample_source_version_id
        visual_updates: dict = {}
        cleared_entities: dict = {}
        for entity_id, entity in current.visual.entities.items.items():
            if (
                entity.voice is not None
                and entity.voice.sample_source_version_id == version_id
            ):
                new_voice = entity.voice.model_copy(
                    update={"sample_source_version_id": None},
                )
                cleared_entities[entity_id] = entity.model_copy(
                    update={"voice": new_voice},
                )
        if cleared_entities:
            visual_updates["entities"] = current.visual.entities.model_copy(
                update={
                    "items": {
                        **current.visual.entities.items,
                        **cleared_entities,
                    },
                },
            )

        # 4. Remove version from VisualVariant refs
        base_entities = (
            visual_updates.get("entities") or current.visual.entities
        )
        variant_updates: dict = {}
        for entity_id, entity in base_entities.items.items():
            for variant_id, variant in entity.variants.items.items():
                if version_id in (variant.reference_asset_version_ids or []):
                    new_refs = [
                        r
                        for r in (variant.reference_asset_version_ids or [])
                        if r != version_id
                    ]
                    variant_updates.setdefault(entity_id, {})[
                        variant_id
                    ] = variant.model_copy(
                        update={
                            "reference_asset_version_ids": new_refs,
                        },
                    )
        if variant_updates:
            merged_items = dict(base_entities.items)
            for entity_id, var_map in variant_updates.items():
                entity = merged_items[entity_id]
                new_variants_collection = entity.variants.model_copy(
                    update={
                        "items": {
                            **entity.variants.items,
                            **var_map,
                        },
                    },
                )
                merged_items[entity_id] = entity.model_copy(
                    update={"variants": new_variants_collection},
                )
            visual_updates["entities"] = base_entities.model_copy(
                update={"items": merged_items},
            )

        # 5. Remove version from VisualCastLineup refs
        base_lineups = current.visual.cast_lineups
        lineup_updates: dict = {}
        for lineup_id, lineup in base_lineups.items.items():
            if version_id in (lineup.reference_asset_version_ids or []):
                new_refs = [
                    r
                    for r in (lineup.reference_asset_version_ids or [])
                    if r != version_id
                ]
                lineup_updates[lineup_id] = lineup.model_copy(
                    update={
                        "reference_asset_version_ids": new_refs,
                    },
                )
        if lineup_updates:
            visual_updates["cast_lineups"] = base_lineups.model_copy(
                update={
                    "items": {
                        **base_lineups.items,
                        **lineup_updates,
                    },
                },
            )

        if visual_updates:
            new_visual = current.visual.model_copy(update=visual_updates)
            current = current.model_copy(update={"visual": new_visual})

        return current

    def list(
        self,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> list[ProjectSummary]:
        """List valid Projects sorted by the requested field and order.

        Supported *sort_by* values: ``updated_at`` (default), ``created_at``,
        and ``name``. *sort_order* accepts ``asc`` or ``desc`` (default).

        Incomplete directories without ``project.json`` and internal deletion
        tombstones are ignored. A discovered but corrupt Project is logged as
        a warning and skipped so that one bad Project does not block listing
        the remaining healthy ones.
        """

        summaries: list[ProjectSummary] = []
        try:
            entries = sorted(self.root.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise ProjectIntegrityError(
                "Cannot scan ProjectStore root",
            ) from exc
        for entry in entries:
            if (
                entry.name.startswith(".deleted-")
                or is_link_path(entry)
                or not entry.is_dir()
            ):
                continue
            try:
                safe_id = _safe_project_id(entry.name)
            except UnsafeProjectPath:
                continue
            if not (entry / "project.json").exists():
                continue
            # Bundled example Projects never surface in "my projects".
            if (entry / BUILTIN_EXAMPLE_MARKER).exists():
                continue
            cached = (
                self._cached_summary(entry, safe_id)
                if _list_summary_cache_enabled()
                else None
            )
            if cached is not None:
                summaries.append(cached)
                continue
            # The stamp is captured *before* the read so it names the exact
            # bytes the summary will describe. ``_cache_summary`` re-checks
            # it against the live file before publishing and skips the write
            # if a commit landed in the read/build window -- otherwise an
            # old summary would be stamped with the new document's fingerprint
            # and every later list would keep serving the stale card until
            # the next write happened to invalidate it.
            stamp_before_read = _project_json_stamp(entry)
            try:
                snapshot = self.read(safe_id)
            except ProjectStoreError as exc:
                logger.warning("Skipping corrupt Project %s: %s", safe_id, exc)
                continue
            cover = _cover_reference(snapshot.project)
            summary = ProjectSummary(
                project_id=safe_id,
                name=snapshot.project.name,
                description=snapshot.project.description,
                scenario=snapshot.project.scenario,
                aspect_ratio=snapshot.project.settings.aspect_ratio,
                resolution=snapshot.project.settings.resolution,
                content_type=snapshot.project.settings.content_type,
                generation=snapshot.generation,
                created_at=snapshot.project.created_at,
                updated_at=snapshot.project.updated_at,
                etag=snapshot.etag,
                cover_version_id=cover[0] if cover else None,
                cover_version_source=cover[1] if cover else None,
                final_video_version_id=_final_video_reference(
                    snapshot.project,
                ),
            )
            if stamp_before_read is not None:
                self._cache_summary(
                    entry,
                    summary,
                    expected_stamp=stamp_before_read,
                )
            summaries.append(summary)
        reverse = sort_order == "desc"
        if sort_by == "name":
            summaries.sort(key=lambda s: s.name.lower(), reverse=reverse)
        elif sort_by == "created_at":
            summaries.sort(key=lambda s: s.created_at, reverse=reverse)
        else:
            summaries.sort(key=lambda s: s.updated_at, reverse=reverse)
        return summaries

    def _cached_summary(
        self,
        entry: Path,
        safe_id: str,
    ) -> ProjectSummary | None:
        """Return the cached listing projection while it still matches.

        ``list()`` used to read, migrate and validate every Project document to
        build one card each -- measured 34 MB and 0.7 s across eight Projects,
        on every home-page load and every return from a Project, competing for
        the GIL with whatever else the process was doing. The record is keyed on
        the document's ``(mtime_ns, size)``, so a moved document simply misses
        and the previous full read happens exactly as before. Anything malformed
        in the record is also a miss: this is a cache, never an authority.
        """

        try:
            raw = json.loads(
                (entry / PROJECT_SUMMARY_RECORD).read_text("utf-8"),
            )
        except (OSError, ValueError):
            return None
        if (
            not isinstance(raw, dict)
            or raw.get("schema") != SUMMARY_RECORD_SCHEMA
        ):
            return None
        if raw.get("projectId") != safe_id:
            # A record naming another Project is a miss, never a read.
            return None
        stamp = _project_json_stamp(entry)
        if stamp is None or raw.get("sourceStamp") != list(stamp):
            return None
        # Field-level validation is the difference between "damage is only
        # a cache miss" and "damage 500s every listing"; see the constants
        # above for the specific crash a missing check would enable.
        for key in SUMMARY_REQUIRED_STR_FIELDS:
            if not isinstance(raw.get(key), str):
                return None
        for key in SUMMARY_OPTIONAL_STR_FIELDS:
            present = raw.get(key)
            if present is not None and not isinstance(present, str):
                return None
        generation = raw.get("generation")
        if not isinstance(generation, (int, str)) or isinstance(
            generation,
            bool,
        ):
            return None
        # Parse datetimes here and refuse naive values before the
        # ``ProjectSummary`` construction; the exception that a mixed
        # naive/aware sort raises lives one call site up and this
        # method's try/except cannot see it. See the constant's comment.
        try:
            parsed_datetimes = {
                key: datetime.fromisoformat(raw[key])
                for key in SUMMARY_TZAWARE_DATETIME_FIELDS
            }
        except (KeyError, TypeError, ValueError):
            return None
        if any(
            value.tzinfo is None for value in parsed_datetimes.values()
        ):
            return None
        try:
            return ProjectSummary(
                project_id=safe_id,
                name=raw["name"],
                description=raw["description"],
                scenario=raw["scenario"],
                aspect_ratio=raw["aspectRatio"],
                resolution=raw["resolution"],
                content_type=raw["contentType"],
                generation=int(raw["generation"]),
                created_at=parsed_datetimes["createdAt"],
                updated_at=parsed_datetimes["updatedAt"],
                etag=raw["etag"],
                cover_version_id=raw.get("coverVersionId"),
                cover_version_source=raw.get("coverVersionSource"),
                final_video_version_id=raw.get("finalVideoVersionId"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _cache_summary(
        self,
        entry: Path,
        summary: ProjectSummary,
        *,
        expected_stamp: tuple[int, int],
    ) -> None:
        """Persist the listing projection; a failed write is only a miss.

        ``expected_stamp`` must be the fingerprint the summary was built
        against, captured before :meth:`read`. If the live document has moved
        on since (a concurrent commit that landed between the read and this
        call), publishing the pair would stamp an old summary with a new
        fingerprint and every later :meth:`list` would keep serving the stale
        card until the next write -- a permanently-cached stale read of a
        legal change, not the transient skew list() is allowed elsewhere.
        Skipping this turn costs one full read on the next listing, which is
        the pre-cache behaviour.
        """

        current_stamp = _project_json_stamp(entry)
        if current_stamp is None or current_stamp != expected_stamp:
            return
        stamp = current_stamp
        payload = {
            "schema": SUMMARY_RECORD_SCHEMA,
            "sourceStamp": list(stamp),
            "projectId": summary.project_id,
            "name": summary.name,
            "description": summary.description,
            "scenario": summary.scenario,
            "aspectRatio": summary.aspect_ratio,
            "resolution": summary.resolution,
            "contentType": summary.content_type,
            "generation": summary.generation,
            "createdAt": summary.created_at.isoformat(),
            "updatedAt": summary.updated_at.isoformat(),
            "etag": summary.etag,
            "coverVersionId": summary.cover_version_id,
            "coverVersionSource": summary.cover_version_source,
            "finalVideoVersionId": summary.final_video_version_id,
        }
        target = entry / PROJECT_SUMMARY_RECORD
        temp_dir = target.parent
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".summary-",
                suffix=".tmp",
                dir=temp_dir,
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                atomic_replace_path(temp_path, target)
            except BaseException:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        except OSError:
            logger.debug(
                "Project summary cache skipped for %s",
                summary.project_id,
            )

    def discover_project_ids(
        self,
        *,
        include_builtin_examples: bool = True,
    ) -> tuple[str, ...]:
        """Discover Project directory identities without loading their data.

        Startup recovery and health reporting must still be able to name a
        Project whose ``project.json`` is corrupt.  ``list()`` intentionally
        validates every Project and therefore cannot serve that purpose.
        Internal staging/tombstone directories, symlinks, unsafe names and
        incomplete directories remain outside discovery.

        *include_builtin_examples* keeps the bundled example Projects in the
        result, which is what the per-tick scheduler wants. A caller acting on
        behalf of the user's own work passes ``False`` so discovery matches
        what ``list()`` reports.
        """

        try:
            entries = sorted(self.root.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise ProjectIntegrityError(
                "Cannot scan ProjectStore root",
            ) from exc
        project_ids: list[str] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                entry_stat = entry.lstat()
                safe_id = _safe_project_id(entry.name)
            except (OSError, UnsafeProjectPath):
                continue
            if is_link_stat(entry_stat) or not stat.S_ISDIR(
                entry_stat.st_mode,
            ):
                continue
            try:
                (entry / "project.json").lstat()
            except (FileNotFoundError, OSError):
                continue
            if (
                not include_builtin_examples
                and (entry / BUILTIN_EXAMPLE_MARKER).exists()
            ):
                continue
            project_ids.append(safe_id)
        return tuple(project_ids)

    def delete(
        self,
        project_id: str,
        *,
        expected_etag: str | None = None,
        cascade: bool = True,
    ) -> None:
        """Atomically remove a Project from discovery, then delete its tree.

        When *cascade* is ``False`` only ``project.json`` is removed so the
        project vanishes from listings but assets, sessions and observability
        data remain on disk.  When ``True`` (default) the entire directory
        tree is deleted.
        """

        safe_id = _safe_project_id(project_id)
        tombstone: Path | None = None
        with self.lifecycle_lock(safe_id), self._lock:
            current = self.read(safe_id)
            if expected_etag is not None and current.etag != expected_etag:
                raise ProjectConflict(
                    f"Project ETag conflict: expected={expected_etag}, actual={current.etag}",
                )
            project_root = self.project_root(safe_id)

            if not cascade:
                manifest = project_root / "project.json"
                try:
                    manifest.unlink()
                except FileNotFoundError:
                    pass
                logger.info(
                    "project manifest deleted (data retained): %s",
                    safe_id,
                )
                return

            tombstone = self.root / f".deleted-{safe_id}-{uuid4().hex}"
            try:
                atomic_replace_path(project_root, tombstone)
                _fsync_directory(self.root)
            except OSError as exc:
                raise ProjectStoreError(
                    f"Cannot delete Project: {safe_id}",
                ) from exc
        # The atomic rename above is the deletion boundary. Physical cleanup
        # is deliberately detached: a large tree or an open provider file must
        # not keep DELETE/Stop waiting after the Project is already absent.
        # Startup recovery also removes any tombstone left by a crash.
        assert tombstone is not None

        def cleanup_deleted_tree() -> None:
            try:
                shutil.rmtree(tombstone)
            except OSError:
                logger.warning(
                    "Project tombstone cleanup deferred to startup: %s",
                    tombstone,
                    exc_info=True,
                )

        threading.Thread(
            target=cleanup_deleted_tree,
            name=f"creator-delete-cleanup:{safe_id}",
            daemon=True,
        ).start()
        logger.info("project deleted: %s", safe_id)

    def export(self, project_id: str) -> tuple[int, Iterator[bytes]]:
        """Archive the Project and recoverable Runtime under ``CREATOR_DATA_ROOT``/exports/.
        Returns the archive byte size plus an iterator yielding the contents
        in 8192-byte chunks, so HTTP callers can advertise Content-Length for
        download progress without loading the whole file into memory.

        This is a best-effort snapshot of the on-disk tree: it does not take
        the lifecycle lock, so a concurrent mutation may be partially captured.
        """
        export_root = require_creator_data_root() / "exports"
        export_root.mkdir(parents=True, exist_ok=True)

        safe_id = _safe_project_id(project_id)
        zip_file_stem = f"{safe_id}-{uuid4().hex}"
        logger.info(f"exporting to:{str(export_root / zip_file_stem)}")

        archive_path = None
        # Confirm it exists before starting. The archive itself intentionally
        # runs without either the lifecycle or in-process store lock: Project
        # files are atomically replaced, and export is explicitly a best-effort
        # snapshot. Holding the global mutation boundary across ZIP I/O caused
        # common 10-second lock timeouts on large Projects.
        snapshot = self.read(safe_id)
        try:
            archive_path = str(export_root / f"{zip_file_stem}.zip")
            write_project_archive(
                self.project_root(safe_id),
                snapshot.project,
                Path(archive_path),
            )
            logger.info(f"export file path:{archive_path}")
        except BadRequestError:
            raise
        except Exception as e:
            logger.error(
                f"failed to create export file for project {safe_id}",
                exc_info=True,
            )
            raise ProjectStoreError(
                f"failed to create export file for project {safe_id}",
            ) from e

        return (
            Path(archive_path).stat().st_size,
            self._stream_export_archive(archive_path),
        )

    def _stream_export_archive(self, archive_path: str) -> Iterator[bytes]:
        try:
            with open(archive_path, "rb") as archive_file:
                while True:
                    chunk = archive_file.read(8192)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(
                f"failed to export project bytes:{archive_path}",
                exc_info=True,
            )
            raise ProjectStoreError("failed to export project bytes") from e
        finally:
            Path(archive_path).unlink(missing_ok=True)
            logger.info(f"deleted project export zip file {archive_path}")

    def lifecycle_lock(
        self,
        project_id: str,
        *,
        shared: bool = False,
        cross_thread_hold: bool = False,
    ) -> CrossProcessFileLock:
        """Guard a Project lifetime without serializing unrelated Runtime domains.

        Project creation, deletion and Project-state publication use the
        default exclusive side. Runtime-only transitions use ``shared=True``:
        they may proceed in parallel with one another, but still cannot race a
        delete or Project commit that owns the exclusive side.
        """

        return CrossProcessFileLock(
            self.root
            / ".locks"
            / f"project-{_safe_project_id(project_id)}.lock",
            timeout_seconds=10.0,
            shared=shared,
            cross_thread_hold=cross_thread_hold,
        )

    def _checked_payload(self, project: Project) -> bytes:
        payload = project_file_bytes(project)
        if len(payload) > self.max_project_json_bytes:
            raise ProjectIntegrityError(
                f"project.json exceeds {self.max_project_json_bytes} bytes; "
                "move large content into assets/ and index it",
            )
        return payload

    def _atomic_write(self, project_root: Path, payload: bytes) -> None:
        target = project_root / "project.json"
        temp_dir = project_root / "runtime" / "temp"
        temp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".project-",
            suffix=".tmp",
            dir=temp_dir,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            atomic_replace_path(temp_path, target)
            _fsync_directory(project_root)
            _fsync_directory(temp_dir)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _require_real_project_directory(
        self,
        project_root: Path,
        project_id: str,
    ) -> None:
        try:
            project_stat = project_root.lstat()
        except FileNotFoundError as exc:
            raise ProjectNotFound(f"Project not found: {project_id}") from exc
        if is_link_stat(project_stat) or not stat.S_ISDIR(
            project_stat.st_mode,
        ):
            raise UnsafeProjectPath(
                "Project directory must be a real directory below the store root",
            )
        try:
            project_root.resolve(strict=True).relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise UnsafeProjectPath(
                "Project directory escapes the store root",
            ) from exc

    def _validate_asset_paths(
        self,
        project_root: Path,
        project: Project,
    ) -> None:
        assets_root = project_root / "assets"
        try:
            assets_stat = assets_root.lstat()
        except FileNotFoundError as exc:
            raise ProjectIntegrityError(
                "Project assets directory is missing",
            ) from exc
        if is_link_stat(assets_stat) or not stat.S_ISDIR(
            assets_stat.st_mode,
        ):
            raise UnsafeProjectPath("Project assets must be a real directory")
        resolved_assets = assets_root.resolve(strict=True)
        # ``Path.resolve()`` walks every ancestor component, so doing it once
        # per indexed file cost ~8 lstats per asset on every Project read --
        # measured 2,500 lstats/second from the reconcile tick alone on a
        # 166-asset Project.  Resolve each distinct parent once (a symlinked
        # directory still lands outside) and only inspect the leaf itself.
        resolved_parents: dict[Path, Path] = {assets_root: resolved_assets}
        for indexed in project.assets.files_by_id.values():
            candidate = project_root.joinpath(
                *_lexical_asset_parts(indexed.relative_uri),
            )
            parent = candidate.parent
            resolved_parent = resolved_parents.get(parent)
            if resolved_parent is None:
                resolved_parent = parent.resolve(strict=False)
                resolved_parents[parent] = resolved_parent
            try:
                resolved_parent.relative_to(resolved_assets)
            except ValueError as exc:
                raise UnsafeProjectPath(
                    f"Indexed file escapes Project assets: {indexed.relative_uri}",
                ) from exc
            try:
                leaf_stat = candidate.lstat()
            except FileNotFoundError:
                # A leaf that is not on disk cannot escape anything, and the
                # previous ``resolve(strict=False)`` accepted it the same way.
                continue
            except OSError as exc:
                raise UnsafeProjectPath(
                    f"Indexed file escapes Project assets: {indexed.relative_uri}",
                ) from exc
            if is_link_stat(leaf_stat):
                # Only a real symlink needs the full walk to learn where it
                # lands -- which is exactly the escape this check exists for.
                try:
                    candidate.resolve(strict=False).relative_to(
                        resolved_assets,
                    )
                except (OSError, ValueError) as exc:
                    raise UnsafeProjectPath(
                        f"Indexed file escapes Project assets: "
                        f"{indexed.relative_uri}",
                    ) from exc


def _lexical_asset_parts(relative_uri: str) -> tuple[str, ...]:
    """Collapse ``.``/``..`` textually and require the result to stay in assets.

    The Project schema already refuses traversal and absolute URIs, so this is
    a second line of defense that costs no syscalls: a URI that normalizes back
    inside the tree (``assets/sub/../artifacts/x``) keeps the same verdict the
    old per-file ``Path.resolve()`` produced, while anything that leaves
    ``assets`` is refused here instead of after a walk over every ancestor.
    """

    parts: list[str] = []
    for part in PurePosixPath(relative_uri).parts:
        if part in {"", ".", "/"}:
            continue
        if part == "..":
            if not parts:
                break
            parts.pop()
            continue
        parts.append(part)
    if not parts or parts[0] != "assets":
        raise UnsafeProjectPath(
            f"Indexed file escapes Project assets: {relative_uri}",
        )
    return tuple(parts)


def _safe_project_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or value != value.strip()
        or not _SAFE_PROJECT_ID.fullmatch(value)
        or "\x00" in value
    ):
        raise InvalidProjectId(f"Unsafe project id: {value!r}")
    return value


def _validated_project(project: Project) -> Project:
    try:
        return Project.model_validate(project.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise ProjectIntegrityError(
            "candidate does not match the Project schema",
        ) from exc


def _snapshot(project: Project) -> ProjectSnapshot:
    return ProjectSnapshot(
        project=project,
        etag=project_etag(project),
        generation=project.generation,
    )


def _fsync_directory(directory: Path) -> None:
    runtime_fsync_directory(directory)


__all__ = [
    "DEFAULT_MAX_PROJECT_JSON_BYTES",
    "InvalidProjectId",
    "ProjectAlreadyExists",
    "ProjectConflict",
    "ProjectIntegrityError",
    "ProjectNotFound",
    "ProjectSnapshot",
    "ProjectStore",
    "ProjectStoreError",
    "ProjectSummary",
    "UnsafeProjectPath",
]
