# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
"""File-native toolkits owned by Creator specialists.

The Agent runtime consumes this registry as a generic AgentScope tool surface.
Business capabilities stay here: role admission, provider schemas and media
handlers.  Handlers publish through the existing file services, so generated
results update ``project.json``/Asset Index and Runtime records without a SQL
transaction or an overlay ChangeSet.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain.enums import CreatorCommandType, SpecialistRole, TaskKind
from domain.errors import PermissionDeniedError, ValidationError
from models.config import (
    get_image_model_name,
    is_s2v_configured,
    is_tts_configured,
)
from models.image.base import image_reference_limit
from services.runtime_files.errors import RecordNotFoundError
from services.media.source_observation import source_observation_service
from services.media.source_video_reader import source_video_reader_service
from services.media.source_memory import (
    QUERY_TYPES as _MEMORY_QUERY_TYPES,
    source_memory_service,
)
from services.media_files.audio_execution import (
    execute_file_tts_command,
    execute_file_voice_enrollment_command,
)
from services.media_files.image_execution import execute_file_image_command
from services.media_files.motion_design import design_motion_overlays
from services.media_files.r2v_execution import (
    execute_file_r2v_command,
    execute_file_s2v_command,
)
from services.project_files.agent_tools import (
    AgentProjectTools,
    agent_project_tool_manifest,
)
from services.project_files.facade import CreatorFileServices
from services.source_analysis import (
    SourceAgentToolContext,
    source_analysis_service,
)

logger = logging.getLogger("creator.specialist_tools")


def _unique_prefix_correction(
    target_ref: str,
    admitted_target_refs: Sequence[str],
) -> str | None:
    """Resolve one mistyped ref against the admitted set, or ``None``.

    Content-addressed refs share a long structural prefix (for example
    ``asset:asset-`` plus hex); a model transcription slip usually keeps
    a long head intact and corrupts a later run. The correction demands
    at least 8 characters beyond the longest structural prefix shared
    across the admitted set, and exactly one candidate — anything less
    stays a hard rejection.
    """

    ref = target_ref.strip()
    if not ref or not admitted_target_refs:
        return None
    structural = admitted_target_refs[0]
    for candidate in admitted_target_refs[1:]:
        limit = min(len(structural), len(candidate))
        keep = 0
        while keep < limit and structural[keep] == candidate[keep]:
            keep += 1
        structural = structural[:keep]
    required = len(structural) + 8
    matches = []
    for candidate in admitted_target_refs:
        limit = min(len(ref), len(candidate))
        shared = 0
        while shared < limit and ref[shared] == candidate[shared]:
            shared += 1
        if shared >= required:
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0]
    return None


class SpecialistToolWait(StrEnum):
    NONE = "NONE"
    TASK = "TASK"
    # The tool returns a batch of task ids; the driver awaits them all in
    # parallel (or returns a status snapshot when the model asks not to
    # wait), so total latency is the max of the batch, not the sum.
    TASK_LIST = "TASK_LIST"


_PROJECT_ASSETS_TARGET_REF = "project:assets"
_ASSET_TARGET_REF_PATTERN = r"^(asset|lineup):.+$"
_SOURCE_PROJECT_TOOL_NAMES = frozenset({"read_project", "read_project_file"})


@dataclass(frozen=True, slots=True)
class SpecialistToolSpec:
    name: str
    description: str
    roles: frozenset[SpecialistRole]
    parameters: Mapping[str, Any]
    requires_execution_authorization: bool = False
    long_running: bool = False
    wait: SpecialistToolWait = SpecialistToolWait.NONE
    provider_kind: str | None = None
    # Tools that may skip the inline TASK wait when the model passes
    # background=true (host-style async: submit now, harvest later via
    # check_observation_tasks).
    background_capable: bool = False

    def expands_project_assets_scope(
        self,
        *,
        role: SpecialistRole,
        admitted_target_refs: Sequence[str],
    ) -> bool:
        """Let a visual Project-assets run address its Asset children."""

        return (
            self.name in {"image_generation", "create_character_voice"}
            and role is SpecialistRole.VISUAL_DEVELOPMENT
            and _PROJECT_ASSETS_TARGET_REF in admitted_target_refs
        )

    def admits_target_ref(
        self,
        *,
        role: SpecialistRole,
        target_ref: str,
        admitted_target_refs: Sequence[str],
    ) -> bool:
        if self.expands_project_assets_scope(
            role=role,
            admitted_target_refs=admitted_target_refs,
        ):
            # Cast lineups are visual assets too: a Project-assets run may
            # generate the group anchor alongside individual entity images.
            return (
                target_ref.startswith("asset:") and bool(target_ref[6:])
            ) or (target_ref.startswith("lineup:") and bool(target_ref[7:]))
        return target_ref in admitted_target_refs

    def manifest(
        self,
        *,
        role: SpecialistRole,
        admitted_target_refs: Sequence[str],
    ) -> dict[str, Any]:
        value = provider_function(
            self.name,
            {"description": self.description, "parameters": self.parameters},
        )
        targets = tuple(dict.fromkeys(admitted_target_refs))
        if targets:
            target = value["function"]["parameters"]["properties"].get(
                "targetRef",
            )
            if isinstance(target, dict):
                if self.expands_project_assets_scope(
                    role=role,
                    admitted_target_refs=targets,
                ):
                    target["pattern"] = _ASSET_TARGET_REF_PATTERN
                    target["description"] = (
                        "必须使用本 Project 中已存在的 exact "
                        "asset:<VisualEntity.entity_id>（或阵容图 "
                        "lineup:<VisualCastLineup.lineup_id>），不能直接使用 "
                        "project:assets，也不能使用来源素材 logicalAssetId；"
                        "来源素材版本只能放在 arguments.referenceVersionIds。"
                    )
                else:
                    target["enum"] = list(targets)
                    target[
                        "description"
                    ] = "必须逐字使用本 SpecialistRun 已准入的 targetRef。"
        return value


def provider_function(
    name: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one native AgentScope/OpenAI function descriptor."""

    description = str(definition.get("description") or "").strip()
    parameters = definition.get("parameters")
    if not description or not isinstance(parameters, Mapping):
        raise ValidationError(f"非法 Specialist tool schema: {name}")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": deepcopy(dict(parameters)),
        },
    }


