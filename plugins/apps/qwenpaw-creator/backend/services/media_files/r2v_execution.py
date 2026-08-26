# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,raise-missing-from
# pylint: disable=too-many-boolean-expressions,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
# pylint: disable=try-except-raise,unused-argument
"""Restart-safe, file-native reference-to-video execution.

``GENERATE_R2V_VIDEO`` admission freezes exact Project versions and returns
immediately.  A process-local supervisor performs provider submission and
polling from a durable state record below ``runtime/tasks/<task>/``.  The
provider never owns Project authority: successful bytes are published as an
immutable Asset and become visible only through one Project commit.

The state machine is deliberately fail-closed around the non-idempotent
provider submission window.  A surviving submit claim without a durable
provider task id is never submitted again after its safety lease expires.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import threading
import time
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field

import httpx

from domain.enums import (
    CreatorCommandType,
    SpecialistRole,
    SpecialistRunStatus,
    TERMINAL_SPECIALIST_STATUSES,
    TaskKind,
    TaskStatus,
)
from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from schemas.common import StrictModel
from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileStore,
    StagedAsset,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    I2VCreation,
    IndexedFile,
    Project,
    R2VCreation,
    S2VCreation,
    T2VCreation,
)
from services.media_files.call_budget import ensure_media_call_budget
from services.media_files.element_adapter import (
    bind_candidate_output,
    find_timeline_element,
    reconcile_candidate_span,
    selected_element_output,
    target_element_id,
)
from services.media_files.review_admission import (
    assert_media_review_admission,
    media_review_policy,
)
from services.media_files.transient_errors import (
    MAX_TRANSIENT_RETRY_SLOTS,
    is_transient_error_message,
    is_transient_task_error,
    transient_retry_slot_key,
)
from services.media_files.visual_reference_resolution import (
    resolve_r2v_visual_reference_version_ids,
)
from services.observability import report_error
from services.project_files.remote_cache import public_source_url
from services.project_files.store import ProjectSnapshot
from services.run_review.media_review import (
    release_media_review_reservation,
    reserve_media_review,
    schedule_media_review,
)
from services.runtime_files.atomic_store import (
    AtomicJsonRecordStore,
    canonical_json_bytes,
)
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionPayloadConflict,
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from services.runtime_files.reconciliation import reconcile_terminal_task_runs

# pylint: disable=no-name-in-module
from utils.logger import setup_logger
from utils.paths import media_task_scope, task_work_root

# pylint: enable=no-name-in-module

from .secure_video_stream import MaterializedVideo, materialize_r2v_video

_MAX_VIDEO_BYTES = 256 * 1024 * 1024
_SUBMIT_TIMEOUT_SECONDS = 180.0
_SUBMIT_CLAIM_SECONDS = 600.0
_MATERIALIZE_TIMEOUT_SECONDS = 180.0
_MATERIALIZE_CLAIM_SECONDS = 300.0
_MATERIALIZE_RETRY_DELAYS = (2.0, 5.0, 10.0)
_TERMINAL_RECOVERY_POLL_SECONDS = 1.0
_ACTIVE_PHASES = frozenset(
    {
        "ADMITTED",
        "SUBMIT_CLAIMED",
        "POLLING",
        "PROVIDER_SUCCEEDED",
        "PUBLISHED",
    },
)
_TERMINAL_TASKS = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.QUARANTINED,
    },
)

logger = setup_logger("services.media_files.r2v_execution")

_GOOGLE_API_KEY_AUTH = "x-goog-api-key"
_CREDENTIAL_QUERY_NAMES = frozenset(
    {"key", "api_key", "token", "access_token"},
)


def _strip_credential_query(value: object) -> object:
    """Remove credential-shaped query parameters from one durable URL."""

    if not isinstance(value, str) or not value:
        return value
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.query:
        return value
    kept = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _CREDENTIAL_QUERY_NAMES
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(kept),
            parsed.fragment,
        ),
    )


def _durable_provider_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a credential-free provider result suitable for task state."""

    durable = dict(result)
    if str(durable.get("download_auth") or "") == _GOOGLE_API_KEY_AUTH:
        for field in ("url", "result_url", "video_url"):
            if field in durable:
                durable[field] = _strip_credential_query(durable[field])
    return durable


def _provider_download_headers(result: Mapping[str, Any]) -> dict[str, str]:
    """Resolve non-durable provider download credentials at request time."""

    auth = str(result.get("download_auth") or "")
    if not auth:
        return {}
    if auth != _GOOGLE_API_KEY_AUTH:
        raise ValidationError(f"未知 provider 下载鉴权类型: {auth}")
    from models import config as model_config

    api_key = model_config.get_video_api_key()
    if not api_key:
        raise ValidationError("Veo 视频下载需要当前模型配置中的 API Key")
    return {_GOOGLE_API_KEY_AUTH: api_key}


class VideoReferenceBudgetError(ValidationError):
    """Resolved Project references exceed the active video model contract."""

    code = "VIDEO_REFERENCE_BUDGET_EXCEEDED"


class VideoModelCapabilityError(ValidationError):
    """A configured video model alias has no verified reference limit."""

    code = "VIDEO_MODEL_CAPABILITY_UNKNOWN"


