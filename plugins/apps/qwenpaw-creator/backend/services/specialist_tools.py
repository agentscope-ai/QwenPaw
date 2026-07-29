# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
"""File-native toolkits owned by Creator specialists.

The Agent runtime consumes this registry as a generic AgentScope tool surface.
Business capabilities stay here: role admission, provider schemas and media
handlers.  Handlers publish through the existing file services, so generated
results update ``project.json``/Asset Index and Runtime records without a SQL
transaction or an overlay ChangeSet.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain.enums import CreatorCommandType, SpecialistRole
from domain.errors import PermissionDeniedError, ValidationError
from services.media_files.image_execution import execute_file_image_command
from services.media_files.motion_design import design_motion_overlays
from services.media_files.r2v_execution import execute_file_r2v_command
from services.project_files.agent_tools import (
    AgentProjectTools,
    agent_project_tool_manifest,
)
from services.project_files.facade import CreatorFileServices
from services.source_analysis import (
    SourceAgentToolContext,
    source_analysis_service,
)


class SpecialistToolWait(StrEnum):
    NONE = "NONE"
    TASK = "TASK"


_PROJECT_ASSETS_TARGET_REF = "project:assets"
_ASSET_TARGET_REF_PATTERN = r"^asset:.+$"
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

    def expands_project_assets_scope(
        self,
        *,
        role: SpecialistRole,
        admitted_target_refs: Sequence[str],
    ) -> bool:
        """Let a visual Project-assets run address its Asset children."""

        return (
            self.name == "image_generation"
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
            return target_ref.startswith("asset:") and bool(target_ref[6:])
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
                        "必须使用本 Project 中已存在的 exact asset:<entityId>，"
                        "不能直接使用 project:assets。"
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
        "aspectRatio": {
            "type": "string",
            "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        },
        "referenceVersionIds": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 5,
            "uniqueItems": True,
        },
    },
    ("prompt",),
)

_R2V_ARGUMENTS = _arguments_schema(
    {
        "prompt": {"type": "string", "minLength": 1},
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
                "视频必须覆盖至少 90% 完整时间线；图片和音频传空数组。" "每段使用整数毫秒半开区间 [startMs,endMs)。"
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
            },
            "additionalProperties": False,
        },
    },
    ("summary", "shots", "entities", "semanticEntries"),
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
            "生成视觉资产或 R2V 分镜图片。只传 Project 中已存在的 exact version id；"
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
            "为已选择真实 storyboard ArtifactVersion 的 R2V Element 提交视频生成；"
            "Runtime 文件任务完成后结果自动写回 Asset Index 与 project.json。"
        ),
        roles=frozenset({SpecialistRole.R2V_GENERATION_DIRECTOR}),
        parameters=_tool_schema(_R2V_ARGUMENTS),
        requires_execution_authorization=True,
        long_running=True,
        wait=SpecialistToolWait.TASK,
        provider_kind="video",
    ),
    SpecialistToolSpec(
        name="design_motion_overlays",
        description=(
            "让视觉设计模型观察目标 Timeline 的真实画面帧做两件事："
            "为每个文字 Overlay（pet_os/interview_summary）生成贴合画面的精美"
            "动态字幕卡样式，写入该 Element 的 creation.motion（渲染失败自动回退"
            "固定气泡模板）；再从全片挑选少数最值得装饰的片段（默认最多 3 个），"
            "生成 overlay_kind=motion 的装饰 Overlay Element。全部结果直接写入 "
            "project.json 并返回逐项摘要；写入后可用 read_project 查看，"
            "之后由确定性后端渲染接口把样式与动效合成进成片。"
        ),
        roles=frozenset({SpecialistRole.AI_EDITING_DIRECTOR}),
        parameters=_tool_schema(_MOTION_DESIGN_ARGUMENTS),
        long_running=True,
        provider_kind="vlm",
    ),
)

_SPECS_BY_NAME = {item.name: item for item in _SPECS}
_PROJECT_TOOL_NAMES = frozenset(
    item["function"]["name"] for item in agent_project_tool_manifest()
)


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
        business_tools = [
            spec.manifest(role=role, admitted_target_refs=admitted_target_refs)
            for spec in _SPECS
            if role in spec.roles
        ]
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
            raise PermissionDeniedError(
                "Specialist tool targetRef 不在本 Run 准入范围",
            )
        payload = arguments.get("arguments")
        if not isinstance(payload, Mapping):
            raise ValidationError("Specialist tool arguments 必须是 object")

        if name in {"transcribe_source_audio", "commit_source_intelligence"}:
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

        if name == "image_generation":
            command = (
                CreatorCommandType.GENERATE_ASSET
                if role is SpecialistRole.VISUAL_DEVELOPMENT
                else CreatorCommandType.GENERATE_STORYBOARD_IMAGE
            )
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
