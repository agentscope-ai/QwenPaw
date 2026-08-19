# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=raise-missing-from,too-many-branches,too-many-statements
# pylint: disable=unused-argument
"""File-native immutable Asset ingest, index, import and content routes."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
import socket
import threading
from typing import Any, Callable, Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.datastructures import UploadFile

from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from domain.enums import TaskKind, TaskStatus
from schemas.assets import TextOrUrlAssetRequest
from schemas.common import StrictModel
from services.document_reader import is_supported_document
from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileError,
    AssetFileStore,
    StagedAsset,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    IndexedFile,
    ProjectSource,
    SourceAssetVersion,
)
from services.project_files.remote_cache import (
    public_source_url,
    publish_remote_cache,
    remote_source_media_type,
    remote_source_name,
    resolve_remote_cache,
)
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.errors import (
    IdempotencyConflictError,
    IdempotencyStateConflictError,
    RecordNotFoundError,
)
from services.runtime_files.execution_models import TaskRecord
from services.runtime_files.execution_store import (
    ExecutionPayloadConflict,
    ExecutionStateConflict,
    ExecutionStoreError,
    ProjectExecutionStore,
)
from services.runtime_files.idempotency_store import IdempotencyRecordStore
from services.runtime_files.models import (
    ChangeOrigin,
    IdempotencyStatus,
    ReviewPolicy,
)
from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
    open_safe_remote_stream,
    validate_public_remote_url,
    validate_response_peer,
)
from services.runtime_files.session_store import (
    ProjectRuntimeSessionStore,
    RuntimeSessionNotFound,
)

from .content_disposition import inline_content_disposition
from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
)

logger = logging.getLogger("qwenpaw.creator.api.file_asset_routes")


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["asset-files"],
    route_class=CreatorErrorRoute,
)

_DEFAULT_MAX_REMOTE_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_REMOTE_ASSET_TIMEOUT_SECONDS = 60 * 60
_MAX_LOCAL_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024
_DEFAULT_MAX_LOCAL_UPLOAD_BYTES = 100 * 1024 * 1024
_DEFAULT_IMPORT_MAX_FILES = 200
_DEFAULT_IMPORT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
_REMOTE_INGEST_TASKS: dict[tuple[str, str], asyncio.Task[None]] = {}
_REMOTE_INGEST_SHUTTING_DOWN = False


class AssetImportItemRecord(StrictModel):
    name: str
    asset_version_id: str = Field(alias="assetVersionId")
    checksum: str


class AssetImportRecord(StrictModel):
    import_id: str = Field(alias="importId")
    task_id: str = Field(alias="taskId")
    project_id: str = Field(alias="projectId")
    status: Literal["SUCCEEDED", "FAILED"]
    progress: float = Field(ge=0, le=1)
    items: list[AssetImportItemRecord] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: datetime = Field(alias="createdAt")


class _AssetInput(StrictModel):
    name: str
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class _StagedAssetInput:
    name: str
    staged: StagedAsset
    media_type: str


@dataclass(frozen=True, slots=True)
class _RemoteAssetDownload:
    name: str
    staged: StagedAsset
    media_type: str


class _BoundedRawReader:
    """Expose an HTTP byte iterator as a bounded file-like stream."""

    def __init__(
        self,
        chunks: Any,
        *,
        max_bytes: int,
        total_bytes: int | None = None,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> None:
        self._chunks = iter(chunks)
        self._max_bytes = max_bytes
        self._size_bytes = 0
        self._total_bytes = total_bytes
        self._on_progress = on_progress

    def read(self, _size: int = -1) -> bytes:
        # ``response.iter_raw()`` yields transport-sized chunks (commonly
        # 16-64 KiB). Coalesce them up to the caller's requested size so the
        # progress callback, the staging write, and the sha256 update fire once
        # per caller chunk (1 MiB from AssetFileStore) rather than once per
        # transport chunk. For a 1 GiB asset that is ~1e3 callbacks instead of
        # ~1e5 — each callback currently triggers a locked ``task.json`` read,
        # so this alone removes ~64x of that overhead.
        target = _size if _size and _size > 0 else self._max_bytes
        parts: list[bytes] = []
        gathered = 0
        while gathered < target:
            try:
                chunk = next(self._chunks)
            except StopIteration:
                break
            if not chunk:
                continue
            self._size_bytes += len(chunk)
            if self._size_bytes > self._max_bytes:
                raise ValidationError(
                    f"远程 Asset 超过 {_format_byte_limit(self._max_bytes)} 限制",
                )
            parts.append(chunk)
            gathered += len(chunk)
        if not parts:
            return b""
        if self._on_progress is not None:
            self._on_progress(self._size_bytes, self._total_bytes)
        return b"".join(parts) if len(parts) != 1 else parts[0]


def _stable_id(
    prefix: str,
    project_id: str,
    key: str,
    suffix: str = "",
) -> str:
    value = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:file:{prefix}:{project_id}:{key}:{suffix}",
    ).hex
    return f"{prefix}-{value}"


def _format_byte_limit(size_bytes: int) -> str:
    gibibyte = 1024 * 1024 * 1024
    mebibyte = 1024 * 1024
    if size_bytes % gibibyte == 0:
        return f"{size_bytes // gibibyte} GiB"
    if size_bytes % mebibyte == 0:
        return f"{size_bytes // mebibyte} MiB"
    return f"{size_bytes} bytes"


def _remote_asset_max_bytes() -> int:
    variable = "CREATOR_REMOTE_ASSET_MAX_BYTES"
    raw = os.environ.get(variable)
    if raw is None:
        variable = "CREATOR_DOWNLOAD_MAX_BYTES"
        raw = os.environ.get(variable)
    if raw is None:
        return _DEFAULT_MAX_REMOTE_ASSET_BYTES
    try:
        value = int(raw)
    except ValueError as error:
        raise ValidationError(f"{variable} 必须是正整数") from error
    if value <= 0:
        raise ValidationError(f"{variable} 必须是正整数")
    return value


def _validate_local_video_upload(
    *,
    name: str,
    media_type: str,
    size_bytes: int | None,
) -> None:
    guessed_type = mimetypes.guess_type(name)[0] or ""
    is_video = media_type.casefold().startswith(
        "video/",
    ) or guessed_type.casefold().startswith("video/")
    if (
        is_video
        and size_bytes is not None
        and size_bytes > _MAX_LOCAL_VIDEO_UPLOAD_BYTES
    ):
        raise ValidationError("本地视频超过 100 MiB 上传限制")


def _positive_int_env(variable: str, default: int) -> int:
    raw = os.environ.get(variable)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValidationError(f"{variable} 必须是正整数") from error
    if value <= 0:
        raise ValidationError(f"{variable} 必须是正整数")
    return value


def _local_upload_max_bytes(*, name: str, media_type: str) -> int:
    guessed_type = mimetypes.guess_type(name)[0] or ""
    is_video = media_type.casefold().startswith(
        "video/",
    ) or guessed_type.casefold().startswith("video/")
    if is_video:
        return _MAX_LOCAL_VIDEO_UPLOAD_BYTES
    return _positive_int_env(
        "CREATOR_UPLOAD_MAX_BYTES",
        _DEFAULT_MAX_LOCAL_UPLOAD_BYTES,
    )


class _BoundedUploadReader:
    """Bounded sync reader over an UploadFile's spooled file object."""

    def __init__(self, source: Any, *, max_bytes: int, name: str) -> None:
        self._source = source
        self._max_bytes = max_bytes
        self._name = name
        self._read_bytes = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(
            size if size and size > 0 else _UPLOAD_READ_CHUNK_BYTES,
        )
        if chunk:
            self._read_bytes += len(chunk)
            if self._read_bytes > self._max_bytes:
                raise ValidationError(
                    f"文件「{self._name}」超过 "
                    f"{_format_byte_limit(self._max_bytes)} 上传限制",
                )
        return chunk


