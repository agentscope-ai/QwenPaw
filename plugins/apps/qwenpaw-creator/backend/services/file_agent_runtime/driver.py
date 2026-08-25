# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=cell-var-from-loop,protected-access,too-many-branches
# pylint: disable=too-many-statements,unused-argument
"""SQLite-free Creator Agent loop over Project and Runtime files."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import mimetypes
from pathlib import Path, PurePosixPath
import secrets
import threading
import time
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import NAMESPACE_URL, uuid4, uuid5

from domain.refs import workspace_asset_ref
from domain.enums import (
    CreatorGoalStatus,
    CreatorSessionStatus,
    SpecialistRole,
    SpecialistRunStatus,
    TaskStatus,
)
from domain.errors import (
    ConflictError,
    CreatorError,
    ReviewPendingError,
    ValidationError,
)
from models.config import (
    CREATION_CHECKPOINT_REQUIRED,
    EXECUTION_AUTHORIZATION_ALLOW_ALL,
    MEDIA_REVIEW_AUTO_APPROVE,
    get_creation_checkpoint_mode,
    get_execution_authorization_mode,
    get_mainline_max_model_turns,
    get_media_review_mode,
    get_specialist_max_model_turns,
    scale_mainline_max_model_turns,
    get_text_model_name,
    get_vlm_model_name,
    get_web_grounding_enabled,
    get_web_grounding_image_download_timeout_seconds,
    get_web_grounding_max_sources,
    get_web_grounding_timeout_seconds,
    get_web_grounding_verification_timeout_seconds,
    get_web_grounding_visual_search_timeout_seconds,
    get_image_model_name,
    get_video_backend,
    get_video_model_name,
)
from models.media_transport import (
    read_reference_media,
    validate_reference_image_bytes,
)
from services.object_grounding import ground_image_objects
from services.object_grounding import object_grounding_image_suffix
from services.object_grounding import render_object_grounding_annotation
from services.project_files.agent_tools import (
    AgentProjectToolError,
    AgentProjectToolContext,
    AgentProjectTools,
    JQ_PROJECT_TOOL_NAME,
    PATCH_PROJECT_TOOL_NAME,
    READ_PROJECT_TOOL_NAME,
    agent_project_tool_manifest,
)
from services.project_files.jq_transform import JqTransformError
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.assets import AssetAlreadyExists, AssetFileStore
from services.project_files.models import (
    IndexedFile,
    Project,
    SourceAssetVersion,
)
from services.project_files.remote_cache import public_source_url
from services.runtime_files.models import (
    ChangeOrigin,
    CreatorMessageRecord,
    MessageChannel,
    ReviewPolicy,
)
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    SpecialistRunRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStoreError,
    ProjectExecutionStore,
)
from services.runtime_files.errors import (
    LockTimeoutError,
    RecordNotFoundError,
)
from services.runtime_files.atomic_store import atomic_replace_bytes
from services.media_files.call_budget import (
    MediaCallBudgetExhausted,
    ensure_media_call_budget,
)
from services.external_skills import (
    EXTERNAL_SKILL_TOOL_NAMES,
    VIEW_SKILL_TOOL_NAME,
    LoadedSkill,
    external_skill_tool_manifests,
    load_skills as load_external_skills,
    render_external_skills_context,
    view_skill as view_external_skill,
)
from services.observability import report_error, trace_event, traced_async
from services.source_analysis import SourceAgentToolContext
from services.specialist_tools import (
    FileSpecialistToolRegistry,
    SpecialistToolSpec,
    SpecialistToolWait,
)
from services.runtime_files.session_store import (
    ProjectRuntimeSessionStore,
    RuntimeGoalNotFound,
    SessionStateConflict,
)
from services.web_grounding import ground_prompt_context
from utils.logger import setup_logger
from utils.paths import media_path_from_url
from utils.paths import media_task_scope
from utils.paths import media_url_for
from utils.paths import unique_task_work_path

from .checkpoints import (
    CHECKPOINT_PROVIDER,
    checkpoint_authorization_id,
    checkpoint_execution_request_id,
    checkpoint_label,
    checkpoint_operation,
    checkpoint_recovery,
    checkpoint_summary,
    required_checkpoint_phases,
)
from .model_client import (
    AgentChatClient,
    AgentModelConfigurationError,
    AgentModelError,
    AgentStreamCallbackError,
    AgentStreamCallbackPassthrough,
    AgentModelTurn,
    RateLimitExhaustedError,
    RateLimitRetryNotice,
    AgentScopeAgentChatClient,
    AgentScopeVlmChatClient,
    AgentToolCall,
)
from .models import (
    AgentRunStatus,
    CreatorAgentRunRecord,
    TERMINAL_AGENT_RUN_STATUSES,
)
from .native_media import (
    document_page_content_parts,
    video_frame_content_parts,
    source_intelligence_content_parts,
)
from .prompts import render_creator_system_prompt
from .run_store import AgentRunStateConflict, CreatorAgentRunStore
from .work_graph import derive_work_graph
from .work_scheduler import WorkGraphScheduler
from .subagents import (
    DELEGATE_TOOL_NAME,
    DelegateToAgentInput,
    delegate_tool_manifest,
    specialist_system_prompt,
)

logger = setup_logger("creator.agent_runtime")


def _log_safe(value: object) -> str:
    """Neutralize CR/LF in user-provided values before logging."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


# Arguments the provider prices on: they must still match the approved scope
# at invocation time, or the user would pay for terms they never saw.
_BILLING_SENSITIVE_ARGUMENTS = ("durationSeconds", "resolution", "mode")

GROUND_PROMPT_CONTEXT_TOOL_NAME = "ground_prompt_context"
OBJECT_GROUNDING_TOOL_NAME = "ground_image_objects"
GROUNDING_VISUAL_MAX_BYTES = 16 * 1024 * 1024
MAX_MALFORMED_JQ_PROJECT_RETRIES = 2
MAX_REPEATED_DETERMINISTIC_TOOL_FAILURES = 2
DEFAULT_MODEL_TURN_TIMEOUT_SECONDS = 300.0

# Tool results that may carry video-frame refs to inject as native
# images: the synchronous reader and the background-task harvester.
_VIDEO_FRAME_TOOL_NAMES = frozenset(
    {"read_source_video", "check_observation_tasks"},
)


