# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Read-only media delivery from Project Asset indexes and file namespaces."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from services.media_files.ffmpeg import ffmpeg_readiness
from services.media_files.keyframe_cache import (
    materialize_keyframe,
    verified_indexed_path,
)
from services.project_files.assets import AssetFileError, AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import IndexedFile
from services.project_files.remote_cache import resolve_remote_cache
from services.project_files.store import ProjectNotFound
from services.runtime_files.execution_store import ProjectExecutionStore
from utils.paths import media_path_from_url

from .content_disposition import inline_content_disposition
from .dependencies import CreatorErrorRoute, project_file_services


router = APIRouter(tags=["media-files"], route_class=CreatorErrorRoute)


_STREAM_CHUNK_BYTES = 64 * 1024

# Verified-on-hit version -> project map; avoids scanning every Project for
# each media request. Uniqueness is still enforced on cache misses.
_VERSION_PROJECT_CACHE: dict[tuple[str, str], str] = {}
_VERSION_PROJECT_CACHE_MAX = 4096


def _response_range(
    range_header: str | None,
    size_bytes: int,
) -> tuple[int, int, int, str | None]:
    """Return ``(start, length, status, content_range)`` for one byte range."""

    if not range_header:
        return 0, size_bytes, 200, None
    value = range_header.strip()
    if not value.startswith("bytes=") or "," in value or size_bytes <= 0:
        raise ValueError("invalid byte range")
    bounds = value.removeprefix("bytes=").strip()
    start_text, separator, end_text = bounds.partition("-")
    if not separator:
        raise ValueError("invalid byte range")
    if not start_text:
        try:
            suffix_length = int(end_text)
        except ValueError as error:
            raise ValueError("invalid byte range") from error
        if suffix_length <= 0:
            raise ValueError("invalid byte range")
        start = max(0, size_bytes - suffix_length)
        end = size_bytes - 1
    else:
        try:
            start = int(start_text)
            end = int(end_text) if end_text else size_bytes - 1
        except ValueError as error:
            raise ValueError("invalid byte range") from error
        if start < 0 or start >= size_bytes or end < start:
            raise ValueError("invalid byte range")
        end = min(end, size_bytes - 1)
    length = end - start + 1
    return start, length, 206, f"bytes {start}-{end}/{size_bytes}"


def _stream_range(stream: Any, *, start: int, length: int) -> Iterator[bytes]:
    """Yield exactly one verified file range and always close its descriptor."""

    try:
        stream.seek(start)
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(_STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        stream.close()


def _range_not_satisfiable(size_bytes: int) -> Response:
    return Response(
        status_code=416,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes */{size_bytes}",
        },
    )