async def _upload_file_store(
    services: CreatorFileServices,
    project_id: str,
) -> AssetFileStore:
    # read() maps a missing Project to 404 before staging touches disk.
    await asyncio.to_thread(services.projects.read, project_id)
    return await asyncio.to_thread(
        AssetFileStore,
        services.projects.project_root(project_id),
    )


async def _stage_upload(
    upload: UploadFile,
    *,
    name: str,
    media_type: str,
    file_store: AssetFileStore,
    staging_id: str,
) -> _StagedAssetInput:
    """Stream one upload into Project staging without materializing bytes."""

    max_bytes = _local_upload_max_bytes(name=name, media_type=media_type)
    if upload.size is not None and upload.size > max_bytes:
        raise ValidationError(
            f"文件「{name}」超过 {_format_byte_limit(max_bytes)} 上传限制",
        )
    await upload.seek(0)
    reader = _BoundedUploadReader(
        upload.file,
        max_bytes=max_bytes,
        name=name,
    )
    staged = await asyncio.to_thread(
        file_store.stage_stream,
        reader,
        staging_id=staging_id,
    )
    return _StagedAssetInput(name=name, staged=staged, media_type=media_type)


async def _abandon_staged_uploads(
    file_store: AssetFileStore | None,
    items: list[_StagedAssetInput],
) -> None:
    """Best-effort cleanup; published handles are already renamed away."""

    if file_store is None:
        return
    for item in items:
        try:
            await asyncio.to_thread(file_store.abandon, item.staged)
        except Exception:  # noqa: BLE001
            pass


def _asset_checksum(item: _AssetInput | _StagedAssetInput) -> str:
    if isinstance(item, _StagedAssetInput):
        return item.staged.sha256
    return sha256(item.content).hexdigest()


def _asset_size_bytes(item: _AssetInput | _StagedAssetInput) -> int:
    if isinstance(item, _StagedAssetInput):
        return item.staged.size_bytes
    return len(item.content)


_AV_MIME_PREFIXES = (
    ("image/", "image"),
    ("video/", "video"),
    ("audio/", "audio"),
)
_DOCUMENT_MIME_MARKERS = (
    "document",
    "presentation",
    "spreadsheet",
    "powerpoint",
    "ms-excel",
)


def _media_kind(media_type: str, name: str = "") -> str:
    normalized = media_type.casefold()
    # SVG is a renderable document (vendored resvg renderer), not a raster
    # image: the image/* prefix would lock it out of read_document.
    if normalized == "image/svg+xml" or name.casefold().endswith(".svg"):
        return "document"
    for prefix, kind in _AV_MIME_PREFIXES:
        if normalized.startswith(prefix):
            return kind
    # Extension carries the format for documents: CSV/subtitles/plain text
    # arrive as text/*, and legacy Office MIME types would otherwise fall
    # into "other", locking them out of the read_document flow.
    if name and is_supported_document(name):
        return "document"
    if normalized in {"application/pdf", "application/msword"} or any(
        marker in normalized for marker in _DOCUMENT_MIME_MARKERS
    ):
        return "document"
    if normalized.startswith("text/"):
        return "text"
    return "other"


def _assert_supported_source_upload(name: str, media_type: str) -> None:
    """Source uploads must be analyzable creative material, not opaque blobs."""
    if _media_kind(media_type, name) != "other":
        return
    raise ValidationError(
        f"不支持的来源素材格式: {name}（{media_type}）。"
        "支持图片、视频、音频，以及 PDF/Office/表格/字幕/纯文本等可读文档。",
    )


def _extension(name: str, media_type: str) -> str:
    suffix = Path(name).suffix[:20]
    if suffix and suffix.replace(".", "").isalnum():
        return suffix.casefold()
    guessed = mimetypes.guess_extension(media_type.split(";", 1)[0].strip())
    return guessed or ".bin"


def _records_root(services: CreatorFileServices, project_id: str) -> Path:
    return (
        services.projects.project_root(project_id)
        / "runtime"
        / "idempotency"
        / "asset-http"
    )


def _ensure_existing_file(
    file_store: AssetFileStore,
    indexed: IndexedFile,
) -> None:
    inspection = file_store.inspect(indexed)
    if not inspection.available:
        raise StorageIntegrityError(
            f"已存在的 Asset 路径与请求内容不一致: {indexed.relative_uri}",
        )


def _ingest_many_sync(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    inputs: list[_AssetInput | _StagedAssetInput],
    attach_source: bool,
    scope: str,
) -> tuple[dict[str, Any], bool]:
    # The lifecycle lock is acquired before the per-Project idempotency path
    # can be created. A concurrent DELETE therefore cannot be followed by a
    # late upload recreating a phantom Project directory.
    with services.projects.lifecycle_lock(project_id):
        services.projects.read(project_id)
        return _ingest_many_locked(
            services,
            project_id=project_id,
            key=key,
            inputs=inputs,
            attach_source=attach_source,
            scope=scope,
        )