def _log_safe(value: object) -> str:
    """Neutralise CR/LF so identifier values cannot forge log lines."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


class R2VProvider(Protocol):
    """Injectable provider boundary.  Calls happen outside all file locks."""

    async def submit(
        self,
        *,
        prompt: str,
        reference_image_urls: Sequence[str],
        ratio: str,
        duration_seconds: int,
        resolution: str,
        watermark: bool,
        generate_audio: bool,
        mode: str = "r2v",
        first_frame_url: str | None = None,
        video_url: str | None = None,
    ) -> str:
        ...

    async def poll(self, provider_task_id: str) -> Mapping[str, Any]:
        ...

    async def submit_s2v(
        self,
        *,
        image_url: str,
        audio_url: str,
        resolution: str,
    ) -> str:
        ...

    async def poll_s2v(self, provider_task_id: str) -> Mapping[str, Any]:
        ...


class ExistingR2VProvider:
    """Lazy adapter over the configured video model.

    Keeping the import inside the call means read-only Creator startup does not
    import the model transport, while the packaged runtime can still select it
    when a real R2V command is submitted.
    """

    async def submit(
        self,
        *,
        prompt: str,
        reference_image_urls: Sequence[str],
        ratio: str,
        duration_seconds: int,
        resolution: str,
        watermark: bool,
        generate_audio: bool,
        mode: str = "r2v",
        first_frame_url: str | None = None,
        video_url: str | None = None,
    ) -> str:
        from models.video_model import submit_video_task

        return await submit_video_task(
            prompt=prompt,
            reference_image_url_list=list(reference_image_urls),
            ratio=ratio,
            duration=duration_seconds,
            resolution=resolution,
            watermark=watermark,
            generate_audio=generate_audio,
            mode=mode,
            first_frame_url=first_frame_url,
            video_url=video_url,
        )

    async def poll(self, provider_task_id: str) -> Mapping[str, Any]:
        from models.video_model import check_task_status

        return await check_task_status(provider_task_id)

    async def submit_s2v(
        self,
        *,
        image_url: str,
        audio_url: str,
        resolution: str,
    ) -> str:
        from models.s2v_model import submit_s2v_task

        return await submit_s2v_task(
            image_url=image_url,
            audio_url=audio_url,
            resolution=resolution,
        )

    async def poll_s2v(self, provider_task_id: str) -> Mapping[str, Any]:
        from models.s2v_model import check_s2v_task_status

        return await check_s2v_task_status(provider_task_id)


class R2VTaskState(StrictModel):
    """Mutable recovery head stored atomically beside the Task aggregate."""

    schema_version: Literal[1] = 1
    project_id: str
    task_id: str
    run_id: str
    request_fingerprint: str
    phase: Literal[
        "ADMITTED",
        "SUBMIT_CLAIMED",
        "POLLING",
        "PROVIDER_SUCCEEDED",
        "PUBLISHED",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "QUARANTINED",
    ] = "ADMITTED"
    request: dict[str, Any]
    submit_owner: str | None = None
    submit_claim_token: str | None = None
    submit_claimed_at_epoch: float | None = None
    submit_heartbeat_at_epoch: float | None = None
    submit_claim_expires_at_epoch: float | None = None
    provider_task_id: str | None = None
    last_poll_at_epoch: float | None = None
    next_poll_at_epoch: float | None = None
    poll_lease_owner: str | None = None
    poll_lease_token: str | None = None
    poll_lease_expires_at_epoch: float | None = None
    provider_result: dict[str, Any] | None = None
    materialize_owner: str | None = None
    materialize_claim_token: str | None = None
    materialize_claimed_at_epoch: float | None = None
    materialize_heartbeat_at_epoch: float | None = None
    materialize_claim_expires_at_epoch: float | None = None
    materialized_result: dict[str, Any] | None = None
    published_result: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class FileR2VDispatch:
    task_id: str
    run_id: str
    transaction_id: str
    input_etag: str
    replayed: bool

    def command_response(self, command_id: str) -> dict[str, Any]:
        return {
            "commandId": command_id,
            "status": "QUEUED",
            "eventSeq": 0,
            "transactionId": self.transaction_id,
            "workingHead": self.input_etag,
        }


class _R2VClaimLost(RuntimeError):
    """A stale supervisor lost durable ownership; it must never fail the Task."""


@dataclass(frozen=True, slots=True)
class _ResolvedR2V:
    target_ref: str
    element_id: str
    element_label: str
    prompt: str
    ratio: str
    duration_seconds: int
    resolution: str
    watermark: bool
    generate_audio: bool
    reference_version_ids: tuple[str, ...]
    reference_urls: tuple[str, ...]
    reference_checksums: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    read_set: tuple[dict[str, Any], ...]
    slot_id: str
    slot_kind: str
    owner_ref: str
    mode: str = "r2v"
    first_frame_version_id: str = ""
    first_frame_url: str = ""
    video_version_id: str = ""
    video_url: str = ""
    # "video" (default) drives the configured video model; "s2v" drives the
    # wan2.2-s2v digital-human provider through the same durable machinery.
    provider: str = "video"
    s2v_image_version_id: str = ""
    s2v_image_url: str = ""
    s2v_audio_version_id: str = ""
    s2v_audio_url: str = ""
    s2v_resolution: str = ""


def _stable_id(prefix: str, project_id: str, key: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:file-r2v:{prefix}:{project_id}:{key}",
    ).hex
    return f"{prefix}-{digest}"


def _ids(project_id: str, key: str) -> dict[str, str]:
    return {
        "run_id": _stable_id("run", project_id, key),
        "round_id": _stable_id("round", project_id, key),
        "task_id": _stable_id("task", project_id, key),
        "attempt_id": _stable_id("attempt", project_id, key),
        "attempt_started_event_id": _stable_id(
            "attempt-started",
            project_id,
            key,
        ),
        "attempt_succeeded_event_id": _stable_id(
            "attempt-succeeded",
            project_id,
            key,
        ),
        "attempt_failed_event_id": _stable_id(
            "attempt-failed",
            project_id,
            key,
        ),
        "attempt_quarantined_event_id": _stable_id(
            "attempt-quarantined",
            project_id,
            key,
        ),
        "file_id": _stable_id("file", project_id, key),
        "artifact_version_id": _stable_id("artifact-version", project_id, key),
        "transaction_id": _stable_id("media-transaction", project_id, key),
        "quarantine_id": _stable_id("quarantine", project_id, key),
    }


def _fingerprint(value: Mapping[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _failed_task_conflict(
    task: TaskRecord | None,
    *,
    exhausted_retries: bool = False,
) -> ConflictError:
    """Name the original failure and the exact way out of the replay wall."""

    status = task.status.value if task is not None else "FAILED"
    reason = ""
    error = getattr(task, "error", None)
    if isinstance(error, Mapping) and error.get("message"):
        reason = f"；原失败原因：{str(error['message'])[:200]}"
    if exhausted_retries:
        advice = "瞬态重试槽位已用尽，说明故障持续存在。请停止重发相同请求，向用户报告故障或稍后再试。"
    else:
        advice = (
            "相同 arguments 的重发将始终返回此错误；若需重试，请先修正失败原因"
            "并调整 arguments（如更换分镜图或修改 prompt 措辞）以生成新任务。"
        )
    return ConflictError(f"R2V Task 已终止: {status}{reason}。{advice}")


def _is_transient_materialize_error(error: BaseException) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    return is_transient_error_message(str(error))


def _json_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} 必须是 JSON object")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{label} 必须可以持久化为 JSON") from error
    if not isinstance(
        decoded,
        dict,
    ):  # pragma: no cover - mapping encodes object
        raise ValidationError(f"{label} 必须是 JSON object")
    return decoded


def _target_element_id(target_ref: str) -> str:
    return target_element_id(target_ref, command="GENERATE_R2V_VIDEO")


def _duration(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("R2V durationSeconds 必须是整数")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError("R2V durationSeconds 必须是整数") from error
    if not number.is_integer() or not 1 <= number <= 60:
        raise ValidationError("R2V durationSeconds 必须是 1 到 60 的整数")
    return int(number)


def _indexed_path(project_root: Path, indexed: IndexedFile) -> Path:
    return project_root.joinpath(*PurePosixPath(indexed.relative_uri).parts)


def _resolve_reference_versions(
    *,
    project: Project,
    project_root: Path,
    version_ids: Sequence[str],
) -> tuple[list[str], list[str], list[str], list[dict[str, Any]]]:
    urls: list[str] = []
    checksums: list[str] = []
    provenance: list[str] = []
    read_set: list[dict[str, Any]] = []
    files = AssetFileStore(project_root)
    for version_id in dict.fromkeys(version_ids):
        source = project.assets.source_versions_by_id.get(version_id)
        artifact = project.assets.artifact_versions_by_id.get(version_id)
        version = source or artifact
        if version is None:
            raise NotFoundError(f"R2V reference version 不存在: {version_id}")
        # Check for source_url stored by Token Plan image generation.
        # Stored at metadata["provider"]["source_url"] by _materialize_and_publish.
        source_url = ""
        if artifact is not None and isinstance(
            getattr(artifact, "metadata", None),
            dict,
        ):
            provider_meta = artifact.metadata.get("provider", {})
            if isinstance(provider_meta, dict):
                source_url = provider_meta.get("source_url", "")
        if source_url:
            indexed = project.assets.files_by_id.get(version.file_id)
            if indexed is None or not indexed.media_type.casefold().startswith(
                ("image/", "video/"),
            ):
                raise ValidationError(
                    f"R2V reference 不是图片或视频: {version_id}",
                )
            ref = f"artifact-version:{version_id}"
            urls.append(source_url)
            checksums.append(version.checksum)
            provenance.append(ref)
            read_set.append(
                {
                    "ref": ref,
                    "versionId": version_id,
                    "fileId": indexed.file_id,
                    "checksum": version.checksum,
                    "sourceUrl": source_url,
                },
            )
            continue
        remote_url = public_source_url(source) if source is not None else None
        if remote_url is not None:
            if not version.media_type.casefold().startswith(
                ("image/", "video/"),
            ):
                raise ValidationError(
                    f"R2V reference 不是图片或视频: {version_id}",
                )
            ref = f"asset-version:{version_id}"
            urls.append(remote_url)
            checksums.append(version.checksum)
            provenance.append(ref)
            read_set.append(
                {
                    "ref": ref,
                    "versionId": version_id,
                    "fileId": None,
                    "checksum": version.checksum,
                    "sourceUrl": remote_url,
                },
            )
            continue
        indexed = project.assets.files_by_id.get(version.file_id)
        if indexed is None:
            raise StorageIntegrityError(
                f"R2V reference 缺少 IndexedFile: {version_id}",
            )
        if indexed.sha256 != version.checksum:
            raise StorageIntegrityError(
                f"R2V reference checksum/index 不一致: {version_id}",
            )
        if not indexed.media_type.casefold().startswith(
            ("image/", "video/"),
        ):
            raise ValidationError(
                f"R2V reference 不是图片或视频: {version_id}",
            )
        inspection = files.inspect(indexed)
        if not inspection.available:
            raise StorageIntegrityError(
                f"R2V reference 文件不可用: {version_id} ({inspection.status.value})",
            )
        ref = (
            f"asset-version:{version_id}"
            if source is not None
            else f"artifact-version:{version_id}"
        )
        urls.append(_indexed_path(project_root, indexed).resolve().as_uri())
        checksums.append(version.checksum)
        provenance.append(ref)
        read_set.append(
            {
                "ref": ref,
                "versionId": version_id,
                "fileId": indexed.file_id,
                "checksum": version.checksum,
            },
        )
    return urls, checksums, provenance, read_set


def _resolve_single_media_version(
    *,
    project: Project,
    project_root: Path,
    version_id: str,
    media_prefix: str,
    label: str,
) -> tuple[str, str, str, dict[str, Any]]:
    """Resolve one exact version id into ``(url, checksum, ref, read_entry)``.

    Same integrity rules as ``_resolve_reference_versions`` but with a
    caller-selected media kind, so i2v first frames stay images and
    video_edit inputs stay videos.
    """

    source = project.assets.source_versions_by_id.get(version_id)
    artifact = project.assets.artifact_versions_by_id.get(version_id)
    version = source or artifact
    if version is None:
        raise NotFoundError(f"{label} version 不存在: {version_id}")
    # Check for source_url stored by Token Plan image generation.
    source_url = ""
    if artifact is not None and isinstance(
        getattr(artifact, "metadata", None),
        dict,
    ):
        provider_meta = artifact.metadata.get("provider", {})
        if isinstance(provider_meta, dict):
            source_url = provider_meta.get("source_url", "")
    if source_url:
        indexed = project.assets.files_by_id.get(version.file_id)
        if indexed is None or not indexed.media_type.casefold().startswith(
            media_prefix,
        ):
            raise ValidationError(
                f"{label} 必须是 {media_prefix}* 媒体: {version_id}",
            )
        ref = f"artifact-version:{version_id}"
        return (
            source_url,
            version.checksum,
            ref,
            {
                "ref": ref,
                "versionId": version_id,
                "fileId": indexed.file_id,
                "checksum": version.checksum,
                "sourceUrl": source_url,
            },
        )
    remote_url = public_source_url(source) if source is not None else None
    if remote_url is not None:
        if not version.media_type.casefold().startswith(media_prefix):
            raise ValidationError(
                f"{label} 必须是 {media_prefix}* 媒体: {version_id}",
            )
        ref = f"asset-version:{version_id}"
        return (
            remote_url,
            version.checksum,
            ref,
            {
                "ref": ref,
                "versionId": version_id,
                "fileId": None,
                "checksum": version.checksum,
                "sourceUrl": remote_url,
            },
        )
    indexed = project.assets.files_by_id.get(version.file_id)
    if indexed is None:
        raise StorageIntegrityError(
            f"{label} 缺少 IndexedFile: {version_id}",
        )
    if indexed.sha256 != version.checksum:
        raise StorageIntegrityError(
            f"{label} checksum/index 不一致: {version_id}",
        )
    if not indexed.media_type.casefold().startswith(media_prefix):
        raise ValidationError(
            f"{label} 必须是 {media_prefix}* 媒体: {version_id}",
        )
    inspection = AssetFileStore(project_root).inspect(indexed)
    if not inspection.available:
        raise StorageIntegrityError(
            f"{label} 文件不可用: {version_id} ({inspection.status.value})",
        )
    ref = (
        f"asset-version:{version_id}"
        if source is not None
        else f"artifact-version:{version_id}"
    )
    return (
        _indexed_path(project_root, indexed).resolve().as_uri(),
        version.checksum,
        ref,
        {
            "ref": ref,
            "versionId": version_id,
            "fileId": indexed.file_id,
            "checksum": version.checksum,
        },
    )


def media_version_duration_seconds(
    project: Project,
    version_id: str,
) -> float | None:
    """Recorded duration of one exact source/artifact version, when known."""

    version = project.assets.source_versions_by_id.get(
        version_id,
    ) or project.assets.artifact_versions_by_id.get(version_id)
    return None if version is None else version.duration_seconds


def _probed_media_duration_seconds(
    project: Project,
    project_root: Path,
    version_id: str,
) -> float | None:
    """Probe the indexed local file of one version for its real duration.

    Older assets (and anything imported before duration probing) carry no
    recorded duration, so the file itself is the fallback source of truth.
    """

    version = project.assets.source_versions_by_id.get(
        version_id,
    ) or project.assets.artifact_versions_by_id.get(version_id)
    if version is None or version.file_id is None:
        return None
    indexed = project.assets.files_by_id.get(version.file_id)
    if indexed is None:
        return None
    path = _indexed_path(project_root, indexed)
    if not path.is_file():
        return None
    from services.runtime_files.media_probe import MediaProbeError, probe_media

    try:
        probe = probe_media(os.fspath(path))
    except (MediaProbeError, OSError, ValueError):
        return None
    duration = getattr(probe, "duration_seconds", None)
    return float(duration) if duration else None


def effective_video_duration_seconds(
    project: Project,
    project_root: Path,
    version_id: str,
) -> float | None:
    """The duration a billed request will really be charged for.

    Single resolver for authorization and execution: the recorded metadata
    first, then a probe of the indexed local file for assets that carry
    none. Returning None means the length is genuinely unknown.
    """

    recorded = media_version_duration_seconds(project, version_id)
    if recorded is not None:
        return recorded
    return _probed_media_duration_seconds(project, project_root, version_id)


def _assert_video_edit_input_duration(
    project: Project,
    project_root: Path,
    version_id: str,
) -> None:
    """Fail before a billed submission when the input length is unusable.

    video_edit takes its duration from the input video (3-60s, with the
    provider keeping only the first 15s), and the tool's durationSeconds is
    not sent for this mode, so the input itself is the only thing to check.
    An unknown duration is never waved through: the local file is probed,
    and a still-unknown length is rejected rather than billed blindly.
    """

    duration = effective_video_duration_seconds(
        project,
        project_root,
        version_id,
    )
    from models.video_capabilities import (
        HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS,
        HAPPYHORSE_VIDEO_EDIT_MAX_INPUT_SECONDS,
        HAPPYHORSE_VIDEO_EDIT_MIN_INPUT_SECONDS,
    )

    if duration is None:
        raise ValidationError(
            f"无法确定 videoRef 的时长，而 video_edit 输入必须在 "
            f"{HAPPYHORSE_VIDEO_EDIT_MIN_INPUT_SECONDS}–"
            f"{HAPPYHORSE_VIDEO_EDIT_MAX_INPUT_SECONDS} 秒之间：该版本既未记录"
            " duration_seconds，本地文件也探测不到（缺失、不可读或无 "
            "ffprobe/ffmpeg）。请重新引入该视频以补齐元数据后重试",
        )
    if (
        duration < HAPPYHORSE_VIDEO_EDIT_MIN_INPUT_SECONDS
        or duration > HAPPYHORSE_VIDEO_EDIT_MAX_INPUT_SECONDS
    ):
        raise ValidationError(
            f"video_edit 输入视频时长必须在 "
            f"{HAPPYHORSE_VIDEO_EDIT_MIN_INPUT_SECONDS}–"
            f"{HAPPYHORSE_VIDEO_EDIT_MAX_INPUT_SECONDS} 秒之间，"
            f"当前 videoRef 为 {duration:.2f} 秒；超过 "
            f"{HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS} 秒时上游只取前 "
            f"{HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS} 秒",
        )


def _validated_request_mode(arguments: Mapping[str, Any]) -> str:
    """Normalize the requested mode against the runtime capability matrix."""

    from models import config as model_config
    from models.video_capabilities import validate_video_mode

    model_name = model_config.get_video_model_name()
    protocol_backend = model_config.get_video_backend()
    try:
        return validate_video_mode(
            protocol_backend,
            model_name,
            str(arguments.get("mode") or "r2v"),
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error


def _assert_r2v_reference_budget(
    project: Project,
    version_ids: Sequence[str],
    *,
    project_root: Path | None = None,
    output_duration_seconds: int | None = None,
) -> None:
    """Fail before admission when Project references exceed model limits."""

    from models import config as model_config
    from models.video_capabilities import (
        effective_video_model_name,
        is_wan3_video_model,
        video_backend_key,
        video_reference_capability,
        video_reference_violation,
    )

    configured_model = model_config.get_video_model_name().strip()
    backend_key = video_backend_key(
        configured_model,
        model_config.get_video_backend(),
    )
    effective_model = effective_video_model_name(
        configured_model,
        "r2v",
        backend_key,
    )
    capability = video_reference_capability(effective_model)

    image_ids: list[str] = []
    video_ids: list[str] = []
    for version_id in dict.fromkeys(version_ids):
        source = project.assets.source_versions_by_id.get(version_id)
        artifact = project.assets.artifact_versions_by_id.get(version_id)
        version = source or artifact
        if version is None:
            # The resolver below owns the stable NotFoundError contract.
            continue
        if source is not None:
            media_type = source.media_type.casefold()
        else:
            indexed = project.assets.files_by_id.get(artifact.file_id)
            if indexed is None:
                # The resolver below owns the integrity error and its details.
                continue
            media_type = indexed.media_type.casefold()
        if media_type.startswith("image/"):
            image_ids.append(version_id)
        elif media_type.startswith("video/"):
            video_ids.append(version_id)

    details = {
        "modelName": configured_model or "未配置",
        "effectiveModelName": effective_model or "未配置",
        "resolvedCount": len(image_ids) + len(video_ids),
        "imageCount": len(image_ids),
        "videoCount": len(video_ids),
        "referenceVersionIds": list(dict.fromkeys(version_ids)),
        "imageReferenceVersionIds": image_ids,
        "videoReferenceVersionIds": video_ids,
    }
    if capability is None:
        raise VideoModelCapabilityError(
            "VIDEO_MODEL_CAPABILITY_UNKNOWN: 执行层已解析 R2V 的 Project "
            "参考素材，但无法从官方能力表确认视频模型 "
            f"{effective_model or '未配置'} 的输入上限，因此没有创建任务、"
            "上传素材或调用 provider。如果这是兼容网关别名，请先将别名"
            "映射到官方模型能力，不可使用 Wan 或通用猜测上限。",
            details={**details, "knownModelRequired": True},
        )

    violation = video_reference_violation(
        capability,
        image_count=len(image_ids),
        video_count=len(video_ids),
    )
    if violation is not None:
        raise VideoReferenceBudgetError(
            "VIDEO_REFERENCE_BUDGET_EXCEEDED: 执行层解析 storyboard 与 Project "
            f"exact reference version 后，共得到 {details['resolvedCount']} 个"
            f"参考素材，但视频模型 {effective_model} 的官方限制为：{violation}。"
            "执行层没有静默截断，也没有创建任务、上传素材或调用 provider。"
            "请先 read_project，缩减目标 Element 的角色、场景、道具、阵容锚点"
            "或 video_reference_version_ids，再用已变更的 Project 重试。",
            details={
                **details,
                "modelFamily": capability.family,
                "maxReferenceImages": capability.max_reference_images,
                "maxReferenceVideos": capability.max_reference_videos,
                "maxReferenceMedia": capability.max_reference_media,
                "documentationUrl": capability.documentation_url,
            },
        )

    if not is_wan3_video_model(effective_model) or not video_ids:
        return
    max_input_duration = capability.max_reference_video_duration_seconds
    max_combined_duration = capability.max_input_output_duration_seconds
    if max_input_duration is None or max_combined_duration is None:
        raise VideoModelCapabilityError(
            "VIDEO_MODEL_CAPABILITY_UNKNOWN: Wan3.0 参考视频能力缺少官方时长"
            "预算，未创建上游任务。",
            details={**details, "knownDurationBudgetRequired": True},
        )
    durations: list[float] = []
    for version_id in video_ids:
        duration = media_version_duration_seconds(project, version_id)
        if duration is None and project_root is not None:
            duration = effective_video_duration_seconds(
                project,
                project_root,
                version_id,
            )
        if duration is None:
            raise VideoReferenceBudgetError(
                "VIDEO_REFERENCE_DURATION_UNKNOWN: Wan3.0 参考视频"
                f" {version_id} 缺少可验证的时长，未创建上游任务。",
                details={**details, "unknownDurationVersionId": version_id},
            )
        durations.append(duration)
    input_duration = sum(durations)
    if input_duration > max_input_duration or (
        output_duration_seconds is not None
        and input_duration + output_duration_seconds > max_combined_duration
    ):
        raise VideoReferenceBudgetError(
            "VIDEO_REFERENCE_DURATION_EXCEEDED: Wan3.0 参考视频总时长"
            f" {input_duration:.2f} 秒，输出时长 {output_duration_seconds or 0} "
            f"秒；官方要求参考视频合计不超过 {max_input_duration} 秒，且"
            "输入视频与输出视频时长之和不超过 "
            f"{max_combined_duration} 秒。",
            details={
                **details,
                "inputVideoDurationSeconds": input_duration,
                "outputDurationSeconds": output_duration_seconds,
                "maxInputVideoDurationSeconds": max_input_duration,
                "maxCombinedDurationSeconds": max_combined_duration,
            },
        )


def _resolve_request(
    *,
    snapshot: ProjectSnapshot,
    project_root: Path,
    target_ref: str,
    arguments: Mapping[str, Any],
) -> _ResolvedR2V:
    project = snapshot.project
    element_id = _target_element_id(target_ref)
    timeline, element = find_timeline_element(project, element_id)
    creation = element.creation
    mode = _validated_request_mode(arguments)
    # Each creation type declares exactly one generation mode; the request
    # mode must match it so a t2v element can never be submitted as r2v.
    creation_by_mode = {
        "r2v": R2VCreation,
        "video_edit": R2VCreation,
        "t2v": T2VCreation,
        "i2v": I2VCreation,
    }
    expected = creation_by_mode.get(mode)
    if expected is None or not isinstance(creation, expected):
        raise ValidationError(
            f"mode={mode} 与目标 Element 的 creation.type={creation.type} 不匹配；"
            "生成模式由 Element 的 creation 类型声明，不可在提交时替换",
        )
    first_frame_ref = str(arguments.get("firstFrameRef") or "").strip()
    if mode == "i2v" and not first_frame_ref:
        # The declared first frame on the element is the default input.
        first_frame_ref = str(
            getattr(creation, "first_frame_version_id", None) or "",
        ).strip()
    video_ref = str(arguments.get("videoRef") or "").strip()
    if mode == "i2v" and not first_frame_ref:
        raise ValidationError(
            "i2v 模式必须提供 firstFrameRef（exact 图片 version id）或在 "
            "creation.first_frame_version_id 声明首帧",
        )
    if mode == "video_edit" and not video_ref:
        raise ValidationError(
            "video_edit 模式必须提供 videoRef（exact 视频 version id）",
        )
    if first_frame_ref and mode != "i2v":
        raise ValidationError("firstFrameRef 仅用于 i2v 模式")
    if video_ref and mode != "video_edit":
        raise ValidationError("videoRef 仅用于 video_edit 模式")

    storyboard_id: str | None = None
    if mode == "r2v":
        # Only r2v consumes the storyboard + reference stack; the other
        # modes take their exact inputs from firstFrameRef / videoRef.
        selected_storyboard = selected_element_output(
            project,
            element,
            "storyboard",
        )
        storyboard_id = (
            selected_storyboard[1] if selected_storyboard is not None else None
        )
        if not storyboard_id:
            raise ValidationError(
                "R2V Element 尚未选择 storyboard ArtifactVersion",
            )
        storyboard = project.assets.artifact_versions_by_id.get(storyboard_id)
        if storyboard is None:
            raise StorageIntegrityError(
                "selected storyboard ArtifactVersion 不存在",
            )
        if storyboard.owner_ref != f"element:{element_id}":
            raise StorageIntegrityError("selected storyboard 不属于目标 Element")

    prompt = str(arguments.get("prompt") or creation.video_prompt).strip()
    if not prompt:
        raise ValidationError("生成 R2V 视频需要 video prompt")
    if "referenceImageUrls" in arguments or "referenceVersionIds" in arguments:
        raise ValidationError(
            "R2V reference 只能来自 project.json 的 exact version 列表",
        )
    duration_seconds = _duration(
        element.span.duration_tick / timeline.ticks_per_second,
    )
    ratio = str(
        arguments.get("ratio") or project.settings.aspect_ratio,
    ).strip()
    resolution = str(
        arguments.get("resolution") or project.settings.resolution or "720P",
    ).strip()
    if not ratio or not resolution:
        raise ValidationError("R2V ratio/resolution 不能为空")
    # No provider watermark by default; enabled only on explicit request.
    watermark = arguments.get("watermark", False)
    generate_audio = arguments.get("generateAudio", True)
    if not isinstance(watermark, bool) or not isinstance(generate_audio, bool):
        raise ValidationError("R2V watermark/generateAudio 必须是 boolean")

    if mode == "r2v":
        version_ids = tuple(
            dict.fromkeys(
                [
                    storyboard_id,
                    *resolve_r2v_visual_reference_version_ids(
                        project,
                        creation,
                        creation.video_reference_version_ids,
                    ),
                ],
            ),
        )
        _assert_r2v_reference_budget(
            project,
            version_ids,
            project_root=project_root,
            output_duration_seconds=duration_seconds,
        )
        urls, checksums, provenance, read_set = _resolve_reference_versions(
            project=project,
            project_root=project_root,
            version_ids=version_ids,
        )
    else:
        version_ids = ()
        urls, checksums, provenance, read_set = [], [], [], []

    first_frame_url = ""
    video_url = ""
    if mode == "i2v":
        first_frame_url, checksum, ref, entry = _resolve_single_media_version(
            project=project,
            project_root=project_root,
            version_id=first_frame_ref,
            media_prefix="image/",
            label="firstFrameRef",
        )
        version_ids = (first_frame_ref,)
        checksums = [checksum]
        provenance = [ref]
        read_set = [entry]
    elif mode == "video_edit":
        video_url, checksum, ref, entry = _resolve_single_media_version(
            project=project,
            project_root=project_root,
            version_id=video_ref,
            media_prefix="video/",
            label="videoRef",
        )
        _assert_video_edit_input_duration(project, project_root, video_ref)
        version_ids = (video_ref,)
        checksums = [checksum]
        provenance = [ref]
        read_set = [entry]

    return _ResolvedR2V(
        target_ref=target_ref,
        element_id=element_id,
        element_label=element.label,
        prompt=prompt,
        ratio=ratio,
        duration_seconds=duration_seconds,
        resolution=resolution,
        watermark=watermark,
        generate_audio=generate_audio,
        reference_version_ids=version_ids,
        reference_urls=tuple(urls),
        reference_checksums=tuple(checksums),
        provenance_refs=tuple(provenance),
        read_set=tuple(read_set),
        slot_id=f"element:{element_id}:main",
        slot_kind="element_video",
        owner_ref=f"element:{element_id}",
        mode=mode,
        first_frame_version_id=first_frame_ref if mode == "i2v" else "",
        first_frame_url=first_frame_url,
        video_version_id=video_ref if mode == "video_edit" else "",
        video_url=video_url,
    )


def _resolve_s2v_request(
    *,
    snapshot: ProjectSnapshot,
    project_root: Path,
    target_ref: str,
    arguments: Mapping[str, Any],
) -> _ResolvedR2V:
    """Resolve one s2v_generation call onto the R2V durable machinery.

    The digital-human video publishes into the same element main slot as an
    r2v render; inputs are exact versions (character image + TTS audio).
    """

    from models.s2v_model import normalize_s2v_resolution

    project = snapshot.project
    element_id = _target_element_id(target_ref)
    _, element = find_timeline_element(project, element_id)
    creation = element.creation
    if not isinstance(creation, S2VCreation):
        raise ValidationError(
            "仅 creation.type=s2v 的 Element 可以生成数字人视频",
        )
    # Explicit refs win; the element's declared portrait/audio are the
    # defaults so the tool call carries no redundant arguments.
    image_ref = str(
        arguments.get("characterImageRef")
        or creation.portrait_version_id
        or "",
    ).strip()
    audio_ref = str(
        arguments.get("audioAssetRef") or creation.audio_version_id or "",
    ).strip()
    if not image_ref:
        raise ValidationError(
            "s2v_generation 需要人像图：传 characterImageRef 或在 "
            "creation.portrait_version_id 声明（exact 图片 version id）",
        )
    if not audio_ref:
        raise ValidationError(
            "s2v_generation 需要驱动音频：传 audioAssetRef 或在 "
            "creation.audio_version_id 声明（可直接使用 tts_generation "
            "产出的 version）",
        )
    resolution = normalize_s2v_resolution(
        str(arguments.get("resolution") or "480P"),
    )
    (
        image_url,
        image_checksum,
        image_prov,
        image_entry,
    ) = _resolve_single_media_version(
        project=project,
        project_root=project_root,
        version_id=image_ref,
        media_prefix="image/",
        label="characterImageRef",
    )
    (
        audio_url,
        audio_checksum,
        audio_prov,
        audio_entry,
    ) = _resolve_single_media_version(
        project=project,
        project_root=project_root,
        version_id=audio_ref,
        media_prefix="audio/",
        label="audioAssetRef",
    )
    # Task duration metadata follows the (header-corrected) audio duration
    # recorded on the TTS source version; the provider derives the real one.
    audio_version = project.assets.source_versions_by_id.get(audio_ref)
    audio_duration = (
        audio_version.duration_seconds
        if audio_version is not None and audio_version.duration_seconds
        else 5.0
    )
    duration_seconds = max(1, min(60, round(audio_duration)))
    return _ResolvedR2V(
        target_ref=target_ref,
        element_id=element_id,
        element_label=element.label,
        prompt=f"数字人口型合成：{element.label or element_id}",
        ratio=project.settings.aspect_ratio,
        duration_seconds=duration_seconds,
        resolution=resolution,
        watermark=False,
        generate_audio=True,
        reference_version_ids=(image_ref, audio_ref),
        reference_urls=(),
        reference_checksums=(image_checksum, audio_checksum),
        provenance_refs=(image_prov, audio_prov),
        read_set=(image_entry, audio_entry),
        slot_id=f"element:{element_id}:main",
        slot_kind="element_video",
        owner_ref=f"element:{element_id}",
        provider="s2v",
        s2v_image_version_id=image_ref,
        s2v_image_url=image_url,
        s2v_audio_version_id=audio_ref,
        s2v_audio_url=audio_url,
        s2v_resolution=resolution,
    )


def _stage_materialized_video(
    file_store: AssetFileStore,
    materialized: MaterializedVideo,
    *,
    staging_id: str,
) -> StagedAsset:
    """Stream a verified private scratch file into immutable Asset staging."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    else:
        value = materialized.path.lstat()
        if stat.S_ISLNK(value.st_mode):
            raise ValidationError("R2V Asset staging refuses symlink output")
    descriptor = os.open(materialized.path, flags)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise StorageIntegrityError(
                "R2V materialized output is not a private file",
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            staged = file_store.stage_stream(source, staging_id=staging_id)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        staged.sha256 != materialized.sha256
        or staged.size_bytes != materialized.size_bytes
    ):
        file_store.abandon(staged)
        raise StorageIntegrityError("R2V scratch changed during Asset staging")
    return staged


