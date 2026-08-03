# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Content-addressed storage for immutable Creator blobs and artifacts.

This module is deliberately independent from any source-tree workspace layout.  It
stores bytes under the external Creator data root and never exposes a mutable
project directory to agents.  Callers persist only the returned SHA-256 digest
in revision/working-tree entries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import BinaryIO, Literal, Protocol

from domain.errors import StorageIntegrityError, ValidationError


ContentNamespace = Literal["blob", "artifact"]
WriteStageHook = Callable[[str, Path], None]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE_DIR = {"blob": "blobs", "artifact": "artifacts"}


class DataRootProvider(Protocol):
    def __call__(self) -> str | os.PathLike[str]:
        ...


@dataclass(frozen=True, slots=True)
class StoredContent:
    namespace: ContentNamespace
    sha256: str
    size: int
    path: Path


def _notify(hook: WriteStageHook | None, stage: str, path: Path) -> None:
    if hook is not None:
        hook(stage, path)


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry update where the platform supports it."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:  # pragma: no cover - uncommon platform limitation
        raise StorageIntegrityError(f"无法打开目录进行 fsync: {path}") from exc
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace_bytes(
    target: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
    stage_hook: WriteStageHook | None = None,
) -> None:
    """Crash-safe private metadata replacement.

    The current target remains authoritative until the complete temp file has been
    flushed and atomically renamed.  This helper is also used by the revision,
    working-tree and journal file repositories; it never writes agent-facing
    workspace content directly.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temp_path = Path(raw_temp)
    _notify(stage_hook, "temp_created", temp_path)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _notify(stage_hook, "temp_fsynced", temp_path)
        os.replace(temp_path, target)
        _notify(stage_hook, "renamed", target)
        _fsync_directory(target.parent)
        _notify(stage_hook, "directory_fsynced", target.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)
        raise


def atomic_copy_file(
    source: Path,
    target: Path,
    *,
    mode: int = 0o600,
    stage_hook: WriteStageHook | None = None,
) -> None:
    """Crash-safe streaming copy for replaceable task scratch files.

    Large uploads must not be loaded into memory merely to move them into a
    restart-safe ``task-work/{taskId}`` directory.  As with
    :func:`atomic_replace_bytes`, the target only becomes visible after the
    complete file is flushed and renamed.
    """

    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise StorageIntegrityError(f"无法复制不存在的文件: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temp_path = Path(raw_temp)
    _notify(stage_hook, "temp_created", temp_path)
    try:
        os.fchmod(descriptor, mode)
        with source.open("rb") as input_handle, os.fdopen(
            descriptor,
            "wb",
        ) as output_handle:
            descriptor = -1
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        _notify(stage_hook, "temp_fsynced", temp_path)
        os.replace(temp_path, target)
        _notify(stage_hook, "renamed", target)
        _fsync_directory(target.parent)
        _notify(stage_hook, "directory_fsynced", target.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)
        raise


def resolve_creator_data_root(
    root: str | os.PathLike[str] | None = None,
    *,
    provider: DataRootProvider | None = None,
) -> Path:
    """Return the single external Creator data root."""
    candidate: str | os.PathLike[str] | None = root
    if candidate is None and provider is not None:
        candidate = provider()
    if candidate is None:
        # Local import avoids a package-initialization cycle while keeping the
        # filesystem data-root resolver as the only default authority.
        from services.storage_root import require_creator_data_root

        candidate = require_creator_data_root()
    return Path(candidate).expanduser().resolve()


def validate_sha256(value: str) -> str:
    digest = (value or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValidationError(f"非法 SHA-256 digest: {value!r}")
    return digest


class ContentStore:
    """Immutable SHA-256 blob/artifact store on one filesystem."""

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        data_root_provider: DataRootProvider | None = None,
        stage_hook: WriteStageHook | None = None,
    ) -> None:
        self.root = resolve_creator_data_root(
            root,
            provider=data_root_provider,
        )
        self.stage_hook = stage_hook
        self.root.mkdir(parents=True, exist_ok=True)
        self._temp_root = self.root / ".tmp"
        self._temp_root.mkdir(parents=True, exist_ok=True)

    def _namespace_root(self, namespace: ContentNamespace) -> Path:
        try:
            directory = _NAMESPACE_DIR[namespace]
        except KeyError as exc:
            raise ValidationError(
                f"非法 content namespace: {namespace!r}",
            ) from exc
        return self.root / directory / "sha256"

    def path_for(
        self,
        digest: str,
        *,
        namespace: ContentNamespace = "blob",
    ) -> Path:
        normalized = validate_sha256(digest)
        return self._namespace_root(namespace) / normalized[:2] / normalized

    def put_bytes(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        namespace: ContentNamespace = "blob",
        expected_sha256: str | None = None,
    ) -> StoredContent:
        return self.put_stream(
            io.BytesIO(bytes(payload)),
            namespace=namespace,
            expected_sha256=expected_sha256,
        )

    def put_text(
        self,
        text: str,
        *,
        namespace: ContentNamespace = "blob",
        encoding: str = "utf-8",
        expected_sha256: str | None = None,
    ) -> StoredContent:
        return self.put_bytes(
            text.encode(encoding),
            namespace=namespace,
            expected_sha256=expected_sha256,
        )

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        namespace: ContentNamespace = "blob",
        expected_sha256: str | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> StoredContent:
        """Write, fsync, hash-verify, then atomically publish a stream."""
        if chunk_size <= 0:
            raise ValidationError("chunk_size 必须大于 0")
        expected = (
            validate_sha256(expected_sha256) if expected_sha256 else None
        )
        # Validate the namespace before doing any I/O.
        self._namespace_root(namespace)

        descriptor, raw_temp = tempfile.mkstemp(
            prefix="content-",
            suffix=".tmp",
            dir=self._temp_root,
        )
        temp_path = Path(raw_temp)
        _notify(self.stage_hook, "temp_created", temp_path)
        hasher = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise ValidationError("content stream 必须返回 bytes")
                    data = bytes(chunk)
                    handle.write(data)
                    hasher.update(data)
                    size += len(data)
                handle.flush()
                os.fsync(handle.fileno())
            _notify(self.stage_hook, "temp_fsynced", temp_path)

            digest = hasher.hexdigest()
            if expected is not None and digest != expected:
                raise StorageIntegrityError(
                    "content hash 不匹配",
                    details={"expected": expected, "actual": digest},
                )
            _notify(self.stage_hook, "hash_verified", temp_path)
            target = self.path_for(digest, namespace=namespace)
            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists():
                self._verify_file(target, digest, expected_size=size)
                temp_path.unlink(missing_ok=True)
                _notify(self.stage_hook, "deduplicated", target)
                return StoredContent(namespace, digest, size, target)

            os.replace(temp_path, target)
            _notify(self.stage_hook, "renamed", target)
            _fsync_directory(target.parent)
            # The source .tmp directory also changed during a cross-directory
            # rename and must be flushed before reporting the write durable.
            _fsync_directory(self._temp_root)
            _notify(self.stage_hook, "directory_fsynced", target.parent)
            return StoredContent(namespace, digest, size, target)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            temp_path.unlink(missing_ok=True)
            raise

    def _verify_file(
        self,
        path: Path,
        digest: str,
        *,
        expected_size: int | None = None,
    ) -> None:
        hasher = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
                    size += len(chunk)
        except OSError as exc:
            raise StorageIntegrityError(f"无法读取 content blob: {path}") from exc
        if hasher.hexdigest() != digest or (
            expected_size is not None and size != expected_size
        ):
            raise StorageIntegrityError(
                "content-addressed 文件损坏",
                details={
                    "path": str(path),
                    "expectedSha256": digest,
                    "actualSha256": hasher.hexdigest(),
                    "expectedSize": expected_size,
                    "actualSize": size,
                },
            )

    def verify(
        self,
        digest: str,
        *,
        namespace: ContentNamespace = "blob",
    ) -> bool:
        normalized = validate_sha256(digest)
        path = self.path_for(normalized, namespace=namespace)
        if not path.is_file():
            return False
        self._verify_file(path, normalized)
        return True

    def exists(
        self,
        digest: str,
        *,
        namespace: ContentNamespace = "blob",
    ) -> bool:
        return self.path_for(digest, namespace=namespace).is_file()

    def read_bytes(
        self,
        digest: str,
        *,
        namespace: ContentNamespace = "blob",
        verify: bool = True,
    ) -> bytes:
        normalized = validate_sha256(digest)
        path = self.path_for(normalized, namespace=namespace)
        if not path.is_file():
            raise StorageIntegrityError(
                "content blob 不存在",
                details={"sha256": normalized, "namespace": namespace},
            )
        if verify:
            self._verify_file(path, normalized)
        return path.read_bytes()

    def read_text(
        self,
        digest: str,
        *,
        namespace: ContentNamespace = "blob",
        encoding: str = "utf-8",
    ) -> str:
        try:
            return self.read_bytes(digest, namespace=namespace).decode(
                encoding,
            )
        except UnicodeDecodeError as exc:
            raise StorageIntegrityError(
                "content blob 不是合法文本",
                details={"sha256": digest, "encoding": encoding},
            ) from exc

    def iter_digests(
        self,
        *,
        namespace: ContentNamespace = "blob",
    ) -> Iterator[str]:
        root = self._namespace_root(namespace)
        if not root.exists():
            return
        for prefix in sorted(root.iterdir()):
            if not prefix.is_dir():
                continue
            for path in sorted(prefix.iterdir()):
                if path.is_file() and _SHA256_RE.fullmatch(path.name):
                    yield path.name