def _ingest_many_locked(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    inputs: list[_AssetInput | _StagedAssetInput],
    attach_source: bool,
    scope: str,
) -> tuple[dict[str, Any], bool]:
    if not inputs:
        raise ValidationError("至少需要一个 Asset")
    records = IdempotencyRecordStore(_records_root(services, project_id))
    request_payload = {
        "projectId": project_id,
        "attachSource": attach_source,
        "items": [
            {
                "name": item.name,
                "mediaType": item.media_type,
                "sha256": _asset_checksum(item),
                "size": _asset_size_bytes(item),
            }
            for item in inputs
        ],
    }
    request_hash = records.request_hash(request_payload)
    operation_id = records.operation_id(
        namespace="asset",
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
    )
    with records.operation_lock(
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
    ):
        reservation = records.reserve(
            owner_id=project_id,
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
            record_id=operation_id,
        )
        if reservation.record.status is IdempotencyStatus.COMPLETED:
            if not isinstance(reservation.record.response, dict):
                raise StorageIntegrityError("Asset idempotency response 损坏")
            return reservation.record.response, True
        if reservation.record.status is IdempotencyStatus.FAILED:
            raise StorageIntegrityError(
                "上一次 Asset 写入失败，请使用新的 Idempotency-Key 重试",
            )

        # The public helper owns the Project lifecycle lock for this complete
        # idempotency/file/index publication boundary.
        with nullcontext():
            base = services.projects.read(project_id)
            candidate = base.project.model_dump(mode="json")
            files = candidate["assets"]["files_by_id"]
            versions = candidate["assets"]["source_versions_by_id"]
            source_items = candidate["sources"]["sources"]["items"]
            source_order = candidate["sources"]["sources"]["order"]
            file_store = AssetFileStore(
                services.projects.project_root(project_id),
            )
            output_items: list[dict[str, str]] = []
            created_at = datetime.now(UTC)
            for index, item in enumerate(inputs):
                suffix = str(index)
                logical_asset_id = _stable_id("asset", project_id, key, suffix)
                version_id = _stable_id(
                    "asset-version",
                    project_id,
                    key,
                    suffix,
                )
                file_id = _stable_id("file", project_id, key, suffix)
                source_id = _stable_id("source", project_id, key, suffix)
                checksum = _asset_checksum(item)
                size_bytes = _asset_size_bytes(item)
                relative_uri = PurePosixPath(
                    "assets",
                    "sources",
                    f"{file_id}{_extension(item.name, item.media_type)}",
                ).as_posix()
                indexed = IndexedFile(
                    file_id=file_id,
                    kind="source_original",
                    relative_uri=relative_uri,
                    sha256=checksum,
                    size_bytes=size_bytes,
                    media_type=item.media_type,
                    created_at=created_at,
                )
                version = SourceAssetVersion(
                    version_id=version_id,
                    logical_asset_id=logical_asset_id,
                    name=item.name,
                    file_id=file_id,
                    checksum=checksum,
                    media_kind=_media_kind(item.media_type, item.name),
                    media_type=item.media_type,
                    created_at=created_at,
                    metadata={"clientRequestId": key},
                )
                existing_file = files.get(file_id)
                existing_version = versions.get(version_id)
                if existing_file is not None or existing_version is not None:
                    if existing_file != indexed.model_dump(
                        mode="json",
                    ) or existing_version != version.model_dump(mode="json"):
                        raise ConflictError("Asset 稳定 ID 已存在但内容不同")
                    _ensure_existing_file(file_store, indexed)
                else:
                    staged = (
                        item.staged
                        if isinstance(item, _StagedAssetInput)
                        else file_store.stage_bytes(
                            item.content,
                            staging_id=operation_id[:80],
                        )
                    )
                    try:
                        file_store.publish(
                            staged,
                            relative_uri,
                            expected_sha256=checksum,
                            expected_size_bytes=size_bytes,
                        )
                    except AssetAlreadyExists:
                        file_store.abandon(staged)
                        _ensure_existing_file(file_store, indexed)
                    files[file_id] = indexed.model_dump(mode="json")
                    versions[version_id] = version.model_dump(mode="json")
                if attach_source and source_id not in source_items:
                    source = ProjectSource(
                        source_id=source_id,
                        display_name=item.name,
                        logical_asset_id=logical_asset_id,
                        selected_asset_version_id=version_id,
                    )
                    source_items[source_id] = source.model_dump(mode="json")
                    source_order.append(source_id)
                output_items.append(
                    {
                        "name": item.name,
                        "assetId": logical_asset_id,
                        "assetVersionId": version_id,
                        "checksum": checksum,
                    },
                )

            # A recovered retry may find every index entry already published.
            # Avoid manufacturing a no-op generation in that case.
            if candidate != base.project.model_dump(mode="json"):
                result = services.commits.commit(
                    base=base,
                    candidate=candidate,
                    origin=ChangeOrigin.FRONTEND_EDIT,
                    review_policy=ReviewPolicy.AUTO_FIX,
                    caused_by_request_id=key,
                    round_id=f"round-{operation_id}",
                    transaction_id=operation_id,
                    advance_accepted_baseline=True,
                    _lifecycle_lock_held=True,
                )
                services.poller.note_commit(result.snapshot)

        response = {
            "taskId": _stable_id("task", project_id, key, scope),
            "status": "SUCCEEDED",
            "progress": 1.0,
            "items": output_items,
        }
        records.complete(
            owner_id=project_id,
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
            response=response,
            response_status=status.HTTP_202_ACCEPTED,
        )
        return response, not reservation.created