@dataclass(frozen=True, slots=True)
class SpecialistToolResult:
    payload: dict[str, Any]
    task_id: str | None = None
    task_ids: tuple[str, ...] = ()


def _arguments_schema(
    properties: Mapping[str, Any],
    required: Sequence[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


def _tool_schema(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "projectId": {"type": "string", "minLength": 1},
            "targetRef": {"type": "string", "minLength": 1},
            "arguments": dict(arguments),
        },
        "required": ["projectId", "targetRef", "arguments"],
        "additionalProperties": False,
    }


_IMAGE_ARGUMENTS = _arguments_schema(
    {
        "prompt": {"type": "string", "minLength": 1},
        "mode": {
            "type": "string",
            "enum": ["generate", "edit", "translate"],
            "description": (
                "图像操作模式，缺省 generate（文生图，可附参考图）。"
                "edit：按 prompt 指令编辑 referenceImageRefs 指定的 1–3 张图；"
                "translate：翻译图内文字并保留排版（仅需 1 张图，prompt 不参与"
                "生成）。edit/translate 仅 DashScope qwen-image provider 支持。"
            ),
        },
        "referenceImageRefs": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 3,
            "uniqueItems": True,
            "description": (
                "edit/translate 模式的输入图：传本 Project 已存在的 exact "
                "version id（edit 1–3 张，translate 恰 1 张）。"
            ),
        },
        "sourceLang": {
            "type": "string",
            "description": "translate 模式的源语种（如 zh/en），缺省 auto 自动检测。",
        },
        "targetLang": {
            "type": "string",
            "description": "translate 模式的目标语种（如 zh/en），缺省 en。",
        },
        "aspectRatio": {
            "type": "string",
            "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        },
        "referenceVersionIds": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "variantId": {
            "type": "string",
            "minLength": 1,
            "description": (
                "生成视觉资产时指定稳定的 VisualVariant ID；目标实体包含多个 "
                "Variant 时必填。分镜图生成不使用此字段。"
            ),
        },
    },
    ("prompt",),
)

_R2V_ARGUMENTS = _arguments_schema(
    {
        "prompt": {"type": "string", "minLength": 1},
        "mode": {
            "type": "string",
            "enum": ["r2v", "t2v", "i2v", "video_edit"],
            "description": (
                "视频生成模式，缺省 r2v（storyboard + 参考图，保持现状）。"
                "t2v：纯文本生视频；i2v：首帧生视频（需 firstFrameRef）；"
                "video_edit：按 prompt 指令编辑已有视频（需 videoRef，仅 "
                "HappyHorse 模型）。支持的组合以当前模型的能力矩阵为准，"
                "不支持时会返回可读错误并提示替代。"
            ),
        },
        "firstFrameRef": {
            "type": "string",
            "minLength": 1,
            "description": (
                "i2v 模式必传：首帧图的 exact version id（可用已选定的 "
                "storyboard 版本）；画幅跟随首帧。"
            ),
        },
        "videoRef": {
            "type": "string",
            "minLength": 1,
            "description": (
                "video_edit 模式必传：输入视频的 exact version id。输入需 "
                "3–60 秒，超过 15 秒时上游自动只取前 15 秒，输出时长跟随输入。"
            ),
        },
        "durationSeconds": {"type": "integer", "minimum": 1, "maximum": 60},
        "ratio": {
            "type": "string",
            "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        },
        "resolution": {
            "type": "string",
            "enum": ["720P", "1080P", "720p", "1080p"],
        },
        "watermark": {
            "type": "boolean",
            "default": False,
            "description": "默认 false（无水印）；仅在用户明确要求时传 true",
        },
        "generateAudio": {"type": "boolean"},
    },
    ("prompt", "durationSeconds", "ratio", "resolution"),
)

_SOURCE_SHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "startMs": {"type": "integer", "minimum": 0},
        "endMs": {"type": "integer", "minimum": 1},
        "description": {"type": "string", "minLength": 1},
        "events": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["startMs", "endMs", "description", "events", "confidence"],
    "additionalProperties": False,
}

_SOURCE_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "startMs": {"type": "integer", "minimum": 0},
        "endMs": {"type": "integer", "minimum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["kind", "label", "description", "confidence"],
    "additionalProperties": False,
}

_SOURCE_SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1},
        "tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "startMs": {"type": "integer", "minimum": 0},
        "endMs": {"type": "integer", "minimum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["text", "tags", "confidence"],
    "additionalProperties": False,
}

_SOURCE_COMMIT_ARGUMENTS = _arguments_schema(
    {
        "summary": {
            "type": "string",
            "minLength": 1,
            "description": (
                "外层 VLM 基于原生媒体形成的详尽全局理解，覆盖主体、场景、动作、" "镜头语言、风格、质量变化、异常与不确定内容。"
            ),
        },
        "shots": {
            "type": "array",
            "items": _SOURCE_SHOT_SCHEMA,
            "description": (
                "视频必须覆盖至少 90% 完整时间线；图片和音频传空数组；"
                "文档按页伪时间线提交（有页图时每渲染页恰好一条）。"
                "每段使用整数毫秒半开区间 [startMs,endMs)。"
            ),
        },
        "entities": {
            "type": "array",
            "items": _SOURCE_ENTITY_SCHEMA,
            "description": "主体、人物、动物、物体、场景元素及其可观察特征。",
        },
        "semanticEntries": {
            "type": "array",
            "items": _SOURCE_SEMANTIC_SCHEMA,
            "description": ("可检索、可剪辑的事件级与细节级语义。视频/音频每条必须含时间范围；" "图片不得填写时间范围。"),
        },
        "moduleResultRefs": {
            "type": "object",
            "properties": {
                "asr": {
                    "type": "string",
                    "minLength": 1,
                    "description": "transcribe_source_audio 返回的 opaque resultRef。",
                },
                "document": {
                    "type": "string",
                    "minLength": 1,
                    "description": "read_document 返回的 opaque resultRef；文档 Source 提交时必填。",
                },
            },
            "additionalProperties": False,
        },
    },
    ("summary", "shots", "entities", "semanticEntries"),
)

