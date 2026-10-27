# -*- coding: utf-8 -*-
"""User-created video templates persisted to the data root.

Unlike the built-in ``VideoTemplate`` presets in ``video_templates.py``,
user templates are extracted from an existing project's timeline and
stored as individual JSON files under ``$CREATOR_DATA_ROOT/user-templates/``.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.storage_root import require_creator_data_root

_USER_TEMPLATE_DIR_NAME = "user-templates"
_USER_TEMPLATE_PREFIX = "user:"

_CONCEPT_CAPTIONS_RE = re.compile(r"字幕蓝图:\s*([^\|]+)")
_CONCEPT_OPENING_RE = re.compile(r"片头字幕:\s*(\S+)")
_CONCEPT_CLOSING_RE = re.compile(r"片尾字幕:\s*(\S+)")
_SIG_TRANSITION_RE = re.compile(
    r"默认转场:\s*(\S+?)\s*\(([\d.]+)s\)",
)


class UserVideoTemplate(BaseModel):
    template_id: str
    name: str
    description: str = ""
    content_type: str = ""
    scenario: Literal["short_drama", "video_edit", "general"] = "general"
    opening_caption_blueprint: str = ""
    closing_caption_blueprint: str = ""
    default_transition_kind: str = "fade"
    transition_blend_seconds: float = 0.4
    caption_blueprint_order: list[str] = Field(default_factory=list)
    color_grade: str = ""
    energy: Literal["low", "mid", "high"] = "mid"
    density: Literal["low", "mid", "high"] = "mid"
    decoration: Literal["low", "mid", "high"] = "mid"
    design_floor_opening: str = ""
    design_floor_transitions: str = ""
    design_floor_body: str = ""
    design_floor_ending: str = ""
    preview_description: str = ""
    icon_emoji: str = "\u2728"


def _template_dir() -> Path:
    root = require_creator_data_root()
    directory = root / _USER_TEMPLATE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _template_path(template_id: str) -> Path:
    safe_name = template_id.replace(":", "_")
    return _template_dir() / f"{safe_name}.json"


def _generate_id() -> str:
    return f"{_USER_TEMPLATE_PREFIX}{uuid.uuid4().hex[:8]}"


def _parse_concept(concept: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "opening_caption_blueprint": "",
        "closing_caption_blueprint": "",
        "caption_blueprint_order": [],
    }
    captions_match = _CONCEPT_CAPTIONS_RE.search(concept)
    if captions_match:
        raw = captions_match.group(1).strip()
        result["caption_blueprint_order"] = [
            s.strip() for s in raw.split(",") if s.strip()
        ]
    opening_match = _CONCEPT_OPENING_RE.search(concept)
    if opening_match:
        result["opening_caption_blueprint"] = opening_match.group(1).strip()
    closing_match = _CONCEPT_CLOSING_RE.search(concept)
    if closing_match:
        result["closing_caption_blueprint"] = closing_match.group(1).strip()
    return result


def _parse_signature(signature: str) -> dict[str, Any]:
    match = _SIG_TRANSITION_RE.search(signature)
    if match:
        return {
            "default_transition_kind": match.group(1),
            "transition_blend_seconds": float(match.group(2)),
        }
    return {
        "default_transition_kind": "fade",
        "transition_blend_seconds": 0.4,
    }


def extract_template_from_project(
    project_data: dict[str, Any],
    *,
    name: str,
    description: str = "",
    icon_emoji: str = "\u2728",
    timeline_id: str | None = None,
) -> UserVideoTemplate:
    """Extract a user template from a project's timeline configuration."""
    timelines = project_data.get("timelines", {})
    items = timelines.get("items", {})
    order = timelines.get("order", [])
    tid = timeline_id or (order[0] if order else None)
    timeline = items.get(tid) if tid else None

    edit_plan = (timeline or {}).get("edit_plan") or {}
    dials = edit_plan.get("dials", {})
    design_floor = edit_plan.get("design_floor", {})
    concept = edit_plan.get("concept", "")
    signature = edit_plan.get("signature_device", "")

    concept_fields = _parse_concept(concept)
    sig_fields = _parse_signature(signature)

    settings = project_data.get("settings", {})
    scenario = project_data.get("scenario", "general")
    if scenario not in ("short_drama", "video_edit", "general"):
        scenario = "general"

    color_grade = (timeline or {}).get("color_grade", "")

    return UserVideoTemplate(
        template_id=_generate_id(),
        name=name,
        description=description,
        content_type=settings.get("content_type", ""),
        scenario=scenario,
        opening_caption_blueprint=concept_fields["opening_caption_blueprint"],
        closing_caption_blueprint=concept_fields["closing_caption_blueprint"],
        default_transition_kind=sig_fields["default_transition_kind"],
        transition_blend_seconds=sig_fields["transition_blend_seconds"],
        caption_blueprint_order=concept_fields["caption_blueprint_order"],
        color_grade=color_grade,
        energy=dials.get("energy", "mid"),
        density=dials.get("density", "mid"),
        decoration=dials.get("decoration", "mid"),
        design_floor_opening=design_floor.get("opening", ""),
        design_floor_transitions=design_floor.get("transitions", ""),
        design_floor_body=design_floor.get("body", ""),
        design_floor_ending=design_floor.get("ending", ""),
        preview_description=description,
        icon_emoji=icon_emoji,
    )


def save_user_template(template: UserVideoTemplate) -> UserVideoTemplate:
    path = _template_path(template.template_id)
    path.write_text(
        template.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return template


def load_user_template(template_id: str) -> UserVideoTemplate | None:
    path = _template_path(template_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return UserVideoTemplate.model_validate(data)


def list_user_templates() -> list[UserVideoTemplate]:
    directory = _template_dir()
    templates: list[UserVideoTemplate] = []
    for path in sorted(directory.glob("user_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            templates.append(UserVideoTemplate.model_validate(data))
        except (json.JSONDecodeError, ValueError):
            continue
    return templates


def delete_user_template(template_id: str) -> bool:
    path = _template_path(template_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def template_to_apply_dict(
    template: UserVideoTemplate,
) -> dict[str, Any]:
    """Convert a user template to the shape used by apply logic."""
    caption_names = ", ".join(template.caption_blueprint_order)
    concept_parts: list[str] = []
    if caption_names:
        concept_parts.append(f"字幕蓝图: {caption_names}")
    if template.opening_caption_blueprint:
        concept_parts.append(
            f"片头字幕: {template.opening_caption_blueprint}",
        )
    if template.closing_caption_blueprint:
        concept_parts.append(
            f"片尾字幕: {template.closing_caption_blueprint}",
        )

    return {
        "concept": " | ".join(concept_parts),
        "signature_device": (
            f"默认转场: {template.default_transition_kind}"
            f" ({template.transition_blend_seconds}s)"
        ),
        "color_grade": template.color_grade,
        "content_type": template.content_type,
        "energy": template.energy,
        "density": template.density,
        "decoration": template.decoration,
        "design_floor": {
            "opening": template.design_floor_opening,
            "transitions": template.design_floor_transitions,
            "body": template.design_floor_body,
            "ending": template.design_floor_ending,
        },
    }
