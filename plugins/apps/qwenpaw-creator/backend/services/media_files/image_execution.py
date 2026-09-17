# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=raise-missing-from,too-many-branches,too-many-statements
# pylint: disable=try-except-raise
"""Task-first image generation against the file-native Project authority.

One invocation freezes its Project snapshot, records a stable Run/Task/Attempt,
calls the provider without holding Project or Runtime locks, publishes immutable
bytes through :class:`AssetFileStore`, and then converges the Asset Index and
selected pointer through one :class:`ProjectCommitBoundary` transaction.

Provider output that arrives after cancellation or after the frozen Project
snapshot became stale is kept as an unindexed immutable file and recorded in
Runtime quarantine.  The model/provider never writes Asset Index entries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import threading
import re
import socket
import stat
from typing import Any, Protocol, TYPE_CHECKING
from urllib.parse import unquote, urlparse, urlsplit
from uuid import NAMESPACE_URL, uuid5

from domain.enums import (
    CreatorCommandType,
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
from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileStore,
)
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
    R2VCreation,
    VisualEntity,
    VisualVariant,
)
from services.media_files.call_budget import ensure_media_call_budget
from services.media_files.element_adapter import (
    bind_candidate_output,
    find_timeline_element,
    selected_element_output,
    target_element_id,
)
from services.media_files.review_admission import (
    assert_media_review_admission,
    media_review_policy,
)
from services.media_files.transient_errors import (
    MAX_TRANSIENT_RETRY_SLOTS,
    is_transient_task_error,
    transient_retry_slot_key,
)
from services.media_files.visual_reference_resolution import (
    resolve_r2v_visual_reference_version_ids,
)
from services.media_files.visual_design_readiness import (
    assert_visual_design_ready_for_storyboards,
)
from services.project_files.remote_cache import public_source_url
from services.project_files.store import ProjectSnapshot
from services.run_review.media_review import schedule_media_review
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
from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
    validate_public_remote_url,
)

# pylint: disable=no-name-in-module
from utils.exceptions import ModelError
from utils.paths import media_path_from_url, media_task_scope

# pylint: enable=no-name-in-module
from utils.logger import setup_logger

if TYPE_CHECKING:
    from services.project_files.facade import CreatorFileServices


logger = setup_logger("services.media_files.image_execution")


_IMAGE_COMMANDS = frozenset(
    {
        CreatorCommandType.GENERATE_ASSET,
        CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
        CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE,
    },
)
_IMAGE_MODES = ("generate", "edit", "translate")

# Background supervision of accepted (billed) asynchronous provider tasks.
# A finished result stays retrievable upstream for 24h, so the supervisor
# keeps polling well past one pass instead of dropping a paid result.
_RESUME_POLL_INTERVAL_SECONDS = 3.0
_RESUME_POLL_BUDGET_SECONDS = 60.0
_RESUME_RETRY_INTERVAL_SECONDS = 15.0
_RESUME_HORIZON_SECONDS = 6 * 60 * 60.0
# Retries only back off; a terminal verdict comes from the provider or from
# the horizon above, never from a run of transient failures.
_RESUME_BACKOFF_MAX_SHIFT = 5
_RESUME_BACKOFF_CAP_SECONDS = 300.0
_EDIT_MAX_REFERENCES = 3
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_SAFE_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


class ImageProvider(Protocol):
    """Injectable image provider boundary; provider calls are never locked."""

    async def generate(
        self,
        *,
        prompt: str,
        aspect_ratio: str,
        reference_image_urls: Sequence[str],
        mode: str = "generate",
        source_lang: str = "",
        target_lang: str = "",
    ) -> Mapping[str, Any]:
        ...


class ExistingImageProvider:
    """Adapter over the existing configured image provider.

    The import is intentionally lazy: Creator startup and read-only APIs do
    not load image backends or their optional transport dependencies.
    """

    async def generate(
        self,
        *,
        prompt: str,
        aspect_ratio: str,
        reference_image_urls: Sequence[str],
        mode: str = "generate",
        source_lang: str = "",
        target_lang: str = "",
    ) -> Mapping[str, Any]:
        from models.image import generate_image

        url = await generate_image(
            prompt,
            aspect_ratio=aspect_ratio,
            reference_image_urls=list(reference_image_urls),
            mode=mode,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        return {"url": url, "media_type": "image/png"}


@dataclass(frozen=True, slots=True)
class FileImageExecutionResult:
    task_id: str
    run_id: str
    transaction_id: str
    artifact_version_id: str
    project_etag: str
    project_generation: int
    replayed: bool

    def command_response(self, command_id: str) -> dict[str, Any]:
        return {
            "commandId": command_id,
            "status": "APPLIED",
            "eventSeq": 0,
            "transactionId": self.transaction_id,
            "workingHead": self.project_etag,
        }


@dataclass(frozen=True, slots=True)
class _ResolvedRequest:
    command: CreatorCommandType
    target_ref: str
    prompt: str
    aspect_ratio: str
    reference_image_urls: tuple[str, ...]
    reference_version_ids: tuple[str, ...]
    reference_checksums: tuple[str, ...]
    read_set: tuple[dict[str, Any], ...]
    slot_id: str
    slot_kind: str
    owner_ref: str
    artifact_name: str
    role: SpecialistRole
    target_id: str
    variant_id: str | None = None
    mode: str = "generate"
    source_lang: str = ""
    target_lang: str = ""


def _stable_id(prefix: str, project_id: str, idempotency_key: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:file-image:{prefix}:{project_id}:{idempotency_key}",
    ).hex
    return f"{prefix}-{digest}"


def _fingerprint(value: Mapping[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


# Deterministic provider-side content refusals. Field data (2026-08-05,
# 22 consecutive 400s): the model *narrates* removing the person-photo
# references while resending the identical ref list every call, so the
# refusal must name the refs it saw and repeat-offender calls are blocked
# locally instead of burning provider quota.
_SAFETY_REJECTION_MARKERS = (
    "rejected by the safety system",
    "content policy",
    "content_policy",
)


def _is_safety_rejection_message(message: str) -> bool:
    folded = message.casefold()
    return any(marker in folded for marker in _SAFETY_REJECTION_MARKERS)


def _resolved_reference_ids(resolved: _ResolvedRequest) -> tuple[str, ...]:
    return tuple(resolved.reference_version_ids) + tuple(
        resolved.reference_image_urls,
    )


def _safety_rejection_note(resolved: _ResolvedRequest) -> str:
    refs = _resolved_reference_ids(resolved)
    if refs:
        listed = ", ".join(refs[:6])
        return (
            f"本次调用携带了图片参考 [{listed}]。safety 拒绝通常由含真人照片的"
            "参考图触发：在移除这些参考（置空 referenceVersionIds 改用纯文本，"
            "或改用已生成的风格化 artifact-version id）之前，仅修改 prompt 的"
            "重试不会成功。"
        )
    return (
        "本次调用未携带参考图，拒绝来自 prompt 文本本身：请移除对真实人物的"
        "可识别描述（姓名、球队/机构名、可定位的真实事件），改用虚构化的"
        "外貌与气质描述。"
    )


def _terminated_task_conflict(
    task: Any,
    *,
    exhausted_retries: bool = False,
) -> ConflictError:
    """Name the original failure and the exact way out of the replay wall.

    Identical arguments always map to the same durable slot, so a bare
    "task terminated" message traps the model in a resend loop: it cannot
    know that only changed arguments (or a fixed cause) produce a new task.
    """

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
            "并调整 arguments（如更换参考图或修改 prompt 措辞）以生成新任务。"
        )
    return ConflictError(f"图片 Task 已终止: {status}{reason}。{advice}")


def _plain_sha256(value: str) -> str:
    normalized = value.strip().lower().removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", normalized):
        raise ValidationError("provider checksum 不是合法 SHA-256")
    return normalized


def _json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _list_of_strings(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValidationError(f"{label} 必须是字符串数组")
    return [item.strip() for item in value if item.strip()]


def _target_id(target_ref: str, prefix: str) -> str:
    expected = f"{prefix}:"
    if not target_ref.startswith(expected) or not target_ref[len(expected) :]:
        raise ValidationError(f"targetRef 必须是 {expected}<id>")
    return target_ref[len(expected) :]


def _variant_for(
    entity: VisualEntity,
    arguments: Mapping[str, Any],
) -> VisualVariant | None:
    if not entity.variants.order:
        return None
    raw_variant_id = arguments.get("variantId")
    raw_index = arguments.get("promptIndex")
    if raw_variant_id is not None and raw_index is not None:
        raise ValidationError("variantId 与 promptIndex 不能同时提供")
    if raw_variant_id is not None:
        if not isinstance(raw_variant_id, str):
            raise ValidationError("variantId 必须是字符串")
        variant_id = raw_variant_id.strip()
        if not variant_id:
            raise ValidationError("variantId 不能为空")
        variant = entity.variants.items.get(variant_id)
        if variant is None or variant_id not in entity.variants.order:
            raise ValidationError("variantId 不在视觉变体范围内")
        return variant
    if raw_index is None:
        if len(entity.variants.order) > 1:
            raise ValidationError("目标包含多个视觉变体，必须提供 variantId")
        return entity.variants.items[entity.variants.order[0]]
    if isinstance(raw_index, bool):
        raise ValidationError("promptIndex 必须是整数")
    try:
        index = int(raw_index)
    except (TypeError, ValueError) as exc:
        raise ValidationError("promptIndex 必须是整数") from exc
    if index < 0 or index >= len(entity.variants.order):
        raise ValidationError("promptIndex 超出视觉变体范围")
    return entity.variants.items[entity.variants.order[index]]


def _variant_display_name(variant_id: str) -> str:
    for prefix in ("visual-variant:", "variant:", "var:"):
        if variant_id.startswith(prefix):
            return variant_id.removeprefix(prefix)
    return variant_id


def _validate_public_remote_url(
    value: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> str:
    try:
        return validate_public_remote_url(value, resolver=resolver)
    except SafeRemoteDownloadError as error:
        raise ValidationError(str(error)) from error


def _exact_version_from_ref(value: str) -> str | None:
    if not value.startswith(("asset://", "artifact://")) or "@" not in value:
        return None
    version_id = value.rsplit("@", 1)[1].strip()
    if not version_id:
        raise ValidationError("图片引用缺少 exact version id")
    return version_id


def _explicit_references(
    arguments: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    values = _list_of_strings(
        arguments.get("referenceImageUrls"),
        label="referenceImageUrls",
    )
    urls: list[str] = []
    version_ids: list[str] = []
    for value in values:
        version_id = _exact_version_from_ref(value)
        if version_id is not None:
            version_ids.append(version_id)
            continue
        if value.startswith("/generated/"):
            # Compatibility Runtime URLs are local transport, not user paths.
            media_path_from_url(value)
            urls.append(value)
            continue
        parsed = urlparse(value)
        if parsed.scheme.casefold() in {"http", "https"}:
            urls.append(_validate_public_remote_url(value))
        else:
            raise ValidationError(
                "referenceImageUrls 仅接受 exact Project ref、公网 http(s) "
                "或 Runtime generated URL",
            )
    return urls, version_ids


def _indexed_path(project_root: Path, indexed: IndexedFile) -> Path:
    return project_root.joinpath(*PurePosixPath(indexed.relative_uri).parts)


def _resolve_version_references(
    *,
    project: Project,
    project_root: Path,
    version_ids: Sequence[str],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    urls: list[str] = []
    checksums: list[str] = []
    read_set: list[dict[str, Any]] = []
    files = AssetFileStore(project_root)
    for version_id in dict.fromkeys(version_ids):
        source = project.assets.source_versions_by_id.get(version_id)
        artifact = project.assets.artifact_versions_by_id.get(version_id)
        version = source or artifact
        if version is None:
            raise NotFoundError(f"引用版本不存在: {version_id}")
        remote_url = public_source_url(source) if source is not None else None
        if remote_url is not None:
            if not version.media_type.casefold().startswith("image/"):
                raise ValidationError(f"引用版本不是图片: {version_id}")
            urls.append(remote_url)
            checksums.append(version.checksum)
            read_set.append(
                {
                    "ref": f"asset-version:{version_id}",
                    "versionId": version_id,
                    "fileId": None,
                    "checksum": version.checksum,
                    "sourceUrl": remote_url,
                },
            )
            continue
        indexed = project.assets.files_by_id[version.file_id]
        if not indexed.media_type.casefold().startswith("image/"):
            raise ValidationError(f"引用版本不是图片: {version_id}")
        inspection = files.inspect(indexed)
        if not inspection.available:
            raise StorageIntegrityError(
                f"引用图片不可用: {version_id} ({inspection.status.value})",
            )
        urls.append(_indexed_path(project_root, indexed).resolve().as_uri())
        checksums.append(version.checksum)
        read_set.append(
            {
                "ref": (
                    f"asset-version:{version_id}"
                    if source is not None
                    else f"artifact-version:{version_id}"
                ),
                "versionId": version_id,
                "fileId": indexed.file_id,
                "checksum": version.checksum,
            },
        )
    return urls, checksums, read_set


def _lineup_character_reference_ids(
    project: Any,
    lineup: Any,
) -> tuple[list[str], list[str]]:
    """Identity anchors for every lineup character, placement order kept.

    Each character contributes its canonical variant's selected artifact
    (the identity master), falling back to any variant with a selected
    artifact, then to the entity-level selection. Characters without any
    generated artifact are reported so the caller can fail actionably —
    a lineup drawn from text alone cannot lock relative consistency.
    """

    version_ids: list[str] = []
    missing: list[str] = []
    for ref in lineup.character_refs:
        entity = project.visual.entities.items.get(ref)
        if entity is None:
            missing.append(ref)
            continue
        variant = None
        if entity.canonical_variant_id:
            variant = entity.variants.items.get(entity.canonical_variant_id)
        if variant is None or not variant.selected_artifact_version_id:
            variant = next(
                (
                    item
                    for item in entity.variants.items.values()
                    if item.selected_artifact_version_id
                ),
                variant,
            )
        selected = (
            variant.selected_artifact_version_id
            if variant is not None and variant.selected_artifact_version_id
            else entity.selected_artifact_version_id
        )
        if selected:
            version_ids.append(selected)
        else:
            missing.append(ref)
    return version_ids, missing


def _resolve_request(
    *,
    snapshot: ProjectSnapshot,
    project_root: Path,
    command: CreatorCommandType,
    target_ref: str,
    arguments: Mapping[str, Any],
) -> _ResolvedRequest:
    project = snapshot.project
    explicit_prompt = str(arguments.get("prompt") or "").strip()
    mode = (
        str(arguments.get("mode") or "generate").strip().casefold()
        or "generate"
    )
    if mode not in _IMAGE_MODES:
        raise ValidationError(
            f"mode 必须是 {', '.join(_IMAGE_MODES)} 之一",
        )
    source_lang = str(arguments.get("sourceLang") or "").strip()
    target_lang = str(arguments.get("targetLang") or "").strip()
    reference_image_refs = _list_of_strings(
        arguments.get("referenceImageRefs"),
        label="referenceImageRefs",
    )
    if len(reference_image_refs) > _EDIT_MAX_REFERENCES:
        raise ValidationError(
            f"referenceImageRefs 最多 {_EDIT_MAX_REFERENCES} 个",
        )
    # Each entry is either a bare exact version id or an
    # asset://... / artifact://...@<versionId> reference.
    reference_image_ref_ids = [
        _exact_version_from_ref(item) or item for item in reference_image_refs
    ]
    explicit_version_ids = _list_of_strings(
        arguments.get("referenceVersionIds")
        or arguments.get("referenceAssetVersionIds"),
        label="referenceVersionIds",
    )
    explicit_urls, exact_ref_version_ids = _explicit_references(arguments)
    if mode == "translate":
        if len(reference_image_ref_ids) != 1:
            raise ValidationError(
                "translate 模式需要且仅需要 1 个 referenceImageRefs"
                "（图内文字翻译的输入图 exact version id）",
            )
        if explicit_urls:
            raise ValidationError(
                "translate 模式仅接受 referenceImageRefs，不接受 referenceImageUrls",
            )
    explicit_version_ids = [
        *explicit_version_ids,
        *exact_ref_version_ids,
        *reference_image_ref_ids,
    ]

    if command is CreatorCommandType.GENERATE_STORYBOARD_IMAGE:
        element_id = target_element_id(
            target_ref,
            command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE.value,
        )
        _, element = find_timeline_element(project, element_id)
        creation = element.creation
        if not isinstance(creation, R2VCreation):
            raise ValidationError("仅 R2V Element 可以生成分镜图")
        assert_visual_design_ready_for_storyboards(project)
        prompt = explicit_prompt or creation.storyboard_prompt.strip()
        if not prompt:
            shot_text = "；".join(
                shot.description.strip()
                for shot in creation.shots.items.values()
                if shot.description.strip()
            )
            prompt = "，".join(
                item
                for item in (
                    element.label.strip(),
                    creation.narrative.strip(),
                    shot_text,
                )
                if item
            )
        if not prompt:
            raise ValidationError("生成分镜图需要 storyboard prompt")
        version_ids = list(
            resolve_r2v_visual_reference_version_ids(
                project,
                creation,
                [
                    *creation.storyboard_reference_version_ids,
                    *explicit_version_ids,
                ],
            ),
        )
        resolved = _ResolvedRequest(
            command=command,
            target_ref=target_ref,
            prompt=prompt,
            aspect_ratio=project.settings.aspect_ratio,
            reference_image_urls=(),
            reference_version_ids=tuple(dict.fromkeys(version_ids)),
            reference_checksums=(),
            read_set=(),
            slot_id=f"element:{element_id}:storyboard",
            slot_kind="r2v_storyboard_image",
            owner_ref=f"element:{element_id}",
            artifact_name=f"{element.label or element_id} 分镜图",
            role=SpecialistRole.R2V_GENERATION_DIRECTOR,
            target_id=element_id,
        )
    elif command is CreatorCommandType.GENERATE_ASSET:
        entity_id = _target_id(target_ref, "asset")
        entity = project.visual.entities.items.get(entity_id)
        if entity is None:
            raise NotFoundError("视觉 Asset 不存在")
        variant = _variant_for(entity, arguments)
        prompt = explicit_prompt or (variant.prompt.strip() if variant else "")
        if not prompt:
            prompt = "，".join(
                item
                for item in (
                    entity.name.strip(),
                    entity.description.strip(),
                    project.visual.style.strip(),
                )
                if item
            )
        if not prompt:
            raise ValidationError("生成视觉 Asset 需要 prompt 或描述")
        version_ids = [
            *(variant.reference_asset_version_ids if variant else []),
            *(variant.reference_artifact_version_ids if variant else []),
            *explicit_version_ids,
        ]
        resolved = _ResolvedRequest(
            command=command,
            target_ref=f"asset:{entity_id}",
            prompt=prompt,
            aspect_ratio=project.settings.aspect_ratio,
            reference_image_urls=(),
            reference_version_ids=tuple(dict.fromkeys(version_ids)),
            reference_checksums=(),
            read_set=(),
            # ArtifactSlot IDs are opaque. Entity and Variant IDs may already
            # contain colons, so consumers must not parse this by splitting.
            slot_id=(
                f"asset:{entity_id}:variant:{variant.variant_id}:image"
                if variant
                else f"asset:{entity_id}:image"
            ),
            slot_kind="visual_asset_image",
            owner_ref=f"asset:{entity_id}",
            # Include the Variant in both the slot and title so independently
            # versioned looks remain distinguishable in history and pickers.
            artifact_name=(
                f"{entity.name}（{_variant_display_name(variant.variant_id)}）"
                "视觉图"
                if variant
                else f"{entity.name} 视觉图"
            ),
            role=SpecialistRole.VISUAL_DEVELOPMENT,
            target_id=entity_id,
            variant_id=variant.variant_id if variant else None,
        )
    elif command is CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE:
        lineup_id = _target_id(target_ref, "lineup")
        lineup = project.visual.cast_lineups.items.get(lineup_id)
        if lineup is None:
            raise NotFoundError("阵容图（cast lineup）不存在")
        anchor_ids, missing = _lineup_character_reference_ids(project, lineup)
        if missing:
            raise ValidationError(
                "生成阵容图前，以下角色必须先有已选定的视觉图（canonical "
                "variant 的 selected artifact）：" + "、".join(missing),
            )
        prompt = explicit_prompt or lineup.description.strip()
        character_names = [
            (project.visual.entities.items[ref].name.strip() or ref)
            for ref in lineup.character_refs
        ]
        prompt_parts = [
            "一张多角色阵容对比图（cast lineup）：所有角色全身站立并排，"
            "同一地平线，从左到右依次为：" + "、".join(character_names) + "。",
            "严格保持各角色之间真实的身高与体型比例，风格、光照、色彩基准完全统一。",
        ]
        if prompt:
            prompt_parts.append(prompt)
        if lineup.relative_notes.strip():
            prompt_parts.append(
                f"相对关系要求：{lineup.relative_notes.strip()}",
            )
        if project.visual.style.strip():
            prompt_parts.append(project.visual.style.strip())
        prompt_parts.append(
            "No panel numbers, no captions, no labels, no subtitles, "
            "no watermarks, no annotation text in the image.",
        )
        prompt = "\n".join(prompt_parts)
        version_ids = [
            *anchor_ids,
            *lineup.reference_asset_version_ids,
            *lineup.reference_artifact_version_ids,
            *explicit_version_ids,
        ]
        resolved = _ResolvedRequest(
            command=command,
            target_ref=f"lineup:{lineup_id}",
            prompt=prompt,
            aspect_ratio=project.settings.aspect_ratio,
            reference_image_urls=(),
            reference_version_ids=tuple(dict.fromkeys(version_ids)),
            reference_checksums=(),
            read_set=(),
            slot_id=f"lineup:{lineup_id}:image",
            slot_kind="cast_lineup_image",
            owner_ref=f"lineup:{lineup_id}",
            artifact_name=f"{lineup.name or lineup_id} 阵容图",
            role=SpecialistRole.VISUAL_DEVELOPMENT,
            target_id=lineup_id,
        )
    else:  # pragma: no cover - public entry validates this first
        raise ValidationError(f"不支持的图片命令: {command.value}")

    # In translate mode the provider input is exactly the referenced image;
    # variant/creation references would pollute the single-image contract.
    active_version_ids = (
        tuple(dict.fromkeys(reference_image_ref_ids))
        if mode == "translate"
        else resolved.reference_version_ids
    )
    local_urls, checksums, read_set = _resolve_version_references(
        project=project,
        project_root=project_root,
        version_ids=active_version_ids,
    )
    urls = tuple(
        dict.fromkeys(
            [*local_urls, *([] if mode == "translate" else explicit_urls)],
        ),
    )
    if mode == "edit" and not 1 <= len(urls) <= _EDIT_MAX_REFERENCES:
        raise ValidationError(
            f"edit 模式需要 1–{_EDIT_MAX_REFERENCES} 张参考图，"
            f"当前解析到 {len(urls)} 张；用 referenceImageRefs 指定要编辑的图",
        )
    return _ResolvedRequest(
        command=resolved.command,
        target_ref=resolved.target_ref,
        prompt=resolved.prompt,
        aspect_ratio=resolved.aspect_ratio,
        reference_image_urls=urls,
        reference_version_ids=active_version_ids,
        reference_checksums=tuple(checksums),
        read_set=tuple(read_set),
        slot_id=resolved.slot_id,
        slot_kind=resolved.slot_kind,
        owner_ref=resolved.owner_ref,
        artifact_name=resolved.artifact_name,
        role=resolved.role,
        target_id=resolved.target_id,
        variant_id=resolved.variant_id,
        mode=mode,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def _generated_output_path(value: str, *, allowed_root: Path) -> Path:
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/generated/")
    ):
        raise ValidationError("provider generated URL 非法")
    raw_parts = parsed.path.removeprefix("/generated/").split("/")
    parts = tuple(unquote(part) for part in raw_parts)
    if any(
        not part
        or part in {".", ".."}
        or Path(part).is_absolute()
        or len(Path(part).parts) != 1
        for part in parts
    ):
        raise ValidationError("provider generated URL 路径不安全")
    project_id = allowed_root.parents[2].name
    expected_prefix = ("projects", project_id, "task-work", allowed_root.name)
    if len(parts) <= len(expected_prefix) or parts[:4] != expected_prefix:
        raise ValidationError("provider 输出不属于当前 Task work 目录")
    return allowed_root.joinpath(*parts[4:])


async def _read_controlled_local(
    path: Path,
    *,
    allowed_root: Path,
    max_bytes: int,
) -> bytes:
    try:
        relative = path.relative_to(allowed_root)
    except ValueError as exc:
        raise ValidationError("provider 输出不属于当前 Task work 目录") from exc
    if not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValidationError("provider 本地输出路径不安全")

    def read() -> bytes:
        if (
            os.name == "nt"
            or not hasattr(os, "O_NOFOLLOW")
            or os.open not in os.supports_dir_fd
        ):
            parent = allowed_root
            for segment in relative.parts[:-1]:
                parent = parent / segment
                try:
                    details = parent.lstat()
                except OSError as exc:
                    raise ValidationError(
                        "provider 本地输出不存在、越界或包含 symlink",
                    ) from exc
                if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(
                    details.st_mode,
                ):
                    raise ValidationError(
                        "provider 本地输出不存在、越界或包含 symlink",
                    )
            target = parent / relative.parts[-1]
            try:
                details = target.lstat()
            except OSError as exc:
                raise ValidationError(
                    "provider 本地输出不存在、越界或包含 symlink",
                ) from exc
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(
                details.st_mode,
            ):
                raise ValidationError("provider 本地输出必须是普通文件")
            if details.st_size <= 0 or details.st_size > max_bytes:
                raise ValidationError("provider 图片为空或超过大小限制")
            try:
                with target.open("rb") as handle:
                    content = handle.read(max_bytes + 1)
            except OSError as exc:
                raise ValidationError(
                    "provider 本地输出不存在、越界或包含 symlink",
                ) from exc
            if not content or len(content) > max_bytes:
                raise ValidationError("provider 图片为空或超过大小限制")
            return content

        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        directory_fd: int | None = None
        file_fd: int | None = None
        try:
            directory_fd = os.open(allowed_root, directory_flags)
            for segment in relative.parts[:-1]:
                next_fd = os.open(
                    segment,
                    directory_flags,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(
                relative.parts[-1],
                file_flags,
                dir_fd=directory_fd,
            )
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValidationError("provider 本地输出必须是普通文件")
            if file_stat.st_size <= 0 or file_stat.st_size > max_bytes:
                raise ValidationError("provider 图片为空或超过大小限制")
            remaining = max_bytes + 1
            chunks: list[bytes] = []
            while remaining > 0:
                chunk = os.read(file_fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if not content or len(content) > max_bytes:
                raise ValidationError("provider 图片为空或超过大小限制")
            return content
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                "provider 本地输出不存在、越界或包含 symlink",
            ) from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if directory_fd is not None:
                os.close(directory_fd)

    return await asyncio.to_thread(read)


def _actual_image_media_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return "image/webp"
    if content.startswith(b"BM"):
        return "image/bmp"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    raise ValidationError("provider 输出 magic 不是受支持的图片格式")


def _normalized_image_media_type(value: str) -> str:
    normalized = value.split(";", 1)[0].strip().casefold()
    aliases = {
        "image/jpg": "image/jpeg",
        "image/x-png": "image/png",
        "image/x-ms-bmp": "image/bmp",
    }
    return aliases.get(normalized, normalized)


async def _provider_bytes(
    output: Mapping[str, Any],
    *,
    allowed_local_root: Path,
    max_bytes: int,
) -> tuple[bytes, str]:
    direct = output.get("content")
    if direct is None:
        direct = output.get("bytes")
    source_hint = ""
    if isinstance(direct, (bytes, bytearray, memoryview)):
        content = bytes(direct)
    else:
        source_hint = str(
            output.get("output_path")
            or output.get("path")
            or output.get("url")
            or output.get("result_url")
            or output.get("image_url")
            or "",
        ).strip()
        if not source_hint:
            raise ValidationError("provider 结果缺少图片 bytes/path/url")
        parsed = urlparse(source_hint)
        if source_hint.startswith("/generated/"):
            path = _generated_output_path(
                source_hint,
                allowed_root=allowed_local_root,
            )
        elif parsed.scheme.casefold() == "file":
            if parsed.netloc not in {"", "localhost"}:
                raise ValidationError("provider file URL host 非法")
            path = Path(unquote(parsed.path))
        else:
            path = Path(source_hint).expanduser()
            if not path.is_absolute():
                raise ValidationError("provider 本地输出必须是绝对路径")
        content = await _read_controlled_local(
            path,
            allowed_root=allowed_local_root,
            max_bytes=max_bytes,
        )

    if not content or len(content) > max_bytes:
        raise ValidationError("provider 图片为空或超过大小限制")
    actual = hashlib.sha256(content).hexdigest()
    declared_checksum = str(output.get("checksum") or "").strip()
    if declared_checksum and _plain_sha256(declared_checksum) != actual:
        raise StorageIntegrityError("provider 图片 checksum 与实际字节不一致")
    media_type = _actual_image_media_type(content)
    declared_media_type = _normalized_image_media_type(
        str(output.get("media_type") or ""),
    )
    if declared_media_type and declared_media_type != media_type:
        raise ValidationError("provider media_type 与图片 magic 不一致")
    return content, media_type


def _image_suffix(media_type: str) -> str:
    guessed = mimetypes.guess_extension(media_type) or ".png"
    return guessed if _SAFE_SUFFIX.fullmatch(guessed) else ".png"


def _accepted_provider_task_hint(task_id: str, project_id: str) -> str:
    """Name the billed provider task ids so a result stays retrievable."""

    try:
        from models.provider_tasks import read_provider_tasks

        ids = [
            str(entry.get("providerTaskId"))
            for entry in read_provider_tasks(task_id, project_id)
            if entry.get("providerTaskId")
        ]
    except Exception:  # noqa: BLE001 - hint only
        return ""
    if not ids:
        return ""
    return f" (billed provider task(s): {', '.join(ids)})"


# Only ledger kinds with a working resume implementation may keep a Task
# RUNNING after a local failure: the supervisor polls exactly these to a
# terminal state. An accepted-but-unresumable job (async image generation
# today) must terminalize instead — resume_provider_task() reports it
# "unsupported", so deferring it would strand the paid Task in RUNNING
# forever with nothing left to finish it.
RESUMABLE_PROVIDER_TASK_KINDS = frozenset({"image_translate"})


def resumable_provider_entries(
    task_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """The provider-task ledger entries the resume supervisor can poll."""

    from models.provider_tasks import read_provider_tasks

    return [
        entry
        for entry in read_provider_tasks(task_id, project_id)
        if str(entry.get("kind") or "") in RESUMABLE_PROVIDER_TASK_KINDS
        and entry.get("providerTaskId")
    ]


def _publish_snapshot(resolved: _ResolvedRequest) -> dict[str, Any]:
    """The subset of a resolved request needed to publish its output."""

    return {
        "command": resolved.command.value,
        "targetRef": resolved.target_ref,
        "mode": resolved.mode,
        "prompt": resolved.prompt,
        "aspectRatio": resolved.aspect_ratio,
        "referenceVersionIds": list(resolved.reference_version_ids),
        "readSet": [dict(item) for item in resolved.read_set],
        "slotId": resolved.slot_id,
        "slotKind": resolved.slot_kind,
        "ownerRef": resolved.owner_ref,
        "artifactName": resolved.artifact_name,
        "role": resolved.role.value,
        "targetId": resolved.target_id,
        "variantId": resolved.variant_id,
    }


def _resolved_from_publish_snapshot(
    snapshot: Mapping[str, Any],
) -> _ResolvedRequest:
    """Rebuild the publish-relevant resolved request after a restart."""

    return _ResolvedRequest(
        command=CreatorCommandType(str(snapshot["command"])),
        target_ref=str(snapshot["targetRef"]),
        prompt=str(snapshot.get("prompt") or ""),
        aspect_ratio=str(snapshot.get("aspectRatio") or "16:9"),
        reference_image_urls=(),
        reference_version_ids=tuple(
            str(item) for item in snapshot.get("referenceVersionIds") or ()
        ),
        reference_checksums=(),
        read_set=tuple(dict(item) for item in snapshot.get("readSet") or ()),
        slot_id=str(snapshot["slotId"]),
        slot_kind=str(snapshot["slotKind"]),
        owner_ref=str(snapshot["ownerRef"]),
        artifact_name=str(snapshot.get("artifactName") or ""),
        role=SpecialistRole(str(snapshot["role"])),
        target_id=str(snapshot.get("targetId") or ""),
        variant_id=(
            str(snapshot["variantId"]) if snapshot.get("variantId") else None
        ),
        mode=str(snapshot.get("mode") or "generate"),
    )


class FileImageExecutionService:
    """Convergent P0 image worker over Project and Runtime files."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        provider: ImageProvider | None = None,
        max_output_bytes: int = _MAX_IMAGE_BYTES,
        resume_poll_interval_seconds: float = _RESUME_POLL_INTERVAL_SECONDS,
        resume_poll_budget_seconds: float = _RESUME_POLL_BUDGET_SECONDS,
        resume_retry_interval_seconds: float = _RESUME_RETRY_INTERVAL_SECONDS,
        resume_horizon_seconds: float = _RESUME_HORIZON_SECONDS,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.services = services
        self.provider = provider or ExistingImageProvider()
        self.executions = ProjectExecutionStore(services.root)
        self.max_output_bytes = max_output_bytes
        self.resume_poll_interval_seconds = resume_poll_interval_seconds
        self.resume_poll_budget_seconds = resume_poll_budget_seconds
        self.resume_retry_interval_seconds = resume_retry_interval_seconds
        self.resume_horizon_seconds = resume_horizon_seconds
        # Background pollers for accepted (billed) async provider tasks,
        # keyed by Task id so one Task is never supervised twice.
        self._resume_jobs: dict[str, asyncio.Task] = {}
        # (project_id, target_ref) -> reference ids of the last safety-
        # rejected call. Process-local: worth losing on restart, priceless
        # for cutting off same-refs resend loops within a session.
        self._safety_rejected_refs: dict[tuple[str, str], frozenset[str]] = {}

    async def execute(
        self,
        *,
        project_id: str,
        command: CreatorCommandType | str,
        target_ref: str,
        arguments: Mapping[str, Any],
        idempotency_key: str,
        expected_object_versions: Sequence[str] = (),
    ) -> FileImageExecutionResult:
        command_value = CreatorCommandType(command)
        if command_value not in _IMAGE_COMMANDS:
            raise ValidationError(f"不支持的文件图片命令: {command_value.value}")
        ids = self._ids(project_id, idempotency_key)
        command_request_hash = _fingerprint(
            {
                "command": command_value.value,
                "targetRef": target_ref,
                "arguments": dict(arguments),
            },
        )
        # Identical retries reuse the same durable slot, so a transient
        # provider failure (network, timeout, 5xx) would otherwise become a
        # permanent ConflictError wall for this run. Probe a bounded number
        # of derived retry slots for transient failures only; deterministic
        # rejections (safety refusals, validation) keep the terminal wall.
        existing_task = None
        for attempt in range(MAX_TRANSIENT_RETRY_SLOTS + 1):
            slot_key = transient_retry_slot_key(idempotency_key, attempt)
            ids = self._ids(project_id, slot_key)
            try:
                existing_task = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    ids["task_id"],
                )
            except RecordNotFoundError:
                existing_task = None
                break
            self._assert_command_replay(
                existing_task,
                command=command_value,
                target_ref=target_ref,
                command_request_hash=command_request_hash,
            )
            if existing_task.status is TaskStatus.SUCCEEDED:
                return self._result_from_task(existing_task, replayed=True)
            if existing_task.status is TaskStatus.RUNNING:
                if existing_task.result is None:
                    raise ConflictError("图片 Task 已由另一个执行者领取")
                return await self._converge(
                    task=existing_task,
                    ids=ids,
                    replayed=True,
                )
            if existing_task.status is TaskStatus.FAILED and (
                is_transient_task_error(existing_task.error)
            ):
                continue
            if existing_task.status is TaskStatus.QUARANTINED:
                rescued = await self._rescue_stale_quarantine(
                    task=existing_task,
                    slot_key=slot_key,
                )
                if rescued is not None:
                    return rescued
            raise _terminated_task_conflict(existing_task)
        else:
            raise _terminated_task_conflict(
                existing_task,
                exhausted_retries=True,
            )

        base = await asyncio.to_thread(self.services.projects.read, project_id)
        conflicts = [
            value
            for value in expected_object_versions
            if f"project:{base.etag}:" not in value
        ]
        if conflicts:
            raise ConflictError("图片命令目标已被其他写者修改")
        project_root = self.services.projects.project_root(project_id)
        resolved = await asyncio.to_thread(
            _resolve_request,
            snapshot=base,
            project_root=project_root,
            command=command_value,
            target_ref=target_ref,
            arguments=dict(arguments),
        )
        fingerprint_payload: dict[str, Any] = {
            "command": command_value.value,
            "targetRef": resolved.target_ref,
            "prompt": resolved.prompt,
            "aspectRatio": resolved.aspect_ratio,
            "referenceImageUrls": list(resolved.reference_image_urls),
            "referenceVersionIds": list(resolved.reference_version_ids),
            "referenceChecksums": list(resolved.reference_checksums),
            "inputGeneration": base.generation,
            "inputEtag": base.etag,
        }
        if resolved.mode != "generate":
            # Only non-default modes join the fingerprint so legacy generate
            # requests keep their replay identity across the upgrade.
            fingerprint_payload.update(
                {
                    "mode": resolved.mode,
                    "sourceLang": resolved.source_lang,
                    "targetLang": resolved.target_lang,
                },
            )
        request_fingerprint = _fingerprint(fingerprint_payload)
        reviews = await asyncio.to_thread(
            self.services.reviews.all_pending,
            project_id,
        )
        assert_media_review_admission(
            reviews=reviews,
            command_type=command_value.value,
            target_ref=resolved.target_ref,
            variant_id=resolved.variant_id,
            reference_version_ids=resolved.reference_version_ids,
        )
        run, task = await self._admit(
            base=base,
            resolved=resolved,
            request_fingerprint=request_fingerprint,
            command_request_hash=command_request_hash,
            idempotency_key=idempotency_key,
            ids=ids,
        )
        if task.status is TaskStatus.SUCCEEDED:
            return self._result_from_task(task, replayed=True)
        if task.status in {
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.QUARANTINED,
        }:
            raise _terminated_task_conflict(task)

        if task.status is TaskStatus.RUNNING and task.result is not None:
            return await self._converge(
                task=task,
                ids=ids,
                replayed=True,
            )

        task = await self._start(
            run=run,
            task=task,
            resolved=resolved,
            ids=ids,
        )
        if not await self._claim_provider(task):
            raise ConflictError("图片 Task 已由另一个执行者领取")

        try:
            # No Project/Runtime lock spans this await.  The ContextVar only
            # scopes compatibility scratch emitted by the existing provider.
            self._block_known_safety_refs(project_id, resolved)
            with media_task_scope(task.task_id, project_id=project_id):
                extra_arguments: dict[str, Any] = {}
                if resolved.mode != "generate":
                    # Passed only for explicit modes so injected test
                    # providers with the legacy signature keep working.
                    extra_arguments = {
                        "mode": resolved.mode,
                        "source_lang": resolved.source_lang,
                        "target_lang": resolved.target_lang,
                    }
                provider_output = await self.provider.generate(
                    prompt=resolved.prompt,
                    aspect_ratio=resolved.aspect_ratio,
                    reference_image_urls=resolved.reference_image_urls,
                    **extra_arguments,
                )
            published_result = await self._materialize_and_publish(
                base=base,
                resolved=resolved,
                task=task,
                ids=ids,
                output=provider_output,
            )
            latest = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task.task_id,
            )
            if latest.status is TaskStatus.CANCELLED:
                await self._quarantine(
                    task=latest,
                    ids=ids,
                    reason="TASK_CANCELLED_BEFORE_IMPORT",
                    result=published_result,
                    run_status=SpecialistRunStatus.CANCELLED,
                )
                raise ConflictError("图片 Task 已取消，迟到结果已隔离")
            try:
                task = await asyncio.to_thread(
                    self.executions.transition_task,
                    project_id,
                    task.task_id,
                    expected_status=TaskStatus.RUNNING,
                    status=TaskStatus.RUNNING,
                    updates={
                        "progress": 0.9,
                        "result": published_result,
                        "output_refs": [
                            f"artifact-version:{ids['artifact_version_id']}",
                        ],
                    },
                )
            except ExecutionStateConflict:
                latest = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    task.task_id,
                )
                if latest.status is not TaskStatus.CANCELLED:
                    raise
                await self._quarantine(
                    task=latest,
                    ids=ids,
                    reason="TASK_CANCELLED_BEFORE_IMPORT",
                    result=published_result,
                    run_status=SpecialistRunStatus.CANCELLED,
                )
                raise ConflictError("图片 Task 已取消，迟到结果已隔离")
            return await self._converge(
                task=task,
                ids=ids,
                replayed=False,
            )
        except (ConflictError, ValidationError, StorageIntegrityError):
            if not await self._defer_to_resume_supervisor(project_id, ids):
                await self._fail_if_running(
                    project_id,
                    ids,
                    "IMAGE_GENERATION_FAILED",
                    message=(
                        "IMAGE_GENERATION_FAILED"
                        + _accepted_provider_task_hint(
                            ids["task_id"],
                            project_id,
                        )
                    ),
                )
            raise
        except Exception as exc:
            if await self._defer_to_resume_supervisor(project_id, ids):
                raise ConflictError(
                    "图片 provider 任务已被受理（已计费）但本地等待未完成；"
                    "后台轮询已接管，完成后会自动写回 Asset Index，"
                    "请勿重复提交",
                ) from exc
            message = str(exc)
            if _is_safety_rejection_message(message):
                self._note_safety_rejection(project_id, resolved)
                message = f"{message} {_safety_rejection_note(resolved)}"
                exc = ModelError(
                    message,
                    model_name=getattr(exc, "model_name", ""),
                    retryable=False,
                )
            await self._fail_if_running(
                project_id,
                ids,
                "IMAGE_GENERATION_FAILED",
                message=message
                + _accepted_provider_task_hint(ids["task_id"], project_id),
            )
            raise exc

    def _block_known_safety_refs(
        self,
        project_id: str,
        resolved: _ResolvedRequest,
    ) -> None:
        """Refuse locally when a safety-rejected ref set is resent verbatim.

        The provider's answer is deterministic for the same references, so
        replaying them with a reworded prompt only burns quota and turns.
        """

        refs = frozenset(_resolved_reference_ids(resolved))
        if not refs:
            return
        rejected = self._safety_rejected_refs.get(
            (project_id, resolved.target_ref),
        )
        if rejected is not None and refs == rejected:
            raise ConflictError(
                "已本地拦截：上一次 safety 拒绝时携带的是完全相同的图片参考 "
                f"[{', '.join(sorted(refs)[:6])}]。"
                + _safety_rejection_note(resolved),
            )

    def _note_safety_rejection(
        self,
        project_id: str,
        resolved: _ResolvedRequest,
    ) -> None:
        refs = frozenset(_resolved_reference_ids(resolved))
        if refs:
            self._safety_rejected_refs[
                (project_id, resolved.target_ref)
            ] = refs

    async def _defer_to_resume_supervisor(
        self,
        project_id: str,
        ids: Mapping[str, str],
    ) -> bool:
        """Keep an accepted (billed) async provider task alive and supervised.

        A local failure after the provider accepted the job — a polling
        budget that expired, a dropped connection — must not terminalize the
        Task: the paid result still exists upstream, so the Task stays
        RUNNING and the background poller finishes it.

        Only ledger kinds the supervisor can actually resume qualify. An
        accepted job of any other kind must fail closed at the call site
        (with the billed id named) instead of staying RUNNING behind a
        supervisor that would drop it as "unsupported".
        """

        try:
            accepted = resumable_provider_entries(ids["task_id"], project_id)
        except Exception:  # noqa: BLE001 - bookkeeping must not mask errors
            return False
        if not accepted:
            return False
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                ids["task_id"],
            )
        except RecordNotFoundError:
            return False
        if task.status is not TaskStatus.RUNNING or task.result is not None:
            return False
        logger.info(
            "image provider task accepted but not awaited; handing it to the "
            "background poller | task=%s provider_task=%s",
            task.task_id,
            accepted[-1].get("providerTaskId"),
        )
        self.schedule_resume(task)
        return True

    def schedule_resume(self, task: TaskRecord) -> None:
        """Poll one accepted provider task in the background until terminal."""

        existing = self._resume_jobs.get(task.task_id)
        if existing is not None and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        job = loop.create_task(
            self._resume_until_terminal(task),
            name=f"image-translate-resume:{task.task_id}",
        )
        self._resume_jobs[task.task_id] = job
        job.add_done_callback(
            lambda _job, task_id=task.task_id: self._resume_jobs.pop(
                task_id,
                None,
            ),
        )

    async def _resume_until_terminal(self, task: TaskRecord) -> None:
        """Supervise one accepted provider task across transient failures.

        The provider keeps a finished result for 24h, so polling continues
        well past a single pass; only a definitive provider failure or an
        exhausted horizon terminalizes the Task.
        """

        deadline = (
            asyncio.get_running_loop().time() + self.resume_horizon_seconds
        )
        failures = 0
        while True:
            try:
                outcome = await self.resume_provider_task(
                    task,
                    poll_interval_seconds=self.resume_poll_interval_seconds,
                    poll_budget_seconds=self.resume_poll_budget_seconds,
                )
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - retry transient errors
                failures += 1
                outcome = "error"
                logger.warning(
                    "image provider task resume attempt failed (%d) | "
                    "task=%s: %s",
                    failures,
                    task.task_id,
                    error,
                )
                # A retryable failure never terminalizes a paid task: the
                # count only drives backoff, so a network or parsing outage
                # cannot strand a result that is still retrievable upstream.
            if outcome in {"published", "failed", "unsupported", "cancelled"}:
                return
            try:
                latest = await asyncio.to_thread(
                    self.executions.get_task,
                    task.project_id,
                    task.task_id,
                )
            except RecordNotFoundError:
                return
            if latest.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                # Cancelled or terminalized elsewhere; stop supervising.
                return
            if asyncio.get_running_loop().time() >= deadline:
                await self._fail_if_running(
                    task.project_id,
                    self._ids(
                        task.project_id,
                        str(task.idempotency_key or task.task_id),
                    ),
                    "IMAGE_RESUME_TIMEOUT",
                    message=(
                        "the accepted image provider task did not finish "
                        f"within {self.resume_horizon_seconds:.0f}s"
                        + _accepted_provider_task_hint(
                            task.task_id,
                            task.project_id,
                        )
                    ),
                )
                return
            await asyncio.sleep(self._resume_backoff_seconds(failures))

    def _resume_backoff_seconds(self, failures: int) -> float:
        """Exponential backoff for retries, capped; 0 keeps tests fast."""

        interval = self.resume_retry_interval_seconds
        if failures <= 0 or interval <= 0:
            return interval
        return min(
            interval * (2 ** min(failures - 1, _RESUME_BACKOFF_MAX_SHIFT)),
            _RESUME_BACKOFF_CAP_SECONDS,
        )

    def notify_terminal_task(self, task: TaskRecord) -> None:
        """Stop supervising a Task that a user cancelled or terminalized.

        The provider task may already be paid for, but a cancelled Task must
        not gain a late artifact; the durable ledger still names the billed
        id for manual retrieval.
        """

        job = self._resume_jobs.pop(task.task_id, None)
        if job is not None and not job.done():
            logger.info(
                "cancelling image resume supervision | task=%s status=%s",
                task.task_id,
                task.status.value,
            )
            job.cancel()

    async def drain_resume_jobs(self) -> None:
        """Await the background resume jobs (used by startup and tests)."""

        while True:
            jobs = [
                job for job in self._resume_jobs.values() if not job.done()
            ]
            if not jobs:
                return
            await asyncio.gather(*jobs, return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel background resume jobs; durable state stays resumable."""

        jobs = list(self._resume_jobs.values())
        self._resume_jobs.clear()
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    @staticmethod
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
            "artifact_version_id": _stable_id(
                "artifact-version",
                project_id,
                key,
            ),
            "transaction_id": _stable_id("media-transaction", project_id, key),
            "quarantine_id": _stable_id("quarantine", project_id, key),
        }

    async def _admit(
        self,
        *,
        base: ProjectSnapshot,
        resolved: _ResolvedRequest,
        request_fingerprint: str,
        command_request_hash: str,
        idempotency_key: str,
        ids: Mapping[str, str],
    ) -> tuple[SpecialistRunRecord, TaskRecord]:
        run_candidate = SpecialistRunRecord(
            run_id=ids["run_id"],
            project_id=base.project.project_id,
            round_id=ids["round_id"],
            role=resolved.role,
            target_refs=[resolved.target_ref],
            input_generation=base.generation,
            input_etag=base.etag,
            request_fingerprint=request_fingerprint,
            read_set=list(resolved.read_set),
            caused_by_request_id=idempotency_key,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata={
                "commandType": resolved.command.value,
                "targetRef": resolved.target_ref,
                "variantId": resolved.variant_id,
                "commandRequestHash": command_request_hash,
            },
        )
        try:
            run = await asyncio.to_thread(
                self.executions.get_run,
                base.project.project_id,
                ids["run_id"],
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
            raise ConflictError("Idempotency-Key 已用于不同的图片 Run")

        task_candidate = TaskRecord(
            task_id=ids["task_id"],
            project_id=base.project.project_id,
            round_id=ids["round_id"],
            run_id=ids["run_id"],
            kind=TaskKind.IMAGE_GENERATION,
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
                "commandType": resolved.command.value,
                "targetRef": resolved.target_ref,
                "variantId": resolved.variant_id,
                "commandRequestHash": command_request_hash,
                "slotId": resolved.slot_id,
                "artifactVersionId": ids["artifact_version_id"],
                "fileId": ids["file_id"],
                # Frozen publish inputs, so an interrupted provider task can
                # be resumed and published after a restart without
                # re-resolving (and possibly re-billing) anything.
                "requestSnapshot": _publish_snapshot(resolved),
            },
        )
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                base.project.project_id,
                ids["task_id"],
            )
        except RecordNotFoundError:
            try:
                task = await asyncio.to_thread(
                    self.executions.create_task,
                    task_candidate,
                )
            except (ExecutionPayloadConflict, ExecutionStateConflict) as exc:
                raise ConflictError(str(exc)) from exc
        if (
            task.request_fingerprint != request_fingerprint
            or task.input_etag != base.etag
            or task.input_refs != task_candidate.input_refs
        ):
            raise ConflictError("Idempotency-Key 已用于不同的图片 Task")
        return run, task

    @staticmethod
    def _assert_command_replay(
        task: TaskRecord,
        *,
        command: CreatorCommandType,
        target_ref: str,
        command_request_hash: str,
    ) -> None:
        if (
            task.metadata.get("commandType") != command.value
            or task.metadata.get("targetRef") != target_ref
            or task.metadata.get("commandRequestHash") != command_request_hash
        ):
            raise ConflictError("Idempotency-Key 已用于不同的图片命令")

    async def _claim_provider(self, task: TaskRecord) -> bool:
        """Durably claim the one-shot provider call without holding a lock.

        A surviving claim with no result is intentionally not auto-retried:
        doing so could duplicate a non-idempotent provider job after a crash.
        """

        claim = {
            "taskId": task.task_id,
            "requestFingerprint": task.request_fingerprint,
            "claimedAt": datetime.now(UTC).isoformat(),
        }

        def claim_sync():
            with self.services.projects.lifecycle_lock(task.project_id):
                self.services.projects.read(task.project_id)
                claim_store = AtomicJsonRecordStore(
                    self.services.projects.project_root(task.project_id)
                    / "runtime"
                    / "tasks"
                    / task.task_id
                    / "provider-claim.json",
                )
                created = claim_store.try_create(claim)
                existing = None if created is not None else claim_store.read()
                return created, existing

        created, existing = await asyncio.to_thread(claim_sync)
        if created is not None:
            return True
        assert isinstance(existing, dict)
        if (
            existing.get("taskId") != task.task_id
            or existing.get("requestFingerprint") != task.request_fingerprint
        ):
            raise StorageIntegrityError("图片 provider claim 内容损坏")
        return False

    async def _start(
        self,
        *,
        run: SpecialistRunRecord,
        task: TaskRecord,
        resolved: _ResolvedRequest,
        ids: Mapping[str, str],
    ) -> TaskRecord:
        project_id = task.project_id
        if run.status in {
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.QUEUED_CAPACITY,
        }:
            run = await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.RUNNING_MODEL,
            )
        if task.status is TaskStatus.QUEUED:
            await asyncio.to_thread(
                self.executions.append_attempt,
                project_id,
                task.task_id,
                event_id=ids["attempt_started_event_id"],
                attempt_id=ids["attempt_id"],
                status=TaskAttemptStatus.RUNNING,
                input={
                    "command": resolved.command.value,
                    "targetRef": resolved.target_ref,
                    "prompt": resolved.prompt,
                    "aspectRatio": resolved.aspect_ratio,
                    "referenceImageUrls": list(resolved.reference_image_urls),
                    "referenceVersionIds": list(
                        resolved.reference_version_ids,
                    ),
                    "referenceChecksums": list(resolved.reference_checksums),
                    "variantId": resolved.variant_id,
                    "artifactVersionId": ids["artifact_version_id"],
                },
            )
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task.task_id,
            )
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run.run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.WAITING_RUNTIME,
            )
        return task

    async def _materialize_and_publish(
        self,
        *,
        base: ProjectSnapshot,
        resolved: _ResolvedRequest,
        task: TaskRecord,
        ids: Mapping[str, str],
        output: Mapping[str, Any],
    ) -> dict[str, Any]:
        project_root = self.services.projects.project_root(
            base.project.project_id,
        )
        content, media_type = await _provider_bytes(
            output,
            allowed_local_root=(
                project_root / "runtime" / "task-work" / task.task_id
            ),
            max_bytes=self.max_output_bytes,
        )
        timestamp = datetime.now(UTC)
        checksum = hashlib.sha256(content).hexdigest()
        relative_uri = PurePosixPath(
            "assets",
            "artifacts",
            f"{ids['file_id']}{_image_suffix(media_type)}",
        ).as_posix()
        indexed = IndexedFile(
            file_id=ids["file_id"],
            kind="artifact_payload",
            relative_uri=relative_uri,
            sha256=checksum,
            size_bytes=len(content),
            media_type=media_type,
            created_at=timestamp,
        )
        artifact = ArtifactVersion(
            version_id=ids["artifact_version_id"],
            slot_id=resolved.slot_id,
            kind=resolved.slot_kind,
            owner_ref=resolved.owner_ref,
            name=resolved.artifact_name,
            file_id=ids["file_id"],
            checksum=checksum,
            based_on_generation=task.input_generation or base.generation,
            provenance_refs=[str(item["ref"]) for item in resolved.read_set],
            input_fingerprint=task.request_fingerprint,
            created_at=timestamp,
            metadata={
                "taskId": task.task_id,
                "runId": task.run_id,
                "commandType": resolved.command.value,
                "targetRef": resolved.target_ref,
                "variantId": resolved.variant_id,
                "provider": _json_mapping(output.get("metadata")),
            },
        )
        file_store = AssetFileStore(project_root)
        staged = await asyncio.to_thread(
            file_store.stage_bytes,
            content,
            staging_id=task.task_id[:80],
        )
        try:
            await asyncio.to_thread(
                file_store.publish,
                staged,
                relative_uri,
                expected_sha256=checksum,
                expected_size_bytes=len(content),
            )
        except AssetAlreadyExists:
            await asyncio.to_thread(file_store.abandon, staged)
            inspection = await asyncio.to_thread(file_store.inspect, indexed)
            if not inspection.available:
                raise StorageIntegrityError("稳定图片输出路径已存在但内容不同")
        return {
            "taskId": task.task_id,
            "runId": task.run_id,
            "transactionId": ids["transaction_id"],
            "commandType": resolved.command.value,
            "targetRef": resolved.target_ref,
            "variantId": resolved.variant_id,
            "indexedFile": indexed.model_dump(mode="json"),
            "artifactVersion": artifact.model_dump(mode="json"),
            "outputRef": f"artifact-version:{artifact.version_id}",
        }

    async def resume_provider_task(
        self,
        task: TaskRecord,
        *,
        poll_interval_seconds: float = 3.0,
        poll_budget_seconds: float = 120.0,
    ) -> str:
        """Resume an interrupted asynchronous provider task, then publish.

        Only tasks whose provider work is a *server-side* job can be
        resumed: the accepted (billed) id lives in the paying Task's durable
        ledger, so a restart continues polling, downloads the result and
        publishes it through the normal commit boundary instead of throwing
        the paid output away.

        Returns ``"published"`` / ``"failed"`` / ``"pending"``; ``pending``
        leaves the Task active so the next recovery pass resumes again.
        """

        entries = resumable_provider_entries(task.task_id, task.project_id)
        if not entries:
            return "unsupported"
        snapshot = task.metadata.get("requestSnapshot")
        if not isinstance(snapshot, Mapping):
            return "unsupported"
        provider_task_id = str(entries[-1]["providerTaskId"])
        from models.image import poll_image_translate_task

        deadline = asyncio.get_running_loop().time() + poll_budget_seconds
        while True:
            result = await poll_image_translate_task(provider_task_id)
            status = str(result.get("status") or "")
            if status in {"SUCCEEDED", "FAILED"}:
                break
            if asyncio.get_running_loop().time() >= deadline:
                logger.info(
                    "image translate task still running after restart; "
                    "will resume again | task=%s provider_task=%s",
                    task.task_id,
                    provider_task_id,
                )
                return "pending"
            await asyncio.sleep(poll_interval_seconds)

        ids = self._ids(
            task.project_id,
            str(task.idempotency_key or task.task_id),
        )
        if status == "FAILED":
            await self._fail_if_running(
                task.project_id,
                ids,
                "IMAGE_PROVIDER_FAILED",
                message=(
                    "resumed image translate task failed: "
                    f"{result.get('error')} (provider_task={provider_task_id})"
                ),
            )
            return "failed"

        translated_url = str(result.get("image_url") or "")
        if not translated_url:
            await self._fail_if_running(
                task.project_id,
                ids,
                "IMAGE_PROVIDER_FAILED",
                message=(
                    "resumed image translate task succeeded without an image "
                    f"url (provider_task={provider_task_id})"
                ),
            )
            return "failed"
        return await self._publish_resumed_output(
            task=task,
            ids=ids,
            snapshot=snapshot,
            translated_url=translated_url,
            model_name=str(entries[-1].get("model") or "qwen-mt-image"),
            provider_task_id=provider_task_id,
        )

    async def _publish_resumed_output(
        self,
        *,
        task: TaskRecord,
        ids: Mapping[str, str],
        snapshot: Mapping[str, Any],
        translated_url: str,
        model_name: str,
        provider_task_id: str,
    ) -> str:
        """Download and publish a resumed result under the same boundary.

        Mirrors the in-process commit path: a Task cancelled before or during
        publication never gains an artifact, and a late result is
        quarantined instead of left unreferenced.
        """

        # Re-read the Task first: it may have been cancelled while this job
        # was queued, and a cancelled Task must not gain a published file.
        try:
            current = await asyncio.to_thread(
                self.executions.get_task,
                task.project_id,
                task.task_id,
            )
        except RecordNotFoundError:
            return "cancelled"
        if current.status is not TaskStatus.RUNNING:
            logger.info(
                "resumed image task is no longer running (%s); skipping "
                "publication | task=%s provider_task=%s",
                current.status.value,
                task.task_id,
                provider_task_id,
            )
            return "cancelled"
        base = await asyncio.to_thread(
            self.services.projects.read,
            task.project_id,
        )
        resolved = _resolved_from_publish_snapshot(snapshot)
        with media_task_scope(task.task_id, project_id=task.project_id):
            from models.image.base import download_remote_image

            generated_url = await download_remote_image(
                translated_url,
                model_name,
            )
            published_result = await self._materialize_and_publish(
                base=base,
                resolved=resolved,
                task=task,
                ids=ids,
                output={"url": generated_url, "media_type": "image/png"},
            )
        # Record the immutable result on the Task, then converge it exactly
        # like the in-process path does, so the Task reaches SUCCEEDED and
        # the Project commit becomes visible.
        try:
            task = await asyncio.to_thread(
                self.executions.transition_task,
                task.project_id,
                task.task_id,
                expected_status=TaskStatus.RUNNING,
                status=TaskStatus.RUNNING,
                updates={
                    "progress": 0.9,
                    "result": published_result,
                    "output_refs": [
                        f"artifact-version:{ids['artifact_version_id']}",
                    ],
                },
            )
        except ExecutionStateConflict:
            latest = await asyncio.to_thread(
                self.executions.get_task,
                task.project_id,
                task.task_id,
            )
            if latest.status is not TaskStatus.CANCELLED:
                raise
            await self._quarantine(
                task=latest,
                ids=ids,
                reason="TASK_CANCELLED_BEFORE_IMPORT",
                result=published_result,
                run_status=SpecialistRunStatus.CANCELLED,
            )
            return "cancelled"
        await self._converge(task=task, ids=ids, replayed=True)
        logger.info(
            "resumed image translate task published | task=%s provider_task=%s",
            task.task_id,
            provider_task_id,
        )
        return "published"

    async def _converge(
        self,
        *,
        task: TaskRecord,
        ids: Mapping[str, str],
        replayed: bool,
    ) -> FileImageExecutionResult:
        if not isinstance(task.result, dict):
            raise StorageIntegrityError("RUNNING 图片 Task 缺少可重放 result")
        result = dict(task.result)

        def commit_if_live() -> tuple[str, TaskRecord, ProjectSnapshot | None]:
            # Cancellation and Project import share one lifecycle decision.
            # Whichever acquires this lock first determines whether the
            # immutable provider output is indexed or quarantined.
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
                elif (
                    current.etag != latest.input_etag
                    or current.generation != latest.input_generation
                ) and not self._read_set_still_current(
                    current.project,
                    latest,
                ):
                    return "STALE", latest, current
                else:
                    candidate = current.project.model_dump(mode="json")
                    self._apply_result(candidate, result)
                    # Generated images (storyboards and character art) are
                    # reviewed before acceptance unless the operator opted
                    # into unattended auto-approval; an AUTO_FIX round must
                    # not carry a ReviewBoundary.
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
                        round_id=ids["round_id"],
                        transaction_id=ids["transaction_id"],
                        advance_accepted_baseline=True,
                        _lifecycle_lock_held=True,
                    )
                    snapshot = commit.snapshot
                success = {
                    **result,
                    "projectEtag": snapshot.etag,
                    "projectGeneration": snapshot.generation,
                }
                if latest.status is TaskStatus.RUNNING:
                    self.executions.append_attempt(
                        task.project_id,
                        task.task_id,
                        event_id=ids["attempt_succeeded_event_id"],
                        attempt_id=ids["attempt_id"],
                        status=TaskAttemptStatus.SUCCEEDED,
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

        outcome, current_task, snapshot = await asyncio.to_thread(
            commit_if_live,
        )
        if outcome == "CANCELLED":
            await self._quarantine(
                task=current_task,
                ids=ids,
                reason="TASK_CANCELLED_BEFORE_IMPORT",
                result=result,
                run_status=SpecialistRunStatus.CANCELLED,
            )
            raise ConflictError("图片 Task 已取消，迟到结果已隔离")
        if outcome == "STALE":
            await self._quarantine(
                task=current_task,
                ids=ids,
                reason="PROJECT_INPUT_SNAPSHOT_STALE",
                result=result,
                run_status=SpecialistRunStatus.STALE,
            )
            raise ConflictError("图片生成期间 Project 已变化，结果已隔离")
        if outcome != "SUCCEEDED" or snapshot is None:
            raise ConflictError(f"图片 Task 已终止: {outcome}")
        await asyncio.to_thread(self.services.poller.note_commit, snapshot)
        success = (
            current_task.result
            if isinstance(current_task.result, dict)
            else {
                **result,
                "projectEtag": snapshot.etag,
                "projectGeneration": snapshot.generation,
            }
        )
        await self._finish_run(
            task.project_id,
            ids["run_id"],
            SpecialistRunStatus.SUCCEEDED,
            summary=(
                "已生成并选择 "
                + ArtifactVersion.model_validate(
                    success["artifactVersion"],
                ).name
            ),
        )
        return self._result_from_task(current_task, replayed=replayed)

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
        except (KeyError, TypeError, ValueError):
            return False
        existing_file = project.assets.files_by_id.get(indexed.file_id)
        existing_version = project.assets.artifact_versions_by_id.get(
            artifact.version_id,
        )
        slot = project.assets.artifact_slots_by_id.get(artifact.slot_id)
        if (
            existing_file != indexed
            or existing_version != artifact
            or slot is None
            or slot.selected_version_id != artifact.version_id
        ):
            return False
        command = str(result.get("commandType") or "")
        target_ref = str(result.get("targetRef") or "")
        if command == CreatorCommandType.GENERATE_STORYBOARD_IMAGE.value:
            element_id = target_element_id(target_ref, command=command)
            try:
                _, element = find_timeline_element(project, element_id)
            except NotFoundError:
                return False
            selected = selected_element_output(project, element, "storyboard")
            return selected is not None and selected[1] == artifact.version_id
        entity_id = _target_id(target_ref, "asset")
        entity = project.visual.entities.items.get(entity_id)
        if entity is None:
            return False
        variant_id = result.get("variantId")
        selected_version_id = entity.selected_artifact_version_id
        if variant_id:
            variant = entity.variants.items.get(str(variant_id))
            selected_version_id = (
                variant.selected_artifact_version_id
                if variant is not None
                else None
            )
        return selected_version_id == artifact.version_id

    @staticmethod
    def _read_set_still_current(
        project: Project,
        task: TaskRecord,
    ) -> bool:
        """True when the task's render inputs are unchanged in ``project``.

        Whole-project etag drift treats every commit as fatal, but under
        parallel fan-out the most common mid-render commit is a sibling
        media import touching disjoint pointers — quarantining then
        discards a finished, paid render (field run 2026-08-07: the
        first commit of a four-wide storyboard wave staled the other
        three). Publishing stays allowed when every frozen read-set
        version still resolves to the same checksum and the target
        still exists; anything else keeps the fail-closed quarantine.
        """

        metadata = task.metadata or {}
        command = str(metadata.get("commandType") or "")
        target_ref = str(metadata.get("targetRef") or "")
        if not command or not target_ref:
            return False
        for item in task.read_set or []:
            if not isinstance(item, Mapping):
                return False
            version_id = str(item.get("versionId") or "")
            checksum = str(item.get("checksum") or "")
            version = project.assets.source_versions_by_id.get(
                version_id,
            ) or project.assets.artifact_versions_by_id.get(version_id)
            if version is None or version.checksum != checksum:
                return False
        return FileImageExecutionService._target_still_present(
            project,
            command=command,
            target_ref=target_ref,
            metadata=metadata,
        )

    @staticmethod
    def _target_still_present(
        project: Project,
        *,
        command: str,
        target_ref: str,
        metadata: Mapping[str, Any],
    ) -> bool:
        if command == CreatorCommandType.GENERATE_STORYBOARD_IMAGE.value:
            element_id = target_element_id(target_ref, command=command)
            try:
                find_timeline_element(project, element_id)
            except NotFoundError:
                return False
            return True
        if command == CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE.value:
            lineup_id = _target_id(target_ref, "lineup")
            return lineup_id in project.visual.cast_lineups.items
        entity_id = _target_id(target_ref, "asset")
        entity = project.visual.entities.items.get(entity_id)
        if entity is None:
            return False
        raw_snapshot = metadata.get("requestSnapshot")
        variant_id = (
            raw_snapshot.get("variantId")
            if isinstance(raw_snapshot, Mapping)
            else None
        )
        if variant_id:
            return str(variant_id) in entity.variants.items
        return True

    @staticmethod
    def _apply_result(
        candidate: dict[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        indexed = IndexedFile.model_validate(result["indexedFile"])
        artifact = ArtifactVersion.model_validate(result["artifactVersion"])
        assets = candidate["assets"]
        files = assets["files_by_id"]
        versions = assets["artifact_versions_by_id"]
        slots = assets["artifact_slots_by_id"]
        indexed_json = indexed.model_dump(mode="json")
        artifact_json = artifact.model_dump(mode="json")
        if indexed.file_id in files and files[indexed.file_id] != indexed_json:
            raise ConflictError("图片 IndexedFile 稳定 ID 内容冲突")
        if (
            artifact.version_id in versions
            and versions[artifact.version_id] != artifact_json
        ):
            raise ConflictError("图片 ArtifactVersion 稳定 ID 内容冲突")
        files[indexed.file_id] = indexed_json
        versions[artifact.version_id] = artifact_json
        raw_slot = slots.get(artifact.slot_id)
        if raw_slot is None:
            variant_id = result.get("variantId")
            slot = ArtifactSlot(
                slot_id=artifact.slot_id,
                kind=artifact.kind,
                owner_ref=artifact.owner_ref,
                version_ids=[artifact.version_id],
                selected_version_id=artifact.version_id,
                metadata=(
                    {"variantId": str(variant_id)} if variant_id else {}
                ),
            )
            slots[artifact.slot_id] = slot.model_dump(mode="json")
        else:
            if (
                raw_slot["kind"] != artifact.kind
                or raw_slot["owner_ref"] != artifact.owner_ref
            ):
                raise ConflictError("图片 ArtifactSlot 归属冲突")
            if artifact.version_id not in raw_slot["version_ids"]:
                raw_slot["version_ids"].append(artifact.version_id)
            raw_slot["selected_version_id"] = artifact.version_id

        command = CreatorCommandType(str(result["commandType"]))
        target_ref = str(result["targetRef"])
        if command is CreatorCommandType.GENERATE_STORYBOARD_IMAGE:
            element_id = target_element_id(target_ref, command=command.value)
            bind_candidate_output(
                candidate,
                element_id=element_id,
                output_name="storyboard",
                slot_id=artifact.slot_id,
                select_for_render=False,
            )
        elif command is CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE:
            lineup_id = _target_id(target_ref, "lineup")
            lineup = candidate["visual"]["cast_lineups"]["items"].get(
                lineup_id,
            )
            if lineup is None:
                raise ConflictError("阵容图（cast lineup）已不存在")
            if (
                artifact.version_id
                not in lineup["generated_artifact_version_ids"]
            ):
                lineup["generated_artifact_version_ids"].append(
                    artifact.version_id,
                )
            lineup["selected_artifact_version_id"] = artifact.version_id
        else:
            entity_id = _target_id(target_ref, "asset")
            entity = candidate["visual"]["entities"]["items"].get(entity_id)
            if entity is None:
                raise ConflictError("视觉 Asset 已不存在")
            variant_id = result.get("variantId")
            if variant_id:
                variant = entity["variants"]["items"].get(str(variant_id))
                if variant is None:
                    raise ConflictError("视觉 Asset variant 已不存在")
                if (
                    artifact.version_id
                    not in variant["generated_artifact_version_ids"]
                ):
                    variant["generated_artifact_version_ids"].append(
                        artifact.version_id,
                    )
                variant["selected_artifact_version_id"] = artifact.version_id
                if len(entity["variants"]["order"]) == 1:
                    entity[
                        "selected_artifact_version_id"
                    ] = artifact.version_id
            else:
                entity["selected_artifact_version_id"] = artifact.version_id

    async def _quarantine(
        self,
        *,
        task: TaskRecord,
        ids: Mapping[str, str],
        reason: str,
        result: Mapping[str, Any],
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
                    event_id=ids["attempt_quarantined_event_id"],
                    attempt_id=ids["attempt_id"],
                    status=TaskAttemptStatus.QUARANTINED,
                    output=dict(result),
                    output_refs=[str(result.get("outputRef") or "")],
                    error={"code": reason, "message": reason},
                )
            except ExecutionStateConflict:
                latest = await asyncio.to_thread(
                    self.executions.get_task,
                    task.project_id,
                    task.task_id,
                )
        await asyncio.to_thread(
            self.executions.quarantine_task_result,
            task.project_id,
            task.task_id,
            reason=reason,
            result=dict(result),
            quarantine_id=ids["quarantine_id"],
            transition_task=False,
        )
        await self._finish_run(task.project_id, ids["run_id"], run_status)

    async def _rescue_stale_quarantine(
        self,
        *,
        task: TaskRecord,
        slot_key: str,
    ) -> FileImageExecutionResult | None:
        """Import a quarantined-but-paid render whose inputs still hold.

        Under parallel fan-out the whole-project staleness gate used to
        quarantine every sibling of the first committed render; their
        provider outputs were already published and billed. Re-dispatch
        lands on the terminal durable slot, so instead of a
        ConflictError wall the stored result is re-validated against
        the current snapshot and committed — no second render, no
        second bill. Any other quarantine reason keeps the wall.
        """

        error = task.error if isinstance(task.error, Mapping) else {}
        if str(error.get("code") or "") != "PROJECT_INPUT_SNAPSHOT_STALE":
            return None
        result = task.result if isinstance(task.result, dict) else None
        if result is None:
            return None
        try:
            artifact = ArtifactVersion.model_validate(
                result["artifactVersion"],
            )
        except (KeyError, TypeError, ValueError):
            return None
        ids = self._ids(task.project_id, f"{slot_key}:rescue")

        def commit_rescue() -> ProjectSnapshot | None:
            with self.services.projects.lifecycle_lock(task.project_id):
                current = self.services.projects.read(task.project_id)
                if self._result_is_converged(current.project, result):
                    return current
                if not self._read_set_still_current(current.project, task):
                    return None
                candidate = current.project.model_dump(mode="json")
                self._apply_result(candidate, result)
                review_policy = media_review_policy()
                review_boundary = (
                    self.services.commits.runtime_review_boundary(
                        task.project_id,
                        run_id=str(task.run_id),
                        request_id=task.caused_by_request_id,
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
                    caused_by_request_id=task.caused_by_request_id,
                    round_id=ids["round_id"],
                    transaction_id=ids["transaction_id"],
                    advance_accepted_baseline=True,
                    _lifecycle_lock_held=True,
                )
                return commit.snapshot

        snapshot = await asyncio.to_thread(commit_rescue)
        if snapshot is None:
            return None
        await asyncio.to_thread(self.services.poller.note_commit, snapshot)
        logger.info(
            "rescued quarantined image result | task=%s target=%s",
            task.task_id,
            result.get("targetRef"),
        )
        published = {
            **result,
            "projectEtag": snapshot.etag,
            "projectGeneration": snapshot.generation,
        }
        schedule_media_review(
            self.services,
            project_id=task.project_id,
            published_result=published,
        )
        return FileImageExecutionResult(
            task_id=task.task_id,
            run_id=str(task.run_id or ""),
            transaction_id=str(
                result.get("transactionId") or ids["transaction_id"],
            ),
            artifact_version_id=artifact.version_id,
            project_etag=snapshot.etag,
            project_generation=snapshot.generation,
            replayed=True,
        )

    async def _fail_if_running(
        self,
        project_id: str,
        ids: Mapping[str, str],
        code: str,
        *,
        message: str | None = None,
    ) -> None:
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                ids["task_id"],
            )
        except RecordNotFoundError:
            return
        if task.status is TaskStatus.RUNNING:
            try:
                await asyncio.to_thread(
                    self.executions.append_attempt,
                    project_id,
                    task.task_id,
                    event_id=ids["attempt_failed_event_id"],
                    attempt_id=ids["attempt_id"],
                    status=TaskAttemptStatus.FAILED,
                    error={"code": code, "message": message or code},
                )
            except ExecutionStateConflict:
                pass
        await self._finish_run(
            project_id,
            ids["run_id"],
            SpecialistRunStatus.FAILED,
        )

    async def _finish_run(
        self,
        project_id: str,
        run_id: str,
        status: SpecialistRunStatus,
        *,
        summary: str | None = None,
    ) -> None:
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
        updates = {"final_summary_text": summary} if summary else None
        try:
            await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run_id,
                expected_status=run.status,
                status=status,
                updates=updates,
            )
        except ExecutionStateConflict:
            return

    def _result_from_task(
        self,
        task: TaskRecord,
        *,
        replayed: bool,
    ) -> FileImageExecutionResult:
        result = task.result if isinstance(task.result, dict) else {}
        try:
            artifact = ArtifactVersion.model_validate(
                result["artifactVersion"],
            )
            transaction_id = str(result["transactionId"])
            project_etag = str(result["projectEtag"])
            project_generation = int(result["projectGeneration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageIntegrityError("SUCCEEDED 图片 Task 缺少可重放结果") from exc
        # Run-review hook: every successful convergence (fresh generation,
        # idempotent replay, crash recovery) flows through this single
        # point. Scheduling is advisory and idempotent: the switch, the
        # command filter and the already-reviewed dedup live on the review
        # side.
        schedule_media_review(
            self.services,
            project_id=task.project_id,
            published_result=result,
        )
        return FileImageExecutionResult(
            task_id=task.task_id,
            run_id=str(task.run_id or ""),
            transaction_id=transaction_id,
            artifact_version_id=artifact.version_id,
            project_etag=project_etag,
            project_generation=project_generation,
            replayed=replayed,
        )


_image_registry_lock = threading.RLock()
_image_registry: dict[Path, FileImageExecutionService] = {}


def file_image_execution_service(
    services: CreatorFileServices,
    *,
    provider: ImageProvider | None = None,
) -> FileImageExecutionService:
    """One image worker per data root, so its supervisor jobs are shared.

    Background polling of accepted (billed) provider tasks lives on the
    instance, so tool calls, HTTP routes and startup recovery must all reach
    the same object; a caller passing its own provider (tests) gets an
    unregistered instance instead.
    """

    if provider is not None:
        return FileImageExecutionService(services, provider=provider)
    root = services.root.resolve()
    with _image_registry_lock:
        worker = _image_registry.get(root)
        if worker is None:
            worker = FileImageExecutionService(services)
            _image_registry[root] = worker
        return worker


async def shutdown_file_image_execution_services() -> None:
    """Cancel supervisors; the durable ledger keeps tasks resumable."""

    with _image_registry_lock:
        workers = list(_image_registry.values())
        _image_registry.clear()
    if workers:
        await asyncio.gather(
            *(worker.shutdown() for worker in workers),
            return_exceptions=True,
        )


async def execute_file_image_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: CreatorCommandType | str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
    expected_object_versions: Sequence[str] = (),
    provider: ImageProvider | None = None,
) -> FileImageExecutionResult:
    """Small route/tool entry point with an injectable provider for tests."""

    # Wallet fuse: every dispatch path (specialist delegation, work-graph
    # scheduler, manual retry) funnels through here.
    ensure_media_call_budget(services, project_id)
    worker = file_image_execution_service(services, provider=provider)
    return await worker.execute(
        project_id=project_id,
        command=command,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
        expected_object_versions=expected_object_versions,
    )


__all__ = [
    "ExistingImageProvider",
    "FileImageExecutionResult",
    "FileImageExecutionService",
    "ImageProvider",
    "execute_file_image_command",
    "file_image_execution_service",
    "shutdown_file_image_execution_services",
]
