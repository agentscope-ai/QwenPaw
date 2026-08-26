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
from models import config as model_config
from models.image.base import image_model_prompt_guidance
from models.video_capabilities import video_model_prompt_guidance
from services.file_agent_runtime.prompts import render_file_agent_prompt
from services.file_agent_runtime.prompts import tts_guidance
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
        # ``lineup`` mirrors the image_generation tool surface: cast-lineup
        # rendering is a visual-development capability, so its delegation
        # target must be spellable too.
        {"project", "element", "asset", "artifact", "lineup"},
        {"assets"},
    ),
    SpecialistRole.R2V_GENERATION_DIRECTOR: ({"element"}, set()),
    SpecialistRole.AI_EDITING_DIRECTOR: ({"timeline"}, set()),
}

_TARGET_GUIDANCE = {
    SpecialistRole.SOURCE_INTELLIGENCE: "asset:<logicalAssetId>",
    SpecialistRole.VISUAL_DEVELOPMENT: (
        "overall visuals: project:assets; or element:<id>, "
        "asset:<VisualEntity.entity_id>, artifact:<id>, "
        "lineup:<VisualCastLineup.lineup_id>"
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

# Visual entity ids are keyed char:/scene:/prop:<x> in project.json and the
# UI displays them as visual-entity:<id>, so models keep deriving targetRefs
# in those spellings. They map onto exactly one canonical asset ref.
_VISUAL_ENTITY_ALIAS_KINDS = frozenset({"char", "scene", "prop"})

# TTS guidance is built per render from the configured model's
# capabilities (see prompts.tts_guidance): a model without system voices
# turns designing a character voice from an option into a prerequisite.
_TTS_GUIDANCE_ROLES = frozenset(
    {
        SpecialistRole.VISUAL_DEVELOPMENT,
        SpecialistRole.AI_EDITING_DIRECTOR,
    },
)


def _normalize_asset_target_ref(target_ref: str) -> str:
    kind, separator, identifier = target_ref.partition(":")
    if not separator or not identifier:
        return target_ref
    if kind == "visual-entity":
        return f"asset:{identifier}"
    if kind in _VISUAL_ENTITY_ALIAS_KINDS:
        return f"asset:{target_ref}"
    return target_ref


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
        if "asset" in allowed_kinds:
            # Accept-and-map the unambiguous visual-entity spellings instead
            # of failing the delegation for a guessable reason; anything
            # still unknown falls through to the strict check below.
            self.target_refs = list(
                dict.fromkeys(
                    _normalize_asset_target_ref(target_ref)
                    for target_ref in self.target_refs
                ),
            )
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

    def validate_project_targets(self, *, project: Project) -> None:
        """Resolve role-sensitive refs against the current Project snapshot.

        ``asset:`` names two different domains in the public tool surface:
        Source Intelligence receives a source logical Asset, while Visual
        Development receives a ``VisualEntity.entity_id``.  Syntax validation
        alone cannot distinguish them, so a source Asset id could previously
        start a Visual SpecialistRun and fail every image call.  Resolve the
        ambiguous visual spelling before the run is created.
        """

        if self.role is not SpecialistRole.VISUAL_DEVELOPMENT:
            return
        entity_ids = project.visual.entities.items
        lineup_ids = project.visual.cast_lineups.items
        for target_ref in self.target_refs:
            kind, _, identifier = target_ref.partition(":")
            if kind == "lineup" and identifier not in lineup_ids:
                valid_lineups = [
                    f"lineup:{lineup_id}"
                    for lineup_id in project.visual.cast_lineups.order
                ]
                lineup_hint = (
                    ", ".join(valid_lineups[:8])
                    if valid_lineups
                    else "no VisualCastLineup exists yet; create one with "
                    "jq_project first"
                )
                raise ValueError(
                    f"{self.role.value} targetRef {target_ref!r} does not "
                    "resolve to project.visual.cast_lineups.items. Valid "
                    f"lineup targets: {lineup_hint}",
                )
            if kind != "asset" or identifier in entity_ids:
                continue
            valid_targets = [
                f"asset:{entity_id}"
                for entity_id in project.visual.entities.order
            ]
            valid_hint = (
                ", ".join(valid_targets[:8])
                if valid_targets
                else "no VisualEntity exists yet; create one with jq_project"
            )
            raise ValueError(
                f"{self.role.value} targetRef {target_ref!r} does not resolve "
                "to project.visual.entities.items; use "
                "asset:<VisualEntity.entity_id>. Source logical Asset ids "
                "belong in referenceVersionIds, not target_refs. Valid "
                f"visual targets: {valid_hint}",
            )


def delegate_tool_manifest() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": DELEGATE_TOOL_NAME,
            "description": (
                "把一个边界明确的素材理解、视觉媒体、R2V 或 AI 剪辑任务委派给"
                "对应 Creator Specialist。source_intelligence_agent 使用 asset:<id>；"
                "visual_development_agent 的整体视觉使用 project:assets，单个视觉实体"
                "必须使用 asset:<VisualEntity.entity_id>，阵容图使用 "
                "lineup:<VisualCastLineup.lineup_id>；来源素材 logicalAssetId 只能"
                "作为 referenceVersionIds，不能作为 Visual Specialist target_ref；"
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
    if role in _TTS_GUIDANCE_ROLES:
        # Guidance depends on the configured model's capabilities and on the
        # project scenario, so it is built per render rather than templated.
        values["tts_guidance"] = tts_guidance.specialist_guidance(
            role,
            project.scenario if project is not None else "general",
        )
    if role is SpecialistRole.SOURCE_INTELLIGENCE:
        # Memory usage rules are injected only when the delegated asset
        # actually has a built graph memory for its current intelligence.
        from services.media.source_memory import memory_guidance_for_targets

        values["memory_guidance"] = memory_guidance_for_targets(
            project_root,
            project,
            list(target_refs or ()),
        )
    if role is SpecialistRole.R2V_GENERATION_DIRECTOR:
        # Model-specific prompt rules (e.g. HappyHorse [Image N] citations)
        # are injected from the runtime-resolved video model so the static
        # prompt stays model-agnostic.
        values["video_model_guidance"] = video_model_prompt_guidance(
            model_config.get_video_model_name(),
            model_config.get_video_backend(),
        )
    if role in {
        SpecialistRole.VISUAL_DEVELOPMENT,
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    }:
        # The image reference budget is a model capability, not a static
        # rule: qwen-image only accepts 0-3 image content items per call
        # while other providers keep the historical budget of 5.
        values["image_model_guidance"] = image_model_prompt_guidance(
            model_config.get_image_model_name(),
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
