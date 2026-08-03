# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Persistent local JPEG previews for immutable source-video versions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
from threading import Lock
from uuid import uuid4

from domain.errors import StorageIntegrityError, ValidationError
from services.project_files.assets import AssetFileStore
from services.project_files.models import IndexedFile


@dataclass(frozen=True, slots=True)
class CachedKeyframe:
    path: Path
    sha256: str
    size_bytes: int
    timestamp_seconds: float
    width: int


_LOCKS_GUARD = Lock()
_KEYFRAME_LOCKS: dict[str, Lock] = {}
_INDEXED_PATHS_GUARD = Lock()
_VERIFIED_INDEXED_PATHS: dict[
    tuple[str, str, int, str],
    tuple[Path, int, int, int],
] = {}


def _lock_for(key: str) -> Lock:
    with _LOCKS_GUARD:
        return _KEYFRAME_LOCKS.setdefault(key, Lock())


def _require_real_directory(path: Path, *, parent: Path, label: str) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    try:
        value = path.lstat()
    except OSError as error:
        raise StorageIntegrityError(f"{label} 不可用: {path}") from error
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise StorageIntegrityError(f"{label} 必须是安全的真实目录")
    try:
        path.resolve(strict=True).relative_to(parent.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise StorageIntegrityError(f"{label} 逃逸预期目录") from error


def _regular_file_stat(path: Path, *, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except FileNotFoundError as error:
        raise StorageIntegrityError(f"{label} 不存在: {path}") from error
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        raise StorageIntegrityError(f"{label} 必须是安全的普通文件")
    return value


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verified_indexed_path(project_root: Path, indexed: IndexedFile) -> Path:
    """Verify an immutable IndexedFile once per unchanged inode fingerprint."""

    key = (
        str(project_root),
        indexed.relative_uri,
        indexed.size_bytes,
        indexed.sha256,
    )
    target = project_root.joinpath(*PurePosixPath(indexed.relative_uri).parts)
    with _INDEXED_PATHS_GUARD:
        value = _regular_file_stat(target, label="IndexedFile")
        cached = _VERIFIED_INDEXED_PATHS.get(key)
        if cached is not None:
            path, device, inode, modified_ns = cached
            if (
                path == target
                and value.st_dev == device
                and value.st_ino == inode
                and value.st_mtime_ns == modified_ns
                and value.st_size == indexed.size_bytes
            ):
                return target

        try:
            with AssetFileStore(project_root).open_verified(indexed):
                pass
        except Exception as error:
            raise StorageIntegrityError(str(error)) from error
        value = _regular_file_stat(target, label="IndexedFile")
        _VERIFIED_INDEXED_PATHS[key] = (
            target,
            value.st_dev,
            value.st_ino,
            value.st_mtime_ns,
        )
        return target


def _cached_entry(
    target: Path,
    *,
    timestamp_seconds: float,
    width: int,
) -> CachedKeyframe | None:
    try:
        value = target.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        raise StorageIntegrityError("关键帧缓存目标不是安全的普通文件")
    if value.st_size <= 0:
        raise StorageIntegrityError("关键帧缓存为空")
    return CachedKeyframe(
        path=target,
        sha256=_hash_file(target),
        size_bytes=value.st_size,
        timestamp_seconds=timestamp_seconds,
        width=width,
    )


def materialize_keyframe(
    project_root: Path,
    *,
    source_path: Path,
    source_identity: str,
    timestamp_seconds: float,
    width: int,
    ffmpeg_path: str,
) -> CachedKeyframe:
    """Extract one frame from a local source and atomically persist its JPEG."""

    timestamp = round(float(timestamp_seconds), 3)
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValidationError("关键帧时间码必须是非负有限数值")
    if not 160 <= width <= 1920:
        raise ValidationError("关键帧宽度必须位于 160 到 1920 之间")
    if not ffmpeg_path:
        raise ValidationError("ffmpeg 尚未就绪，无法生成关键帧")
    _regular_file_stat(source_path, label="关键帧源视频")

    runtime_root = project_root / "runtime"
    _require_real_directory(
        runtime_root,
        parent=project_root,
        label="Runtime 目录",
    )
    cache_root = runtime_root / "keyframe-cache"
    _require_real_directory(cache_root, parent=runtime_root, label="关键帧缓存目录")
    cache_key = sha256(
        f"v1\0{source_identity}\0{timestamp:.3f}\0{width}".encode("utf-8"),
    ).hexdigest()
    target = cache_root / f"{cache_key}.jpg"

    with _lock_for(cache_key):
        cached = _cached_entry(
            target,
            timestamp_seconds=timestamp,
            width=width,
        )
        if cached is not None:
            return cached

        temporary = cache_root / f".{cache_key}.{uuid4().hex}.jpg.part"
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-q:v",
            "3",
            "-f",
            "image2",
            "-update",
            "1",
            str(temporary),
        ]
        try:
            result = subprocess.run(
                command,
                # Detach stdin so ffmpeg is not suspended by SIGTTIN when it
                # reads the tty from a background process group.
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            temporary.unlink(missing_ok=True)
            raise StorageIntegrityError("关键帧抽取超时") from error
        if result.returncode != 0:
            temporary.unlink(missing_ok=True)
            detail = (
                result.stderr or result.stdout or "ffmpeg failed"
            ).strip()
            raise StorageIntegrityError(f"关键帧抽取失败: {detail[-500:]}")
        value = _regular_file_stat(temporary, label="新生成关键帧")
        if value.st_size <= 0:
            temporary.unlink(missing_ok=True)
            raise StorageIntegrityError("新生成关键帧为空")
        os.chmod(temporary, 0o600)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
        directory_descriptor = os.open(cache_root, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        cached = _cached_entry(
            target,
            timestamp_seconds=timestamp,
            width=width,
        )
        if (
            cached is None
        ):  # pragma: no cover - os.replace published the target
            raise StorageIntegrityError("关键帧缓存发布失败")
        return cached


__all__ = [
    "CachedKeyframe",
    "materialize_keyframe",
    "verified_indexed_path",
]