def _validate_public_remote_url(
    value: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> str:
    try:
        return validate_public_remote_url(value, resolver=resolver)
    except SafeRemoteDownloadError as error:
        raise ValidationError(str(error)) from error


def _validate_response_peer(response: httpx.Response) -> None:
    try:
        validate_response_peer(response)
    except SafeRemoteDownloadError as error:
        raise ValidationError(str(error)) from error


def _download_remote_to_staging(
    url: str,
    *,
    file_store: AssetFileStore,
    staging_id: str,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> _RemoteAssetDownload:
    """Stream one public remote Asset directly into Project staging."""

    original = urlsplit(url)
    max_bytes = _remote_asset_max_bytes()
    staged: StagedAsset | None = None
    try:
        with open_safe_remote_stream(
            url,
            max_bytes=max_bytes,
            timeout=httpx.Timeout(
                _DEFAULT_REMOTE_ASSET_TIMEOUT_SECONDS,
                connect=30,
            ),
        ) as remote:
            current = remote.final_url
            staged = file_store.stage_stream(
                _BoundedRawReader(
                    remote.iter_raw(),
                    max_bytes=max_bytes,
                    total_bytes=remote.declared_size,
                    on_progress=on_progress,
                ),
                staging_id=staging_id,
            )
            if staged.size_bytes == 0:
                file_store.abandon(staged)
                raise ValidationError("远程 Asset 为空")
            media_type = remote.media_type
        if (
            staged is None
        ):  # pragma: no cover - successful response always stages
            raise ValidationError("Asset URL 未产生内容")
        name = (
            Path(urlsplit(current).path or original.path).name
            or "remote-asset.bin"
        )
        return _RemoteAssetDownload(
            name=name,
            staged=staged,
            media_type=media_type or "application/octet-stream",
        )
    except (httpx.HTTPError, ValueError) as error:
        if staged is not None:
            file_store.abandon(staged)
        raise ValidationError(f"无法读取远程 Asset: {error}") from error
    except BaseException:
        if staged is not None:
            file_store.abandon(staged)
        raise


def _ingest_remote_sync(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    url: str,
    requested_name: str,
    attach_source: bool,
    scope: str,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Download outside the Project lock into a non-authoritative Runtime cache.

    The URL-backed AssetVersion already exists before this starts. Cache
    completion never creates another version or advances ``project.json``.
    """

    snapshot = services.projects.read(project_id)
    version_id = _stable_id("asset-version", project_id, key, "0")
    logical_asset_id = _stable_id("asset", project_id, key, "0")
    version = snapshot.project.assets.source_versions_by_id.get(version_id)
    if version is None or version.logical_asset_id != logical_asset_id:
        raise StorageIntegrityError("远程 AssetVersion 注册信息不存在")
    staging_store = AssetFileStore(services.projects.project_root(project_id))
    download: _RemoteAssetDownload | None = None
    try:
        download = _download_remote_to_staging(
            url,
            file_store=staging_store,
            staging_id=_stable_id("remote-stage", project_id, key),
            on_progress=on_progress,
        )
        name = requested_name
        if name.strip() == url.strip() or not Path(name).suffix:
            name = download.name
        cache = publish_remote_cache(
            services.projects.project_root(project_id),
            version,
            download.staged,
            media_type=download.media_type,
        )
        return (
            {
                "taskId": _stable_id("task", project_id, key, scope),
                "status": "SUCCEEDED",
                "progress": 1.0,
                "items": [
                    {
                        "name": name,
                        "assetId": logical_asset_id,
                        "assetVersionId": version_id,
                        "checksum": version.checksum,
                        "cacheChecksum": cache.sha256,
                        "cacheSizeBytes": cache.size_bytes,
                        "cacheRelativeUri": cache.relative_uri,
                        "mediaType": cache.media_type,
                    },
                ],
            },
            False,
        )
    finally:
        if download is not None:
            staging_store.abandon(download.staged)


def _execution_task_view(task: TaskRecord) -> dict[str, Any]:
    return {
        "id": task.task_id,
        "projectId": task.project_id,
        "transactionId": task.round_id,
        "specialistRunId": task.run_id,
        "kind": task.kind.value,
        "targetRef": str(task.metadata.get("targetRef") or ""),
        "status": task.status.value,
        "progress": task.progress,
        "completedElements": task.metadata.get("completedElements"),
        "totalElements": task.metadata.get("totalElements"),
        "resultRefs": task.output_refs,
        "result": task.result,
        "error": task.error,
        "createdAt": task.created_at.isoformat(),
        "updatedAt": task.updated_at.isoformat(),
    }


def _publish_remote_task_event(
    services: CreatorFileServices,
    task: TaskRecord,
    *,
    event_type: str,
) -> None:
    sessions = ProjectRuntimeSessionStore(services.root)
    try:
        session = sessions.get_project_session(task.project_id)
    except RuntimeSessionNotFound:
        # Store-level tests and recovery tools may create a Project without a
        # Creator Session. The durable Task remains the authority in that case.
        return
    sessions.append_event(
        task.project_id,
        session.session_id,
        event_type=event_type,
        payload={
            "taskId": task.task_id,
            "progress": task.progress,
            "status": task.status.value,
            "task": _execution_task_view(task),
        },
    )


def _remote_task_fingerprint(
    *,
    project_id: str,
    key: str,
    url: str,
    requested_name: str,
    attach_source: bool,
) -> str:
    payload = json.dumps(
        {
            "projectId": project_id,
            "key": key,
            "url": url,
            "requestedName": requested_name,
            "attachSource": attach_source,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _register_remote_asset_sync(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    url: str,
    requested_name: str,
    attach_source: bool,
    scope: str,
) -> dict[str, str]:
    """Publish the URL identity before the optional byte cache starts."""

    logical_asset_id = _stable_id("asset", project_id, key, "0")
    version_id = _stable_id("asset-version", project_id, key, "0")
    source_id = _stable_id("source", project_id, key, "0")
    task_id = _stable_id("task", project_id, key, scope)
    name = remote_source_name(url, requested_name)
    media_type = remote_source_media_type(url, name)
    checksum = sha256(url.encode("utf-8")).hexdigest()
    created_at = datetime.now(UTC)
    version = SourceAssetVersion(
        version_id=version_id,
        logical_asset_id=logical_asset_id,
        name=name,
        file_id=None,
        checksum=checksum,
        media_kind=_media_kind(media_type, name),
        media_type=media_type,
        provenance_refs=[url],
        created_at=created_at,
        metadata={
            "clientRequestId": key,
            "sourceKind": "remote_url",
            "publicSourceUrl": url,
            "checksumKind": "source_url_sha256",
            "cacheTaskId": task_id,
        },
    )
    with services.projects.lifecycle_lock(project_id):
        base = services.projects.read(project_id)
        candidate = base.project.model_dump(mode="json")
        versions = candidate["assets"]["source_versions_by_id"]
        existing = versions.get(version_id)
        serialized = version.model_dump(mode="json")
        if existing is not None:
            existing_version = SourceAssetVersion.model_validate(existing)
            if (
                existing_version.logical_asset_id != logical_asset_id
                or existing_version.name != name
                or existing_version.checksum != checksum
                or existing_version.media_type != media_type
                or existing_version.metadata.get("publicSourceUrl") != url
            ):
                raise ConflictError("远程 Asset 稳定 ID 已存在但 URL 身份不同")
        else:
            versions[version_id] = serialized
        if attach_source:
            source_items = candidate["sources"]["sources"]["items"]
            source_order = candidate["sources"]["sources"]["order"]
            source = ProjectSource(
                source_id=source_id,
                display_name=name,
                logical_asset_id=logical_asset_id,
                selected_asset_version_id=version_id,
            ).model_dump(mode="json")
            existing_source = source_items.get(source_id)
            if existing_source is not None and existing_source != source:
                raise ConflictError("远程 ProjectSource 稳定 ID 已存在但内容不同")
            if existing_source is None:
                source_items[source_id] = source
                source_order.append(source_id)
        if candidate != base.project.model_dump(mode="json"):
            result = services.commits.commit(
                base=base,
                candidate=candidate,
                origin=ChangeOrigin.FRONTEND_EDIT,
                review_policy=ReviewPolicy.AUTO_FIX,
                caused_by_request_id=key,
                round_id=f"round-{task_id}",
                transaction_id=task_id,
                advance_accepted_baseline=True,
                _lifecycle_lock_held=True,
            )
            services.poller.note_commit(result.snapshot)
    return {
        "name": name,
        "assetId": logical_asset_id,
        "assetVersionId": version_id,
        "checksum": checksum,
        "mediaType": media_type,
    }


def _ensure_remote_task(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    url: str,
    requested_name: str,
    attach_source: bool,
    scope: str,
) -> TaskRecord:
    executions = ProjectExecutionStore(services.root)
    snapshot = services.projects.read(project_id)
    task_id = _stable_id("task", project_id, key, scope)
    fingerprint = _remote_task_fingerprint(
        project_id=project_id,
        key=key,
        url=url,
        requested_name=requested_name,
        attach_source=attach_source,
    )
    candidate = TaskRecord(
        task_id=task_id,
        project_id=project_id,
        kind=TaskKind.ASSET_INGEST,
        request_fingerprint=fingerprint,
        idempotency_key=key,
        input_generation=snapshot.generation,
        input_etag=snapshot.etag,
        expected_target_version=snapshot.etag,
        input_refs=[
            url,
            f"asset-version:{_stable_id('asset-version', project_id, key, '0')}",
        ],
        progress=0.0,
        caused_by_request_id=key,
        review_policy=ReviewPolicy.AUTO_FIX,
        metadata={
            "targetRef": f"asset:{_stable_id('asset', project_id, key, '0')}",
            "sourceUrl": url,
            "requestedName": requested_name,
            "attachSource": attach_source,
            "assetId": _stable_id("asset", project_id, key, "0"),
            "assetVersionId": _stable_id(
                "asset-version",
                project_id,
                key,
                "0",
            ),
        },
    )
    try:
        existing = executions.get_task(project_id, task_id)
    except RecordNotFoundError:
        try:
            return executions.create_task(candidate)
        except (ExecutionPayloadConflict, ExecutionStateConflict) as error:
            raise ConflictError(str(error)) from error
    if existing.request_fingerprint != fingerprint:
        raise ConflictError("Idempotency-Key 已用于不同的远程 Asset 请求")
    return existing


def _run_remote_task_sync(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    url: str,
    requested_name: str,
    attach_source: bool,
    scope: str,
) -> None:
    executions = ProjectExecutionStore(services.root)
    task_id = _stable_id("task", project_id, key, scope)
    if _REMOTE_INGEST_SHUTTING_DOWN:
        return
    task = executions.get_task(project_id, task_id)
    if task.status in {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }:
        return
    task = executions.transition_task(
        project_id,
        task_id,
        expected_status={TaskStatus.QUEUED, TaskStatus.RUNNING},
        status=TaskStatus.RUNNING,
        updates={"progress": task.progress or 0.0},
    )
    _publish_remote_task_event(services, task, event_type="task.started")
    last_progress = float(task.progress or 0.0)

    def report_progress(downloaded: int, total: int | None) -> None:
        nonlocal last_progress
        if _REMOTE_INGEST_SHUTTING_DOWN:
            raise RuntimeError("Creator 正在关闭，远程素材入库中止")
        current = executions.get_task(project_id, task_id)
        if current.status is TaskStatus.CANCELLED:
            raise RuntimeError("远程素材入库已取消")
        if current.status is not TaskStatus.RUNNING:
            return
        progress = (
            min(0.9, max(0.01, downloaded / total * 0.9))
            if total and total > 0
            else min(0.85, 0.01 + downloaded / (128 * 1024 * 1024))
        )
        if progress < 0.9 and progress - last_progress < 0.01:
            return
        last_progress = progress
        updated = executions.transition_task(
            project_id,
            task_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.RUNNING,
            updates={"progress": progress},
        )
        _publish_remote_task_event(
            services,
            updated,
            event_type="task.progress_updated",
        )

    try:
        result, replayed = _ingest_remote_sync(
            services,
            project_id=project_id,
            key=key,
            url=url,
            requested_name=requested_name,
            attach_source=attach_source,
            scope=scope,
            on_progress=report_progress,
        )
        items = list(result.get("items") or [])
        refs = [
            f"asset-version:{item['assetVersionId']}"
            for item in items
            if item.get("assetVersionId")
        ]
        task = executions.transition_task(
            project_id,
            task_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.SUCCEEDED,
            updates={
                "progress": 1.0,
                "output_refs": refs,
                "result": {"items": items, "idempotentReplay": replayed},
            },
        )
        _publish_remote_task_event(services, task, event_type="task.completed")
    except BaseException as error:
        try:
            current = executions.get_task(project_id, task_id)
        except (ExecutionStoreError, RecordNotFoundError):
            # Project deletion is the terminal cancellation boundary for every
            # Project-local Runtime task. Nothing remains to publish.
            return
        if current.status is TaskStatus.CANCELLED:
            _publish_remote_task_event(
                services,
                current,
                event_type="task.cancelled",
            )
            return
        task = executions.transition_task(
            project_id,
            task_id,
            expected_status={TaskStatus.QUEUED, TaskStatus.RUNNING},
            status=TaskStatus.FAILED,
            updates={
                "error": {
                    "code": "ASSET_INGEST_FAILED",
                    "message": str(error),
                    "type": type(error).__name__,
                },
            },
        )
        _publish_remote_task_event(services, task, event_type="task.failed")


def _start_remote_task(
    services: CreatorFileServices,
    *,
    project_id: str,
    key: str,
    url: str,
    requested_name: str,
    attach_source: bool,
    scope: str,
) -> None:
    if _REMOTE_INGEST_SHUTTING_DOWN:
        return
    task_id = _stable_id("task", project_id, key, scope)
    identity = (project_id, task_id)
    running = _REMOTE_INGEST_TASKS.get(identity)
    if running is not None and not running.done():
        return
    background = asyncio.create_task(
        asyncio.to_thread(
            _run_remote_task_sync,
            services,
            project_id=project_id,
            key=key,
            url=url,
            requested_name=requested_name,
            attach_source=attach_source,
            scope=scope,
        ),
        name=f"creator-remote-asset:{project_id}:{task_id}",
    )
    _REMOTE_INGEST_TASKS[identity] = background

    def completed(task: asyncio.Task[None]) -> None:
        if _REMOTE_INGEST_TASKS.get(identity) is task:
            _REMOTE_INGEST_TASKS.pop(identity, None)
        if not task.cancelled():
            task.exception()

    background.add_done_callback(completed)


def reset_remote_ingest_admission() -> None:
    global _REMOTE_INGEST_SHUTTING_DOWN
    _REMOTE_INGEST_SHUTTING_DOWN = False


async def drain_remote_ingest_tasks(timeout_seconds: float = 15.0) -> None:
    """Stop admission and wait for ingest workers to reach a terminal state.

    These tasks wrap ``asyncio.to_thread`` workers: cancelling the outer
    Task would only sever the await while the thread keeps writing. The
    shutdown flag makes workers abort at their next cooperative checkpoint
    and this coroutine waits for real completion. Workers that outlive the
    timeout keep their registry entries so they are never mistaken for done.
    """

    global _REMOTE_INGEST_SHUTTING_DOWN
    _REMOTE_INGEST_SHUTTING_DOWN = True
    pending = [
        task for task in _REMOTE_INGEST_TASKS.values() if not task.done()
    ]
    if pending:
        await asyncio.wait(pending, timeout=timeout_seconds)
    for identity, task in list(_REMOTE_INGEST_TASKS.items()):
        if task.done():
            _REMOTE_INGEST_TASKS.pop(identity, None)


# Original-footage cache downloads for bundled example Projects. The bytes
# are only a Runtime cache behind an existing URL-backed SourceAssetVersion,
# so completion never advances the Project generation.
_SOURCE_CACHE_DOWNLOADS: dict[tuple[str, str], asyncio.Task[None]] = {}
_SOURCE_CACHE_PROGRESS: dict[tuple[str, str], dict[str, Any]] = {}
_SOURCE_CACHE_PROGRESS_LOCK = threading.Lock()


def _source_cache_progress_set(
    identity: tuple[str, str],
    *,
    state: str,
    received_bytes: int = 0,
    total_bytes: int | None = None,
    error: str | None = None,
) -> None:
    with _SOURCE_CACHE_PROGRESS_LOCK:
        _SOURCE_CACHE_PROGRESS[identity] = {
            "state": state,
            "receivedBytes": received_bytes,
            "totalBytes": total_bytes,
            "error": error,
        }


def _source_cache_progress_get(
    identity: tuple[str, str],
) -> dict[str, Any] | None:
    with _SOURCE_CACHE_PROGRESS_LOCK:
        value = _SOURCE_CACHE_PROGRESS.get(identity)
        return dict(value) if value is not None else None


def _source_cache_task_item(
    tasks: Any,
    version_id: str,
) -> dict[str, Any] | None:
    """Locate the bundled SUCCEEDED asset_ingest result for one version."""

    for task in tasks:
        if (
            task.kind is not TaskKind.ASSET_INGEST
            or task.status is not TaskStatus.SUCCEEDED
            or task.metadata.get("assetVersionId") != version_id
        ):
            continue
        items = list((task.result or {}).get("items") or [])
        item = next(
            (
                value
                for value in items
                if isinstance(value, dict)
                and value.get("assetVersionId") == version_id
            ),
            None,
        )
        if item is not None:
            return item
    return None


def _download_source_cache_sync(
    services: CreatorFileServices,
    *,
    project_id: str,
    version_id: str,
    url: str,
    expected_size_bytes: int | None,
) -> None:
    identity = (project_id, version_id)
    try:
        snapshot = services.projects.read(project_id)
        version = snapshot.project.assets.source_versions_by_id.get(
            version_id,
        )
        if version is None:
            raise NotFoundError("远程 AssetVersion 不存在")
        project_root = services.projects.project_root(project_id)
        staging_store = AssetFileStore(project_root)

        def report_progress(downloaded: int, total: int | None) -> None:
            if _REMOTE_INGEST_SHUTTING_DOWN:
                raise RuntimeError("Creator 正在关闭，原片下载中止")
            _source_cache_progress_set(
                identity,
                state="downloading",
                received_bytes=downloaded,
                total_bytes=total or expected_size_bytes,
            )

        download: _RemoteAssetDownload | None = None
        try:
            download = _download_remote_to_staging(
                url,
                file_store=staging_store,
                staging_id=_stable_id(
                    "source-cache",
                    project_id,
                    version_id,
                ),
                on_progress=report_progress,
            )
            if (
                expected_size_bytes is not None
                and download.staged.size_bytes != expected_size_bytes
            ):
                raise ValidationError("下载的原片大小与入库任务记录不一致")
            publish_remote_cache(
                project_root,
                version,
                download.staged,
                media_type=download.media_type,
            )
        finally:
            if download is not None:
                staging_store.abandon(download.staged)
        _source_cache_progress_set(
            identity,
            state="cached",
            received_bytes=download.staged.size_bytes
            if download is not None
            else 0,
            total_bytes=download.staged.size_bytes
            if download is not None
            else expected_size_bytes,
        )
    except BaseException as error:
        if not isinstance(error, KeyboardInterrupt):
            _source_cache_progress_set(
                identity,
                state="failed",
                error=str(error),
            )
        raise


def _start_source_cache_download(
    services: CreatorFileServices,
    *,
    project_id: str,
    version_id: str,
    url: str,
    expected_size_bytes: int | None,
) -> None:
    if _REMOTE_INGEST_SHUTTING_DOWN:
        return
    identity = (project_id, version_id)
    running = _SOURCE_CACHE_DOWNLOADS.get(identity)
    if running is not None and not running.done():
        return
    background = asyncio.create_task(
        asyncio.to_thread(
            _download_source_cache_sync,
            services,
            project_id=project_id,
            version_id=version_id,
            url=url,
            expected_size_bytes=expected_size_bytes,
        ),
        name=f"creator-source-cache:{project_id}:{version_id}",
    )
    _SOURCE_CACHE_DOWNLOADS[identity] = background
    # Share the ingest registry so shutdown drains these workers too.
    drain_identity = (project_id, f"source-cache:{version_id}")
    _REMOTE_INGEST_TASKS[drain_identity] = background

    def completed(task: asyncio.Task[None]) -> None:
        if _SOURCE_CACHE_DOWNLOADS.get(identity) is task:
            _SOURCE_CACHE_DOWNLOADS.pop(identity, None)
        if _REMOTE_INGEST_TASKS.get(drain_identity) is task:
            _REMOTE_INGEST_TASKS.pop(drain_identity, None)
        if not task.cancelled():
            task.exception()

    background.add_done_callback(completed)


def _source_cache_version_view(
    *,
    project_root: Path,
    version: SourceAssetVersion,
    tasks: Any,
) -> dict[str, Any] | None:
    url = public_source_url(version)
    if version.file_id is not None or url is None:
        return None
    item = _source_cache_task_item(tasks, version.version_id)
    expected_size: int | None = None
    if item is not None:
        try:
            expected_size = int(item["cacheSizeBytes"])
        except (KeyError, TypeError, ValueError):
            expected_size = None
    cached = resolve_remote_cache(project_root, version, tasks) is not None
    return {
        "assetVersionId": version.version_id,
        "name": version.name,
        "sourceUrl": url,
        "cached": cached,
        "expectedSizeBytes": expected_size,
    }


@router.get("/source-cache")
async def get_source_cache(
    project_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    """Cache state of every URL-backed source version in one Project."""

    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    project_root = services.projects.project_root(project_id)
    tasks = await asyncio.to_thread(
        ProjectExecutionStore(services.root).list_tasks,
        project_id,
    )
    versions: list[dict[str, Any]] = []
    for version in snapshot.project.assets.source_versions_by_id.values():
        view = _source_cache_version_view(
            project_root=project_root,
            version=version,
            tasks=tasks,
        )
        if view is None:
            continue
        identity = (project_id, version.version_id)
        progress = _source_cache_progress_get(identity)
        if view["cached"]:
            state = "cached"
        elif progress is not None and progress["state"] in {
            "downloading",
            "failed",
        }:
            state = progress["state"]
        else:
            state = "idle"
        view["state"] = state
        view["receivedBytes"] = (
            progress["receivedBytes"] if progress is not None else 0
        )
        if view["expectedSizeBytes"] is None and progress is not None:
            view["expectedSizeBytes"] = progress["totalBytes"]
        view["error"] = progress["error"] if progress is not None else None
        versions.append(view)
    return {"projectId": project_id, "versions": versions}


@router.post(
    "/source-cache/{version_id}/download",
    status_code=status.HTTP_202_ACCEPTED,
)
async def download_source_cache(
    project_id: str,
    version_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    """Fetch the remote original footage behind one example source version."""

    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    version = snapshot.project.assets.source_versions_by_id.get(version_id)
    if version is None:
        raise NotFoundError("AssetVersion 不存在")
    url = public_source_url(version)
    if version.file_id is not None or url is None:
        raise ValidationError("该素材不是远程 URL 素材")
    project_root = services.projects.project_root(project_id)
    tasks = await asyncio.to_thread(
        ProjectExecutionStore(services.root).list_tasks,
        project_id,
    )
    if resolve_remote_cache(project_root, version, tasks) is not None:
        return {"assetVersionId": version_id, "state": "cached"}
    item = _source_cache_task_item(tasks, version_id)
    if item is None:
        raise NotFoundError("缺少远程素材入库任务记录，无法下载原片")
    expected_size: int | None
    try:
        expected_size = int(item["cacheSizeBytes"])
    except (KeyError, TypeError, ValueError):
        expected_size = None
    identity = (project_id, version_id)
    running = _SOURCE_CACHE_DOWNLOADS.get(identity)
    if running is not None and not running.done():
        progress = _source_cache_progress_get(identity) or {}
        return {
            "assetVersionId": version_id,
            "state": "downloading",
            "receivedBytes": progress.get("receivedBytes", 0),
            "totalBytes": progress.get("totalBytes") or expected_size,
        }
    if _REMOTE_INGEST_SHUTTING_DOWN:
        raise ValidationError("Creator 正在关闭，无法开始原片下载")
    url = _validate_public_remote_url(url)
    _source_cache_progress_set(
        identity,
        state="downloading",
        received_bytes=0,
        total_bytes=expected_size,
    )
    _start_source_cache_download(
        services,
        project_id=project_id,
        version_id=version_id,
        url=url,
        expected_size_bytes=expected_size,
    )
    return {
        "assetVersionId": version_id,
        "state": "downloading",
        "receivedBytes": 0,
        "totalBytes": expected_size,
    }


def _translate(error: BaseException) -> None:
    if isinstance(error, IdempotencyConflictError):
        raise ConflictError("Idempotency-Key 已用于不同的 Asset 请求") from error
    if isinstance(error, IdempotencyStateConflictError):
        raise ConflictError("Asset idempotency 状态冲突") from error
    if isinstance(error, AssetFileError):
        raise StorageIntegrityError(str(error)) from error
    raise error


@router.post("/assets", status_code=status.HTTP_202_ACCEPTED)
async def ingest_asset(
    project_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    staged_uploads: list[_StagedAssetInput] = []
    upload_store: AssetFileStore | None = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = next(
            (
                value
                for _, value in form.multi_items()
                if isinstance(value, UploadFile)
            ),
            None,
        )
        if upload is None:
            raise ValidationError("multipart assets 请求缺少 file")
        key = resolve_idempotency_key(
            idempotency_key,
            stable_client_id=str(form.get("clientRequestId") or ""),
        )
        post_action = str(form.get("postIngestAction") or "NONE")
        name = Path(upload.filename or "upload.bin").name
        media_type = (
            upload.content_type
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream"
        )
        _validate_local_video_upload(
            name=name,
            media_type=media_type,
            size_bytes=upload.size,
        )
        if post_action == "ATTACH_SOURCE":
            _assert_supported_source_upload(name, media_type)
        upload_store = await _upload_file_store(services, project_id)
        input_item: _AssetInput | _StagedAssetInput = await _stage_upload(
            upload,
            name=name,
            media_type=media_type,
            file_store=upload_store,
            staging_id=_stable_id("upload", project_id, key, "0"),
        )
        staged_uploads.append(input_item)
        remote_url: str | None = None
    else:
        body = TextOrUrlAssetRequest.model_validate(await request.json())
        key = resolve_idempotency_key(
            idempotency_key,
            stable_client_id=body.client_request_id,
        )
        post_action = body.post_ingest_action
        name = body.name.strip() or "asset"
        if body.kind == "text":
            payload = body.value.encode("utf-8")
            media_type = "text/plain; charset=utf-8"
            input_item = _AssetInput(
                name=name,
                content=payload,
                media_type=media_type,
            )
            remote_url = None
        else:
            remote_url = body.value
    if post_action not in {"NONE", "ATTACH_SOURCE"}:
        raise ValidationError("postIngestAction 非法")
    try:
        if remote_url is not None:
            remote_url = _validate_public_remote_url(remote_url)
            indexed_item = await asyncio.to_thread(
                _register_remote_asset_sync,
                services,
                project_id=project_id,
                key=key,
                url=remote_url,
                requested_name=name,
                attach_source=post_action == "ATTACH_SOURCE",
                scope="POST-assets",
            )
            task = await asyncio.to_thread(
                _ensure_remote_task,
                services,
                project_id=project_id,
                key=key,
                url=remote_url,
                requested_name=name,
                attach_source=post_action == "ATTACH_SOURCE",
                scope="POST-assets",
            )
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                _start_remote_task(
                    services,
                    project_id=project_id,
                    key=key,
                    url=remote_url,
                    requested_name=name,
                    attach_source=post_action == "ATTACH_SOURCE",
                    scope="POST-assets",
                )
            return {
                "assetId": indexed_item["assetId"],
                "taskId": task.task_id,
                "status": task.status.value,
                "progress": task.progress,
                "assetVersionId": indexed_item["assetVersionId"],
                "result": task.result,
                "error": task.error,
            }
        else:
            result, replayed = await asyncio.to_thread(
                _ingest_many_sync,
                services,
                project_id=project_id,
                key=key,
                inputs=[input_item],
                attach_source=post_action == "ATTACH_SOURCE",
                scope="POST-assets",
            )
    except BaseException as error:
        _translate(error)
    finally:
        await _abandon_staged_uploads(upload_store, staged_uploads)
    item = result["items"][0]
    logger.info(
        "asset ingested: project=%s asset=%s status=%s",
        project_id,
        item["assetId"],
        result["status"],
    )
    return {
        "assetId": item["assetId"],
        "taskId": result["taskId"],
        "status": result["status"],
        "progress": result["progress"],
        "assetVersionId": item["assetVersionId"],
        "result": {"items": result["items"], "idempotentReplay": replayed},
        "error": None,
    }


@router.post("/asset-imports", status_code=status.HTTP_202_ACCEPTED)
async def import_assets(
    project_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    if not request.headers.get("content-type", "").startswith(
        "multipart/form-data",
    ):
        raise ValidationError("asset-imports 只接受 multipart")
    form = await request.form()
    key = resolve_idempotency_key(
        idempotency_key,
        stable_client_id=str(form.get("clientRequestId") or ""),
    )
    post_action = str(form.get("postIngestAction") or "NONE")
    if post_action not in {"NONE", "ATTACH_SOURCE"}:
        raise ValidationError("postIngestAction 非法")
    uploads = [
        value
        for _, value in form.multi_items()
        if isinstance(value, UploadFile)
    ]
    if not uploads:
        raise ValidationError("文件夹导入至少包含一个文件")
    max_files = _positive_int_env(
        "CREATOR_IMPORT_MAX_FILES",
        _DEFAULT_IMPORT_MAX_FILES,
    )
    if len(uploads) > max_files:
        raise ValidationError(f"文件夹导入最多支持 {max_files} 个文件")
    max_total_bytes = _positive_int_env(
        "CREATOR_IMPORT_MAX_TOTAL_BYTES",
        _DEFAULT_IMPORT_MAX_TOTAL_BYTES,
    )
    upload_store = await _upload_file_store(services, project_id)
    total_bytes = 0
    inputs: list[_AssetInput | _StagedAssetInput] = []
    staged_uploads: list[_StagedAssetInput] = []
    try:
        for index, upload in enumerate(uploads):
            name = Path(upload.filename or f"item-{index + 1}").name
            media_type = (
                upload.content_type
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream"
            )
            _validate_local_video_upload(
                name=name,
                media_type=media_type,
                size_bytes=upload.size,
            )
            if post_action == "ATTACH_SOURCE":
                _assert_supported_source_upload(name, media_type)
            item = await _stage_upload(
                upload,
                name=name,
                media_type=media_type,
                file_store=upload_store,
                staging_id=_stable_id("upload", project_id, key, str(index)),
            )
            staged_uploads.append(item)
            total_bytes += item.staged.size_bytes
            if total_bytes > max_total_bytes:
                raise ValidationError(
                    f"文件夹导入总量超过 " f"{_format_byte_limit(max_total_bytes)} 限制",
                )
            inputs.append(item)
        result, _replayed = await asyncio.to_thread(
            _ingest_many_sync,
            services,
            project_id=project_id,
            key=key,
            inputs=inputs,
            attach_source=post_action == "ATTACH_SOURCE",
            scope="POST-asset-imports",
        )
    except BaseException as error:
        _translate(error)
    finally:
        await _abandon_staged_uploads(upload_store, staged_uploads)
    import_id = _stable_id("asset-import", project_id, key)
    record = AssetImportRecord(
        importId=import_id,
        taskId=result["taskId"],
        projectId=project_id,
        status="SUCCEEDED",
        progress=1.0,
        items=[
            AssetImportItemRecord(
                name=item["name"],
                assetVersionId=item["assetVersionId"],
                checksum=item["checksum"],
            )
            for item in result["items"]
        ],
        createdAt=datetime.now(UTC),
    )
    await asyncio.to_thread(
        AtomicJsonRecordStore(
            services.projects.project_root(project_id)
            / "runtime"
            / "asset-imports"
            / f"{import_id}.json",
            AssetImportRecord,
        ).write,
        record,
    )
    logger.info(
        "asset import started: project=%s import=%s files=%d",
        project_id,
        import_id,
        len(uploads),
    )
    return {"importId": import_id, "taskId": result["taskId"], "eventSeq": 0}


@router.get("/asset-imports/{import_id}")
async def get_asset_import(
    project_id: str,
    import_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    try:
        record = await asyncio.to_thread(
            AtomicJsonRecordStore(
                services.projects.project_root(project_id)
                / "runtime"
                / "asset-imports"
                / f"{import_id}.json",
                AssetImportRecord,
            ).read,
        )
    except RecordNotFoundError as error:
        raise NotFoundError("asset import 不存在") from error
    if record.project_id != project_id or record.import_id != import_id:
        raise StorageIntegrityError("asset import identity 损坏")
    return record.model_dump(
        mode="json",
        by_alias=True,
        exclude={"project_id", "created_at"},
    )


@router.get("/asset-imports/{import_id}/events")
async def get_asset_import_events(
    project_id: str,
    import_id: str,
    after: int = Query(0, ge=0),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    del after
    await get_asset_import(project_id, import_id, services)
    return {"items": []}


def _asset_version(project: Any, asset_id: str, version_id: str | None):
    candidates = [
        item
        for item in project.assets.source_versions_by_id.values()
        if item.logical_asset_id == asset_id
        and (version_id is None or item.version_id == version_id)
    ]
    if not candidates:
        raise NotFoundError("AssetVersion 不存在")
    return max(candidates, key=lambda item: item.created_at)


@router.get("/assets/{asset_id}/content")
async def get_asset_content(
    project_id: str,
    asset_id: str,
    version_id: str | None = Query(None, alias="versionId"),
    services: CreatorFileServices = Depends(project_file_services),
) -> StreamingResponse:
    try:
        project = await asyncio.to_thread(services.projects.read, project_id)
    except Exception as error:
        raise NotFoundError("Project 不存在") from error
    version = _asset_version(project.project, asset_id, version_id)
    if version.file_id is None:
        cache = await asyncio.to_thread(
            resolve_remote_cache,
            services.projects.project_root(project_id),
            version,
            ProjectExecutionStore(services.root).list_tasks(project_id),
        )
        if cache is None:
            raise NotFoundError("远程 Asset 本地缓存尚未完成")
        return StreamingResponse(
            cache.path.open("rb"),
            media_type=version.media_type,
            headers={
                "Content-Length": str(cache.size_bytes),
                "Content-Disposition": inline_content_disposition(
                    version.name,
                    version.media_type,
                ),
                "ETag": f'"sha256:{cache.sha256}"',
            },
        )
    indexed = project.project.assets.files_by_id[version.file_id]
    try:
        stream = await asyncio.to_thread(
            AssetFileStore(
                services.projects.project_root(project_id),
            ).open_verified,
            indexed,
        )
    except AssetFileError as error:
        raise StorageIntegrityError(str(error)) from error
    return StreamingResponse(
        stream,
        media_type=version.media_type,
        headers={
            "Content-Length": str(indexed.size_bytes),
            "Content-Disposition": inline_content_disposition(
                version.name,
                version.media_type,
            ),
            "ETag": f'"sha256:{indexed.sha256}"',
        },
    )


__all__ = ["router"]
