# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""File-native Creator specialist contracts and prompt selection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.enums import SpecialistRole
from models import config as model_config
from models.video_capabilities import video_model_prompt_guidance
from services.file_agent_runtime.prompts import render_file_agent_prompt
from services.project_files.models import Project
from services.project_files.schema_prompt import build_project_schema_prompt


DELEGATE_TOOL_NAME = "delegate_to_agent"

_DELEGATABLE_ROLES = (
    SpecialistRole.SOURCE_INTELLIGENCE,
    SpecialistRole.VISUAL_DEVELOPMENT,
    SpecialistRole.R2V_GENERATION_DIRECTOR,
    SpecialistRole.AI_EDITING_DIRECTOR,
)

_ROLE_TARGETS: dict[SpecialistRole, tuple[set[str], set[str]]] = {
    SpecialistRole.SOURCE_INTELLIGENCE: ({"asset"}, set()),
    SpecialistRole.VISUAL_DEVELOPMENT: (
        {"project", "element", "asset", "artifact"},
        {"assets"},
    ),
    SpecialistRole.R2V_GENERATION_DIRECTOR: ({"element"}, set()),
    SpecialistRole.AI_EDITING_DIRECTOR: ({"timeline"}, set()),
}

_TARGET_GUIDANCE = {
    SpecialistRole.SOURCE_INTELLIGENCE: "asset:<logicalAssetId>",
    SpecialistRole.VISUAL_DEVELOPMENT: (
        "overall visuals: project:assets; or element:<id>, "
        "asset:<id>, artifact:<id>"
    ),
    SpecialistRole.R2V_GENERATION_DIRECTOR: "an existing r2v element:<id>",
    SpecialistRole.AI_EDITING_DIRECTOR: "an existing timeline:<id>",
}

_ROLE_PROMPT_IDS = {
    SpecialistRole.SOURCE_INTELLIGENCE: "source_intelligence_agent.system",
    SpecialistRole.VISUAL_DEVELOPMENT: "visual_development_agent.system",
    SpecialistRole.R2V_GENERATION_DIRECTOR: "r2v_generation_director.system",
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
                "把一个边界明确的素材理解、视觉媒体、R2V 或 AI 剪辑任务委派给"
                "对应 Creator Specialist。source_intelligence_agent 使用 asset:<id>；"
                "visual_development_agent 的整体视觉使用 project:assets；"
                "r2v_generation_director 使用 element:<id>，"
                "ai_editing_director 使用 timeline:<id>。"
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
) -> str:
    if role not in _DELEGATABLE_ROLES:
        raise ValueError(f"specialist role has no active prompt: {role.value}")
    values: dict[str, str] = {
        "project_id": project_id,
        "workspace_schema": workspace_schema
        or build_project_schema_prompt().text,
    }
    if role is SpecialistRole.R2V_GENERATION_DIRECTOR:
        # Model-specific prompt rules (e.g. HappyHorse [Image N] citations)
        # are injected from the runtime-resolved video model so the static
        # prompt stays model-agnostic.
        values["video_model_guidance"] = video_model_prompt_guidance(
            model_config.get_video_model_name(),
        )
    if role is SpecialistRole.AI_EDITING_DIRECTOR:
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
    return render_file_agent_prompt(_ROLE_PROMPT_IDS[role], **values)


__all__ = [
    "DELEGATE_TOOL_NAME",
    "DelegateToAgentInput",
    "delegate_tool_manifest",
    "specialist_system_prompt",
]