_TTS_ARGUMENTS = _arguments_schema(
    {
        "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 800,
            "description": ("要合成的台词或旁白文本；单次上限约 512 token，超长文案按句子" "拆分后分次生成。"),
        },
        "voice": {
            "type": "string",
            "description": "可选系统音色名；省略时使用已配置的默认音色。",
        },
        "characterRef": {
            "type": "string",
            "description": (
                "可选；传已存在的 exact asset:<entityId>（character 实体）。"
                "该角色已绑定音色时自动改用其复刻音色合成。"
            ),
        },
        "speechRate": {
            "type": "number",
            "minimum": 0.5,
            "maximum": 2.0,
            "description": (
                "可选语速倍率（默认 1.0）；仅 CosyVoice 系列模型支持，"
                "其它模型传非 1.0 值会报错，请改用增删文稿控制时长。"
            ),
        },
        "label": {
            "type": "string",
            "description": "可选的音频资产名称。",
        },
    },
    ("text",),
)

_VOICE_ENROLLMENT_ARGUMENTS = _arguments_schema(
    {
        "characterRef": {
            "type": "string",
            "description": (
                "目标 character 实体的 exact asset:<entityId>；targetRef 不是角色"
                "实体时（如 project:assets 场景）必填。"
            ),
        },
        "voicePrompt": {
            "type": "string",
            "maxLength": 300,
            "description": (
                "根据角色设定写的音色描述（如「低沉沙哑的中年男声，语速缓慢」），"
                "无需音频样本即可设计专属音色。与 sampleSourceVersionId / "
                "sampleText 三选一；三者都未传时报错。"
            ),
        },
        "previewText": {
            "type": "string",
            "maxLength": 200,
            "description": (
                "voicePrompt 设计时的试听文本，至少 15 个字；省略时自动用角色" "名与描述拼一句。"
            ),
        },
        "sampleSourceVersionId": {
            "type": "string",
            "description": (
                "可选；已存在的 exact 音频 SourceAssetVersion id 作为 10–20 秒"
                "音色样本（复刻路径）。"
            ),
        },
        "sampleText": {
            "type": "string",
            "maxLength": 200,
            "description": ("可选；先用系统音色合成这段试音文本作为样本再复刻；仅当前" "模型有系统音色时可用。"),
        },
        "voice": {
            "type": "string",
            "description": "可选；sampleText 试音时使用的系统音色。",
        },
        "preferredName": {
            "type": "string",
            "description": "可选的音色名称前缀；省略时使用角色名。",
        },
    },
    (),
)

_S2V_ARGUMENTS = _arguments_schema(
    {
        "characterImageRef": {
            "type": "string",
            "minLength": 1,
            "description": (
                "人像图的 exact version id（单人、正脸、清晰，单边 400–7000px，"
                "支持真人/卡通）。缺省时使用目标 Element "
                "creation.portrait_version_id 声明的人物图。工具会先跑免费的"
                "人像检测，未通过时直接返回原因且不产生费用。"
            ),
        },
        "audioAssetRef": {
            "type": "string",
            "minLength": 1,
            "description": (
                "驱动音频的 exact 音频 version id，可直接使用 tts_generation "
                "产出的 audio version（含复刻音色合成）；缺省时使用目标 "
                "Element creation.audio_version_id 声明的音频；建议 ≤20 秒人声。"
            ),
        },
        "resolution": {
            "type": "string",
            "enum": ["480P", "720P"],
            "description": "输出分辨率，缺省 480P（更快更便宜）。",
        },
    },
    (),
)

_READ_DOCUMENT_ARGUMENTS = _arguments_schema(
    {
        "fileRef": {
            "type": "string",
            "minLength": 1,
            "description": (
                "当前 Source 选中的 exact asset-version:<versionId>，逐字使用；"
                "超出本 Run 准入边界的引用会被拒绝。"
            ),
        },
        "pages": {
            "type": "string",
            "description": ('1-based 页范围，如 "1-5" 或 "1,3,5-8"；省略时渲染前 20 页。'),
        },
        "budget": {
            "type": "string",
            "enum": ["small", "normal", "large"],
            "description": "页图分辨率预算，缺省 normal。",
        },
    },
    ("fileRef",),
)

_MEMORY_QUERY_ARGUMENTS = _arguments_schema(
    {
        "queryType": {
            "type": "string",
            "enum": list(_MEMORY_QUERY_TYPES),
            "description": (
                "summary/super_events/macro_events 看层次概览；"
                "subgraph 下钻单个 macro；search_nodes/search_ocr/"
                "search_asr 语义与文本检索；by_time 按时间窗；"
                "enumerate 计数/枚举候选。"
            ),
        },
        "query": {
            "type": "string",
            "minLength": 1,
            "description": (
                "search_*/enumerate 必传的检索文本。用陈述句描述目标内容，"
                "不要写问句；多目标问题只取各选项共享的信息，排除彼此"
                "分歧的细节。"
            ),
        },
        "nodeTypes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "entity",
                    "event",
                    "on_screen_text",
                    "asr_text",
                ],
            },
            "uniqueItems": True,
        },
        "macroId": {
            "type": "string",
            "minLength": 1,
            "description": (
                "subgraph 必传目标 macro_id；macro_events 可传 "
                "super_XX 只列该 SuperEvent 下的 macros。"
            ),
        },
        "startMs": {"type": "integer", "minimum": 0},
        "endMs": {"type": "integer", "minimum": 1},
        "topK": {"type": "integer", "minimum": 1, "maximum": 50},
        "minCosine": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": (
                "仅 enumerate：密集命中的余弦阈值（默认 0.5）；枚举结果" "疑似漏计时调低后重试。"
            ),
        },
        "maxResults": {
            "type": "integer",
            "minimum": 1,
            "maximum": 300,
            "description": "仅 enumerate：枚举条目上限（默认 120）。",
        },
        "scope": {
            "type": "string",
            "enum": ["source", "project"],
            "description": (
                "默认 source 只查当前素材；project 合并项目内全部已构建"
                "记忆跨素材检索（结果 ID 带来源前缀，hitWindowsMs 附 "
                "assetId；by_time 不支持）。"
            ),
        },
    },
    ("queryType",),
)

