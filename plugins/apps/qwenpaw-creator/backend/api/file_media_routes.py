# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Read-only media delivery from Project Asset indexes and file namespaces."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
import re
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
from services.media_files.motion_engine import (
    referenced_vendor_filenames,
    resolve_vendor_files,
)
from services.media_files.motion_overlay import render_motion_poster
from services.project_files.assets import AssetFileError, AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import IndexedFile
from services.project_files.remote_cache import resolve_remote_cache
from services.project_files.store import (
    ProjectIntegrityError,
    ProjectNotFound,
    ProjectStoreError,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from utils.logger import setup_logger
from utils.paths import media_path_from_url

from .content_disposition import inline_content_disposition
from .dependencies import CreatorErrorRoute, project_file_services


logger = setup_logger("file_media_routes")

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
    # discover_project_ids (not list) so bundled example Projects, which are
    # hidden from the user's project shelf, still serve their media.
    summaries = await asyncio.to_thread(services.projects.discover_project_ids)
    for summary in summaries:
        match = await asyncio.to_thread(
            _version_in_project,
            services,
            project_id=summary,
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
    # A genuinely missing Project means "no match here". So does a Project
    # that cannot even be loaded (corrupt or unmigratable project.json):
    # it cannot serve the version anyway, and propagating its integrity
    # error would take media streaming down for every healthy project
    # (field run 2026-08-25: legacy corrupt projects 500'd all previews).
    # Integrity failures AFTER a match — broken files behind a matched
    # version — still propagate below instead of becoming 404.
    try:
        snapshot = services.projects.read(project_id)
    except ProjectNotFound:
        return None
    except ProjectIntegrityError as error:
        # Only corruption counts as "no match here": transient I/O or
        # permission failures must propagate, or a healthy project's real
        # fault would masquerade as a 404 and get cached as missing.
        logger.warning(
            "media scan: skipping unloadable project %s: %s",
            project_id,
            error,
        )
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


def _motion_document_in_project(
    services: CreatorFileServices,
    *,
    project_id: str,
    file_id: str,
) -> tuple[Path, IndexedFile] | None:
    try:
        snapshot = services.projects.read(project_id)
    except ProjectNotFound:
        return None
    except ProjectStoreError:
        # Discovery includes unvalidated directories; one corrupt Project must
        # not block the scan of the remaining healthy ones.
        return None
    indexed = snapshot.project.assets.files_by_id.get(file_id)
    if indexed is None or indexed.schema_name != "motion_document":
        return None
    return services.projects.project_root(project_id), indexed


@router.get("/media/motion-documents/{file_id}")
async def motion_document(
    file_id: str,
    request: Request,
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    """Serve one externalized motion document body.

    Content is delivered as plain text: the frontend injects it into a
    sandboxed iframe via srcDoc, and this route must never become a
    same-origin HTML navigation target.
    """

    matches: list[tuple[Path, IndexedFile]] = []
    # O(项目数) 扫描：本地单用户部署的项目数量有限，且命中后前端会长期
    # immutable 缓存；若项目规模增长，应改为全局 file_id → 项目的索引。
    # discover_project_ids (not list) so bundled example Projects, which are
    # hidden from the user's project shelf, still serve their media.
    project_ids = await asyncio.to_thread(
        services.projects.discover_project_ids,
    )
    for project_id in project_ids:
        match = await asyncio.to_thread(
            _motion_document_in_project,
            services,
            project_id=project_id,
            file_id=file_id,
        )
        if match is not None:
            matches.append(match)
    if not matches:
        raise NotFoundError("motion 文档不存在")
    # Content-addressed ids may legitimately appear in several Projects;
    # every copy carries identical bytes, so the first match serves.
    project_root, indexed = matches[0]

    def open_verified():
        try:
            return AssetFileStore(project_root).open_verified(indexed)
        except AssetFileError as error:
            raise StorageIntegrityError(str(error)) from error

    return _media_response(
        request,
        stream_factory=open_verified,
        size_bytes=indexed.size_bytes,
        media_type="text/plain; charset=utf-8",
        name=f"{file_id}.html",
        etag=f'"sha256:{indexed.sha256}"',
        cache_control="public, max-age=31536000, immutable",
    )


@router.get("/media/motion-documents/{file_id}/poster")
async def motion_document_poster(
    file_id: str,
    doc_format: Literal["html_css", "html_js"] = Query(
        "html_css",
        alias="format",
    ),
    width: int = Query(640, ge=16, le=1920),
    height: int = Query(360, ge=16, le=1080),
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    """Deterministic PNG poster frame of one externalized motion document.

    Backs the live preview of ``html_js`` documents: their scripts never
    execute in the frontend, so the sandboxed render engine produces one
    settled frame here instead.  Content-addressed and immutable.
    """

    matches: list[tuple[Path, IndexedFile]] = []
    # discover_project_ids (not list) so bundled example Projects, which are
    # hidden from the user's project shelf, still serve their media.
    project_ids = await asyncio.to_thread(
        services.projects.discover_project_ids,
    )
    for project_id in project_ids:
        match = await asyncio.to_thread(
            _motion_document_in_project,
            services,
            project_id=project_id,
            file_id=file_id,
        )
        if match is not None:
            matches.append(match)
    if not matches:
        raise NotFoundError("motion 文档不存在")
    project_root, indexed = matches[0]

    def read_verified() -> str:
        try:
            with AssetFileStore(project_root).open_verified(
                indexed,
            ) as stream:
                return stream.read().decode("utf-8")
        except AssetFileError as error:
            raise StorageIntegrityError(str(error)) from error

    html = await asyncio.to_thread(read_verified)
    # ffmpeg 的 YUV 子采样要求偶数尺寸；ETag 必须反映实际渲染尺寸，
    # 否则两个不同的奇数请求会产生同图不同 ETag 的缓存不一致。
    actual_width = width // 2 * 2
    actual_height = height // 2 * 2
    payload = await asyncio.to_thread(
        render_motion_poster,
        html,
        doc_format=doc_format,
        box_width=actual_width,
        box_height=actual_height,
    )
    if payload is None:
        raise NotFoundError("无法渲染动效海报帧")
    return Response(
        payload,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"poster:{indexed.sha256}:{actual_width}x{actual_height}"',
        },
    )


# Host->document bridge for the sandboxed live-preview iframe: the paused
# GSAP timeline never advances on its own, so the preview host drives it by
# posting seek messages the same way the render worker drives __hf.seek.
# targetOrigin is deliberately '*': the document runs in an opaque origin
# (sandbox without allow-same-origin), which no concrete origin string can
# match; the payload carries nothing but a type tag and a timestamp.
_PREVIEW_SEEK_BRIDGE = """
<script>
window.addEventListener('message', function (event) {
  var data = event.data || {};
  if (data.type !== 'qwenpaw-motion-seek') return;
  var seconds = Number(data.seconds) || 0;
  var proto = window.__hf;
  if (proto && typeof proto.seek === 'function') {
    try { proto.seek(seconds, { suppressEvents: true }); } catch (error) {}
  }
  var animations = document.getAnimations
    ? document.getAnimations({ subtree: true })
    : [];
  for (var i = 0; i < animations.length; i++) {
    try { animations[i].currentTime = seconds * 1000; } catch (error) {}
  }
});
try { parent.postMessage({ type: 'qwenpaw-motion-ready' }, '*'); } catch (error) {}
</script>
"""


@router.get("/media/motion-documents/{file_id}/preview")
async def motion_document_preview(
    file_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    """Self-contained playable copy of one html_js motion document.

    The hyperframes-style same-source preview: the very document the
    render worker captures also runs in the frontend, inside an iframe
    sandboxed to ``allow-scripts`` only (opaque origin, no host access).
    Vendored runtime references are inlined because the sandbox cannot
    resolve relative ``vendor/`` paths, and a postMessage seek bridge
    lets the host drive the paused timeline exactly like the renderer.
    """

    matches: list[tuple[Path, IndexedFile]] = []
    summaries = await asyncio.to_thread(services.projects.list)
    for summary in summaries:
        match = await asyncio.to_thread(
            _motion_document_in_project,
            services,
            project_id=summary.project_id,
            file_id=file_id,
        )
        if match is not None:
            matches.append(match)
    if not matches:
        raise NotFoundError("motion 文档不存在")
    project_root, indexed = matches[0]

    def build_preview() -> str:
        try:
            with AssetFileStore(project_root).open_verified(
                indexed,
            ) as stream:
                html = stream.read().decode("utf-8")
        except AssetFileError as error:
            raise StorageIntegrityError(str(error)) from error
        for filename, path in resolve_vendor_files(
            referenced_vendor_filenames(html),
        ).items():
            body = Path(path).read_text(encoding="utf-8")
            html = re.sub(
                rf"<script\s+src=[\"']vendor/{re.escape(filename)}[\"']\s*>\s*</script>",
                lambda _m, body=body: f"<script>{body}</script>",
                html,
                count=1,
            )
        # Fail closed on a leftover vendor reference: the sandboxed iframe
        # cannot resolve relative paths, so an uninlined runtime would boot
        # a silently dead document instead of a playable one.
        if re.search(r"<script\s+src=[\"']vendor/", html):
            raise StorageIntegrityError("动效文档的运行时引用未能内联，无法预览")
        if "</body>" in html:
            return html.replace("</body>", _PREVIEW_SEEK_BRIDGE + "</body>", 1)
        return html + _PREVIEW_SEEK_BRIDGE

    payload = await asyncio.to_thread(build_preview)
    return Response(
        payload,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"preview:{indexed.sha256}"',
            # The document runs in an opaque-origin sandbox; this CSP is a
            # second fence: inline script/style only, no network at all.
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; img-src data:; font-src data:"
            ),
        },
    )


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
