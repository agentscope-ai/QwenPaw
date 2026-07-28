# -*- coding: utf-8 -*-
# pylint: disable=raise-missing-from
"""Operational cache helpers for URL-backed SourceAssetVersions.

The public URL is the immutable Project source identity. Downloaded bytes are
only a Runtime cache: they must not create a second AssetVersion or advance the
Project generation when they arrive.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
import mimetypes
import os
from pathlib import Path, PurePosixPath
import stat
from urllib.parse import urlsplit

from domain.enums import TaskKind, TaskStatus
from domain.errors import StorageIntegrityError
from services.runtime_files.execution_models import TaskRecord

from .assets import StagedAsset
from .models import SourceAssetVersion


@dataclass(frozen=True, slots=True)
class RemoteCacheEntry:
    path: Path
    relative_uri: str
    sha256: str
    size_bytes: int
    media_type: str


def public_source_url(version: SourceAssetVersion) -> str | None:
    value = str(version.metadata.get("publicSourceUrl") or "").strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme in {"http", "https", "oss"}
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
    ):
        return value
    return None


def remote_source_name(url: str, requested_name: str) -> str:
    requested = requested_name.strip()
    path_name = Path(urlsplit(url).path).name
    if not requested or requested == url or not Path(requested).suffix:
        return path_name or requested or "remote-asset.bin"
    return Path(requested).name


def remote_source_media_type(url: str, name: str) -> str:
    path_name = Path(urlsplit(url).path).name
    return (
        mimetypes.guess_type(name)[0]
        or mimetypes.guess_type(path_name)[0]
        or "application/octet-stream"
    )


def remote_cache_relative_uri(version: SourceAssetVersion) -> str:
    suffix = Path(version.name).suffix[:20].casefold()
    if not suffix or not suffix.replace(".", "").isalnum():
        suffix = (
            mimetypes.guess_extension(version.media_type.split(";", 1)[0])
            or ".bin"
        )
    return PurePosixPath(
        "runtime",
        "asset-cache",
        f"{version.version_id}{suffix}",
    ).as_posix()


def _ensure_real_directory(path: Path) -> None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        value = path.lstat()
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise StorageIntegrityError(f"Runtime cache path is unsafe: {path}")


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def publish_remote_cache(
    project_root: Path,
    version: SourceAssetVersion,
    staged: StagedAsset,
    *,
    media_type: str,
) -> RemoteCacheEntry:
    runtime_root = project_root / "runtime"
    _ensure_real_directory(runtime_root)
    cache_root = runtime_root / "asset-cache"
    _ensure_real_directory(cache_root)
    relative_uri = remote_cache_relative_uri(version)
    target = project_root.joinpath(*PurePosixPath(relative_uri).parts)
    if target.parent != cache_root:
        raise StorageIntegrityError("Runtime cache path escaped its namespace")

    try:
        value = target.lstat()
    except FileNotFoundError:
        os.chmod(staged.path, 0o600)
        os.replace(staged.path, target)
        descriptor = os.open(cache_root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise StorageIntegrityError(
                "Runtime cache target is not a regular file",
            )
        if (
            value.st_size != staged.size_bytes
            or _hash_file(target) != staged.sha256
        ):
            raise StorageIntegrityError(
                "Runtime cache target has different content",
            )

    return RemoteCacheEntry(
        path=target,
        relative_uri=relative_uri,
        sha256=staged.sha256,
        size_bytes=staged.size_bytes,
        media_type=media_type,
    )


def resolve_remote_cache(
    project_root: Path,
    version: SourceAssetVersion,
    tasks: Sequence[TaskRecord],
) -> RemoteCacheEntry | None:
    expected_uri = remote_cache_relative_uri(version)
    for task in tasks:
        if (
            task.kind is not TaskKind.ASSET_INGEST
            or task.status is not TaskStatus.SUCCEEDED
            or task.metadata.get("assetVersionId") != version.version_id
        ):
            continue
        items = list((task.result or {}).get("items") or [])
        item = next(
            (
                value
                for value in items
                if isinstance(value, dict)
                and value.get("assetVersionId") == version.version_id
            ),
            None,
        )
        if item is None or item.get("cacheRelativeUri") != expected_uri:
            continue
        try:
            size_bytes = int(item["cacheSizeBytes"])
            checksum = str(item["cacheChecksum"])
            media_type = str(item.get("mediaType") or version.media_type)
        except (KeyError, TypeError, ValueError):
            raise StorageIntegrityError(
                "Remote Asset cache result is malformed",
            )
        target = project_root.joinpath(*PurePosixPath(expected_uri).parts)
        try:
            value = target.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise StorageIntegrityError(
                "Remote Asset cache is not a regular file",
            )
        if value.st_size != size_bytes:
            raise StorageIntegrityError(
                "Remote Asset cache size does not match Runtime task",
            )
        return RemoteCacheEntry(
            path=target,
            relative_uri=expected_uri,
            sha256=checksum,
            size_bytes=size_bytes,
            media_type=media_type,
        )
    return None


__all__ = [
    "RemoteCacheEntry",
    "public_source_url",
    "publish_remote_cache",
    "remote_cache_relative_uri",
    "remote_source_media_type",
    "remote_source_name",
    "resolve_remote_cache",
]