_OBSERVE_CLIP_ARGUMENTS = _arguments_schema(
    {
        "startMs": {
            "type": "integer",
            "minimum": 0,
            "description": "观察窗口在源素材时间轴上的起点（毫秒）。",
        },
        "endMs": {
            "type": "integer",
            "minimum": 1,
            "description": (
                "观察窗口终点（毫秒）。窗口上限 120 秒：更宽的问题先用 "
                "query_source_memory 定位到窄窗后逐窗核验。"
            ),
        },
        "question": {
            "type": "string",
            "minLength": 1,
            "description": (
                "对这段原片要核验/回答的具体问题，带上待验证的结论本身，"
                "例如：‘记忆检索称此处出现主角摔倒，画面中是否属实，"
                "具体发生在哪个时刻？’"
            ),
        },
        "background": {
            "type": "boolean",
            "description": (
                "true=立即返回 taskId 不等待，可在同一回合并行提交多个"
                "互相独立的观察，之后用 check_observation_tasks 一次性"
                "收割；false（默认）=等待完成后直接返回答案。"
            ),
        },
    },
    ("startMs", "endMs", "question"),
)

_READ_SOURCE_VIDEO_ARGUMENTS = _arguments_schema(
    {
        "fps": {
            "type": "number",
            "minimum": 0,
            "description": ("采样帧率；0（默认）按窗口时长自动选择。窄窗口细看时" "可传 1-2。"),
        },
        "budget": {
            "type": "string",
            "enum": ["small", "normal", "large"],
            "description": (
                "单帧分辨率预算：small(~288px) 粗扫全片定位，"
                "normal(~512px) 默认，large(~1024px) 看清局部细节。"
            ),
        },
        "startMs": {"type": "integer", "minimum": 0},
        "endMs": {"type": "integer", "minimum": 1},
        "maxFrames": {
            "type": "integer",
            "minimum": 2,
            "maximum": 64,
            "description": "抽帧上限（默认 32）。",
        },
        "background": {
            "type": "boolean",
            "description": (
                "true=立即返回 taskId 不等待（帧图在 "
                "check_observation_tasks 收割时注入）；适合对多个素材"
                "并行粗扫。false（默认）=等待完成，帧图随本回合注入。"
            ),
        },
    },
    (),
)

_CHECK_OBSERVATION_ARGUMENTS = _arguments_schema(
    {
        "taskIds": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "description": (
                "要收割的观察任务 id（observe_source_clip / "
                "read_source_video 以 background=true 提交时返回）。"
            ),
        },
        "wait": {
            "type": "boolean",
            "description": (
                "true（默认）=并行等待全部任务到终态后返回结果；" "false=立即返回当前状态快照，不等待。"
            ),
        },
    },
    ("taskIds",),
)

_REVIEW_SCENE_ARGUMENTS = _arguments_schema(
    {
        "sceneId": {
            "type": "string",
            "minLength": 1,
            "description": "edit_plan.scene_ledger 中的 scene_id。",
        },
    },
    ("sceneId",),
)

_MOTION_DESIGN_ARGUMENTS = _arguments_schema(
    {
        "brief": {
            "type": "string",
            "description": "整体包装风格要求，例如节奏、情绪、配色倾向。",
        },
        "theme": {
            "type": "string",
            "enum": ["comic_patrol", "soft_journal", "neon_night"],
            "description": ("全片统一视觉主题；默认 comic_patrol。所有 OS 与装饰沿用同一主题。"),
        },
        "elementIds": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 24,
            "uniqueItems": True,
            "description": (
                "只处理这些 Element：文字 Overlay Element ID 表示只为其生成样式，"
                "Edit Element ID 表示只为其设计装饰动效；"
                "省略时自动处理全部文字 Overlay 并稀疏挑选装饰片段。"
            ),
        },
        "maxDecorations": {
            "type": "integer",
            "minimum": 0,
            "maximum": 8,
            "description": "装饰动效名额上限（默认 3）。装饰是锦上添花，只在少数关键片段出现；0 表示只做文字 Overlay 样式、不加装饰。",
        },
        "captionStyle": {
            "type": "string",
            "enum": ["varied", "uniform"],
            "description": (
                "字幕卡样式策略：varied（默认）逐卡生成式设计、蓝图轮换，"
                "适合宠物 OS/综艺台词卡；uniform 全片用同一固定模板确定性"
                "渲染（只换文字，样式逐卡一致），适合教学/解说/纪录片式"
                "旁白字幕；uniform 是全片字幕策略，覆盖所有文字 Overlay，不受 "
                "elementIds 限定。"
            ),
        },
        "sceneStyle": {
            "type": "string",
            "enum": ["generative", "edu_steps"],
            "description": (
                "全画幅 motion_clip 场景的设计策略：generative（默认）由模型"
                "自由生成 HTML；edu_steps 用确定性教学推导卡模板（满屏版式、"
                "步骤徽章/上一步/推导行/结果高亮固定骨架），模型只填内容文案，"
                "全片风格绝对一致且文案强制中文；数学/物理等分步讲解视频必须用 "
                "edu_steps。"
            ),
        },
    },
    (),
)