class FileR2VExecutionService:
    """Durable R2V admission and background supervisor for one data root."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        provider: R2VProvider | None = None,
        poll_interval_seconds: float = 2.0,
        poll_lease_seconds: float = 120.0,
        poll_timeout_seconds: float | None = None,
        submit_timeout_seconds: float = _SUBMIT_TIMEOUT_SECONDS,
        submit_claim_seconds: float = _SUBMIT_CLAIM_SECONDS,
        materialize_timeout_seconds: float = _MATERIALIZE_TIMEOUT_SECONDS,
        materialize_claim_seconds: float = _MATERIALIZE_CLAIM_SECONDS,
        materialize_retry_delays: Sequence[float] = _MATERIALIZE_RETRY_DELAYS,
        max_output_bytes: int = _MAX_VIDEO_BYTES,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if poll_lease_seconds <= 0 or submit_timeout_seconds <= 0:
            raise ValueError("provider lease durations must be positive")
        if poll_timeout_seconds is not None and (
            poll_timeout_seconds <= 0
            or poll_timeout_seconds >= poll_lease_seconds
        ):
            raise ValueError(
                "poll timeout must be positive and below its lease",
            )
        if submit_claim_seconds <= submit_timeout_seconds:
            raise ValueError(
                "submit claim must exceed the total submit timeout",
            )
        if materialize_timeout_seconds <= 0:
            raise ValueError("materialize_timeout_seconds must be positive")
        if materialize_claim_seconds <= materialize_timeout_seconds:
            raise ValueError(
                "materialize claim must exceed the total materialize timeout",
            )
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.services = services
        self.provider = provider or ExistingR2VProvider()
        self.executions = ProjectExecutionStore(services.root)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.poll_lease_seconds = float(poll_lease_seconds)
        self.poll_timeout_seconds = float(
            (
                poll_timeout_seconds
                if poll_timeout_seconds is not None
                else min(60.0, poll_lease_seconds * 0.8)
            ),
        )
        self.submit_timeout_seconds = float(submit_timeout_seconds)
        self.submit_claim_seconds = float(submit_claim_seconds)
        self.materialize_timeout_seconds = float(materialize_timeout_seconds)
        self.materialize_claim_seconds = float(materialize_claim_seconds)
        self.materialize_retry_delays = tuple(
            float(delay) for delay in materialize_retry_delays
        )
        self.max_output_bytes = int(max_output_bytes)
        self.clock = clock or time.time
        self.owner_id = f"r2v-supervisor-{uuid4().hex}"
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._job_projects: dict[str, str] = {}
        self._terminal_recovery_jobs: dict[
            tuple[str, str],
            asyncio.Task[None],
        ] = {}

    def _state_store(
        self,
        project_id: str,
        task_id: str,
    ) -> AtomicJsonRecordStore[R2VTaskState]:
        return AtomicJsonRecordStore(
            self.services.projects.project_root(project_id)
            / "runtime"
            / "tasks"
            / task_id
            / "r2v-state.json",
            R2VTaskState,
        )

    def _read_state_sync(self, project_id: str, task_id: str) -> R2VTaskState:
        state = self._state_store(project_id, task_id).read()
        if state.project_id != project_id or state.task_id != task_id:
            raise StorageIntegrityError("R2V Runtime state ownership 损坏")
        return state

    def _update_state_sync(
        self,
        project_id: str,
        task_id: str,
        mutator: Callable[[R2VTaskState], R2VTaskState | Mapping[str, Any]],
    ) -> R2VTaskState:
        with self.services.projects.lifecycle_lock(project_id, shared=True):
            self.services.projects.read(project_id)

            def update(current: R2VTaskState) -> Any:
                if (
                    current.project_id != project_id
                    or current.task_id != task_id
                ):
                    raise StorageIntegrityError(
                        "R2V Runtime state ownership 损坏",
                    )
                candidate = mutator(current)
                if isinstance(candidate, R2VTaskState):
                    dumped = candidate.model_dump(mode="python")
                else:
                    dumped = dict(candidate)
                dumped["updated_at"] = datetime.now(UTC)
                return dumped

            return self._state_store(project_id, task_id).update(update).value

    @staticmethod
    def _frozen_request(
        run: SpecialistRunRecord,
        task: TaskRecord | None = None,
    ) -> dict[str, Any]:
        raw = None if task is None else task.metadata.get("requestSnapshot")
        if not isinstance(raw, Mapping):
            raw = run.metadata.get("requestSnapshot")
        if not isinstance(raw, Mapping):
            raise StorageIntegrityError(
                "R2V admission 缺少 frozen request snapshot",
            )
        request = _json_mapping(raw, label="R2V frozen request snapshot")
        fingerprint = _fingerprint(request)
        expected = (
            task.request_fingerprint
            if task is not None
            else run.request_fingerprint
        )
        if not expected or fingerprint != expected:
            raise StorageIntegrityError("R2V frozen request fingerprint 不一致")
        if (
            request.get("inputGeneration") != run.input_generation
            or request.get("inputEtag") != run.input_etag
            or request.get("targetRef") not in run.target_refs
        ):
            raise StorageIntegrityError("R2V frozen request 与 Run input 不一致")
        if task is not None and (
            task.run_id != run.run_id
            or task.input_generation != run.input_generation
            or task.input_etag != run.input_etag
        ):
            raise StorageIntegrityError("R2V Task 与 frozen Run 不一致")
        return request

    def _task_from_frozen_run(
        self,
        run: SpecialistRunRecord,
        stable: Mapping[str, str],
        request: Mapping[str, Any],
    ) -> TaskRecord:
        key = str(run.caused_by_request_id or "")
        if not key or stable["run_id"] != run.run_id:
            raise StorageIntegrityError(
                "R2V Run 缺少可恢复的 stable idempotency key",
            )
        command_hash = str(run.metadata.get("commandRequestHash") or "")
        if not command_hash:
            raise StorageIntegrityError("R2V Run 缺少 command request hash")
        candidate = TaskRecord(
            task_id=stable["task_id"],
            project_id=run.project_id,
            round_id=run.round_id,
            run_id=run.run_id,
            kind=TaskKind.R2V_GENERATION,
            request_fingerprint=str(run.request_fingerprint),
            idempotency_key=key,
            input_generation=run.input_generation,
            input_etag=run.input_etag,
            expected_target_version=run.input_etag,
            input_refs=[
                str(request["targetRef"]),
                *[str(item) for item in request["referenceVersionIds"]],
            ],
            read_set=list(request["readSet"]),
            caused_by_request_id=run.caused_by_request_id,
            caused_by_message_id=run.caused_by_message_id,
            caused_by_message_seq=run.caused_by_message_seq,
            review_policy=run.review_policy,
            metadata={
                "commandType": CreatorCommandType.GENERATE_R2V_VIDEO.value,
                "targetRef": str(request["targetRef"]),
                "commandRequestHash": command_hash,
                "slotId": str(request["slotId"]),
                "artifactVersionId": str(request["artifactVersionId"]),
                "fileId": str(request["fileId"]),
                "requestSnapshot": dict(request),
            },
        )
        return self.executions.create_task(candidate)

    def _create_or_validate_state_sync(
        self,
        run: SpecialistRunRecord,
        task: TaskRecord,
        request: Mapping[str, Any],
    ) -> R2VTaskState:
        self._ensure_task_scratch_sync(task)
        candidate = R2VTaskState(
            project_id=task.project_id,
            task_id=task.task_id,
            run_id=run.run_id,
            request_fingerprint=task.request_fingerprint,
            request=dict(request),
        )
        with self.services.projects.lifecycle_lock(
            task.project_id,
            shared=True,
        ):
            self.services.projects.read(task.project_id)
            store = self._state_store(task.project_id, task.task_id)
            created = store.try_create(candidate)
            existing = created.value if created is not None else store.read()
            if (
                existing.request_fingerprint != task.request_fingerprint
                or existing.request != dict(request)
                or existing.run_id != run.run_id
            ):
                raise StorageIntegrityError("R2V Runtime state 与 Task 不一致")
            return existing

    def _ensure_task_scratch_sync(self, task: TaskRecord) -> Path:
        """Create and validate the durable scratch owned by one active R2V Task."""

        with self.services.projects.lifecycle_lock(
            task.project_id,
            shared=True,
        ):
            self.services.projects.read(task.project_id)
            with media_task_scope(task.task_id, project_id=task.project_id):
                scratch = task_work_root()
            expected = (
                self.services.projects.project_root(task.project_id)
                / "runtime"
                / "task-work"
                / task.task_id
            )
            if scratch != expected:
                raise StorageIntegrityError("R2V Task scratch 归属路径不一致")
            return scratch

    async def _fail_orphan_run(
        self,
        run: SpecialistRunRecord,
        *,
        code: str,
        message: str,
    ) -> None:
        if run.status in TERMINAL_SPECIALIST_STATUSES:
            return
        try:
            await asyncio.to_thread(
                self.executions.transition_run,
                run.project_id,
                run.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.FAILED,
                updates={
                    "final_marker": "FAILED",
                    "final_summary_text": f"{code}: {message}"[:2000],
                },
            )
        except ExecutionStateConflict:
            pass

    async def _ensure_state_for_task(
        self,
        run: SpecialistRunRecord,
        task: TaskRecord,
    ) -> bool:
        try:
            state = await asyncio.to_thread(
                self._read_state_sync,
                task.project_id,
                task.task_id,
            )
        except RecordNotFoundError:
            state = None
        if state is not None:
            if (
                state.request_fingerprint != task.request_fingerprint
                or _fingerprint(state.request) != task.request_fingerprint
                or state.run_id != run.run_id
            ):
                await self._fail(
                    task,
                    code="R2V_RECOVERY_STATE_MISMATCH",
                    message="R2V durable state ownership/fingerprint 损坏",
                )
                return False
            try:
                await asyncio.to_thread(self._ensure_task_scratch_sync, task)
            except Exception as error:
                await self._fail(
                    task,
                    code="R2V_RECOVERY_SCRATCH_FAILED",
                    message=str(error),
                )
                return False
            return True
        if task.status is TaskStatus.QUEUED:
            try:
                request = self._frozen_request(run, task)
                await asyncio.to_thread(
                    self._create_or_validate_state_sync,
                    run,
                    task,
                    request,
                )
            except Exception as error:
                await self._fail(
                    task,
                    code="R2V_ADMISSION_STATE_REBUILD_FAILED",
                    message=str(error),
                )
                return False
            return True
        if task.status is TaskStatus.RUNNING:
            await self._fail(
                task,
                code="R2V_RECOVERY_STATE_MISSING",
                message=(
                    "RUNNING R2V Task 缺少 durable state；provider 是否已提交不可知，"
                    "拒绝自动重提"
                ),
            )
            return False
        return False

    async def _recover_run_admission_gap(
        self,
        run: SpecialistRunRecord,
    ) -> TaskRecord | None:
        key = str(run.caused_by_request_id or "")
        stable = _ids(run.project_id, key) if key else {}
        if (
            not key
            or stable.get("run_id") != run.run_id
            or run.metadata.get("commandType")
            != CreatorCommandType.GENERATE_R2V_VIDEO.value
        ):
            await self._fail_orphan_run(
                run,
                code="R2V_ADMISSION_IDENTITY_UNRECOVERABLE",
                message="R2V Run 缺少 stable admission identity",
            )
            return None
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                run.project_id,
                stable["task_id"],
            )
        except RecordNotFoundError:
            if run.status in TERMINAL_SPECIALIST_STATUSES:
                return None
            try:
                request = self._frozen_request(run)
                task = await asyncio.to_thread(
                    self._task_from_frozen_run,
                    run,
                    stable,
                    request,
                )
            except Exception as error:
                await self._fail_orphan_run(
                    run,
                    code="R2V_ADMISSION_TASK_REBUILD_FAILED",
                    message=str(error),
                )
                return None
        if (
            task.kind is not TaskKind.R2V_GENERATION
            or task.run_id != run.run_id
        ):
            await self._fail_orphan_run(
                run,
                code="R2V_ADMISSION_TASK_CONFLICT",
                message="stable Task id 已被不相容记录占用",
            )
            return None
        await self._ensure_state_for_task(run, task)
        return await asyncio.to_thread(
            self.executions.get_task,
            run.project_id,
            task.task_id,
        )

    async def dispatch(
        self,
        *,
        project_id: str,
        target_ref: str,
        arguments: Mapping[str, Any],
        idempotency_key: str,
        expected_object_versions: Sequence[str] = (),
        start: bool = True,
        s2v: bool = False,
    ) -> FileR2VDispatch:
        command_hash = _fingerprint(
            {
                "command": CreatorCommandType.GENERATE_R2V_VIDEO.value,
                "targetRef": target_ref,
                "arguments": dict(arguments),
            },
        )
        # Identical retries reuse the same durable slot, so a transient
        # provider failure would otherwise replay the FAILED task forever.
        # Probe a bounded number of derived retry slots for transient
        # failures only; deterministic failures keep the terminal wall.
        stable = _ids(project_id, idempotency_key)
        existing: TaskRecord | None = None
        for attempt in range(MAX_TRANSIENT_RETRY_SLOTS + 1):
            slot_key = transient_retry_slot_key(idempotency_key, attempt)
            stable = _ids(project_id, slot_key)
            try:
                existing = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    stable["task_id"],
                )
            except RecordNotFoundError:
                existing = None
                idempotency_key = slot_key
                break
            self._assert_replay(existing, target_ref, command_hash)
            if existing.status is TaskStatus.FAILED:
                if is_transient_task_error(existing.error):
                    continue
                raise _failed_task_conflict(existing)
            run = await asyncio.to_thread(
                self.executions.get_run,
                project_id,
                str(existing.run_id),
            )
            if existing.status not in _TERMINAL_TASKS:
                await self._ensure_state_for_task(run, existing)
                existing = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    existing.task_id,
                )
            if start and existing.status not in _TERMINAL_TASKS:
                self.start_task(project_id, existing.task_id)
            return self._dispatch_result(existing, stable, replayed=True)
        else:
            raise _failed_task_conflict(existing, exhausted_retries=True)

        try:
            orphan_run = await asyncio.to_thread(
                self.executions.get_run,
                project_id,
                stable["run_id"],
            )
        except RecordNotFoundError:
            orphan_run = None
        if orphan_run is not None:
            self._assert_run_replay(orphan_run, target_ref, command_hash)
            recovered = await self._recover_run_admission_gap(orphan_run)
            if recovered is None:
                raise ConflictError(
                    "R2V admission 在 Run/Task 边界中断且无法安全恢复",
                )
            if start and recovered.status not in _TERMINAL_TASKS:
                self.start_task(project_id, recovered.task_id)
            return self._dispatch_result(recovered, stable, replayed=True)

        # Two independent tool calls may legally submit the same command:
        # an interrupted director gets re-delegated after the next review
        # approval while its first submission is still generating. Their
        # stable ids differ (derived from the tool-call id), so the replay
        # checks above cannot see the first submission — attach to any
        # live task carrying the same command hash instead of paying the
        # provider for an identical video twice.
        in_flight = await asyncio.to_thread(
            self._find_in_flight_duplicate,
            project_id,
            command_hash,
            target_ref,
        )
        if in_flight is not None:
            logger.info(
                "r2v dispatch attached to in-flight duplicate: "
                "project=%s task=%s target=%s",
                _log_safe(project_id),
                _log_safe(in_flight.task_id),
                _log_safe(target_ref),
            )
            if start and in_flight.status not in _TERMINAL_TASKS:
                self.start_task(project_id, in_flight.task_id)
            return self._dispatch_result(in_flight, stable, replayed=True)

        base = await asyncio.to_thread(self.services.projects.read, project_id)
        conflicts = [
            value
            for value in expected_object_versions
            if f"project:{base.etag}:" not in value
        ]
        if conflicts:
            raise ConflictError("R2V 命令目标已被其他写者修改")
        resolved = await asyncio.to_thread(
            _resolve_s2v_request if s2v else _resolve_request,
            snapshot=base,
            project_root=self.services.projects.project_root(project_id),
            target_ref=target_ref,
            arguments=dict(arguments),
        )
        reviews = await asyncio.to_thread(
            self.services.reviews.all_pending,
            project_id,
        )
        assert_media_review_admission(
            reviews=reviews,
            command_type=CreatorCommandType.GENERATE_R2V_VIDEO.value,
            target_ref=resolved.target_ref,
            reference_version_ids=resolved.reference_version_ids,
        )
        request = self._request_payload(base, resolved, stable)
        request_fingerprint = _fingerprint(request)
        logger.info(
            "r2v dispatch: project=%s task=%s target=%s",
            project_id,
            stable["task_id"],
            target_ref,
        )
        run, task = await self._admit(
            base=base,
            resolved=resolved,
            request=request,
            request_fingerprint=request_fingerprint,
            command_hash=command_hash,
            idempotency_key=idempotency_key,
            stable=stable,
        )
        del run
        if start and task.status not in _TERMINAL_TASKS:
            self.start_task(project_id, task.task_id)
        return self._dispatch_result(task, stable, replayed=False)

    @staticmethod
    def _request_payload(
        base: ProjectSnapshot,
        resolved: _ResolvedR2V,
        stable: Mapping[str, str],
    ) -> dict[str, Any]:
        payload = {
            "targetRef": resolved.target_ref,
            "elementId": resolved.element_id,
            "elementLabel": resolved.element_label,
            "prompt": resolved.prompt,
            "ratio": resolved.ratio,
            "durationSeconds": resolved.duration_seconds,
            "resolution": resolved.resolution,
            "watermark": resolved.watermark,
            "generateAudio": resolved.generate_audio,
            "referenceVersionIds": list(resolved.reference_version_ids),
            "referenceUrls": list(resolved.reference_urls),
            "referenceChecksums": list(resolved.reference_checksums),
            "provenanceRefs": list(resolved.provenance_refs),
            "readSet": list(resolved.read_set),
            "slotId": resolved.slot_id,
            "slotKind": resolved.slot_kind,
            "ownerRef": resolved.owner_ref,
            "inputGeneration": base.generation,
            "inputEtag": base.etag,
            "fileId": stable["file_id"],
            "artifactVersionId": stable["artifact_version_id"],
            "transactionId": stable["transaction_id"],
        }
        if resolved.mode != "r2v":
            # Only non-default modes join the frozen request so legacy r2v
            # tasks keep their fingerprint identity across the upgrade.
            payload.update(
                {
                    "mode": resolved.mode,
                    "firstFrameVersionId": resolved.first_frame_version_id,
                    "firstFrameUrl": resolved.first_frame_url,
                    "videoVersionId": resolved.video_version_id,
                    "videoUrl": resolved.video_url,
                },
            )
        if resolved.provider == "s2v":
            payload.update(
                {
                    "provider": "s2v",
                    "s2vImageVersionId": resolved.s2v_image_version_id,
                    "s2vImageUrl": resolved.s2v_image_url,
                    "s2vAudioVersionId": resolved.s2v_audio_version_id,
                    "s2vAudioUrl": resolved.s2v_audio_url,
                    "s2vResolution": resolved.s2v_resolution,
                },
            )
        return payload

    async def _admit(
        self,
        *,
        base: ProjectSnapshot,
        resolved: _ResolvedR2V,
        request: Mapping[str, Any],
        request_fingerprint: str,
        command_hash: str,
        idempotency_key: str,
        stable: Mapping[str, str],
    ) -> tuple[SpecialistRunRecord, TaskRecord]:
        run_candidate = SpecialistRunRecord(
            run_id=stable["run_id"],
            project_id=base.project.project_id,
            round_id=stable["round_id"],
            role=SpecialistRole.R2V_GENERATION_DIRECTOR,
            target_refs=[resolved.target_ref],
            input_generation=base.generation,
            input_etag=base.etag,
            request_fingerprint=request_fingerprint,
            read_set=list(resolved.read_set),
            caused_by_request_id=idempotency_key,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata={
                "commandType": CreatorCommandType.GENERATE_R2V_VIDEO.value,
                "targetRef": resolved.target_ref,
                "commandRequestHash": command_hash,
                "requestSnapshot": dict(request),
            },
        )
        try:
            run = await asyncio.to_thread(
                self.executions.get_run,
                base.project.project_id,
                stable["run_id"],
            )
        except RecordNotFoundError:
            run = await asyncio.to_thread(
                self.executions.create_run,
                run_candidate,
            )
        if (
            run.request_fingerprint != request_fingerprint
            or run.input_etag != base.etag
            or run.target_refs != [resolved.target_ref]
        ):
            raise ConflictError("Idempotency-Key 已用于不同的 R2V Run")

        task_candidate = TaskRecord(
            task_id=stable["task_id"],
            project_id=base.project.project_id,
            round_id=stable["round_id"],
            run_id=stable["run_id"],
            kind=TaskKind.R2V_GENERATION,
            request_fingerprint=request_fingerprint,
            idempotency_key=idempotency_key,
            input_generation=base.generation,
            input_etag=base.etag,
            expected_target_version=base.etag,
            input_refs=[resolved.target_ref, *resolved.reference_version_ids],
            read_set=list(resolved.read_set),
            caused_by_request_id=idempotency_key,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata={
                "commandType": CreatorCommandType.GENERATE_R2V_VIDEO.value,
                "targetRef": resolved.target_ref,
                "commandRequestHash": command_hash,
                "slotId": resolved.slot_id,
                "artifactVersionId": stable["artifact_version_id"],
                "fileId": stable["file_id"],
                "requestSnapshot": dict(request),
            },
        )
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                base.project.project_id,
                stable["task_id"],
            )
        except RecordNotFoundError:
            try:
                task = await asyncio.to_thread(
                    self.executions.create_task,
                    task_candidate,
                )
            except (ExecutionPayloadConflict, ExecutionStateConflict) as error:
                raise ConflictError(str(error)) from error
        if (
            task.request_fingerprint != request_fingerprint
            or task.input_etag != base.etag
            or task.input_refs != task_candidate.input_refs
        ):
            raise ConflictError("Idempotency-Key 已用于不同的 R2V Task")

        await asyncio.to_thread(
            self._create_or_validate_state_sync,
            run,
            task,
            dict(request),
        )
        return run, task

    @staticmethod
    def _assert_replay(
        task: TaskRecord,
        target_ref: str,
        command_hash: str,
    ) -> None:
        if (
            task.kind is not TaskKind.R2V_GENERATION
            or task.metadata.get("commandType")
            != CreatorCommandType.GENERATE_R2V_VIDEO.value
            or task.metadata.get("targetRef") != target_ref
            or task.metadata.get("commandRequestHash") != command_hash
        ):
            raise ConflictError("Idempotency-Key 已用于不同的 R2V 命令")

    @staticmethod
    def _assert_run_replay(
        run: SpecialistRunRecord,
        target_ref: str,
        command_hash: str,
    ) -> None:
        if (
            run.role is not SpecialistRole.R2V_GENERATION_DIRECTOR
            or run.metadata.get("commandType")
            != CreatorCommandType.GENERATE_R2V_VIDEO.value
            or run.metadata.get("targetRef") != target_ref
            or run.metadata.get("commandRequestHash") != command_hash
        ):
            raise ConflictError("Idempotency-Key 已用于不同的 R2V Run")

    def _find_in_flight_duplicate(
        self,
        project_id: str,
        command_hash: str,
        target_ref: str,
    ) -> TaskRecord | None:
        """Return a live R2V Task already generating for this target.

        The command hash covers command type, target and arguments but not
        the caller's idempotency key, so it identifies "the same video"
        across independent submissions — the caller attaches to it.

        A live task for the same target with a *different* hash is a
        conflict, not a sibling: an Element owns exactly one video slot,
        so two concurrent renders make the selected output depend on
        completion order and double the provider bill (field run
        2026-08-11: the scheduler dispatched the committed video_prompt
        while a specialist re-submitted its own inline rewrite 39s
        later — both rendered). The dispatcher fails such submissions
        closed; the caller retries once the in-flight render settles.
        """

        for task in self.executions.list_tasks(project_id):
            if (
                task.kind is not TaskKind.R2V_GENERATION
                or task.status in _TERMINAL_TASKS
            ):
                continue
            if str(task.metadata.get("targetRef") or "") != target_ref:
                continue
            if (
                str(task.metadata.get("commandRequestHash") or "")
                == command_hash
            ):
                return task
            raise ConflictError(
                f"目标 {target_ref} 已有一个不同内容的视频任务在生成中"
                f"（task={task.task_id}）；同一 Element 同时只允许一个在飞渲染，"
                "请等待其完成后再提交（若需替换请先取消在飞任务）",
            )
        return None

    @staticmethod
    def _dispatch_result(
        task: TaskRecord,
        stable: Mapping[str, str],
        *,
        replayed: bool,
    ) -> FileR2VDispatch:
        return FileR2VDispatch(
            task_id=task.task_id,
            run_id=str(task.run_id or ""),
            transaction_id=stable["transaction_id"],
            input_etag=str(task.input_etag or ""),
            replayed=replayed,
        )

    def start_task(
        self,
        project_id: str,
        task_id: str,
    ) -> asyncio.Task[None] | None:
        current = self._jobs.get(task_id)
        if current is not None and not current.done():
            return current
        try:
            task = self.executions.get_task(project_id, task_id)
        except RecordNotFoundError:
            return None
        if task.status in _TERMINAL_TASKS:
            return None
        worker = asyncio.create_task(
            self._drive(project_id, task_id),
            name=f"file-r2v:{task_id}",
        )
        self._jobs[task_id] = worker
        self._job_projects[task_id] = project_id

        def discard(done: asyncio.Task[None]) -> None:
            if self._jobs.get(task_id) is done:
                self._jobs.pop(task_id, None)
                self._job_projects.pop(task_id, None)
            if not done.cancelled():
                try:
                    done.exception()
                except BaseException:
                    pass

        worker.add_done_callback(discard)
        return worker

    def cancel_project(self, project_id: str) -> None:
        """Signal all provider/recovery workers owned by one Project."""

        task_ids = [
            task_id
            for task_id, owner in self._job_projects.items()
            if owner == project_id
        ]
        for task_id in task_ids:
            worker = self._jobs.pop(task_id, None)
            self._job_projects.pop(task_id, None)
            if worker is not None:
                worker.cancel()
        for key, worker in list(self._terminal_recovery_jobs.items()):
            if key[0] != project_id:
                continue
            self._terminal_recovery_jobs.pop(key, None)
            worker.cancel()

    def _schedule_terminal_recovery(
        self,
        project_id: str,
        task_id: str,
    ) -> asyncio.Task[None]:
        """Keep a deferred terminal Task live until its critical lease settles."""

        key = (project_id, task_id)
        current = self._terminal_recovery_jobs.get(key)
        if current is not None and not current.done():
            return current
        worker = asyncio.create_task(
            self._recover_deferred_terminal_task(project_id, task_id),
            name=f"file-r2v-terminal-recovery:{task_id}",
        )
        self._terminal_recovery_jobs[key] = worker

        def discard(done: asyncio.Task[None]) -> None:
            if self._terminal_recovery_jobs.get(key) is done:
                self._terminal_recovery_jobs.pop(key, None)
            if not done.cancelled():
                try:
                    done.exception()
                except BaseException:
                    pass

        worker.add_done_callback(discard)
        return worker

    def notify_terminal_task(
        self,
        task: TaskRecord,
    ) -> asyncio.Task[None] | None:
        """Wake terminal convergence after an API-side Task cancellation."""

        if (
            task.kind is not TaskKind.R2V_GENERATION
            or task.status not in _TERMINAL_TASKS
        ):
            return None
        return self._schedule_terminal_recovery(task.project_id, task.task_id)

    @staticmethod
    def _terminal_barrier_expiry(state: R2VTaskState) -> float | None:
        if state.phase == "SUBMIT_CLAIMED" and state.provider_task_id is None:
            return state.submit_claim_expires_at_epoch
        if state.phase == "PROVIDER_SUCCEEDED":
            return state.materialize_claim_expires_at_epoch
        return None

    async def _recover_deferred_terminal_task(
        self,
        project_id: str,
        task_id: str,
    ) -> None:
        while True:
            try:
                task = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    task_id,
                )
                if task.status not in _TERMINAL_TASKS:
                    return
                if await self._align_state_to_terminal_task(task):
                    await asyncio.to_thread(
                        reconcile_terminal_task_runs,
                        self.services.root,
                        [project_id],
                    )
                    return
                state = await asyncio.to_thread(
                    self._read_state_sync,
                    project_id,
                    task_id,
                )
                expiry = self._terminal_barrier_expiry(state)
                remaining = (
                    max(0.0, expiry - float(self.clock()))
                    if expiry is not None
                    else self.poll_interval_seconds
                )
                delay = min(
                    _TERMINAL_RECOVERY_POLL_SECONDS,
                    max(0.01, remaining),
                )
            except asyncio.CancelledError:
                raise
            except RecordNotFoundError:
                return
            except _R2VClaimLost:
                delay = min(
                    _TERMINAL_RECOVERY_POLL_SECONDS,
                    max(0.01, self.poll_interval_seconds),
                )
            except Exception:
                logger.exception(
                    "deferred R2V terminal recovery failed for %s/%s",
                    _log_safe(project_id),
                    _log_safe(task_id),
                )
                delay = min(
                    _TERMINAL_RECOVERY_POLL_SECONDS,
                    max(0.05, self.poll_interval_seconds),
                )
            await asyncio.sleep(delay)

    async def wait_for_task(
        self,
        project_id: str,
        task_id: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> TaskRecord:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task_id,
            )
            if task.status in _TERMINAL_TASKS:
                worker = self._jobs.get(task_id)
                if worker is not None and not worker.done():
                    remaining = max(
                        0.001,
                        deadline - asyncio.get_running_loop().time(),
                    )
                    await asyncio.wait_for(
                        asyncio.shield(worker),
                        timeout=remaining,
                    )
                    task = await asyncio.to_thread(
                        self.executions.get_task,
                        project_id,
                        task_id,
                    )
                return task
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"R2V Task did not finish: {task_id}")
            await asyncio.sleep(min(self.poll_interval_seconds, 0.05))

    async def _align_state_to_terminal_task(self, task: TaskRecord) -> bool:
        target = {
            TaskStatus.SUCCEEDED: "SUCCEEDED",
            TaskStatus.FAILED: "FAILED",
            TaskStatus.CANCELLED: "CANCELLED",
            TaskStatus.QUARANTINED: "QUARANTINED",
        }.get(task.status)
        if target is None:
            return True
        action = "aligned"

        def align(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal action
            if (
                current.phase == "SUBMIT_CLAIMED"
                and current.provider_task_id is None
                and current.submit_owner
                and current.submit_claim_token
                and (current.submit_claim_expires_at_epoch or 0.0)
                > self.clock()
            ):
                # Provider submission is non-idempotent.  A terminal Task must
                # not erase the only durable ownership anchor before the live
                # owner has bound the provider id.
                action = "defer"
                return current.model_dump(mode="python")
            if task.status is TaskStatus.CANCELLED:
                if current.phase == "QUARANTINED":
                    return current.model_dump(mode="python")
                if current.phase == "PUBLISHED":
                    action = "complete"
                    return current.model_dump(mode="python")
                if current.phase == "PROVIDER_SUCCEEDED":
                    live_claim = bool(
                        current.materialize_owner
                        and current.materialize_claim_token
                        and (current.materialize_claim_expires_at_epoch or 0.0)
                        > self.clock(),
                    )
                    if live_claim:
                        action = "defer"
                        return current.model_dump(mode="python")
                    if current.materialized_result is not None:
                        action = "adopt_cancelled"
                        return current.model_dump(mode="python")
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": target,
                    "submit_owner": None,
                    "submit_claim_token": None,
                    "submit_claim_expires_at_epoch": None,
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "materialize_owner": None,
                    "materialize_claim_token": None,
                    "materialize_claimed_at_epoch": None,
                    "materialize_heartbeat_at_epoch": None,
                    "materialize_claim_expires_at_epoch": None,
                },
            )
            if isinstance(task.result, Mapping):
                dumped["published_result"] = dict(task.result)
            if isinstance(task.error, Mapping):
                dumped["last_error"] = dict(task.error)
            return dumped

        try:
            state = await asyncio.to_thread(
                self._update_state_sync,
                task.project_id,
                task.task_id,
                align,
            )
        except RecordNotFoundError:
            return True
        if task.status is TaskStatus.QUARANTINED:
            await self._ensure_terminal_quarantine_record(task, state)
        if action == "complete":
            await self._complete_success(task, state)
            return True
        if action == "adopt_cancelled":
            return await self._adopt_cancelled_materialized_output(task)
        return action != "defer"

    async def _ensure_terminal_quarantine_record(
        self,
        task: TaskRecord,
        state: R2VTaskState,
    ) -> None:
        """Repair the crash gap between a quarantined Attempt and its record."""

        result = task.result
        if not isinstance(result, Mapping):
            result = state.published_result
        if not isinstance(result, Mapping):
            raise StorageIntegrityError(
                "QUARANTINED R2V Task is missing its quarantined result",
            )
        task_error = task.error if isinstance(task.error, Mapping) else {}
        state_error = (
            state.last_error if isinstance(state.last_error, Mapping) else {}
        )
        reason = str(
            task_error.get("quarantineReason")
            or task_error.get("code")
            or state_error.get("code")
            or "R2V_TERMINAL_QUARANTINED",
        )
        stable = _ids(
            task.project_id,
            str(task.idempotency_key or task.task_id),
        )
        await asyncio.to_thread(
            self.executions.quarantine_task_result,
            task.project_id,
            task.task_id,
            reason=reason,
            result=dict(result),
            quarantine_id=stable["quarantine_id"],
            transition_task=False,
        )

    def _align_terminal_state_locked(self, task: TaskRecord) -> None:
        """Align state to the Task authority while lifecycle_lock is held."""

        target = {
            TaskStatus.SUCCEEDED: "SUCCEEDED",
            TaskStatus.FAILED: "FAILED",
            TaskStatus.CANCELLED: "CANCELLED",
            TaskStatus.QUARANTINED: "QUARANTINED",
        }.get(task.status)
        if target is None:
            return

        def align(current: R2VTaskState) -> Mapping[str, Any]:
            if (
                current.phase == "SUBMIT_CLAIMED"
                and current.provider_task_id is None
                and current.submit_owner
                and current.submit_claim_token
                and (current.submit_claim_expires_at_epoch or 0.0)
                > self.clock()
            ):
                return current.model_dump(mode="python")
            if (
                task.status is TaskStatus.CANCELLED
                and current.phase
                in {"PROVIDER_SUCCEEDED", "PUBLISHED", "QUARANTINED"}
                and (
                    (
                        current.materialize_owner
                        and current.materialize_claim_token
                        and (current.materialize_claim_expires_at_epoch or 0.0)
                        > self.clock()
                    )
                    or current.materialized_result is not None
                    or current.phase == "PUBLISHED"
                    or current.phase == "QUARANTINED"
                )
            ):
                return current.model_dump(mode="python")
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": target,
                    "submit_owner": None,
                    "submit_claim_token": None,
                    "submit_claim_expires_at_epoch": None,
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "materialize_owner": None,
                    "materialize_claim_token": None,
                    "materialize_claimed_at_epoch": None,
                    "materialize_heartbeat_at_epoch": None,
                    "materialize_claim_expires_at_epoch": None,
                    "updated_at": datetime.now(UTC),
                },
            )
            if isinstance(task.result, Mapping):
                dumped["published_result"] = dict(task.result)
            if isinstance(task.error, Mapping):
                dumped["last_error"] = dict(task.error)
            return dumped

        try:
            self._state_store(task.project_id, task.task_id).update(align)
        except RecordNotFoundError:
            return

    def _fail_active_task_locked(
        self,
        task: TaskRecord,
        *,
        error: Mapping[str, Any],
        stable: Mapping[str, str],
    ) -> TaskRecord:
        """Atomically terminalize active Task/state under one Project lock."""

        with self.services.projects.lifecycle_lock(task.project_id):
            latest = self.executions.get_task(
                task.project_id,
                task.task_id,
                _lifecycle_lock_held=True,
            )
            if latest.status is TaskStatus.RUNNING:
                try:
                    state = self._read_state_sync(
                        task.project_id,
                        task.task_id,
                    )
                except RecordNotFoundError:
                    state = None
                try:
                    self.executions.append_attempt(
                        task.project_id,
                        task.task_id,
                        event_id=stable["attempt_failed_event_id"],
                        attempt_id=stable["attempt_id"],
                        status=TaskAttemptStatus.FAILED,
                        provider_task_id=(
                            state.provider_task_id if state else None
                        ),
                        error=dict(error),
                        _lifecycle_lock_held=True,
                    )
                except ExecutionStateConflict:
                    pass
            elif latest.status is TaskStatus.QUEUED:
                try:
                    self.executions.transition_task(
                        task.project_id,
                        task.task_id,
                        expected_status=TaskStatus.QUEUED,
                        status=TaskStatus.FAILED,
                        updates={"error": dict(error)},
                        _lifecycle_lock_held=True,
                    )
                except ExecutionStateConflict:
                    pass
            latest = self.executions.get_task(
                task.project_id,
                task.task_id,
                _lifecycle_lock_held=True,
            )
            if latest.status in _TERMINAL_TASKS:
                self._align_terminal_state_locked(latest)
            return latest

    async def _terminalize_task_from_state(
        self,
        task: TaskRecord,
        state: R2VTaskState,
    ) -> None:
        stable = _ids(
            task.project_id,
            str(task.idempotency_key or task.task_id),
        )
        if state.phase == "SUCCEEDED":
            result = state.published_result
            if not isinstance(result, Mapping):
                await self._fail(
                    task,
                    code="R2V_SUCCEEDED_RESULT_MISSING",
                    message="R2V SUCCEEDED state is missing its published result",
                )
                return
            if task.status is TaskStatus.QUEUED:
                await asyncio.to_thread(
                    self.executions.append_attempt,
                    task.project_id,
                    task.task_id,
                    event_id=stable["attempt_started_event_id"],
                    attempt_id=stable["attempt_id"],
                    status=TaskAttemptStatus.RUNNING,
                    input=state.request,
                )
                task = await asyncio.to_thread(
                    self.executions.get_task,
                    task.project_id,
                    task.task_id,
                )
            await self._converge(task, stable, result)
            return
        if state.phase == "CANCELLED":
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                task = await asyncio.to_thread(
                    self.executions.transition_task,
                    task.project_id,
                    task.task_id,
                    expected_status=task.status,
                    status=TaskStatus.CANCELLED,
                    updates={"error": state.last_error},
                )
            await self._mark_cancelled(task)
            return
        if state.phase == "QUARANTINED":
            result = state.published_result
            if not isinstance(result, Mapping):
                await self._fail(
                    task,
                    code="R2V_QUARANTINE_RESULT_MISSING",
                    message="R2V QUARANTINED state is missing its result",
                )
                return
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                task = await asyncio.to_thread(
                    self.executions.transition_task,
                    task.project_id,
                    task.task_id,
                    expected_status=task.status,
                    status=TaskStatus.QUARANTINED,
                    updates={
                        "result": dict(result),
                        "error": state.last_error,
                    },
                )
            await self._quarantine(
                task,
                stable,
                result=result,
                reason=str(
                    (state.last_error or {}).get("code") or "QUARANTINED",
                ),
                run_status=SpecialistRunStatus.STALE,
            )

    async def _drive(self, project_id: str, task_id: str) -> None:
        try:
            while True:
                task = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    task_id,
                )
                if task.status in _TERMINAL_TASKS:
                    aligned = await self._align_state_to_terminal_task(task)
                    if not aligned:
                        self._schedule_terminal_recovery(project_id, task_id)
                    await asyncio.to_thread(
                        reconcile_terminal_task_runs,
                        self.services.root,
                        [project_id],
                    )
                    return
                try:
                    state = await asyncio.to_thread(
                        self._read_state_sync,
                        project_id,
                        task_id,
                    )
                except RecordNotFoundError:
                    await self._fail(
                        task,
                        code="R2V_RECOVERY_STATE_MISSING",
                        message="R2V Task 缺少 durable state，已 fail-closed",
                    )
                    return
                if (
                    state.request_fingerprint != task.request_fingerprint
                    or _fingerprint(state.request) != task.request_fingerprint
                ):
                    await self._fail(
                        task,
                        code="R2V_RECOVERY_STATE_MISMATCH",
                        message="R2V durable state fingerprint 损坏",
                    )
                    return
                if state.phase == "FAILED":
                    detail = state.last_error or {}
                    await self._fail(
                        task,
                        code=str(detail.get("code") or "R2V_STATE_FAILED"),
                        message=str(
                            detail.get("message") or "R2V state failed",
                        ),
                        retryable=bool(detail.get("retryable")),
                    )
                    return
                if state.phase == "CANCELLED":
                    await self._terminalize_task_from_state(task, state)
                    return
                if state.phase == "QUARANTINED":
                    await self._terminalize_task_from_state(task, state)
                    return
                if state.phase == "SUCCEEDED":
                    await self._terminalize_task_from_state(task, state)
                    return
                if state.phase == "ADMITTED":
                    claimed = await self._submit(task, state)
                    if claimed:
                        continue
                elif (
                    state.phase == "SUBMIT_CLAIMED"
                    and not state.provider_task_id
                ):
                    deadline = state.submit_claim_expires_at_epoch or 0.0
                    if self.clock() >= deadline:
                        accepted = (
                            await self._expire_submit_claim_if_still_stale(
                                task,
                            )
                        )
                        if accepted:
                            await self._fail(
                                task,
                                code="R2V_PROVIDER_SUBMISSION_UNRECOVERABLE",
                                message=(
                                    "provider submission claim survived without a "
                                    "durable provider task id; refusing duplicate submit"
                                ),
                            )
                            return
                elif state.phase in {"PROVIDER_SUCCEEDED", "PUBLISHED"}:
                    await self._complete_success(task, state)
                    continue
                elif state.provider_task_id:
                    await self._poll_once(task, state)
                    continue
                elif state.phase not in _ACTIVE_PHASES:
                    return
                await asyncio.sleep(self.poll_interval_seconds)
        except _R2VClaimLost:
            # Another live supervisor owns the durable claim.  A stale worker
            # must exit without changing Task, Run, state, or published files.
            return
        except asyncio.CancelledError:
            # Process shutdown intentionally preserves durable active state.
            raise
        except Exception as error:
            # The durable Task record keeps the failure, but without this
            # line the server log showed a RUNNING -> FAILED transition with
            # no ERROR anywhere — diagnosing field failures required digging
            # through runtime task.json files.
            logger.error(
                "r2v supervisor failed: project=%s task=%s error=%s",
                _log_safe(project_id),
                _log_safe(task_id),
                _log_safe(error),
                exc_info=True,
            )
            try:
                task = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    task_id,
                )
                await self._fail(
                    task,
                    code="R2V_SUPERVISOR_FAILED",
                    message=str(error),
                    retryable=_is_transient_materialize_error(error),
                    error=error,
                )
            except BaseException:
                logger.exception(
                    "r2v supervisor failure could not be persisted: "
                    "project=%s task=%s",
                    _log_safe(project_id),
                    _log_safe(task_id),
                )

    async def _submit(self, task: TaskRecord, state: R2VTaskState) -> bool:
        now = float(self.clock())
        token = uuid4().hex

        def claim(current: R2VTaskState) -> Mapping[str, Any]:
            if current.phase != "ADMITTED":
                return current.model_dump(mode="python")
            latest = self.executions.get_task(
                task.project_id,
                task.task_id,
                _lifecycle_lock_held=True,
            )
            if latest.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                return current.model_dump(mode="python")
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "SUBMIT_CLAIMED",
                    "submit_owner": self.owner_id,
                    "submit_claim_token": token,
                    "submit_claimed_at_epoch": now,
                    "submit_heartbeat_at_epoch": now,
                    "submit_claim_expires_at_epoch": now
                    + self.submit_claim_seconds,
                },
            )
            return dumped

        claimed = await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            claim,
        )
        if (
            claimed.phase != "SUBMIT_CLAIMED"
            or claimed.submit_owner != self.owner_id
        ):
            return False
        heartbeat = asyncio.create_task(
            self._heartbeat_submit_claim(task, claimed),
            name=f"r2v-submit-heartbeat:{task.task_id}",
        )
        request = claimed.request
        try:
            task = await self._prepare_submit_claim(task, request)
        except BaseException:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            raise
        try:
            await self._require_live_submit_claim(
                task,
                claimed,
                require_active_task=True,
            )

            async def invoke_provider() -> str:
                with media_task_scope(
                    task.task_id,
                    project_id=task.project_id,
                ):
                    if str(request.get("provider") or "") == "s2v":
                        return await self.provider.submit_s2v(
                            image_url=str(request["s2vImageUrl"]),
                            audio_url=str(request["s2vAudioUrl"]),
                            resolution=str(
                                request.get("s2vResolution") or "480P",
                            ),
                        )
                    request_mode = str(request.get("mode") or "r2v")
                    extra_arguments: dict[str, Any] = {}
                    if request_mode != "r2v":
                        # Passed only for explicit modes so injected test
                        # providers with the legacy signature keep working.
                        extra_arguments = {
                            "mode": request_mode,
                            "first_frame_url": (
                                str(request["firstFrameUrl"])
                                if request.get("firstFrameUrl")
                                else None
                            ),
                            "video_url": (
                                str(request["videoUrl"])
                                if request.get("videoUrl")
                                else None
                            ),
                        }
                    return await self.provider.submit(
                        prompt=str(request["prompt"]),
                        reference_image_urls=tuple(request["referenceUrls"]),
                        ratio=str(request["ratio"]),
                        duration_seconds=int(request["durationSeconds"]),
                        resolution=str(request["resolution"]),
                        watermark=bool(request["watermark"]),
                        generate_audio=bool(request["generateAudio"]),
                        **extra_arguments,
                    )

            provider_task_id = await asyncio.wait_for(
                invoke_provider(),
                timeout=self.submit_timeout_seconds,
            )
            provider_task_id = str(provider_task_id).strip()
            if not provider_task_id:
                raise ValidationError("R2V provider 返回空 task id")

            def bind(current: R2VTaskState) -> Mapping[str, Any]:
                if not self._owns_live_submit_claim(current, claimed):
                    raise _R2VClaimLost("R2V provider id bind claim lost")
                dumped = current.model_dump(mode="python")
                dumped.update(
                    {
                        "phase": "POLLING",
                        "provider_task_id": provider_task_id,
                        "next_poll_at_epoch": float(self.clock()),
                        "submit_claim_token": None,
                        "submit_claim_expires_at_epoch": None,
                    },
                )
                return dumped

            # Binding the provider id is part of the non-idempotent submission
            # critical section.  Keep the durable owner heartbeat alive until
            # this CAS has completed so another supervisor cannot observe an
            # expired claim between provider acceptance and id persistence.
            await asyncio.to_thread(
                self._update_state_sync,
                task.project_id,
                task.task_id,
                bind,
            )
        except _R2VClaimLost:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._mark_submit_failed_if_owned(task, claimed, str(error))
            await self._fail(
                task,
                code="R2V_PROVIDER_SUBMISSION_FAILED",
                message=str(error),
            )
            return True
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        latest = await asyncio.to_thread(
            self.executions.get_task,
            task.project_id,
            task.task_id,
        )
        if latest.status is TaskStatus.RUNNING:
            await asyncio.to_thread(
                self.executions.transition_task,
                task.project_id,
                task.task_id,
                expected_status=TaskStatus.RUNNING,
                status=TaskStatus.RUNNING,
                updates={
                    "progress": 0.05,
                    "metadata": {
                        **latest.metadata,
                        "providerTaskId": provider_task_id,
                    },
                },
            )
        run = await asyncio.to_thread(
            self.executions.get_run,
            task.project_id,
            str(task.run_id),
        )
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            await asyncio.to_thread(
                self.executions.transition_run,
                task.project_id,
                run.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.WAITING_RUNTIME,
            )
        return True

    async def _prepare_submit_claim(
        self,
        task: TaskRecord,
        request: Mapping[str, Any],
    ) -> TaskRecord:
        run = await asyncio.to_thread(
            self.executions.get_run,
            task.project_id,
            str(task.run_id),
        )
        if run.status in {
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.QUEUED_CAPACITY,
        }:
            await asyncio.to_thread(
                self.executions.transition_run,
                task.project_id,
                run.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.RUNNING_MODEL,
            )
        if task.status is TaskStatus.QUEUED:
            stable = _ids(
                task.project_id,
                str(task.idempotency_key or task.task_id),
            )
            await asyncio.to_thread(
                self.executions.append_attempt,
                task.project_id,
                task.task_id,
                event_id=stable["attempt_started_event_id"],
                attempt_id=stable["attempt_id"],
                status=TaskAttemptStatus.RUNNING,
                input=request,
            )
            task = await asyncio.to_thread(
                self.executions.get_task,
                task.project_id,
                task.task_id,
            )
        return task

    def _owns_live_submit_claim(
        self,
        current: R2VTaskState,
        claim: R2VTaskState,
    ) -> bool:
        return bool(
            current.phase == "SUBMIT_CLAIMED"
            and current.provider_task_id is None
            and current.submit_owner == self.owner_id
            and current.submit_claim_token
            and current.submit_claim_token == claim.submit_claim_token
            and (current.submit_claim_expires_at_epoch or 0.0) > self.clock(),
        )

    async def _require_live_submit_claim(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        *,
        require_active_task: bool,
    ) -> None:
        current = await asyncio.to_thread(
            self._read_state_sync,
            task.project_id,
            task.task_id,
        )
        if not self._owns_live_submit_claim(current, claim):
            raise _R2VClaimLost("R2V submit claim ownership lost")
        if require_active_task:
            latest = await asyncio.to_thread(
                self.executions.get_task,
                task.project_id,
                task.task_id,
            )
            if latest.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                raise _R2VClaimLost("R2V submit Task is no longer active")

    async def _heartbeat_submit_claim(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
    ) -> None:
        interval = min(30.0, max(0.01, self.submit_claim_seconds / 4.0))
        while True:
            await asyncio.sleep(interval)
            now = float(self.clock())
            owned = False

            def heartbeat(current: R2VTaskState) -> Mapping[str, Any]:
                nonlocal owned
                if not self._owns_live_submit_claim(current, claim):
                    return current.model_dump(mode="python")
                owned = True
                dumped = current.model_dump(mode="python")
                dumped.update(
                    {
                        "submit_heartbeat_at_epoch": now,
                        "submit_claim_expires_at_epoch": (
                            now + self.submit_claim_seconds
                        ),
                    },
                )
                return dumped

            await asyncio.to_thread(
                self._update_state_sync,
                task.project_id,
                task.task_id,
                heartbeat,
            )
            if not owned:
                return

    async def _mark_submit_failed_if_owned(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        message: str,
    ) -> bool:
        accepted = False

        def fail(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_submit_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "FAILED",
                    "submit_owner": None,
                    "submit_claim_token": None,
                    "submit_claim_expires_at_epoch": None,
                    "last_error": {
                        "code": "R2V_PROVIDER_SUBMISSION_FAILED",
                        "message": message[:2000],
                    },
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            fail,
        )
        return accepted

    async def _expire_submit_claim_if_still_stale(
        self,
        task: TaskRecord,
    ) -> bool:
        accepted = False
        now = float(self.clock())

        def expire(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if (
                current.phase != "SUBMIT_CLAIMED"
                or current.provider_task_id is not None
                or (current.submit_claim_expires_at_epoch or 0.0) > now
            ):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "FAILED",
                    "submit_owner": None,
                    "submit_claim_token": None,
                    "submit_claim_expires_at_epoch": None,
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            expire,
        )
        return accepted

    async def _claim_poll(
        self,
        task: TaskRecord,
    ) -> R2VTaskState | None:
        now = float(self.clock())
        claimed = False
        token = uuid4().hex

        def claim(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal claimed
            if current.phase != "POLLING" or not current.provider_task_id:
                return current.model_dump(mode="python")
            if (
                current.next_poll_at_epoch is not None
                and now < current.next_poll_at_epoch
            ):
                return current.model_dump(mode="python")
            if (
                current.poll_lease_owner not in {None, self.owner_id}
                and (current.poll_lease_expires_at_epoch or 0.0) > now
            ):
                return current.model_dump(mode="python")
            claimed = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "poll_lease_owner": self.owner_id,
                    "poll_lease_token": token,
                    "poll_lease_expires_at_epoch": now
                    + self.poll_lease_seconds,
                },
            )
            return dumped

        state = await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            claim,
        )
        return state if claimed else None

    def _owns_live_poll_claim(
        self,
        current: R2VTaskState,
        claim: R2VTaskState,
    ) -> bool:
        return bool(
            current.phase == "POLLING"
            and current.provider_task_id == claim.provider_task_id
            and current.poll_lease_owner == self.owner_id
            and current.poll_lease_token
            and current.poll_lease_token == claim.poll_lease_token
            and (current.poll_lease_expires_at_epoch or 0.0) > self.clock(),
        )

    async def _heartbeat_poll_claim(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
    ) -> None:
        interval = min(30.0, max(0.01, self.poll_lease_seconds / 4.0))
        while True:
            await asyncio.sleep(interval)
            owned = False

            def heartbeat(current: R2VTaskState) -> Mapping[str, Any]:
                nonlocal owned
                if not self._owns_live_poll_claim(current, claim):
                    return current.model_dump(mode="python")
                owned = True
                dumped = current.model_dump(mode="python")
                dumped["poll_lease_expires_at_epoch"] = (
                    float(self.clock()) + self.poll_lease_seconds
                )
                return dumped

            await asyncio.to_thread(
                self._update_state_sync,
                task.project_id,
                task.task_id,
                heartbeat,
            )
            if not owned:
                return

    async def _poll_once(self, task: TaskRecord, state: R2VTaskState) -> None:
        del state
        claim = await self._claim_poll(task)
        if claim is None:
            await asyncio.sleep(self.poll_interval_seconds)
            return
        assert claim.provider_task_id is not None
        heartbeat = asyncio.create_task(
            self._heartbeat_poll_claim(task, claim),
            name=f"r2v-poll-heartbeat:{task.task_id}",
        )
        try:

            async def invoke_provider() -> Mapping[str, Any]:
                with media_task_scope(
                    task.task_id,
                    project_id=task.project_id,
                ):
                    if str(claim.request.get("provider") or "") == "s2v":
                        return await self.provider.poll_s2v(
                            claim.provider_task_id,
                        )
                    return await self.provider.poll(claim.provider_task_id)

            raw = await asyncio.wait_for(
                invoke_provider(),
                timeout=self.poll_timeout_seconds,
            )
            result = _durable_provider_result(
                _json_mapping(raw, label="R2V provider poll result"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if getattr(error, "retryable", True) is False:
                if await self._mark_poll_failed_if_owned(
                    task,
                    claim,
                    str(error),
                ):
                    await self._fail(
                        task,
                        code="R2V_PROVIDER_POLL_FAILED",
                        message=str(error),
                    )
                return
            await self._release_poll_with_error(task, claim, str(error))
            return
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

        status = str(result.get("status") or "UNKNOWN").upper()
        if status in {"QUEUED", "PENDING", "RUNNING", "PROCESSING", "UNKNOWN"}:
            await self._record_running_poll(task, claim, result)
            return
        if status != "SUCCEEDED":
            message = str(result.get("error") or f"provider status={status}")
            if await self._mark_poll_failed_if_owned(task, claim, message):
                await self._fail(
                    task,
                    code="R2V_PROVIDER_FAILED",
                    message=message,
                )
            return

        accepted = False

        def success(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_poll_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "PROVIDER_SUCCEEDED",
                    "provider_result": result,
                    "last_poll_at_epoch": float(self.clock()),
                    "next_poll_at_epoch": None,
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "last_error": None,
                },
            )
            return dumped

        state = await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            success,
        )
        if accepted:
            await self._complete_success(task, state)

    async def _record_running_poll(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        result: Mapping[str, Any],
    ) -> None:
        now = float(self.clock())
        accepted = False

        def update(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_poll_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "last_poll_at_epoch": now,
                    "next_poll_at_epoch": now + self.poll_interval_seconds,
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "last_error": None,
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            update,
        )
        if not accepted:
            return
        latest = await asyncio.to_thread(
            self.executions.get_task,
            task.project_id,
            task.task_id,
        )
        if latest.status is TaskStatus.RUNNING:
            progress = result.get("progress")
            try:
                normalized = max(0.05, min(0.89, float(progress)))
            except (TypeError, ValueError):
                normalized = latest.progress or 0.05
            # Skip the no-op CAS write: providers rarely report progress, so
            # this used to rewrite the Task record (under the exclusive
            # project lock, with a task-transition log line) on every ~2s
            # poll with an unchanged payload — field logs showed ~1.8k such
            # writes per day and they were the dominant lock hot spot.
            if latest.progress == normalized:
                return
            await asyncio.to_thread(
                self.executions.transition_task,
                task.project_id,
                task.task_id,
                expected_status=TaskStatus.RUNNING,
                status=TaskStatus.RUNNING,
                updates={"progress": normalized},
            )

    async def _release_poll_with_error(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        message: str,
    ) -> None:
        now = float(self.clock())

        def update(current: R2VTaskState) -> Mapping[str, Any]:
            if not self._owns_live_poll_claim(current, claim):
                return current.model_dump(mode="python")
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "last_poll_at_epoch": now,
                    "next_poll_at_epoch": now + self.poll_interval_seconds,
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "last_error": {
                        "code": "R2V_PROVIDER_POLL_RETRY",
                        "message": message[:2000],
                    },
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            update,
        )

    async def _mark_poll_failed_if_owned(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        message: str,
    ) -> bool:
        accepted = False

        def update(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_poll_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "FAILED",
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "last_error": {
                        "code": "R2V_PROVIDER_FAILED",
                        "message": message[:2000],
                    },
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            update,
        )
        return accepted

    async def _claim_materialize(
        self,
        task: TaskRecord,
    ) -> R2VTaskState | None:
        now = float(self.clock())
        claimed = False
        token = uuid4().hex

        def claim(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal claimed
            if current.phase != "PROVIDER_SUCCEEDED":
                return current.model_dump(mode="python")
            if current.provider_result is None:
                raise StorageIntegrityError(
                    "R2V PROVIDER_SUCCEEDED state is missing provider result",
                )
            owner = current.materialize_owner
            expires = current.materialize_claim_expires_at_epoch or 0.0
            if owner not in {None, self.owner_id} and now < expires:
                return current.model_dump(mode="python")
            claimed = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "materialize_owner": self.owner_id,
                    "materialize_claim_token": token,
                    "materialize_claimed_at_epoch": (
                        current.materialize_claimed_at_epoch
                        if owner == self.owner_id
                        else now
                    ),
                    "materialize_heartbeat_at_epoch": now,
                    "materialize_claim_expires_at_epoch": (
                        now + self.materialize_claim_seconds
                    ),
                },
            )
            return dumped

        state = await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            claim,
        )
        if not claimed or state.materialize_owner != self.owner_id:
            return None
        return state

    def _owns_live_materialize_claim(
        self,
        current: R2VTaskState,
        claim: R2VTaskState,
    ) -> bool:
        return bool(
            current.phase == "PROVIDER_SUCCEEDED"
            and current.materialize_owner == self.owner_id
            and current.materialize_claim_token
            and current.materialize_claim_token
            == claim.materialize_claim_token
            and (current.materialize_claim_expires_at_epoch or 0.0)
            > self.clock(),
        )

    async def _require_live_materialize_claim(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
    ) -> None:
        current = await asyncio.to_thread(
            self._read_state_sync,
            task.project_id,
            task.task_id,
        )
        if not self._owns_live_materialize_claim(current, claim):
            raise _R2VClaimLost("R2V materialize claim ownership lost")

    async def _heartbeat_materialize_claim(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
    ) -> None:
        interval = min(30.0, max(0.01, self.materialize_claim_seconds / 4.0))
        while True:
            await asyncio.sleep(interval)
            now = float(self.clock())
            owned = False

            def heartbeat(current: R2VTaskState) -> Mapping[str, Any]:
                nonlocal owned
                if not self._owns_live_materialize_claim(current, claim):
                    return current.model_dump(mode="python")
                owned = True
                dumped = current.model_dump(mode="python")
                dumped.update(
                    {
                        "materialize_heartbeat_at_epoch": now,
                        "materialize_claim_expires_at_epoch": (
                            now + self.materialize_claim_seconds
                        ),
                    },
                )
                return dumped

            await asyncio.to_thread(
                self._update_state_sync,
                task.project_id,
                task.task_id,
                heartbeat,
            )
            if not owned:
                return

    async def _release_materialize_claim(self, task: TaskRecord) -> None:
        def release(current: R2VTaskState) -> Mapping[str, Any]:
            if current.materialize_owner != self.owner_id:
                return current.model_dump(mode="python")
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "materialize_owner": None,
                    "materialize_claim_token": None,
                    "materialize_claimed_at_epoch": None,
                    "materialize_heartbeat_at_epoch": None,
                    "materialize_claim_expires_at_epoch": None,
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            release,
        )

    @staticmethod
    def _provider_duration(
        state: R2VTaskState,
        request: Mapping[str, Any],
    ) -> float:
        if state.provider_result is None:
            raise StorageIntegrityError(
                "R2V PROVIDER_SUCCEEDED state is missing provider result",
            )
        raw_duration = state.provider_result.get("durationSeconds")
        try:
            duration = (
                float(raw_duration)
                if raw_duration is not None
                else float(request["durationSeconds"])
            )
        except (TypeError, ValueError) as error:
            raise ValidationError("R2V provider durationSeconds 非法") from error
        if duration <= 0:
            raise ValidationError("R2V provider durationSeconds 必须为正数")
        return duration

    def _build_materialized_publication(
        self,
        task: TaskRecord,
        state: R2VTaskState,
        *,
        stable: Mapping[str, str],
        materialized: MaterializedVideo,
        actual_duration: float,
    ) -> tuple[IndexedFile, dict[str, Any]]:
        request = state.request
        if state.provider_result is None:
            raise StorageIntegrityError(
                "R2V materialize claim has no provider result",
            )
        timestamp = datetime.now(UTC)
        relative_uri = PurePosixPath(
            "assets",
            "artifacts",
            f"{stable['file_id']}{materialized.path.suffix}",
        ).as_posix()
        indexed = IndexedFile(
            file_id=stable["file_id"],
            kind="artifact_payload",
            relative_uri=relative_uri,
            sha256=materialized.sha256,
            size_bytes=materialized.size_bytes,
            media_type=materialized.media_type,
            created_at=timestamp,
        )
        artifact = ArtifactVersion(
            version_id=stable["artifact_version_id"],
            slot_id=str(request["slotId"]),
            kind=str(request["slotKind"]),
            owner_ref=str(request["ownerRef"]),
            name=(
                f"{str(request.get('elementLabel') or request['elementId'])} R2V 视频"
            ),
            file_id=stable["file_id"],
            checksum=materialized.sha256,
            based_on_generation=task.input_generation or 0,
            provenance_refs=list(request["provenanceRefs"]),
            duration_seconds=actual_duration,
            input_fingerprint=task.request_fingerprint,
            created_at=timestamp,
            metadata={
                "taskId": task.task_id,
                "runId": task.run_id,
                "commandType": CreatorCommandType.GENERATE_R2V_VIDEO.value,
                "targetRef": str(request["targetRef"]),
                "providerTaskId": state.provider_task_id,
                "generateAudio": bool(request.get("generateAudio", True)),
                "provider": {
                    key: value
                    for key, value in state.provider_result.items()
                    if key
                    not in {
                        "url",
                        "result_url",
                        "video_url",
                        "path",
                        "output_path",
                    }
                },
            },
        )
        published = {
            "taskId": task.task_id,
            "runId": task.run_id,
            "transactionId": stable["transaction_id"],
            "commandType": CreatorCommandType.GENERATE_R2V_VIDEO.value,
            "targetRef": request["targetRef"],
            "providerTaskId": state.provider_task_id,
            "indexedFile": indexed.model_dump(mode="json"),
            "artifactVersion": artifact.model_dump(mode="json"),
            "outputRef": f"artifact-version:{artifact.version_id}",
        }
        return indexed, published

    async def _materialize_video_with_retry(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
    ) -> MaterializedVideo:
        """Download the provider result with bounded transient retries.

        The provider already finished the expensive generation; a flaky
        download must not terminalize the Task and waste that result.
        """

        delays = self.materialize_retry_delays
        for attempt in range(len(delays) + 1):
            try:
                return await materialize_r2v_video(
                    claim.provider_result,
                    project_root=self.services.projects.project_root(
                        task.project_id,
                    ),
                    project_id=task.project_id,
                    task_id=task.task_id,
                    max_bytes=self.max_output_bytes,
                    total_timeout_seconds=self.materialize_timeout_seconds,
                    request_headers=_provider_download_headers(
                        claim.provider_result,
                    ),
                )
            except Exception as error:
                if attempt >= len(delays) or not (
                    _is_transient_materialize_error(error)
                ):
                    raise
                logger.warning(
                    "r2v materialize transient failure, retrying: "
                    "project=%s task=%s attempt=%d error=%s",
                    task.project_id,
                    task.task_id,
                    attempt + 1,
                    _log_safe(str(error)),
                )
                await asyncio.sleep(delays[attempt])
                await self._require_live_materialize_claim(task, claim)
        raise StorageIntegrityError("unreachable materialize retry state")

    async def _persist_materialized_result(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        descriptor: Mapping[str, Any],
    ) -> None:
        accepted = False

        def update(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_materialize_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped["materialized_result"] = dict(descriptor)
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            update,
        )
        if not accepted:
            raise _R2VClaimLost("R2V materialize descriptor claim lost")

    async def _mark_published_owned(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        published: Mapping[str, Any],
    ) -> dict[str, Any]:
        accepted = False

        def update(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_materialize_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "PUBLISHED",
                    "published_result": dict(published),
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "materialize_owner": None,
                    "materialize_claim_token": None,
                    "materialize_claimed_at_epoch": None,
                    "materialize_heartbeat_at_epoch": None,
                    "materialize_claim_expires_at_epoch": None,
                },
            )
            return dumped

        state = await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            update,
        )
        if not accepted or state.published_result is None:
            raise _R2VClaimLost("R2V published-state claim lost")
        return dict(state.published_result)

    async def _mark_cancelled_output_missing_owned(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        *,
        code: str,
        message: str,
    ) -> None:
        accepted = False

        def update(current: R2VTaskState) -> Mapping[str, Any]:
            nonlocal accepted
            if not self._owns_live_materialize_claim(current, claim):
                return current.model_dump(mode="python")
            accepted = True
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "CANCELLED",
                    "last_error": {
                        "code": code,
                        "message": message[:2000],
                    },
                    "materialize_owner": None,
                    "materialize_claim_token": None,
                    "materialize_claimed_at_epoch": None,
                    "materialize_heartbeat_at_epoch": None,
                    "materialize_claim_expires_at_epoch": None,
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            update,
        )
        if not accepted:
            raise _R2VClaimLost("R2V cancelled-output claim lost")

    @staticmethod
    def _validated_materialized_publication(
        state: R2VTaskState,
        task: TaskRecord,
        stable: Mapping[str, str],
    ) -> tuple[IndexedFile, dict[str, Any]] | None:
        descriptor = state.materialized_result
        if not isinstance(descriptor, Mapping):
            return None
        raw_published = descriptor.get("publishedResult")
        if not isinstance(raw_published, Mapping):
            raise StorageIntegrityError(
                "R2V materialized descriptor is corrupt",
            )
        published = _json_mapping(
            raw_published,
            label="R2V materialized publication",
        )
        if (
            published.get("taskId") != task.task_id
            or published.get("runId") != task.run_id
            or published.get("transactionId") != stable["transaction_id"]
        ):
            raise StorageIntegrityError(
                "R2V materialized publication ownership mismatch",
            )
        indexed = IndexedFile.model_validate(published.get("indexedFile"))
        if indexed.file_id != stable["file_id"]:
            raise StorageIntegrityError(
                "R2V materialized IndexedFile id mismatch",
            )
        try:
            descriptor_size = int(descriptor.get("sizeBytes"))
        except (TypeError, ValueError) as error:
            raise StorageIntegrityError(
                "R2V materialized descriptor size is corrupt",
            ) from error
        if (
            str(descriptor.get("sha256") or "").casefold()
            != indexed.sha256.casefold()
            or descriptor_size != indexed.size_bytes
            or str(descriptor.get("mediaType") or "").casefold()
            != indexed.media_type.casefold()
            or not str(descriptor.get("path") or "").strip()
        ):
            raise StorageIntegrityError(
                "R2V materialized descriptor does not match IndexedFile",
            )
        return indexed, published

    async def _materialize_descriptor_scratch(
        self,
        task: TaskRecord,
        state: R2VTaskState,
    ) -> MaterializedVideo | None:
        """Securely copy and revalidate a durable Task-scratch descriptor."""

        descriptor = state.materialized_result
        if not isinstance(descriptor, Mapping):
            return None
        try:
            recovered = await materialize_r2v_video(
                {
                    "path": str(descriptor["path"]),
                    "checksum": str(descriptor["sha256"]),
                    "media_type": str(descriptor["mediaType"]),
                },
                project_root=self.services.projects.project_root(
                    task.project_id,
                ),
                project_id=task.project_id,
                task_id=task.task_id,
                max_bytes=self.max_output_bytes,
                total_timeout_seconds=self.materialize_timeout_seconds,
            )
        except ValidationError as error:
            # A dead owner may have already removed its private scratch file.
            # Only genuine absence falls through to the provider URL; unsafe
            # paths, links, MIME mismatches and other integrity failures do not.
            if isinstance(error.__cause__, FileNotFoundError):
                return None
            raise
        try:
            expected_size = int(descriptor["sizeBytes"])
            expected_sha = str(descriptor["sha256"]).casefold()
            expected_media_type = str(descriptor["mediaType"]).casefold()
            expected_container = str(descriptor["container"]).casefold()
        except (KeyError, TypeError, ValueError) as error:
            recovered.path.unlink(missing_ok=True)
            raise StorageIntegrityError(
                "R2V materialized descriptor integrity fields are corrupt",
            ) from error
        if (
            recovered.size_bytes != expected_size
            or recovered.sha256.casefold() != expected_sha
            or recovered.media_type.casefold() != expected_media_type
            or recovered.container.casefold() != expected_container
        ):
            recovered.path.unlink(missing_ok=True)
            raise StorageIntegrityError(
                "R2V recovered scratch does not match materialized descriptor",
            )
        return recovered

    async def _adopt_cancelled_materialized_output(
        self,
        task: TaskRecord,
    ) -> bool:
        """Adopt an already-published late result without downloading again."""

        claim = await self._claim_materialize(task)
        if claim is None:
            return False
        heartbeat = asyncio.create_task(
            self._heartbeat_materialize_claim(task, claim),
            name=f"r2v-cancelled-adopt-heartbeat:{task.task_id}",
        )
        published: dict[str, Any] | None = None
        try:
            try:
                recovered = self._validated_materialized_publication(
                    claim,
                    task,
                    _ids(
                        task.project_id,
                        str(task.idempotency_key or task.task_id),
                    ),
                )
                if recovered is None:
                    raise StorageIntegrityError(
                        "R2V cancelled Task has no materialized descriptor",
                    )
                indexed, candidate = recovered
                inspection = await asyncio.to_thread(
                    AssetFileStore(
                        self.services.projects.project_root(task.project_id),
                    ).inspect,
                    indexed,
                )
                await self._require_live_materialize_claim(task, claim)
                if inspection.available:
                    published = await self._mark_published_owned(
                        task,
                        claim,
                        candidate,
                    )
                else:
                    await self._mark_cancelled_output_missing_owned(
                        task,
                        claim,
                        code="R2V_CANCELLED_LATE_OUTPUT_MISSING",
                        message=(
                            "Cancelled R2V late output was not durably published; "
                            "recovery will not redownload it"
                        ),
                    )
            except _R2VClaimLost:
                raise
            except Exception as error:
                await self._mark_cancelled_output_missing_owned(
                    task,
                    claim,
                    code="R2V_CANCELLED_LATE_OUTPUT_INVALID",
                    message=str(error),
                )
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if published is None:
            return True
        latest = await asyncio.to_thread(
            self.executions.get_task,
            task.project_id,
            task.task_id,
        )
        await self._quarantine(
            latest,
            _ids(task.project_id, str(task.idempotency_key or task.task_id)),
            result=published,
            reason="TASK_CANCELLED_BEFORE_IMPORT",
            run_status=SpecialistRunStatus.CANCELLED,
        )
        return True

    async def _materialize_and_publish_owned(
        self,
        task: TaskRecord,
        claim: R2VTaskState,
        *,
        stable: Mapping[str, str],
    ) -> dict[str, Any]:
        request = claim.request
        actual_duration = self._provider_duration(claim, request)
        if claim.provider_result is None:  # validated above
            raise StorageIntegrityError(
                "R2V materialize claim has no provider result",
            )
        file_store = AssetFileStore(
            self.services.projects.project_root(task.project_id),
        )
        materialized: MaterializedVideo | None = None
        staged: StagedAsset | None = None
        heartbeat = asyncio.create_task(
            self._heartbeat_materialize_claim(task, claim),
            name=f"r2v-materialize-heartbeat:{task.task_id}",
        )
        try:
            await self._require_live_materialize_claim(task, claim)
            recovered = self._validated_materialized_publication(
                claim,
                task,
                stable,
            )
            if recovered is not None:
                recovered_indexed, recovered_published = recovered
                inspection = await asyncio.to_thread(
                    file_store.inspect,
                    recovered_indexed,
                )
                await self._require_live_materialize_claim(task, claim)
                if inspection.available:
                    return await self._mark_published_owned(
                        task,
                        claim,
                        recovered_published,
                    )

                materialized = await self._materialize_descriptor_scratch(
                    task,
                    claim,
                )

            if materialized is None:
                materialized = await self._materialize_video_with_retry(
                    task,
                    claim,
                )
            await self._require_live_materialize_claim(task, claim)
            indexed, published = self._build_materialized_publication(
                task,
                claim,
                stable=stable,
                materialized=materialized,
                actual_duration=actual_duration,
            )
            await self._persist_materialized_result(
                task,
                claim,
                {
                    "path": str(materialized.path),
                    "sha256": materialized.sha256,
                    "sizeBytes": materialized.size_bytes,
                    "mediaType": materialized.media_type,
                    "container": materialized.container,
                    "publishedResult": published,
                },
            )
            await self._require_live_materialize_claim(task, claim)
            staged = await asyncio.to_thread(
                _stage_materialized_video,
                file_store,
                materialized,
                staging_id=task.task_id[:80],
            )
            await self._require_live_materialize_claim(task, claim)
            try:
                await asyncio.to_thread(
                    file_store.publish,
                    staged,
                    indexed.relative_uri,
                    expected_sha256=materialized.sha256,
                    expected_size_bytes=materialized.size_bytes,
                )
                staged = None
            except AssetAlreadyExists:
                await asyncio.to_thread(file_store.abandon, staged)
                staged = None
                inspection = await asyncio.to_thread(
                    file_store.inspect,
                    indexed,
                )
                if not inspection.available:
                    raise StorageIntegrityError(
                        "稳定 R2V 输出路径已存在但内容不同",
                    )
            await self._require_live_materialize_claim(task, claim)
            return await self._mark_published_owned(task, claim, published)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            if staged is not None:
                try:
                    await asyncio.to_thread(file_store.abandon, staged)
                except Exception:
                    pass
            if materialized is not None:
                try:
                    await asyncio.to_thread(
                        materialized.path.unlink,
                        missing_ok=True,
                    )
                except OSError:
                    pass

    async def _complete_success(
        self,
        task: TaskRecord,
        state: R2VTaskState,
    ) -> None:
        stable = _ids(
            task.project_id,
            str(task.idempotency_key or task.task_id),
        )
        published = state.published_result
        if published is None:
            claimed = await self._claim_materialize(task)
            if claimed is None:
                return
            published = await self._materialize_and_publish_owned(
                task,
                claimed,
                stable=stable,
            )
        latest = await asyncio.to_thread(
            self.executions.get_task,
            task.project_id,
            task.task_id,
        )
        if latest.status is TaskStatus.CANCELLED:
            await self._quarantine(
                latest,
                stable,
                result=published,
                reason="TASK_CANCELLED_BEFORE_IMPORT",
                run_status=SpecialistRunStatus.CANCELLED,
            )
            return
        if latest.status is TaskStatus.RUNNING and latest.result is None:
            try:
                latest = await asyncio.to_thread(
                    self.executions.transition_task,
                    task.project_id,
                    task.task_id,
                    expected_status=TaskStatus.RUNNING,
                    status=TaskStatus.RUNNING,
                    updates={
                        "progress": 0.95,
                        "result": published,
                        "output_refs": [str(published["outputRef"])],
                    },
                )
            except ExecutionStateConflict:
                latest = await asyncio.to_thread(
                    self.executions.get_task,
                    task.project_id,
                    task.task_id,
                )
        await self._converge(latest, stable, published)

    @staticmethod
    def _frozen_inputs_still_current(
        project: Project,
        task: TaskRecord,
    ) -> bool:
        """True when the task's render inputs are unchanged in ``project``.

        Whole-project etag drift treats every commit as fatal, but the most
        common mid-render commit is a review approval of an earlier output
        — it does not touch this Element at all, and quarantining discards
        a finished provider render. Publishing stays allowed when the
        target Element still exists and still selects exactly the
        reference versions the video was rendered from (storyboard
        selection first, then the creation's video references). Prompt or
        settings drift is tolerated because the published video is itself
        gated behind a Review; anything else keeps the fail-closed
        quarantine.
        """

        raw = task.metadata.get("requestSnapshot")
        if not isinstance(raw, Mapping):
            return False
        frozen_refs = raw.get("referenceVersionIds")
        element_id = str(raw.get("elementId") or "")
        if not element_id or not isinstance(frozen_refs, list):
            return False
        try:
            _, element = find_timeline_element(project, element_id)
        except Exception:
            return False
        if not isinstance(element.creation, R2VCreation):
            return False
        selected = selected_element_output(project, element, "storyboard")
        storyboard_id = selected[1] if selected is not None else None
        if not storyboard_id:
            return False
        current_refs = list(
            dict.fromkeys(
                [
                    storyboard_id,
                    *resolve_r2v_visual_reference_version_ids(
                        project,
                        element.creation,
                        element.creation.video_reference_version_ids,
                    ),
                ],
            ),
        )
        return current_refs == [str(item) for item in frozen_refs]

    async def _converge(
        self,
        task: TaskRecord,
        stable: Mapping[str, str],
        result: Mapping[str, Any],
    ) -> None:
        review_reservation = reserve_media_review(
            self.services,
            project_id=task.project_id,
            published_result=result,
        )

        def commit_if_live() -> tuple[str, TaskRecord, ProjectSnapshot | None]:
            with self.services.projects.lifecycle_lock(task.project_id):
                latest = self.executions.get_task(
                    task.project_id,
                    task.task_id,
                    _lifecycle_lock_held=True,
                )
                if latest.status is TaskStatus.CANCELLED:
                    return "CANCELLED", latest, None
                if latest.status in {
                    TaskStatus.FAILED,
                    TaskStatus.QUARANTINED,
                }:
                    return latest.status.value, latest, None
                current = self.services.projects.read(task.project_id)
                if self._result_is_converged(current.project, result):
                    snapshot = current
                else:
                    if (
                        current.etag != latest.input_etag
                        or current.generation != latest.input_generation
                    ) and not self._frozen_inputs_still_current(
                        current.project,
                        latest,
                    ):
                        return "STALE", latest, current
                    candidate = current.project.model_dump(mode="json")
                    self._apply_result(candidate, result)
                    # Generated video is reviewed before acceptance unless
                    # the operator opted into unattended auto-approval; an
                    # AUTO_FIX round must not carry a ReviewBoundary.
                    review_policy = media_review_policy()
                    review_boundary = (
                        self.services.commits.runtime_review_boundary(
                            task.project_id,
                            run_id=str(task.run_id),
                            request_id=latest.caused_by_request_id,
                        )
                        if review_policy is ReviewPolicy.REQUIRE_REVIEW
                        else None
                    )
                    commit = self.services.commits.commit(
                        base=current,
                        candidate=candidate,
                        origin=ChangeOrigin.RUNTIME_TASK,
                        review_policy=review_policy,
                        review_boundary=review_boundary,
                        caused_by_request_id=latest.caused_by_request_id,
                        round_id=stable["round_id"],
                        transaction_id=stable["transaction_id"],
                        advance_accepted_baseline=True,
                        _lifecycle_lock_held=True,
                    )
                    snapshot = commit.snapshot
                success = {
                    **dict(result),
                    "projectEtag": snapshot.etag,
                    "projectGeneration": snapshot.generation,
                }
                if latest.status is TaskStatus.RUNNING:
                    self.executions.append_attempt(
                        task.project_id,
                        task.task_id,
                        event_id=stable["attempt_succeeded_event_id"],
                        attempt_id=stable["attempt_id"],
                        status=TaskAttemptStatus.SUCCEEDED,
                        provider_task_id=(
                            str(result.get("providerTaskId") or "") or None
                        ),
                        output=success,
                        output_refs=[str(success["outputRef"])],
                        _lifecycle_lock_held=True,
                    )
                    latest = self.executions.get_task(
                        task.project_id,
                        task.task_id,
                        _lifecycle_lock_held=True,
                    )
                return "SUCCEEDED", latest, snapshot

        try:
            outcome, latest, snapshot = await asyncio.to_thread(commit_if_live)
        except BaseException:
            release_media_review_reservation(review_reservation)
            raise
        if outcome == "CANCELLED":
            release_media_review_reservation(review_reservation)
            await self._quarantine(
                latest,
                stable,
                result=result,
                reason="TASK_CANCELLED_BEFORE_IMPORT",
                run_status=SpecialistRunStatus.CANCELLED,
            )
            return
        if outcome == "STALE":
            release_media_review_reservation(review_reservation)
            await self._quarantine(
                latest,
                stable,
                result=result,
                reason="PROJECT_INPUT_SNAPSHOT_STALE",
                run_status=SpecialistRunStatus.STALE,
            )
            return
        if outcome != "SUCCEEDED" or snapshot is None:
            release_media_review_reservation(review_reservation)
            return
        try:
            await asyncio.to_thread(self.services.poller.note_commit, snapshot)
            success = (
                latest.result
                if isinstance(latest.result, dict)
                else {
                    **dict(result),
                    "projectEtag": snapshot.etag,
                    "projectGeneration": snapshot.generation,
                }
            )
            # Run-review hook: every successful convergence (fresh render,
            # idempotent replay, crash recovery) flows through this single
            # point. Scheduling is advisory and idempotent: the switch, the
            # command filter and the already-reviewed dedup live on the review
            # side.
            schedule_media_review(
                self.services,
                project_id=task.project_id,
                published_result=success,
                reservation_token=review_reservation,
            )
        except BaseException:
            release_media_review_reservation(review_reservation)
            raise
        await self._finish_run(
            task.project_id,
            str(task.run_id),
            SpecialistRunStatus.SUCCEEDED,
            summary="R2V 视频已生成并写入 Project",
        )

        def succeeded(current: R2VTaskState) -> Mapping[str, Any]:
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "SUCCEEDED",
                    "published_result": success,
                    "last_error": None,
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            succeeded,
        )

    @staticmethod
    def _result_is_converged(
        project: Project,
        result: Mapping[str, Any],
    ) -> bool:
        try:
            indexed = IndexedFile.model_validate(result["indexedFile"])
            artifact = ArtifactVersion.model_validate(
                result["artifactVersion"],
            )
            element_id = _target_element_id(str(result["targetRef"]))
        except (KeyError, TypeError, ValueError):
            return False
        slot = project.assets.artifact_slots_by_id.get(artifact.slot_id)
        try:
            _, element = find_timeline_element(project, element_id)
        except NotFoundError:
            return False
        selected = selected_element_output(project, element, "main")
        return (
            project.assets.files_by_id.get(indexed.file_id) == indexed
            and project.assets.artifact_versions_by_id.get(artifact.version_id)
            == artifact
            and slot is not None
            and slot.selected_version_id == artifact.version_id
            and selected is not None
            and selected[1] == artifact.version_id
        )

    @staticmethod
    def _apply_result(
        candidate: dict[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        indexed = IndexedFile.model_validate(result["indexedFile"])
        artifact = ArtifactVersion.model_validate(result["artifactVersion"])
        element_id = _target_element_id(str(result["targetRef"]))
        assets = candidate["assets"]
        files = assets["files_by_id"]
        versions = assets["artifact_versions_by_id"]
        slots = assets["artifact_slots_by_id"]
        indexed_json = indexed.model_dump(mode="json")
        artifact_json = artifact.model_dump(mode="json")
        if indexed.file_id in files and files[indexed.file_id] != indexed_json:
            raise ConflictError("R2V IndexedFile 稳定 ID 内容冲突")
        if (
            artifact.version_id in versions
            and versions[artifact.version_id] != artifact_json
        ):
            raise ConflictError("R2V ArtifactVersion 稳定 ID 内容冲突")
        files[indexed.file_id] = indexed_json
        versions[artifact.version_id] = artifact_json
        raw_slot = slots.get(artifact.slot_id)
        if raw_slot is None:
            slots[artifact.slot_id] = ArtifactSlot(
                slot_id=artifact.slot_id,
                kind=artifact.kind,
                owner_ref=artifact.owner_ref,
                version_ids=[artifact.version_id],
                selected_version_id=artifact.version_id,
            ).model_dump(mode="json")
        else:
            if (
                raw_slot["kind"] != artifact.kind
                or raw_slot["owner_ref"] != artifact.owner_ref
            ):
                raise ConflictError("R2V ArtifactSlot 归属冲突")
            if artifact.version_id not in raw_slot["version_ids"]:
                raw_slot["version_ids"].append(artifact.version_id)
            raw_slot["selected_version_id"] = artifact.version_id
        bind_candidate_output(
            candidate,
            element_id=element_id,
            output_name="main",
            slot_id=artifact.slot_id,
            select_for_render=True,
        )
        # The provider decides the real footage length (s2v follows its
        # driving audio); align the timeline with what was actually billed
        # and delivered instead of freezing the last frame to pad the plan.
        reconcile_candidate_span(
            candidate,
            element_id=element_id,
            actual_duration_seconds=artifact.duration_seconds,
        )

    async def _quarantine(
        self,
        task: TaskRecord,
        stable: Mapping[str, str],
        *,
        result: Mapping[str, Any],
        reason: str,
        run_status: SpecialistRunStatus,
    ) -> None:
        latest = await asyncio.to_thread(
            self.executions.get_task,
            task.project_id,
            task.task_id,
        )
        if latest.status is TaskStatus.RUNNING:
            try:
                await asyncio.to_thread(
                    self.executions.append_attempt,
                    task.project_id,
                    task.task_id,
                    event_id=stable["attempt_quarantined_event_id"],
                    attempt_id=stable["attempt_id"],
                    status=TaskAttemptStatus.QUARANTINED,
                    provider_task_id=str(result.get("providerTaskId") or "")
                    or None,
                    output=dict(result),
                    output_refs=[str(result.get("outputRef") or "")],
                    error={"code": reason, "message": reason},
                )
            except ExecutionStateConflict:
                pass
        await asyncio.to_thread(
            self.executions.quarantine_task_result,
            task.project_id,
            task.task_id,
            reason=reason,
            result=dict(result),
            quarantine_id=stable["quarantine_id"],
            transition_task=False,
        )
        await self._finish_run(
            task.project_id,
            str(task.run_id),
            run_status,
        )

        def quarantined(current: R2VTaskState) -> Mapping[str, Any]:
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "QUARANTINED",
                    "published_result": dict(result),
                    "last_error": {"code": reason, "message": reason},
                    "poll_lease_owner": None,
                    "poll_lease_token": None,
                    "poll_lease_expires_at_epoch": None,
                    "materialize_owner": None,
                    "materialize_claim_token": None,
                    "materialize_claimed_at_epoch": None,
                    "materialize_heartbeat_at_epoch": None,
                    "materialize_claim_expires_at_epoch": None,
                },
            )
            return dumped

        await asyncio.to_thread(
            self._update_state_sync,
            task.project_id,
            task.task_id,
            quarantined,
        )

    async def _fail(
        self,
        task: TaskRecord,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        error: BaseException | None = None,
    ) -> None:
        report = report_error(
            component="r2v-execution",
            code=code,
            message=message,
            error=error,
            retryable=retryable,
            details={
                "projectId": task.project_id,
                "taskId": task.task_id,
                "runId": str(task.run_id or ""),
            },
            projectId=task.project_id,
            taskId=task.task_id,
            runId=str(task.run_id or ""),
        )
        failure = {
            key: value for key, value in report.items() if value is not None
        }
        stable = _ids(
            task.project_id,
            str(task.idempotency_key or task.task_id),
        )
        latest = await asyncio.to_thread(
            self._fail_active_task_locked,
            task,
            error=failure,
            stable=stable,
        )
        if latest.status in _TERMINAL_TASKS:
            aligned = await self._align_state_to_terminal_task(latest)
            if not aligned:
                self._schedule_terminal_recovery(
                    latest.project_id,
                    latest.task_id,
                )
        await asyncio.to_thread(
            reconcile_terminal_task_runs,
            self.services.root,
            [task.project_id],
        )

    async def _mark_cancelled(self, task: TaskRecord) -> None:
        try:
            deferred = False

            def cancelled(current: R2VTaskState) -> Mapping[str, Any]:
                nonlocal deferred
                if (
                    current.phase == "SUBMIT_CLAIMED"
                    and current.provider_task_id is None
                    and (current.submit_claim_expires_at_epoch or 0.0)
                    > self.clock()
                ):
                    # The submit owner must durably bind the external id before
                    # cancellation can terminalize this state.  Otherwise a
                    # second supervisor could erase the only recovery anchor.
                    deferred = True
                    return current.model_dump(mode="python")
                dumped = current.model_dump(mode="python")
                dumped.update(
                    {
                        "phase": "CANCELLED",
                        "submit_owner": None,
                        "submit_claim_token": None,
                        "submit_claim_expires_at_epoch": None,
                        "poll_lease_owner": None,
                        "poll_lease_token": None,
                        "poll_lease_expires_at_epoch": None,
                        "materialize_owner": None,
                        "materialize_claim_token": None,
                        "materialize_claimed_at_epoch": None,
                        "materialize_heartbeat_at_epoch": None,
                        "materialize_claim_expires_at_epoch": None,
                    },
                )
                return dumped

            await asyncio.to_thread(
                self._update_state_sync,
                task.project_id,
                task.task_id,
                cancelled,
            )
            if deferred:
                if task.status in _TERMINAL_TASKS:
                    self._schedule_terminal_recovery(
                        task.project_id,
                        task.task_id,
                    )
                return
        except RecordNotFoundError:
            pass
        await self._finish_run(
            task.project_id,
            str(task.run_id),
            SpecialistRunStatus.CANCELLED,
        )

    async def _finish_run(
        self,
        project_id: str,
        run_id: str,
        status: SpecialistRunStatus,
        *,
        summary: str | None = None,
    ) -> None:
        if not run_id:
            return
        try:
            run = await asyncio.to_thread(
                self.executions.get_run,
                project_id,
                run_id,
            )
        except RecordNotFoundError:
            return
        if run.status in {
            SpecialistRunStatus.SUCCEEDED,
            SpecialistRunStatus.BLOCKED,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        }:
            return
        try:
            await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run_id,
                expected_status=run.status,
                status=status,
                updates={"final_summary_text": summary} if summary else None,
            )
        except ExecutionStateConflict:
            pass

    async def recover_all(self) -> int:
        recovered = 0
        for project_id in self.services.projects.discover_project_ids():
            for run in self.executions.list_specialist_runs(project_id):
                if (
                    run.role is SpecialistRole.R2V_GENERATION_DIRECTOR
                    and run.metadata.get("commandType")
                    == CreatorCommandType.GENERATE_R2V_VIDEO.value
                ):
                    try:
                        await self._recover_run_admission_gap(run)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # One corrupt Project must not prevent unrelated
                        # Projects from recovering during service startup.
                        logger.exception(
                            "R2V admission-gap recovery isolated failure "
                            "for %s/%s",
                            project_id,
                            run.run_id,
                        )
            for task in self.executions.list_tasks(project_id):
                if task.kind is not TaskKind.R2V_GENERATION:
                    continue
                try:
                    if task.status in _TERMINAL_TASKS:
                        aligned = await self._align_state_to_terminal_task(
                            task,
                        )
                        if not aligned:
                            self._schedule_terminal_recovery(
                                project_id,
                                task.task_id,
                            )
                        continue
                    if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                        run = self.executions.get_run(
                            project_id,
                            str(task.run_id),
                        )
                        if await self._ensure_state_for_task(run, task):
                            self.start_task(project_id, task.task_id)
                            recovered += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # One corrupt Task must not prevent unrelated Projects and
                    # Tasks from recovering during service startup.
                    logger.exception(
                        "R2V startup recovery isolated failure for %s/%s",
                        project_id,
                        task.task_id,
                    )
                    if task.status in _TERMINAL_TASKS:
                        self._schedule_terminal_recovery(
                            project_id,
                            task.task_id,
                        )
        await asyncio.to_thread(
            reconcile_terminal_task_runs,
            self.services.root,
            self.services.projects.discover_project_ids(),
        )
        return recovered

    async def shutdown(self) -> None:
        workers = [
            *self._jobs.values(),
            *self._terminal_recovery_jobs.values(),
        ]
        self._jobs.clear()
        self._job_projects.clear()
        self._terminal_recovery_jobs.clear()
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)


def _has_accepted_provider_task(task_id: str, project_id: str) -> bool:
    """Whether a *resumable* billed provider task exists for this Task.

    Only ledger kinds the image resume supervisor supports count: handing
    it an accepted-but-unresumable job (async image generation today) would
    end supervision as "unsupported" and strand the Task in RUNNING, so
    those fall through to the fail-closed terminalization below — the
    billed ids stay named in the error for manual retrieval.
    """

    try:
        from .image_execution import resumable_provider_entries

        return bool(resumable_provider_entries(task_id, project_id))
    except Exception:  # noqa: BLE001 - absence of a ledger is not an error
        return False


def _accepted_provider_tasks_note(task_id: str, project_id: str) -> str:
    """Name any billed provider task an interrupted Task already paid for.

    Asynchronous provider submissions (e.g. qwen-mt-image translation) are
    billed on acceptance and their result stays retrievable for 24h, so a
    terminalized Task must say which ids to fetch instead of losing them.
    """

    from models.provider_tasks import read_provider_tasks

    try:
        entries = read_provider_tasks(task_id, project_id)
    except Exception:  # noqa: BLE001 - bookkeeping must not break recovery
        return ""
    if not entries:
        return ""
    described = ", ".join(
        f"{entry.get('model', '?')}:{entry.get('providerTaskId', '?')}"
        for entry in entries
    )
    return (
        "; already accepted (billed) provider tasks whose results stay "
        f"retrievable for 24h: {described}"
    )


async def recover_interrupted_image_tasks(
    services: CreatorFileServices,
) -> int:
    """Never resubmit an interrupted one-shot image provider call.

    A published Task result is converged from durable files.  Any active image
    Task without such a result is terminalized because the provider may have
    accepted the request before the process died.
    """

    from .image_execution import file_image_execution_service

    worker = file_image_execution_service(services)
    executions = worker.executions
    recovered = 0
    for project_id in services.projects.discover_project_ids():
        for task in executions.list_tasks(project_id):
            if (
                task.kind is not TaskKind.IMAGE_GENERATION
                or task.status
                not in {
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                }
            ):
                continue
            stable = (
                worker._ids(  # noqa: SLF001 - same package recovery boundary
                    project_id,
                    str(task.idempotency_key or task.task_id),
                )
            )
            if stable["task_id"] != task.task_id:
                # Scheduler-dispatched tasks (idempotency keys like
                # ``dag-storyboard:...``) carry execution-store ids, not
                # the file-image command namespace recomputed above.
                # Field run 2026-08-12 (project 27dc): the recomputed id
                # missed the record, _fail_if_running returned on
                # RecordNotFound and the interrupted RUNNING task
                # survived restart as a zombie pinning its work-graph
                # lane RUNNING forever. Recover the record we actually
                # iterated — including its live attempt, which the
                # fail-close must finish (a foreign-namespace attempt id
                # would open a second attempt and leave the first, and
                # therefore the Task, RUNNING).
                stable = {
                    **stable,
                    "task_id": task.task_id,
                    "run_id": str(task.run_id or stable["run_id"]),
                }
                attempts = executions.list_task_attempts(
                    project_id,
                    task.task_id,
                )
                if attempts:
                    stable["attempt_id"] = attempts[-1].attempt_id
            if isinstance(task.result, dict):
                try:
                    await worker._converge(  # noqa: SLF001
                        task=task,
                        ids=stable,
                        replayed=True,
                    )
                except ConflictError:
                    pass
                recovered += 1
                continue
            if task.status is TaskStatus.RUNNING:
                # A resumable server-side provider job (qwen-mt-image
                # translation) is billed on acceptance and its id is durable,
                # so hand it to the background poller rather than discarding
                # a paid result or blocking startup on it. Unresumable
                # provider jobs and one-shot synchronous calls stay
                # fail-closed below.
                if _has_accepted_provider_task(task.task_id, project_id):
                    worker.schedule_resume(task)
                    recovered += 1
                    continue
                await worker._fail_if_running(  # noqa: SLF001
                    project_id,
                    stable,
                    "IMAGE_PROCESS_RESTARTED",
                    message=(
                        "image provider call was interrupted; refusing automatic "
                        "non-idempotent resubmission"
                        + _accepted_provider_tasks_note(
                            task.task_id,
                            project_id,
                        )
                    ),
                )
            else:
                error = {
                    "code": "IMAGE_PROCESS_RESTARTED",
                    "message": (
                        "image Task was interrupted; refusing automatic provider "
                        "submission"
                    ),
                    "retryable": True,
                }
                executions.transition_task(
                    project_id,
                    task.task_id,
                    expected_status=TaskStatus.QUEUED,
                    status=TaskStatus.FAILED,
                    updates={"error": error},
                )
                await worker._finish_run(  # noqa: SLF001
                    project_id,
                    str(task.run_id),
                    SpecialistRunStatus.FAILED,
                )
            recovered += 1
    return recovered


_registry_lock = threading.RLock()
_registry: dict[Path, FileR2VExecutionService] = {}


def file_r2v_execution_service(
    services: CreatorFileServices,
) -> FileR2VExecutionService:
    root = services.root.resolve()
    with _registry_lock:
        service = _registry.get(root)
        if service is None:
            service = FileR2VExecutionService(services)
            _registry[root] = service
        return service


async def start_file_media_execution_services(
    services: CreatorFileServices,
    *,
    provider: R2VProvider | None = None,
    poll_interval_seconds: float = 2.0,
    poll_lease_seconds: float = 120.0,
    submit_timeout_seconds: float = _SUBMIT_TIMEOUT_SECONDS,
    submit_claim_seconds: float = _SUBMIT_CLAIM_SECONDS,
    materialize_timeout_seconds: float = _MATERIALIZE_TIMEOUT_SECONDS,
    materialize_claim_seconds: float = _MATERIALIZE_CLAIM_SECONDS,
    max_output_bytes: int = _MAX_VIDEO_BYTES,
) -> FileR2VExecutionService:
    """Start recovery/supervision for R2V and fail-close one-shot images."""

    root = services.root.resolve()
    with _registry_lock:
        current = _registry.get(root)
        if current is None:
            current = FileR2VExecutionService(
                services,
                provider=provider,
                poll_interval_seconds=poll_interval_seconds,
                poll_lease_seconds=poll_lease_seconds,
                submit_timeout_seconds=submit_timeout_seconds,
                submit_claim_seconds=submit_claim_seconds,
                materialize_timeout_seconds=materialize_timeout_seconds,
                materialize_claim_seconds=materialize_claim_seconds,
                max_output_bytes=max_output_bytes,
            )
            _registry[root] = current
        elif provider is not None and current.provider is not provider:
            raise RuntimeError(
                "R2V execution service already uses another provider",
            )
    await recover_interrupted_image_tasks(services)
    from .local_execution import recover_file_local_media_project
    from services.project_files.store import ProjectIntegrityError

    for project_id in services.projects.discover_project_ids():
        try:
            await recover_file_local_media_project(services, project_id)
        except ProjectIntegrityError:
            # One corrupt/foreign project.json must not veto the whole
            # runtime: skipping keeps every healthy Project operational
            # while the corrupt one is already surfaced by recovery logs.
            logger.exception(
                "skipping local media recovery for corrupt Project %s",
                project_id,
            )
    project_ids = services.projects.discover_project_ids()
    await asyncio.to_thread(
        reconcile_terminal_task_runs,
        services.root,
        project_ids,
    )
    await current.recover_all()
    return current


async def shutdown_file_media_execution_services() -> None:
    with _registry_lock:
        services = list(_registry.values())
        _registry.clear()
    if services:
        await asyncio.gather(
            *(service.shutdown() for service in services),
            return_exceptions=True,
        )
    from .image_execution import shutdown_file_image_execution_services

    await shutdown_file_image_execution_services()


def clear_file_media_execution_registry_for_tests() -> None:
    with _registry_lock:
        if any(  # noqa: SLF001
            service._jobs or service._terminal_recovery_jobs
            for service in _registry.values()
        ):
            raise RuntimeError(
                "shutdown file media services before clearing registry",
            )
        _registry.clear()


async def execute_file_r2v_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
    expected_object_versions: Sequence[str] = (),
) -> FileR2VDispatch:
    # Wallet fuse: every dispatch path (specialist delegation, work-graph
    # scheduler, manual retry) funnels through here.
    ensure_media_call_budget(services, project_id)
    return await file_r2v_execution_service(services).dispatch(
        project_id=project_id,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
        expected_object_versions=expected_object_versions,
    )


async def execute_file_s2v_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
    expected_object_versions: Sequence[str] = (),
) -> FileR2VDispatch:
    """Digital-human (wan2.2-s2v) dispatch through the R2V durable poller."""

    return await file_r2v_execution_service(services).dispatch(
        project_id=project_id,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
        expected_object_versions=expected_object_versions,
        s2v=True,
    )


async def preflight_s2v_face_detect(
    services: CreatorFileServices,
    *,
    project_id: str,
    arguments: Mapping[str, Any],
) -> None:
    """Free wan2.2-s2v-detect gate that runs before execution authorization.

    A failed portrait check raises a readable ``ValidationError`` so the
    agent can pick another image without any authorization being created.
    """

    from models.s2v_model import detect_face

    image_ref = str(arguments.get("characterImageRef") or "").strip()
    if not image_ref:
        raise ValidationError(
            "s2v_generation 需要 characterImageRef（exact 人像图 version id）",
        )
    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    image_url, _, _, _ = _resolve_single_media_version(
        project=snapshot.project,
        project_root=services.projects.project_root(project_id),
        version_id=image_ref,
        media_prefix="image/",
        label="characterImageRef",
    )
    result = await detect_face(image_url)
    if not result.passed:
        raise ValidationError(
            f"数字人人像检测未通过（免费 detect，未创建执行授权）："
            f"{result.reason or '未知原因'}。常见原因：多人/侧脸/模糊/遮挡/"
            "风格不支持；请换一张单人、正脸、清晰的角色图后重试",
        )


__all__ = [
    "ExistingR2VProvider",
    "FileR2VDispatch",
    "FileR2VExecutionService",
    "R2VProvider",
    "R2VTaskState",
    "clear_file_media_execution_registry_for_tests",
    "execute_file_r2v_command",
    "execute_file_s2v_command",
    "file_r2v_execution_service",
    "media_version_duration_seconds",
    "preflight_s2v_face_detect",
    "recover_interrupted_image_tasks",
    "shutdown_file_media_execution_services",
    "start_file_media_execution_services",
]
