# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=try-except-raise
"""Filesystem ProjectStore for the single ``project.json`` authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
from uuid import uuid4

from pydantic import ValidationError
from services.runtime_files.locking import CrossProcessFileLock

from .models import Project
from .serialization import (
    CanonicalJsonError,
    load_project_json,
    project_etag,
    project_file_bytes,
)


DEFAULT_MAX_PROJECT_JSON_BYTES = 8 * 1024 * 1024
_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    project: Project
    etag: str
    generation: int


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
        staged_project = staging_root / f"{candidate.project_id}.{uuid4().hex}"

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
        if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(
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
            project = load_project_json(payload)
        except CanonicalJsonError as exc:
            raise ProjectIntegrityError(
                f"Invalid project.json for {safe_id}",
            ) from exc
        if project.project_id != safe_id:
            raise ProjectIntegrityError(
                f"Project identity mismatch: directory={safe_id}, file={project.project_id}",
            )
        self._validate_asset_paths(project_root, project)
        return _snapshot(project)

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

    def list(
        self,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> list[ProjectSummary]:
        """List valid Projects sorted by the requested field and order.

        Supported *sort_by* values: ``updated_at`` (default), ``created_at``,
        and ``name``. *sort_order* accepts ``asc`` or ``desc`` (default).

        Incomplete directories without ``project.json`` and internal deletion
        tombstones are ignored. A discovered but corrupt Project is surfaced as
        an integrity error instead of being silently hidden from callers.
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
                or entry.is_symlink()
                or not entry.is_dir()
            ):
                continue
            try:
                safe_id = _safe_project_id(entry.name)
            except UnsafeProjectPath:
                continue
            if not (entry / "project.json").exists():
                continue
            snapshot = self.read(safe_id)
            summaries.append(
                ProjectSummary(
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
                ),
            )
        reverse = sort_order == "desc"
        if sort_by == "name":
            summaries.sort(key=lambda s: s.name.lower(), reverse=reverse)
        elif sort_by == "created_at":
            summaries.sort(key=lambda s: s.created_at, reverse=reverse)
        else:
            summaries.sort(key=lambda s: s.updated_at, reverse=reverse)
        return summaries

    def discover_project_ids(self) -> tuple[str, ...]:
        """Discover Project directory identities without loading their data.

        Startup recovery and health reporting must still be able to name a
        Project whose ``project.json`` is corrupt.  ``list()`` intentionally
        validates every Project and therefore cannot serve that purpose.
        Internal staging/tombstone directories, symlinks, unsafe names and
        incomplete directories remain outside discovery.
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
            if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(
                entry_stat.st_mode,
            ):
                continue
            try:
                (entry / "project.json").lstat()
            except (FileNotFoundError, OSError):
                continue
            project_ids.append(safe_id)
        return tuple(project_ids)

    def delete(
        self,
        project_id: str,
        *,
        expected_etag: str | None = None,
    ) -> None:
        """Atomically remove a Project from discovery, then delete its tree."""

        safe_id = _safe_project_id(project_id)
        with self.lifecycle_lock(safe_id), self._lock:
            current = self.read(safe_id)
            if expected_etag is not None and current.etag != expected_etag:
                raise ProjectConflict(
                    f"Project ETag conflict: expected={expected_etag}, actual={current.etag}",
                )
            project_root = self.project_root(safe_id)
            tombstone = self.root / f".deleted-{safe_id}-{uuid4().hex}"
            try:
                os.replace(project_root, tombstone)
                _fsync_directory(self.root)
            except OSError as exc:
                raise ProjectStoreError(
                    f"Cannot delete Project: {safe_id}",
                ) from exc
            try:
                shutil.rmtree(tombstone)
            except OSError as exc:
                # The Project is already logically absent. Leave the hidden
                # tombstone for startup cleanup instead of moving it back and
                # accidentally resurrecting stale data.
                raise ProjectStoreError(
                    f"Project was removed but tombstone cleanup failed: {safe_id}",
                ) from exc

    def lifecycle_lock(self, project_id: str) -> CrossProcessFileLock:
        """Serialize creation/deletion with all Project-scoped mutations."""

        return CrossProcessFileLock(
            self.root
            / ".locks"
            / f"project-{_safe_project_id(project_id)}.lock",
            timeout_seconds=10.0,
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
            os.replace(temp_path, target)
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
        if stat.S_ISLNK(project_stat.st_mode) or not stat.S_ISDIR(
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
        if stat.S_ISLNK(assets_stat.st_mode) or not stat.S_ISDIR(
            assets_stat.st_mode,
        ):
            raise UnsafeProjectPath("Project assets must be a real directory")
        resolved_assets = assets_root.resolve(strict=True)
        for indexed in project.assets.files_by_id.values():
            path = PurePosixPath(indexed.relative_uri)
            candidate = project_root.joinpath(*path.parts)
            try:
                candidate.resolve(strict=False).relative_to(resolved_assets)
            except (OSError, ValueError) as exc:
                raise UnsafeProjectPath(
                    f"Indexed file escapes Project assets: {indexed.relative_uri}",
                ) from exc


def _safe_project_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or value != value.strip()
        or not _SAFE_PROJECT_ID.fullmatch(value)
        or "\x00" in value
    ):
        raise UnsafeProjectPath(f"Unsafe project id: {value!r}")
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
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DEFAULT_MAX_PROJECT_JSON_BYTES",
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
