# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,raise-missing-from
# pylint: disable=too-many-boolean-expressions,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
"""File-native Source Intelligence validation, modality tools, and publishing.

The outer Source Intelligence VLM is the only visual-understanding producer.
This boundary verifies the exact selected SourceAssetVersion, runs optional
non-VLM modality tools such as ASR, normalizes the outer VLM's structured
payload, and publishes one immutable SourceIntelligenceIndex.  The legacy
direct ANALYZE_SOURCE_MEDIA task protocol remains fail-closed for recovery of
older Runtime records and never starts a hidden VLM call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from domain.enums import (
    TERMINAL_SPECIALIST_STATUSES,
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from models import config as model_config
from models import asr_model
from schemas.assets import (
    DocumentMetadata,
    DocumentTextCoverage,
    SourceAgentIntelligenceInput,
    SourceIndexQueryResult,
    SourceIntelligenceIndex,
    SourceMediaMetadata,
    SourceModelRunRef,
)
from services.document_reader import (
    is_supported_document,
    read_document,
)
from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileError,
    AssetFileStore,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    IndexedFile,
    Project,
    ProjectSource,
    SourceAssetVersion,
    SourceIntelligenceVersion,
)
from services.project_files.remote_cache import (
    public_source_url,
    resolve_remote_cache,
)
from services.project_files.serialization import canonical_json_bytes
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from services.runtime_files.media_probe import (
    MediaProbeError,
    MediaProbeUnavailable,
    probe_media,
)

from .codec import build_source_intelligence_index

_SAFE_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,16}$")
_MODALITIES = ("visual", "asr", "ocr", "audio")


class SourceAnalyzerConfigurationError(RuntimeError):
    """The real provider cannot run with the current model/tool config."""


@dataclass(frozen=True, slots=True)
class SourceAgentToolContext:
    """Runtime-owned identity for one outer-VLM Source tool call."""

    specialist_run_id: str
    tool_call_id: str
    assistant_message_id: str
    provider_message_id: str | None
    provider: str
    model: str


class StaleSourceAnalysis(RuntimeError):
    """The frozen Project input head changed before provider publication."""


class CancelledSourceAnalysis(RuntimeError):
    """The Task was cancelled while Runtime was entering publication."""


@dataclass(frozen=True, slots=True)
class SourceMediaAnalysisInput:
    project_id: str
    source_id: str
    logical_asset_id: str
    source_version: SourceAssetVersion
    indexed_file: IndexedFile | None
    local_path: Path | None
    evidence_ref: str
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class SourceAnalyzerOutput:
    raw: Mapping[str, Any]
    media: SourceMediaMetadata
    model_runs: tuple[SourceModelRunRef, ...]
    coverage_policy: Mapping[str, Mapping[str, Any]]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_runs:
            raise ValueError(
                "Source analyzer output requires at least one real model run",
            )
        if set(self.coverage_policy) != set(_MODALITIES):
            raise ValueError(
                "coverage_policy must contain visual/asr/ocr/audio",
            )
        if not self.provenance_refs:
            raise ValueError(
                "Source analyzer output requires Runtime provenance",
            )


class SourceMediaAnalyzer(Protocol):
    async def analyze(
        self,
        request: SourceMediaAnalysisInput,
    ) -> SourceAnalyzerOutput:
        """Analyze one verified immutable SourceAssetVersion."""


@dataclass(frozen=True, slots=True)
class SourceAnalysisJob:
    project_id: str
    command_id: str
    round_id: str
    run_id: str
    task_id: str
    attempt_id: str
    intelligence_version_id: str
    intelligence_file_id: str
    commit_id: str
    source_id: str
    source_version: SourceAssetVersion
    indexed_file: IndexedFile | None
    input_generation: int
    input_etag: str
    request_fingerprint: str

    @property
    def intelligence_ref(self) -> str:
        return (
            f"analysis://{self.source_version.version_id}"
            f"@{self.intelligence_version_id}"
        )


@dataclass(frozen=True, slots=True)
class SourceAnalysisDispatch:
    job: SourceAnalysisJob
    run: SpecialistRunRecord
    task: TaskRecord


def _stable_id(prefix: str, project_id: str, command_id: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:source-analysis:{prefix}:{project_id}:{command_id}",
    ).hex
    return f"{prefix}-{digest}"


def _error_payload(
    error: BaseException,
    *,
    code: str | None = None,
) -> dict[str, Any]:
    message = str(error).strip() or type(error).__name__
    return {
        "code": code or type(error).__name__.upper(),
        "message": message[:2000],
        "retryable": False,
    }


def _require_real_directory(path: Path, *, label: str) -> Path:
    """Reject missing, non-directory and symlinked Runtime path components."""

    try:
        value = path.lstat()
    except FileNotFoundError as error:
        raise StorageIntegrityError(f"{label} 不存在") from error
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise StorageIntegrityError(f"{label} 必须是真实的非 symlink 目录")
    return path


def _ensure_real_child(parent: Path, name: str, *, label: str) -> Path:
    """Create one directory component without following a pre-existing link."""

    _require_real_directory(parent, label=f"{label} parent")
    child = parent / name
    try:
        child.mkdir(mode=0o700)
    except FileExistsError:
        pass
    return _require_real_directory(child, label=label)


async def _thread_boundary(function: Any, *args: Any) -> Any:
    """Let a filesystem critical section finish before propagating cancellation."""

    pending = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        try:
            await pending
        except BaseException:
            pass
        raise


def _probe_media(
    path: Path,
    version: SourceAssetVersion,
) -> SourceMediaMetadata:
    if version.media_kind in {"document", "text"}:
        # Documents and text files carry no probeable AV streams; ffprobe
        # would reject them before read_document ever runs. Page facts
        # arrive later from the document reader module result. Legacy
        # "text" sources with a readable extension analyze as documents.
        readable = version.media_kind == "document" or is_supported_document(
            version.name or "",
        )
        return SourceMediaMetadata(
            mediaKind="document" if readable else "other",
            mediaType=version.media_type,
        )
    try:
        probe = probe_media(os.fspath(path))
    except MediaProbeUnavailable as error:
        raise SourceAnalyzerConfigurationError(
            "视频处理工具 ffprobe/ffmpeg 未就绪，暂时无法完成该视频。",
        ) from error
    except MediaProbeError as error:
        raise RuntimeError(
            f"media probe failed for Source media: {error}",
        ) from error
    media_kind = version.media_kind
    if media_kind not in {"image", "video", "audio", "document", "other"}:
        media_kind = "other"
    return SourceMediaMetadata(
        mediaKind=media_kind,
        mediaType=version.media_type,
        durationMs=(
            max(0, round(probe.duration_seconds * 1000))
            if probe.duration_seconds is not None
            else None
        ),
        width=probe.width,
        height=probe.height,
        sampleRateHz=probe.sample_rate_hz,
        channels=probe.channels,
    )


def _source_module_result_ref(
    context: SourceAgentToolContext,
    kind: str,
) -> str:
    identity = uuid5(
        NAMESPACE_URL,
        (
            "qwenpaw-creator:source-module-result:"
            f"{context.specialist_run_id}:{context.tool_call_id}:{kind}"
        ),
    ).hex
    return f"source-module-result:{identity}"


# One pseudo-page occupies this many milliseconds on the document timeline:
# page N maps to the half-open range [(N-1)*1000, N*1000).
DOCUMENT_PAGE_INTERVAL_MS = 1000


def document_page_ref(source_checksum: str, page: int) -> str:
    """Stable evidence ref for one rendered document page image."""
    return f"doc-page://{source_checksum}/{page:04d}"


def document_pages_dir(project_root: Path, source_checksum: str) -> Path:
    return project_root / "runtime" / "doc-pages" / source_checksum[:16]


def document_page_path(
    project_root: Path,
    source_checksum: str,
    page: int,
) -> Path:
    return (
        document_pages_dir(
            project_root,
            source_checksum,
        )
        / f"page-{page:04d}.png"
    )


def resolve_document_page_ref(
    project_root: Path,
    ref: str,
) -> tuple[str, int, Path] | None:
    """Parse a doc-page:// evidence ref into (checksum, page, local path)."""
    text = str(ref or "").strip()
    if not text.startswith("doc-page://"):
        return None
    remainder = text.removeprefix("doc-page://")
    checksum, _, page_text = remainder.partition("/")
    if not checksum or not page_text.isdigit():
        return None
    page = int(page_text)
    return checksum, page, document_page_path(project_root, checksum, page)


# Deterministic document-text semantic entries are bounded per chunk so the
# canonical index stays line-oriented and retrievable.
DOCUMENT_TEXT_CHUNK_CHARS = 2000


def document_indexed_text_path(
    project_root: Path,
    source_checksum: str,
    result_ref: str,
) -> Path:
    """Runtime file holding the full extracted text of one read_document."""
    identity = uuid5(NAMESPACE_URL, result_ref).hex[:16]
    return (
        document_pages_dir(project_root, source_checksum)
        / f"text-{identity}.txt"
    )


def _document_text_chunks(text: str) -> list[str]:
    """Split extracted document text into bounded, paragraph-aligned chunks."""
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= DOCUMENT_TEXT_CHUNK_CHARS:
            current = candidate
            continue
        if current.strip():
            chunks.append(current.strip())
        while len(paragraph) > DOCUMENT_TEXT_CHUNK_CHARS:
            chunks.append(paragraph[:DOCUMENT_TEXT_CHUNK_CHARS].strip())
            paragraph = paragraph[DOCUMENT_TEXT_CHUNK_CHARS:]
        current = paragraph
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def _covered_ratio(
    intervals: list[tuple[int, int]],
    duration_ms: int,
) -> float:
    if duration_ms <= 0 or not intervals:
        return 0.0
    ordered = sorted(intervals)
    covered = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        covered += current_end - current_start
        current_start, current_end = start, end
    covered += current_end - current_start
    return min(1.0, covered / duration_ms)


