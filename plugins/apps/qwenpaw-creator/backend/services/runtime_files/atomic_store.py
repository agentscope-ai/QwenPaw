# -*- coding: utf-8 -*-
# pylint: disable=not-callable
"""Crash-safe JSON records backed by same-directory atomic publication."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, ValidationError as PydanticValidationError

from .errors import (
    CorruptRecordError,
    RecordAlreadyExistsError,
    RecordConflictError,
    RecordNotFoundError,
    RuntimeFileValidationError,
)
from .locking import CrossProcessFileLock

logger = logging.getLogger("qwenpaw.creator.runtime_files.atomic_store")


T = TypeVar("T")
WriteStageHook = Callable[[str, Path], None]
_UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS = {
    getattr(errno, name)
    for name in (
        "EACCES",
        "EBADF",
        "EINVAL",
        "EISDIR",
        "ENOTSUP",
        "EOPNOTSUPP",
        "EPERM",
    )
    if hasattr(errno, name)
}


def _is_windows() -> bool:
    return os.name == "nt"


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def strict_json_loads(payload: str | bytes | bytearray) -> Any:
    """Decode standards-compliant JSON (Python accepts NaN by default)."""

    return json.loads(payload, parse_constant=_reject_nonfinite_json)


def fsync_directory(path: str | os.PathLike[str]) -> None:
    """Persist directory-entry changes where the platform supports it."""

    directory = Path(path)
    if _is_windows():
        logger.debug("directory fsync skipped on Windows: %s", directory)
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
            logger.debug(
                "directory fsync unsupported for %s: %s",
                directory,
                exc,
            )
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
                logger.debug(
                    "directory fsync unsupported for %s: %s",
                    directory,
                    exc,
                )
                return
            raise
    finally:
        os.close(descriptor)


def chmod_descriptor_if_supported(descriptor: int, mode: int) -> None:
    """Apply POSIX fd chmod when available; Windows has no ``os.fchmod``."""

    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(descriptor, mode)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    elif isinstance(value, Mapping):
        value = dict(value)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        value = list(value)
    try:
        # Round-tripping rejects custom objects and produces detached JSON
        # data.
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return strict_json_loads(encoded)
    except (TypeError, ValueError) as exc:
        raise RuntimeFileValidationError(
            "Runtime record must be JSON serializable",
        ) from exc


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable compact JSON used for checksums and request hashes."""

    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def json_document_bytes(value: Any) -> bytes:
    """Return deterministic, human-readable JSON with a final newline."""

    return (
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def json_checksum(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def atomic_replace_bytes(
    target: str | os.PathLike[str],
    payload: bytes,
    *,
    mode: int = 0o600,
    stage_hook: WriteStageHook | None = None,
) -> None:
    """Publish bytes with temp/fsync/replace/directory-fsync ordering."""

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temp)
    if stage_hook is not None:
        stage_hook("temp_created", temporary)
    try:
        chmod_descriptor_if_supported(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if stage_hook is not None:
            stage_hook("temp_fsynced", temporary)
        os.replace(temporary, path)
        if stage_hook is not None:
            stage_hook("replaced", path)
        fsync_directory(path.parent)
        if stage_hook is not None:
            stage_hook("directory_fsynced", path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _publish_create_if_absent(temporary: Path, path: Path) -> bool:
    if _is_windows():
        try:
            os.rename(temporary, path)
        except FileExistsError:
            return False
        except OSError:
            if path.exists():
                return False
            raise
        return True

    try:
        os.link(temporary, path)
    except FileExistsError:
        return False
    return True


def atomic_create_bytes(
    target: str | os.PathLike[str],
    payload: bytes,
    *,
    mode: int = 0o600,
    stage_hook: WriteStageHook | None = None,
) -> bool:
    """Atomically publish a fully-fsynced file only when the target is absent.

    POSIX has no portable no-replace rename.  A same-directory hard link gives
    the required atomic create-if-absent operation without ever exposing a
    partially written target.  Runtime metadata and its temp file are always on
    the same filesystem.
    """

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temp)
    if stage_hook is not None:
        stage_hook("temp_created", temporary)
    try:
        chmod_descriptor_if_supported(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if stage_hook is not None:
            stage_hook("temp_fsynced", temporary)
        if not _publish_create_if_absent(temporary, path):
            return False
        if stage_hook is not None:
            stage_hook("created", path)
        if not _is_windows():
            temporary.unlink()
        fsync_directory(path.parent)
        if stage_hook is not None:
            stage_hook("directory_fsynced", path.parent)
        return True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def durable_unlink(path: str | os.PathLike[str]) -> bool:
    target = Path(path)
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    fsync_directory(target.parent)
    return True


@dataclass(frozen=True, slots=True)
class RecordSnapshot(Generic[T]):
    value: T
    checksum: str


class AtomicJsonRecordStore(Generic[T]):
    """One mutable Pydantic/JSON record with optional checksum CAS."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        model_type: type[T] | None = None,
        *,
        lock_path: str | os.PathLike[str] | None = None,
        lock_timeout_seconds: float | None = 10.0,
        mode: int = 0o600,
        stage_hook: WriteStageHook | None = None,
    ) -> None:
        self.path = Path(path)
        self.model_type = model_type
        self.lock_path = (
            Path(lock_path)
            if lock_path is not None
            else self.path.with_name(f".{self.path.name}.lock")
        )
        self.lock_timeout_seconds = lock_timeout_seconds
        self.mode = mode
        self.stage_hook = stage_hook

    def _lock(self) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self.lock_path,
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _validate(self, value: Any, *, from_disk: bool = False) -> T:
        try:
            if self.model_type is None:
                return cast(T, _json_value(value))
            validator = getattr(self.model_type, "model_validate", None)
            if validator is None:
                raise RuntimeFileValidationError(
                    "model_type must provide model_validate(): "
                    f"{self.model_type!r}",
                )
            return cast(T, validator(value))
        except (PydanticValidationError, RuntimeFileValidationError) as exc:
            if from_disk:
                raise CorruptRecordError(self.path, str(exc)) from exc
            raise RuntimeFileValidationError(
                f"Runtime record validation failed: {exc}",
            ) from exc

    @staticmethod
    def _dump_value(value: T) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json", by_alias=True)
        return _json_value(value)

    def _read_snapshot_unlocked(self) -> RecordSnapshot[T]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError as exc:
            raise RecordNotFoundError(self.path) from exc
        try:
            value = strict_json_loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            logger.error("atomic_store corruption: %s: %s", self.path, exc)
            raise CorruptRecordError(self.path, str(exc)) from exc
        validated = self._validate(value, from_disk=True)
        dumped = self._dump_value(validated)
        return RecordSnapshot(value=validated, checksum=json_checksum(dumped))

    def read_snapshot(self) -> RecordSnapshot[T]:
        # Atomic replacement means a reader sees either the complete old inode
        # or the complete new inode; no writer lock is needed here.
        return self._read_snapshot_unlocked()

    def read(self) -> T:
        return self.read_snapshot().value

    def read_or_none(self) -> T | None:
        try:
            return self.read()
        except RecordNotFoundError:
            return None

    def write(self, value: Any) -> RecordSnapshot[T]:
        validated = self._validate(value)
        dumped = self._dump_value(validated)
        with self._lock():
            atomic_replace_bytes(
                self.path,
                json_document_bytes(dumped),
                mode=self.mode,
                stage_hook=self.stage_hook,
            )
        logger.debug("atomic_store write: %s", self.path)
        return RecordSnapshot(validated, json_checksum(dumped))

    def try_create(self, value: Any) -> RecordSnapshot[T] | None:
        validated = self._validate(value)
        dumped = self._dump_value(validated)
        with self._lock():
            created = atomic_create_bytes(
                self.path,
                json_document_bytes(dumped),
                mode=self.mode,
                stage_hook=self.stage_hook,
            )
        if not created:
            return None
        return RecordSnapshot(validated, json_checksum(dumped))

    def create(self, value: Any) -> RecordSnapshot[T]:
        snapshot = self.try_create(value)
        if snapshot is None:
            logger.debug("atomic_store create skipped (exists): %s", self.path)
            raise RecordAlreadyExistsError(self.path)
        logger.debug("atomic_store create: %s", self.path)
        return snapshot

    def compare_and_swap(
        self,
        *,
        expected_checksum: str,
        value: Any,
    ) -> RecordSnapshot[T]:
        validated = self._validate(value)
        dumped = self._dump_value(validated)
        with self._lock():
            try:
                current = self._read_snapshot_unlocked()
            except RecordNotFoundError:
                current = None
            actual = current.checksum if current is not None else None
            if actual != expected_checksum:
                logger.warning(
                    "atomic_store cas conflict: %s expected=%s actual=%s",
                    self.path,
                    expected_checksum[:16],
                    actual[:16] if actual else "none",
                )
                raise RecordConflictError(
                    self.path,
                    expected_checksum=expected_checksum,
                    actual_checksum=actual,
                )
            atomic_replace_bytes(
                self.path,
                json_document_bytes(dumped),
                mode=self.mode,
                stage_hook=self.stage_hook,
            )
        logger.debug("atomic_store cas: %s", self.path)
        return RecordSnapshot(validated, json_checksum(dumped))

    def update(
        self,
        mutator: Callable[[T], Any],
        *,
        expected_checksum: str | None = None,
    ) -> RecordSnapshot[T]:
        with self._lock():
            current = self._read_snapshot_unlocked()
            if (
                expected_checksum is not None
                and current.checksum != expected_checksum
            ):
                logger.warning(
                    "atomic_store update conflict: %s expected=%s actual=%s",
                    self.path,
                    expected_checksum[:16],
                    current.checksum[:16],
                )
                raise RecordConflictError(
                    self.path,
                    expected_checksum=expected_checksum,
                    actual_checksum=current.checksum,
                )
            validated = self._validate(mutator(current.value))
            dumped = self._dump_value(validated)
            atomic_replace_bytes(
                self.path,
                json_document_bytes(dumped),
                mode=self.mode,
                stage_hook=self.stage_hook,
            )
        logger.debug("atomic_store update: %s", self.path)
        return RecordSnapshot(validated, json_checksum(dumped))

    def delete(self, *, expected_checksum: str | None = None) -> None:
        with self._lock():
            current = self._read_snapshot_unlocked()
            if (
                expected_checksum is not None
                and current.checksum != expected_checksum
            ):
                logger.warning(
                    "atomic_store delete conflict: %s expected=%s actual=%s",
                    self.path,
                    expected_checksum[:16],
                    current.checksum[:16],
                )
                raise RecordConflictError(
                    self.path,
                    expected_checksum=expected_checksum,
                    actual_checksum=current.checksum,
                )
            if not durable_unlink(
                self.path,
            ):  # pragma: no cover - lock makes this defensive
                raise RecordNotFoundError(self.path)
        logger.debug("atomic_store delete: %s", self.path)


class CreateIfAbsentJsonStore(Generic[T]):
    """Immutable JSON records addressed by a caller-supplied safe key."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        model_type: type[T] | None = None,
        *,
        suffix: str = ".json",
        mode: int = 0o600,
        lock_timeout_seconds: float | None = 10.0,
    ) -> None:
        self.root = Path(root)
        self.model_type = model_type
        self.suffix = suffix
        self.mode = mode
        self.lock_timeout_seconds = lock_timeout_seconds

    @staticmethod
    def validate_key(key: str) -> str:
        if not key or key in {".", ".."}:
            raise RuntimeFileValidationError(
                "record key must not be empty or dot-segment",
            )
        if any(character in key for character in ("/", "\\", "\x00")):
            raise RuntimeFileValidationError(
                f"record key is not a safe path segment: {key!r}",
            )
        if any(
            ord(character) < 32 or ord(character) == 127 for character in key
        ):
            raise RuntimeFileValidationError(
                f"record key contains control characters: {key!r}",
            )
        return key

    def path_for(self, key: str) -> Path:
        return self.root / f"{self.validate_key(key)}{self.suffix}"

    def _store_for(self, key: str) -> AtomicJsonRecordStore[T]:
        path = self.path_for(key)
        return AtomicJsonRecordStore(
            path,
            self.model_type,
            lock_path=self.root / ".locks" / f"{path.name}.lock",
            mode=self.mode,
            lock_timeout_seconds=self.lock_timeout_seconds,
        )

    def create(self, key: str, value: Any) -> bool:
        return self._store_for(key).try_create(value) is not None

    def read(self, key: str) -> T:
        return self._store_for(key).read()

    def read_or_none(self, key: str) -> T | None:
        return self._store_for(key).read_or_none()