_SPECS = (
    SpecialistToolSpec(
        name="transcribe_source_audio",
        description=(
            "对当前 exact 视频/音频 Source 调用独立 ASR 模块。返回的 transcript 是"
            "工具权威结果，并附带 opaque resultRef；最终提交时只引用 resultRef，"
            "不要重写或伪造 transcript。ASR 未配置时返回 available=false。"
        ),
        roles=frozenset({SpecialistRole.SOURCE_INTELLIGENCE}),
        parameters=_tool_schema(_arguments_schema({}, ())),
        long_running=True,
        provider_kind="asr",
    ),
    SpecialistToolSpec(
        name="commit_source_intelligence",
        description=(
            "把当前外层素材理解 VLM 自己生成的详尽结构化理解写入不可变 Source "
            "Intelligence 文件。工具不会再次调用 VLM；它只校验时间范围、合并已引用"
            "的 ASR 模块结果、注入真实版本/provenance，并更新 ProjectSource 关联。"
        ),
        roles=frozenset({SpecialistRole.SOURCE_INTELLIGENCE}),
        parameters=_tool_schema(_SOURCE_COMMIT_ARGUMENTS),
    ),
    SpecialistToolSpec(
        name="image_generation",
        description=(
            "生成、编辑或翻译视觉资产 / R2V 分镜图片（mode 选择 generate/edit/"
            "translate）。只传 Project 中已存在的 exact version id；"
            "生成结果由文件媒体服务写入 Asset Index 与 project.json。"
        ),
        roles=frozenset(
            {
                SpecialistRole.VISUAL_DEVELOPMENT,
                SpecialistRole.R2V_GENERATION_DIRECTOR,
            },
        ),
        parameters=_tool_schema(_IMAGE_ARGUMENTS),
        requires_execution_authorization=True,
        long_running=True,
        provider_kind="image",
    ),
    SpecialistToolSpec(
        name="r2v_generation",
        description=(
            "视频生成（多模式）：默认为已选择真实 storyboard ArtifactVersion 的 "
            "R2V Element 提交参考生视频；mode 可切换 t2v / i2v / video_edit"
            "（视当前视频模型能力矩阵而定）。Runtime 文件任务完成后结果自动"
            "写回 Asset Index 与 project.json。"
        ),
        roles=frozenset({SpecialistRole.R2V_GENERATION_DIRECTOR}),
        parameters=_tool_schema(_R2V_ARGUMENTS),
        requires_execution_authorization=True,
        long_running=True,
        wait=SpecialistToolWait.TASK,
        provider_kind="video",
    ),
    SpecialistToolSpec(
        name="s2v_generation",
        description=(
            "数字人口型视频（wan2.2-s2v）：用一张角色人像图 + 一段音频生成"
            "对口型说话视频，写回目标 R2V Element 的主视频槽。提交前自动先跑"
            "人像检测（按成功请求计费，远低于生成费用；检测未通过不会提交"
            "生成）；audioAssetRef 直接消费 tts_generation 产出的 audio version。"
        ),
        roles=frozenset({SpecialistRole.R2V_GENERATION_DIRECTOR}),
        parameters=_tool_schema(_S2V_ARGUMENTS),
        requires_execution_authorization=True,
        long_running=True,
        wait=SpecialistToolWait.TASK,
        provider_kind="s2v",
    ),
    SpecialistToolSpec(
        name="query_source_memory",
        description=(
            "查询当前 exact Source 已构建的长素材层次图记忆，按台词/"
            "语义/屏幕文字/时间定位片段。返回 JSON 结果与命中 macro 的 "
            "hitWindowsMs 时间窗；结论必须回到原片对应窄窗核验。未构建"
            "记忆时返回 available=false。"
        ),
        roles=frozenset({SpecialistRole.SOURCE_INTELLIGENCE}),
        parameters=_tool_schema(_MEMORY_QUERY_ARGUMENTS),
    ),
    SpecialistToolSpec(
        name="observe_source_clip",
        description=(
            "回原片核验：按时间窗从当前 exact Source 的原始媒体抽出连续"
            "片段，由 VLM 真实观看后回答问题并附时间戳证据。"
            "query_source_memory 的 hitWindowsMs 结论在用于剪辑选段前必须"
            "经本工具逐窗核验；窗口 0.5–120 秒。"
        ),
        roles=frozenset(
            {
                SpecialistRole.SOURCE_INTELLIGENCE,
                SpecialistRole.AI_EDITING_DIRECTOR,
            },
        ),
        parameters=_tool_schema(_OBSERVE_CLIP_ARGUMENTS),
        long_running=True,
        wait=SpecialistToolWait.TASK,
        provider_kind="vlm",
        background_capable=True,
    ),
    SpecialistToolSpec(
        name="read_source_video",
        description=(
            "按需观看源素材（先粗看再细看）：从当前 exact Source 的原始"
            "视频按动态分辨率/帧率抽帧，帧序列带时间戳以原生图片进入你的"
            "下一条消息。典型用法：budget=small 不传时间窗扫全片建立定位，"
            "再对命中段用 budget=large + 时间窗细看；需要连续动态细节时"
            "改用 observe_source_clip。"
        ),
        roles=frozenset(
            {
                SpecialistRole.SOURCE_INTELLIGENCE,
                SpecialistRole.AI_EDITING_DIRECTOR,
            },
        ),
        parameters=_tool_schema(_READ_SOURCE_VIDEO_ARGUMENTS),
        long_running=True,
        wait=SpecialistToolWait.TASK,
        background_capable=True,
    ),
    SpecialistToolSpec(
        name="check_observation_tasks",
        description=(
            "收割以 background=true 提交的观察任务（observe_source_clip /"
            " read_source_video）：wait=true（默认）并行等待全部任务完成后"
            "返回各自结果（read 任务的帧图随之注入）；wait=false 立即返回"
            "状态快照。提交的后台任务必须在结束工作前收割。"
        ),
        roles=frozenset(
            {
                SpecialistRole.SOURCE_INTELLIGENCE,
                SpecialistRole.AI_EDITING_DIRECTOR,
            },
        ),
        parameters=_tool_schema(_CHECK_OBSERVATION_ARGUMENTS),
        long_running=True,
        wait=SpecialistToolWait.TASK_LIST,
    ),
    SpecialistToolSpec(
        name="review_scene",
        description=(
            "场景级预审锁定（scene-loop）：对 edit_plan.scene_ledger 中的一个"
            "场景做六项检查（零渲染：证据来自源素材关键帧与动效文档事实）。"
            "通过则把该行置为 locked 并记录内容指纹；不通过返回逐项 findings。"
            "master 合成前全部声明场景必须 locked；段内 Element 变更会使锁失效。"
        ),
        roles=frozenset({SpecialistRole.AI_EDITING_DIRECTOR}),
        parameters=_tool_schema(_REVIEW_SCENE_ARGUMENTS),
        long_running=True,
        provider_kind="vlm",
        wait=SpecialistToolWait.TASK,
    ),
    SpecialistToolSpec(
        name="design_motion_overlays",
        description=(
            "让视觉设计模型观察目标 Timeline 的真实画面帧做两件事："
            "为每个台词卡 Overlay（text 非空）生成贴合画面的精美"
            "动态字幕卡样式，写入该 Element 的 creation.motion（渲染失败自动回退"
            "固定气泡模板）；再从全片挑选少数最值得装饰的片段（默认最多 3 个），"
            "生成无文字的装饰 Overlay Element（text 为空）。全部结果直接写入 "
            "project.json 并返回逐项摘要；写入后可用 read_project 查看，"
            "之后由确定性后端渲染接口把样式与动效合成进成片。"
        ),
        roles=frozenset({SpecialistRole.AI_EDITING_DIRECTOR}),
        parameters=_tool_schema(_MOTION_DESIGN_ARGUMENTS),
        long_running=True,
        provider_kind="vlm",
    ),
    SpecialistToolSpec(
        name="tts_generation",
        description=(
            "把一段台词或旁白文本合成为语音，结果作为不可变音频 SourceAssetVersion "
            "写入 Asset Index，返回 exact version id 与 durationSeconds。长旁白"
            "按镜头/语义分段多次调用，每段对应一个独立 audio Element。传 "
            "characterRef 且该角色已绑定音色时自动使用其复刻音色；上 Timeline "
            "需再用 jq_project 创建引用该 version 的 audio Element。"
        ),
        roles=frozenset(
            {
                SpecialistRole.VISUAL_DEVELOPMENT,
                SpecialistRole.AI_EDITING_DIRECTOR,
            },
        ),
        parameters=_tool_schema(_TTS_ARGUMENTS),
        requires_execution_authorization=True,
        long_running=True,
        provider_kind="tts",
    ),
    SpecialistToolSpec(
        name="create_character_voice",
        description=(
            "为目标 character 实体创建专属音色并绑定到该实体。两条路径：传 "
            "voicePrompt 根据角色设定直接设计音色（无需样本），或传 "
            "sampleSourceVersionId / sampleText 从音频样本复刻。绑定后该角色的"
            " tts_generation 自动沿用此音色，重新创建会替换旧绑定。"
        ),
        roles=frozenset({SpecialistRole.VISUAL_DEVELOPMENT}),
        parameters=_tool_schema(_VOICE_ENROLLMENT_ARGUMENTS),
        requires_execution_authorization=True,
        long_running=True,
        provider_kind="tts",
    ),
    SpecialistToolSpec(
        name="read_document",
        description=(
            "把当前 exact 文档 Source（PDF/Office/表格/字幕/纯文本等）渲染为"
            "逐页页图与文本摘要。页图由 Runtime 落盘并在下一条消息中以原生图片"
            "送入你的上下文；返回的 resultRef 是工具权威结果，提交素材理解时通过 "
            "moduleResultRefs.document 引用，不要重写或伪造页图内容。"
        ),
        roles=frozenset({SpecialistRole.SOURCE_INTELLIGENCE}),
        parameters=_tool_schema(_READ_DOCUMENT_ARGUMENTS),
        long_running=True,
        provider_kind="document",
    ),
)

