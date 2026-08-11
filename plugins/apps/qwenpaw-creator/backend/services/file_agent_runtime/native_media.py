# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-statements
"""Resolve all media attached to one user request for a file-native Specialist."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
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

# DashScope rejects native video inputs shorter than about two seconds
# ("The video file is too short"); such clips are delivered as an ordered
# frame sequence instead.
_NATIVE_VIDEO_MIN_SECONDS = 2.0
_SHORT_VIDEO_FRAME_COUNT = 4
_FRAME_GRAB_TIMEOUT_SECONDS = 60


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


def _local_source_path(
    snapshot: Any,
    file_store: AssetFileStore,
    version: Any,
) -> Path | None:
    if version.file_id is None:
        return None
    indexed = snapshot.project.assets.files_by_id.get(version.file_id)
    if indexed is None:
        return None
    candidate = Path(file_store.project_root, indexed.relative_uri)
    return candidate if candidate.is_file() else None


def _runtime_duration_seconds(
    services: CreatorFileServices,
    project_id: str,
    version: Any,
) -> float | None:
    if version.duration_seconds is not None:
        return version.duration_seconds
    probe_path: Path | None = None
    if version.file_id is not None:
        # Panel-uploaded sources keep their bytes in the local asset store
        # but were ingested without probing; measure them directly.
        project_root = services.projects.project_root(project_id)
        snapshot = services.projects.read(project_id)
        indexed = snapshot.project.assets.files_by_id.get(version.file_id)
        if indexed is not None:
            candidate = Path(project_root, indexed.relative_uri)
            if candidate.is_file():
                probe_path = candidate
    if probe_path is None:
        cache = resolve_remote_cache(
            services.projects.project_root(project_id),
            version,
            ProjectExecutionStore(services.root).list_tasks(project_id),
        )
        if cache is None:
            return None
        probe_path = cache.path
    try:
        return probe_media(str(probe_path)).duration_seconds
    except (MediaProbeError, MediaProbeUnavailable):
        return None


def _extract_video_frames_sync(
    local_path: Path,
    duration_seconds: float,
    output_dir: Path,
) -> list[tuple[int, Path]]:
    """Grab evenly spaced frames (first to last) from a short clip."""

    from services.runtime_files.runtime_dependencies import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return []
    last = max(0.0, duration_seconds - 0.05)
    count = _SHORT_VIDEO_FRAME_COUNT
    stamps = [round(index * last / (count - 1), 3) for index in range(count)]
    frames: list[tuple[int, Path]] = []
    for index, stamp in enumerate(stamps):
        frame_path = output_dir / f"frame-{index:02d}.jpg"
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(stamp),
                "-i",
                str(local_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-y",
                str(frame_path),
            ],
            # Detach stdin so ffmpeg is not suspended by SIGTTIN when it
            # reads the tty from a background process group.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_FRAME_GRAB_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode == 0 and frame_path.is_file():
            frames.append((round(stamp * 1000), frame_path))
    return frames


async def _short_video_frame_parts(
    local_path: Path,
    *,
    version: Any,
    duration_seconds: float,
    api_key: str,
    model_name: str,
) -> list[dict[str, Any]]:
    """Deliver a too-short clip as an ordered native frame sequence."""

    with tempfile.TemporaryDirectory(prefix="short-video-frames-") as tmp:
        frames = await asyncio.to_thread(
            _extract_video_frames_sync,
            local_path,
            duration_seconds,
            Path(tmp),
        )
        if not frames:
            return []
        duration_ms = round(duration_seconds * 1000)
        parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"素材 {version.name}（asset-version:{version.version_id}，"
                    f"真实时长 {duration_ms}ms）短于模型原生视频最小时长，"
                    f"以下 {len(frames)} 张图片是它按时间顺序的抽帧序列"
                    "（附每帧时间戳），请基于这些帧完成该素材的内容理解。"
                ),
            },
        ]
        for timestamp_ms, frame_path in frames:
            public_url = await upload_local_file_to_dashscope_temp(
                frame_path,
                api_key=api_key,
                model_name=model_name,
                media_type="image/jpeg",
            )
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": public_url,
                        "mediaType": "image/jpeg",
                        "versionId": version.version_id,
                        "frameTimestampMs": timestamp_ms,
                    },
                    "attachment": {
                        "assetVersionRef": (
                            f"asset-version:{version.version_id}"
                        ),
                        "mediaType": "image/jpeg",
                    },
                },
            )
        return parts


async def source_intelligence_content_parts(
    services: CreatorFileServices,
    *,
    project_id: str,
    request: CreatorMessageRecord,
    target_refs: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return every native image/video the delegated specialist must observe.

    Media comes from two places: attachments carried by the triggering user
    message, and the delegated ``asset:<logicalAssetId>`` target refs resolved
    through each ProjectSource's selected version — sources ingested from the
    assets panel carry no message attachment, so target refs are the only
    route to their media. Public URLs stay public so analysis can begin while
    the Runtime cache task is still downloading. File-backed versions are
    uploaded to DashScope's model-bound temporary OSS. Clips shorter than the
    model's native-video minimum are delivered as ordered frame sequences.
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

    if not referenced_versions and not target_refs:
        return parts

    snapshot = services.projects.read(project_id)
    if target_refs:
        sources_by_asset = {
            source.logical_asset_id: source
            for source in snapshot.project.sources.sources.items.values()
        }
        for target_ref in target_refs:
            kind, separator, identifier = str(target_ref).partition(":")
            if kind != "asset" or not separator or not identifier:
                continue
            source = sources_by_asset.get(identifier)
            if source is None:
                # Media may instead arrive as message attachments (the
                # pre-existing contract); leave unmatched refs for the
                # specialist itself to report.
                continue
            referenced_versions.append(source.selected_asset_version_id)
    if not referenced_versions:
        return parts

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
        duration_seconds: float | None = None
        if part_type == "video_url":
            duration_seconds = await asyncio.to_thread(
                _runtime_duration_seconds,
                services,
                project_id,
                version,
            )
            if (
                duration_seconds is not None
                and duration_seconds < _NATIVE_VIDEO_MIN_SECONDS
            ):
                local_path = _local_source_path(snapshot, file_store, version)
                if local_path is not None:
                    if not api_key:
                        raise ValidationError(
                            "本地素材传给素材理解 Agent 需要配置 Creator VLM API key",
                        )
                    frame_parts = await _short_video_frame_parts(
                        local_path,
                        version=version,
                        duration_seconds=duration_seconds,
                        api_key=api_key,
                        model_name=model_name,
                    )
                    if frame_parts:
                        parts.extend(frame_parts)
                        seen.add(identity)
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


async def video_frame_content_parts(
    services: CreatorFileServices,
    *,
    project_id: str,
    task_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Turn a read_source_video task result into native image parts.

    Extracted frames live as Runtime files (video-frames/); they enter
    the specialist context interleaved with their source timestamps,
    mirroring the upstream read_video ``<MM:SS>`` + frame layout.
    """

    from services.media.source_video_reader import resolve_video_frame_ref

    refs = task_result.get("frameImageRefs")
    if not isinstance(refs, list):
        # wait=TASK tool payloads nest the task output under "result".
        nested = task_result.get("result")
        refs = (
            nested.get("frameImageRefs")
            if isinstance(nested, Mapping)
            else None
        )
    if not isinstance(refs, list) or not refs:
        return []
    api_key = model_config.get_vlm_api_key().strip()
    if not api_key:
        raise ValidationError(
            "视频帧图传给专家 Agent 需要配置 Creator VLM API key",
        )
    model_name = (model_config.get_vlm_model_name() or "qwen3.7-plus").strip()
    project_root = services.projects.project_root(project_id)
    parts: list[dict[str, Any]] = []
    for entry in refs:
        if not isinstance(entry, Mapping):
            continue
        ref = str(entry.get("ref") or "")
        resolved = resolve_video_frame_ref(Path(project_root), ref)
        if resolved is None:
            raise StorageIntegrityError(f"非法视频帧引用: {ref}")
        _version_id, ts_ms, local_path = resolved
        # Defense-in-depth: refs come from persisted task output, so the
        # resolved path must stay inside the project root even though the
        # EntityId grammar already excludes traversal characters.
        if not local_path.resolve().is_relative_to(
            Path(project_root).resolve(),
        ):
            raise StorageIntegrityError(f"视频帧路径越界: {ref}")
        if not local_path.is_file():
            raise StorageIntegrityError(f"视频帧不存在: {ref}")
        public_url = await upload_local_file_to_dashscope_temp(
            local_path,
            api_key=api_key,
            model_name=model_name,
            media_type="image/jpeg",
        )
        parts.append(
            {
                "type": "text",
                "text": f"<{entry.get('label') or ts_ms}>",
            },
        )
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": public_url,
                    "mediaType": "image/jpeg",
                    "frameTimestampMs": ts_ms,
                },
                "attachment": {
                    "videoFrameRef": ref,
                    "mediaType": "image/jpeg",
                },
            },
        )
    return parts


__all__ = [
    "document_page_content_parts",
    "source_intelligence_content_parts",
    "video_frame_content_parts",
]
