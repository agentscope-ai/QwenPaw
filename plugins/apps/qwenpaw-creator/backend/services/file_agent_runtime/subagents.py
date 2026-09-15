# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""File-native Creator specialist contracts and prompt selection."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.enums import SpecialistRole
from services.file_agent_runtime.prompts import render_file_agent_prompt
from services.file_agent_runtime.prompts import tts_guidance
from services.project_files.models import Project
from services.project_files.schema_prompt import build_project_schema_prompt

DELEGATE_TOOL_NAME = "delegate_to_agent"

_DELEGATABLE_ROLES = (
    SpecialistRole.SOURCE_INTELLIGENCE,
    SpecialistRole.AI_EDITING_DIRECTOR,
)

_ROLE_TARGETS: dict[SpecialistRole, tuple[set[str], set[str]]] = {
    SpecialistRole.SOURCE_INTELLIGENCE: ({"asset"}, set()),
    SpecialistRole.AI_EDITING_DIRECTOR: ({"timeline"}, set()),
}

_TARGET_GUIDANCE = {
    SpecialistRole.SOURCE_INTELLIGENCE: "asset:<logicalAssetId>",
    SpecialistRole.AI_EDITING_DIRECTOR: "an existing timeline:<id>",
}

_ROLE_PROMPT_IDS = {
    SpecialistRole.SOURCE_INTELLIGENCE: "source_intelligence_agent.system",
    SpecialistRole.AI_EDITING_DIRECTOR: "ai_editing_director.system",
}


class DelegateToAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    role: SpecialistRole
    target_refs: list[str] = Field(alias="target_refs", min_length=1)
    task: str = Field(min_length=1)

    @field_validator("target_refs")
    @classmethod
    def validate_unique_target_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("target_refs must contain unique values")
        return value

    def validate_contract(self, *, project_id: str) -> None:
        del project_id
        if self.role not in _DELEGATABLE_ROLES:
            raise ValueError(
                f"specialist role is not delegatable: {self.role.value}",
            )
        if (
            self.role is SpecialistRole.SOURCE_INTELLIGENCE
            and len(self.target_refs) > 1
        ):
            # A batched delegation reads every image in the same model turn
            # and blows the per-turn wall-clock budget; per-asset runs
            # execute in parallel instead.
            raise ValueError(
                "source_intelligence_agent accepts exactly one asset target "
                "per delegation; delegate each asset separately — the runs "
                "execute in parallel.",
            )
        allowed_kinds, allowed_project_targets = _ROLE_TARGETS[self.role]
        for target_ref in self.target_refs:
            kind, separator, identifier = target_ref.partition(":")
            if not separator or not identifier or kind not in allowed_kinds:
                raise ValueError(
                    f"{self.role.value} does not allow targetRef {target_ref!r}; "
                    f"use {_TARGET_GUIDANCE[self.role]}",
                )
            if kind == "project" and identifier not in allowed_project_targets:
                raise ValueError(
                    f"{self.role.value} does not allow targetRef {target_ref!r}; "
                    f"use {_TARGET_GUIDANCE[self.role]}",
                )


def delegate_tool_manifest() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": DELEGATE_TOOL_NAME,
            "description": (
                "把一个边界明确的素材理解或 AI 剪辑任务委派给对应 Creator "
                "Specialist。source_intelligence_agent 使用 asset:<logicalAssetId>，"
                "且每次委派恰好一个 asset（多个素材各自委派一次，后台并行执行；"
                "一次传多个会被拒绝）；ai_editing_director 使用 timeline:<id>。"
                "调用立即返回 status=ACCEPTED 与 runId，Specialist 在后台执行；"
                "其终态（SUCCESS/BLOCKED/FAILED 或等待审阅）会以【系统自动消息 · "
                "Runtime 通知】送达，届时再读取 Project 验证产出。接受后"
                "不要等待、不要轮询，也不要对同一目标重复委派；可以继续"
                "处理其他不依赖该产物的目标，或结束本回合。"
            ),
            "parameters": deepcopy(
                {
                    "type": "object",
                    "properties": {
                        "role": {
                            "type": "string",
                            "enum": [
                                role.value for role in _DELEGATABLE_ROLES
                            ],
                        },
                        "target_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "uniqueItems": True,
                            "description": (
                                "Use canonical refs only. Never use JSON paths, scenario "
                                "names, bare words, or a raw project id."
                            ),
                        },
                        "task": {"type": "string", "minLength": 1},
                    },
                    "required": ["role", "target_refs", "task"],
                    "additionalProperties": False,
                },
            ),
        },
    }