_SPECS_BY_NAME = {item.name: item for item in _SPECS}
_TTS_TOOL_NAMES = frozenset({"tts_generation", "create_character_voice"})
_S2V_TOOL_NAMES = frozenset({"s2v_generation"})
_PROJECT_TOOL_NAMES = frozenset(
    item["function"]["name"] for item in agent_project_tool_manifest()
)


def _tool_available(name: str) -> bool:
    """Config-gated dynamic registration: unconfigured keys hide tools."""

    if name in _TTS_TOOL_NAMES:
        return is_tts_configured()
    if name in _S2V_TOOL_NAMES:
        return is_s2v_configured()
    return True


class FileSpecialistToolRegistry:
    """Role-scoped AgentScope tool registry for the file Project model."""

    def __init__(self, services: CreatorFileServices) -> None:
        self.services = services

    def spec_for(
        self,
        role: SpecialistRole,
        name: str,
    ) -> SpecialistToolSpec | None:
        spec = _SPECS_BY_NAME.get(name)
        if spec is None:
            return None
        if not _tool_available(name):
            # Key-gated tools are registered dynamically: without a
            # configured key they are absent from every manifest, so treat
            # them as unknown.
            return None
        if role not in spec.roles:
            raise PermissionDeniedError(f"{role.value} 无权调用 {name}")
        return spec

    def manifest_for(
        self,
        role: SpecialistRole,
        *,
        admitted_target_refs: Sequence[str],
    ) -> tuple[dict[str, Any], ...]:
        project_tools = [
            item
            for item in agent_project_tool_manifest()
            if role is not SpecialistRole.SOURCE_INTELLIGENCE
            or item["function"]["name"] in _SOURCE_PROJECT_TOOL_NAMES
        ]
        business_tools = []
        for spec in _SPECS:
            if role not in spec.roles or not _tool_available(spec.name):
                continue
            manifest = spec.manifest(
                role=role,
                admitted_target_refs=admitted_target_refs,
            )
            if spec.name == "image_generation":
                model_name = get_image_model_name().strip()
                reference_limit = image_reference_limit(model_name)
                references = manifest["function"]["parameters"]["properties"][
                    "arguments"
                ]["properties"]["referenceVersionIds"]
                references["maxItems"] = reference_limit or 0
                references["description"] = (
                    f"当前图片模型 {model_name or '未配置'} 的输入参考图，"
                    f"官方上限为 {reference_limit or 0} 张；只传 Project 中"
                    "已存在的 exact version id。未知模型别名按 0 张处理，"
                    "不会套用通用猜测上限。"
                )
            business_tools.append(manifest)
        names = [
            item["function"]["name"]
            for item in (*project_tools, *business_tools)
        ]
        if len(names) != len(set(names)):
            raise RuntimeError(
                "Specialist tool manifest contains duplicate names",
            )
        return tuple(
            deepcopy(item) for item in (*project_tools, *business_tools)
        )

    async def invoke(
        self,
        *,
        role: SpecialistRole,
        name: str,
        arguments: Mapping[str, Any],
        project_id: str,
        admitted_target_refs: Sequence[str],
        project_tools: AgentProjectTools,
        idempotency_key: str,
        context: SourceAgentToolContext | None = None,
    ) -> SpecialistToolResult:
        if name in _PROJECT_TOOL_NAMES:
            payload = await asyncio.to_thread(
                project_tools.invoke,
                name,
                arguments,
            )
            return SpecialistToolResult(payload=dict(payload))

        spec = self.spec_for(role, name)
        if spec is None:
            raise ValidationError(f"Specialist manifest 不存在工具: {name}")
        requested_project_id = str(arguments.get("projectId") or "")
        target_ref = str(arguments.get("targetRef") or "")
        if requested_project_id != project_id:
            raise PermissionDeniedError(
                "Specialist tool attempted another Project",
            )
        if not spec.admits_target_ref(
            role=role,
            target_ref=target_ref,
            admitted_target_refs=admitted_target_refs,
        ):
            corrected = _unique_prefix_correction(
                target_ref,
                admitted_target_refs,
            )
            if corrected is not None and spec.admits_target_ref(
                role=role,
                target_ref=corrected,
                admitted_target_refs=admitted_target_refs,
            ):
                # Long content-addressed ids invite transcription slips
                # (field run 2026-08-09: one flipped hex run burned a
                # whole 18-asset delegation). A unique long-prefix match
                # against the admitted set is deterministic evidence of
                # the intended target, so recover instead of failing the
                # run; ambiguity still fails closed below.
                logger.warning(
                    "specialist targetRef typo corrected: %s -> %s",
                    target_ref,
                    corrected,
                )
                target_ref = corrected
            else:
                raise PermissionDeniedError(
                    "Specialist tool targetRef 不在本 Run 准入范围；"
                    f"收到 {target_ref or '(空)'}。准入目标请逐字符复制，"
                    "不要手抄 ID；本 Run 准入：" + ", ".join(admitted_target_refs[:24]),
                )
        payload = arguments.get("arguments")
        if not isinstance(payload, Mapping):
            raise ValidationError("Specialist tool arguments 必须是 object")

        if name in {
            "transcribe_source_audio",
            "commit_source_intelligence",
            "read_document",
        }:
            if context is None:
                raise ValidationError(
                    f"{name} requires Runtime-owned outer VLM context",
                )

        if name == "transcribe_source_audio":
            result = await source_analysis_service(
                self.services,
            ).transcribe_source_audio(
                project_id=project_id,
                target_ref=target_ref,
                context=context,
            )
            return SpecialistToolResult(payload=dict(result))

        if name == "commit_source_intelligence":
            result = await source_analysis_service(
                self.services,
            ).commit_agent_intelligence(
                project_id=project_id,
                target_ref=target_ref,
                command_id=idempotency_key,
                arguments=payload,
                context=context,
            )
            return SpecialistToolResult(payload=dict(result))

        if name == "read_document":
            result = await source_analysis_service(
                self.services,
            ).read_source_document(
                project_id=project_id,
                target_ref=target_ref,
                arguments=payload,
                context=context,
            )
            return SpecialistToolResult(payload=dict(result))

        if name == "query_source_memory":
            if not target_ref.startswith("asset:") or not target_ref[6:]:
                raise ValidationError(
                    "query_source_memory 只接受 asset:<logicalAssetId>",
                )
            result = await source_memory_service(
                self.services,
            ).query_memory(
                project_id=project_id,
                logical_asset_id=target_ref[6:],
                query_type=str(payload.get("queryType") or ""),
                query=(
                    str(payload["query"])
                    if payload.get("query") is not None
                    else None
                ),
                node_types=(
                    [str(item) for item in payload["nodeTypes"]]
                    if isinstance(payload.get("nodeTypes"), Sequence)
                    and not isinstance(payload.get("nodeTypes"), str)
                    else None
                ),
                macro_id=(
                    str(payload["macroId"])
                    if payload.get("macroId") is not None
                    else None
                ),
                start_ms=(
                    int(payload["startMs"])
                    if payload.get("startMs") is not None
                    else None
                ),
                end_ms=(
                    int(payload["endMs"])
                    if payload.get("endMs") is not None
                    else None
                ),
                top_k=(
                    int(payload["topK"])
                    if payload.get("topK") is not None
                    else None
                ),
                min_cosine=(
                    float(payload["minCosine"])
                    if payload.get("minCosine") is not None
                    else None
                ),
                max_results=(
                    int(payload["maxResults"])
                    if payload.get("maxResults") is not None
                    else None
                ),
                scope=str(payload.get("scope") or "source"),
            )
            return SpecialistToolResult(payload=dict(result))

        if name == "observe_source_clip":
            if not target_ref.startswith("asset:") or not target_ref[6:]:
                raise ValidationError(
                    "observe_source_clip 只接受 asset:<logicalAssetId>",
                )
            task = await source_observation_service(
                self.services,
            ).schedule_observe_clip(
                project_id=project_id,
                logical_asset_id=target_ref[6:],
                start_ms=int(payload["startMs"]),
                end_ms=int(payload["endMs"]),
                question=str(payload["question"]),
                idempotency_key=idempotency_key,
                caused_by_request_id=(
                    context.specialist_run_id if context is not None else None
                ),
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": task.status.value,
                    "taskId": task.task_id,
                },
                task_id=task.task_id,
            )

        if name == "read_source_video":
            if not target_ref.startswith("asset:") or not target_ref[6:]:
                raise ValidationError(
                    "read_source_video 只接受 asset:<logicalAssetId>",
                )
            task = await source_video_reader_service(
                self.services,
            ).schedule_read_source_video(
                project_id=project_id,
                logical_asset_id=target_ref[6:],
                fps=float(payload.get("fps") or 0),
                budget=str(payload.get("budget") or "normal"),
                start_ms=(
                    int(payload["startMs"])
                    if payload.get("startMs") is not None
                    else None
                ),
                end_ms=(
                    int(payload["endMs"])
                    if payload.get("endMs") is not None
                    else None
                ),
                max_frames=int(payload.get("maxFrames") or 32),
                idempotency_key=idempotency_key,
                caused_by_request_id=(
                    context.specialist_run_id if context is not None else None
                ),
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": task.status.value,
                    "taskId": task.task_id,
                },
                task_id=task.task_id,
            )

        if name == "check_observation_tasks":
            # Read-only harvest: validate ownership and kind so a model
            # can never use the harvester to wait on (or leak) tasks that
            # are not its own background observations.
            from services.runtime_files.execution_store import (
                ProjectExecutionStore,
            )

            task_ids = [str(item) for item in payload["taskIds"]]
            executions = ProjectExecutionStore(self.services.root)
            snapshot: list[dict[str, Any]] = []
            for candidate_id in task_ids:
                try:
                    record = await asyncio.to_thread(
                        executions.get_task,
                        project_id,
                        candidate_id,
                    )
                except RecordNotFoundError as exc:
                    raise ValidationError(
                        f"观察任务不存在: {candidate_id}",
                    ) from exc
                if record.kind not in {
                    TaskKind.OBSERVE_SOURCE_CLIP,
                    TaskKind.READ_SOURCE_VIDEO,
                }:
                    raise ValidationError(
                        "check_observation_tasks 只接受 observe_source_clip"
                        f"/read_source_video 任务: {candidate_id} 是 "
                        f"{record.kind.value}",
                    )
                snapshot.append(
                    {
                        "taskId": record.task_id,
                        "status": record.status.value,
                    },
                )
            return SpecialistToolResult(
                payload={"ok": True, "tasks": snapshot},
                task_ids=tuple(task_ids),
            )

        if name == "review_scene":
            if not target_ref.startswith("timeline:"):
                raise ValidationError(
                    "review_scene 只接受 timeline:<timelineId>",
                )
            from services.render_review.scene_review import (
                schedule_review_scene,
            )

            task = await schedule_review_scene(
                self.services,
                project_id=project_id,
                timeline_ref=target_ref,
                scene_id=str(payload["sceneId"]),
                idempotency_key=idempotency_key,
                caused_by_request_id=(
                    context.specialist_run_id if context is not None else None
                ),
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": task.status.value,
                    "taskId": task.task_id,
                },
                task_id=task.task_id,
            )

        if name == "image_generation":
            if target_ref.startswith("lineup:"):
                # The cast lineup is the group anchor; only the visual
                # development role may draw it, storyboard directors
                # consume it through the reference chain instead.
                if role is not SpecialistRole.VISUAL_DEVELOPMENT:
                    raise PermissionDeniedError(
                        "只有视觉开发 Specialist 可以生成阵容图",
                    )
                command = CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE
            elif role is SpecialistRole.VISUAL_DEVELOPMENT:
                command = CreatorCommandType.GENERATE_ASSET
            else:
                command = CreatorCommandType.GENERATE_STORYBOARD_IMAGE
            execution = await execute_file_image_command(
                self.services,
                project_id=project_id,
                command=command,
                target_ref=target_ref,
                arguments=payload,
                idempotency_key=idempotency_key,
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "SUCCEEDED",
                    "taskId": execution.task_id,
                    "artifactVersionId": execution.artifact_version_id,
                    "generation": execution.project_generation,
                    "etag": execution.project_etag,
                    "replayed": execution.replayed,
                },
                task_id=execution.task_id,
            )

        if name == "r2v_generation":
            execution = await execute_file_r2v_command(
                self.services,
                project_id=project_id,
                target_ref=target_ref,
                arguments=payload,
                idempotency_key=idempotency_key,
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "QUEUED",
                    "taskId": execution.task_id,
                    "runId": execution.run_id,
                    "replayed": execution.replayed,
                },
                task_id=execution.task_id,
            )

        if name == "s2v_generation":
            execution = await execute_file_s2v_command(
                self.services,
                project_id=project_id,
                target_ref=target_ref,
                arguments=payload,
                idempotency_key=idempotency_key,
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "QUEUED",
                    "taskId": execution.task_id,
                    "runId": execution.run_id,
                    "replayed": execution.replayed,
                },
                task_id=execution.task_id,
            )

        if name == "tts_generation":
            execution = await execute_file_tts_command(
                self.services,
                project_id=project_id,
                target_ref=target_ref,
                arguments=payload,
                idempotency_key=idempotency_key,
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "SUCCEEDED",
                    "sourceAssetVersionId": execution.source_asset_version_id,
                    "logicalAssetId": execution.logical_asset_id,
                    "durationSeconds": execution.duration_seconds,
                    "voice": execution.voice,
                    "generation": execution.project_generation,
                    "etag": execution.project_etag,
                    "replayed": execution.replayed,
                },
            )

        if name == "create_character_voice":
            enrollment = await execute_file_voice_enrollment_command(
                self.services,
                project_id=project_id,
                target_ref=target_ref,
                arguments=payload,
                idempotency_key=idempotency_key,
            )
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "SUCCEEDED",
                    "entityId": enrollment.entity_id,
                    "voiceBound": True,
                    "voiceOrigin": enrollment.origin,
                    "sampleSourceVersionId": enrollment.sample_source_version_id,
                    "generation": enrollment.project_generation,
                    "etag": enrollment.project_etag,
                    "replayed": enrollment.replayed,
                },
            )

        if name == "design_motion_overlays":
            result = await design_motion_overlays(
                self.services,
                project_id=project_id,
                target_ref=target_ref,
                arguments=payload,
                idempotency_key=idempotency_key,
            )
            return SpecialistToolResult(payload=dict(result))
        raise RuntimeError(f"unhandled Specialist tool: {name}")


__all__ = [
    "FileSpecialistToolRegistry",
    "SpecialistToolResult",
    "SpecialistToolSpec",
    "SpecialistToolWait",
]