class DefaultSourceMediaAnalyzer:
    """Deprecated compatibility boundary; visual understanding belongs to the outer VLM."""

    async def analyze(
        self,
        request: SourceMediaAnalysisInput,
    ) -> SourceAnalyzerOutput:
        del request
        raise SourceAnalyzerConfigurationError(
            "Direct inner Source VLM analysis has been removed; the outer Source "
            "Intelligence VLM must call commit_source_intelligence",
        )


class SourceMediaAnalysisService:
    def __init__(
        self,
        services: CreatorFileServices,
        *,
        analyzer: SourceMediaAnalyzer | None = None,
    ) -> None:
        self.services = services
        self.analyzer = analyzer or DefaultSourceMediaAnalyzer()
        self.executions = ProjectExecutionStore(services.root)
        self._jobs: dict[str, asyncio.Task[TaskRecord]] = {}

    def _resolve_agent_source_sync(
        self,
        project_id: str,
        target_ref: str,
    ) -> tuple[
        Any,
        ProjectSource,
        SourceAssetVersion,
        IndexedFile | None,
        Path | None,
        str | None,
        SourceMediaMetadata,
    ]:
        snapshot = self.services.projects.read(project_id)
        source = self._resolve_source(snapshot.project, target_ref, {})
        version = snapshot.project.assets.source_versions_by_id.get(
            source.selected_asset_version_id,
        )
        if version is None:
            raise StorageIntegrityError(
                "ProjectSource selected AssetVersion 不存在",
            )
        indexed = (
            snapshot.project.assets.files_by_id.get(version.file_id)
            if version.file_id is not None
            else None
        )
        source_url = public_source_url(version)
        local_path: Path | None = None
        if indexed is not None:
            if (
                indexed.kind != "source_original"
                or indexed.sha256 != version.checksum
                or indexed.media_type != version.media_type
            ):
                raise StorageIntegrityError(
                    "SourceAssetVersion 与 IndexedFile 内容身份不一致",
                )
            file_store = AssetFileStore(
                self.services.projects.project_root(project_id),
            )
            inspection = file_store.inspect(indexed)
            if not inspection.available:
                raise StorageIntegrityError(
                    f"Source IndexedFile 不可用: {inspection.status.value}",
                )
            local_path = Path(file_store.project_root, indexed.relative_uri)
            media = _probe_media(local_path, version)
        elif source_url is not None:
            cache = resolve_remote_cache(
                self.services.projects.project_root(project_id),
                version,
                self.executions.list_tasks(project_id),
            )
            if cache is not None:
                local_path = cache.path
                media = _probe_media(local_path, version)
            else:
                media = SourceMediaMetadata(
                    mediaKind=version.media_kind,
                    mediaType=version.media_type,
                    durationMs=(
                        round(version.duration_seconds * 1000)
                        if version.duration_seconds is not None
                        else None
                    ),
                )
        else:
            raise StorageIntegrityError(
                "SourceAssetVersion 缺少本地文件与公网 URL",
            )
        return (
            snapshot,
            source,
            version,
            indexed,
            local_path,
            source_url,
            media,
        )

    async def transcribe_source_audio(
        self,
        *,
        project_id: str,
        target_ref: str,
        context: SourceAgentToolContext,
    ) -> dict[str, Any]:
        (
            _snapshot,
            _source,
            version,
            _indexed,
            local_path,
            source_url,
            media,
        ) = await asyncio.to_thread(
            self._resolve_agent_source_sync,
            project_id,
            target_ref,
        )
        if version.media_kind not in {"video", "audio"}:
            raise ValidationError("ASR 工具只适用于视频或音频 Source")
        result_ref = _source_module_result_ref(context, "asr")
        if not model_config.get_asr_api_key():
            return {
                "ok": True,
                "module": "asr",
                "resultRef": result_ref,
                "available": False,
                "reason": "Creator ASR 未配置",
                "sourceAssetVersionId": version.version_id,
                "sourceChecksum": version.checksum,
                "transcript": [],
            }
        media_uri = (
            local_path.as_uri()
            if local_path is not None
            else str(source_url or "")
        )
        result = await asr_model.transcribe(media_uri)
        model_run_id = f"asr-{uuid5(NAMESPACE_URL, result_ref).hex}"
        transcript: list[dict[str, Any]] = []
        for segment in result.segments:
            end_ms = segment.end_ms
            if media.duration_ms is not None:
                end_ms = min(end_ms, media.duration_ms)
            if end_ms <= segment.start_ms:
                continue
            transcript.append(
                {
                    "startMs": segment.start_ms,
                    "endMs": end_ms,
                    "text": segment.text,
                    "speaker": segment.speaker,
                    "confidence": segment.confidence,
                },
            )
        return {
            "ok": True,
            "module": "asr",
            "resultRef": result_ref,
            "available": True,
            "sourceAssetVersionId": version.version_id,
            "sourceChecksum": version.checksum,
            "modelRun": {
                "id": model_run_id,
                "provider": result.provider,
                "model": result.model,
            },
            "transcript": transcript,
        }

    async def read_source_document(
        self,
        *,
        project_id: str,
        target_ref: str,
        arguments: Mapping[str, Any],
        context: SourceAgentToolContext,
    ) -> dict[str, Any]:
        """Render the admitted document Source into page images + text."""

        file_ref = str(arguments.get("fileRef") or "").strip()
        pages = arguments.get("pages")
        pages = str(pages).strip() if pages is not None else None
        budget = str(arguments.get("budget") or "normal")
        if budget not in {"small", "normal", "large"}:
            raise ValidationError(
                "read_document budget 必须是 small/normal/large",
            )
        (
            _snapshot,
            _source,
            version,
            _indexed,
            local_path,
            _source_url,
            _media,
        ) = await asyncio.to_thread(
            self._resolve_agent_source_sync,
            project_id,
            target_ref,
        )
        if version.media_kind not in {"document", "text"}:
            raise ValidationError(
                "read_document 只适用于文档/文本 Source，当前类型为 "
                f"{version.media_kind}",
            )
        expected_ref = f"asset-version:{version.version_id}"
        if file_ref != expected_ref:
            raise ValidationError(
                "fileRef 超出本 Run 准入边界：必须逐字使用当前 Source 选中的 " f"{expected_ref}",
            )
        if local_path is None:
            raise ValidationError(
                "文档尚未缓存到本地，无法渲染页图；请等待缓存任务完成后重试",
            )
        if not is_supported_document(version.name or local_path.name):
            raise ValidationError(
                f"不支持的文档格式: {version.name or local_path.name}",
            )
        result_ref = _source_module_result_ref(context, "document")
        project_root = self.services.projects.project_root(project_id)
        output_dir = document_pages_dir(project_root, version.checksum)
        source_path = local_path
        suffix = Path(version.name or "").suffix
        if suffix and source_path.suffix.lower() != suffix.lower():
            # Renderer dispatch is extension-based; give cached blobs their
            # declared extension via a hard link/copy next to the pages.
            output_dir.mkdir(parents=True, exist_ok=True)
            aliased = output_dir / f"source{suffix.lower()}"
            if not aliased.exists():
                shutil.copyfile(source_path, aliased)
            source_path = aliased
        rendered = await read_document(
            source_path,
            output_dir=output_dir,
            pages=pages,
            budget=budget,  # type: ignore[arg-type]
        )
        page_refs = [
            document_page_ref(version.checksum, page)
            for page in rendered.pages_rendered
        ]
        # Persist the bounded indexed text as a Runtime file: the excerpt
        # below is for model context only, while commit chunks this file
        # into the semantic index (coverage reflects any truncation).
        indexed_text_path = document_indexed_text_path(
            project_root,
            version.checksum,
            result_ref,
        )
        indexed_text_path.parent.mkdir(parents=True, exist_ok=True)
        # Byte-level write: text-mode IO would translate newlines and break
        # the sha256 integrity contract for sources containing \r.
        await asyncio.to_thread(
            indexed_text_path.write_bytes,
            rendered.indexed_text.encode("utf-8"),
        )
        return {
            "ok": True,
            "module": "document",
            "resultRef": result_ref,
            "sourceAssetVersionId": version.version_id,
            "sourceChecksum": version.checksum,
            "format": rendered.format,
            "pageCount": rendered.page_count,
            "pagesRendered": list(rendered.pages_rendered),
            "pageImageRefs": page_refs,
            "textExcerpt": rendered.text_excerpt,
            "textCoverage": {
                "indexedChars": len(rendered.indexed_text),
                "extractedChars": rendered.extracted_chars,
                "extractionComplete": rendered.extraction_complete,
                "extractionFraction": rendered.extraction_fraction,
                "sha256": sha256(
                    rendered.indexed_text.encode("utf-8"),
                ).hexdigest(),
            },
            "notes": list(rendered.notes),
        }

    def _module_result_sync(
        self,
        *,
        project_id: str,
        context: SourceAgentToolContext,
        result_ref: str,
        tool_name: str,
    ) -> Mapping[str, Any]:
        for message in reversed(
            self.executions.list_specialist_messages(
                project_id,
                context.specialist_run_id,
            ),
        ):
            if (
                message.role != "tool"
                or message.metadata.get("tool") != tool_name
            ):
                continue
            for content_part in message.content_parts:
                if not isinstance(content_part, Mapping):
                    continue
                text = content_part.get("text")
                if not isinstance(text, str):
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(value, Mapping)
                    and value.get("resultRef") == result_ref
                ):
                    return value
        raise ValidationError(
            f"素材理解模块结果不存在或不属于当前 SpecialistRun: {result_ref}",
        )

    @staticmethod
    def _assert_agent_ranges(
        payload: SourceAgentIntelligenceInput,
        media: SourceMediaMetadata,
    ) -> float | None:
        kind = media.media_kind
        duration_ms = media.duration_ms
        if kind == "video":
            if duration_ms is None or duration_ms <= 0:
                raise ValidationError("视频素材理解需要可验证的媒体时长")
            if not payload.shots:
                raise ValidationError("视频素材理解必须包含详尽 shots 时间线")
            if not payload.semantic_entries:
                raise ValidationError(
                    "视频素材理解必须包含带时间范围的 semanticEntries",
                )
        elif kind == "document":
            # Page-analog shots are validated against the read_document
            # module result inside commit_agent_intelligence.
            if not payload.shots:
                raise ValidationError(
                    "文档素材理解必须提交页伪时间线 shots：有页图时每渲染页"
                    "一条，无页图的文本型文档恰好一条 [0,1000)",
                )
        elif payload.shots:
            raise ValidationError("非视频素材不得提交 shots 时间线")

        def assert_range(start: int, end: int, label: str) -> None:
            del start
            if duration_ms is not None and end > duration_ms:
                raise ValidationError(
                    f"{label} 时间范围超过素材时长: {end}>{duration_ms}",
                )

        for number, shot in enumerate(payload.shots, 1):
            assert_range(shot.start_ms, shot.end_ms, f"shots[{number}]")
        for number, entity in enumerate(payload.entities, 1):
            if entity.start_ms is not None:
                assert_range(
                    entity.start_ms,
                    entity.end_ms,
                    f"entities[{number}]",
                )
        for number, item in enumerate(payload.semantic_entries, 1):
            if kind in {"video", "audio"} and item.start_ms is None:
                raise ValidationError(
                    f"semanticEntries[{number}] 缺少 startMs/endMs",
                )
            if kind in {"image", "document"} and item.start_ms is not None:
                raise ValidationError(
                    f"{'图片' if kind == 'image' else '文档'} "
                    f"semanticEntries[{number}] 不得包含时间范围",
                )
            if item.start_ms is not None:
                assert_range(
                    item.start_ms,
                    item.end_ms,
                    f"semanticEntries[{number}]",
                )
        if kind != "video":
            return None
        ratio = _covered_ratio(
            [(item.start_ms, item.end_ms) for item in payload.shots],
            duration_ms,
        )
        if ratio < 0.9:
            covered_ms = round(ratio * duration_ms)
            required_ms = math.ceil(duration_ms * 0.9)
            raise ValidationError(
                "视频 shots 时间线覆盖不足 90%: "
                f"素材实际时长 {duration_ms}ms，当前覆盖约 "
                f"{covered_ms}ms ({ratio:.1%})，至少需覆盖 "
                f"{required_ms}ms。请按实际时长补齐开头、过渡、"
                "静止/黑屏和结尾，不得根据文件大小猜测时长。",
            )
        if duration_ms >= 600_000:
            minimum_precise_semantics = min(
                12,
                max(4, math.ceil(duration_ms / 600_000)),
            )
            precise_semantics = sum(
                1
                for item in payload.semantic_entries
                if item.start_ms is not None
                and item.end_ms - item.start_ms <= 30_000
            )
            if precise_semantics < minimum_precise_semantics:
                raise ValidationError(
                    "长视频素材理解缺少可剪辑的精确事件时间段："
                    f"至少需要 {minimum_precise_semantics} 条不超过 30000ms 的 "
                    f"semanticEntries，当前仅 {precise_semantics} 条",
                )
        return ratio

    async def commit_agent_intelligence(
        self,
        *,
        project_id: str,
        target_ref: str,
        command_id: str,
        arguments: Mapping[str, Any],
        context: SourceAgentToolContext,
    ) -> dict[str, Any]:
        try:
            agent_payload = SourceAgentIntelligenceInput.model_validate(
                dict(arguments),
            )
        except ValueError as error:
            raise ValidationError(
                f"外层 VLM 素材理解结构不合法: {error}",
            ) from error
        (
            snapshot,
            source,
            version,
            indexed,
            local_path,
            _source_url,
            media,
        ) = await asyncio.to_thread(
            self._resolve_agent_source_sync,
            project_id,
            target_ref,
        )
        visual_ratio = self._assert_agent_ranges(agent_payload, media)
        evidence_ref = (
            f"asset://{version.logical_asset_id}@{version.version_id}"
        )
        identity = (
            context.provider_message_id
            or context.assistant_message_id
            or context.tool_call_id
        )
        visual_run = SourceModelRunRef(
            id=f"vlm-{uuid5(NAMESPACE_URL, f'{context.specialist_run_id}:{identity}').hex}",
            provider=context.provider,
            model=context.model,
        )
        additional_runs: list[SourceModelRunRef] = []
        transcript: list[dict[str, Any]] = []
        asr_available = False
        asr_ref = agent_payload.module_result_refs.asr
        if asr_ref:
            module = await asyncio.to_thread(
                self._module_result_sync,
                project_id=project_id,
                context=context,
                result_ref=asr_ref,
                tool_name="transcribe_source_audio",
            )
            if (
                module.get("sourceAssetVersionId") != version.version_id
                or module.get("sourceChecksum") != version.checksum
            ):
                raise ValidationError("ASR 结果不属于当前 SourceAssetVersion")
            asr_available = module.get("available") is True
            model_run = module.get("modelRun")
            if asr_available:
                try:
                    asr_run = SourceModelRunRef.model_validate(model_run)
                except ValueError as error:
                    raise ValidationError(
                        f"ASR modelRun 不合法: {error}",
                    ) from error
                additional_runs.append(asr_run)
                for number, raw_item in enumerate(
                    module.get("transcript") or (),
                    1,
                ):
                    if not isinstance(raw_item, Mapping):
                        raise ValidationError("ASR transcript 必须是 object 数组")
                    item = dict(raw_item)
                    item.update(
                        {
                            "id": f"transcript-{number:06d}",
                            "modelRunId": asr_run.id,
                            "evidenceFrameRefs": [evidence_ref],
                        },
                    )
                    transcript.append(item)

        visual_available = media.media_kind in {"image", "video", "document"}
        asr_applicable = media.media_kind in {"video", "audio"}

        is_document = media.media_kind == "document"
        document_page_refs: list[str] = []
        document_ratio: float | None = None
        document_run: SourceModelRunRef | None = None
        document_indexed_text = ""
        document_text_available = False
        document_text_ratio: float | None = None
        document_ref = agent_payload.module_result_refs.document
        if is_document:
            if not document_ref:
                raise ValidationError(
                    "文档素材理解必须先调用 read_document，并在 "
                    "moduleResultRefs.document 引用其 resultRef",
                )
            module = await asyncio.to_thread(
                self._module_result_sync,
                project_id=project_id,
                context=context,
                result_ref=document_ref,
                tool_name="read_document",
            )
            if (
                module.get("sourceAssetVersionId") != version.version_id
                or module.get("sourceChecksum") != version.checksum
            ):
                raise ValidationError(
                    "read_document 结果不属于当前 SourceAssetVersion",
                )
            try:
                document_pages = [
                    int(item) for item in module.get("pagesRendered") or ()
                ]
                document_page_refs = [
                    str(item) for item in module.get("pageImageRefs") or ()
                ]
                page_count = int(module.get("pageCount") or 0)
                document_format = str(module.get("format") or "")
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    f"read_document 结果结构不合法: {error}",
                ) from error
            if (
                len(document_pages) != len(document_page_refs)
                or page_count < max(1, len(document_pages))
                or not document_format
            ):
                raise ValidationError(
                    "read_document 结果结构不合法，无法产出文档素材理解",
                )
            if document_pages:
                expected_intervals = [
                    (
                        (page - 1) * DOCUMENT_PAGE_INTERVAL_MS,
                        page * DOCUMENT_PAGE_INTERVAL_MS,
                    )
                    for page in document_pages
                ]
                document_ratio = len(document_pages) / page_count
            else:
                # Text-flavored documents (subtitles, plain text, code)
                # render no page images; the whole extracted text maps to a
                # single pseudo-page shot.
                expected_intervals = [(0, DOCUMENT_PAGE_INTERVAL_MS)]
                document_ratio = 1.0
            actual_intervals = [
                (item.start_ms, item.end_ms) for item in agent_payload.shots
            ]
            if actual_intervals != expected_intervals:
                raise ValidationError(
                    "文档 shots 必须使用页伪时间区间 [(页号-1)*1000, 页号*1000)："
                    "有页图时按 pagesRendered 页序每页恰好一条，无页图的文本型文档"
                    f"恰好一条 [0,1000)；期望 {expected_intervals}，"
                    f"实际 {actual_intervals}",
                )
            # Text-extraction coverage is persisted honestly. New-format
            # results must be backed by the intact Runtime text file; the
            # excerpt fallback exists only for legacy results without
            # textCoverage.
            indexed_text_path = document_indexed_text_path(
                self.services.projects.project_root(project_id),
                version.checksum,
                document_ref,
            )
            if "textCoverage" in module:
                # Key present (any value, including null) marks a new-format
                # result, so a null can never be mistaken for a legacy result
                # and skip the integrity check.
                raw_text_coverage = module["textCoverage"]
                # New-format results carry a strict integrity contract: any
                # missing or malformed field rejects the commit instead of
                # silently degrading the checks (fail-closed).
                try:
                    text_coverage = DocumentTextCoverage.model_validate(
                        raw_text_coverage,
                    )
                except ValueError as error:
                    raise ValidationError(
                        f"read_document textCoverage 不合法: {error}",
                    ) from error
                indexed_chars = text_coverage.indexed_chars
                extracted_chars = text_coverage.extracted_chars
                if not indexed_text_path.is_file():
                    raise ValidationError(
                        "文档索引文本的 Runtime 文件缺失，无法提交；请重新调用 "
                        "read_document 后再提交",
                    )
                # Byte-level read: read_text() applies universal-newline
                # translation (\r\n/\r -> \n), which changes both length and
                # sha256 for documents whose text layer contains \r and made
                # this integrity check reject every commit.
                document_indexed_text_bytes = await asyncio.to_thread(
                    indexed_text_path.read_bytes,
                )
                document_indexed_text = document_indexed_text_bytes.decode(
                    "utf-8",
                )
                actual_sha = sha256(document_indexed_text_bytes).hexdigest()
                if (
                    len(document_indexed_text) != indexed_chars
                    or actual_sha != text_coverage.sha256
                ):
                    raise ValidationError(
                        "文档索引文本与 read_document 的 textCoverage 不一致"
                        "（Runtime 文件被修改或截断）；请重新调用 "
                        "read_document 后再提交",
                    )
                # Conservative merge of both truncation stages: character
                # indexing bound x renderer extraction share. An unknowable
                # extraction total yields an honest unknown ratio.
                char_ratio = (
                    min(1.0, indexed_chars / extracted_chars)
                    if extracted_chars > 0
                    else None
                )
                if text_coverage.extraction_complete:
                    document_text_ratio = char_ratio
                else:
                    fraction = text_coverage.extraction_fraction
                    document_text_ratio = (
                        min(1.0, char_ratio * fraction)
                        if char_ratio is not None and fraction is not None
                        else None
                    )
            else:
                if indexed_text_path.is_file():
                    document_indexed_text = (
                        await asyncio.to_thread(
                            indexed_text_path.read_bytes,
                        )
                    ).decode("utf-8")
                else:
                    document_indexed_text = str(
                        module.get("textExcerpt") or "",
                    )
                if document_indexed_text:
                    document_text_ratio = 1.0
            document_text_available = bool(document_indexed_text)
            document_run = SourceModelRunRef(
                id=f"docreader-{uuid5(NAMESPACE_URL, document_ref).hex}",
                provider="document_reader",
                model=document_format,
            )
            additional_runs.append(document_run)
            media = media.model_copy(
                update={
                    "document": DocumentMetadata.model_validate(
                        {
                            "format": document_format,
                            "pageCount": page_count,
                        },
                    ),
                },
            )
        elif document_ref:
            raise ValidationError(
                "moduleResultRefs.document 只适用于文档 Source",
            )

        coverage = {
            "visual": {
                "mode": "available" if visual_available else "not_applicable",
                "producer": (
                    "document_reader"
                    if is_document
                    else "model_native"
                    if visual_available
                    else None
                ),
                "ratio": (
                    document_ratio
                    if is_document
                    else visual_ratio
                    if media.media_kind == "video"
                    else 1.0
                    if media.media_kind == "image"
                    else None
                ),
            },
            "asr": {
                "mode": (
                    "available"
                    if asr_available
                    else "unavailable"
                    if asr_applicable
                    else "not_applicable"
                ),
                "producer": "model_native" if asr_available else None,
                "ratio": 1.0 if asr_available else None,
            },
            "ocr": {
                "mode": (
                    "available"
                    if is_document and document_text_available
                    else "unavailable"
                    if visual_available
                    else "not_applicable"
                ),
                "producer": (
                    "document_reader"
                    if is_document and document_text_available
                    else None
                ),
                # None with mode=available means the coverage share is
                # honestly unknown (renderer cap with unknowable total).
                "ratio": (
                    document_text_ratio
                    if is_document and document_text_available
                    else None
                ),
            },
            "audio": {
                "mode": "unavailable" if asr_applicable else "not_applicable",
                "producer": None,
                "ratio": None,
            },
        }
        shots = [
            {
                "id": f"shot-{number:06d}",
                "startMs": item.start_ms,
                "endMs": item.end_ms,
                "description": item.description.strip(),
                "events": [value.strip() for value in item.events],
                "keyframeRef": (
                    document_page_refs[number - 1]
                    if is_document and document_page_refs
                    else evidence_ref
                ),
                "confidence": item.confidence,
                "modelRunId": visual_run.id,
                "evidenceFrameRefs": [
                    (
                        document_page_refs[number - 1]
                        if is_document and document_page_refs
                        else evidence_ref
                    ),
                ],
            }
            for number, item in enumerate(agent_payload.shots, 1)
        ]
        entities = [
            {
                "id": f"entity-{number:06d}",
                "kind": item.kind.strip(),
                "label": item.label.strip(),
                "description": item.description.strip(),
                **(
                    {"startMs": item.start_ms, "endMs": item.end_ms}
                    if item.start_ms is not None
                    else {}
                ),
                "confidence": item.confidence,
                "modelRunId": visual_run.id,
                "evidenceFrameRefs": [evidence_ref],
            }
            for number, item in enumerate(agent_payload.entities, 1)
        ]
        semantic = [
            {
                "id": f"semantic-{number:06d}",
                "text": item.text.strip(),
                "tags": [value.strip() for value in item.tags],
                **(
                    {"startMs": item.start_ms, "endMs": item.end_ms}
                    if item.start_ms is not None
                    else {}
                ),
                "confidence": item.confidence,
                "modelRunId": visual_run.id,
                "evidenceFrameRefs": [evidence_ref],
            }
            for number, item in enumerate(agent_payload.semantic_entries, 1)
        ]
        if document_run is not None:
            # The extracted document text enters the index deterministically:
            # retrieval must not depend on the model re-typing the content.
            offset = len(semantic)
            semantic.extend(
                {
                    "id": f"semantic-{offset + number:06d}",
                    "text": chunk,
                    "tags": ["document-text", f"chunk-{number}"],
                    "confidence": 1.0,
                    "modelRunId": document_run.id,
                    "evidenceFrameRefs": [evidence_ref],
                }
                for number, chunk in enumerate(
                    _document_text_chunks(document_indexed_text),
                    1,
                )
            )
        raw = {
            "summary": agent_payload.summary.strip(),
            "coverage": coverage,
            "shots": shots,
            "transcript": transcript,
            "words": [],
            "ocrSegments": [],
            "audioEvents": [],
            "entities": entities,
            "semanticEntries": semantic,
        }
        created_at = datetime.now(UTC)
        intelligence_version_id = _stable_id(
            "source-intelligence",
            project_id,
            command_id,
        )
        index = build_source_intelligence_index(
            raw,
            analysis_version_id=intelligence_version_id,
            asset_id=version.logical_asset_id,
            asset_version_id=version.version_id,
            source_checksum=version.checksum,
            model_run=visual_run,
            additional_model_runs=additional_runs,
            created_at=created_at.isoformat().replace("+00:00", "Z"),
            media=media,
            coverage_policy=coverage,
            provenance_refs=(evidence_ref, *document_page_refs),
        )
        job = SourceAnalysisJob(
            project_id=project_id,
            command_id=command_id,
            round_id=context.specialist_run_id,
            run_id=context.specialist_run_id,
            task_id=_stable_id("source-agent-commit", project_id, command_id),
            attempt_id=_stable_id(
                "source-agent-attempt",
                project_id,
                command_id,
            ),
            intelligence_version_id=intelligence_version_id,
            intelligence_file_id=_stable_id(
                "source-intelligence-file",
                project_id,
                command_id,
            ),
            commit_id=_stable_id("source-commit", project_id, command_id),
            source_id=source.source_id,
            source_version=version,
            indexed_file=indexed,
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            request_fingerprint=sha256(
                canonical_json_bytes(dict(arguments)),
            ).hexdigest(),
        )
        published = await _thread_boundary(
            self._publish_and_commit_sync,
            job,
            index,
            created_at,
            False,
        )
        memory_build = await self._schedule_memory_build(
            project_id=project_id,
            index=index,
            local_path=local_path,
            command_id=command_id,
        )
        return {
            "ok": True,
            "status": "SUCCEEDED",
            "summary": index.summary,
            "shotCount": len(index.shots),
            "semanticEntryCount": len(index.semantic_entries),
            **({"memoryBuild": memory_build} if memory_build else {}),
            **published,
        }

    async def _schedule_memory_build(
        self,
        *,
        project_id: str,
        index: SourceIntelligenceIndex,
        local_path: Path | None,
        command_id: str,
    ) -> dict[str, Any] | None:
        """Queue the long-source memory build; never blocks the index."""

        from services.media.source_memory import source_memory_service

        try:
            return await source_memory_service(
                self.services,
            ).maybe_schedule_build(
                project_id=project_id,
                index=index,
                local_path=local_path,
                caused_by_request_id=command_id,
            )
        except Exception as error:  # pylint: disable=broad-except
            import logging

            logging.getLogger("creator.source_memory").warning(
                "memory build scheduling failed (non-fatal): %s",
                error,
            )
            return None

    async def dispatch(
        self,
        *,
        project_id: str,
        target_ref: str,
        command_id: str,
        arguments: Mapping[str, Any] | None = None,
        start: bool = True,
    ) -> SourceAnalysisDispatch:
        dispatch = await asyncio.to_thread(
            self._prepare_sync,
            project_id,
            target_ref,
            command_id,
            dict(arguments or {}),
        )
        if start and dispatch.task.status is TaskStatus.QUEUED:
            self.start(dispatch.job)
        return dispatch

    def start(self, job: SourceAnalysisJob) -> asyncio.Task[TaskRecord] | None:
        current = self._jobs.get(job.task_id)
        if current is not None and not current.done():
            return current
        if (
            self.executions.get_task(job.project_id, job.task_id).status
            is not TaskStatus.QUEUED
        ):
            return None
        task = asyncio.create_task(
            self.execute(job),
            name=f"source-analysis:{job.task_id}",
        )
        self._jobs[job.task_id] = task

        def discard(done: asyncio.Task[TaskRecord]) -> None:
            if self._jobs.get(job.task_id) is done:
                self._jobs.pop(job.task_id, None)
            if not done.cancelled():
                try:
                    done.exception()
                except BaseException:
                    pass

        task.add_done_callback(discard)
        return task

    async def execute(self, job: SourceAnalysisJob) -> TaskRecord:
        temp_root: Path | None = None
        try:
            run = await asyncio.to_thread(
                self.executions.get_run,
                job.project_id,
                job.run_id,
            )
            task = await asyncio.to_thread(
                self.executions.get_task,
                job.project_id,
                job.task_id,
            )
            if task.status is not TaskStatus.QUEUED:
                return task
            await asyncio.to_thread(
                self.executions.transition_run,
                job.project_id,
                job.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.RUNNING_MODEL,
            )
            await asyncio.to_thread(
                self.executions.append_attempt,
                job.project_id,
                job.task_id,
                event_id=f"{job.attempt_id}-running",
                attempt_id=job.attempt_id,
                status=TaskAttemptStatus.RUNNING,
                input=self._attempt_input(job),
            )
            temp_root, local_path = await _thread_boundary(
                self._materialize_verified_input_sync,
                job,
            )
            provider_input = SourceMediaAnalysisInput(
                project_id=job.project_id,
                source_id=job.source_id,
                logical_asset_id=job.source_version.logical_asset_id,
                source_version=job.source_version,
                indexed_file=job.indexed_file,
                local_path=local_path,
                source_url=public_source_url(job.source_version),
                evidence_ref=(
                    f"asset://{job.source_version.logical_asset_id}"
                    f"@{job.source_version.version_id}"
                ),
            )
            output = await self.analyzer.analyze(provider_input)
            created_at = datetime.now(UTC)
            index = build_source_intelligence_index(
                output.raw,
                analysis_version_id=job.intelligence_version_id,
                asset_id=job.source_version.logical_asset_id,
                asset_version_id=job.source_version.version_id,
                source_checksum=job.source_version.checksum,
                model_run=output.model_runs[0],
                additional_model_runs=output.model_runs[1:],
                created_at=created_at.isoformat().replace("+00:00", "Z"),
                media=output.media,
                coverage_policy=output.coverage_policy,
                provenance_refs=output.provenance_refs,
            )
            provider_result = {
                "analysisVersionId": index.id,
                "index": index.model_dump(mode="json", by_alias=True),
            }
            task = await asyncio.to_thread(
                self.executions.get_task,
                job.project_id,
                job.task_id,
            )
            if task.status is TaskStatus.CANCELLED:
                return await asyncio.to_thread(
                    self._quarantine_cancelled_sync,
                    job,
                    provider_result,
                )
            try:
                await _thread_boundary(
                    self._publish_and_commit_sync,
                    job,
                    index,
                    created_at,
                )
            except CancelledSourceAnalysis:
                return await asyncio.to_thread(
                    self._quarantine_cancelled_sync,
                    job,
                    provider_result,
                )
            except StaleSourceAnalysis as error:
                return await asyncio.to_thread(
                    self._quarantine_stale_sync,
                    job,
                    provider_result,
                    str(error),
                )
            await asyncio.to_thread(
                self.executions.transition_run,
                job.project_id,
                job.run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.SUCCEEDED,
                updates={
                    "final_marker": "SUCCESS",
                    "final_summary_text": index.summary,
                    "metadata": {
                        "sourceId": job.source_id,
                        "analysisVersionId": index.id,
                        "coverage": {
                            key: value.mode
                            for key, value in index.coverage.items()
                        },
                    },
                },
            )
            return await asyncio.to_thread(
                self.executions.get_task,
                job.project_id,
                job.task_id,
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(self._cancel_worker_sync, job)
            raise
        except Exception as error:
            return await asyncio.to_thread(self._fail_sync, job, error)
        finally:
            if temp_root is not None:
                await asyncio.to_thread(shutil.rmtree, temp_root, True)

    def load(
        self,
        project_id: str,
        logical_asset_id: str,
        intelligence_version_id: str | None = None,
    ) -> SourceIntelligenceIndex:
        snapshot = self.services.projects.read(project_id)
        project = snapshot.project
        source = self._source_for_logical_asset(project, logical_asset_id)
        selected_id = (
            intelligence_version_id or source.current_intelligence_version_id
        )
        if selected_id is None:
            raise NotFoundError("该 Asset 尚无 source intelligence 索引")
        record = project.assets.intelligence_versions_by_id.get(selected_id)
        if record is None:
            raise NotFoundError("Source Intelligence version 不存在")
        source_version = project.assets.source_versions_by_id.get(
            record.source_asset_version_id,
        )
        if (
            source_version is None
            or source_version.logical_asset_id != logical_asset_id
        ):
            raise StorageIntegrityError("Source Intelligence 指向了其他 Asset")
        indexed = project.assets.files_by_id.get(record.file_id)
        if indexed is None or indexed.kind != "source_intelligence":
            raise StorageIntegrityError(
                "Source Intelligence IndexedFile 不存在或类型错误",
            )
        try:
            payload = AssetFileStore(
                self.services.projects.project_root(project_id),
            ).read_verified(indexed)
            raw = json.loads(payload.decode("utf-8"))
            index = SourceIntelligenceIndex.model_validate(raw)
        except (
            AssetFileError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            raise StorageIntegrityError(
                f"Source Intelligence 索引损坏: {error}",
            ) from error
        if (
            canonical_json_bytes(
                index.model_dump(mode="json", by_alias=True),
                pretty=True,
            )
            != payload
        ):
            raise StorageIntegrityError(
                "Source Intelligence 索引不是 canonical JSON",
            )
        expected_runs = [item.id for item in index.model_runs]
        expected_coverage = {
            key: value.mode for key, value in index.coverage.items()
        }
        if (
            index.id != record.intelligence_version_id
            or index.asset_id != logical_asset_id
            or index.asset_version_id != source_version.version_id
            or index.source_checksum != source_version.checksum
            or expected_runs != record.model_run_ids
            or expected_coverage != record.coverage
        ):
            raise StorageIntegrityError(
                "Source Intelligence 文件与 project.json 索引不一致",
            )
        # Hydrate the read-only memory pointer AFTER the canonical byte
        # check: memory artifacts live outside the immutable index file and
        # invalidate themselves on sourceChecksum change.
        from services.media.source_memory import (
            load_memory_ref,
            merge_projection_semantics,
        )

        project_root = self.services.projects.project_root(project_id)
        index.memory_ref = load_memory_ref(
            project_root,
            index.id,
            index.source_checksum,
        )
        # Fold the P3 Root/SuperEvent drafts into the semantic surface
        # (producer=source_memory) so downstream consumers review them
        # alongside the outer-VLM entries.
        merge_projection_semantics(project_root, index)
        return index

    def query(
        self,
        project_id: str,
        logical_asset_id: str,
        query: str,
    ) -> SourceIndexQueryResult:
        index = self.load(project_id, logical_asset_id)
        payload = index.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        needle = query.casefold().strip()
        items: list[dict[str, Any]] = []

        def add(kind: str, record: Mapping[str, Any], *values: Any) -> None:
            haystack = " ".join(str(value) for value in values).casefold()
            if not needle or needle in haystack:
                items.append({"kind": kind, "record": dict(record)})

        if not needle or needle in index.summary.casefold():
            items.append(
                {
                    "kind": "summary",
                    "record": {
                        "text": index.summary,
                        "assetVersionId": index.asset_version_id,
                        "sourceChecksum": index.source_checksum,
                    },
                },
            )
        for record in payload["shots"]:
            add("shot", record, record["description"], *record["events"])
        for record in payload["transcript"]:
            add(
                "transcript",
                record,
                record["text"],
                record.get("speaker") or "",
            )
        for record in payload["words"]:
            add("word", record, record["word"])
        for record in payload["ocrSegments"]:
            add("ocr", record, record["text"])
        for record in payload["audioEvents"]:
            add("audio", record, record["label"], record["description"])
        for record in payload["entities"]:
            add(
                "entity",
                record,
                record["kind"],
                record["label"],
                record["description"],
            )
        for record in payload["semanticEntries"]:
            add("semantic", record, record["text"], *record["tags"])
        return SourceIndexQueryResult(index=index, query=query, items=items)

    def _prepare_sync(
        self,
        project_id: str,
        target_ref: str,
        command_id: str,
        arguments: Mapping[str, Any],
    ) -> SourceAnalysisDispatch:
        if not command_id or command_id in {".", ".."}:
            raise ValidationError("ANALYZE_SOURCE_MEDIA command id 不合法")
        snapshot = self.services.projects.read(project_id)
        source = self._resolve_source(snapshot.project, target_ref, arguments)
        version = snapshot.project.assets.source_versions_by_id.get(
            source.selected_asset_version_id,
        )
        if version is None:
            raise StorageIntegrityError(
                "ProjectSource selected AssetVersion 不存在",
            )
        indexed = (
            snapshot.project.assets.files_by_id.get(version.file_id)
            if version.file_id is not None
            else None
        )
        source_url = public_source_url(version)
        if indexed is None and source_url is None:
            raise StorageIntegrityError("SourceAssetVersion 缺少本地文件与公网 URL")
        if indexed is not None:
            if indexed.kind != "source_original":
                raise StorageIntegrityError(
                    "SourceAssetVersion IndexedFile 类型错误",
                )
            if (
                indexed.sha256 != version.checksum
                or indexed.media_type != version.media_type
            ):
                raise StorageIntegrityError(
                    "SourceAssetVersion 与 IndexedFile 内容身份不一致",
                )
        requested_version = arguments.get("assetVersionId") or arguments.get(
            "versionId",
        )
        if (
            requested_version is not None
            and str(requested_version) != version.version_id
        ):
            raise ValidationError("只能分析 ProjectSource 当前选中的 AssetVersion")
        if indexed is not None:
            file_store = AssetFileStore(
                self.services.projects.project_root(project_id),
            )
            inspection = file_store.inspect(indexed)
            if not inspection.available:
                raise StorageIntegrityError(
                    f"Source IndexedFile 不可用: {inspection.status.value}",
                )

        round_id = _stable_id("source-round", project_id, command_id)
        run_id = _stable_id("source-run", project_id, command_id)
        task_id = _stable_id("source-task", project_id, command_id)
        fingerprint_data = {
            "operation": "ANALYZE_SOURCE_MEDIA",
            "projectId": project_id,
            "sourceId": source.source_id,
            "sourceAssetVersionId": version.version_id,
            "fileId": indexed.file_id if indexed is not None else None,
            "checksum": version.checksum,
            "mediaType": version.media_type,
            "sourceUrl": source_url,
        }
        request_fingerprint = sha256(
            canonical_json_bytes(fingerprint_data),
        ).hexdigest()
        existing_run: SpecialistRunRecord | None = None
        existing_task: TaskRecord | None = None
        try:
            existing_run = self.executions.get_run(project_id, run_id)
        except RecordNotFoundError:
            pass
        try:
            existing_task = self.executions.get_task(project_id, task_id)
        except RecordNotFoundError:
            pass
        if existing_run is None and existing_task is not None:
            raise StorageIntegrityError(
                "ANALYZE_SOURCE_MEDIA Task 缺少所属 durable Run",
            )
        if existing_run is not None:
            if (
                existing_run.round_id != round_id
                or existing_run.role is not SpecialistRole.SOURCE_INTELLIGENCE
                or existing_run.request_fingerprint != request_fingerprint
            ):
                raise ConflictError(
                    "ANALYZE_SOURCE_MEDIA command id 已用于不同输入",
                )
            frozen_generation = existing_run.input_generation
            frozen_etag = existing_run.input_etag
            if existing_task is not None:
                if (
                    existing_task.round_id != round_id
                    or existing_task.run_id != run_id
                    or existing_task.kind is not TaskKind.SOURCE_INTELLIGENCE
                    or existing_task.request_fingerprint != request_fingerprint
                    or existing_task.idempotency_key != command_id
                    or existing_task.expected_target_version
                    != version.checksum
                    or existing_task.input_generation != frozen_generation
                    or existing_task.input_etag != frozen_etag
                ):
                    raise ConflictError(
                        "ANALYZE_SOURCE_MEDIA command id 已用于不同输入",
                    )
        else:
            frozen_generation = snapshot.generation
            frozen_etag = snapshot.etag

        job = SourceAnalysisJob(
            project_id=project_id,
            command_id=command_id,
            round_id=round_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=_stable_id("source-attempt", project_id, command_id),
            intelligence_version_id=_stable_id(
                "source-intelligence",
                project_id,
                command_id,
            ),
            intelligence_file_id=_stable_id(
                "source-intelligence-file",
                project_id,
                command_id,
            ),
            commit_id=_stable_id("source-commit", project_id, command_id),
            source_id=source.source_id,
            source_version=version,
            indexed_file=indexed,
            input_generation=frozen_generation,
            input_etag=frozen_etag,
            request_fingerprint=request_fingerprint,
        )
        run_record = SpecialistRunRecord(
            run_id=run_id,
            project_id=project_id,
            round_id=round_id,
            role=SpecialistRole.SOURCE_INTELLIGENCE,
            target_refs=[f"source:{source.source_id}"],
            input_generation=frozen_generation,
            input_etag=frozen_etag,
            request_fingerprint=request_fingerprint,
            caused_by_request_id=command_id,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata={
                "operation": "ANALYZE_SOURCE_MEDIA",
                "sourceId": source.source_id,
                "assetVersionId": version.version_id,
                "fileId": indexed.file_id if indexed is not None else None,
                "sourceUrl": source_url,
            },
        )
        input_refs = [
            f"source:{source.source_id}",
            f"asset://{version.logical_asset_id}@{version.version_id}",
        ]
        read_set: list[dict[str, Any]] = []
        if indexed is not None:
            input_refs.append(f"file:{indexed.file_id}")
            read_set.append(
                {
                    "fileId": indexed.file_id,
                    "sha256": indexed.sha256,
                    "relativeUri": indexed.relative_uri,
                },
            )
        elif source_url is not None:
            input_refs.append(source_url)
        task_record = TaskRecord(
            task_id=task_id,
            project_id=project_id,
            round_id=round_id,
            run_id=run_id,
            kind=TaskKind.SOURCE_INTELLIGENCE,
            request_fingerprint=request_fingerprint,
            idempotency_key=command_id,
            input_generation=frozen_generation,
            input_etag=frozen_etag,
            expected_target_version=version.checksum,
            input_refs=input_refs,
            read_set=read_set,
            caused_by_request_id=command_id,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata={
                "targetRef": f"source:{source.source_id}",
                "sourceId": source.source_id,
                "assetId": version.logical_asset_id,
                "assetVersionId": version.version_id,
            },
        )
        # A process can stop after the Run file is durable but before the Task
        # file is created.  Replaying the same command validates the surviving
        # Run and deterministically fills the missing Task instead of leaving a
        # permanent orphan that would require a database-style repair pass.
        run = existing_run or self.executions.create_run(run_record)
        task = existing_task or self.executions.create_task(task_record)
        return SourceAnalysisDispatch(job=job, run=run, task=task)

    @staticmethod
    def _source_for_logical_asset(
        project: Project,
        logical_asset_id: str,
    ) -> ProjectSource:
        matches = [
            item
            for item in project.sources.sources.items.values()
            if item.logical_asset_id == logical_asset_id
        ]
        if len(matches) != 1:
            raise NotFoundError("Asset 未唯一 attach 到 ProjectSource")
        return matches[0]

    @classmethod
    def _resolve_source(
        cls,
        project: Project,
        target_ref: str,
        arguments: Mapping[str, Any],
    ) -> ProjectSource:
        if target_ref.startswith("source:"):
            source_id = target_ref.removeprefix("source:")
            source = project.sources.sources.items.get(source_id)
            if source is None:
                raise NotFoundError("ProjectSource 不存在")
            return source
        if target_ref.startswith("asset:"):
            return cls._source_for_logical_asset(
                project,
                target_ref.removeprefix("asset:"),
            )
        source_id = arguments.get("sourceId")
        if isinstance(source_id, str) and source_id:
            source = project.sources.sources.items.get(source_id)
            if source is not None:
                return source
        asset_id = arguments.get("assetId")
        if isinstance(asset_id, str) and asset_id:
            return cls._source_for_logical_asset(project, asset_id)
        raise ValidationError(
            "ANALYZE_SOURCE_MEDIA targetRef 必须是 source:<id> 或 asset:<logicalId>",
        )

    def _materialize_verified_input_sync(
        self,
        job: SourceAnalysisJob,
    ) -> tuple[Path | None, Path | None]:
        # Project deletion uses the same lifecycle lock.  Holding it while the
        # verified copy is created prevents an interrupted worker from
        # recreating a deleted Project through ``mkdir(parents=True)``.
        with self.services.projects.lifecycle_lock(job.project_id):
            self.services.projects.read(job.project_id)
            task = self.executions.get_task(
                job.project_id,
                job.task_id,
                _lifecycle_lock_held=True,
            )
            if task.status is TaskStatus.CANCELLED:
                raise CancelledSourceAnalysis(
                    "Task was cancelled before Source input materialization",
                )
            if job.indexed_file is None:
                if public_source_url(job.source_version) is None:
                    raise StorageIntegrityError(
                        "URL-backed SourceAssetVersion lost its public URL",
                    )
                return None, None
            project_root = _require_real_directory(
                self.services.projects.project_root(job.project_id),
                label="Project root",
            )
            runtime_root = _require_real_directory(
                project_root / "runtime",
                label="Project runtime",
            )
            temp_root = _require_real_directory(
                runtime_root / "temp",
                label="Project runtime temp",
            )
            temp_parent = _ensure_real_child(
                temp_root,
                "source-analysis",
                label="Source analysis temp",
            )
            root = Path(
                tempfile.mkdtemp(prefix=f"{job.task_id}.", dir=temp_parent),
            )
            _require_real_directory(root, label="Source analysis task temp")
            suffix = Path(job.source_version.name).suffix.casefold()
            if not _SAFE_SUFFIX.fullmatch(suffix):
                suffix = ".bin"
            target = root / f"source{suffix}"
            file_store = AssetFileStore(project_root)
            descriptor: int | None = None
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(target, flags, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    descriptor = None
                    with file_store.open_verified(job.indexed_file) as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
            except Exception:
                if descriptor is not None:
                    os.close(descriptor)
                shutil.rmtree(root, ignore_errors=True)
                raise
            return root, target

    def _publish_and_commit_sync(
        self,
        job: SourceAnalysisJob,
        index: SourceIntelligenceIndex,
        created_at: datetime,
        task_owned: bool = True,
    ) -> dict[str, Any]:
        project_root = self.services.projects.project_root(job.project_id)
        with self.services.projects.lifecycle_lock(job.project_id):
            if task_owned:
                task = self.executions.get_task(
                    job.project_id,
                    job.task_id,
                    _lifecycle_lock_held=True,
                )
                if task.status is TaskStatus.CANCELLED:
                    raise CancelledSourceAnalysis(
                        "Task was cancelled before Source Intelligence publication",
                    )
            current = self.services.projects.read(job.project_id)
            replay = self._already_published(current.project, job)
            if replay:
                published = {
                    "analysisVersionId": index.id,
                    "sourceId": job.source_id,
                    "sourceAssetVersionId": job.source_version.version_id,
                    "indexRef": job.intelligence_ref,
                    "generation": current.generation,
                    "etag": current.etag,
                    "idempotentReplay": True,
                }
                if task_owned:
                    self._complete_task_sync(job, published)
                return published
            if (
                current.generation != job.input_generation
                or current.etag != job.input_etag
                or not self._same_frozen_source(current.project, job)
            ):
                raise StaleSourceAnalysis(
                    "Project generation/ETag or selected SourceAssetVersion changed",
                )
            payload = canonical_json_bytes(
                index.model_dump(mode="json", by_alias=True),
                pretty=True,
            )
            relative_uri = PurePosixPath(
                "assets",
                "source-intelligence",
                job.source_id,
                f"{job.intelligence_version_id}.json",
            ).as_posix()
            indexed = IndexedFile(
                file_id=job.intelligence_file_id,
                kind="source_intelligence",
                relative_uri=relative_uri,
                sha256=sha256(payload).hexdigest(),
                size_bytes=len(payload),
                media_type="application/json",
                schema_name="qwenpaw.creator.SourceIntelligenceIndex",
                schema_version=1,
                created_at=created_at,
            )
            file_store = AssetFileStore(project_root)
            staged = file_store.stage_bytes(
                payload,
                staging_id=job.intelligence_version_id[:80],
            )
            try:
                file_store.publish(
                    staged,
                    relative_uri,
                    expected_sha256=indexed.sha256,
                    expected_size_bytes=indexed.size_bytes,
                )
            except AssetAlreadyExists:
                file_store.abandon(staged)
                if not file_store.inspect(indexed).available:
                    raise StorageIntegrityError(
                        "Source Intelligence immutable path 已存在但内容不同",
                    )
            candidate = current.project.model_dump(mode="json")
            candidate["assets"]["files_by_id"][
                indexed.file_id
            ] = indexed.model_dump(
                mode="json",
            )
            intelligence = SourceIntelligenceVersion(
                intelligence_version_id=index.id,
                source_asset_version_id=job.source_version.version_id,
                file_id=indexed.file_id,
                source_checksum=job.source_version.checksum,
                model_run_ids=[item.id for item in index.model_runs],
                coverage={
                    key: value.mode for key, value in index.coverage.items()
                },
                created_at=created_at,
            )
            candidate["assets"]["intelligence_versions_by_id"][
                index.id
            ] = intelligence.model_dump(mode="json")
            candidate["sources"]["sources"]["items"][job.source_id][
                "current_intelligence_version_id"
            ] = index.id
            result = self.services.commits.commit(
                base=current,
                candidate=candidate,
                origin=ChangeOrigin.RUNTIME_TASK,
                review_policy=ReviewPolicy.AUTO_FIX,
                caused_by_request_id=job.command_id,
                round_id=job.round_id,
                transaction_id=job.commit_id,
                advance_accepted_baseline=True,
                _lifecycle_lock_held=True,
            )
            self.services.poller.note_commit(result.snapshot)
            published = {
                "analysisVersionId": index.id,
                "sourceId": job.source_id,
                "sourceAssetVersionId": job.source_version.version_id,
                "indexRef": job.intelligence_ref,
                "fileId": indexed.file_id,
                "generation": result.snapshot.generation,
                "etag": result.snapshot.etag,
                "idempotentReplay": False,
            }
            # Cancellation takes the same Project lifecycle lock.  Completing
            # the Task before releasing it makes "committed but cancelled"
            # impossible for the public cancellation boundary.
            if task_owned:
                self._complete_task_sync(job, published)
            return published

    def _complete_task_sync(
        self,
        job: SourceAnalysisJob,
        published: Mapping[str, Any],
    ) -> None:
        task = self.executions.get_task(
            job.project_id,
            job.task_id,
            _lifecycle_lock_held=True,
        )
        if task.status is TaskStatus.SUCCEEDED:
            return
        if task.status is TaskStatus.CANCELLED:
            raise CancelledSourceAnalysis(
                "Task was cancelled before Source Intelligence publication",
            )
        self.executions.append_attempt(
            job.project_id,
            job.task_id,
            event_id=f"{job.attempt_id}-succeeded",
            attempt_id=job.attempt_id,
            status=TaskAttemptStatus.SUCCEEDED,
            output=published,
            output_refs=[job.intelligence_ref],
            _lifecycle_lock_held=True,
        )

    def _converge_published_job_sync(
        self,
        job: SourceAnalysisJob,
    ) -> TaskRecord | None:
        """Finish Runtime state when the exact Project result is already durable.

        Project publication and Runtime completion are two atomic file writes,
        so a process can stop between them.  The immutable indexed result is
        sufficient convergence evidence; provider execution is never replayed.
        """

        with self.services.projects.lifecycle_lock(job.project_id):
            current = self.services.projects.read(job.project_id)
            if not self._already_published(current.project, job):
                return None
            indexed = current.project.assets.files_by_id.get(
                job.intelligence_file_id,
            )
            if indexed is None:
                raise StorageIntegrityError(
                    "Published Source Intelligence 缺少 IndexedFile",
                )
            index = self.load(
                job.project_id,
                job.source_version.logical_asset_id,
                job.intelligence_version_id,
            )
            task = self.executions.get_task(
                job.project_id,
                job.task_id,
                _lifecycle_lock_held=True,
            )
            if task.status not in {TaskStatus.RUNNING, TaskStatus.SUCCEEDED}:
                return None
            published = {
                "analysisVersionId": index.id,
                "sourceId": job.source_id,
                "sourceAssetVersionId": job.source_version.version_id,
                "indexRef": job.intelligence_ref,
                "fileId": indexed.file_id,
                "generation": current.generation,
                "etag": current.etag,
                "idempotentReplay": True,
            }
            self._complete_task_sync(job, published)

        run = self.executions.get_run(job.project_id, job.run_id)
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            self.executions.transition_run(
                job.project_id,
                job.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.SUCCEEDED,
                updates={
                    "final_marker": "SUCCESS",
                    "final_summary_text": index.summary,
                    "metadata": {
                        **run.metadata,
                        "sourceId": job.source_id,
                        "analysisVersionId": index.id,
                        "coverage": {
                            key: value.mode
                            for key, value in index.coverage.items()
                        },
                    },
                },
            )
        return self.executions.get_task(job.project_id, job.task_id)

    def _recovery_job_from_task(
        self,
        task: TaskRecord,
    ) -> SourceAnalysisJob | None:
        """Reconstruct only the deterministic identity needed for convergence."""

        command_id = task.idempotency_key
        source_id = task.metadata.get("sourceId")
        version_id = task.metadata.get("assetVersionId")
        if (
            not isinstance(command_id, str)
            or not command_id
            or not isinstance(source_id, str)
            or not source_id
            or not isinstance(version_id, str)
            or not version_id
            or task.run_id is None
            or task.round_id is None
            or task.input_generation is None
            or task.input_etag is None
        ):
            return None
        expected_round_id = _stable_id(
            "source-round",
            task.project_id,
            command_id,
        )
        expected_run_id = _stable_id("source-run", task.project_id, command_id)
        expected_task_id = _stable_id(
            "source-task",
            task.project_id,
            command_id,
        )
        if (
            task.round_id != expected_round_id
            or task.run_id != expected_run_id
            or task.task_id != expected_task_id
        ):
            return None
        project = self.services.projects.read(task.project_id).project
        source = project.sources.sources.items.get(source_id)
        version = project.assets.source_versions_by_id.get(version_id)
        if (
            source is None
            or version is None
            or source.logical_asset_id != version.logical_asset_id
            or task.expected_target_version != version.checksum
        ):
            return None
        indexed = (
            project.assets.files_by_id.get(version.file_id)
            if version.file_id is not None
            else None
        )
        source_url = public_source_url(version)
        if indexed is None and source_url is None:
            return None
        if indexed is not None and indexed.kind != "source_original":
            return None
        fingerprint = sha256(
            canonical_json_bytes(
                {
                    "operation": "ANALYZE_SOURCE_MEDIA",
                    "projectId": task.project_id,
                    "sourceId": source_id,
                    "sourceAssetVersionId": version.version_id,
                    "fileId": indexed.file_id if indexed is not None else None,
                    "checksum": version.checksum,
                    "mediaType": version.media_type,
                    "sourceUrl": source_url,
                },
            ),
        ).hexdigest()
        if task.request_fingerprint != fingerprint:
            return None
        return SourceAnalysisJob(
            project_id=task.project_id,
            command_id=command_id,
            round_id=expected_round_id,
            run_id=expected_run_id,
            task_id=expected_task_id,
            attempt_id=_stable_id(
                "source-attempt",
                task.project_id,
                command_id,
            ),
            intelligence_version_id=_stable_id(
                "source-intelligence",
                task.project_id,
                command_id,
            ),
            intelligence_file_id=_stable_id(
                "source-intelligence-file",
                task.project_id,
                command_id,
            ),
            commit_id=_stable_id("source-commit", task.project_id, command_id),
            source_id=source_id,
            source_version=version,
            indexed_file=indexed,
            input_generation=task.input_generation,
            input_etag=task.input_etag,
            request_fingerprint=fingerprint,
        )

    @staticmethod
    def _same_frozen_source(project: Project, job: SourceAnalysisJob) -> bool:
        source = project.sources.sources.items.get(job.source_id)
        version = project.assets.source_versions_by_id.get(
            job.source_version.version_id,
        )
        indexed = (
            project.assets.files_by_id.get(job.indexed_file.file_id)
            if job.indexed_file is not None
            else None
        )
        return (
            source is not None
            and source.selected_asset_version_id
            == job.source_version.version_id
            and version == job.source_version
            and indexed == job.indexed_file
        )

    @staticmethod
    def _already_published(project: Project, job: SourceAnalysisJob) -> bool:
        source = project.sources.sources.items.get(job.source_id)
        intelligence = project.assets.intelligence_versions_by_id.get(
            job.intelligence_version_id,
        )
        indexed = project.assets.files_by_id.get(job.intelligence_file_id)
        return bool(
            source is not None
            and source.current_intelligence_version_id
            == job.intelligence_version_id
            and intelligence is not None
            and intelligence.source_asset_version_id
            == job.source_version.version_id
            and intelligence.file_id == job.intelligence_file_id
            and indexed is not None
            and indexed.kind == "source_intelligence",
        )

    @staticmethod
    def _attempt_input(job: SourceAnalysisJob) -> dict[str, Any]:
        return {
            "projectId": job.project_id,
            "sourceId": job.source_id,
            "sourceAssetVersionId": job.source_version.version_id,
            "fileId": (
                job.indexed_file.file_id
                if job.indexed_file is not None
                else None
            ),
            "sourceUrl": public_source_url(job.source_version),
            "sourceChecksum": job.source_version.checksum,
            "inputGeneration": job.input_generation,
            "inputEtag": job.input_etag,
        }

    def _quarantine_stale_sync(
        self,
        job: SourceAnalysisJob,
        result: Mapping[str, Any],
        reason: str,
    ) -> TaskRecord:
        task = self.executions.get_task(job.project_id, job.task_id)
        if task.status is TaskStatus.RUNNING:
            self.executions.append_attempt(
                job.project_id,
                job.task_id,
                event_id=f"{job.attempt_id}-quarantined",
                attempt_id=job.attempt_id,
                status=TaskAttemptStatus.QUARANTINED,
                output=result,
                error={"code": "STALE_INPUT", "message": reason},
            )
        self.executions.quarantine_task_result(
            job.project_id,
            job.task_id,
            quarantine_id=_stable_id(
                "source-quarantine",
                job.project_id,
                job.command_id,
            ),
            reason=reason,
            result=result,
            transition_task=False,
        )
        run = self.executions.get_run(job.project_id, job.run_id)
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            self.executions.transition_run(
                job.project_id,
                job.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.STALE,
                updates={
                    "final_marker": "STALE",
                    "final_summary_text": reason,
                },
            )
        return self.executions.get_task(job.project_id, job.task_id)

    def _quarantine_cancelled_sync(
        self,
        job: SourceAnalysisJob,
        result: Mapping[str, Any],
    ) -> TaskRecord:
        reason = "Task was cancelled before Source Intelligence publication"
        self.executions.quarantine_task_result(
            job.project_id,
            job.task_id,
            quarantine_id=_stable_id(
                "source-quarantine",
                job.project_id,
                job.command_id,
            ),
            reason=reason,
            result=result,
            transition_task=False,
        )
        run = self.executions.get_run(job.project_id, job.run_id)
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            self.executions.transition_run(
                job.project_id,
                job.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.CANCELLED,
                updates={
                    "final_marker": "CANCELLED",
                    "final_summary_text": reason,
                },
            )
        return self.executions.get_task(job.project_id, job.task_id)

    def _fail_sync(
        self,
        job: SourceAnalysisJob,
        error: BaseException,
    ) -> TaskRecord:
        task = self.executions.get_task(job.project_id, job.task_id)
        if task.status is TaskStatus.CANCELLED:
            return self._quarantine_cancelled_sync(
                job,
                {"error": _error_payload(error)},
            )
        if task.status is TaskStatus.RUNNING:
            converged = self._converge_published_job_sync(job)
            if converged is not None:
                return converged
        if task.status is TaskStatus.RUNNING:
            self.executions.append_attempt(
                job.project_id,
                job.task_id,
                event_id=f"{job.attempt_id}-failed",
                attempt_id=job.attempt_id,
                status=TaskAttemptStatus.FAILED,
                error=_error_payload(error),
            )
        elif task.status is TaskStatus.QUEUED:
            self.executions.transition_task(
                job.project_id,
                job.task_id,
                expected_status=TaskStatus.QUEUED,
                status=TaskStatus.FAILED,
                updates={"error": _error_payload(error)},
            )
        run = self.executions.get_run(job.project_id, job.run_id)
        if run.status in {
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.QUEUED_CAPACITY,
            SpecialistRunStatus.RUNNING_MODEL,
        }:
            self.executions.transition_run(
                job.project_id,
                job.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.FAILED,
                updates={
                    "final_marker": "FAILED",
                    "final_summary_text": _error_payload(error)["message"],
                },
            )
        return self.executions.get_task(job.project_id, job.task_id)

    def _cancel_worker_sync(self, job: SourceAnalysisJob) -> None:
        task = self.executions.get_task(job.project_id, job.task_id)
        if task.status is TaskStatus.RUNNING:
            self.executions.transition_task(
                job.project_id,
                job.task_id,
                expected_status=TaskStatus.RUNNING,
                status=TaskStatus.CANCELLED,
                updates={
                    "error": {
                        "code": "WORKER_CANCELLED",
                        "message": "Source analysis worker was cancelled",
                    },
                },
            )
            task = self.executions.get_task(job.project_id, job.task_id)
        run = self.executions.get_run(job.project_id, job.run_id)
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            target = {
                TaskStatus.SUCCEEDED: SpecialistRunStatus.SUCCEEDED,
                TaskStatus.FAILED: SpecialistRunStatus.FAILED,
                TaskStatus.QUARANTINED: SpecialistRunStatus.STALE,
                TaskStatus.CANCELLED: SpecialistRunStatus.CANCELLED,
            }.get(task.status, SpecialistRunStatus.CANCELLED)
            self.executions.transition_run(
                job.project_id,
                job.run_id,
                expected_status=run.status,
                status=target,
                updates={"final_marker": target.value},
            )


_registry_lock = threading.RLock()
_registry: dict[Path, SourceMediaAnalysisService] = {}


def source_analysis_service(
    services: CreatorFileServices,
) -> SourceMediaAnalysisService:
    root = services.root.resolve()
    with _registry_lock:
        service = _registry.get(root)
        if service is None:
            service = SourceMediaAnalysisService(services)
            _registry[root] = service
        return service


def clear_source_analysis_service_registry() -> None:
    with _registry_lock:
        for service in _registry.values():
            for task in service._jobs.values():
                task.cancel()
        _registry.clear()


async def shutdown_source_analysis_services() -> None:
    """Cancel and await every process-local Source analysis worker."""

    with _registry_lock:
        services = list(_registry.values())
        _registry.clear()
    workers = [task for service in services for task in service._jobs.values()]
    for task in workers:
        task.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)


def recover_interrupted_source_analysis(
    services: CreatorFileServices,
) -> int:
    """Converge published tasks, then fail closed unknown provider work.

    Provider calls are intentionally not replayed from partial Runtime state:
    the external request may have completed without a durable response.  The
    exact immutable Project index is accepted as convergence evidence; all
    other interrupted Tasks become FAILED and must be submitted again.
    """

    executions = ProjectExecutionStore(services.root)
    convergence = SourceMediaAnalysisService(services)
    recovered = 0
    error = {
        "code": "SOURCE_ANALYSIS_PROCESS_RESTARTED",
        "message": (
            "Source analysis was interrupted by process restart; "
            "submit a new ANALYZE_SOURCE_MEDIA command"
        ),
        "retryable": True,
    }
    for project_id in services.projects.discover_project_ids():
        # Admission writes Run then Task.  If the second atomic write was
        # interrupted, reconstruct the deterministic Task before the normal
        # fail-closed pass so the command never remains a permanent orphan.
        for run in executions.list_specialist_runs(project_id):
            if (
                run.role is not SpecialistRole.SOURCE_INTELLIGENCE
                or run.status in TERMINAL_SPECIALIST_STATUSES
                or run.metadata.get("operation") != "ANALYZE_SOURCE_MEDIA"
            ):
                continue
            command_id = run.caused_by_request_id
            if not isinstance(command_id, str) or not command_id:
                continue
            expected_task_id = _stable_id(
                "source-task",
                project_id,
                command_id,
            )
            try:
                executions.get_task(project_id, expected_task_id)
                continue
            except RecordNotFoundError:
                pass
            source_id = run.metadata.get("sourceId")
            version_id = run.metadata.get("assetVersionId")
            try:
                if not isinstance(source_id, str) or not source_id:
                    raise StorageIntegrityError("Source Run 缺少 sourceId")
                convergence._prepare_sync(
                    project_id,
                    f"source:{source_id}",
                    command_id,
                    (
                        {"assetVersionId": version_id}
                        if isinstance(version_id, str) and version_id
                        else {}
                    ),
                )
            except (
                ConflictError,
                NotFoundError,
                StorageIntegrityError,
                ValidationError,
            ) as repair_error:
                executions.transition_run(
                    project_id,
                    run.run_id,
                    expected_status=run.status,
                    status=SpecialistRunStatus.FAILED,
                    updates={
                        "final_marker": "FAILED",
                        "final_summary_text": (
                            "Interrupted Source admission could not be repaired: "
                            f"{str(repair_error)[:1600]}"
                        ),
                    },
                )
                recovered += 1
        for task in executions.list_tasks(project_id):
            if (
                task.kind is not TaskKind.SOURCE_INTELLIGENCE
                or task.status
                not in {
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                }
            ):
                continue
            recovery_job = convergence._recovery_job_from_task(task)
            if recovery_job is not None:
                converged = convergence._converge_published_job_sync(
                    recovery_job,
                )
                if (
                    converged is not None
                    and converged.status is TaskStatus.SUCCEEDED
                ):
                    recovered += 1
                    continue
            if task.status is TaskStatus.RUNNING:
                running_attempt = next(
                    (
                        item
                        for item in reversed(
                            executions.list_attempts(project_id, task.task_id),
                        )
                        if item.status is TaskAttemptStatus.RUNNING
                    ),
                    None,
                )
                if running_attempt is not None:
                    executions.append_attempt(
                        project_id,
                        task.task_id,
                        event_id=f"{running_attempt.attempt_id}-restart-failed",
                        attempt_id=running_attempt.attempt_id,
                        status=TaskAttemptStatus.FAILED,
                        error=error,
                    )
                else:
                    executions.transition_task(
                        project_id,
                        task.task_id,
                        expected_status=TaskStatus.RUNNING,
                        status=TaskStatus.FAILED,
                        updates={"error": error},
                    )
            else:
                executions.transition_task(
                    project_id,
                    task.task_id,
                    expected_status=TaskStatus.QUEUED,
                    status=TaskStatus.FAILED,
                    updates={"error": error},
                )
            if task.run_id is not None:
                run = executions.get_run(project_id, task.run_id)
                if run.status not in TERMINAL_SPECIALIST_STATUSES:
                    executions.transition_run(
                        project_id,
                        run.run_id,
                        expected_status=run.status,
                        status=SpecialistRunStatus.FAILED,
                        updates={
                            "final_marker": "FAILED",
                            "final_summary_text": error["message"],
                        },
                    )
            recovered += 1
    return recovered


__all__ = [
    "DefaultSourceMediaAnalyzer",
    "SourceAgentToolContext",
    "SourceAnalysisDispatch",
    "SourceAnalysisJob",
    "SourceAnalyzerConfigurationError",
    "SourceAnalyzerOutput",
    "SourceMediaAnalysisInput",
    "SourceMediaAnalysisService",
    "SourceMediaAnalyzer",
    "clear_source_analysis_service_registry",
    "recover_interrupted_source_analysis",
    "shutdown_source_analysis_services",
    "source_analysis_service",
]
