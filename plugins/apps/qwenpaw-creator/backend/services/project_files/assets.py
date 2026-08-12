# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-boolean-expressions,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
# pylint: disable=try-except-raise
"""Crash-safe, immutable file storage below one Project's ``assets/`` tree.

``project.json`` owns the meaning of every published file.  This module owns
only the file boundary: staging, content identity, immutable publication,
verified reads, and discovery of unindexed files.  It deliberately does not
create an Asset Index sidecar or any AI-edit-plan-specific directory.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import errno
import hashlib
import logging
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import BinaryIO, Final
from uuid import uuid4

from services.runtime_files.atomic_store import (
    fsync_directory as runtime_fsync_directory,
)

from .models import AssetIndex, IndexedFile

logger = logging.getLogger("qwenpaw.creator.project_files.assets")


DEFAULT_CHUNK_SIZE: Final = 4 * 1024 * 1024
DEFAULT_ORPHAN_GRACE_PERIOD: Final = timedelta(hours=24)
_SAFE_STAGING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _is_windows() -> bool:
    return os.name == "nt"


def _supports_dir_fd_publication() -> bool:
    return (
        not _is_windows()
        and hasattr(os, "O_NOFOLLOW")
        and os.link in os.supports_dir_fd
        and os.open in os.supports_dir_fd
        and os.rename in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )


class AssetFileError(RuntimeError):
    """Base error for Project Asset file operations."""


class AssetPathError(AssetFileError):
    """An Asset path is non-canonical, unsafe, or escapes its Project."""


class AssetAlreadyExists(AssetFileError):
    """The immutable destination is already occupied."""


class AssetFileMissing(AssetFileError):
    """An IndexedFile has no corresponding file on disk."""


class AssetFileCorrupt(AssetFileError):
    """An Asset does not match its indexed content identity."""


class AssetFileNotRegular(AssetFileError):
    """An Asset path names something other than a regular file."""


class StagedAssetError(AssetFileError):
    """A staging handle is invalid, foreign, missing, or was modified."""


class AssetFileStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    CORRUPT = "corrupt"
    UNSAFE = "unsafe"
    NOT_REGULAR = "not_regular"


@dataclass(frozen=True, slots=True)
class StagedAsset:
    """A fully written and fsynced file that has not been published yet."""

    project_root: Path
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PublishedAsset:
    """Content identity returned after immutable publication."""

    relative_uri: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class AssetInspection:
    file_id: str
    relative_uri: str
    status: AssetFileStatus
    expected_size_bytes: int
    expected_sha256: str
    actual_size_bytes: int | None = None
    actual_sha256: str | None = None
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.status is AssetFileStatus.AVAILABLE


@dataclass(frozen=True, slots=True)
class AssetValidationReport:
    files: tuple[AssetInspection, ...]

    @property
    def valid(self) -> bool:
        return all(item.available for item in self.files)

    @property
    def failures(self) -> tuple[AssetInspection, ...]:
        return tuple(item for item in self.files if not item.available)


@dataclass(frozen=True, slots=True)
class OrphanCandidate:
    """An unindexed regular file observed by Runtime and eligible only later.

    Runtime persists ``first_observed_at`` in its GC records and supplies it on
    subsequent scans.  A newly discovered file is never immediately eligible,
    even if its filesystem mtime is old.
    """

    relative_uri: str
    size_bytes: int
    first_observed_at: datetime
    eligible_after: datetime
    eligible_for_collection: bool


@dataclass(frozen=True, slots=True)
class OrphanScan:
    candidates: tuple[OrphanCandidate, ...]
    unsafe_entries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FileFingerprint:
    device: int
    inode: int
    size_bytes: int
    modified_ns: int
    changed_ns: int


class AssetFileStore:
    """Filesystem boundary for immutable files in one Project directory."""

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        raw_root = Path(project_root).expanduser()
        if not raw_root.is_absolute():
            raise AssetPathError("Project root must be an absolute path")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        _require_real_directory(raw_root, label="Project root")
        self.project_root = raw_root.resolve(strict=True)
        self.chunk_size = chunk_size

        assets_root = self.project_root / "assets"
        _mkdir_real(assets_root, parent=self.project_root, label="assets")
        self.assets_root = assets_root
        self._resolved_assets_root = assets_root.resolve(strict=True)

        staging_root = assets_root / ".staging"
        created_staging = _mkdir_real(
            staging_root,
            parent=assets_root,
            label="Asset staging",
        )
        self.staging_root = staging_root
        if created_staging:
            _fsync_directory(assets_root)

    def stage_stream(
        self,
        source: BinaryIO,
        *,
        staging_id: str | None = None,
    ) -> StagedAsset:
        """Stream ``source`` to a private staging file, hash it, and fsync it."""

        self._validate_roots()
        if staging_id is not None and not _SAFE_STAGING_ID.fullmatch(
            staging_id,
        ):
            raise AssetPathError(f"Unsafe staging id: {staging_id!r}")
        prefix = staging_id or "asset"
        path = self.staging_root / f"{prefix}.{uuid4().hex}.part"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with os.fdopen(descriptor, "wb") as target:
                while True:
                    chunk = source.read(self.chunk_size)
                    if chunk is None:
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("Asset source must return bytes")
                    data = bytes(chunk)
                    if not data:
                        break
                    target.write(data)
                    digest.update(data)
                    size_bytes += len(data)
                target.flush()
                os.fsync(target.fileno())
            _fsync_directory(self.staging_root)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        return StagedAsset(
            project_root=self.project_root,
            path=path,
            sha256=digest.hexdigest(),
            size_bytes=size_bytes,
        )

    def stage_bytes(
        self,
        content: bytes | bytearray | memoryview,
        *,
        staging_id: str | None = None,
    ) -> StagedAsset:
        """Convenience wrapper around :meth:`stage_stream` for small payloads."""

        from io import BytesIO

        return self.stage_stream(
            BytesIO(bytes(content)),
            staging_id=staging_id,
        )

    def publish(
        self,
        staged: StagedAsset,
        relative_uri: str,
        *,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> PublishedAsset:
        """Atomically publish a staged file without replacing any destination.

        The destination is created with an exclusive hard-link operation and
        the staging name is then removed.  Both names are on the same Project
        ``assets`` filesystem, so readers see either no final file or the full,
        already-fsynced inode.  Existing content is never overwritten.
        """

        parts = _asset_uri_parts(relative_uri)
        if parts[1] == ".staging":
            raise AssetPathError(
                "Published Assets cannot use the reserved .staging path",
            )
        self._validate_roots()
        actual_sha256, actual_size, verified_fingerprint = self._verify_staged(
            staged,
        )
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise StagedAssetError(
                "Staged Asset does not match expected sha256",
            )
        if (
            expected_size_bytes is not None
            and actual_size != expected_size_bytes
        ):
            raise StagedAssetError("Staged Asset does not match expected size")

        parent = self._ensure_final_parent(parts[1:-1])
        target = parent / parts[-1]
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None:
            raise AssetAlreadyExists(
                f"Immutable Asset already exists: {relative_uri}",
            )
        if not _supports_dir_fd_publication():
            self._publish_staged_path_fallback(
                staged,
                target,
                relative_uri,
                verified_fingerprint,
            )
            logger.info(
                "asset published: uri=%s size=%d sha256=%s",
                PurePosixPath(*parts).as_posix(),
                actual_size,
                actual_sha256[:16],
            )
            return PublishedAsset(
                relative_uri=PurePosixPath(*parts).as_posix(),
                sha256=actual_sha256,
                size_bytes=actual_size,
            )

        source_dir_fd = _open_directory(self.staging_root)
        target_dir_fd = _open_directory(parent)
        linked = False
        target_durable = False
        try:
            try:
                os.link(
                    staged.path.name,
                    target.name,
                    src_dir_fd=source_dir_fd,
                    dst_dir_fd=target_dir_fd,
                    follow_symlinks=False,
                )
                linked = True
            except FileExistsError as exc:
                raise AssetAlreadyExists(
                    f"Immutable Asset already exists: {relative_uri}",
                ) from exc
            except OSError as exc:
                raise AssetFileError(
                    f"Cannot publish Asset: {relative_uri}",
                ) from exc

            source_stat = os.stat(
                staged.path.name,
                dir_fd=source_dir_fd,
                follow_symlinks=False,
            )
            target_stat = os.stat(
                target.name,
                dir_fd=target_dir_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(source_stat.st_mode)
                or not stat.S_ISREG(target_stat.st_mode)
                or not _matches_published_file(
                    source_stat,
                    verified_fingerprint,
                )
                or not _matches_published_file(
                    target_stat,
                    verified_fingerprint,
                )
            ):
                raise StagedAssetError(
                    "Staged Asset changed during publication",
                )
            os.fsync(target_dir_fd)
            target_durable = True
            try:
                os.unlink(staged.path.name, dir_fd=source_dir_fd)
            except OSError as exc:
                # The authoritative final name is already durable.  Surface a
                # precise cleanup failure; a later staging sweep may remove the
                # harmless duplicate link.
                raise AssetFileError(
                    f"Asset published but staging cleanup failed: {relative_uri}",
                ) from exc
            os.fsync(source_dir_fd)
        except Exception:
            # Roll back only before the final directory entry was made durable.
            # Once fsync succeeds, the immutable final path is authoritative
            # and must not be silently removed by cleanup logic.
            if linked and not target_durable:
                try:
                    os.unlink(target.name, dir_fd=target_dir_fd)
                    os.fsync(target_dir_fd)
                except OSError:
                    pass
            raise
        finally:
            os.close(source_dir_fd)
            os.close(target_dir_fd)

        logger.info(
            "asset published: uri=%s size=%d sha256=%s",
            PurePosixPath(*parts).as_posix(),
            actual_size,
            actual_sha256[:16],
        )
        return PublishedAsset(
            relative_uri=PurePosixPath(*parts).as_posix(),
            sha256=actual_sha256,
            size_bytes=actual_size,
        )

    def _publish_staged_path_fallback(
        self,
        staged: StagedAsset,
        target: Path,
        relative_uri: str,
        verified_fingerprint: _FileFingerprint,
    ) -> None:
        source = staged.path
        linked = False
        source_moved = False
        target_durable = False
        try:
            source_stat = source.lstat()
            if (
                stat.S_ISLNK(source_stat.st_mode)
                or not stat.S_ISREG(source_stat.st_mode)
                or not _matches_published_file(
                    source_stat,
                    verified_fingerprint,
                )
            ):
                raise StagedAssetError(
                    "Staged Asset changed during publication",
                )
            try:
                os.link(source, target)
                linked = True
            except FileExistsError as exc:
                raise AssetAlreadyExists(
                    f"Immutable Asset already exists: {relative_uri}",
                ) from exc
            except OSError as exc:
                if not _is_windows():
                    raise AssetFileError(
                        f"Cannot publish Asset: {relative_uri}",
                    ) from exc
                try:
                    os.rename(source, target)
                    source_moved = True
                except FileExistsError as exists:
                    raise AssetAlreadyExists(
                        f"Immutable Asset already exists: {relative_uri}",
                    ) from exists
                except OSError as rename_error:
                    raise AssetFileError(
                        f"Cannot publish Asset: {relative_uri}",
                    ) from rename_error

            target_stat = target.lstat()
            if (
                stat.S_ISLNK(target_stat.st_mode)
                or not stat.S_ISREG(target_stat.st_mode)
                or not _matches_published_file(
                    target_stat,
                    verified_fingerprint,
                )
            ):
                raise StagedAssetError(
                    "Staged Asset changed during publication",
                )
            _fsync_directory(target.parent)
            target_durable = True
            if not source_moved:
                try:
                    source.unlink()
                except OSError as exc:
                    raise AssetFileError(
                        f"Asset published but staging cleanup failed: {relative_uri}",
                    ) from exc
            _fsync_directory(self.staging_root)
        except Exception:
            if linked and not target_durable:
                try:
                    target.unlink()
                    _fsync_directory(target.parent)
                except OSError:
                    pass
            if source_moved and not target_durable:
                try:
                    os.rename(target, source)
                    _fsync_directory(self.staging_root)
                except OSError:
                    pass
            raise

    def abandon(self, staged: StagedAsset) -> None:
        """Remove an unpublished staging file owned by this store."""

        self._validate_staged_handle(staged)
        try:
            staged.path.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(self.staging_root)

    def inspect(self, indexed: IndexedFile) -> AssetInspection:
        """Return a non-throwing availability result for one IndexedFile."""

        try:
            stream, actual_size = self._open_candidate(indexed.relative_uri)
        except AssetFileMissing as exc:
            return _inspection(
                indexed,
                AssetFileStatus.MISSING,
                detail=str(exc),
            )
        except AssetFileNotRegular as exc:
            return _inspection(
                indexed,
                AssetFileStatus.NOT_REGULAR,
                detail=str(exc),
            )
        except AssetPathError as exc:
            return _inspection(
                indexed,
                AssetFileStatus.UNSAFE,
                detail=str(exc),
            )

        with stream:
            if actual_size != indexed.size_bytes:
                return _inspection(
                    indexed,
                    AssetFileStatus.CORRUPT,
                    actual_size=actual_size,
                    detail="size does not match Asset Index",
                )
            actual_sha256, streamed_size = _hash_stream(
                stream,
                self.chunk_size,
            )
        if streamed_size != actual_size:
            return _inspection(
                indexed,
                AssetFileStatus.CORRUPT,
                actual_size=streamed_size,
                actual_sha256=actual_sha256,
                detail="file changed while it was being inspected",
            )
        if actual_sha256 != indexed.sha256:
            return _inspection(
                indexed,
                AssetFileStatus.CORRUPT,
                actual_size=actual_size,
                actual_sha256=actual_sha256,
                detail="sha256 does not match Asset Index",
            )
        return _inspection(
            indexed,
            AssetFileStatus.AVAILABLE,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
        )

    def validate_index(self, index: AssetIndex) -> AssetValidationReport:
        """Inspect every IndexedFile without making Project loading all-or-none."""

        return AssetValidationReport(
            files=tuple(
                self.inspect(index.files_by_id[file_id])
                for file_id in sorted(index.files_by_id)
            ),
        )

    def require_valid_index(self, index: AssetIndex) -> AssetValidationReport:
        """Strict validation for commit/readiness paths that require all files."""

        report = self.validate_index(index)
        if not report.valid:
            summary = ", ".join(
                f"{item.file_id}={item.status.value}"
                for item in report.failures
            )
            raise AssetFileCorrupt(
                f"Asset Index contains unavailable files: {summary}",
            )
        return report

    def open_verified(self, indexed: IndexedFile) -> BinaryIO:
        """Open an IndexedFile only after size and sha256 match on the same fd."""

        stream, actual_size = self._open_candidate(indexed.relative_uri)
        try:
            if actual_size != indexed.size_bytes:
                raise AssetFileCorrupt(
                    f"Asset size mismatch for {indexed.file_id}: "
                    f"expected={indexed.size_bytes}, actual={actual_size}",
                )
            actual_sha256, streamed_size = _hash_stream(
                stream,
                self.chunk_size,
            )
            if streamed_size != actual_size:
                raise AssetFileCorrupt(
                    f"Asset changed while being read: {indexed.file_id}",
                )
            if actual_sha256 != indexed.sha256:
                raise AssetFileCorrupt(
                    f"Asset sha256 mismatch for {indexed.file_id}: "
                    f"expected={indexed.sha256}, actual={actual_sha256}",
                )
            stream.seek(0)
            return stream
        except Exception:
            stream.close()
            raise

    def read_verified(self, indexed: IndexedFile) -> bytes:
        """Read a small IndexedFile through the verified-read boundary."""

        with self.open_verified(indexed) as stream:
            return stream.read()

    def scan_orphans(
        self,
        index: AssetIndex,
        *,
        previous_candidates: Mapping[str, datetime] | None = None,
        now: datetime | None = None,
        grace_period: timedelta = DEFAULT_ORPHAN_GRACE_PERIOD,
    ) -> OrphanScan:
        """Find unindexed files and emit GC candidates; never delete them.

        ``previous_candidates`` is Runtime-owned durable state mapping URI to
        its first observation.  Requiring a positive grace period and treating
        every newly seen orphan as new prevents an old mtime from bypassing the
        two-phase deletion protocol.
        """

        if grace_period <= timedelta(0):
            raise ValueError("orphan grace_period must be positive")
        observed_at = _utc_datetime(
            now or datetime.now(timezone.utc),
            label="now",
        )
        previous = {
            uri: _utc_datetime(value, label=f"previous candidate {uri}")
            for uri, value in (previous_candidates or {}).items()
        }
        referenced = {
            PurePosixPath(*_asset_uri_parts(item.relative_uri)).as_posix()
            for item in index.files_by_id.values()
        }
        disk_files, unsafe_entries = self._walk_asset_files()
        candidates: list[OrphanCandidate] = []
        for relative_uri, file_stat in sorted(disk_files.items()):
            if relative_uri in referenced:
                continue
            first_observed = previous.get(relative_uri, observed_at)
            eligible_after = first_observed + grace_period
            candidates.append(
                OrphanCandidate(
                    relative_uri=relative_uri,
                    size_bytes=file_stat.st_size,
                    first_observed_at=first_observed,
                    eligible_after=eligible_after,
                    eligible_for_collection=observed_at >= eligible_after,
                ),
            )
        return OrphanScan(
            candidates=tuple(candidates),
            unsafe_entries=tuple(sorted(unsafe_entries)),
        )

    def _verify_staged(
        self,
        staged: StagedAsset,
    ) -> tuple[str, int, _FileFingerprint]:
        self._validate_staged_handle(staged)
        try:
            stream, size_bytes = _open_regular(
                staged.path,
                missing_error=StagedAssetError,
            )
        except AssetFileError as exc:
            raise StagedAssetError(
                "Staged Asset is not a regular file",
            ) from exc
        with stream:
            before = _file_fingerprint(os.fstat(stream.fileno()))
            sha256, streamed_size = _hash_stream(stream, self.chunk_size)
            after = _file_fingerprint(os.fstat(stream.fileno()))
        if before != after or streamed_size != size_bytes:
            raise StagedAssetError("Staged Asset changed while being verified")
        if size_bytes != staged.size_bytes or sha256 != staged.sha256:
            raise StagedAssetError("Staged Asset was modified after staging")
        return sha256, size_bytes, after

    def _validate_staged_handle(self, staged: StagedAsset) -> None:
        if (
            not isinstance(staged, StagedAsset)
            or staged.project_root != self.project_root
        ):
            raise StagedAssetError(
                "Staged Asset belongs to a different Project",
            )
        if staged.path.parent != self.staging_root:
            raise StagedAssetError(
                "Staged Asset is outside this Project staging directory",
            )
        try:
            staged.path.resolve(strict=False).relative_to(self.staging_root)
        except (OSError, ValueError) as exc:
            raise StagedAssetError("Staged Asset escapes its Project") from exc

    def _open_candidate(self, relative_uri: str) -> tuple[BinaryIO, int]:
        parts = _asset_uri_parts(relative_uri)
        if parts[1] == ".staging":
            raise AssetPathError(
                "Asset Index cannot reference the reserved .staging path",
            )
        self._validate_roots()
        parent = self._require_final_parent(parts[1:-1])
        target = parent / parts[-1]
        return _open_regular(target, missing_error=AssetFileMissing)

    def _ensure_final_parent(self, directory_parts: tuple[str, ...]) -> Path:
        current = self.assets_root
        for part in directory_parts:
            child = current / part
            created = _mkdir_real(
                child,
                parent=current,
                label="Asset directory",
            )
            if created:
                _fsync_directory(current)
            current = child
        return current

    def _require_final_parent(self, directory_parts: tuple[str, ...]) -> Path:
        current = self.assets_root
        for part in directory_parts:
            child = current / part
            try:
                _require_real_directory(child, label="Asset directory")
            except FileNotFoundError as exc:
                raise AssetFileMissing(
                    f"Asset directory is missing: {child}",
                ) from exc
            current = child
        try:
            current.resolve(strict=True).relative_to(
                self._resolved_assets_root,
            )
        except (OSError, ValueError) as exc:
            raise AssetPathError(
                "Asset parent escapes the Project assets directory",
            ) from exc
        return current

    def _validate_roots(self) -> None:
        _require_real_directory(self.project_root, label="Project root")
        _require_real_directory(self.assets_root, label="assets")
        _require_real_directory(self.staging_root, label="Asset staging")
        try:
            self.assets_root.resolve(strict=True).relative_to(
                self.project_root,
            )
            self.staging_root.resolve(strict=True).relative_to(
                self._resolved_assets_root,
            )
        except (OSError, ValueError) as exc:
            raise AssetPathError(
                "Asset storage root escapes its Project",
            ) from exc

    def _walk_asset_files(self) -> tuple[dict[str, os.stat_result], list[str]]:
        self._validate_roots()
        files: dict[str, os.stat_result] = {}
        unsafe: list[str] = []

        def visit(directory: Path, relative_parts: tuple[str, ...]) -> None:
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError as exc:
                raise AssetFileError(
                    f"Cannot scan Asset directory: {directory}",
                ) from exc
            for entry in entries:
                if not relative_parts and entry.name == ".staging":
                    continue
                uri = PurePosixPath(
                    "assets",
                    *relative_parts,
                    entry.name,
                ).as_posix()
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError:
                    unsafe.append(uri)
                    continue
                if stat.S_ISLNK(entry_stat.st_mode):
                    unsafe.append(uri)
                elif stat.S_ISDIR(entry_stat.st_mode):
                    visit(Path(entry.path), (*relative_parts, entry.name))
                elif stat.S_ISREG(entry_stat.st_mode):
                    files[uri] = entry_stat
                else:
                    unsafe.append(uri)

        visit(self.assets_root, ())
        return files, unsafe


def _inspection(
    indexed: IndexedFile,
    status: AssetFileStatus,
    *,
    actual_size: int | None = None,
    actual_sha256: str | None = None,
    detail: str | None = None,
) -> AssetInspection:
    return AssetInspection(
        file_id=indexed.file_id,
        relative_uri=indexed.relative_uri,
        status=status,
        expected_size_bytes=indexed.size_bytes,
        expected_sha256=indexed.sha256,
        actual_size_bytes=actual_size,
        actual_sha256=actual_sha256,
        detail=detail,
    )


def _asset_uri_parts(value: str) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or "\x00" in value
        or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        )
    ):
        raise AssetPathError("Asset URI must be a normalized POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) < 2
        or path.parts[0] != "assets"
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise AssetPathError(
            "Asset URI must name a canonical file below assets/",
        )
    return tuple(path.parts)


def _mkdir_real(path: Path, *, parent: Path, label: str) -> bool:
    try:
        path.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        created = False
    _require_real_directory(path, label=label)
    try:
        path.resolve(strict=True).relative_to(parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise AssetPathError(f"{label} escapes its expected parent") from exc
    return created


def _require_real_directory(path: Path, *, label: str) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        raise
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise AssetPathError(f"{label} must be a real, non-symlink directory")


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AssetPathError(
            f"Cannot securely open Asset directory: {path}",
        ) from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise AssetPathError(f"Asset path is not a directory: {path}")
    return descriptor


def _open_regular(
    path: Path,
    *,
    missing_error: type[AssetFileError],
) -> tuple[BinaryIO, int]:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as exc:
        raise missing_error(f"Asset file is missing: {path}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise AssetPathError(f"Asset file cannot be a symlink: {path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise AssetFileNotRegular(f"Asset must be a regular file: {path}")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise missing_error(f"Asset file is missing: {path}") from exc
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise AssetPathError(
                f"Asset file cannot be a symlink: {path}",
            ) from exc
        raise AssetFileError(f"Cannot open Asset file: {path}") from exc
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode):
        os.close(descriptor)
        raise AssetFileNotRegular(f"Asset must be a regular file: {path}")
    return os.fdopen(descriptor, "rb"), file_stat.st_size


def _hash_stream(stream: BinaryIO, chunk_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
        size_bytes += len(chunk)
    return digest.hexdigest(), size_bytes


def _file_fingerprint(value: os.stat_result) -> _FileFingerprint:
    return _FileFingerprint(
        device=value.st_dev,
        inode=value.st_ino,
        size_bytes=value.st_size,
        modified_ns=value.st_mtime_ns,
        changed_ns=value.st_ctime_ns,
    )


def _matches_published_file(
    value: os.stat_result,
    verified: _FileFingerprint,
) -> bool:
    # Creating the final hard link legitimately changes ctime/link count.  The
    # inode, size and content mtime must remain the ones that were hashed.
    return (
        value.st_dev == verified.device
        and value.st_ino == verified.inode
        and value.st_size == verified.size_bytes
        and value.st_mtime_ns == verified.modified_ns
    )


def _utc_datetime(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value.astimezone(timezone.utc)


def _fsync_directory(directory: Path) -> None:
    runtime_fsync_directory(directory)


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_ORPHAN_GRACE_PERIOD",
    "AssetAlreadyExists",
    "AssetFileCorrupt",
    "AssetFileError",
    "AssetFileMissing",
    "AssetFileNotRegular",
    "AssetFileStatus",
    "AssetFileStore",
    "AssetInspection",
    "AssetPathError",
    "AssetValidationReport",
    "OrphanCandidate",
    "OrphanScan",
    "PublishedAsset",
    "StagedAsset",
    "StagedAssetError",
]
