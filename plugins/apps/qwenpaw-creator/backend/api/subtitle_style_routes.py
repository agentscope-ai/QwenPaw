# -*- coding: utf-8 -*-
"""List, save, update and delete user-defined subtitle styles.

A custom style is a named bundle of style-window picks (base pack, the
five overrides, the motion triple); applying one is just moving those
controls, so nothing here touches the caption renderer.  Storage lives in
``services.media_files.user_subtitle_styles``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import Field

from schemas.common import StrictModel
from schemas.projects import SubtitleAnimationPolicy, SubtitleStylePolicy
from services.media_files.user_subtitle_styles import (
    UserSubtitleStyle,
    delete_user_subtitle_style,
    list_user_subtitle_styles,
    load_user_subtitle_style,
    new_user_subtitle_style_id,
    save_user_subtitle_style,
)

router = APIRouter(prefix="/subtitle-packs", tags=["subtitle-packs"])


def _user_item(style: UserSubtitleStyle) -> dict[str, Any]:
    """Camel-case wire shape, with unset controls left out entirely."""
    style_bundle = {
        key: value
        for key, value in {
            "color": style.color,
            "fontScale": style.font_scale,
            "strokeScale": style.stroke_scale,
            "backgroundOpacity": style.background_opacity,
            "fontFamily": style.font_family,
        }.items()
        if value is not None
    }
    animation = {
        key: value
        for key, value in {
            "entrance": style.entrance,
            "exit": style.exit,
            "loop": style.loop,
        }.items()
        if value is not None
    }
    return {
        "styleId": style.style_id,
        "name": style.name,
        "description": style.description,
        "packId": style.pack_id,
        "style": style_bundle,
        "animation": animation,
    }


class CustomSubtitleStyleRequest(StrictModel):
    """The style window's current picks, named for later reuse."""

    name: str
    description: str = ""
    pack_id: str | None = Field(default=None, alias="packId")
    style: SubtitleStylePolicy | None = None
    animation: SubtitleAnimationPolicy | None = None


def _to_model(
    request: CustomSubtitleStyleRequest,
    style_id: str,
) -> UserSubtitleStyle:
    style = request.style
    animation = request.animation
    return UserSubtitleStyle(
        style_id=style_id,
        name=request.name.strip(),
        description=request.description.strip(),
        pack_id=request.pack_id,
        color=style.color if style else None,
        font_scale=style.font_scale if style else None,
        stroke_scale=style.stroke_scale if style else None,
        background_opacity=style.background_opacity if style else None,
        font_family=style.font_family if style else None,
        entrance=animation.entrance if animation else None,
        exit=animation.exit if animation else None,
        loop=animation.loop if animation else None,
    )


@router.get("/custom")
async def list_custom_subtitle_styles() -> dict[str, Any]:
    return {"items": [_user_item(s) for s in list_user_subtitle_styles()]}


@router.post("/custom")
async def create_custom_subtitle_style(
    request: CustomSubtitleStyleRequest,
) -> dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="自定义风格需要名称")
    style = _to_model(request, new_user_subtitle_style_id())
    save_user_subtitle_style(style)
    return _user_item(style)


@router.put("/custom/{style_id}")
async def update_custom_subtitle_style(
    style_id: str,
    request: CustomSubtitleStyleRequest,
) -> dict[str, Any]:
    if not style_id.startswith("user:"):
        raise HTTPException(status_code=400, detail="只能更新用户自定义风格")
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="自定义风格需要名称")
    if load_user_subtitle_style(style_id) is None:
        raise HTTPException(status_code=404, detail=f"风格不存在: {style_id}")
    style = _to_model(request, style_id)
    save_user_subtitle_style(style)
    return _user_item(style)


@router.delete("/custom/{style_id}")
async def remove_custom_subtitle_style(style_id: str) -> dict[str, Any]:
    if not style_id.startswith("user:"):
        raise HTTPException(status_code=400, detail="只能删除用户自定义风格")
    if not delete_user_subtitle_style(style_id):
        raise HTTPException(status_code=404, detail=f"风格不存在: {style_id}")
    return {"deleted": style_id}
