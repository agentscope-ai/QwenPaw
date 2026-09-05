# -*- coding: utf-8 -*-
"""Code-built-in video template presets.

Each template bundles intro/outro caption style, transition style, subtitle
style, colour grade, and edit-plan dials into a single reusable preset that
can be applied at project creation time.

Follows the same immutable-dataclass + registry-dict pattern as
``motion_blueprints.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from services.project_files.models import (
    DEFAULT_TIMELINE_ID,
    EditPlan,
    EditPlanDesignFloor,
    EditPlanDials,
    Project,
)


@dataclass(frozen=True)
class VideoTemplateDesignFloor:
    opening: str
    transitions: str
    body: str
    ending: str


@dataclass(frozen=True)
class VideoTemplate:
    template_id: str
    name: str
    description: str
    content_type: str
    scenario: Literal["short_drama", "video_edit", "general"]

    opening_caption_blueprint: str
    closing_caption_blueprint: str

    default_transition_kind: str
    transition_blend_seconds: float

    caption_blueprint_order: tuple[str, ...]

    color_grade: str

    energy: Literal["low", "mid", "high"]
    density: Literal["low", "mid", "high"]
    decoration: Literal["low", "mid", "high"]

    design_floor: VideoTemplateDesignFloor

    decoration_catalog: tuple[str, ...]
    frame_blueprint: str

    preview_description: str
    icon_emoji: str


_VIDEO_TEMPLATES: dict[str, VideoTemplate] = {
    "vlog_daily": VideoTemplate(
        template_id="vlog_daily",
        name="日常Vlog",
        description="手写笔记风格字幕 + 溶解转场 + 清新色调，适合日常生活记录",
        content_type="travel",
        scenario="video_edit",
        opening_caption_blueprint="handwritten_note",
        closing_caption_blueprint="glow_breath",
        default_transition_kind="dissolve",
        transition_blend_seconds=0.5,
        caption_blueprint_order=(
            "handwritten_note",
            "glow_breath",
            "stagger_pop",
        ),
        color_grade="vlog_fresh",
        energy="mid",
        density="mid",
        decoration="low",
        design_floor=VideoTemplateDesignFloor(
            opening="1-3秒手写笔记风格标题卡渐入，轻快开场",
            transitions="以溶解(dissolve)为主，偶尔硬切保持节奏",
            body="每个场景一个设计节拍，手写笔记字幕贯穿",
            ending="温暖渐出，手写笔记风格结束卡",
        ),
        decoration_catalog=("bokeh_float", "particle_drift"),
        frame_blueprint="warm_journal",
        preview_description="温暖手写风格，适合日常Vlog",
        icon_emoji="\U0001f4f7",
    ),
    "short_drama_cinematic": VideoTemplate(
        template_id="short_drama_cinematic",
        name="短剧电影感",
        description="水墨揭示字幕 + 黑场转场 + 电影色调，适合剧情短片",
        content_type="short_drama",
        scenario="short_drama",
        opening_caption_blueprint="ink_reveal",
        closing_caption_blueprint="drama_whisper",
        default_transition_kind="fadeblack",
        transition_blend_seconds=0.6,
        caption_blueprint_order=("ink_reveal", "drama_whisper"),
        color_grade="ink_wash",
        energy="low",
        density="mid",
        decoration="mid",
        design_floor=VideoTemplateDesignFloor(
            opening="水墨侧条揭示式标题卡，3秒内建立氛围",
            transitions="黑场淡入淡出(fadeblack)为主，场景间留白呼吸",
            body="每场一个情绪节拍，低语独白式字幕",
            ending="低语独白渐隐，余韵收尾",
        ),
        decoration_catalog=("ink_splash", "ambient_halo"),
        frame_blueprint="kraft_paper",
        preview_description="电影水墨风格，适合短剧叙事",
        icon_emoji="\U0001f3ac",
    ),
    "tutorial_clean": VideoTemplate(
        template_id="tutorial_clean",
        name="教程清晰版",
        description="精密字幕 + 滑动转场 + 无调色，适合软件教程和知识分享",
        content_type="tutorial",
        scenario="video_edit",
        opening_caption_blueprint="precision_subtitle",
        closing_caption_blueprint="chapter_label",
        default_transition_kind="slideleft",
        transition_blend_seconds=0.4,
        caption_blueprint_order=(
            "precision_subtitle",
            "chapter_label",
            "keyword_spotlight",
        ),
        color_grade="",
        energy="low",
        density="mid",
        decoration="low",
        design_floor=VideoTemplateDesignFloor(
            opening="精密字幕风格标题，直接切入主题",
            transitions="左滑(slideleft)推进，保持信息密度",
            body="每步骤一个章节标签，精密字幕逐句解说",
            ending="章节标签式结束，干净收束",
        ),
        decoration_catalog=("cursor_ripple",),
        frame_blueprint="product_ui",
        preview_description="简洁专业风格，适合教程演示",
        icon_emoji="\U0001f4da",
    ),
    "interview_pro": VideoTemplate(
        template_id="interview_pro",
        name="专业访谈",
        description="静态胶囊字幕 + 淡入淡出 + 冷色调，适合访谈和纪录片",
        content_type="interview",
        scenario="video_edit",
        opening_caption_blueprint="static_capsule",
        closing_caption_blueprint="keyword_spotlight",
        default_transition_kind="fade",
        transition_blend_seconds=0.4,
        caption_blueprint_order=("static_capsule", "keyword_spotlight"),
        color_grade="clean_cool",
        energy="low",
        density="low",
        decoration="low",
        design_floor=VideoTemplateDesignFloor(
            opening="静态胶囊标题卡，简洁专业",
            transitions="淡入淡出(fade)为主，不抢注意力",
            body="逐句静态胶囊字幕，关键词处切换聚焦高亮",
            ending="关键词聚焦式总结卡",
        ),
        decoration_catalog=("wave_flow",),
        frame_blueprint="product_ui",
        preview_description="冷静专业风格，适合访谈纪录",
        icon_emoji="\U0001f399\ufe0f",
    ),
    "gaming_neon": VideoTemplate(
        template_id="gaming_neon",
        name="游戏霓虹",
        description="霓虹脉冲字幕 + 像素化转场 + 霓虹色调，适合游戏集锦",
        content_type="gaming",
        scenario="video_edit",
        opening_caption_blueprint="neon_pulse",
        closing_caption_blueprint="brush_strike",
        default_transition_kind="pixelize",
        transition_blend_seconds=0.5,
        caption_blueprint_order=("neon_pulse", "brush_strike", "stagger_pop"),
        color_grade="neon_vivid",
        energy="high",
        density="high",
        decoration="mid",
        design_floor=VideoTemplateDesignFloor(
            opening="霓虹脉冲标题卡，暗底发光震撼开场",
            transitions="像素化(pixelize)为主，高能量切换",
            body="霓虹脉冲字幕贯穿，高潮处墨笔横扫强调",
            ending="墨笔横扫式结束，干脆利落",
        ),
        decoration_catalog=("eq_bars", "grid_pulse", "confetti_drift"),
        frame_blueprint="neon_glow",
        preview_description="霓虹赛博风格，适合游戏高光",
        icon_emoji="\U0001f3ae",
    ),
    "travel_warm": VideoTemplate(
        template_id="travel_warm",
        name="旅行暖阳",
        description="手写笔记字幕 + 擦除转场 + 暖色调，适合旅行记录",
        content_type="travel",
        scenario="video_edit",
        opening_caption_blueprint="handwritten_note",
        closing_caption_blueprint="stagger_pop",
        default_transition_kind="wipeleft",
        transition_blend_seconds=0.5,
        caption_blueprint_order=(
            "handwritten_note",
            "stagger_pop",
            "glow_breath",
        ),
        color_grade="warm_bright",
        energy="mid",
        density="mid",
        decoration="mid",
        design_floor=VideoTemplateDesignFloor(
            opening="手写笔记标题卡，温暖开场",
            transitions="左擦除(wipeleft)为主，画面自然过渡",
            body="手写笔记字幕配合综艺花字点缀",
            ending="逐字弹入式结束卡，活泼收束",
        ),
        decoration_catalog=("bokeh_float", "particle_drift", "wave_flow"),
        frame_blueprint="warm_journal",
        preview_description="温暖明亮风格，适合旅行风光",
        icon_emoji="\u2708\ufe0f",
    ),
    "product_showcase": VideoTemplate(
        template_id="product_showcase",
        name="产品展示",
        description="编辑标题字幕 + 淡入淡出 + 冷色调，适合产品宣传片",
        content_type="tutorial",
        scenario="video_edit",
        opening_caption_blueprint="editorial_title",
        closing_caption_blueprint="editorial_title",
        default_transition_kind="fade",
        transition_blend_seconds=0.4,
        caption_blueprint_order=("editorial_title", "precision_subtitle"),
        color_grade="clean_cool",
        energy="mid",
        density="low",
        decoration="low",
        design_floor=VideoTemplateDesignFloor(
            opening="编辑标题左对齐字组，产品名渐入",
            transitions="淡入淡出(fade)，干净不抢镜",
            body="编辑标题配合精密字幕，产品展示节奏",
            ending="编辑标题式收束，品牌感结尾",
        ),
        decoration_catalog=("ambient_halo",),
        frame_blueprint="product_ui",
        preview_description="简洁高端风格，适合产品展示",
        icon_emoji="\U0001f4e6",
    ),
}

_DISPLAY_ORDER = (
    "vlog_daily",
    "short_drama_cinematic",
    "tutorial_clean",
    "interview_pro",
    "gaming_neon",
    "travel_warm",
    "product_showcase",
)


def list_video_templates() -> list[VideoTemplate]:
    return [
        _VIDEO_TEMPLATES[tid]
        for tid in _DISPLAY_ORDER
        if tid in _VIDEO_TEMPLATES
    ]


def get_video_template(template_id: str) -> VideoTemplate | None:
    return _VIDEO_TEMPLATES.get(template_id)


def apply_video_template_to_project(
    project: Project,
    template: VideoTemplate,
    *,
    timeline_id: str | None = None,
) -> Project:
    target_tid = timeline_id or DEFAULT_TIMELINE_ID
    timeline = project.timelines.items.get(target_tid)
    if timeline is None:
        return project

    caption_names = ", ".join(template.caption_blueprint_order)
    concept_parts = [
        f"字幕蓝图: {caption_names}",
    ]
    if template.opening_caption_blueprint:
        concept_parts.append(
            f"片头字幕: {template.opening_caption_blueprint}",
        )
    if template.closing_caption_blueprint:
        concept_parts.append(
            f"片尾字幕: {template.closing_caption_blueprint}",
        )
    concept = " | ".join(concept_parts)

    signature_device = (
        f"默认转场: {template.default_transition_kind}"
        f" ({template.transition_blend_seconds}s)"
    )

    edit_plan = EditPlan(
        concept=concept,
        dials=EditPlanDials(
            energy=template.energy,
            density=template.density,
            decoration=template.decoration,
        ),
        signature_device=signature_device,
        pacing="",
        design_floor=EditPlanDesignFloor(
            opening=template.design_floor.opening,
            transitions=template.design_floor.transitions,
            body=template.design_floor.body,
            ending=template.design_floor.ending,
        ),
    )

    updated_timeline = timeline.model_copy(
        update={
            "color_grade": template.color_grade,
            "edit_plan": edit_plan,
        },
    )

    updated_timelines = project.timelines.model_copy(
        update={
            "items": {**project.timelines.items, target_tid: updated_timeline},
        },
    )

    updated_settings = project.settings.model_copy(
        update={"content_type": template.content_type},
    )

    return project.model_copy(
        update={
            "settings": updated_settings,
            "timelines": updated_timelines,
        },
    )