def _media_response(
    request: Request,
    *,
    stream_factory: Any,
    size_bytes: int,
    media_type: str,
    name: str,
    etag: str,
    cache_control: str,
) -> Response:
    try:
        start, length, status_code, content_range = _response_range(
            request.headers.get("range"),
            size_bytes,
        )
    except ValueError:
        return _range_not_satisfiable(size_bytes)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": inline_content_disposition(name, media_type),
        "ETag": etag,
        "Cache-Control": cache_control,
    }
    if content_range is not None:
        headers["Content-Range"] = content_range
    if request.method == "HEAD":
        return Response(
            status_code=status_code,
            media_type=media_type,
            headers=headers,
        )
    stream = stream_factory()
    return StreamingResponse(
        _stream_range(stream, start=start, length=length),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


async def _indexed_version(
    services: CreatorFileServices,
    *,
    version_id: str,
    kind: Literal["source", "artifact"],
) -> tuple[Path, IndexedFile | None, Any, str]:
    cached_project = _VERSION_PROJECT_CACHE.get((kind, version_id))
    if cached_project is not None:
        match = await asyncio.to_thread(
            _version_in_project,
            services,
            project_id=cached_project,
            version_id=version_id,
            kind=kind,
        )
        if match is not None:
            return match
        _VERSION_PROJECT_CACHE.pop((kind, version_id), None)
    matches: list[tuple[Path, IndexedFile | None, Any, str]] = []
    summaries = await asyncio.to_thread(services.projects.list)
    for summary in summaries:
        match = await asyncio.to_thread(
            _version_in_project,
            services,
            project_id=summary.project_id,
            version_id=version_id,
            kind=kind,
        )
        if match is not None:
            matches.append(match)
    if not matches:
        raise NotFoundError(
            "AssetVersion 不存在" if kind == "source" else "ArtifactVersion 不存在",
        )
    if len(matches) != 1:
        raise StorageIntegrityError("跨 Project 的 Version ID 不唯一")
    if len(_VERSION_PROJECT_CACHE) >= _VERSION_PROJECT_CACHE_MAX:
        _VERSION_PROJECT_CACHE.clear()
    _VERSION_PROJECT_CACHE[(kind, version_id)] = matches[0][3]
    return matches[0]


def _version_in_project(
    services: CreatorFileServices,
    *,
    project_id: str,
    version_id: str,
    kind: Literal["source", "artifact"],
) -> tuple[Path, IndexedFile | None, Any, str] | None:
    # Only a genuinely missing Project means "no match here"; integrity,
    # permission and I/O failures must propagate instead of becoming 404.
    try:
        snapshot = services.projects.read(project_id)
    except ProjectNotFound:
        return None
    if kind == "source":
        version: Any = snapshot.project.assets.source_versions_by_id.get(
            version_id,
        )
    else:
        version = snapshot.project.assets.artifact_versions_by_id.get(
            version_id,
        )
    if version is None:
        return None
    indexed = (
        snapshot.project.assets.files_by_id.get(version.file_id)
        if version.file_id is not None
        else None
    )
    if indexed is None and not (kind == "source" and version.file_id is None):
        raise StorageIntegrityError("AssetVersion 引用的 IndexedFile 不存在")
    return (
        services.projects.project_root(project_id),
        indexed,
        version,
        project_id,
    )


async def _indexed_response(
    services: CreatorFileServices,
    *,
    request: Request,
    version_id: str,
    kind: Literal["source", "artifact"],
) -> Response:
    project_root, indexed, version, project_id = await _indexed_version(
        services,
        version_id=version_id,
        kind=kind,
    )
    if indexed is None:
        cache = await asyncio.to_thread(
            resolve_remote_cache,
            project_root,
            version,
            ProjectExecutionStore(services.root).list_tasks(project_id),
        )
        if cache is None:
            raise NotFoundError("远程 Asset 本地缓存尚未完成")
        return _media_response(
            request,
            stream_factory=lambda: cache.path.open("rb"),
            size_bytes=cache.size_bytes,
            media_type=version.media_type,
            name=version.name,
            etag=f'"sha256:{cache.sha256}"',
            cache_control="public, max-age=31536000, immutable",
        )

    def open_verified():
        try:
            return AssetFileStore(project_root).open_verified(indexed)
        except AssetFileError as error:
            raise StorageIntegrityError(str(error)) from error

    return _media_response(
        request,
        stream_factory=open_verified,
        size_bytes=indexed.size_bytes,
        media_type=indexed.media_type,
        name=version.name,
        etag=f'"sha256:{indexed.sha256}"',
        cache_control="public, max-age=31536000, immutable",
    )


@router.get("/generated/{path:path}")
@router.head("/generated/{path:path}", include_in_schema=False)
async def generated_file(path: str) -> FileResponse:
    try:
        target = media_path_from_url(f"/generated/{path}")
    except ValueError as error:
        raise NotFoundError("生成资源不存在") from error
    if not target.is_file():
        raise NotFoundError("生成资源不存在")
    return FileResponse(target, content_disposition_type="inline")


@router.get("/media/assets/{version_id}")
@router.head("/media/assets/{version_id}", include_in_schema=False)
async def asset_media(
    version_id: str,
    request: Request,
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    return await _indexed_response(
        services,
        request=request,
        version_id=version_id,
        kind="source",
    )


async def _keyframe_response(
    services: CreatorFileServices,
    *,
    version_id: str,
    kind: Literal["source", "artifact"],
    timestamp: float,
    width: int,
) -> FileResponse:
    """Serve a persistent JPEG extracted only from the local media cache.

    Both route wrappers validate the bounds via ``Query``; direct callers
    must honour the same preconditions.
    """

    if not 0 <= timestamp <= 86_400:
        raise ValidationError("timestamp 必须在 0–86400 秒之间")
    if not 160 <= width <= 1920:
        raise ValidationError("width 必须在 160–1920 之间")

    project_root, indexed, version, project_id = await _indexed_version(
        services,
        version_id=version_id,
        kind=kind,
    )
    media_type = (
        indexed.media_type if indexed is not None else version.media_type
    )
    if not str(media_type).startswith("video/"):
        version_label = (
            "AssetVersion" if kind == "source" else "ArtifactVersion"
        )
        raise NotFoundError(
            f"{version_label} 不是可预览的视频（media_type={media_type}）",
        )
    if indexed is None:
        cache = await asyncio.to_thread(
            resolve_remote_cache,
            project_root,
            version,
            ProjectExecutionStore(services.root).list_tasks(project_id),
        )
        if cache is None:
            raise NotFoundError("远程 Asset 本地缓存尚未完成")
        source_path = cache.path
        source_identity = f"remote-cache:{cache.sha256}:{cache.size_bytes}"
    else:
        source_path = await asyncio.to_thread(
            verified_indexed_path,
            project_root,
            indexed,
        )
        source_identity = f"indexed:{indexed.sha256}:{indexed.size_bytes}"

    readiness = await asyncio.to_thread(ffmpeg_readiness)
    ffmpeg_path = readiness.get("path")
    if readiness.get("status") != "ok" or not ffmpeg_path:
        raise ConflictError("ffmpeg 尚未就绪，无法生成关键帧")
    frame = await asyncio.to_thread(
        materialize_keyframe,
        project_root,
        source_path=source_path,
        source_identity=source_identity,
        timestamp_seconds=timestamp,
        width=width,
        ffmpeg_path=str(ffmpeg_path),
    )
    return FileResponse(
        frame.path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"sha256:{frame.sha256}"',
            "X-Creator-Media-Source": "local-keyframe-cache",
        },
    )


@router.get("/media/assets/{version_id}/frame")
async def asset_keyframe(
    version_id: str,
    timestamp: float = Query(ge=0, le=86_400),
    width: int = Query(640, ge=160, le=1920),
    services: CreatorFileServices = Depends(project_file_services),
) -> FileResponse:
    return await _keyframe_response(
        services,
        version_id=version_id,
        kind="source",
        timestamp=timestamp,
        width=width,
    )


@router.get("/media/artifacts/{version_id}/frame")
async def artifact_keyframe(
    version_id: str,
    timestamp: float = Query(0.0, ge=0, le=86_400),
    width: int = Query(640, ge=160, le=1920),
    services: CreatorFileServices = Depends(project_file_services),
) -> FileResponse:
    """Still frame of a rendered video Artifact, used for project covers."""

    return await _keyframe_response(
        services,
        version_id=version_id,
        kind="artifact",
        timestamp=timestamp,
        width=width,
    )


@router.get("/media/artifacts/{version_id}")
@router.head("/media/artifacts/{version_id}", include_in_schema=False)
async def artifact_media(
    version_id: str,
    request: Request,
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    return await _indexed_response(
        services,
        request=request,
        version_id=version_id,
        kind="artifact",
    )


__all__ = ["router"]
