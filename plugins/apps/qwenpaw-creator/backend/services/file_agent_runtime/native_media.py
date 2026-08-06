# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-statements
"""Resolve all media attached to one user request for a file-native Specialist."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from domain.errors import StorageIntegrityError, ValidationError
from models import config as model_config
from models.media_transport import upload_local_file_to_dashscope_temp
from services.project_files.assets import AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.remote_cache import resolve_remote_cache
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.media_probe import (
    MediaProbeError,
    MediaProbeUnavailable,
    probe_media,
)
from services.runtime_files.models import CreatorMessageRecord

_MEDIA_PART_TYPES = frozenset({"image_url", "video_url"})


def _version_id_from_ref(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.startswith("asset-version:"):
        return None
    identifier = text.removeprefix("asset-version:").strip()
    return identifier or None


def _part_identity(part: Mapping[str, Any]) -> tuple[str, str]:
    part_type = str(part.get("type") or "")
    payload = part.get(part_type)
    nested = dict(payload) if isinstance(payload, Mapping) else {}
    attachment = part.get("attachment")
    attachment = dict(attachment) if isinstance(attachment, Mapping) else {}
    version_id = str(
        nested.get("versionId")
        or _version_id_from_ref(attachment.get("assetVersionRef"))
        or "",
    )
    return part_type, version_id or f"url:{nested.get('url') or ''}"


def _safe_public_model_url(metadata: Mapping[str, Any]) -> str | None:
    for key in ("nativeModelUrl", "publicSourceUrl"):
        value = str(metadata.get(key) or "").strip()
        parsed = urlparse(value)
        if (
            parsed.scheme in {"http", "https", "oss"}
            and parsed.netloc
            and parsed.username is None
            and parsed.password is None
        ):
            return value
    return None


def _source_video_sampling_fps(duration_seconds: float | None) -> float:
    """Keep short-video detail while bounding long-video native sampling."""

    if duration_seconds is None or duration_seconds <= 0:
        return 0.5
    if duration_seconds <= 120:
        return 2.0
    if duration_seconds <= 600:
        return 1.0
    return 0.5


def _runtime_duration_seconds(
    services: CreatorFileServices,
    project_id: str,
    version: Any,
) -> float | None:
    if version.duration_seconds is not None:
        return version.duration_seconds
    cache = resolve_remote_cache(
        services.projects.project_root(project_id),
        version,
        ProjectExecutionStore(services.root).list_tasks(project_id),
    )
    if cache is None:
        return None
    try:
        return probe_media(str(cache.path)).duration_seconds
    except (MediaProbeError, MediaProbeUnavailable):
        return None


async def source_intelligence_content_parts(
    services: CreatorFileServices,
    *,
    project_id: str,
    request: CreatorMessageRecord,
) -> list[dict[str, Any]]:
    """Return every native image/video supplied by the triggering user message.

    Public URLs stay public so analysis can begin while the Runtime cache task
    is still downloading. File-backed ``assetVersionRefs`` are resolved through
    ``project.json`` and uploaded to DashScope's model-bound temporary OSS.
    Nothing is silently converted to a textual URL placeholder.
    """

    parts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    referenced_versions: list[str] = []

    for content_part in request.content_parts:
        payload = content_part.model_dump(mode="json", exclude_none=True)
        if content_part.type in _MEDIA_PART_TYPES:
            nested = payload.get(content_part.type)
            if not isinstance(nested, Mapping) or not str(
                nested.get("url") or "",
            ):
                raise ValidationError(
                    f"用户素材 {content_part.type} 缺少可传给模型的 URL",
                )
            identity = _part_identity(payload)
            if identity not in seen:
                seen.add(identity)
                seen_urls.add(str(nested.get("url") or ""))
                parts.append(payload)
        attachment = payload.get("attachment")
        if isinstance(attachment, Mapping):
            version_id = _version_id_from_ref(
                attachment.get("assetVersionRef"),
            )
            if version_id:
                referenced_versions.append(version_id)

    metadata_refs = request.metadata.get("assetVersionRefs") or []
    if isinstance(metadata_refs, list):
        referenced_versions.extend(
            version_id
            for value in metadata_refs
            if (version_id := _version_id_from_ref(value)) is not None
        )

    if not referenced_versions:
        return parts

    snapshot = services.projects.read(project_id)
    file_store = AssetFileStore(services.projects.project_root(project_id))
    api_key = model_config.get_vlm_api_key().strip()
    model_name = (model_config.get_vlm_model_name() or "qwen3.7-plus").strip()
    for version_id in dict.fromkeys(referenced_versions):
        version = snapshot.project.assets.source_versions_by_id.get(version_id)
        if version is None:
            raise ValidationError(
                f"用户素材引用的 AssetVersion 不存在: {version_id}",
            )
        if version.media_kind not in {"image", "video"}:
            continue
        part_type = (
            "image_url" if version.media_kind == "image" else "video_url"
        )
        identity = (part_type, version_id)
        if identity in seen:
            continue
        public_url = _safe_public_model_url(version.metadata)
        if public_url is None:
            if version.file_id is None:
                raise StorageIntegrityError(
                    f"AssetVersion {version_id} 缺少本地文件与公网 URL",
                )
            indexed = snapshot.project.assets.files_by_id.get(version.file_id)
            if indexed is None:
                raise StorageIntegrityError(
                    f"AssetVersion {version_id} 引用的 IndexedFile 不存在",
                )
            inspection = file_store.inspect(indexed)
            if not inspection.available:
                raise StorageIntegrityError(
                    f"用户素材 {version_id} 不可用: {inspection.status.value}",
                )
            if not api_key:
                raise ValidationError(
                    "本地素材传给素材理解 Agent 需要配置 Creator VLM API key",
                )
            local_path = Path(file_store.project_root, indexed.relative_uri)
            public_url = await upload_local_file_to_dashscope_temp(
                local_path,
                api_key=api_key,
                model_name=model_name,
                media_type=version.media_type,
            )
        if public_url in seen_urls:
            continue
        native_payload: dict[str, Any] = {
            "url": public_url,
            "mediaType": version.media_type,
            "versionId": version.version_id,
            "checksum": version.checksum,
        }
        if part_type == "video_url":
            duration_seconds = await asyncio.to_thread(
                _runtime_duration_seconds,
                services,
                project_id,
                version,
            )
            native_payload["fps"] = _source_video_sampling_fps(
                duration_seconds,
            )
            if duration_seconds is not None:
                native_payload["durationMs"] = round(duration_seconds * 1000)
        parts.append(
            {
                "type": part_type,
                part_type: native_payload,
                "attachment": {
                    "assetVersionRef": f"asset-version:{version.version_id}",
                    "mediaType": version.media_type,
                },
            },
        )
        seen.add(identity)
        seen_urls.add(public_url)
    return parts


async def document_page_content_parts(
    services: CreatorFileServices,
    *,
    project_id: str,
    tool_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Turn a read_document tool result into native image parts.

    Rendered page images live as Runtime files (doc-pages/); they enter the
    outer VLM context through the existing multimodal user-message mechanism
    instead of inline base64 in the tool return body.
    """

    from services.source_analysis.service import resolve_document_page_ref

    refs = tool_result.get("pageImageRefs")
    if not isinstance(refs, list) or not refs:
        return []
    api_key = model_config.get_vlm_api_key().strip()
    if not api_key:
        raise ValidationError(
            "文档页图传给素材理解 Agent 需要配置 Creator VLM API key",
        )
    model_name = (model_config.get_vlm_model_name() or "qwen3.7-plus").strip()
    project_root = services.projects.project_root(project_id)
    parts: list[dict[str, Any]] = []
    for ref in refs:
        resolved = resolve_document_page_ref(project_root, str(ref))
        if resolved is None:
            raise StorageIntegrityError(f"非法文档页图引用: {ref}")
        _checksum, page, local_path = resolved
        if not local_path.is_file():
            raise StorageIntegrityError(f"文档页图不存在: {ref}")
        public_url = await upload_local_file_to_dashscope_temp(
            local_path,
            api_key=api_key,
            model_name=model_name,
            media_type="image/png",
        )
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": public_url,
                    "mediaType": "image/png",
                    "page": page,
                },
                "attachment": {
                    "documentPageRef": str(ref),
                    "mediaType": "image/png",
                },
            },
        )
    return parts


__all__ = [
    "document_page_content_parts",
    "source_intelligence_content_parts",
]