def _nested_tool_payload(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Model-owned specialist tool flags (background/wait) live in the
    nested ``arguments.arguments`` payload, not on the envelope."""
    payload = arguments.get("arguments")
    return payload if isinstance(payload, Mapping) else {}


# The workspace schema prompt instructs the model to keep each jq_project
# argument JSON under 4KB; the advisory fires at 2x that guidance so the
# diagnosis surfaces payloads that ignored the instruction.
JQ_PROJECT_ARGUMENT_SIZE_GUIDANCE_BYTES = 4 * 1024
JQ_PROJECT_LARGE_ARGUMENT_ADVISORY_BYTES = (
    2 * JQ_PROJECT_ARGUMENT_SIZE_GUIDANCE_BYTES
)
TOOL_ARGUMENT_PROGRESS_BYTES = 1024
MAX_PERSISTED_RAW_TOOL_ARGUMENT_BYTES = 256 * 1024

_PROJECT_SNAPSHOT_RESULT_KIND = "project_snapshot"
_PROJECT_CHANGE_RECEIPT_RESULT_KIND = "project_change_receipt"
_PROJECT_SNAPSHOT_TOOL_NAMES = frozenset(
    {READ_PROJECT_TOOL_NAME, JQ_PROJECT_TOOL_NAME, PATCH_PROJECT_TOOL_NAME},
)


@dataclass
class _ToolArgumentProgressState:
    tool: str
    received_bytes: int = 0
    provider_chunk_count: int = 0
    last_reported_bytes: int = 0


class _ToolArgumentProgressReporter:
    """Collapse provider fragments into bounded, content-free progress events."""

    def __init__(self, emit: Any) -> None:
        self._emit = emit
        self._states: dict[str, _ToolArgumentProgressState] = {}

    async def feed(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments_delta: str,
    ) -> None:
        if not arguments_delta:
            return
        state = self._states.setdefault(
            tool_call_id,
            _ToolArgumentProgressState(tool=tool_name),
        )
        state.tool = tool_name or state.tool
        state.received_bytes += len(arguments_delta.encode("utf-8"))
        state.provider_chunk_count += 1
        if (
            state.last_reported_bytes == 0
            or state.received_bytes - state.last_reported_bytes
            >= TOOL_ARGUMENT_PROGRESS_BYTES
        ):
            await self._emit(tool_call_id, state, False)
            state.last_reported_bytes = state.received_bytes

    async def finish(self, calls: tuple[AgentToolCall, ...]) -> None:
        for call in calls:
            state = self._states.setdefault(
                call.call_id,
                _ToolArgumentProgressState(tool=call.name),
            )
            state.tool = call.name
            state.received_bytes = max(
                state.received_bytes,
                call.raw_arguments_bytes,
            )
            state.provider_chunk_count = max(
                state.provider_chunk_count,
                call.provider_chunk_count,
            )
            await self._emit(call.call_id, state, True)
            state.last_reported_bytes = state.received_bytes


def _tool_call_transport_metadata(call: AgentToolCall) -> dict[str, Any]:
    """Return one bounded forensic record for a completed provider payload."""

    raw = call.raw_arguments
    raw_bytes = raw.encode("utf-8")
    payload: dict[str, Any] = {
        "rawArgumentsBytes": call.raw_arguments_bytes or len(raw_bytes),
        "providerChunkCount": call.provider_chunk_count,
        "argumentsRepaired": call.arguments_repaired,
        "strictJsonError": call.strict_json_error,
        "rawArgumentsCaptured": bool(raw),
    }
    if raw:
        payload["rawArgumentsSha256"] = hashlib.sha256(raw_bytes).hexdigest()
        if len(raw_bytes) <= MAX_PERSISTED_RAW_TOOL_ARGUMENT_BYTES:
            payload["rawArguments"] = raw
        else:
            # Preserve useful forensic boundaries without allowing one model
            # response to make an unbounded Runtime record.
            boundary = MAX_PERSISTED_RAW_TOOL_ARGUMENT_BYTES // 2
            payload.update(
                {
                    "rawArgumentsCaptured": False,
                    "rawArgumentsTruncated": True,
                    "rawArgumentsPrefix": raw_bytes[:boundary].decode(
                        "utf-8",
                        errors="replace",
                    ),
                    "rawArgumentsSuffix": raw_bytes[-boundary:].decode(
                        "utf-8",
                        errors="replace",
                    ),
                },
            )
    return payload


def _specialist_waiting_review_summary(
    role: SpecialistRole,
    target_refs: list[str],
) -> str:
    # The Runtime does not auto-resume a paused specialist: after approval
    # the mainline must re-delegate the same target. The summary must not
    # promise an automation that does not exist, or the mainline skips the
    # re-delegation and falsely reports the video as in progress.
    target = "、".join(target_refs) or "当前目标"
    if role is SpecialistRole.R2V_GENERATION_DIRECTOR:
        return (
            f"{target} 的分镜图已生成，视频尚未开始。请先审阅分镜图；"
            "审阅通过后，主线需对该 Element 重新委派 R2V 生成 Director 以继续生成视频；"
            "这不算重新生成已通过产物。"
        )
    return f"{target} 的产物已生成，后续步骤尚未开始。请先完成审阅；" "审阅通过后，主线需重新委派同一目标以继续后续步骤。"


def _timelines_have_plan(project: Any, target_refs: list[str]) -> bool:
    """True when every delegated Timeline already carries an edit_plan.

    Used by the co-creation direction gate: a Timeline with a written
    contract has already passed (or explicitly skipped) direction picking.
    """
    timelines = project.timelines.items
    for target_ref in target_refs:
        if not str(target_ref).startswith("timeline:"):
            continue
        stripped = str(target_ref).partition(":")[2]
        timeline = timelines.get(stripped) or timelines.get(str(target_ref))
        if timeline is None:
            continue
        plan = getattr(timeline, "edit_plan", None)
        if plan is None or not plan.concept.strip():
            return False
    return True


def _agent_waiting_review_summary(
    specialist_summary: str | None,
) -> str:
    summary = (specialist_summary or "").strip()
    if not summary:
        summary = "当前产物已生成，后续步骤尚未开始。请先完成审阅；审阅通过后主线需重新委派同一目标以继续。"
    return f"{summary}\n\n无需另行发送消息。"


def _deterministic_tool_failure_fingerprint(
    call: AgentToolCall,
    error: Exception,
) -> str | None:
    """Identify an exact, non-retryable tool failure across model turns."""

    supported = isinstance(
        error,
        (
            CreatorError,
            AgentProjectToolError,
            JqTransformError,
            ValueError,
            KeyError,
        ),
    )
    if not supported or bool(getattr(error, "retryable", False)):
        return None
    payload = json.dumps(
        {
            "tool": call.name,
            "arguments": call.arguments,
            "errorType": type(error).__name__,
            "errorCode": getattr(error, "code", None),
            "error": str(error),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tool_failure_result(
    name: str,
    error: Exception,
    *,
    recovery: str | None = None,
) -> dict[str, Any]:
    """Expose stable error fields without flattening useful diagnostics."""

    error_payload: dict[str, Any] = {
        "type": type(error).__name__,
        "message": str(error),
        "recovery": recovery
        or _specialist_tool_recovery(
            name,
            str(error),
            code=getattr(error, "code", None),
        ),
    }
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        error_payload["code"] = code
        error_payload["retryable"] = bool(
            getattr(error, "retryable", False),
        )
    details = getattr(error, "details", None)
    if isinstance(details, Mapping) and details:
        error_payload["details"] = dict(details)
    return {"ok": False, "error": error_payload}


def _unfinished_video_element_ids(project: Any) -> list[str]:
    """Timeline r2v elements that do not have an accepted main video yet.

    This is the YOLO completion criterion (and the seed of the future DAG
    node state): an element whose creative facts exist but whose
    ``element:{id}:main`` video slot has no selected version is unfinished.
    """

    finished_owners = {
        slot.owner_ref
        for slot in project.assets.artifact_slots_by_id.values()
        if slot.kind == "element_video" and slot.selected_version_id
    }
    unfinished: list[str] = []
    for timeline in project.timelines.items.values():
        for element_id, element in timeline.elements_by_id.items():
            creation = getattr(element, "creation", None)
            if getattr(creation, "type", None) != "r2v":
                continue
            if f"element:{element_id}" not in finished_owners:
                unfinished.append(element_id)
    return sorted(unfinished)


def _grounding_stable_id(prefix: str, project_id: str, identity: str) -> str:
    value = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:grounding:{prefix}:{project_id}:{identity}",
    ).hex
    return f"{prefix}-{value}"


def _grounding_media_kind(media_type: str) -> str:
    main_type = media_type.split("/", 1)[0].casefold()
    if main_type in {"image", "video", "audio", "text"}:
        return main_type
    if media_type.casefold() in {"application/pdf"}:
        return "document"
    return "other"


def _grounding_extension(path: Path, media_type: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return suffix
    guessed = mimetypes.guess_extension(media_type)
    return (
        guessed
        if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        else ".img"
    )


def _grounding_local_path(source: Mapping[str, Any]) -> Path | None:
    raw_path = str(source.get("local_path") or "").strip()
    if raw_path:
        return Path(raw_path)
    raw_url = str(source.get("local_url") or "").strip()
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _grounding_visual_is_usable(source: Mapping[str, Any]) -> bool:
    verification = source.get("verification")
    return (
        isinstance(verification, Mapping)
        and str(verification.get("status") or "").casefold() == "accepted"
    )


def _object_grounding_version_ref(value: str) -> tuple[str, str] | None:
    ref = str(value or "").strip()
    for prefix, kind in (
        ("asset-version:", "asset"),
        ("artifact-version:", "artifact"),
    ):
        if ref.startswith(prefix):
            version_id = ref.removeprefix(prefix).strip()
            return (kind, version_id) if version_id else None
    parsed = urlparse(ref)
    if parsed.scheme not in {"asset", "artifact"} or not parsed.netloc:
        return None
    identity = unquote(parsed.netloc)
    if "@" not in identity:
        return None
    version_id = identity.rsplit("@", 1)[-1].strip()
    return (parsed.scheme, version_id) if version_id else None


def _ground_prompt_context_tool_manifest() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": GROUND_PROMPT_CONTEXT_TOOL_NAME,
            "description": (
                "对用户目标中的真实人物、品牌、地点、赛事、IP、视觉风格或文化/服饰/材质引用"
                "执行 web grounding；返回 source-backed text context 和下载后的视觉参考。"
                "这是只读工具，不修改 Project。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "minLength": 1},
                    "prompt": {"type": "string"},
                    "queries": {
                        "type": "array",
                        "description": (
                            "可选的简短检索建议，按实际检索目标生成最少必要数量，最多 6 条；6 是上限而非配额。"
                            "每个独立人物、节目/舞台或风格目标至多一条，不得为了凑数制造 query。"
                            "真实人物身份检索只使用规范姓名和稳定身份词，"
                            "例如 'Erling Haaland official profile portrait'；除非用户明确要求特定时期，"
                            "或所查事实本身具有时效性，否则不得添加年份或 current/latest，也不得添加 "
                            "personality、fashion、style、look 等宽泛修饰词。"
                            "舞台、节目和视觉风格必须作为单独的 context query。"
                        ),
                        "items": {"type": "string"},
                    },
                    "includeVisuals": {"type": "boolean"},
                    "context": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "force": {"type": "boolean"},
                    "detectOnly": {"type": "boolean"},
                    "detector": {
                        "type": "string",
                        "enum": ["hybrid", "llm", "heuristic"],
                    },
                },
                "required": ["projectId"],
                "additionalProperties": False,
            },
        },
    }


def _object_grounding_tool_manifest() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": OBJECT_GROUNDING_TOOL_NAME,
            "description": (
                "使用 Creator VLM 检测并定位一张图片中的指定对象。返回每个对象的 "
                "0-1000 归一化 bbox 和原图像素 bbox；需要可视化时可生成带框标注图。"
                "imageRef 接受本轮附件中的 asset-version/artifact-version ref、"
                "asset:// 或 artifact:// workspace ref、安全公网图片 URL，或当前 "
                "Project 的 /generated URL。不要传本机文件路径。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "minLength": 1},
                    "imageRef": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "要检测的 exact AssetVersion/ArtifactVersion workspace "
                            "ref、安全公网图片 URL，或当前 Project 的 /generated URL。"
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                        "description": (
                            "要检测的对象，例如 all cats、the red car、画面中的所有人。"
                        ),
                    },
                    "returnImage": {
                        "type": "boolean",
                        "description": "是否生成带检测框的临时标注图。",
                    },
                },
                "required": ["projectId", "imageRef", "prompt"],
                "additionalProperties": False,
            },
        },
    }


def _creator_agent_tool_manifest(
    external_skills: list[LoadedSkill] | None = None,
) -> list[dict[str, Any]]:
    manifest = [*agent_project_tool_manifest()]
    if get_web_grounding_enabled():
        manifest.append(_ground_prompt_context_tool_manifest())
    manifest.append(_object_grounding_tool_manifest())
    if external_skills:
        manifest.extend(external_skill_tool_manifests(external_skills))
    manifest.append(delegate_tool_manifest())
    return manifest


_TERMINAL_GOAL_STATUSES = frozenset(
    {
        CreatorGoalStatus.COMPLETED,
        CreatorGoalStatus.CANCELLED,
        CreatorGoalStatus.FAILED,
    },
)


class FileAgentRuntimeError(RuntimeError):
    pass


class CreationCheckpointBlocked(FileAgentRuntimeError):
    """A pit stop the user has not cleared blocks costly generation."""

    def __init__(
        self,
        phase: str,
        status: ExecutionAuthorizationStatus,
    ) -> None:
        self.phase = phase
        self.status = status
        verdict = (
            "被用户否决"
            if status is ExecutionAuthorizationStatus.REJECTED
            else f"未通过（{status.value}）"
        )
        super().__init__(
            f"创作检查点「{checkpoint_label(phase)}」{verdict}；未执行任何生成。",
        )

    def recovery(self) -> str:
        return checkpoint_recovery(self.phase)


@dataclass(frozen=True, slots=True)
class _JqProjectArgumentDiagnosis:
    missing_top_level: tuple[str, ...]
    invalid_top_level: tuple[str, ...]
    unexpected_top_level: tuple[str, ...]
    nested_required_paths: tuple[str, ...]
    nested_scan_truncated: bool
    raw_arguments_bytes: int
    program_bytes: int
    json_args_bytes: int
    large_payload_advisory: bool
    strict_json_parsed: bool
    json_repair_applied: bool
    strict_json_error: str | None
    fingerprint: str

    @property
    def schema_valid(self) -> bool:
        return not (
            self.missing_top_level
            or self.invalid_top_level
            or self.unexpected_top_level
        )

    @property
    def safe_to_execute(self) -> bool:
        """Whether jq may run on these arguments.

        jq_project mutates the Project, so a payload that only became a
        JSON object through ``json_repair`` (typically a truncated stream
        closed by the repairer) is never executed: the top-level shape may
        look complete while string/JSON argument values silently lost their
        tails. Read-only tools keep accepting repaired payloads.
        """

        return self.schema_valid and not self.json_repair_applied

    def event_payload(self) -> dict[str, Any]:
        return {
            "rawArgumentsBytes": self.raw_arguments_bytes,
            "programBytes": self.program_bytes,
            "jsonArgsBytes": self.json_args_bytes,
            "largePayloadAdvisory": self.large_payload_advisory,
            "strictJsonParsed": self.strict_json_parsed,
            "jsonRepairApplied": self.json_repair_applied,
            "strictJsonError": self.strict_json_error,
            "schemaValid": self.schema_valid,
            "safeToExecute": self.safe_to_execute,
            "missingTopLevel": list(self.missing_top_level),
            "invalidTopLevel": list(self.invalid_top_level),
            "unexpectedTopLevel": list(self.unexpected_top_level),
            "nestedRequiredPaths": list(self.nested_required_paths),
            "nestedScanTruncated": self.nested_scan_truncated,
            "fingerprint": self.fingerprint,
        }


# Shared call-shape guidance for jq_project argument failures. Composed by
# both ``MalformedJqProjectArguments.tool_result`` and
# ``_specialist_tool_recovery`` so the two recovery texts cannot drift when
# the tool surface changes.
_JQ_PROJECT_CALL_SHAPE_RECOVERY = (
    "Issue a new jq_project call with projectId and program at the top "
    "level; the Runtime selects the base snapshot itself. Keep program "
    "small and put structured values in jsonArgs. Split bulk work into "
    "separate commits for strategy/settings, visual entities, and "
    "timeline elements, re-reading project.json between commits."
)


class MalformedJqProjectArguments(FileAgentRuntimeError):
    """A jq_project call whose decoded object is unsafe to execute."""

    def __init__(
        self,
        diagnosis: _JqProjectArgumentDiagnosis,
        *,
        attempt: int,
        repeated_payload: bool,
    ) -> None:
        self.diagnosis = diagnosis
        self.attempt = attempt
        self.repeated_payload = repeated_payload
        self.retries_remaining = max(
            0,
            MAX_MALFORMED_JQ_PROJECT_RETRIES - attempt + 1,
        )
        details: list[str] = []
        if diagnosis.missing_top_level:
            details.append(
                "missing top-level " + ", ".join(diagnosis.missing_top_level),
            )
        if diagnosis.invalid_top_level:
            details.append(
                "invalid top-level " + ", ".join(diagnosis.invalid_top_level),
            )
        if diagnosis.unexpected_top_level:
            details.append(
                "unexpected top-level "
                + ", ".join(diagnosis.unexpected_top_level),
            )
        if diagnosis.json_repair_applied:
            details.append(
                "arguments only parsed after json_repair"
                + (
                    f" ({diagnosis.strict_json_error})"
                    if diagnosis.strict_json_error
                    else ""
                ),
            )
        message = "jq_project arguments are structurally corrupted; jq was not executed"
        if details:
            message += ": " + "; ".join(details)
        super().__init__(message)

    def tool_result(self) -> dict[str, Any]:
        recovery = (
            "Do not reuse or auto-hoist any nested field from this "
            "corrupted payload. Call read_project to refresh your "
            "snapshot. " + _JQ_PROJECT_CALL_SHAPE_RECOVERY
        )
        if self.diagnosis.json_repair_applied:
            strict_error = self.diagnosis.strict_json_error or ""
            if "Extra data" in strict_error:
                # The model emitted a complete object and kept writing:
                # it closed jsonArgs and the root brace too early, then
                # streamed the remaining entries as orphan text. "Send
                # smaller batches" alone does not break this loop — name
                # the exact mistake and force one entry per call.
                syntax_hint = (
                    "Your previous arguments closed the top-level JSON "
                    f"object too early ({strict_error}) and kept "
                    "emitting content after the closing brace. "
                )
            else:
                syntax_hint = (
                    "Your previous arguments only became a JSON object "
                    "after automatic repair"
                    + (f" ({strict_error})" if strict_error else "")
                    + "; the stream was likely cut off before the "
                    "payload was complete. "
                )
            recovery = (
                syntax_hint + "Your arguments were "
                f"{self.diagnosis.raw_arguments_bytes} bytes; keep each "
                "call's JSON under "
                f"{JQ_PROJECT_ARGUMENT_SIZE_GUIDANCE_BYTES} bytes and "
                "write one timeline element or settings change per "
                "jq_project call. " + recovery
            )
        if self.repeated_payload:
            recovery = (
                "The same malformed payload was repeated. Do not resend it. "
                + recovery
            )
        return {
            "ok": False,
            "error": {
                "type": type(self).__name__,
                "code": "JQ_ARGUMENTS_MALFORMED",
                "message": str(self),
                "retryable": self.retries_remaining > 0,
                "details": self.diagnosis.event_payload(),
                "retry": {
                    "attempt": self.attempt,
                    "retriesRemaining": self.retries_remaining,
                    "samePayload": self.repeated_payload,
                },
                "recovery": recovery,
            },
        }


def _nested_required_key_paths(
    value: Any,
    required_keys: set[str],
) -> tuple[tuple[str, ...], bool]:
    """Find misplaced required jq keys without trusting or moving them.

    Also reports whether the scan was cut short by the node/depth/result
    budget, so an exhausted traversal is surfaced as partial instead of
    silently looking like a complete diagnosis.
    """

    found: list[str] = []
    remaining_nodes = 4_096
    truncated = False

    def visit(current: Any, path: str, depth: int) -> None:
        nonlocal remaining_nodes, truncated
        if remaining_nodes <= 0 or depth > 16 or len(found) >= 12:
            if isinstance(current, (Mapping, list)) and current:
                truncated = True
            return
        remaining_nodes -= 1
        if isinstance(current, Mapping):
            for key, child in current.items():
                child_path = f"{path}.{key}"
                if depth > 0 and key in required_keys:
                    found.append(child_path)
                    if len(found) >= 12:
                        truncated = True
                        return
                visit(child, child_path, depth + 1)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                visit(child, f"{path}[{index}]", depth + 1)

    visit(value, "$", 0)
    return tuple(found), truncated


def _jq_project_argument_diagnosis(
    call: AgentToolCall,
) -> _JqProjectArgumentDiagnosis:
    arguments = call.arguments
    required = {"projectId", "program"}
    # ``baseEtag`` is deprecated on the model surface but still tolerated so
    # an older prompt/history echo is never misdiagnosed as corruption.
    allowed = required | {"baseEtag", "stringArgs", "jsonArgs"}
    missing = tuple(sorted(required - arguments.keys()))
    invalid: list[str] = []
    for key in sorted(required & arguments.keys()):
        if not isinstance(arguments[key], str) or not arguments[key].strip():
            invalid.append(key)
    for key in ("stringArgs", "jsonArgs"):
        if key in arguments and not isinstance(arguments[key], Mapping):
            invalid.append(key)
    if isinstance(arguments.get("stringArgs"), Mapping) and any(
        not isinstance(value, str)
        for value in arguments["stringArgs"].values()
    ):
        invalid.append("stringArgs")
    unexpected = tuple(sorted(set(arguments) - allowed))
    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    program = arguments.get("program")
    program_bytes = (
        len(program.encode("utf-8")) if isinstance(program, str) else 0
    )
    json_args = arguments.get("jsonArgs")
    json_args_bytes = (
        len(
            json.dumps(
                json_args,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        if isinstance(json_args, Mapping)
        else 0
    )
    raw_arguments_bytes = call.raw_arguments_bytes or len(encoded)
    fingerprint = hashlib.sha256(encoded).hexdigest()[:16]
    nested_paths, nested_truncated = _nested_required_key_paths(
        arguments,
        set(missing),
    )
    return _JqProjectArgumentDiagnosis(
        missing_top_level=missing,
        invalid_top_level=tuple(sorted(set(invalid))),
        unexpected_top_level=unexpected,
        nested_required_paths=nested_paths,
        nested_scan_truncated=nested_truncated,
        raw_arguments_bytes=raw_arguments_bytes,
        program_bytes=program_bytes,
        json_args_bytes=json_args_bytes,
        large_payload_advisory=(
            raw_arguments_bytes >= JQ_PROJECT_LARGE_ARGUMENT_ADVISORY_BYTES
        ),
        strict_json_parsed=not call.arguments_repaired,
        json_repair_applied=call.arguments_repaired,
        strict_json_error=call.strict_json_error,
        fingerprint=fingerprint,
    )


class ToolArgumentsJSONError(FileAgentRuntimeError):
    """The model streamed tool arguments that never became a JSON object.

    Raised per tool call and fed back to the model as a failed tool result;
    it must never terminate the whole run.
    """


class RepeatedDeterministicToolFailure(AgentModelError):
    """The model repeated an identical non-retryable tool failure."""


class StaleAgentRun(FileAgentRuntimeError, AgentStreamCallbackPassthrough):
    """Raised when a revoked run reaches a model/tool/commit fence."""


@dataclass(slots=True)
class _ProjectTask:
    project_id: str
    run_id: str
    message_seq: int
    epoch: int
    task: asyncio.Task[None]
    superseded: bool = False
    interrupting: bool = False


@dataclass(frozen=True, slots=True)
class _LoopResult:
    summary: str
    tool_call_count: int
    review_ids: tuple[str, ...]


class _FencedCommitBoundary:
    """Hold the run fence throughout publication.

    Interrupt revocation uses the same process lock.  If publication already
    began, interrupt waits for that local atomic commit to finish; once the
    interrupt returns, the old run cannot begin another commit.
    """

    def __init__(
        self,
        driver: FileCreatorAgentRuntime,
        project_id: str,
        run_id: str,
        epoch: int,
        delegate: ProjectCommitBoundary,
    ) -> None:
        self.driver = driver
        self.project_id = project_id
        self.run_id = run_id
        self.epoch = epoch
        self.delegate = delegate

    def commit(self, **kwargs: Any):
        with self.driver._publication_lock:
            self.driver._assert_epoch(self.project_id, self.run_id, self.epoch)
            return self.delegate.commit(**kwargs)


class FileCreatorAgentRuntime:
    """One process coordinator consuming durable user messages per Project."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        model_client: AgentChatClient | None = None,
        source_model_client: AgentChatClient | None = None,
        poll_interval_seconds: float = 1.0,
        max_model_turns: int | None = None,
        specialist_max_model_turns: int | None = None,
        model_turn_timeout_seconds: float = DEFAULT_MODEL_TURN_TIMEOUT_SECONDS,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if max_model_turns is None:
            max_model_turns = get_mainline_max_model_turns()
        if specialist_max_model_turns is None:
            specialist_max_model_turns = get_specialist_max_model_turns()
        if max_model_turns <= 0:
            raise ValueError("max_model_turns must be positive")
        if specialist_max_model_turns <= 0:
            raise ValueError("specialist_max_model_turns must be positive")
        if model_turn_timeout_seconds <= 0:
            raise ValueError("model_turn_timeout_seconds must be positive")
        self.services = services
        self.sessions = ProjectRuntimeSessionStore(services.root)
        self.runs = CreatorAgentRunStore(services.root)
        self.executions = ProjectExecutionStore(services.root)
        self.specialist_tools = FileSpecialistToolRegistry(services)
        injected_model_client = model_client is not None
        self.model_client = model_client or AgentScopeAgentChatClient()
        self.source_model_client = source_model_client or (
            self.model_client
            if injected_model_client
            else AgentScopeVlmChatClient()
        )
        self.poll_interval_seconds = poll_interval_seconds
        self.max_model_turns = max_model_turns
        self.specialist_max_model_turns = specialist_max_model_turns
        self.model_turn_timeout_seconds = model_turn_timeout_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._active: dict[str, _ProjectTask] = {}
        self._interrupt_cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._blocked_heads: dict[str, int] = {}
        # Durable-interrupt stall tracking: project -> (run_id, first seen
        # monotonic time).  A RUNNING run with no local handle normally
        # belongs to another live process, but when that owner died before
        # persisting a terminal status the Session would otherwise stay
        # INTERRUPT_REQUESTED forever (see _record_idle_interrupt).
        self._interrupt_stalls: dict[str, tuple[str, float]] = {}
        self._epochs: dict[str, int] = {}
        self._publication_lock = threading.RLock()
        # Event-driven media fan-out: the model plans, the Runtime executes
        # READY work-graph nodes in parallel (unattended ladder only).
        self.work_scheduler = WorkGraphScheduler(services)
        # Media workers commit from thread-pool threads; route their
        # post-commit signal onto the loop so a finished r2v/compose task
        # re-evaluates the work graph without waiting for a model turn.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._commit_wake_listener: Callable[[str], None] | None = None
        if loop is not None:

            def _wake_from_commit(project_id: str, _loop=loop) -> None:
                _loop.call_soon_threadsafe(
                    self.work_scheduler.wake,
                    project_id,
                )

            services.poller.add_commit_listener(_wake_from_commit)
            self._commit_wake_listener = _wake_from_commit

    async def _complete_model_turn(
        self,
        client: AgentChatClient,
        *,
        label: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text_delta: Any,
        on_thinking_delta: Any,
        on_tool_call_delta: Any,
        on_rate_limit_retry: Any = None,
    ) -> AgentModelTurn:
        """Bound one provider turn; max_model_turns cannot stop a hung turn."""

        try:
            return await asyncio.wait_for(
                client.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    on_rate_limit_retry=on_rate_limit_retry,
                ),
                timeout=self.model_turn_timeout_seconds,
            )
        except TimeoutError as exc:
            raise AgentModelError(
                f"{label} model turn exceeded "
                f"{self.model_turn_timeout_seconds:g} seconds",
            ) from exc

    @property
    def started(self) -> bool:
        return self._dispatcher is not None and not self._dispatcher.done()

    async def start(self) -> None:
        if self.started:
            return
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._dispatcher = asyncio.create_task(
            self._dispatch_loop(),
            name="creator-file-agent-dispatcher",
        )
        self._wake.set()
        # Startup sweep: the media scheduler is commit-driven, so READY
        # work-graph nodes that became dispatchable right before a
        # restart (field run 2026-08-09: all scenes locked, compose
        # READY, process bounced) would otherwise wait for the next
        # commit that may never come. One wake per Project re-evaluates
        # every graph; projects with nothing READY are a cheap no-op.
        # An unattended run the shutdown cancelled mid-turn additionally
        # gets one YOLO continuation — nobody is attending to retype
        # “继续”, and the existing fuses still bound runaway loops.
        try:
            summaries = await asyncio.to_thread(self.services.projects.list)
        except Exception:  # noqa: BLE001 - sweep must never block startup
            summaries = []
        for summary in summaries:
            self.work_scheduler.wake(summary.project_id)
            try:
                await self._resume_interrupted_run(summary.project_id)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "startup interrupted-run resume failed for %s",
                    summary.project_id,
                )

    async def _resume_interrupted_run(self, project_id: str) -> None:
        """Queue one YOLO continuation for a stalled unattended project.

        Two startup dead-ends are recovered here. A shutdown-cancelled
        run: the dispatcher only launches runs for pending user messages
        and graceful shutdown consumes the head message first, so the
        project would sit idle forever. A succeeded run whose work graph
        still carries model-required gaps: the end-of-run YOLO check can
        race automation that invalidates state right after it passed
        (field run 2026-08-09: the pre-compose design pass expired scene
        locks minutes after the run's clean exit). Both continuations go
        through the standard YOLO gate (auto-approve mode only, resume
        caps, no-progress fuse), so an actually-finished project is a
        no-op.
        """

        records = await asyncio.to_thread(self.runs.list, project_id)
        if not records:
            return
        last = records[-1]
        if last.status is AgentRunStatus.CANCELLED:
            code = str((last.error or {}).get("code") or "")
            if code != "SHUTDOWN":
                # SUPERSEDED/INTERRUPTED carry human intent (a replacement
                # request or an explicit stop); restarting must not
                # overrule them.
                return
            await self._queue_yolo_completion_resume(
                project_id=project_id,
                session_id=last.session_id,
                conversation_id=last.conversation_id,
                run_id=last.run_id,
                after_failure=True,
            )
            self._wake.set()
            return
        if last.status is AgentRunStatus.SUCCEEDED:
            await self._queue_yolo_completion_resume(
                project_id=project_id,
                session_id=last.session_id,
                conversation_id=last.conversation_id,
                run_id=last.run_id,
            )
            self._wake.set()

    async def stop(self) -> None:
        if self._commit_wake_listener is not None:
            self.services.poller.remove_commit_listener(
                self._commit_wake_listener,
            )
            self._commit_wake_listener = None
        self._stopping = True
        dispatcher = self._dispatcher
        self._dispatcher = None
        if dispatcher is not None:
            dispatcher.cancel()
        handles = list(self._active.values())
        for handle in handles:
            await asyncio.to_thread(
                self._revoke_epoch,
                handle.project_id,
                handle.run_id,
                handle.epoch,
            )
            handle.task.cancel()
        cleanup_tasks = list(self._interrupt_cleanup_tasks)
        for task in cleanup_tasks:
            task.cancel()
        if handles:
            await asyncio.gather(
                *(handle.task for handle in handles),
                return_exceptions=True,
            )
        if dispatcher is not None:
            await asyncio.gather(dispatcher, return_exceptions=True)
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        self._active.clear()
        self._interrupt_cleanup_tasks.clear()
        self._loop = None

    def notify(self, project_id: str) -> None:
        """Wake the coordinator after a Project/message is durably published."""

        self._blocked_heads.pop(project_id, None)
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    # pylint: disable=too-many-return-statements
    async def interrupt(
        self,
        project_id: str,
        *,
        superseded: bool = False,
        reason: str = "user_interrupt",
        expected_run_id: str | None = None,
    ) -> bool:
        """Cancel one Project's current task and revoke all later commits."""

        handle = self._active.get(project_id)
        if (
            superseded
            and expected_run_id is not None
            and handle is not None
            and handle.run_id != expected_run_id
        ):
            # The run captured by the superseding request's boundary is
            # already gone and a different run now owns the Session —
            # usually the replacement for that very request, which the
            # dispatcher admitted while the API was still finishing its
            # admission.  Cancelling it would swallow the request: the
            # supersede cleanup consumes the message that caused the
            # cancelled run, leaving nothing behind to resume.
            self.notify(project_id)
            return False
        if handle is None or handle.task.done():
            # Superseding an old AgentDock run is not a hard stop.  The API
            # path and the dispatcher may both observe the same durable
            # ReviewBoundary.  If the first caller already cancelled and
            # cleaned up the old handle, a second caller must leave the
            # replacement message pending for reconciliation instead of
            # consuming it through the idle-interrupt cleanup path.
            if superseded:
                self.notify(project_id)
                return False
            if reason == "project_deleted":
                # There is no durable Session to settle after the atomic
                # Project rename. Returning immediately also prevents an idle
                # cleanup writer from racing deletion and recreating Runtime
                # parents under the old Project id.
                self.work_scheduler.cancel_project(project_id)
                return False
            await self._record_idle_interrupt(project_id, reason=reason)
            self.notify(project_id)
            return False
        handle.superseded = superseded
        if handle.interrupting:
            # The durable INTERRUPT_REQUESTED status stays visible until the
            # cancellation cleanup persists the terminal session state, so the
            # dispatcher polls this path again.  Re-cancelling the task here
            # would abort that cleanup and leave the Session interrupted
            # forever; the first cancellation already owns the shutdown.
            self.notify(project_id)
            return True
        handle.interrupting = True
        immediate = reason in {"user_interrupt", "project_deleted"}
        if not immediate:
            # Internal callers use the awaited boundary when they need to
            # admit replacement work immediately after this method returns.
            # The HTTP hard-stop/delete paths use the signal-first branch
            # below so the UI never waits behind an in-progress commit.
            await asyncio.to_thread(
                self._revoke_epoch,
                project_id,
                handle.run_id,
                handle.epoch,
            )
            self.work_scheduler.cancel_project(project_id)
            handle.task.cancel()
            self.notify(project_id)
            return True
        # Signal cancellation first. Revoke may need to wait behind an atomic
        # publication already holding the in-process commit boundary; stop and
        # delete must not keep the caller waiting for that completed decision.
        self.work_scheduler.cancel_project(project_id)
        handle.task.cancel()
        cleanup = asyncio.create_task(
            asyncio.to_thread(
                self._revoke_epoch,
                project_id,
                handle.run_id,
                handle.epoch,
            ),
            name=f"creator-interrupt-revoke:{project_id}:{handle.run_id}",
        )
        self._interrupt_cleanup_tasks.add(cleanup)
        cleanup.add_done_callback(self._interrupt_cleanup_tasks.discard)
        self.notify(project_id)
        return True

    async def wait_until_idle(
        self,
        project_id: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            handle = self._active.get(project_id)
            if handle is None or handle.task.done():
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Creator Agent did not become idle: {project_id}",
                )
            await asyncio.sleep(0.01)

    async def _dispatch_loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
                self._wake.clear()
                try:
                    # Reconciliation only needs Project identities, not their
                    # loaded data.  ``list()`` fully reads every Project
                    # (parse + validate + canonicalize + deepcopy + resolve every
                    # indexed asset path) on each tick; with several Projects
                    # that pinned a core constantly.  ``discover_project_ids``
                    # is a directory scan with no payload load.  Per-Project load
                    # errors are handled inside ``_reconcile_project``.
                    project_ids = await asyncio.to_thread(
                        self.services.projects.discover_project_ids,
                    )
                except Exception:
                    # Storage integrity remains visible through health/recovery;
                    # one failed scan must not terminate the process driver.
                    continue
                for project_id in project_ids:
                    if self._stopping:
                        return
                    try:
                        await self._reconcile_project(project_id)
                    except Exception:
                        # A per-Project failure is persisted by its run whenever
                        # possible and must not starve unrelated Projects.
                        continue
                logger.debug(
                    "dispatch loop tick: projects=%d",
                    len(project_ids),
                )
        except asyncio.CancelledError:
            return

    # How long a QUEUED run may sit without progress before reconcile may
    # treat it as an orphan. Long enough that an in-flight admission in
    # another process (created QUEUED, not yet transitioned to RUNNING) is
    # never mistaken for one.
    _ORPHAN_RUN_GRACE_SECONDS = 60.0

    async def _reclaim_orphaned_run(
        self,
        project_id: str,
        session: Any,
    ) -> Any | None:
        """Release a Session whose active run can never make progress.

        Two crash shapes leave a dangling ``active_run_id`` behind:
        a run that already reached a terminal status while the Session
        pointer survived the crash between the two writes, and a QUEUED
        run bound to a terminal Goal (the pre-fix admission path allowed
        this), which no dispatcher will ever start. Both permanently
        wedge the Session: admission rejects every new message with
        "Active Goal is terminal" and reconcile treats the pointer as a
        foreign-process lease. Anything else — a QUEUED run inside the
        grace window or a RUNNING run — may legitimately belong to
        another process sharing this Runtime root and stays untouched.

        Returns the released Session, or ``None`` when nothing was
        reclaimed.
        """

        try:
            run = await asyncio.to_thread(
                self.runs.get,
                project_id,
                session.active_run_id,
            )
        except Exception:
            return None
        if run.status is AgentRunStatus.QUEUED:
            if not await self._cancel_queued_orphan(project_id, run):
                return None
        elif run.status not in TERMINAL_AGENT_RUN_STATUSES:
            return None
        elif (
            datetime.now(UTC) - run.updated_at
        ).total_seconds() < self._ORPHAN_RUN_GRACE_SECONDS:
            # A run that just reached its terminal status is almost always
            # a live owner between its final transition and its own
            # clear_active_run — stealing the lease in that window fails
            # the owner's cleanup for nothing. True crash leftovers stay
            # stuck far longer than the grace period.
            return None
        try:
            return await asyncio.to_thread(
                self.sessions.clear_active_run,
                project_id,
                session.session_id,
                expected_run_id=run.run_id,
                status=CreatorSessionStatus.IDLE,
            )
        except SessionStateConflict:
            return None

    async def _cancel_queued_orphan(
        self,
        project_id: str,
        run: CreatorAgentRunRecord,
    ) -> bool:
        """Cancel a QUEUED run that is provably unstartable, or decline."""

        age = (datetime.now(UTC) - run.updated_at).total_seconds()
        if age < self._ORPHAN_RUN_GRACE_SECONDS:
            return False
        try:
            goal = await asyncio.to_thread(
                self.sessions.get_goal,
                project_id,
                run.goal_id,
            )
        except RuntimeGoalNotFound:
            return False
        if goal.status not in _TERMINAL_GOAL_STATUSES:
            return False
        try:
            await asyncio.to_thread(
                self.runs.transition,
                project_id,
                run.run_id,
                expected_status=AgentRunStatus.QUEUED,
                status=AgentRunStatus.CANCELLED,
                updates={
                    "error": {
                        "code": "ORPHANED_ON_TERMINAL_GOAL",
                        "message": (
                            "run was queued against a terminal Goal "
                            f"({goal.status.value}) and could never "
                            "start; reconciled automatically"
                        ),
                    },
                },
            )
        except AgentRunStateConflict:
            # Another process moved the run first; re-evaluate on the
            # next poll instead of guessing.
            return False
        return True

    async def _reconcile_admission_state(
        self,
        project_id: str,
        session: Any,
        handle: Any,
    ) -> Any | None:
        """Settle durable pauses before reconcile may dispatch anything.

        Returns the converged Session, or ``None`` while the Session is
        paused — a durable interrupt is being served, or an active Review
        keeps the mainline waiting for the user.
        """

        if session.status is CreatorSessionStatus.INTERRUPT_REQUESTED:
            if handle is not None:
                await self.interrupt(project_id, reason="durable_interrupt")
            else:
                # No local handle: the pointed-at run either belongs to
                # another live process (RUNNING — leave it to cancel itself)
                # or is ownerless after a restart (QUEUED/terminal — serve
                # the durable stop here, or nobody ever will).
                await self._record_idle_interrupt(
                    project_id,
                    reason="durable_interrupt",
                )
            return None
        session = await self._converge_resolved_review(project_id, session)
        # Pending Review is a durable, recoverable pause. Messages may be
        # queued while the user decides, but none may start until every active
        # Review is resolved and the Session projection has converged.
        if session.status is CreatorSessionStatus.PENDING_REVIEW:
            return None
        return session

    async def _reconcile_project(self, project_id: str) -> None:
        handle = self._active.get(project_id)
        if handle is not None and handle.task.done():
            self._active.pop(project_id, None)
            handle = None
        # Snapshot read (shared lock, session.json only): reconcile only needs
        # status + head pointers to decide whether to launch a run, and the
        # full event-stream recovery of get_project_session costs ~1s on large
        # sessions (it reparses the whole events.jsonl under an exclusive lock,
        # which also starves every reader and causes lock timeouts).  Head
        # reconciliation is left to the next writer (_run_message).
        session = await asyncio.to_thread(
            self.sessions.get_project_session_snapshot,
            project_id,
        )
        session = await self._reconcile_admission_state(
            project_id,
            session,
            handle,
        )
        if session is None:
            return
        pending = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session.session_id,
            after_seq=session.last_consumed_message_seq,
            limit=None,
        )
        user_messages = [item for item in pending if item.role == "user"]

        # The durable Session, not this process-local coordinator, owns the
        # cross-process run lease. A second QwenPaw process may observe the same
        # filesystem, but it must not start a duplicate Agent run. An explicit
        # AgentDock interruption is the sole exception: it supersedes the old
        # lease before the replacement request is admitted.
        if session.active_run_id is not None and handle is None:
            interrupted = any(
                item.review_boundary is not None
                and item.review_boundary.interrupted_run_id
                == session.active_run_id
                for item in user_messages
            )
            if interrupted:
                session = await asyncio.to_thread(
                    self.sessions.clear_active_run,
                    project_id,
                    session.session_id,
                    expected_run_id=session.active_run_id,
                    status=CreatorSessionStatus.RESUMING,
                )
            else:
                reclaimed = await self._reclaim_orphaned_run(
                    project_id,
                    session,
                )
                if reclaimed is None:
                    return
                session = reclaimed

        if handle is not None:
            if any(
                item.review_boundary is not None
                and item.review_boundary.interrupted_run_id == handle.run_id
                for item in user_messages
            ):
                await self.interrupt(
                    project_id,
                    superseded=True,
                    reason="agentdock_interrupt",
                )
            return
        if not user_messages:
            if (
                session.status is CreatorSessionStatus.RESUMING
                and session.active_run_id is None
            ):
                # A supersede cleanup consumed its own replacement message,
                # so no pending input will ever move this Session out of
                # RESUMING.  Surface the truth instead of spinning forever.
                await asyncio.to_thread(
                    self.sessions.set_session_status,
                    project_id,
                    session.session_id,
                    CreatorSessionStatus.IDLE,
                )
            return
        message = user_messages[0]
        if self._blocked_heads.get(project_id) == message.message_seq:
            return
        # Durable variant of the in-memory guard above: sessions written
        # before failures consumed their request (or a crash between the
        # FAILED transition and the consumption) can still expose a failed
        # head message after a restart.  Relaunching it would auto-start the
        # Agent without any new user input, so consume it instead and let
        # AgentDock surface the persisted session error.
        head_runs = [
            record
            for record in await asyncio.to_thread(self.runs.list, project_id)
            if record.caused_by_message_seq == message.message_seq
        ]
        if head_runs and head_runs[-1].status is AgentRunStatus.FAILED:
            try:
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session.session_id,
                    through_seq=message.message_seq,
                    goal_id=head_runs[-1].goal_id,
                )
            except SessionStateConflict:
                pass
            return
        run_id = f"agent-run-{uuid4().hex}"
        epoch = self._begin_epoch(project_id, run_id)
        task = asyncio.create_task(
            self._run_message(project_id, message, run_id=run_id, epoch=epoch),
            name=f"creator-file-agent:{project_id}:{run_id}",
        )
        handle = _ProjectTask(
            project_id=project_id,
            run_id=run_id,
            message_seq=message.message_seq,
            epoch=epoch,
            task=task,
        )
        self._active[project_id] = handle

        def completed(_task: asyncio.Task[None]) -> None:
            current = self._active.get(project_id)
            if current is handle:
                self._active.pop(project_id, None)
            self._wake.set()

        task.add_done_callback(completed)

    @traced_async(
        "creator.agent.execution",
        component="creator.file_agent_runtime",
        context=lambda _self, project_id, message, *, run_id, epoch: {
            "projectId": project_id,
            "sessionId": message.creator_session_id,
            "conversationId": message.conversation_id,
            "runId": run_id,
        },
        attributes=lambda _self, project_id, message, *, run_id, epoch: {
            "messageId": message.message_id,
            "messageSeq": message.message_seq,
            "epoch": epoch,
        },
    )
    async def _run_message(
        self,
        project_id: str,
        message: CreatorMessageRecord,
        *,
        run_id: str,
        epoch: int,
    ) -> None:
        # Snapshot read: _run_message only needs session identity (session_id,
        # active_goal_id) to build the run record and resolve its goal; the
        # durable writes that follow (activate_run, runs.create, ...) take the
        # exclusive lock and reconcile the head themselves.  Avoiding the full
        # event-stream recovery here matters under concurrent runs.
        session = await asyncio.to_thread(
            self.sessions.get_project_session_snapshot,
            project_id,
        )
        goal, goal_created = await self._goal_for_message(session, message)
        snapshot = await asyncio.to_thread(
            self.services.projects.read,
            project_id,
        )
        context = self._tool_context(message, run_id=run_id)
        round_id = context.round_id or f"agent-round-{run_id}"
        record = CreatorAgentRunRecord(
            run_id=run_id,
            project_id=project_id,
            session_id=session.session_id,
            goal_id=goal.goal_id,
            conversation_id=message.conversation_id,
            round_id=round_id,
            caused_by_message_id=message.message_id,
            caused_by_message_seq=message.message_seq,
            caused_by_request_id=context.caused_by_request_id,
            origin=context.origin,
            review_policy=context.review_policy,
            review_boundary=context.review_boundary,
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
        )
        await asyncio.to_thread(self.runs.create, record)
        try:
            await asyncio.to_thread(
                self.sessions.activate_run,
                project_id,
                session.session_id,
                goal_id=goal.goal_id,
                run_id=run_id,
                status=CreatorSessionStatus.RUNNING,
            )
        except SessionStateConflict as exc:
            # A concurrent dispatcher (another process sharing this runtime
            # root, or a stale coordinator surviving a hot reinstall) won
            # the durable lease first. Without compensation the loser
            # leaks a QUEUED run forever and, when it also minted a fresh
            # Goal, leaves that Goal ACTIVE with no run that could ever
            # settle it — the Session then looks busy indefinitely.
            logger.warning(
                "duplicate admission lost the session lease: project=%s "
                "run=%s goal=%s: %s",
                project_id,
                run_id,
                goal.goal_id,
                exc,
            )
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self.runs.transition,
                    project_id,
                    run_id,
                    expected_status=AgentRunStatus.QUEUED,
                    status=AgentRunStatus.CANCELLED,
                    updates={
                        "error": {
                            "code": "DUPLICATE_ADMISSION",
                            "message": (
                                "a concurrent dispatcher already owns this "
                                "Session; duplicate run cancelled"
                            ),
                        },
                    },
                )
            if goal_created:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self.sessions.set_goal_status,
                        project_id,
                        goal.goal_id,
                        CreatorGoalStatus.CANCELLED,
                    )
            return
        await asyncio.to_thread(
            self.sessions.set_goal_status,
            project_id,
            goal.goal_id,
            CreatorGoalStatus.ACTIVE,
        )
        await asyncio.to_thread(
            self.runs.transition,
            project_id,
            run_id,
            expected_status=AgentRunStatus.QUEUED,
            status=AgentRunStatus.RUNNING,
        )
        await self._event(
            project_id,
            session.session_id,
            "agent.run.started",
            run_id,
            message,
            {
                "runId": run_id,
                "goalId": goal.goal_id,
                "reviewPolicy": context.review_policy.value,
                "origin": context.origin.value,
            },
        )

        commits = _FencedCommitBoundary(
            self,
            project_id,
            run_id,
            epoch,
            ProjectCommitBoundary(self.services.projects),
        )
        tools = AgentProjectTools(
            self.services.projects,
            context=context,
            transformer=self.services.jq,
            commits=commits,
        )
        try:
            result = await self._model_loop(
                project_id=project_id,
                session_id=session.session_id,
                run_id=run_id,
                epoch=epoch,
                request=message,
                tools=tools,
            )
            self._assert_epoch(project_id, run_id, epoch)
            await asyncio.to_thread(
                self.runs.transition,
                project_id,
                run_id,
                expected_status=AgentRunStatus.RUNNING,
                status=AgentRunStatus.SUCCEEDED,
                updates={
                    "tool_call_count": result.tool_call_count,
                    "review_ids": list(result.review_ids),
                    "final_summary": result.summary,
                },
            )
            await asyncio.to_thread(
                self.sessions.mark_messages_consumed,
                project_id,
                session.session_id,
                through_seq=message.message_seq,
                goal_id=goal.goal_id,
            )
            needs_review = bool(result.review_ids)
            await asyncio.to_thread(
                self.sessions.set_goal_status,
                project_id,
                goal.goal_id,
                (
                    CreatorGoalStatus.WAITING_REVIEW
                    if needs_review
                    else CreatorGoalStatus.COMPLETED
                ),
            )
            try:
                await asyncio.to_thread(
                    self.sessions.clear_active_run,
                    project_id,
                    session.session_id,
                    expected_run_id=run_id,
                    status=(
                        CreatorSessionStatus.PENDING_REVIEW
                        if needs_review
                        else CreatorSessionStatus.IDLE
                    ),
                )
            except SessionStateConflict as exc:
                # A sibling reconciler (another process on this runtime
                # root) already observed the terminal run record and
                # released the session first. The outcome is equivalent —
                # the run succeeded and the lease is free — so failing the
                # whole run here would flip a finished Goal to FAILED over
                # a no-op.
                logger.warning(
                    "session lease already released after success: "
                    "project=%s run=%s: %s",
                    project_id,
                    run_id,
                    exc,
                )
            await self._event(
                project_id,
                session.session_id,
                "agent.run.completed",
                run_id,
                message,
                {
                    "runId": run_id,
                    "goalId": goal.goal_id,
                    "reviewIds": list(result.review_ids),
                    "summary": result.summary,
                },
            )
            if (
                context.review_boundary is not None
                and context.review_boundary.interrupted_run_id is not None
            ):
                await self._queue_mainline_resume(
                    project_id=project_id,
                    session_id=session.session_id,
                    conversation_id=message.conversation_id,
                    intervention_run_id=run_id,
                    interrupted_run_id=(
                        context.review_boundary.interrupted_run_id
                    ),
                )
            elif not needs_review:
                # Unattended (YOLO) projects treat a succeeded mainline as a
                # checkpoint, not a finish line: resume until every element
                # has its video (fused against runaway loops inside).
                await self._queue_yolo_completion_resume(
                    project_id=project_id,
                    session_id=session.session_id,
                    conversation_id=message.conversation_id,
                    run_id=run_id,
                )
            self._blocked_heads.pop(project_id, None)
        except asyncio.CancelledError:
            await self._cancel_run_if_project_exists(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
            )
            raise
        except StaleAgentRun:
            await self._cancel_run_if_project_exists(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
            )
            return
        except AgentModelConfigurationError as exc:
            logger.error(
                "Agent run %s failed — model configuration missing: %s",
                run_id,
                exc,
            )
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="MODEL_CONFIG_MISSING",
                message_text=str(exc),
                retryable=False,
            )
            self._blocked_heads[project_id] = message.message_seq
        except RepeatedDeterministicToolFailure as exc:
            logger.error(
                "Agent run %s stopped after repeated deterministic tool failure: %s",
                run_id,
                exc,
            )
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="TOOL_NON_PROGRESS",
                message_text=str(exc),
                retryable=False,
            )
            self._blocked_heads[project_id] = message.message_seq
        except RateLimitExhaustedError as exc:
            logger.error(
                "Agent run %s failed — model rate limit exhausted after "
                "%d retries: %s",
                run_id,
                exc.retries,
                exc,
            )
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="MODEL_RATE_LIMITED",
                # Neutral technical text: AgentDock renders the localized
                # notice from locales via the MODEL_RATE_LIMITED code.
                message_text=str(exc),
                retryable=True,
                extra_details={"retryCount": exc.retries},
            )
            self._blocked_heads[project_id] = message.message_seq
        except AgentModelError as exc:
            logger.error(
                "Agent run %s failed — model request error: %s",
                run_id,
                exc,
            )
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="MODEL_REQUEST_FAILED",
                message_text=str(exc),
                retryable=True,
            )
            self._blocked_heads[project_id] = message.message_seq
        except AgentStreamCallbackError as exc:
            cause = exc.cause
            logger.error(
                "Agent run %s failed — stream persistence error: %s: %s",
                run_id,
                type(cause).__name__,
                cause,
            )
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="STREAM_PERSISTENCE_FAILED",
                message_text=f"{type(cause).__name__}: {cause}",
                retryable=True,
            )
            self._blocked_heads[project_id] = message.message_seq
        except Exception as exc:
            logger.error(
                "Agent run %s failed — unexpected error: %s: %s",
                run_id,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="AGENT_RUN_FAILED",
                message_text=f"{type(exc).__name__}: {exc}",
                retryable=False,
            )
            self._blocked_heads[project_id] = message.message_seq

    async def _model_loop(
        self,
        *,
        project_id: str,
        session_id: str,
        run_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        tools: AgentProjectTools,
    ) -> _LoopResult:
        # External skills never break the run: loading is isolated and a
        # broken configuration only yields an empty toolset/context block.
        # Loading scans the skills directories and may probe `node --version`
        # (up to 10s), so it must not run on the event loop.
        external_skills = await asyncio.to_thread(load_external_skills)
        tool_manifest = _creator_agent_tool_manifest(external_skills)
        conversation_records = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session_id,
            after_seq=0,
            limit=None,
        )
        prior_context = [
            item
            for item in conversation_records
            if item.conversation_id == request.conversation_id
            and item.message_seq < request.message_seq
        ]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": render_creator_system_prompt(
                    project_id=project_id,
                    workspace_schema=tools.schema_prompt.text,
                    external_skills=render_external_skills_context(
                        external_skills,
                    ),
                ),
            },
            {
                "role": "user",
                "content": _continuation_message_text(request, prior_context),
            },
        ]
        tool_call_count = 0
        review_ids: list[str] = []
        waiting_review_summary: str | None = None
        malformed_jq_attempts = 0
        malformed_jq_fingerprints: set[str] = set()
        deterministic_failure_counts: dict[str, int] = {}
        # Element-heavy projects legitimately need more mainline turns
        # (one element per jq_project call plus one delegation each), so
        # the runaway cap scales with the current timeline size instead of
        # failing healthy long runs.
        try:
            snapshot = await asyncio.to_thread(
                self.services.projects.read,
                project_id,
            )
            element_count = sum(
                len(timeline.elements_by_id)
                for timeline in snapshot.project.timelines.items.values()
            )
        except Exception:
            element_count = 0
        turn_budget = scale_mainline_max_model_turns(
            self.max_model_turns,
            element_count,
        )
        # The element-scaled budget is used as-is: skills provide domain
        # knowledge through the viewer and deliverables flow through the
        # native pipeline, so no per-tool budget extension exists anymore.
        effective_max_turns = turn_budget
        turn_number = 0
        finalization_turn_added = False
        while turn_number < effective_max_turns:
            turn_number += 1
            self._assert_epoch(project_id, run_id, epoch)
            _compact_wire_project_snapshots(messages)
            assistant_message_id = f"message-{uuid4().hex}"
            delta_index = 0
            # The authoritative assistant message is still persisted durably by
            # ``_persist_assistant_turn`` at turn end.

            async def persist_message_delta(
                stream_kind: str,
                delta: str,
            ) -> None:
                nonlocal delta_index
                if not delta:
                    return
                self._assert_epoch(project_id, run_id, epoch)
                await self._event(
                    project_id,
                    session_id,
                    "agent.message_delta",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "messageId": assistant_message_id,
                        "deltaIndex": delta_index,
                        "delta": delta,
                        "streamKind": stream_kind,
                    },
                )
                delta_index += 1

            async def persist_text_delta(delta: str) -> None:
                # Once a tool has opened a Review, the Runtime owns the pause
                # and resume contract. Suppress the model's free-form final
                # CTA so it cannot ask the user to send "continue"; the
                # canonical review summary is emitted after the turn ends.
                if review_ids:
                    return
                await persist_message_delta("text", delta)

            async def persist_thinking_delta(delta: str) -> None:
                await persist_message_delta("thinking", delta)

            async def persist_tool_progress(
                tool_call_id: str,
                state: _ToolArgumentProgressState,
                complete: bool,
            ) -> None:
                nonlocal delta_index
                self._assert_epoch(project_id, run_id, epoch)
                await self._event(
                    project_id,
                    session_id,
                    "agent.tool_progress",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "messageId": assistant_message_id,
                        "toolCallId": tool_call_id,
                        "tool": state.tool,
                        "deltaIndex": delta_index,
                        "receivedBytes": state.received_bytes,
                        "providerChunkCount": state.provider_chunk_count,
                        "complete": complete,
                        "stage": (
                            "arguments_complete"
                            if complete
                            else "assembling_arguments"
                        ),
                    },
                )
                delta_index += 1

            tool_progress = _ToolArgumentProgressReporter(
                persist_tool_progress,
            )

            async def report_rate_limit_retry(
                notice: RateLimitRetryNotice,
            ) -> None:
                self._assert_epoch(project_id, run_id, epoch)
                await self._event(
                    project_id,
                    session_id,
                    "agent.model.rate_limit_retry",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "attempt": notice.attempt,
                        "maxAttempts": notice.max_attempts,
                        "delaySeconds": notice.delay_seconds,
                    },
                )

            turn = await self._complete_model_turn(
                self.model_client,
                label="Creator Agent",
                messages=messages,
                tools=tool_manifest,
                on_text_delta=persist_text_delta,
                on_thinking_delta=persist_thinking_delta,
                on_tool_call_delta=tool_progress.feed,
                on_rate_limit_retry=report_rate_limit_retry,
            )
            await tool_progress.finish(turn.tool_calls)
            self._assert_epoch(project_id, run_id, epoch)
            if len(turn.tool_calls) > 1:
                raise AgentModelError(
                    "Creator Agent returned more than one tool call in one turn",
                )
            if not turn.tool_calls and turn.content is None:
                raise AgentModelError(
                    "Creator Agent returned no final content or tool calls",
                )
            if not turn.tool_calls and review_ids:
                canonical_summary = _agent_waiting_review_summary(
                    waiting_review_summary,
                )
                turn = AgentModelTurn(
                    content=canonical_summary,
                    thinking=turn.thinking,
                    provider_message_id=turn.provider_message_id,
                    finish_reason=turn.finish_reason,
                    usage=turn.usage,
                )
                await persist_message_delta("text", canonical_summary)
            await self._persist_assistant_turn(
                project_id,
                session_id,
                run_id,
                request,
                turn,
                message_id=assistant_message_id,
            )
            assistant_wire: dict[str, Any] = {
                "role": "assistant",
                "content": turn.content,
            }
            if turn.tool_calls:
                assistant_wire["tool_calls"] = [
                    call.history_dict() for call in turn.tool_calls
                ]
            messages.append(assistant_wire)
            if not turn.tool_calls:
                return _LoopResult(
                    summary=turn.content,
                    tool_call_count=tool_call_count,
                    review_ids=tuple(review_ids),
                )

            for call in turn.tool_calls:
                tool_call_count += 1
                tool_failed = False
                malformed_budget_exhausted = False
                repeated_failure_exhausted = False
                self._assert_epoch(project_id, run_id, epoch)
                logger.info(
                    "tool: project=%s run=%s tool=%s call_id=%s args=%s",
                    project_id,
                    run_id,
                    call.name,
                    call.call_id,
                    (
                        _prompt_preview(call.arguments, limit=200)
                        if call.name != DELEGATE_TOOL_NAME
                        else call.arguments.get("task")
                    ),
                )
                await self._event(
                    project_id,
                    session_id,
                    "agent.tool_started",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "actionId": call.call_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "messageId": assistant_message_id,
                        "arguments": dict(call.arguments),
                        "rawArgumentsBytes": call.raw_arguments_bytes,
                        "providerChunkCount": call.provider_chunk_count,
                        "argumentsRepaired": call.arguments_repaired,
                        "finishReason": turn.finish_reason,
                    },
                )
                try:
                    if call.parse_error is not None:
                        raise ToolArgumentsJSONError(call.parse_error)
                    if call.name == JQ_PROJECT_TOOL_NAME:
                        diagnosis = _jq_project_argument_diagnosis(call)
                        next_attempt = (
                            0
                            if diagnosis.safe_to_execute
                            else malformed_jq_attempts + 1
                        )
                        await self._event(
                            project_id,
                            session_id,
                            "agent.tool_arguments_checked",
                            run_id,
                            request,
                            {
                                "runId": run_id,
                                "actionId": call.call_id,
                                "toolCallId": call.call_id,
                                "tool": call.name,
                                "messageId": assistant_message_id,
                                "malformedAttempt": next_attempt,
                                **diagnosis.event_payload(),
                            },
                        )
                        if not diagnosis.safe_to_execute:
                            malformed_jq_attempts = next_attempt
                            repeated_payload = (
                                diagnosis.fingerprint
                                in malformed_jq_fingerprints
                            )
                            malformed_jq_fingerprints.add(
                                diagnosis.fingerprint,
                            )
                            raise MalformedJqProjectArguments(
                                diagnosis,
                                attempt=malformed_jq_attempts,
                                repeated_payload=repeated_payload,
                            )
                        # A structurally valid replacement resolves the current
                        # malformed-payload incident. Normal jq/CAS failures
                        # retain their existing recovery behavior.
                        malformed_jq_attempts = 0
                        malformed_jq_fingerprints.clear()
                    # External skill tools take their Project identity from
                    # the runtime, never from the model, so a stray projectId
                    # echo from the model must not kill the whole run.
                    if (
                        call.name != DELEGATE_TOOL_NAME
                        and call.name not in EXTERNAL_SKILL_TOOL_NAMES
                        and "projectId" in call.arguments
                        and call.arguments.get("projectId") != project_id
                    ):
                        raise FileAgentRuntimeError(
                            "model tool call attempted another Project",
                        )
                    if call.name == DELEGATE_TOOL_NAME:
                        result = await self._run_subagent(
                            project_id=project_id,
                            session_id=session_id,
                            parent_run_id=run_id,
                            parent_action_id=call.call_id,
                            epoch=epoch,
                            request=request,
                            tools=tools,
                            arguments=call.arguments,
                        )
                    elif call.name == GROUND_PROMPT_CONTEXT_TOOL_NAME:
                        result = await self._run_ground_prompt_context(
                            request=request,
                            arguments=call.arguments,
                        )
                    elif call.name == OBJECT_GROUNDING_TOOL_NAME:
                        result = await self._run_object_grounding(
                            request=request,
                            arguments=call.arguments,
                        )
                    elif call.name in EXTERNAL_SKILL_TOOL_NAMES:
                        result = await self._run_external_skill_tool(
                            name=call.name,
                            arguments=call.arguments,
                        )
                    else:
                        result = await asyncio.to_thread(
                            tools.invoke,
                            call.name,
                            call.arguments,
                        )
                    self._assert_epoch(project_id, run_id, epoch)
                    review_id = result.get("reviewId")
                    if (
                        isinstance(review_id, str)
                        and review_id
                        and review_id not in review_ids
                    ):
                        review_ids.append(review_id)
                    if result.get("status") == "WAITING_REVIEW":
                        candidate_summary = result.get("summary")
                        if (
                            isinstance(candidate_summary, str)
                            and candidate_summary.strip()
                        ):
                            waiting_review_summary = candidate_summary
                    await self._persist_tool_result(
                        project_id,
                        session_id,
                        run_id,
                        request,
                        call_id=call.call_id,
                        tool_name=call.name,
                        result=result,
                    )
                    if call.name in {"jq_project", "patch_project"}:
                        await self._workspace_changed(
                            project_id,
                            session_id,
                            run_id,
                            request,
                            result,
                            action_id=call.call_id,
                        )
                    tool_content = json.dumps(
                        result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                except (asyncio.CancelledError, StaleAgentRun):
                    raise
                except Exception as exc:
                    tool_failed = True
                    if isinstance(exc, MalformedJqProjectArguments):
                        error_result = exc.tool_result()
                        malformed_budget_exhausted = (
                            exc.attempt > MAX_MALFORMED_JQ_PROJECT_RETRIES
                        )
                    else:
                        failure_fingerprint = (
                            _deterministic_tool_failure_fingerprint(
                                call,
                                exc,
                            )
                        )
                        if failure_fingerprint is not None:
                            failure_count = (
                                deterministic_failure_counts.get(
                                    failure_fingerprint,
                                    0,
                                )
                                + 1
                            )
                            deterministic_failure_counts[
                                failure_fingerprint
                            ] = failure_count
                            repeated_failure_exhausted = (
                                failure_count
                                >= MAX_REPEATED_DETERMINISTIC_TOOL_FAILURES
                            )
                        error_result = _tool_failure_result(call.name, exc)
                    await self._persist_tool_result(
                        project_id,
                        session_id,
                        run_id,
                        request,
                        call_id=call.call_id,
                        tool_name=call.name,
                        result=error_result,
                        failed=True,
                    )
                    tool_content = json.dumps(
                        error_result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": tool_content,
                        "failed": tool_failed,
                    },
                )
                if malformed_budget_exhausted:
                    raise RepeatedDeterministicToolFailure(
                        "jq_project produced structurally corrupted tool "
                        "arguments after 2 bounded retries; the run stopped "
                        "before jq execution",
                    )
                if repeated_failure_exhausted:
                    raise RepeatedDeterministicToolFailure(
                        "Creator Agent repeated the same non-retryable "
                        f"{call.name} failure twice without changing its "
                        "arguments; the run stopped instead of starting "
                        "another model turn",
                    )
            if (
                turn_number == effective_max_turns
                and not finalization_turn_added
            ):
                # A healthy last-budget tool result used to be followed by an
                # immediate run failure, before the model could observe the
                # result and conclude. Grant exactly one non-runaway recovery
                # turn and explicitly require a final answer, not more work.
                finalization_turn_added = True
                effective_max_turns += 1
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "MODEL_TURN_BUDGET_FINALIZE: The normal tool-turn "
                            "budget is exhausted. Inspect the latest tool "
                            "result and now return the best truthful final "
                            "summary. Do not call another tool. If work remains, "
                            "state it explicitly as blocked/remaining work."
                        ),
                    },
                )
        raise AgentModelError(
            f"Creator Agent exceeded {effective_max_turns} model turns",
        )

    async def _run_ground_prompt_context(
        self,
        *,
        request: CreatorMessageRecord,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        prompt = str(arguments.get("prompt") or _message_text(request)).strip()
        if not prompt:
            raise FileAgentRuntimeError(
                "ground_prompt_context requires prompt text",
            )

        raw_queries = arguments.get("queries")
        queries: list[str] | None = None
        if raw_queries is not None:
            if not isinstance(raw_queries, list) or not all(
                isinstance(item, str) for item in raw_queries
            ):
                raise FileAgentRuntimeError(
                    "ground_prompt_context queries must be a string array",
                )
            queries = [item for item in raw_queries if item.strip()]

        raw_context = arguments.get("context")
        if raw_context is not None and not isinstance(raw_context, dict):
            raise FileAgentRuntimeError(
                "ground_prompt_context context must be an object",
            )

        detector = arguments.get("detector")
        if detector is not None and detector not in {
            "hybrid",
            "llm",
            "heuristic",
        }:
            raise FileAgentRuntimeError(
                "ground_prompt_context detector is invalid",
            )

        include_visuals = arguments.get("includeVisuals")
        if include_visuals is not None and not isinstance(
            include_visuals,
            bool,
        ):
            raise FileAgentRuntimeError(
                "ground_prompt_context includeVisuals must be boolean",
            )
        force = arguments.get("force", False)
        if not isinstance(force, bool):
            raise FileAgentRuntimeError(
                "ground_prompt_context force must be boolean",
            )
        detect_only = arguments.get("detectOnly", False)
        if not isinstance(detect_only, bool):
            raise FileAgentRuntimeError(
                "ground_prompt_context detectOnly must be boolean",
            )

        result = await ground_prompt_context(
            prompt,
            context=raw_context,
            queries=queries,
            force=force,
            detect_only=detect_only,
            detector=detector,
            max_sources=get_web_grounding_max_sources(),
            timeout=float(get_web_grounding_timeout_seconds()),
            visual_search_timeout=float(
                get_web_grounding_visual_search_timeout_seconds(),
            ),
            image_download_timeout=float(
                get_web_grounding_image_download_timeout_seconds(),
            ),
            verification_timeout=float(
                get_web_grounding_verification_timeout_seconds(),
            ),
            include_visuals=include_visuals,
        )
        return await self._promote_grounding_visuals(
            project_id=request.project_id,
            request_id=request.message_id,
            result=result,
        )

    def _read_object_grounding_project_image(
        self,
        project_id: str,
        image_ref: str,
    ) -> tuple[bytes | None, str | None]:
        parsed_ref = _object_grounding_version_ref(image_ref)
        if parsed_ref is None:
            raise FileAgentRuntimeError(
                "ground_image_objects imageRef is not a supported Project ref",
            )
        kind, version_id = parsed_ref
        snapshot = self.services.projects.read(project_id)
        if kind == "asset":
            version = snapshot.project.assets.source_versions_by_id.get(
                version_id,
            )
        else:
            version = snapshot.project.assets.artifact_versions_by_id.get(
                version_id,
            )
        if version is None:
            raise FileAgentRuntimeError(
                f"ground_image_objects image version does not exist: {version_id}",
            )
        if not str(version.media_type or "").casefold().startswith("image/"):
            raise FileAgentRuntimeError(
                f"ground_image_objects imageRef is not an image: {version_id}",
            )
        if version.file_id:
            indexed = snapshot.project.assets.files_by_id.get(version.file_id)
            if indexed is None:
                raise FileAgentRuntimeError(
                    f"ground_image_objects image file is missing from the index: {version_id}",
                )
            if indexed.sha256 != version.checksum:
                raise FileAgentRuntimeError(
                    f"ground_image_objects image checksum does not match the index: {version_id}",
                )
            content = AssetFileStore(
                self.services.projects.project_root(project_id),
            ).read_verified(indexed)
            return content, None
        if kind == "asset" and isinstance(version, SourceAssetVersion):
            remote_url = public_source_url(version)
            if remote_url:
                return None, remote_url
        raise FileAgentRuntimeError(
            f"ground_image_objects image bytes are unavailable: {version_id}",
        )

    async def _resolve_object_grounding_image(
        self,
        project_id: str,
        image_ref: str,
    ) -> bytes:
        ref = str(image_ref or "").strip()
        if ref.startswith(("http://", "https://")):
            content, _filename = await read_reference_media(
                ref,
                max_bytes=GROUNDING_VISUAL_MAX_BYTES,
            )
        elif ref.startswith("/generated/"):
            path = media_path_from_url(ref)
            project_root = self.services.projects.project_root(
                project_id,
            ).resolve()
            try:
                path.resolve().relative_to(project_root)
            except ValueError as exc:
                raise FileAgentRuntimeError(
                    "ground_image_objects cannot read generated media outside the current Project",
                ) from exc
            content, _filename = await read_reference_media(
                ref,
                max_bytes=GROUNDING_VISUAL_MAX_BYTES,
            )
        else:
            content, remote_url = await asyncio.to_thread(
                self._read_object_grounding_project_image,
                project_id,
                ref,
            )
            if content is None:
                if not remote_url:
                    raise FileAgentRuntimeError(
                        "ground_image_objects image bytes are unavailable",
                    )
                content, _filename = await read_reference_media(
                    remote_url,
                    max_bytes=GROUNDING_VISUAL_MAX_BYTES,
                )
        if len(content) > GROUNDING_VISUAL_MAX_BYTES:
            raise FileAgentRuntimeError(
                f"ground_image_objects image exceeds {GROUNDING_VISUAL_MAX_BYTES} bytes",
            )
        try:
            validate_reference_image_bytes(content)
        except ValueError as exc:
            raise FileAgentRuntimeError(
                "ground_image_objects image cannot be decoded",
            ) from exc
        return content

    @staticmethod
    def _write_object_grounding_runtime_image(
        *,
        project_id: str,
        request_id: str,
        content: bytes,
        subdir: str,
        prefix: str,
        suffix: str,
    ) -> str:
        with media_task_scope(request_id, project_id=project_id):
            path = unique_task_work_path(
                subdir,
                suffix,
                prefix=prefix,
                task_id=request_id,
            )
            atomic_replace_bytes(path, content)
            return media_url_for(path)

    async def _run_object_grounding(
        self,
        *,
        request: CreatorMessageRecord,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        image_ref = str(arguments.get("imageRef") or "").strip()
        prompt = str(arguments.get("prompt") or "").strip()
        return_image = arguments.get("returnImage", False)
        if not image_ref:
            raise FileAgentRuntimeError(
                "ground_image_objects requires imageRef",
            )
        if not prompt:
            raise FileAgentRuntimeError(
                "ground_image_objects requires prompt",
            )
        if len(prompt) > 1000:
            raise FileAgentRuntimeError(
                "ground_image_objects prompt exceeds 1000 characters",
            )
        if not isinstance(return_image, bool):
            raise FileAgentRuntimeError(
                "ground_image_objects returnImage must be boolean",
            )
        content = await self._resolve_object_grounding_image(
            request.project_id,
            image_ref,
        )
        suffix = object_grounding_image_suffix(content)
        input_url = await asyncio.to_thread(
            self._write_object_grounding_runtime_image,
            project_id=request.project_id,
            request_id=request.message_id,
            content=content,
            subdir="object-grounding",
            prefix="input-",
            suffix=suffix,
        )
        result = await ground_image_objects(
            content,
            input_url,
            prompt,
        )
        response: dict[str, Any] = {
            "ok": True,
            "status": "success",
            "imageRef": image_ref,
            "inputImageUrl": input_url,
            **result,
        }
        if return_image:
            annotated = await asyncio.to_thread(
                render_object_grounding_annotation,
                content,
                list(result.get("detections") or []),
            )
            response["annotatedImageUrl"] = await asyncio.to_thread(
                self._write_object_grounding_runtime_image,
                project_id=request.project_id,
                request_id=request.message_id,
                content=annotated,
                subdir="object-grounding",
                prefix="annotated-",
                suffix=".png",
            )
        return response

    async def _promote_grounding_visuals(
        self,
        *,
        project_id: str,
        request_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        visual_sources = result.get("visual_sources")
        if not isinstance(visual_sources, list) or not visual_sources:
            return result
        promoted = await asyncio.to_thread(
            self._promote_grounding_visuals_sync,
            project_id,
            request_id,
            visual_sources,
        )
        if not promoted["promoted"]:
            result["grounding_asset_promotion"] = promoted
            return result
        by_index = {
            item["index"]: item
            for item in promoted["promoted"]
            if isinstance(item.get("index"), int)
        }
        for index, source in enumerate(visual_sources):
            if not isinstance(source, dict):
                continue
            entry = by_index.get(index)
            if entry is None:
                continue
            source["workspace_ref"] = entry["workspace_ref"]
            source["assetVersionRef"] = entry["workspace_ref"]
            source["source_asset_version_id"] = entry[
                "source_asset_version_id"
            ]
            source["logical_asset_id"] = entry["logical_asset_id"]
            source["indexed_file_id"] = entry["file_id"]
        context_lines = [
            "",
            "Workspace Visual References:",
            *[
                (
                    f"[G{item['index'] + 1}] "
                    f"{item['workspace_ref']} "
                    f"asset_version_id={item['source_asset_version_id']} "
                    f"local={item.get('local_url') or ''}"
                ).rstrip()
                for item in promoted["promoted"]
            ],
        ]
        grounded_context = str(result.get("grounded_context") or "").rstrip()
        result["grounded_context"] = "\n".join(
            item for item in [grounded_context, *context_lines] if item
        )
        result["grounding_asset_promotion"] = promoted
        return result

    def _promote_grounding_visuals_sync(
        self,
        project_id: str,
        request_id: str,
        visual_sources: list[Any],
    ) -> dict[str, Any]:
        promoted: list[dict[str, Any]] = []
        issues: list[str] = []
        changed = False
        project_root = self.services.projects.project_root(project_id)
        file_store = AssetFileStore(project_root)
        with self.services.projects.lifecycle_lock(project_id):
            base = self.services.projects.read(project_id)
            candidate = base.project.model_dump(mode="json")
            files = candidate["assets"]["files_by_id"]
            versions = candidate["assets"]["source_versions_by_id"]
            created_at = datetime.now(UTC)
            for index, raw_source in enumerate(visual_sources):
                if not isinstance(raw_source, Mapping):
                    continue
                if not _grounding_visual_is_usable(raw_source):
                    continue
                local_path = _grounding_local_path(raw_source)
                if local_path is None:
                    issues.append(f"visual_source_missing_local_path:{index}")
                    continue
                try:
                    stat = local_path.stat()
                except OSError as exc:
                    issues.append(
                        f"visual_source_unavailable:{index}:{type(exc).__name__}",
                    )
                    continue
                if not local_path.is_file() or stat.st_size <= 0:
                    issues.append(f"visual_source_not_regular:{index}")
                    continue
                if stat.st_size > GROUNDING_VISUAL_MAX_BYTES:
                    issues.append(
                        f"visual_source_too_large:{index}:{stat.st_size}",
                    )
                    continue
                content = local_path.read_bytes()
                try:
                    validate_reference_image_bytes(content)
                except ValueError:
                    issues.append(f"visual_source_invalid_image:{index}")
                    continue
                checksum = hashlib.sha256(content).hexdigest()
                identity = str(raw_source.get("storage_sha256") or checksum)
                logical_asset_id = _grounding_stable_id(
                    "asset",
                    project_id,
                    identity,
                )
                version_id = _grounding_stable_id(
                    "asset-version",
                    project_id,
                    identity,
                )
                file_id = _grounding_stable_id("file", project_id, identity)
                media_type = str(
                    raw_source.get("media_type")
                    or (raw_source.get("download") or {}).get("media_type")
                    or mimetypes.guess_type(local_path.name)[0]
                    or "image/jpeg",
                )
                if not media_type.casefold().startswith("image/"):
                    issues.append(
                        f"visual_source_not_image:{index}:{media_type}",
                    )
                    continue
                relative_uri = PurePosixPath(
                    "assets",
                    "sources",
                    f"{file_id}{_grounding_extension(local_path, media_type)}",
                ).as_posix()
                indexed = IndexedFile(
                    file_id=file_id,
                    kind="source_original",
                    relative_uri=relative_uri,
                    sha256=checksum,
                    size_bytes=len(content),
                    media_type=media_type,
                    created_at=created_at,
                )
                version = SourceAssetVersion(
                    version_id=version_id,
                    logical_asset_id=logical_asset_id,
                    name=str(
                        raw_source.get("title")
                        or f"Grounding visual {index + 1}",
                    )[:160],
                    file_id=file_id,
                    checksum=checksum,
                    media_kind=_grounding_media_kind(media_type),  # type: ignore[arg-type]
                    media_type=media_type,
                    provenance_refs=[
                        item
                        for item in (
                            str(raw_source.get("url") or ""),
                            str(raw_source.get("source_url") or ""),
                            str(raw_source.get("grounding_ref") or ""),
                        )
                        if item
                    ],
                    created_at=created_at,
                    metadata={
                        "sourceKind": "web_grounding_visual",
                        "requestId": request_id,
                        "provider": str(raw_source.get("provider") or ""),
                        "query": str(raw_source.get("query") or ""),
                        "entityName": str(raw_source.get("entity_name") or ""),
                        "usage": str(
                            raw_source.get("usage")
                            or raw_source.get("usage_hint")
                            or "",
                        ),
                        "localUrl": str(
                            raw_source.get("local_url") or local_path.as_uri(),
                        ),
                    },
                )
                indexed_json = indexed.model_dump(mode="json")
                version_json = version.model_dump(mode="json")
                existing_file = files.get(file_id)
                existing_version = versions.get(version_id)
                if existing_file is not None:
                    existing_created_at = existing_file.get("created_at")
                    if existing_created_at is not None:
                        indexed_json["created_at"] = existing_created_at
                    if existing_file != indexed_json:
                        raise ConflictError(
                            "Grounding visual file id collision",
                        )
                if existing_version is not None:
                    existing = SourceAssetVersion.model_validate(
                        existing_version,
                    )
                    if (
                        existing.logical_asset_id != logical_asset_id
                        or existing.checksum != checksum
                        or existing.file_id != file_id
                    ):
                        raise ConflictError(
                            "Grounding visual asset version collision",
                        )
                if existing_file is None:
                    staged = file_store.stage_bytes(
                        content,
                        staging_id=f"grounding-{file_id[:48]}",
                    )
                    try:
                        file_store.publish(
                            staged,
                            relative_uri,
                            expected_sha256=checksum,
                            expected_size_bytes=len(content),
                        )
                    except AssetAlreadyExists:
                        file_store.abandon(staged)
                    files[file_id] = indexed_json
                    changed = True
                if existing_version is None:
                    versions[version_id] = version_json
                    changed = True
                promoted.append(
                    {
                        "index": index,
                        "workspace_ref": workspace_asset_ref(
                            logical_asset_id,
                            version_id,
                        ),
                        "logical_asset_id": logical_asset_id,
                        "source_asset_version_id": version_id,
                        "file_id": file_id,
                        "local_url": str(
                            raw_source.get("local_url") or local_path.as_uri(),
                        ),
                    },
                )
            if changed:
                commit = self.services.commits.commit(
                    base=base,
                    candidate=candidate,
                    origin=ChangeOrigin.RUNTIME_TASK,
                    review_policy=ReviewPolicy.AUTO_FIX,
                    caused_by_request_id=request_id,
                    round_id=_grounding_stable_id(
                        "round",
                        project_id,
                        request_id,
                    ),
                    transaction_id=_grounding_stable_id(
                        "transaction",
                        project_id,
                        request_id,
                    ),
                    advance_accepted_baseline=True,
                    _lifecycle_lock_held=True,
                )
                self.services.poller.note_commit(commit.snapshot)
        return {
            "status": "success" if promoted else "skipped",
            "promoted_count": len(promoted),
            "promoted": promoted,
            "issues": issues,
        }

    async def _run_external_skill_tool(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Serve one skill viewer call from the main Agent.

        Skill failures surface as regular tool errors through the generic
        handler; they never abort the run or the session.
        """

        skill_name = str(arguments.get("skill") or "").strip()
        if not skill_name:
            raise FileAgentRuntimeError(f"{name} requires skill")
        if name != VIEW_SKILL_TOOL_NAME:
            raise FileAgentRuntimeError(
                f"unhandled external skill tool: {name}",
            )
        return await asyncio.to_thread(
            view_external_skill,
            skill_name=skill_name,
        )

    async def _run_subagent(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        parent_action_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        tools: AgentProjectTools,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        delegated = DelegateToAgentInput.model_validate(dict(arguments))
        delegated.validate_contract(project_id=project_id)
        feedback_target_refs = _review_feedback_target_refs(request)
        if feedback_target_refs and not set(delegated.target_refs).issubset(
            feedback_target_refs,
        ):
            raise FileAgentRuntimeError(
                "review regeneration may only delegate the rejected targets: "
                + ", ".join(sorted(feedback_target_refs)),
            )
        role = delegated.role
        role_name = role.value
        snapshot = await asyncio.to_thread(
            self.services.projects.read,
            project_id,
        )
        delegated.validate_project_targets(project=snapshot.project)
        specialist_run_id = f"specialist-run-{uuid4().hex}"
        round_id = tools.context.round_id or f"agent-round-{parent_run_id}"
        prompt = specialist_system_prompt(
            role,
            project_id=project_id,
            project=snapshot.project,
            workspace_schema=tools.schema_prompt.text,
            project_root=self.services.projects.project_root(project_id),
            target_refs=delegated.target_refs,
        )
        record_metadata: dict[str, Any] = {"parentActionId": parent_action_id}
        if request.source == "review_rejection_feedback":
            record_metadata.update(
                {
                    "reviewId": request.metadata.get("reviewId"),
                    "reviewDecisionId": request.metadata.get("decisionId"),
                    "rejectionFeedback": request.metadata.get(
                        "rejectionFeedback",
                    ),
                },
            )
        record = SpecialistRunRecord(
            run_id=specialist_run_id,
            project_id=project_id,
            round_id=round_id,
            role=role,
            target_refs=list(delegated.target_refs),
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            related_run_id=parent_run_id,
            prompt_spec_id=f"file_project_json.{role_name}.v1",
            caused_by_request_id=tools.context.caused_by_request_id,
            caused_by_message_id=request.message_id,
            caused_by_message_seq=request.message_seq,
            review_policy=tools.context.review_policy,
            metadata=record_metadata,
        )
        await asyncio.to_thread(self.executions.create_specialist_run, record)
        common = {
            "parentActionId": parent_action_id,
            "parentRunId": parent_run_id,
            "runId": specialist_run_id,
            "role": role_name,
            "displayName": role_name,
            "targetRefs": list(delegated.target_refs),
        }
        await self._event(
            project_id,
            session_id,
            "subagent.accepted",
            parent_run_id,
            request,
            {**common, "task": delegated.task},
        )
        await asyncio.to_thread(
            self.executions.transition_specialist_run,
            project_id,
            specialist_run_id,
            expected_status=SpecialistRunStatus.QUEUED,
            status=SpecialistRunStatus.RUNNING_MODEL,
        )
        await self._event(
            project_id,
            session_id,
            "subagent.started",
            parent_run_id,
            request,
            common,
        )

        user_text = (
            f"父任务的用户原始要求：\n{_message_text(request)}\n\n"
            f"本次委派：\n{delegated.task}\n\n"
            f"目标对象：{', '.join(delegated.target_refs)}"
        )
        feedback_constraint = _review_feedback_constraint(request)
        if feedback_constraint:
            user_text += "\n\n" + feedback_constraint
        native_media_parts: list[dict[str, Any]] = []
        if role is SpecialistRole.SOURCE_INTELLIGENCE:
            native_media_parts = await source_intelligence_content_parts(
                self.services,
                project_id=project_id,
                request=request,
                target_refs=delegated.target_refs,
            )
            user_text += (
                "\n\n本消息附有本次委派需要观察的全部原生图片/视频，"
                f"共 {len(native_media_parts)} 份。必须基于这些原生媒体进行观察，"
                "不能把消息中的 URL 文本当作已经完成素材理解。"
            )
            runtime_media_facts = []
            for part in native_media_parts:
                video = part.get("video_url")
                if (
                    isinstance(video, Mapping)
                    and video.get("durationMs") is not None
                ):
                    runtime_media_facts.append(
                        {
                            "assetVersionId": video.get("versionId"),
                            "durationMs": video.get("durationMs"),
                        },
                    )
            if runtime_media_facts:
                user_text += (
                    "\n\nRuntime 已通过本地缓存和 ffprobe 核验以下媒体事实；"
                    "时间段必须落在这些真实时长内：\n"
                    + json.dumps(
                        runtime_media_facts,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
        if role is SpecialistRole.AI_EDITING_DIRECTOR:
            from models.config import get_execution_mode

            execution_mode = get_execution_mode()
            user_text += f"\n\n当前执行模式：{execution_mode}。"
            if execution_mode == "co_creation" and not _timelines_have_plan(
                snapshot.project,
                delegated.target_refs,
            ):
                user_text += (
                    "共创模式且目标 Timeline 尚无 edit_plan：进入方向门——"
                    "先产出 3 个候选创作方向（每个含一句话 concept、三旋钮 "
                    "dials、signature_device 与一句 pitch），首行用 "
                    "[BLOCKED] 列出三卡等待用户选择；用户选定后再把该方向"
                    "作为 edit_plan 底稿继续。用户已在本次消息中明确选择方向"
                    "或要求直接开剪时不重复询问。"
                )
            elif execution_mode == "delegated":
                user_text += (
                    "委派模式：不要中途询问方向或确认，自主完成 edit_plan " "与剪辑，决策写进 edit_plan 即可。"
                )
            elif execution_mode == "fine_tuning":
                user_text += (
                    "微调模式：用户在迭代已交付成片。只确认本次改动范围，"
                    "不重新提方向；修改波及的场景需重新 review_scene。"
                )
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            *native_media_parts,
        ]
        await asyncio.to_thread(
            self.executions.append_specialist_message,
            project_id,
            specialist_run_id,
            message_id=f"specialist-message-{uuid4().hex}",
            role="user",
            content_parts=user_content,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]
        tool_manifest = list(
            self.specialist_tools.manifest_for(
                role,
                admitted_target_refs=delegated.target_refs,
            ),
        )
        tool_call_count = 0
        review_ids: list[str] = []
        malformed_jq_attempts = 0
        malformed_jq_fingerprints: set[str] = set()
        deterministic_failure_counts: dict[str, int] = {}
        try:
            for _turn_number in range(
                1,
                self.specialist_max_model_turns + 2,
            ):
                if _turn_number == self.specialist_max_model_turns + 1:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "MODEL_TURN_BUDGET_FINALIZE: The normal "
                                "specialist tool-turn budget is exhausted. "
                                "Use the latest tool result to return [SUCCESS], "
                                "[BLOCKED], or [FAILED] with a truthful concise "
                                "summary now. Do not call another tool."
                            ),
                        },
                    )
                self._assert_epoch(project_id, parent_run_id, epoch)
                message_id = f"specialist-message-{uuid4().hex}"
                delta_index = 0

                async def message_delta(stream_kind: str, delta: str) -> None:
                    nonlocal delta_index
                    if not delta:
                        return
                    self._assert_epoch(project_id, parent_run_id, epoch)
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.message_delta",
                        parent_run_id,
                        request,
                        {
                            **common,
                            "messageId": message_id,
                            "deltaIndex": delta_index,
                            "delta": delta,
                            "streamKind": stream_kind,
                        },
                    )
                    delta_index += 1

                async def text_delta(delta: str) -> None:
                    await message_delta("text", delta)

                async def thinking_delta(delta: str) -> None:
                    await message_delta("thinking", delta)

                async def subagent_tool_progress(
                    tool_call_id: str,
                    state: _ToolArgumentProgressState,
                    complete: bool,
                ) -> None:
                    nonlocal delta_index
                    self._assert_epoch(project_id, parent_run_id, epoch)
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.tool_progress",
                        parent_run_id,
                        request,
                        {
                            **common,
                            "messageId": message_id,
                            "toolCallId": tool_call_id,
                            "tool": state.tool,
                            "deltaIndex": delta_index,
                            "receivedBytes": state.received_bytes,
                            "providerChunkCount": state.provider_chunk_count,
                            "complete": complete,
                            "stage": (
                                "arguments_complete"
                                if complete
                                else "assembling_arguments"
                            ),
                        },
                    )
                    delta_index += 1

                model_client = (
                    self.source_model_client
                    if role is SpecialistRole.SOURCE_INTELLIGENCE
                    else self.model_client
                )
                _compact_wire_project_snapshots(messages)
                tool_progress = _ToolArgumentProgressReporter(
                    subagent_tool_progress,
                )
                turn = await self._complete_model_turn(
                    model_client,
                    label=role_name,
                    messages=messages,
                    tools=tool_manifest,
                    on_text_delta=text_delta,
                    on_thinking_delta=thinking_delta,
                    on_tool_call_delta=tool_progress.feed,
                )
                await tool_progress.finish(turn.tool_calls)
                if len(turn.tool_calls) > 1:
                    raise AgentModelError(
                        f"{role_name} returned more than one tool call in one turn",
                    )
                metadata: dict[str, Any] = {
                    "parentActionId": parent_action_id,
                    "providerMessageId": turn.provider_message_id,
                    "providerThinking": turn.thinking,
                    "providerFinishReason": turn.finish_reason,
                    "providerUsage": turn.usage,
                }
                if turn.tool_calls:
                    call = turn.tool_calls[0]
                    metadata["toolCall"] = {
                        "id": call.call_id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                        "transport": _tool_call_transport_metadata(call),
                    }
                await asyncio.to_thread(
                    self.executions.append_specialist_message,
                    project_id,
                    specialist_run_id,
                    message_id=message_id,
                    role="assistant",
                    content_parts=[
                        {"type": "text", "text": turn.content or ""},
                    ],
                    provider_message_id=turn.provider_message_id,
                    metadata=metadata,
                )
                await self._event(
                    project_id,
                    session_id,
                    "subagent.message_completed",
                    parent_run_id,
                    request,
                    {
                        **common,
                        "messageId": message_id,
                        "text": turn.content or "",
                        "finishReason": turn.finish_reason,
                        "usage": turn.usage,
                    },
                )
                assistant_wire: dict[str, Any] = {
                    "role": "assistant",
                    "content": turn.content,
                }
                if turn.tool_calls:
                    assistant_wire["tool_calls"] = [
                        call.history_dict() for call in turn.tool_calls
                    ]
                messages.append(assistant_wire)
                if not turn.tool_calls:
                    if turn.content is None:
                        raise AgentModelError(
                            f"{role_name} returned no final content or tool calls",
                        )
                    try:
                        marker, summary = _specialist_terminal(turn.content)
                    except AgentModelError:
                        correction = (
                            "你的最终回复必须以 [SUCCESS]、[BLOCKED] 或 [FAILED] 开头。"
                            "请重新输出，首行使用正确的标记：\n"
                            "- [SUCCESS]：全部工作已完成并验证\n"
                            "- [BLOCKED]：缺少必要信息或素材\n"
                            "- [FAILED]：遇到不可恢复的技术错误\n"
                            "标记后写简短总结。"
                        )
                        await asyncio.to_thread(
                            self.executions.append_specialist_message,
                            project_id,
                            specialist_run_id,
                            message_id=f"specialist-message-{uuid4().hex}",
                            role="user",
                            content_parts=[
                                {"type": "text", "text": correction},
                            ],
                            metadata={"parentActionId": parent_action_id},
                        )
                        messages.append(
                            {"role": "user", "content": correction},
                        )
                        continue
                    latest = None
                    if (
                        marker == "SUCCESS"
                        and role is SpecialistRole.SOURCE_INTELLIGENCE
                    ):
                        latest = await asyncio.to_thread(
                            self.services.projects.read,
                            project_id,
                        )
                        try:
                            _require_source_intelligence_associations(
                                latest.project,
                                delegated.target_refs,
                            )
                        except FileAgentRuntimeError as error:
                            correction = (
                                "你刚才直接输出了 [SUCCESS]，但没有通过 "
                                "commit_source_intelligence 写入素材理解文件，"
                                f"因此该成功被 Runtime 拒绝：{error}。"
                                "现在禁止再次返回自然语言分析或 [SUCCESS]；"
                                "请把你已经观察到的完整视觉理解转换成工具要求的"
                                "结构化 summary、shots、entities、semanticEntries，"
                                "并在本回合调用 commit_source_intelligence。"
                            )
                            await asyncio.to_thread(
                                self.executions.append_specialist_message,
                                project_id,
                                specialist_run_id,
                                message_id=f"specialist-message-{uuid4().hex}",
                                role="user",
                                content_parts=[
                                    {"type": "text", "text": correction},
                                ],
                                metadata={"parentActionId": parent_action_id},
                            )
                            messages.append(
                                {"role": "user", "content": correction},
                            )
                            continue
                    status = {
                        "SUCCESS": SpecialistRunStatus.SUCCEEDED,
                        "BLOCKED": SpecialistRunStatus.BLOCKED,
                        "FAILED": SpecialistRunStatus.FAILED,
                    }[marker]
                    waiting_review_id: str | None = None
                    if status is SpecialistRunStatus.BLOCKED and review_ids:
                        pending_reviews = await asyncio.to_thread(
                            self.services.reviews.all_pending,
                            project_id,
                        )
                        pending_review_ids = {
                            review.review_id for review in pending_reviews
                        }
                        waiting_review_id = next(
                            (
                                review_id
                                for review_id in reversed(review_ids)
                                if review_id in pending_review_ids
                            ),
                            None,
                        )
                    waiting_for_review = waiting_review_id is not None
                    if waiting_for_review:
                        summary = _specialist_waiting_review_summary(
                            role,
                            delegated.target_refs,
                        )
                    transition_updates: dict[str, Any] = {
                        "final_marker": marker,
                        "final_summary_text": summary,
                    }
                    if waiting_for_review:
                        transition_updates["metadata"] = {
                            **record_metadata,
                            "waitingReview": True,
                            "waitingReviewId": waiting_review_id,
                        }
                    await asyncio.to_thread(
                        self.executions.transition_specialist_run,
                        project_id,
                        specialist_run_id,
                        expected_status=SpecialistRunStatus.RUNNING_MODEL,
                        status=status,
                        updates=transition_updates,
                    )
                    terminal_event = {
                        SpecialistRunStatus.SUCCEEDED: "subagent.completed",
                        SpecialistRunStatus.BLOCKED: "subagent.blocked",
                        SpecialistRunStatus.FAILED: "subagent.failed",
                    }[status]
                    terminal_payload: dict[str, Any] = {
                        **common,
                        "summary": summary,
                    }
                    if waiting_for_review:
                        terminal_payload.update(
                            {
                                "waitingReview": True,
                                "reviewId": waiting_review_id,
                            },
                        )
                    await self._event(
                        project_id,
                        session_id,
                        terminal_event,
                        parent_run_id,
                        request,
                        terminal_payload,
                    )
                    if latest is None:
                        latest = await asyncio.to_thread(
                            self.services.projects.read,
                            project_id,
                        )
                    return {
                        "ok": (
                            status is SpecialistRunStatus.SUCCEEDED
                            or waiting_for_review
                        ),
                        "runId": specialist_run_id,
                        "role": role_name,
                        "status": (
                            "WAITING_REVIEW"
                            if waiting_for_review
                            else status.value
                        ),
                        "waitingReview": waiting_for_review,
                        "summary": summary,
                        "toolCallCount": tool_call_count,
                        "generation": latest.generation,
                        "etag": latest.etag,
                        "reviewId": (
                            waiting_review_id
                            or (review_ids[-1] if review_ids else None)
                        ),
                    }

                call = turn.tool_calls[0]
                tool_call_count += 1
                logger.info(
                    "tool: project=%s run=%s role=%s tool=%s call_id=%s args=%s",
                    project_id,
                    specialist_run_id,
                    role_name,
                    call.name,
                    call.call_id,
                    _prompt_preview(call.arguments, limit=200),
                )
                await self._event(
                    project_id,
                    session_id,
                    "subagent.tool_started",
                    parent_run_id,
                    request,
                    {
                        **common,
                        "messageId": message_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "arguments": dict(call.arguments),
                        "rawArgumentsBytes": call.raw_arguments_bytes,
                        "providerChunkCount": call.provider_chunk_count,
                        "argumentsRepaired": call.arguments_repaired,
                        "finishReason": turn.finish_reason,
                    },
                )
                failed = False
                malformed_budget_exhausted = False
                repeated_failure_exhausted = False
                waiting_review: ReviewPendingError | None = None
                try:
                    if call.parse_error is not None:
                        raise ToolArgumentsJSONError(call.parse_error)
                    if call.name == JQ_PROJECT_TOOL_NAME:
                        diagnosis = _jq_project_argument_diagnosis(call)
                        next_attempt = (
                            0
                            if diagnosis.safe_to_execute
                            else malformed_jq_attempts + 1
                        )
                        await self._event(
                            project_id,
                            session_id,
                            "subagent.tool_arguments_checked",
                            parent_run_id,
                            request,
                            {
                                **common,
                                "messageId": message_id,
                                "toolCallId": call.call_id,
                                "tool": call.name,
                                "malformedAttempt": next_attempt,
                                **diagnosis.event_payload(),
                            },
                        )
                        if not diagnosis.safe_to_execute:
                            malformed_jq_attempts = next_attempt
                            repeated_payload = (
                                diagnosis.fingerprint
                                in malformed_jq_fingerprints
                            )
                            malformed_jq_fingerprints.add(
                                diagnosis.fingerprint,
                            )
                            raise MalformedJqProjectArguments(
                                diagnosis,
                                attempt=malformed_jq_attempts,
                                repeated_payload=repeated_payload,
                            )
                        malformed_jq_attempts = 0
                        malformed_jq_fingerprints.clear()
                    if call.arguments.get("projectId") != project_id:
                        raise FileAgentRuntimeError(
                            "specialist tool call attempted another Project",
                        )
                    result = await self._invoke_specialist_tool(
                        project_id=project_id,
                        session_id=session_id,
                        parent_run_id=parent_run_id,
                        specialist_run_id=specialist_run_id,
                        round_id=round_id,
                        role=role,
                        admitted_target_refs=delegated.target_refs,
                        epoch=epoch,
                        request=request,
                        common=common,
                        call_id=call.call_id,
                        assistant_message_id=message_id,
                        provider_message_id=turn.provider_message_id,
                        name=call.name,
                        arguments=call.arguments,
                        tools=tools,
                    )
                    review_id = result.get("reviewId")
                    if (
                        isinstance(review_id, str)
                        and review_id
                        and review_id not in review_ids
                    ):
                        review_ids.append(review_id)
                    if call.name in {"jq_project", "patch_project"}:
                        await self._workspace_changed(
                            project_id,
                            session_id,
                            parent_run_id,
                            request,
                            result,
                            action_id=call.call_id,
                            specialist=common,
                        )
                except (asyncio.CancelledError, StaleAgentRun):
                    raise
                except Exception as exc:
                    if isinstance(exc, ReviewPendingError):
                        waiting_review = exc
                        review_id = exc.details.get("reviewId")
                        logger.info(
                            "review required: project=%s run=%s role=%s "
                            "tool=%s call_id=%s review_id=%s target=%s",
                            project_id,
                            specialist_run_id,
                            role_name,
                            call.name,
                            call.call_id,
                            review_id,
                            exc.details.get("targetRef"),
                        )
                        if (
                            isinstance(review_id, str)
                            and review_id
                            and review_id not in review_ids
                        ):
                            review_ids.append(review_id)
                        result = {
                            "ok": True,
                            "status": "WAITING_REVIEW",
                            "message": exc.message,
                            **exc.details,
                        }
                    elif isinstance(exc, MalformedJqProjectArguments):
                        failed = True
                        result = exc.tool_result()
                        malformed_budget_exhausted = (
                            exc.attempt > MAX_MALFORMED_JQ_PROJECT_RETRIES
                        )
                    else:
                        failed = True
                        failure_fingerprint = (
                            _deterministic_tool_failure_fingerprint(
                                call,
                                exc,
                            )
                        )
                        if failure_fingerprint is not None:
                            failure_count = (
                                deterministic_failure_counts.get(
                                    failure_fingerprint,
                                    0,
                                )
                                + 1
                            )
                            deterministic_failure_counts[
                                failure_fingerprint
                            ] = failure_count
                            repeated_failure_exhausted = (
                                failure_count
                                >= MAX_REPEATED_DETERMINISTIC_TOOL_FAILURES
                            )
                        result = _tool_failure_result(
                            call.name,
                            exc,
                            recovery=(
                                exc.recovery()
                                if isinstance(
                                    exc,
                                    CreationCheckpointBlocked,
                                )
                                else None
                            ),
                        )
                await asyncio.to_thread(
                    self.executions.append_specialist_message,
                    project_id,
                    specialist_run_id,
                    message_id=f"specialist-message-{uuid4().hex}",
                    role="tool",
                    content_parts=[
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False),
                        },
                    ],
                    metadata={
                        "parentActionId": parent_action_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "failed": failed,
                    },
                )
                await self._event(
                    project_id,
                    session_id,
                    "subagent.tool_completed",
                    parent_run_id,
                    request,
                    {
                        **common,
                        "messageId": message_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "failed": failed,
                        "result": result,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "failed": failed,
                    },
                )
                if (
                    call.name in _VIDEO_FRAME_TOOL_NAMES
                    and not failed
                    and not result.get("background")
                ):
                    # Extracted source frames enter the specialist context
                    # as native images interleaved with timestamps, via the
                    # same mechanism as read_document page images. Frames
                    # arrive either directly (synchronous read) or nested
                    # in the per-task entries of a harvest result.
                    frame_content: list[dict[str, Any]] = []
                    frame_sources: list[dict[str, Any]] = [result]
                    frame_sources.extend(
                        entry
                        for entry in result.get("tasks") or []
                        if isinstance(entry, dict)
                    )
                    try:
                        frame_parts = []
                        for frame_source in frame_sources:
                            frame_parts.extend(
                                await video_frame_content_parts(
                                    self.services,
                                    project_id=project_id,
                                    task_result=frame_source,
                                ),
                            )
                    except (asyncio.CancelledError, StaleAgentRun):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        frame_parts = []
                        frame_content = [
                            {
                                "type": "text",
                                "text": (
                                    "视频帧图注入失败，请基于工具返回的" f"摘要继续或缩小窗口重试：{exc}"
                                ),
                            },
                        ]
                    if frame_parts:
                        frame_note = (
                            "以下是 read_source_video 抽取的帧序列，每帧前"
                            "一行是它在源素材中的时间戳；请直接观察帧内容，"
                            "需看连续动态细节时对命中时段改用 "
                            "observe_source_clip。"
                        )
                        frame_content = [
                            {"type": "text", "text": frame_note},
                            *frame_parts,
                        ]
                    if frame_content:
                        await asyncio.to_thread(
                            self.executions.append_specialist_message,
                            project_id,
                            specialist_run_id,
                            message_id=f"specialist-message-{uuid4().hex}",
                            role="user",
                            content_parts=frame_content,
                            metadata={
                                "parentActionId": parent_action_id,
                                "videoFramesForToolCallId": call.call_id,
                            },
                        )
                        messages.append(
                            {"role": "user", "content": frame_content},
                        )
                if call.name == "read_document" and not failed:
                    # Rendered pages enter the VLM context as native images
                    # via the existing multimodal user-message mechanism.
                    page_content: list[dict[str, Any]] = []
                    try:
                        page_parts = await document_page_content_parts(
                            self.services,
                            project_id=project_id,
                            tool_result=result,
                        )
                    except (asyncio.CancelledError, StaleAgentRun):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        page_parts = []
                        page_content = [
                            {
                                "type": "text",
                                "text": ("文档页图注入失败，请基于工具返回的" f"文本摘要继续：{exc}"),
                            },
                        ]
                    if page_parts:
                        page_note = (
                            f"以下是 read_document 渲染的 {len(page_parts)} 张"
                            "文档页图，按页序排列；请直接观察页图内容，"
                            "结合工具返回的文本摘要形成文档理解。"
                        )
                        page_content = [
                            {"type": "text", "text": page_note},
                            *page_parts,
                        ]
                    if page_content:
                        await asyncio.to_thread(
                            self.executions.append_specialist_message,
                            project_id,
                            specialist_run_id,
                            message_id=f"specialist-message-{uuid4().hex}",
                            role="user",
                            content_parts=page_content,
                            metadata={
                                "parentActionId": parent_action_id,
                                "documentPagesForToolCallId": call.call_id,
                            },
                        )
                        messages.append(
                            {"role": "user", "content": page_content},
                        )
                if waiting_review is not None:
                    target_ref = str(
                        waiting_review.details.get("targetRef") or "当前目标",
                    )
                    command_type = str(
                        waiting_review.details.get("commandType") or "",
                    )
                    if command_type == "GENERATE_R2V_VIDEO":
                        summary = _specialist_waiting_review_summary(
                            role,
                            [target_ref],
                        )
                    else:
                        summary = (
                            f"{target_ref} 的前置产物已生成，"
                            "本步骤尚未开始。请先完成审阅；"
                            "审阅通过后，主线需重新委派同一目标以继续。"
                        )
                    waiting_metadata = {
                        **record_metadata,
                        "waitingReview": True,
                        "waitingReviewId": waiting_review.details.get(
                            "reviewId",
                        ),
                        "waitingArtifactVersionId": (
                            waiting_review.details.get("artifactVersionId")
                        ),
                    }
                    await asyncio.to_thread(
                        self.executions.transition_specialist_run,
                        project_id,
                        specialist_run_id,
                        expected_status=SpecialistRunStatus.RUNNING_MODEL,
                        status=SpecialistRunStatus.BLOCKED,
                        updates={
                            "final_marker": "BLOCKED",
                            "final_summary_text": summary,
                            "metadata": waiting_metadata,
                        },
                    )
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.blocked",
                        parent_run_id,
                        request,
                        {
                            **common,
                            "summary": summary,
                            "waitingReview": True,
                            "reviewId": waiting_review.details.get(
                                "reviewId",
                            ),
                            "artifactVersionId": waiting_review.details.get(
                                "artifactVersionId",
                            ),
                        },
                    )
                    latest = await asyncio.to_thread(
                        self.services.projects.read,
                        project_id,
                    )
                    return {
                        "ok": True,
                        "runId": specialist_run_id,
                        "role": role_name,
                        "status": "WAITING_REVIEW",
                        "waitingReview": True,
                        "summary": summary,
                        "toolCallCount": tool_call_count,
                        "generation": latest.generation,
                        "etag": latest.etag,
                        "reviewId": waiting_review.details.get("reviewId"),
                    }
                if malformed_budget_exhausted:
                    raise RepeatedDeterministicToolFailure(
                        "jq_project produced structurally corrupted tool "
                        "arguments after 2 bounded retries; the specialist "
                        "stopped before jq execution",
                    )
                if repeated_failure_exhausted:
                    raise RepeatedDeterministicToolFailure(
                        f"{role_name} repeated the same non-retryable "
                        f"{call.name} failure twice without changing its "
                        "arguments; the specialist stopped instead of "
                        "starting another model turn",
                    )
            raise AgentModelError(
                f"{role_name} exceeded "
                f"{self.specialist_max_model_turns} model turns",
            )
        except (asyncio.CancelledError, StaleAgentRun):
            logger.warning(
                "Specialist run %s (%s) cancelled",
                specialist_run_id,
                role.value,
            )
            if not self.services.projects.project_path(project_id).is_file():
                # Project DELETE is already the terminal authority; do not let
                # specialist cleanup recreate Runtime directories below the
                # removed id.
                raise
            await asyncio.to_thread(
                self.executions.transition_specialist_run,
                project_id,
                specialist_run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.CANCELLED,
                updates={"final_marker": "CANCELLED"},
            )
            # Emit subagent.failed so the frontend can disarm.
            await self._event(
                project_id,
                session_id,
                "subagent.failed",
                parent_run_id,
                request,
                {
                    **common,
                    "cancelled": True,
                    "error": "specialist run cancelled",
                },
            )
            raise
        except Exception as exc:
            logger.error(
                "Specialist run %s (%s) failed: %s: %s",
                specialist_run_id,
                role.value,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            await asyncio.to_thread(
                self.executions.transition_specialist_run,
                project_id,
                specialist_run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.FAILED,
                updates={
                    "final_marker": "FAILED",
                    "final_summary_text": f"{type(exc).__name__}: {exc}",
                },
            )
            await self._event(
                project_id,
                session_id,
                "subagent.failed",
                parent_run_id,
                request,
                {**common, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise

    async def _invoke_specialist_tool(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        specialist_run_id: str,
        round_id: str,
        role: SpecialistRole,
        admitted_target_refs: list[str],
        epoch: int,
        request: CreatorMessageRecord,
        common: Mapping[str, Any],
        call_id: str,
        assistant_message_id: str,
        provider_message_id: str | None,
        name: str,
        arguments: Mapping[str, Any],
        tools: AgentProjectTools,
    ) -> dict[str, Any]:
        """Invoke one role-owned tool through generic guard/wait protocols."""

        arguments, feedback_applied = _apply_review_feedback_to_tool_arguments(
            request,
            name=name,
            arguments=arguments,
        )
        spec = self.specialist_tools.spec_for(role, name)
        authorization_id: str | None = None
        if spec is not None:
            await self._require_creation_checkpoints(
                project_id=project_id,
                session_id=session_id,
                parent_run_id=parent_run_id,
                specialist_run_id=specialist_run_id,
                round_id=round_id,
                epoch=epoch,
                request=request,
                common=common,
                call_id=call_id,
                spec=spec,
                role=role,
                tools=tools,
            )
        if spec is not None and spec.name == "s2v_generation":
            # Free wan2.2-s2v-detect gate: an unsuitable portrait must fail
            # with a readable error before the billed submission — and, in
            # required-authorization mode, before any execution
            # authorization is created (the detect call itself is free).
            from services.media_files.r2v_execution import (
                preflight_s2v_face_detect,
            )

            inner_arguments = arguments.get("arguments")
            await preflight_s2v_face_detect(
                self.services,
                project_id=project_id,
                arguments=(
                    inner_arguments
                    if isinstance(inner_arguments, Mapping)
                    else {}
                ),
            )
        if (
            spec is not None
            and spec.requires_execution_authorization
            and get_execution_authorization_mode()
            != EXECUTION_AUTHORIZATION_ALLOW_ALL
        ):
            authorization_id = await self._await_execution_authorization(
                project_id=project_id,
                session_id=session_id,
                parent_run_id=parent_run_id,
                specialist_run_id=specialist_run_id,
                round_id=round_id,
                epoch=epoch,
                request=request,
                common=common,
                call_id=call_id,
                spec=spec,
                arguments=arguments,
                tools=tools,
            )
            authorization = await asyncio.to_thread(
                self.executions.get_execution_authorization,
                project_id,
                authorization_id,
            )
            active_provider, active_model = _execution_provider_model(
                spec,
                (
                    arguments.get("arguments")
                    if isinstance(arguments.get("arguments"), Mapping)
                    else {}
                ),
            )
            if (
                active_provider != authorization.requested_provider
                or active_model != authorization.requested_model
            ):
                raise FileAgentRuntimeError(
                    "execution model configuration changed after authorization; "
                    "request a new authorization",
                )
            # The billing terms must still be the approved ones: a video_edit
            # input whose duration only became probeable while the user was
            # deciding would otherwise be billed on a length nobody approved.
            approved_parameters = (
                authorization.scope.get("parameters")
                if isinstance(authorization.scope, Mapping)
                else None
            )
            if isinstance(approved_parameters, Mapping):
                active_billing = await self._billing_arguments(
                    spec,
                    project_id=project_id,
                    tool_arguments=(
                        dict(arguments.get("arguments"))
                        if isinstance(arguments.get("arguments"), Mapping)
                        else {}
                    ),
                )
                drifted = [
                    key
                    for key in _BILLING_SENSITIVE_ARGUMENTS
                    if key in active_billing
                    and approved_parameters.get(key) != active_billing[key]
                ]
                if drifted:
                    raise FileAgentRuntimeError(
                        "billing terms changed after authorization "
                        f"({', '.join(drifted)}): "
                        + ", ".join(
                            f"{key} {approved_parameters.get(key)!r} -> "
                            f"{active_billing[key]!r}"
                            for key in drifted
                        )
                        + "; request a new authorization",
                    )

        waiting_runtime = bool(spec and spec.long_running)
        if waiting_runtime:
            await asyncio.to_thread(
                self.executions.transition_specialist_run,
                project_id,
                specialist_run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.WAITING_RUNTIME,
            )
            await self._event(
                project_id,
                session_id,
                "subagent.waiting_runtime",
                parent_run_id,
                request,
                {**dict(common), "toolCallId": call_id, "tool": name},
            )
        try:
            idempotency_key = _specialist_tool_invocation_id(
                specialist_run_id,
                name,
                arguments,
                call_id=call_id,
            )
            invoked = await self.specialist_tools.invoke(
                role=role,
                name=name,
                arguments=arguments,
                project_id=project_id,
                admitted_target_refs=admitted_target_refs,
                project_tools=tools,
                idempotency_key=idempotency_key,
                context=SourceAgentToolContext(
                    specialist_run_id=specialist_run_id,
                    tool_call_id=call_id,
                    assistant_message_id=assistant_message_id,
                    provider_message_id=provider_message_id,
                    provider=(
                        "configured_vlm"
                        if role is SpecialistRole.SOURCE_INTELLIGENCE
                        else "configured_text"
                    ),
                    model=(
                        get_vlm_model_name()
                        if role is SpecialistRole.SOURCE_INTELLIGENCE
                        else get_text_model_name()
                    ),
                ),
            )
            result = dict(invoked.payload)
            tool_payload = _nested_tool_payload(arguments)
            background_requested = bool(
                spec is not None
                and spec.background_capable
                and tool_payload.get("background"),
            )
            if (
                spec is not None
                and spec.wait is SpecialistToolWait.TASK
                and background_requested
            ):
                # Host-style async submit: hand the task id back now and
                # let the model harvest via check_observation_tasks.
                result["background"] = True
            elif spec is not None and spec.wait is SpecialistToolWait.TASK:
                if not invoked.task_id:
                    raise FileAgentRuntimeError(
                        f"{name} declared Task wait without a task id",
                    )
                task = await self._await_specialist_task(
                    project_id=project_id,
                    parent_run_id=parent_run_id,
                    epoch=epoch,
                    task_id=invoked.task_id,
                )
                result.update(
                    {
                        "status": task.status.value,
                        "taskId": task.task_id,
                        "outputRefs": list(task.output_refs),
                        "result": task.result,
                    },
                )
            elif (
                spec is not None
                and spec.wait is SpecialistToolWait.TASK_LIST
                and invoked.task_ids
                and tool_payload.get("wait", True)
            ):
                result["tasks"] = await self._await_specialist_tasks(
                    project_id=project_id,
                    parent_run_id=parent_run_id,
                    epoch=epoch,
                    task_ids=invoked.task_ids,
                )
            if authorization_id is not None:
                result["executionAuthorizationId"] = authorization_id
            if feedback_applied:
                result["reviewFeedbackApplied"] = True
                result["reviewDecisionId"] = request.metadata.get(
                    "decisionId",
                )
            return result
        finally:
            if waiting_runtime:
                current = await asyncio.to_thread(
                    self.executions.get_specialist_run,
                    project_id,
                    specialist_run_id,
                )
                if current.status is SpecialistRunStatus.WAITING_RUNTIME:
                    await asyncio.to_thread(
                        self.executions.transition_specialist_run,
                        project_id,
                        specialist_run_id,
                        expected_status=SpecialistRunStatus.WAITING_RUNTIME,
                        status=SpecialistRunStatus.RUNNING_MODEL,
                    )
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.continuation_started",
                        parent_run_id,
                        request,
                        {**dict(common), "toolCallId": call_id, "tool": name},
                    )

    async def _require_creation_checkpoints(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        specialist_run_id: str,
        round_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        common: Mapping[str, Any],
        call_id: str,
        spec: SpecialistToolSpec,
        role: SpecialistRole,
        tools: AgentProjectTools,
    ) -> None:
        """Block costly generation until the user cleared each pit stop.

        The gate lives here, in deterministic tool admission, so a model
        cannot skip a checkpoint by forgetting to ask. Each phase is one
        durable approval per Project: once cleared, later calls pass
        without prompting again.
        """

        if get_creation_checkpoint_mode() != CREATION_CHECKPOINT_REQUIRED:
            return
        for phase in required_checkpoint_phases(spec.name, role):
            authorization = await self._creation_checkpoint_record(
                project_id=project_id,
                round_id=round_id,
                specialist_run_id=specialist_run_id,
                request=request,
                call_id=call_id,
                parent_run_id=parent_run_id,
                phase=phase,
                tools=tools,
            )
            if authorization.status is ExecutionAuthorizationStatus.APPROVED:
                continue
            if authorization.status is ExecutionAuthorizationStatus.PENDING:
                logger.info(
                    "approval required: project=%s run=%s role=%s tool=%s "
                    "phase=%s call_id=%s operation=%s summary=%s",
                    project_id,
                    specialist_run_id,
                    common.get("role"),
                    spec.name,
                    phase,
                    call_id,
                    authorization.operation,
                    authorization.summary,
                )
                await self._event(
                    project_id,
                    session_id,
                    "creation.checkpoint_required",
                    parent_run_id,
                    request,
                    {
                        **dict(common),
                        "authorizationId": authorization.authorization_id,
                        "authorizationToken": (
                            authorization.authorization_token
                        ),
                        "checkpointPhase": phase,
                        "operation": authorization.operation,
                        "summary": authorization.summary,
                        "toolCallId": call_id,
                        "tool": spec.name,
                    },
                )
                authorization = await self._await_authorization_decision(
                    project_id=project_id,
                    session_id=session_id,
                    parent_run_id=parent_run_id,
                    specialist_run_id=specialist_run_id,
                    epoch=epoch,
                    request=request,
                    common=common,
                    call_id=call_id,
                    authorization=authorization,
                    decided_event="creation.checkpoint_decided",
                    decided_payload={"checkpointPhase": phase},
                )
                logger.info(
                    "approval decided: project=%s run=%s role=%s "
                    "tool=%s phase=%s call_id=%s status=%s",
                    project_id,
                    specialist_run_id,
                    common.get("role"),
                    spec.name,
                    phase,
                    call_id,
                    authorization.status.value,
                )
            if (
                authorization.status
                is not ExecutionAuthorizationStatus.APPROVED
            ):
                raise CreationCheckpointBlocked(phase, authorization.status)

    async def _creation_checkpoint_record(
        self,
        *,
        project_id: str,
        round_id: str,
        specialist_run_id: str,
        request: CreatorMessageRecord,
        call_id: str,
        parent_run_id: str,
        phase: str,
        tools: AgentProjectTools,
    ) -> ExecutionAuthorizationRecord:
        """Read this Project's checkpoint approval, creating it on demand.

        Rejected attempts stay behind as terminal audit records; the next
        generation call opens a fresh attempt so the user can approve the
        revised plan or designs instead of being locked out forever.
        """

        attempt = 0
        while True:
            authorization_id = checkpoint_authorization_id(
                project_id,
                phase,
                attempt,
            )
            try:
                record = await asyncio.to_thread(
                    self.executions.get_execution_authorization,
                    project_id,
                    authorization_id,
                )
            except RecordNotFoundError:
                break
            if record.status not in (
                ExecutionAuthorizationStatus.REJECTED,
                ExecutionAuthorizationStatus.EXPIRED,
            ):
                return record
            attempt += 1
        candidate = ExecutionAuthorizationRecord(
            authorization_id=authorization_id,
            project_id=project_id,
            round_id=round_id,
            run_id=specialist_run_id,
            execution_request_id=checkpoint_execution_request_id(
                project_id,
                phase,
                attempt,
            ),
            operation=checkpoint_operation(phase),
            target_scope=[f"project:{project_id}"],
            authorization_token=secrets.token_urlsafe(32),
            summary=checkpoint_summary(phase),
            scope={
                "operation": checkpoint_operation(phase),
                "checkpointPhase": phase,
                "message": checkpoint_summary(phase),
            },
            # The decision-tray card echoes provider/model back on approve,
            # and the API requires them to match the request exactly.
            requested_provider=CHECKPOINT_PROVIDER,
            requested_model=checkpoint_label(phase),
            requested_candidates=1,
            caused_by_request_id=tools.context.caused_by_request_id,
            caused_by_message_id=request.message_id,
            caused_by_message_seq=request.message_seq,
            review_policy=tools.context.review_policy,
            metadata={"toolCallId": call_id, "parentRunId": parent_run_id},
        )
        try:
            return await asyncio.to_thread(
                self.executions.create_execution_authorization,
                candidate,
            )
        except ExecutionStoreError:
            # A concurrent run created the same checkpoint first; its
            # record is the authority.
            return await asyncio.to_thread(
                self.executions.get_execution_authorization,
                project_id,
                authorization_id,
            )

    async def _await_authorization_decision(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        specialist_run_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        common: Mapping[str, Any],
        call_id: str,
        authorization: ExecutionAuthorizationRecord,
        decided_event: str = "execution.authorization_decided",
        decided_payload: Mapping[str, Any] | None = None,
    ) -> ExecutionAuthorizationRecord:
        """Park the Specialist run until a persisted approval is decided."""

        await asyncio.to_thread(
            self.executions.transition_specialist_run,
            project_id,
            specialist_run_id,
            expected_status=SpecialistRunStatus.RUNNING_MODEL,
            status=SpecialistRunStatus.WAITING_AUTHORIZATION,
        )
        try:
            while authorization.status is ExecutionAuthorizationStatus.PENDING:
                self._assert_epoch(project_id, parent_run_id, epoch)
                await asyncio.sleep(min(self.poll_interval_seconds, 0.5))
                authorization = await asyncio.to_thread(
                    self.executions.get_execution_authorization,
                    project_id,
                    authorization.authorization_id,
                )
        finally:
            current = await asyncio.to_thread(
                self.executions.get_specialist_run,
                project_id,
                specialist_run_id,
            )
            if current.status is SpecialistRunStatus.WAITING_AUTHORIZATION:
                await asyncio.to_thread(
                    self.executions.transition_specialist_run,
                    project_id,
                    specialist_run_id,
                    expected_status=SpecialistRunStatus.WAITING_AUTHORIZATION,
                    status=SpecialistRunStatus.RUNNING_MODEL,
                )
        await self._event(
            project_id,
            session_id,
            decided_event,
            parent_run_id,
            request,
            {
                **dict(common),
                **dict(decided_payload or {}),
                "authorizationId": authorization.authorization_id,
                "status": authorization.status.value,
                "toolCallId": call_id,
            },
        )
        return authorization

    async def _billing_arguments(
        self,
        spec: SpecialistToolSpec,
        *,
        project_id: str,
        tool_arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Tool arguments adjusted so the estimate matches what is billed.

        ``video_edit`` ignores the tool's ``durationSeconds``: the provider
        bills the input video's own length (truncated to its documented
        keep-window), so the estimate reads that duration from the exact
        version instead of the requested one.
        """

        arguments = dict(tool_arguments)
        if spec.provider_kind != "video":
            return arguments
        if str(arguments.get("mode") or "").strip().casefold() != "video_edit":
            return arguments
        video_ref = str(arguments.get("videoRef") or "").strip()
        if not video_ref:
            return arguments
        from models.video_capabilities import (
            HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS,
        )
        from services.media_files.r2v_execution import (
            effective_video_duration_seconds,
        )

        try:
            snapshot = await asyncio.to_thread(
                self.services.projects.read,
                project_id,
            )
            # Same resolver execution uses, so a probed-only asset is priced
            # and authorized on the duration it will actually be billed for.
            duration = await asyncio.to_thread(
                effective_video_duration_seconds,
                snapshot.project,
                self.services.projects.project_root(project_id),
                video_ref,
            )
        # Expected resolution failures (missing version, unreadable
        # metadata) fall back to "unknown duration", which surfaces as a
        # readable ValidationError below. Programming errors must propagate
        # instead of masquerading as a bad user request.
        except (CreatorError, ValueError, OSError) as error:
            logger.warning(
                "could not resolve the video_edit input duration | "
                "project=%s ref=%s: %s",
                project_id,
                video_ref,
                error,
            )
            duration = None
        if not duration:
            # Never offer an approvable price for terms we cannot verify:
            # execution rejects an unknown video_edit length anyway, so fail
            # here instead of authorizing the unverified requested duration.
            raise ValidationError(
                "无法确定 videoRef 的时长，video_edit 按输入视频计费，"
                "因此无法给出可批准的费用；请重新引入该视频以补齐元数据后重试",
            )
        arguments["durationSeconds"] = min(
            HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS,
            max(1, round(duration)),
        )
        return arguments

    async def _await_execution_authorization(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        specialist_run_id: str,
        round_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        common: Mapping[str, Any],
        call_id: str,
        spec: SpecialistToolSpec,
        arguments: Mapping[str, Any],
        tools: AgentProjectTools,
    ) -> str:
        execution_request_id = _specialist_tool_request_id(
            specialist_run_id,
            spec.name,
            arguments,
        )
        # The approval identity is target-scoped (tool name + arguments),
        # not run-scoped: a re-delegated Specialist retrying the same
        # generation (e.g. its predecessor was interrupted by a review
        # decision while parked on this very approval) must reuse the
        # pending/approved record instead of asking the user to confirm the
        # same call again. Rejected/expired attempts stay behind as terminal
        # audit records and the next call opens a fresh attempt, mirroring
        # creation checkpoints.
        request_digest = hashlib.sha256(
            "\0".join(
                (
                    spec.name,
                    json.dumps(
                        dict(arguments),
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            ).encode("utf-8"),
        ).hexdigest()
        attempt = 0
        existing: ExecutionAuthorizationRecord | None = None
        while True:
            authorization_id = (
                "authorization-"
                + uuid5(
                    NAMESPACE_URL,
                    "qwenpaw-creator:file-tool-authorization:"
                    f"{project_id}:{request_digest}:{attempt}",
                ).hex
            )
            try:
                record = await asyncio.to_thread(
                    self.executions.get_execution_authorization,
                    project_id,
                    authorization_id,
                )
            except RecordNotFoundError:
                break
            if record.status in (
                ExecutionAuthorizationStatus.REJECTED,
                ExecutionAuthorizationStatus.EXPIRED,
            ):
                attempt += 1
                continue
            existing = record
            break
        if (
            existing is not None
            and existing.status is ExecutionAuthorizationStatus.APPROVED
        ):
            logger.info(
                "approval reused: project=%s run=%s role=%s tool=%s "
                "call_id=%s authorization=%s",
                project_id,
                specialist_run_id,
                common.get("role"),
                spec.name,
                call_id,
                existing.authorization_id,
            )
            return existing.authorization_id
        target_ref = str(arguments.get("targetRef") or "project:unknown")
        tool_arguments = dict(arguments.get("arguments") or {})
        provider, model = _execution_provider_model(spec, tool_arguments)
        if existing is not None:
            # A pending approval for the same call already exists (created by
            # an interrupted predecessor run): park on it instead of opening
            # a duplicate decision card.
            authorization = existing
        else:
            # What the provider will actually bill: video_edit follows its
            # input video, not the requested durationSeconds. The user must
            # approve those effective terms, so summary and scope both read
            # them (upstream dropped the local price estimate entirely).
            billing_arguments = await self._billing_arguments(
                spec,
                project_id=project_id,
                tool_arguments=tool_arguments,
            )
            adjusted_parameters = {
                key: value
                for key, value in billing_arguments.items()
                if tool_arguments.get(key) != value
            }
            record = ExecutionAuthorizationRecord(
                authorization_id=authorization_id,
                project_id=project_id,
                round_id=round_id,
                run_id=specialist_run_id,
                execution_request_id=execution_request_id,
                operation=spec.name,
                target_scope=[target_ref],
                authorization_token=secrets.token_urlsafe(32),
                summary=_authorization_summary(
                    spec,
                    target_ref=target_ref,
                    provider=provider,
                    model=model,
                    tool_arguments=billing_arguments,
                ),
                scope={
                    "operation": spec.name,
                    "targetRefs": [target_ref],
                    "parameters": billing_arguments,
                    # Keep the literal tool request when it differs, so the
                    # approval record shows both what was asked and what is
                    # billed.
                    **(
                        {"requestedParameters": tool_arguments}
                        if adjusted_parameters
                        else {}
                    ),
                    "promptPreview": _prompt_preview(
                        tool_arguments,
                        limit=200,
                    ),
                },
                requested_provider=provider,
                requested_model=model,
                requested_candidates=1,
                caused_by_request_id=tools.context.caused_by_request_id,
                caused_by_message_id=request.message_id,
                caused_by_message_seq=request.message_seq,
                review_policy=tools.context.review_policy,
                metadata={"toolCallId": call_id, "parentRunId": parent_run_id},
            )
            authorization = await asyncio.to_thread(
                self.executions.create_execution_authorization,
                record,
            )
        await self._event(
            project_id,
            session_id,
            "execution.authorization_required",
            parent_run_id,
            request,
            {
                **dict(common),
                "authorizationId": authorization.authorization_id,
                "authorizationToken": authorization.authorization_token,
                "executionRequestId": authorization.execution_request_id,
                "operation": authorization.operation,
                "targetRef": target_ref,
                "provider": provider,
                "model": model,
                "summary": authorization.summary,
                "toolCallId": call_id,
            },
        )
        logger.info(
            "approval required: project=%s run=%s role=%s tool=%s call_id=%s "
            "operation=%s target=%s provider=%s/%s summary=%s",
            project_id,
            specialist_run_id,
            common.get("role"),
            spec.name,
            call_id,
            authorization.operation,
            target_ref,
            provider,
            model,
            authorization.summary,
        )
        authorization = await self._await_authorization_decision(
            project_id=project_id,
            session_id=session_id,
            parent_run_id=parent_run_id,
            specialist_run_id=specialist_run_id,
            epoch=epoch,
            request=request,
            common=common,
            call_id=call_id,
            authorization=authorization,
        )
        logger.info(
            "approval decided: project=%s run=%s role=%s tool=%s call_id=%s status=%s",
            project_id,
            specialist_run_id,
            common.get("role"),
            spec.name,
            call_id,
            authorization.status.value,
        )
        if authorization.status is not ExecutionAuthorizationStatus.APPROVED:
            raise FileAgentRuntimeError(
                f"execution authorization {authorization.status.value.lower()}",
            )
        return authorization.authorization_id

    async def _await_specialist_task(
        self,
        *,
        project_id: str,
        parent_run_id: str,
        epoch: int,
        task_id: str,
    ) -> Any:
        while True:
            self._assert_epoch(project_id, parent_run_id, epoch)
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task_id,
            )
            if task.status is TaskStatus.SUCCEEDED:
                return task
            if task.status in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.QUARANTINED,
            }:
                detail = task.error or task.result or {}
                raise FileAgentRuntimeError(
                    f"Task {task_id} ended as {task.status.value}: {detail}",
                )
            await asyncio.sleep(min(self.poll_interval_seconds, 0.5))

    async def _await_specialist_tasks(
        self,
        *,
        project_id: str,
        parent_run_id: str,
        epoch: int,
        task_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Await a batch of tasks in parallel, tolerating per-task failure.

        Unlike the single-task awaiter this never raises for a FAILED
        task: the harvest must report every task's own outcome so one
        bad observation cannot mask the results of its batch peers.
        """

        async def _one(task_id: str) -> dict[str, Any]:
            try:
                task = await self._await_specialist_task(
                    project_id=project_id,
                    parent_run_id=parent_run_id,
                    epoch=epoch,
                    task_id=task_id,
                )
            except (asyncio.CancelledError, StaleAgentRun):
                raise
            except FileAgentRuntimeError as exc:
                return {
                    "taskId": task_id,
                    "status": "FAILED",
                    "error": str(exc),
                }
            return {
                "taskId": task.task_id,
                "status": task.status.value,
                "outputRefs": list(task.output_refs),
                "result": task.result,
            }

        return list(
            await asyncio.gather(*(_one(task_id) for task_id in task_ids)),
        )

    async def _workspace_changed(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        result: Mapping[str, Any],
        *,
        action_id: str,
        specialist: Mapping[str, Any] | None = None,
    ) -> None:
        changed = result.get("changedPointers")
        if not isinstance(changed, list) or not changed:
            return
        # Every committed structure write may have turned media nodes READY
        # (prompt-first planning writes complete variant prompts long before
        # the run ends). Waking the scheduler here lets anchors render in
        # parallel with the remaining planning turns instead of idling until
        # run completion — measured at ~9 wasted minutes on a five-act
        # project. Cheap when nothing is ready: one derived-graph tick, and
        # the fingerprint ledger already dedupes; a later prompt edit marks
        # the early render stale through the normal staleness path.
        self.work_scheduler.wake(project_id)
        await self._event(
            project_id,
            session_id,
            "workspace.head_changed",
            run_id,
            request,
            {
                "runId": run_id,
                "actionId": action_id,
                "generation": result.get("generation"),
                "etag": result.get("etag"),
                "changedPointers": changed,
                **dict(specialist or {}),
            },
        )

    async def _persist_assistant_turn(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        turn: AgentModelTurn,
        *,
        message_id: str,
    ) -> None:
        metadata: dict[str, Any] = {
            "runId": run_id,
            "providerMessageId": turn.provider_message_id,
            "providerThinking": turn.thinking,
            "providerFinishReason": turn.finish_reason,
            "providerUsage": turn.usage,
        }
        open_action_ids: list[str] = []
        if turn.tool_calls:
            call = turn.tool_calls[0]
            open_action_ids.append(call.call_id)
            metadata.update(
                {
                    "actionId": call.call_id,
                    "actionDispatchStatus": "OPEN_ACTION",
                    "toolCall": {
                        "id": call.call_id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                        "transport": _tool_call_transport_metadata(call),
                    },
                },
            )
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            request.conversation_id,
            role="assistant",
            content_parts=[{"type": "text", "text": turn.content or ""}],
            message_id=message_id,
            source="creator_agent",
            metadata=metadata,
        )
        await self._event(
            project_id,
            session_id,
            "message.completed",
            run_id,
            request,
            {
                "runId": run_id,
                "messageId": appended.message.message_id,
                "messageSeq": appended.message.message_seq,
                "openActionIds": open_action_ids,
            },
        )

    async def _persist_tool_result(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        *,
        call_id: str,
        tool_name: str,
        result: Mapping[str, Any],
        failed: bool = False,
    ) -> None:
        raw_result = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        result_kind = _runtime_action_result_kind(
            tool_name,
            result,
            failed=failed,
        )
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            request.conversation_id,
            role="tool",
            content_parts=[{"type": "text", "text": raw_result}],
            source="runtime_action_result",
            metadata={
                "runId": run_id,
                "actionId": call_id,
                "toolCallId": call_id,
                "toolName": tool_name,
                "tool": tool_name,
                **({"resultKind": result_kind} if result_kind else {}),
                "failed": failed,
                "generation": result.get("generation"),
                "etag": result.get("etag"),
                "transactionId": result.get("transactionId"),
                "changedPointers": result.get("changedPointers"),
                "reviewId": result.get("reviewId"),
            },
        )
        await self._event(
            project_id,
            session_id,
            "agent.tool_completed",
            run_id,
            request,
            {
                "runId": run_id,
                "actionId": call_id,
                "toolCallId": call_id,
                "tool": tool_name,
                "messageSeq": appended.message.message_seq,
                "failed": failed,
                **(
                    {
                        "error": str(
                            (
                                result.get("error", {}).get("message")
                                if isinstance(result.get("error"), Mapping)
                                else "Tool execution failed"
                            ),
                        ),
                        "errorType": str(
                            (
                                result.get("error", {}).get("type")
                                if isinstance(result.get("error"), Mapping)
                                else "ToolError"
                            ),
                        ),
                    }
                    if failed
                    else {}
                ),
            },
        )

    async def _goal_for_message(
        self,
        session: Any,
        message: CreatorMessageRecord,
    ):
        """Resolve the Goal owning this message; returns (goal, created)."""

        if session.active_goal_id is not None:
            try:
                goal = await asyncio.to_thread(
                    self.sessions.get_goal,
                    message.project_id,
                    session.active_goal_id,
                )
            except RuntimeGoalNotFound:
                goal = None
            # A COMPLETED Goal is finished work and can never own a new
            # run: binding one deadlocks the Session, because admission
            # rejects every later message with "Active Goal is terminal"
            # while the dispatcher treats the queued run as a foreign
            # lease. A resume request after completion starts a fresh
            # Goal instead. CANCELLED/FAILED goals stay reusable — an
            # AgentDock interrupt deliberately resumes its cancelled
            # mainline under the same Goal identity.
            if (
                goal is not None
                and goal.status is not CreatorGoalStatus.COMPLETED
            ):
                return goal, False
        created = await asyncio.to_thread(
            self.sessions.create_goal,
            message.project_id,
            session.session_id,
            message.conversation_id,
            root_message_seq=message.message_seq,
            intent=_message_text(message),
            goal_id=f"goal-{uuid4().hex}",
            metadata={"source": "file_agent_runtime"},
        )
        return created, True

    MAINLINE_RESUME_SOURCE = "mainline_resume"
    YOLO_RESUME_SOURCE = "yolo_auto_resume"
    # Fuse 1: never chain more unattended resumes than this since the last
    # human message — a stuck project must fall back to a human.
    YOLO_RESUME_MAX_CONSECUTIVE = 5

    async def _queue_yolo_completion_resume(  # pylint: disable=too-many-return-statements
        self,
        *,
        project_id: str,
        session_id: str,
        conversation_id: str,
        run_id: str,
        after_failure: bool = False,
    ) -> None:
        """Keep an unattended (YOLO) project moving until it is finished.

        A succeeded mainline run is a model decision to stop narrating, not
        proof the project reached its goal: models habitually wrap up with a
        progress report after a batch of work. Under media_review
        auto_approve the operator asked for zero attendance, so when timeline
        elements still lack their main video the Runtime injects the same
        “继续” a supervising user would type. Two fuses stop runaway loops:
        a consecutive-resume cap and a no-progress breaker.

        ``after_failure`` covers retryable faults (empty model turns,
        transport blips): the failure itself proves the work is unfinished,
        so the completion criterion is skipped — an early failure with no
        elements yet must still resume.
        """

        if get_media_review_mode() != MEDIA_REVIEW_AUTO_APPROVE:
            return
        try:
            snapshot = await asyncio.to_thread(
                self.services.projects.read,
                project_id,
            )
        except Exception:  # pylint: disable=broad-except
            return
        try:
            records = await asyncio.to_thread(
                self.executions.list_tasks,
                project_id,
            )
        except Exception:  # pylint: disable=broad-except
            records = []
        graph = derive_work_graph(snapshot.project, tasks=records)
        unfinished_nodes = graph.unfinished()
        if not unfinished_nodes and not after_failure:
            return
        # Let the machine take every dispatchable gap before deciding to
        # spend a model turn: the scheduler fans out READY media nodes.
        self.work_scheduler.wake(project_id)
        try:
            await asyncio.to_thread(
                ensure_media_call_budget,
                self.services,
                project_id,
            )
        except MediaCallBudgetExhausted as exc:
            # A spent wallet fuse paralyzes every media path — a resume
            # would only make the model walk into the same wall.
            logger.warning(
                "YOLO auto-resume stopped for %s: %s",
                project_id,
                exc,
            )
            return
        model_required = graph.model_required_nodes()
        if (
            not after_failure
            and self.work_scheduler.enabled()
            and not model_required
        ):
            # Every remaining gap is machine-dispatchable (READY/RUNNING):
            # the scheduler owns it; a resume would only burn model turns.
            return
        unfinished = [
            node.label for node in (model_required or unfinished_nodes)
        ]
        messages = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session_id,
            after_seq=0,
            limit=None,
        )
        resume_streak = 0
        last_resume_generation: int | None = None
        for item in reversed(messages):
            if item.role != "user":
                continue
            if item.source == self.YOLO_RESUME_SOURCE:
                if resume_streak == 0:
                    generation = item.metadata.get("projectGeneration")
                    if isinstance(generation, int):
                        last_resume_generation = generation
                resume_streak += 1
                continue
            if item.source == self.MAINLINE_RESUME_SOURCE:
                continue
            break
        if resume_streak >= self.YOLO_RESUME_MAX_CONSECUTIVE:
            logger.warning(
                "YOLO auto-resume stopped for %s: %d consecutive resumes "
                "without a human message",
                project_id,
                resume_streak,
            )
            return
        # Fuse 2: the previous auto-resume produced no committed progress,
        # so another identical nudge would only burn model turns.
        if last_resume_generation == snapshot.generation:
            logger.warning(
                "YOLO auto-resume stopped for %s: no progress since the "
                "previous resume (generation %d)",
                project_id,
                snapshot.generation,
            )
            return
        if after_failure:
            text = (
                "【系统自动消息 · YOLO 持续执行】上一回合因瞬态故障中止"
                "（如模型空响应或传输抖动），项目尚未完成。\n"
                "请回顾会话历史，从中断处继续执行，不要重复已完成的工作。"
            )
            if unfinished:
                text += (
                    "\n以下环节尚未完成："
                    + "、".join(unfinished[:8])
                    + "。可自动派发的媒体生成已由 Runtime 并行执行，无需重复委派。"
                )
        else:
            reasons = []
            for node in model_required[:8]:
                why = node.error or "、".join(node.missing[:3]) or "待处理"
                reasons.append(f"{node.label}（{why}）")
            text = (
                "【系统自动消息 · YOLO 持续执行】主线回合已结束，但以下环节需要"
                "你处理（可自动派发的媒体生成已由 Runtime 并行执行，无需重复委派）：\n"
                + "\n".join(f"- {reason}" for reason in reasons)
                + "\n请针对上述环节修复结构、补全 prompt 或调整参数；不要重复已完成的工作。"
            )
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            conversation_id,
            role="user",
            content_parts=[{"type": "text", "text": text}],
            source=self.YOLO_RESUME_SOURCE,
            channel=MessageChannel.RUNTIME,
            metadata={
                "resumeAfterRunId": run_id,
                "projectGeneration": snapshot.generation,
                "unfinishedElements": unfinished,
                "modelRequiredNodes": [
                    node.node_id for node in model_required[:12]
                ],
            },
        )
        await self._event(
            project_id,
            session_id,
            "agent.yolo.resumed",
            run_id,
            appended.message,
            {
                "runId": run_id,
                "messageSeq": appended.message.message_seq,
                "unfinishedElements": unfinished,
            },
        )
        self._wake.set()

    async def _queue_mainline_resume(
        self,
        *,
        project_id: str,
        session_id: str,
        conversation_id: str,
        intervention_run_id: str,
        interrupted_run_id: str,
    ) -> None:
        """Return the Agent to its interrupted mainline after an intervention.

        An AgentDock interrupt cancels the running mainline and gates every
        branch change behind a Review.  Once the branch run has finished, the
        Session would otherwise sit still and the original task would never
        complete.  Queue one runtime-channel user message — never AgentDock,
        so it can never capture a ReviewBoundary — that tells the Agent to
        continue the mainline.  Everything the resumed run produces is plain
        auto-fix mainline work again and does not require review.
        """

        try:
            interrupted = await asyncio.to_thread(
                self.runs.get,
                project_id,
                interrupted_run_id,
            )
        except Exception:
            interrupted = None
        # Only a run that never reached its own terminal success/failure
        # left unfinished mainline work behind.  A run that succeeded or
        # failed on its own terms must not be relaunched automatically —
        # restarting a failed mainline could loop forever.  A CANCELLED (or
        # still RUNNING/QUEUED after a cross-process takeover) record is the
        # superseded mainline we return to.
        if interrupted is None or interrupted.status in {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
        }:
            return
        messages = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session_id,
            after_seq=0,
            limit=None,
        )
        if any(
            item.source == self.MAINLINE_RESUME_SOURCE
            and item.metadata.get("resumeAfterRunId") == intervention_run_id
            for item in messages
        ):
            return
        mainline_request = next(
            (
                item
                for item in messages
                if item.message_seq == interrupted.caused_by_message_seq
            ),
            None,
        )
        mainline_goal = (
            _message_text(mainline_request)
            if mainline_request is not None
            else ""
        )
        # Never assert that the intervention is resolved: when the branch
        # run ended by asking the user a question, claiming “已处理完成”
        # makes the model abandon its own open question and resume work.
        text = (
            "【系统自动消息 · 主线恢复提醒】一次用户插入请求的处理回合已结束。"
            "请先回顾你的上一条回复，再决定下一步：\n"
            "1. 如果你正在等待用户答复（例如提出了问题、给出了待选择的方案），"
            "请不要恢复主线：直接简短说明你仍在等待用户答复，然后结束本轮；\n"
            "2. 如果插入请求确实已处理完毕，请回顾会话历史，找到此前被中断的"
            "主线任务，从中断处继续执行，不要重复已完成的步骤；\n"
            "3. 本消息不是新的修改意见；如果主线任务实际上已全部完成，"
            "请直接确认完成状态，不要进行任何新的修改。"
        )
        if mainline_goal:
            text += f"\n\n被中断的主线任务原始请求：\n{mainline_goal}"
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            conversation_id,
            role="user",
            content_parts=[{"type": "text", "text": text}],
            source=self.MAINLINE_RESUME_SOURCE,
            channel=MessageChannel.RUNTIME,
            metadata={
                "resumeAfterRunId": intervention_run_id,
                "interruptedRunId": interrupted_run_id,
            },
        )
        await self._event(
            project_id,
            session_id,
            "agent.mainline.resumed",
            intervention_run_id,
            appended.message,
            {
                "runId": intervention_run_id,
                "interruptedRunId": interrupted_run_id,
                "messageSeq": appended.message.message_seq,
            },
        )
        self._wake.set()

    async def _converge_resolved_review(self, project_id: str, session: Any):
        """Recover Session/Goal projections after a Review becomes terminal."""

        if session.status is not CreatorSessionStatus.PENDING_REVIEW:
            return session
        active_review = await asyncio.to_thread(
            self.services.reviews.active,
            project_id,
        )
        if active_review is not None:
            return session
        try:
            return await asyncio.to_thread(
                self.sessions.resolve_pending_review,
                project_id,
                session.session_id,
            )
        except (RuntimeGoalNotFound, SessionStateConflict):
            return await asyncio.to_thread(
                self.sessions.get_project_session,
                project_id,
            )

    @staticmethod
    def _tool_context(
        message: CreatorMessageRecord,
        *,
        run_id: str,
    ) -> AgentProjectToolContext:
        boundary = message.review_boundary
        if boundary is not None:
            # A boundary captured while a Run was active is an interrupt; one
            # captured on an idle Session is post-run feedback.  Both gate all
            # related changes behind the same review flow.
            origin = (
                ChangeOrigin.AGENTDOCK_INTERRUPT
                if boundary.interrupted_run_id is not None
                else ChangeOrigin.AGENTDOCK_IDLE_GOAL
            )
            policy = ReviewPolicy.REQUIRE_REVIEW
            request_id = boundary.request_id
            message_seq = boundary.request_message_seq
        else:
            initial = bool(message.metadata.get("initialCreation")) or (
                message.source == "initial_goal"
            )
            origin = (
                ChangeOrigin.INITIAL_CREATION
                if initial
                else (
                    ChangeOrigin.AGENTDOCK_IDLE_GOAL
                    if message.channel is MessageChannel.AGENTDOCK
                    else ChangeOrigin.RUNTIME_TASK
                )
            )
            policy = ReviewPolicy.AUTO_FIX
            request_id = message.client_message_id or message.message_id
            message_seq = message.message_seq
        return AgentProjectToolContext(
            origin=origin,
            review_policy=policy,
            review_boundary=boundary,
            caused_by_request_id=request_id,
            caused_by_message_seq=message_seq,
            round_id=f"agent-round-{run_id}",
        )

    async def _cancel_run_if_project_exists(
        self,
        project_id: str,
        session_id: str,
        goal_id: str,
        run_id: str,
        message: CreatorMessageRecord,
    ) -> None:
        """Settle cancellation, suppressing only an atomic Project deletion."""

        try:
            await self._cancel_run(
                project_id,
                session_id,
                goal_id,
                run_id,
                message,
            )
        except Exception:  # pylint: disable=broad-except
            project_path = self.services.projects.project_path(project_id)
            if project_path.is_file():
                raise
            # DELETE atomically removed the complete authority. Persisting a
            # terminal Run/Session below the old id would recreate a ghost
            # Project; absence is already the stronger terminal state.
            logger.info(
                "cancel cleanup stopped because Project was deleted: "
                "project=%s run=%s",
                project_id,
                run_id,
            )

    async def _cancel_run(
        self,
        project_id: str,
        session_id: str,
        goal_id: str,
        run_id: str,
        message: CreatorMessageRecord,
    ) -> None:
        handle = self._active.get(project_id)
        superseded = bool(
            handle is not None
            and handle.run_id == run_id
            and handle.superseded,
        )
        try:
            await asyncio.to_thread(
                self.runs.transition,
                project_id,
                run_id,
                expected_status={
                    AgentRunStatus.QUEUED,
                    AgentRunStatus.RUNNING,
                },
                status=AgentRunStatus.CANCELLED,
                updates={
                    "error": {
                        # SHUTDOWN marks a process-lifecycle cancellation
                        # (restart/deploy): the startup sweep may resume
                        # it. INTERRUPTED stays a human stop and is never
                        # auto-resumed.
                        "code": (
                            "SUPERSEDED"
                            if superseded
                            else (
                                "SHUTDOWN" if self._stopping else "INTERRUPTED"
                            )
                        ),
                        "message": (
                            "Run superseded by an AgentDock request"
                            if superseded
                            else (
                                "Run cancelled by process shutdown"
                                if self._stopping
                                else "Run interrupted by the user"
                            )
                        ),
                    },
                },
            )
        except AgentRunStateConflict:
            pass
        if superseded:
            try:
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session_id,
                    through_seq=message.message_seq,
                    goal_id=goal_id,
                )
            except SessionStateConflict:
                pass
        else:
            # A hard stop is a durable input boundary, not a process-local
            # retry guard.  Consume every message that existed when cleanup
            # reached this point before releasing active_run_id.  Other
            # QwenPaw processes can then observe the same stop and cannot
            # immediately relaunch the cancelled request.
            #
            # Snapshot read (shared lock): the full get_project_session
            # recovery replays the whole event stream under the exclusive
            # Runtime lock and loses that race against steady polling on
            # large sessions.  An error escaping this block would abort the
            # terminal writes below, leaving the Session INTERRUPT_REQUESTED
            # while reconcile reclaimed the pointer and relaunched the
            # unconsumed request — the dock showed 「正在停止」 forever.
            try:
                current_session = await asyncio.to_thread(
                    self.sessions.get_project_session_snapshot,
                    project_id,
                )
                consume_through_seq = current_session.last_message_seq
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "interrupt cleanup could not read the session head; "
                    "consuming the stopped request only: project=%s run=%s",
                    project_id,
                    run_id,
                )
                consume_through_seq = message.message_seq
            try:
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session_id,
                    through_seq=consume_through_seq,
                    goal_id=goal_id,
                )
            except SessionStateConflict:
                pass
        try:
            await asyncio.to_thread(
                self.sessions.set_goal_status,
                project_id,
                goal_id,
                (
                    CreatorGoalStatus.RESUME_REQUIRED
                    if superseded
                    else CreatorGoalStatus.CANCELLED
                ),
            )
            await asyncio.to_thread(
                self.sessions.clear_active_run,
                project_id,
                session_id,
                expected_run_id=run_id,
                status=(
                    CreatorSessionStatus.RESUMING
                    if superseded
                    else CreatorSessionStatus.CANCELLED
                ),
            )
        except SessionStateConflict:
            pass
        await self._event(
            project_id,
            session_id,
            "agent.run.cancelled",
            run_id,
            message,
            {"runId": run_id, "superseded": superseded},
        )

    async def _fail_run(
        self,
        project_id: str,
        session_id: str,
        goal_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        *,
        code: str,
        message_text: str,
        retryable: bool,
        extra_details: Mapping[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "runId": run_id,
            "messageSeq": request.message_seq,
            "projectId": project_id,
            "sessionId": session_id,
            "goalId": goal_id,
        }
        if extra_details:
            details.update(extra_details)
        report = report_error(
            component="file-agent-runtime",
            code=code,
            message=message_text,
            retryable=retryable,
            details=details,
            projectId=project_id,
            sessionId=session_id,
            goalId=goal_id,
            runId=run_id,
        )
        details.update(
            {
                key: report[key]
                for key in ("errorId", "traceId", "requestId")
                if report.get(key)
            },
        )
        # Terminal persistence must survive the very condition that usually
        # triggers it: Runtime lock starvation.  A failure cascade that
        # itself dies on LockTimeoutError durably strands the run RUNNING
        # and wedges the Session (observed live: the dock showed 「正在停止
        # 所有 Agent」 forever).  Each step below therefore retries lock
        # timeouts and never aborts the remaining cleanup.
        try:
            await self._persist_terminal_state(
                "run transition",
                self.runs.transition,
                project_id,
                run_id,
                expected_status={
                    AgentRunStatus.QUEUED,
                    AgentRunStatus.RUNNING,
                },
                status=AgentRunStatus.FAILED,
                updates={
                    "error": {
                        "code": code,
                        "message": message_text,
                        "retryable": retryable,
                        "details": details,
                    },
                },
            )
        except AgentRunStateConflict:
            pass
        # A failure is a durable input boundary, not a process-local retry
        # guard.  Consume the failed request before releasing active_run_id so
        # that neither a process restart nor an unrelated ``notify`` (which
        # clears the in-memory ``_blocked_heads``) relaunches the Agent on the
        # same message.  Recovery requires a new explicit user request; the
        # persisted session error keeps the failure visible to AgentDock.
        try:
            await self._persist_terminal_state(
                "consume failed request",
                self.sessions.mark_messages_consumed,
                project_id,
                session_id,
                through_seq=request.message_seq,
                goal_id=goal_id,
            )
        except SessionStateConflict:
            pass
        try:
            await self._persist_terminal_state(
                "goal failure",
                self.sessions.set_goal_status,
                project_id,
                goal_id,
                CreatorGoalStatus.FAILED,
            )
            await self._persist_terminal_state(
                "session lease release",
                self.sessions.clear_active_run,
                project_id,
                session_id,
                expected_run_id=run_id,
            )
        except SessionStateConflict:
            pass
        with contextlib.suppress(SessionStateConflict):
            await self._persist_terminal_state(
                "session error",
                self.sessions.set_session_error,
                project_id,
                session_id,
                code=code,
                message=message_text,
                retryable=retryable,
                details=details,
            )
        # Unattended (YOLO) projects must not stay parked on a transient
        # model fault at 3am: a retryable failure gets the same completion
        # check as a succeeded run. The resume fuses (consecutive cap and
        # the no-progress generation breaker) bound a run that keeps dying
        # at the same spot, so this cannot loop forever. Non-retryable
        # failures still wait for a human.
        if retryable:
            await self._queue_yolo_completion_resume(
                project_id=project_id,
                session_id=session_id,
                conversation_id=request.conversation_id,
                run_id=run_id,
                after_failure=True,
            )
        await self._event(
            project_id,
            session_id,
            "agent.run.failed",
            run_id,
            request,
            {
                "runId": run_id,
                "error": {
                    "code": code,
                    "message": message_text,
                    "retryable": retryable,
                    "details": details,
                },
            },
        )

    # How long a durable interrupt may point at a RUNNING run that no local
    # handle owns before this process reclaims it.  A live owner (this or any
    # sibling process) serves a durable interrupt within seconds via task
    # cancellation, so a stall this long means the owner died between failing
    # and persisting a terminal run status.
    _INTERRUPT_STALL_RECLAIM_SECONDS = 120.0

    def _interrupt_stall_expired(self, project_id: str, run_id: str) -> bool:
        """Track how long a durable interrupt has pointed at the same run."""

        now = time.monotonic()
        stall = self._interrupt_stalls.get(project_id)
        if stall is None or stall[0] != run_id:
            self._interrupt_stalls[project_id] = (run_id, now)
            return False
        return now - stall[1] >= self._INTERRUPT_STALL_RECLAIM_SECONDS

    async def _persist_terminal_state(
        self,
        description: str,
        func: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a durable terminal write, retrying Runtime lock timeouts.

        Terminal cleanup usually executes exactly when the Runtime lock is
        most contended; giving up on the first timeout durably strands
        non-terminal state that no later pass may safely repair.
        """

        delay = 1.0
        attempts = 5
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except LockTimeoutError as exc:
                if attempt == attempts:
                    logger.error(
                        "terminal persistence gave up (%s) after %d "
                        "attempts: %s",
                        description,
                        attempts,
                        exc,
                    )
                    raise
                logger.warning(
                    "terminal persistence retry %d/%d (%s): %s",
                    attempt,
                    attempts,
                    description,
                    exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)

    async def _record_idle_interrupt(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> None:
        try:
            # Snapshot read (shared lock): the full get_project_session
            # recovery holds the exclusive Runtime lock while it replays
            # the whole event stream, which loses the lock race against
            # steady UI polling on large sessions — the stop then never
            # completes (observed live: LockTimeoutError on every poll
            # while the dock showed 「正在停止所有 Agent」 forever).  The
            # cleanup below only needs head pointers; each write takes
            # its own short exclusive lock.
            session = await asyncio.to_thread(
                self.sessions.get_project_session_snapshot,
                project_id,
            )
            if session.active_run_id is not None:
                # A RUNNING run without a local handle is owned by another
                # live process: leave the durable interrupt in place so that
                # owner cancels itself.  A QUEUED or terminal run is
                # ownerless (typically orphaned by a backend restart while
                # the stop was pending) — no dispatcher will ever start or
                # finish it, so the stop must be served here.
                try:
                    run = await asyncio.to_thread(
                        self.runs.get,
                        project_id,
                        session.active_run_id,
                    )
                except Exception:
                    return
                if run.status is AgentRunStatus.QUEUED:
                    try:
                        await asyncio.to_thread(
                            self.runs.transition,
                            project_id,
                            run.run_id,
                            expected_status=AgentRunStatus.QUEUED,
                            status=AgentRunStatus.CANCELLED,
                            updates={
                                "error": {
                                    "code": "INTERRUPTED",
                                    "message": (
                                        "queued run cancelled by a durable "
                                        "interrupt served after restart"
                                    ),
                                },
                            },
                        )
                    except AgentRunStateConflict:
                        # Another process started it first; that owner now
                        # serves the interrupt.
                        return
                elif run.status not in TERMINAL_AGENT_RUN_STATUSES:
                    # A RUNNING run whose worker died between failing and
                    # persisting its terminal status (observed live: the
                    # FAILED transition itself lost the Runtime lock race)
                    # stays RUNNING durably with no owner — waiting on it
                    # parks the Session in INTERRUPT_REQUESTED forever.  A
                    # live owner resolves a durable interrupt within
                    # seconds, so a persistent stall proves the owner is
                    # gone and the stop must be served here.
                    if not self._interrupt_stall_expired(
                        project_id,
                        run.run_id,
                    ):
                        return
                    try:
                        await asyncio.to_thread(
                            self.runs.transition,
                            project_id,
                            run.run_id,
                            expected_status=run.status,
                            status=AgentRunStatus.FAILED,
                            updates={
                                "error": {
                                    "code": "INTERRUPTED",
                                    "message": (
                                        "running run reclaimed by a stalled "
                                        "durable interrupt; its worker died "
                                        "without persisting a terminal "
                                        "status"
                                    ),
                                    "retryable": True,
                                },
                            },
                        )
                    except AgentRunStateConflict:
                        # A live owner moved the run after all; it now
                        # serves the interrupt.
                        return
                    logger.warning(
                        "reclaimed orphaned RUNNING run for durable "
                        "interrupt: project=%s run=%s",
                        _log_safe(project_id),
                        _log_safe(run.run_id),
                    )
                session = await self._persist_terminal_state(
                    "interrupt lease release",
                    self.sessions.clear_active_run,
                    project_id,
                    session.session_id,
                    expected_run_id=run.run_id,
                    status=CreatorSessionStatus.INTERRUPT_REQUESTED,
                )
            if session.last_consumed_message_seq < session.last_message_seq:
                await self._persist_terminal_state(
                    "interrupt message consumption",
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session.session_id,
                    through_seq=session.last_message_seq,
                    goal_id=session.active_goal_id,
                )
            await self._persist_terminal_state(
                "interrupt session status",
                self.sessions.set_session_status,
                project_id,
                session.session_id,
                CreatorSessionStatus.CANCELLED,
            )
            await asyncio.to_thread(
                self.sessions.append_event,
                project_id,
                session.session_id,
                event_type="agent.interrupt.idle",
                actor="user",
                payload={"reason": reason},
            )
            self._interrupt_stalls.pop(project_id, None)
        except Exception:
            # The next reconcile pass retries; keep the failure visible —
            # this path being silent hid a permanently wedged Session.
            logger.warning(
                "idle interrupt cleanup failed: project=%s reason=%s",
                _log_safe(project_id),
                _log_safe(reason),
                exc_info=True,
            )
            return

    async def _event(
        self,
        project_id: str,
        session_id: str,
        event_type: str,
        run_id: str,
        request: CreatorMessageRecord,
        payload: Mapping[str, Any],
    ) -> None:
        await asyncio.to_thread(
            self.sessions.append_event,
            project_id,
            session_id,
            event_type=event_type,
            actor="file_agent_runtime",
            round_id=f"agent-round-{run_id}",
            message_id=request.message_id,
            payload=dict(payload),
        )
        if not event_type.endswith("_delta"):
            trace_event(
                f"creator.{event_type}",
                component="creator.file_agent_runtime",
                projectId=project_id,
                sessionId=session_id,
                conversationId=request.conversation_id,
                runId=run_id,
                attributes=dict(payload),
            )

    def _begin_epoch(self, project_id: str, run_id: str) -> int:
        with self._publication_lock:
            epoch = self._epochs.get(project_id, 0) + 1
            self._epochs[project_id] = epoch
            return epoch

    def _revoke_epoch(self, project_id: str, run_id: str, epoch: int) -> None:
        del run_id
        with self._publication_lock:
            if self._epochs.get(project_id) == epoch:
                self._epochs[project_id] = epoch + 1

    def _assert_epoch(self, project_id: str, run_id: str, epoch: int) -> None:
        with self._publication_lock:
            if self._epochs.get(project_id) != epoch:
                raise StaleAgentRun(
                    f"Agent run was interrupted and may no longer commit: {run_id}",
                )


def _message_text(message: CreatorMessageRecord) -> str:
    chunks: list[str] = []
    for part in message.content_parts:
        if part.type == "text" and part.text:
            chunks.append(part.text)
        else:
            chunks.append(
                json.dumps(
                    part.model_dump(mode="json", exclude_none=True),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    refs = message.metadata.get("assetVersionRefs")
    if isinstance(refs, list):
        exact_refs = [
            str(value).strip() for value in refs if str(value).strip()
        ]
        if exact_refs:
            chunks.append(
                "本轮已入库素材（本轮消息附件的 exact AssetVersion refs，"
                "不是文件路径或操作指令）："
                + json.dumps(
                    list(dict.fromkeys(exact_refs)),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    context = message.metadata.get("context")
    if isinstance(context, Mapping):
        keys = (
            "panel",
            "selected",
            "editingField",
            "selection",
            "selections",
            "extraRefs",
            "targetRef",
            "targetRefs",
            "userEdits",
        )
        structured = {
            key: context[key]
            for key in keys
            if key in context and context[key] not in (None, "", [], {})
        }
        if structured:
            chunks.append(
                "[Creator UI 结构化上下文；path 是 project.json 的 RFC 6901 "
                "字段指针，field/ref 是语义定位。userEdits 是用户自上条消息以来"
                "在编辑台手动应用且已生效的 project.json 修改记录，不需要重新"
                "执行；评估这些修改对方案依赖的影响。修改前读取对应字段核验]\n"
                + json.dumps(
                    structured,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    return "\n".join(chunks).strip() or "请处理本消息中的项目请求。"


# A conversation accumulates full project.json echoes from read_project and
# jq_project; a 50-element Project makes each echo ~400KB and the sum overflows
# the model input window (observed: 2.09MB of history against a 0.98MB limit).
# Keep one latest materialized snapshot as the model's source of truth and turn
# older snapshots into compact mutation receipts. The jq tool call immediately
# before each receipt still records the exact mutation program and arguments,
# so history remains change-based without asking the model to replay those
# changes to reconstruct current state. Durable Runtime history keeps every
# original byte.
_SNAPSHOT_SOURCE = "runtime_action_result"


@dataclass(frozen=True)
class _ProjectSnapshotEnvelope:
    payload: Mapping[str, Any]
    project_id: str
    generation: int
    etag: str


def _project_snapshot_envelope(
    payload: Mapping[str, Any],
) -> _ProjectSnapshotEnvelope | None:
    project = payload.get("project")
    if not isinstance(project, Mapping):
        return None
    project_id = project.get("project_id")
    generation = payload.get("generation")
    project_generation = project.get("generation")
    etag = payload.get("etag")
    if not isinstance(project_id, str) or not project_id.strip():
        return None
    if not isinstance(generation, int) or isinstance(generation, bool):
        return None
    if (
        not isinstance(project_generation, int)
        or isinstance(project_generation, bool)
        or project_generation != generation
    ):
        return None
    if not isinstance(etag, str) or not etag.strip():
        return None
    return _ProjectSnapshotEnvelope(
        payload=payload,
        project_id=project_id,
        generation=generation,
        etag=etag,
    )


def _project_snapshot_from_text(text: str) -> _ProjectSnapshotEnvelope | None:
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return _project_snapshot_envelope(payload)


def _runtime_action_result_kind(
    tool_name: str,
    result: Mapping[str, Any],
    *,
    failed: bool,
) -> str | None:
    if (
        not failed
        and tool_name in _PROJECT_SNAPSHOT_TOOL_NAMES
        and _project_snapshot_envelope(result) is not None
    ):
        return _PROJECT_SNAPSHOT_RESULT_KIND
    if not failed and tool_name == GROUND_PROMPT_CONTEXT_TOOL_NAME:
        return "web_grounding"
    if not failed and tool_name == OBJECT_GROUNDING_TOOL_NAME:
        return "object_grounding"
    return None


def _message_project_snapshot(
    message: CreatorMessageRecord,
) -> tuple[_ProjectSnapshotEnvelope, str] | None:
    tool_name = str(
        message.metadata.get("toolName") or message.metadata.get("tool") or "",
    ).strip()
    if tool_name not in _PROJECT_SNAPSHOT_TOOL_NAMES:
        return None
    result_kind = message.metadata.get("resultKind")
    if result_kind not in (None, "", _PROJECT_SNAPSHOT_RESULT_KIND):
        return None
    for part in message.content_parts:
        if not part.text:
            continue
        snapshot = _project_snapshot_from_text(part.text)
        if snapshot is not None:
            return snapshot, tool_name
    return None


def _project_change_receipt(
    snapshot: _ProjectSnapshotEnvelope,
    *,
    tool_name: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    source = metadata or snapshot.payload
    receipt: dict[str, Any] = {
        "resultKind": _PROJECT_CHANGE_RECEIPT_RESULT_KIND,
        "supersededProjectSnapshot": True,
        "toolName": tool_name,
        "projectId": snapshot.project_id,
        "generation": snapshot.generation,
        "etag": snapshot.etag,
        "note": (
            "The full project snapshot from this historical tool result was "
            "omitted. A later project_snapshot in this conversation is the "
            "authoritative materialized state."
        ),
    }
    for key in ("transactionId", "reviewId"):
        value = source.get(key)
        if value in (None, ""):
            value = snapshot.payload.get(key)
        if value not in (None, ""):
            receipt[key] = value
    changed_pointers = source.get("changedPointers")
    if not isinstance(changed_pointers, list):
        changed_pointers = snapshot.payload.get("changedPointers")
    if isinstance(changed_pointers, list):
        receipt["changedPointers"] = [
            str(pointer)
            for pointer in changed_pointers
            if isinstance(pointer, str) and pointer
        ]
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))


def _elide_stale_snapshots(
    prior_context: list[CreatorMessageRecord],
) -> dict[int, str]:
    """Map message seq to a receipt for each superseded snapshot."""

    snapshots: list[
        tuple[CreatorMessageRecord, _ProjectSnapshotEnvelope, str]
    ] = []
    for item in prior_context:
        if item.role != "tool" or item.source != _SNAPSHOT_SOURCE:
            continue
        identified = _message_project_snapshot(item)
        if identified is None:
            continue
        snapshot, tool_name = identified
        snapshots.append((item, snapshot, tool_name))

    receipts: dict[int, str] = {}
    for item, snapshot, tool_name in snapshots[:-1]:
        receipts[item.message_seq] = _project_change_receipt(
            snapshot,
            tool_name=tool_name,
            metadata=item.metadata,
        )
    return receipts


def _compact_wire_project_snapshots(messages: list[dict[str, Any]]) -> None:
    """Compact superseded snapshots in the ephemeral model wire context.

    Tool content is normally a string, but OpenAI-compatible wire messages
    may represent it as text content parts. Mutates message content in place
    while preserving any multipart structure and part metadata. Durable
    conversation and execution records remain unchanged. The operation is
    idempotent because receipts are not recognized as full Project snapshots.
    """

    snapshots: list[
        tuple[dict[str, Any], _ProjectSnapshotEnvelope, str, int | None]
    ] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        tool_name = str(message.get("name") or "").strip()
        if tool_name not in _PROJECT_SNAPSHOT_TOOL_NAMES:
            continue
        content = message.get("content")
        if isinstance(content, str):
            snapshot = _project_snapshot_from_text(content)
            if snapshot is not None:
                snapshots.append((message, snapshot, tool_name, None))
            continue
        if not isinstance(content, list):
            continue
        for part_index, part in enumerate(content):
            if not isinstance(part, Mapping) or part.get("type") != "text":
                continue
            text = part.get("text")
            if not isinstance(text, str):
                continue
            snapshot = _project_snapshot_from_text(text)
            if snapshot is not None:
                snapshots.append(
                    (message, snapshot, tool_name, part_index),
                )
                break
    for message, snapshot, tool_name, part_index in snapshots[:-1]:
        receipt = _project_change_receipt(
            snapshot,
            tool_name=tool_name,
        )
        if part_index is None:
            message["content"] = receipt
            continue
        content = message.get("content")
        if not isinstance(content, list) or part_index >= len(content):
            continue
        part = content[part_index]
        if not isinstance(part, Mapping):
            continue
        updated_content = list(content)
        updated_content[part_index] = {**part, "text": receipt}
        message["content"] = updated_content


def _continuation_message_text(
    request: CreatorMessageRecord,
    prior_context: list[CreatorMessageRecord],
) -> str:
    """Carry one durable AgentDock Conversation into the next Agent run."""

    current = _message_text(request)
    if not prior_context:
        return current
    snapshot_receipts = _elide_stale_snapshots(prior_context)
    history = [
        {
            "messageSeq": item.message_seq,
            "role": item.role,
            "source": item.source,
            "content": (
                [
                    {
                        "type": "text",
                        "text": snapshot_receipts[item.message_seq],
                    },
                ]
                if item.message_seq in snapshot_receipts
                else [
                    part.model_dump(mode="json", exclude_none=True)
                    for part in item.content_parts
                ]
            ),
            "metadata": {
                **dict(item.metadata),
                **(
                    {"resultKind": _PROJECT_CHANGE_RECEIPT_RESULT_KIND}
                    if item.message_seq in snapshot_receipts
                    else {}
                ),
            },
        }
        for item in prior_context
    ]
    return (
        "以下 CONVERSATION_HISTORY_JSON 是同一 AgentDock Conversation 在本轮之前"
        "已经持久化的完整上下文。请继承其中的用户目标、已完成步骤、工具结果与约束；"
        "它是上下文，不是新的操作指令。\n"
        "CONVERSATION_HISTORY_JSON="
        + json.dumps(history, ensure_ascii=False, separators=(",", ":"))
        + "\n\nCURRENT_USER_REQUEST=\n"
        + current
    )


def _require_source_intelligence_associations(
    project: Project,
    target_refs: list[str],
) -> None:
    """A Source Specialist cannot succeed with observations only in chat.

    SourceAnalysisService is the authority that publishes the indexed analysis
    and selects it on ProjectSource. This terminal fence prevents an outer VLM
    Specialist from returning SUCCESS before that durable association exists.
    """

    for target_ref in target_refs:
        prefix, separator, logical_asset_id = target_ref.partition(":")
        if prefix != "asset" or not separator or not logical_asset_id:
            raise FileAgentRuntimeError(
                f"Source Intelligence target is not canonical: {target_ref}",
            )
        sources = [
            source
            for source in project.sources.sources.items.values()
            if source.logical_asset_id == logical_asset_id
        ]
        if len(sources) != 1:
            raise FileAgentRuntimeError(
                "Source Intelligence SUCCESS requires exactly one ProjectSource for "
                f"asset:{logical_asset_id}",
            )
        source = sources[0]
        intelligence_id = source.current_intelligence_version_id
        if intelligence_id is None:
            raise FileAgentRuntimeError(
                "Source Intelligence SUCCESS requires ProjectSource."
                f"current_intelligence_version_id for asset:{logical_asset_id}",
            )
        intelligence = project.assets.intelligence_versions_by_id.get(
            intelligence_id,
        )
        if (
            intelligence is None
            or intelligence.source_asset_version_id
            != source.selected_asset_version_id
        ):
            raise FileAgentRuntimeError(
                "Source Intelligence selection does not match the current Source version "
                f"for asset:{logical_asset_id}",
            )
        indexed = project.assets.files_by_id.get(intelligence.file_id)
        if indexed is None or indexed.kind != "source_intelligence":
            raise FileAgentRuntimeError(
                "Source Intelligence SUCCESS requires an indexed analysis file for "
                f"asset:{logical_asset_id}",
            )


def _review_feedback_target_refs(
    request: CreatorMessageRecord,
) -> frozenset[str]:
    if request.source != "review_rejection_feedback":
        return frozenset()
    feedback = request.metadata.get("rejectionFeedback")
    if not isinstance(feedback, Mapping) or (
        feedback.get("action") != "UNDO_AND_REGENERATE"
    ):
        return frozenset()
    raw_targets = request.metadata.get("targets")
    if not isinstance(raw_targets, list):
        return frozenset()
    target_refs = {
        target_ref.strip()
        for item in raw_targets
        if isinstance(item, Mapping)
        for target_ref in [item.get("target_ref") or item.get("targetRef")]
        if isinstance(target_ref, str) and target_ref.strip()
    }
    # Legacy visual reviews used visual-entity:<id>, while the current
    # Specialist contract admits the same logical entity as asset:<id>.
    target_refs.update(
        "asset:" + target_ref.removeprefix("visual-entity:")
        for target_ref in tuple(target_refs)
        if target_ref.startswith("visual-entity:")
    )
    return frozenset(target_refs)


def _review_feedback_constraint(
    request: CreatorMessageRecord,
) -> str | None:
    """Render the durable rejection facts as a non-optional run constraint."""

    target_refs = _review_feedback_target_refs(request)
    if not target_refs:
        return None
    feedback = request.metadata.get("rejectionFeedback")
    if not isinstance(feedback, Mapping):
        return None
    lines = [
        "【Runtime 强制约束 · 审阅重做】",
        "本轮只允许重做这些 targetRef：" + ", ".join(sorted(target_refs)),
        "生成工具的最终 prompt 必须明确吸收下面的用户反馈；不能复用原 prompt。",
    ]
    feedback_note = feedback.get("feedbackNote") or feedback.get(
        "feedback_note",
    )
    problem_note = feedback.get("problemNote") or feedback.get("problem_note")
    instruction = feedback.get("regenerationInstruction") or feedback.get(
        "regeneration_instruction",
    )
    if isinstance(feedback_note, str) and feedback_note.strip():
        lines.append("必须吸收的用户反馈：" + feedback_note.strip())
    if isinstance(problem_note, str) and problem_note.strip():
        lines.append("需要修正的问题：" + problem_note.strip())
    if isinstance(instruction, str) and instruction.strip():
        lines.append("必须执行的重做要求：" + instruction.strip())
    return "\n".join(lines)


def _apply_review_feedback_to_tool_arguments(
    request: CreatorMessageRecord,
    *,
    name: str,
    arguments: Mapping[str, Any],
) -> tuple[Mapping[str, Any], bool]:
    """Deterministically carry rejection feedback into paid media prompts."""

    if name not in {"image_generation", "r2v_generation"}:
        return arguments, False
    constraint = _review_feedback_constraint(request)
    if constraint is None:
        return arguments, False
    raw_payload = arguments.get("arguments")
    if not isinstance(raw_payload, Mapping):
        return arguments, False
    prompt = raw_payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return arguments, False
    decision_id = str(request.metadata.get("decisionId") or "unknown")
    marker = f"[review-decision:{decision_id}]"
    if marker in prompt:
        return arguments, True
    payload = dict(raw_payload)
    payload["prompt"] = f"{prompt.rstrip()}\n\n{marker}\n{constraint}"
    enriched = dict(arguments)
    enriched["arguments"] = payload
    return enriched, True


def _specialist_terminal(content: str) -> tuple[str, str]:
    text = content.strip()
    for marker in ("SUCCESS", "BLOCKED", "FAILED"):
        prefix = f"[{marker}]"
        if text.startswith(prefix):
            return marker, text[len(prefix) :].strip() or prefix
    raise AgentModelError(
        "Specialist final response must start with [SUCCESS], [BLOCKED], or [FAILED]",
    )


def _jq_project_recovery(code: str | None) -> str:
    if code == "JQ_ARGUMENT_TYPE_MISMATCH":
        return (
            "Preserve each jsonArgs value's JSON type. The failed "
            "from_entries input is already an object map; assign or "
            "merge it directly. Use from_entries only for an array of "
            "{key, value} entries, and do not repeat the failed call."
        )
    if code == "JQ_RESULT_NOT_PROJECT_ROOT":
        return (
            "Issue a new jq_project transform rooted at the input "
            "Project `.` and return the complete Project object. Do not "
            "finish with a Timeline, Element, jsonArgs value, or other "
            "child object."
        )
    if code == "JQ_PROJECT_SCHEMA_INVALID":
        return (
            "Use the reported validation paths to correct program or "
            "jsonArgs, then issue a changed jq_project call. The invalid "
            "candidate was not published."
        )
    return (
        "Re-read project.json and retry jq_project with a transform "
        "that returns the complete Project root and preserves all "
        "Runtime-protected root fields. Never assign schema_version, "
        "project_id, generation, created_at, or updated_at; the "
        "Runtime maintains them. Start from the input Project `.`, "
        "not `$jsonArgs`. If the failure was malformed or misnested "
        "argument JSON: " + _JQ_PROJECT_CALL_SHAPE_RECOVERY + " For "
        "structured jsonArgs, preserve their JSON type: assign or merge "
        "object maps directly, and use from_entries only for an array "
        "of {key, value} entries. "
        "Remove nonexistent references; not-yet-produced artifacts "
        "stay null. Parenthesize computed jq values before binding "
        "them, for example "
        '("source:" + $logicalId) as $sourceKey, and parenthesize '
        "expressions used as object values. Never finish with a saved "
        "pre-edit root such as $project because that discards mutations."
    )


# pylint: disable=too-many-return-statements
def _specialist_tool_recovery(
    name: str,
    error: str = "",
    *,
    code: str | None = None,
) -> str:
    media_tools = {"image_generation", "r2v_generation", "ai_edit"}
    if any(
        marker in error.casefold()
        for marker in ("unknown tool", "tool not found", "not offered")
    ):
        return (
            "The provider emitted a native call for a tool that was not "
            "offered in this turn. Inspect the current tool manifest and issue "
            "one changed native tool call using an exact offered tool name; do "
            "not reproduce the call as textual/XML markup."
        )
    if name == "image_generation" and (
        code == "IMAGE_REFERENCE_BUDGET_EXCEEDED"
        or "IMAGE_REFERENCE_BUDGET_EXCEEDED" in error
    ):
        return (
            "The execution layer resolved both Project-owned automatic image "
            "references and explicit call references before provider dispatch, "
            "and their deduplicated total exceeds the active model limit. No "
            "provider call was made and no references were silently dropped. "
            "Read error.details, then call read_project and use jq_project to "
            "remove lower-priority reference IDs from the target variant, "
            "storyboard creation, or lineup fields as appropriate; also shrink "
            "referenceVersionIds/referenceImageUrls in the next call. Re-read "
            "the Project and retry only after the resolved total is within "
            "details.limit. Preserve the identity/storyboard anchors that are "
            "actually essential."
        )
    if name == "r2v_generation" and (
        code == "VIDEO_REFERENCE_BUDGET_EXCEEDED"
        or "VIDEO_REFERENCE_BUDGET_EXCEEDED" in error
    ):
        return (
            "The execution layer resolved the selected storyboard and every "
            "Project-owned exact video reference before task admission, and "
            "their deduplicated image/video counts exceed the active video "
            "model's official limits. No task was created, no media was "
            "uploaded, and no provider call was made. Read error.details for "
            "maxReferenceImages, maxReferenceVideos, maxReferenceMedia, and "
            "the resolved version IDs. Call read_project, then use jq_project "
            "to remove lower-priority character, scene, prop, cast-lineup, or "
            "video_reference_version_ids from the target Element. Preserve "
            "the selected storyboard because it is the required first image, "
            "re-read the Project, and retry only after the resolved counts fit "
            "all three limits."
        )
    capability_unknown_code = {
        "image_generation": "IMAGE_MODEL_CAPABILITY_UNKNOWN",
        "r2v_generation": "VIDEO_MODEL_CAPABILITY_UNKNOWN",
    }.get(name)
    if capability_unknown_code and (
        code == capability_unknown_code or capability_unknown_code in error
    ):
        return (
            "The configured media model name is empty or is an unregistered "
            "gateway alias, so Creator cannot verify its official reference "
            "input limit and failed closed before provider dispatch. Do not "
            "guess a generic limit or repeat the same call. Report the model "
            "configuration problem to the user; references may be retried "
            "only after the configured name is changed or explicitly mapped "
            "to a documented official model capability."
        )
    if name in media_tools and (
        "PROJECT_INPUT_SNAPSHOT_STALE" in error
        or "已终止: QUARANTINED" in error
        or "ended as QUARANTINED" in error
    ):
        # The provider work finished but the Project advanced while it ran
        # (often a review approval of an earlier output), so the frozen
        # input snapshot failed CAS at publish and the Task was
        # quarantined. Replaying the identical call can only hit the same
        # terminated Task — name the fix or the model burns its remaining
        # turns rediscovering it.
        return (
            "The Task was quarantined because the Project changed while it "
            "was running (for example a review was approved), so its input "
            "snapshot went stale; the terminated Task can never be resumed "
            "by resending the same call. Call read_project to load the "
            "current Project state, confirm the target still needs this "
            "output, then issue one fresh " + name + " call so it is "
            "admitted against the current snapshot."
        )
    if name == "r2v_generation" and "real human face" in error.casefold():
        # Provider-side face moderation rejects the uploaded pixels, so
        # resubmitting the same references can never succeed. Identity is
        # already carried by the generated character-design artifacts.
        return (
            "The video provider rejected the uploaded reference images "
            "because they appear to contain real human faces. This is a "
            "provider content policy, not a transient failure — do not "
            "resubmit the same references. Use jq_project to remove every "
            "source-photo reference (asset-version IDs of downloaded or "
            "uploaded real images) from the Element's "
            "video_reference_version_ids, keep only generated "
            "artifact-version references such as the character design and "
            "storyboard images, then call r2v_generation again."
        )
    if name == "image_generation" and any(
        marker in error.casefold()
        for marker in (
            "rejected by the safety system",
            "content policy",
            "content_policy_violation",
        )
    ):
        # The image provider's safety system deterministically rejects the
        # request; identical resubmission can never succeed. The dominant
        # cause in practice is real-person photos travelling as reference
        # images — including into scene/prop generations that do not need
        # any face at all.
        return (
            "The image provider's safety system rejected this request — a "
            "deterministic content policy, not a transient failure; do not "
            "resubmit the same arguments. For scene or prop targets, remove "
            "every reference image that contains a person before retrying. "
            "For character targets, drop real-photo references "
            "(asset-version IDs of downloaded or uploaded images) and use "
            "already generated stylized artifact-version references — or a "
            "text-only prompt — instead, then call image_generation again "
            "with the adjusted references or a rephrased prompt."
        )
    if name == "jq_project":
        return _jq_project_recovery(code)
    if name == "ai_edit":
        return (
            "Use the persisted Runtime Task error as the cause and retry ai_edit with "
            "a new tool call when appropriate. A URL-backed SourceAssetVersion with "
            "file_id=null remains executable when metadata.publicSourceUrl is valid; "
            "do not wait for or infer failure from the display cache."
        )
    return (
        "Use the reported tool or Runtime Task error as the cause, refresh Project "
        "state when relevant, and retry with a new tool call only when the operation "
        "is safe to repeat."
    )


def _specialist_tool_request_id(
    specialist_run_id: str,
    name: str,
    arguments: Mapping[str, Any],
    *,
    invocation_id: str | None = None,
) -> str:
    payload = json.dumps(
        arguments,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity = f"{specialist_run_id}\0{name}\0{payload}"
    if invocation_id is not None:
        identity = f"{identity}\0{invocation_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"specialist-tool-{digest}"


def _specialist_tool_invocation_id(
    specialist_run_id: str,
    name: str,
    arguments: Mapping[str, Any],
    *,
    call_id: str,
) -> str:
    return _specialist_tool_request_id(
        specialist_run_id,
        name,
        arguments,
        invocation_id=call_id if name == "ai_edit" else None,
    )


def _execution_provider_model(
    spec: SpecialistToolSpec,
    tool_arguments: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Snapshot the model an approval actually authorizes.

    The identity must be the *effective* model, not just the configured
    one: image translate runs on ``translate_model`` and the video modes run
    on names derived from the configured base, so pricing and the
    post-approval identity check would otherwise cover a different model
    than the one submitted.
    """

    arguments = tool_arguments or {}
    mode = str(arguments.get("mode") or "").strip().casefold()
    if spec.provider_kind == "image":
        from models.image import get_image_backend

        if mode == "translate":
            from models.config import get_image_translate_model_name

            return "dashscope", get_image_translate_model_name()
        return get_image_backend().casefold(), get_image_model_name()
    if spec.provider_kind == "video":
        from models.video_capabilities import (
            effective_video_model_name,
            video_backend_key,
        )

        backend = get_video_backend()
        configured = get_video_model_name()
        # Same rule as the submit path, so the approval can never name a
        # different model than the billed request (HappyHorse derives even
        # for the default r2v).
        return backend, effective_video_model_name(
            configured,
            mode,
            video_backend_key(configured, backend),
        )
    if spec.provider_kind == "tts":
        from models.config import get_tts_model_name

        return "dashscope", get_tts_model_name()
    if spec.provider_kind == "s2v":
        from models.config import get_s2v_model_name

        return "dashscope", get_s2v_model_name()
    return str(spec.provider_kind or "creator-tool"), "configured"


_AUTHORIZATION_OPERATION_LABELS = {
    "image_generation": "生成图片",
    "r2v_generation": "生成视频",
    "s2v_generation": "生成数字人视频",
    "tts_generation": "生成语音",
    "create_character_voice": "复刻角色音色",
}


def _prompt_preview(tool_arguments: Mapping[str, Any], *, limit: int) -> str:
    prompt = str(tool_arguments.get("prompt") or "").strip()
    if len(prompt) <= limit:
        return prompt
    return prompt[: limit - 1] + "…"


def _authorization_summary(
    spec: SpecialistToolSpec,
    *,
    target_ref: str,
    provider: str,
    model: str,
    tool_arguments: Mapping[str, Any],
) -> str:
    """One human-readable line telling the user exactly what will run.

    Deliberately no price estimate: locally transcribed price tables go
    stale silently and an authoritative-looking wrong number misleads
    worse than no number. Call counts are the honest metric.
    """

    label = _AUTHORIZATION_OPERATION_LABELS.get(spec.name, f"执行 {spec.name}")
    parts = [f"{label}：{target_ref}", f"模型 {provider}/{model}"]
    if spec.provider_kind == "image":
        ratio = str(tool_arguments.get("aspectRatio") or "16:9")
        parts.append(f"画幅 {ratio}")
    elif spec.provider_kind == "video":
        mode = str(tool_arguments.get("mode") or "r2v").strip().casefold()
        duration = tool_arguments.get("durationSeconds")
        if duration:
            # video_edit follows its input video, so name the source of the
            # number the price is computed from.
            parts.append(
                (
                    f"{duration}秒（按输入视频计费）"
                    if mode == "video_edit"
                    else f"{duration}秒"
                ),
            )
        resolution = tool_arguments.get("resolution")
        if resolution:
            parts.append(str(resolution).upper())
        ratio = tool_arguments.get("ratio")
        if ratio:
            parts.append(f"比例 {ratio}")
        if "generateAudio" in tool_arguments:
            parts.append(
                "有声" if tool_arguments.get("generateAudio") else "无声",
            )
    return " · ".join(parts)


__all__ = [
    "FileAgentRuntimeError",
    "FileCreatorAgentRuntime",
    "StaleAgentRun",
]