def specialist_system_prompt(
    role: SpecialistRole,
    *,
    project_id: str,
    project: Project | None = None,
    workspace_schema: str | None = None,
    project_root: Path | None = None,
    target_refs: Sequence[str] | None = None,
) -> str:
    if role not in _DELEGATABLE_ROLES:
        raise ValueError(f"specialist role has no active prompt: {role.value}")
    values: dict[str, str] = {
        "project_id": project_id,
        "workspace_schema": workspace_schema
        or build_project_schema_prompt().text,
    }
    if role is SpecialistRole.SOURCE_INTELLIGENCE:
        # Source tools own the write contract. Timeline/visual/provider schemas
        # are irrelevant to perception and previously dominated every VLM turn.
        values["workspace_schema"] = (
            "Project 文件位于 ./project.json；只读取下列 Source 路径。"
            "写入素材理解使用 commit_source_intelligence 的工具 Schema；"
            "不编辑时间线、视觉资产或生成任务。成功提交回执包含已校验的持久化关联。"
        )
        # Memory usage rules are injected only when the delegated asset
        # actually has a built graph memory for its current intelligence.
        from services.media.source_memory import memory_guidance_for_targets

        values["memory_guidance"] = memory_guidance_for_targets(
            project_root,
            project,
            list(target_refs or ()),
        )
    if role is SpecialistRole.AI_EDITING_DIRECTOR:
        # TTS guidance depends on the configured model's capabilities and on
        # the project scenario, so it is built per render rather than
        # templated.
        values["tts_guidance"] = tts_guidance.specialist_guidance(
            role,
            project.scenario if project is not None else "general",
        )
        content_type = (
            project.settings.content_type if project is not None else None
        )
        target_duration = (
            project.settings.target_duration_seconds
            if project is not None
            else None
        )
        values.update(
            {
                "content_type": content_type or "general",
                "target_duration_seconds": (
                    f"{target_duration:g}"
                    if target_duration is not None
                    else "null"
                ),
            },
        )
    rendered = render_file_agent_prompt(_ROLE_PROMPT_IDS[role], **values)
    if role is SpecialistRole.SOURCE_INTELLIGENCE and project is not None:
        logical_ids = {ref.removeprefix("asset:") for ref in target_refs or ()}
        versions = [
            project.assets.source_versions_by_id.get(
                source.selected_asset_version_id,
            )
            for source in project.sources.sources.items.values()
            if source.logical_asset_id in logical_ids
        ]
        if versions and all(
            version and version.media_kind == "image" for version in versions
        ):
            start = rendered.index("# 视频理解内容要求")
            end = rendered.index("# 图片理解内容要求")
            rendered = rendered[:start] + rendered[end:]
            start = rendered.index("# 文档理解内容要求")
            end = rendered.index("# 工具使用原则")
            rendered = rendered[:start] + rendered[end:]
            rendered += (
                "\n\n本次仅有静态图片：不执行视频分段、转写或长素材检索。"
                "summary 通常使用一至两段，semanticEntries 只记录不同的可观察事实，"
                "不重复扩写。观察后直接提交工具，不先输出长篇自然语言分析。"
            )
    return rendered


__all__ = [
    "DELEGATE_TOOL_NAME",
    "DelegateToAgentInput",
    "delegate_tool_manifest",
    "specialist_system_prompt",
]
