# -*- coding: utf-8 -*-
"""Video template listing, save, and delete endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import project_file_services
from services.media_files.user_templates import (
    UserVideoTemplate,
    delete_user_template,
    extract_template_from_project,
    list_user_templates,
    save_user_template,
)
from services.media_files.video_templates import list_video_templates
from services.project_files.facade import CreatorFileServices

router = APIRouter(prefix="/video-templates", tags=["video-templates"])


def _builtin_item(t: Any, *, source: str) -> dict[str, Any]:
    return {
        "templateId": t.template_id,
        "name": t.name,
        "description": t.description,
        "contentType": t.content_type,
        "scenario": t.scenario,
        "colorGrade": t.color_grade,
        "defaultTransitionKind": t.default_transition_kind,
        "previewDescription": t.preview_description,
        "iconEmoji": t.icon_emoji,
        "captionBlueprints": list(t.caption_blueprint_order),
        "energy": t.energy,
        "density": t.density,
        "decoration": t.decoration,
        "source": source,
    }


def _user_item(t: UserVideoTemplate) -> dict[str, Any]:
    return {
        "templateId": t.template_id,
        "name": t.name,
        "description": t.description,
        "contentType": t.content_type,
        "scenario": t.scenario,
        "colorGrade": t.color_grade,
        "defaultTransitionKind": t.default_transition_kind,
        "previewDescription": t.preview_description,
        "iconEmoji": t.icon_emoji,
        "captionBlueprints": list(t.caption_blueprint_order),
        "energy": t.energy,
        "density": t.density,
        "decoration": t.decoration,
        "source": "user",
    }


@router.get("")
async def list_templates() -> dict[str, Any]:
    builtins = [
        _builtin_item(t, source="builtin") for t in list_video_templates()
    ]
    user_templates = [_user_item(t) for t in list_user_templates()]
    return {"items": builtins + user_templates}


class SaveAsTemplateRequest(BaseModel):
    project_id: str = Field(alias="projectId")
    name: str
    description: str = ""
    icon_emoji: str = Field(default="\u2728", alias="iconEmoji")
    timeline_id: str | None = Field(default=None, alias="timelineId")


@router.post("")
async def create_template(
    request: SaveAsTemplateRequest,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    snapshot = services.projects.read(request.project_id)
    project_data = snapshot.project.model_dump(mode="json")
    template = extract_template_from_project(
        project_data,
        name=request.name.strip(),
        description=request.description.strip(),
        icon_emoji=request.icon_emoji,
        timeline_id=request.timeline_id,
    )
    save_user_template(template)
    return _user_item(template)


@router.delete("/{template_id}")
async def remove_template(template_id: str) -> dict[str, Any]:
    if not template_id.startswith("user:"):
        raise HTTPException(
            status_code=400,
            detail="只能删除用户自定义模板",
        )
    if not delete_user_template(template_id):
        raise HTTPException(
            status_code=404,
            detail=f"模板不存在: {template_id}",
        )
    return {"deleted": template_id}
