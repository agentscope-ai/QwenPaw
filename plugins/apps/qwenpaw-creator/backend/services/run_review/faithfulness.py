# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Plan-faithfulness five-element checklist (tier-2).

Method ported from APE-benchmark ``layer_c._judge_faithfulness`` — the
"does the output honor the plan" judgement is split into five
independently answerable elements (entity form / spatial composition /
tone & atmosphere / camera motion / narrative sequence) instead of one
catch-all check — with the comparison target swapped for Creator's own
plan chain: the committed shot list (descriptions, camera notes,
dialogue) versus the generated frames.

Design points kept from upstream: every element question carries its
own tolerance note ("direction match is enough, not brand-exact"),
elements the plan never declared are not asked (no NA-noise), and the
camera element gets the tier-0 optical-motion facts injected so the VLM
does not have to guess motion from sparse frames.

Departure from upstream, documented: APE issues one VLM call per
element; Creator folds the five elements into the single scene-check
call as an extra checklist to keep per-artifact review cost flat. The
isolation benefit is partially retained by forcing one verdict object
per element in the output contract.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_TONE_PATTERN = re.compile(
    r"(暖色|冷色|逆光|夜景|黄昏|清晨|阴天|柔光|霓虹|电影感|胶片|黑白|高对比|低饱和|梦幻|昏暗|明亮)",
)
_COMPOSITION_PATTERN = re.compile(
    r"(特写|近景|中景|远景|全景|俯拍|仰拍|居中|三分法|对称|前景|背景虚化|过肩|侧面|正面|大全景)",
)
_MOTION_PATTERN = re.compile(
    r"(镜头(?:推|拉|摇|移)|(?:推|拉)(?:近|远)|缓缓(?:推|拉|摇|移)"
    r"|跟拍|环绕|升降|手持|固定机位|变焦|甩镜|推镜|拉镜|摇镜|移镜"
    r"|zoom|pan|tilt|dolly|orbit|static)",
    re.IGNORECASE,
)

# Faithfulness severities mirror the defect bank's reading: a missing or
# wrong subject breaks the shot, while tone/motion drift is a note. Only
# ``major`` rows can force a regeneration, so single-word look-alikes
# ("他推开门") can no longer cost a re-render on their own.
FAITHFULNESS_SEVERITIES: dict[str, str] = {
    "faith_entity": "major",
    "faith_sequence": "major",
    "faith_composition": "minor",
    "faith_tone": "minor",
    "faith_motion": "minor",
}

FAITHFULNESS_ELEMENT_KEYS = (
    "faith_entity",
    "faith_composition",
    "faith_tone",
    "faith_motion",
    "faith_sequence",
)


def _shot_texts(plan_context: Mapping[str, Any]) -> list[dict[str, str]]:
    shots = plan_context.get("planned_shots") or []
    rows: list[dict[str, str]] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            continue
        rows.append(
            {
                "shot_id": str(shot.get("shot_id") or ""),
                "description": str(shot.get("description") or ""),
                "dialogue": str(shot.get("dialogue") or ""),
            },
        )
    return rows


def build_faithfulness_elements(
    plan_context: Mapping[str, Any],
    *,
    objective_facts: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Applicable elements with their per-element question text.

    Only elements the plan actually declares produce a question — an
    unmentioned tone or camera move is simply not asked (upstream rule:
    undeclared aspects stay out of the denominator).
    """
    shots = _shot_texts(plan_context)
    if not shots:
        return []
    combined = "。".join(
        f"{row['description']} {row['dialogue']}" for row in shots
    )
    elements: list[dict[str, str]] = [
        {
            "key": "faith_entity",
            "title": "实体形态",
            "question": (
                "计划声明的主体/道具/场景是否真的出现在画面中且形态方向一致？"
                "容错：不要求品牌/型号/纹样精确匹配，外形与颜色方向一致即 ET。逐镜对照：\n"
                + "\n".join(
                    f"  - {row['shot_id']}: {row['description'][:120]}"
                    for row in shots[:8]
                )
            ),
        },
    ]
    composition_terms = sorted(set(_COMPOSITION_PATTERN.findall(combined)))
    if composition_terms:
        elements.append(
            {
                "key": "faith_composition",
                "title": "空间布局",
                "question": (
                    f"计划声明了构图要求（{'、'.join(composition_terms[:6])}），"
                    "实际画面构图是否大方向匹配？容错：只判大方向，轻微偏移判 ET。"
                ),
            },
        )
    tone_terms = sorted(set(_TONE_PATTERN.findall(combined)))
    if tone_terms:
        elements.append(
            {
                "key": "faith_tone",
                "title": "色调氛围",
                "question": (
                    f"计划声明了色调/光线氛围（{'、'.join(tone_terms[:6])}），"
                    "实际画面是否大方向一致？容错：只判方向（暖/冷、明/暗），不判精确色值。"
                ),
            },
        )
    motion_terms = sorted(
        {term.casefold() for term in _MOTION_PATTERN.findall(combined)},
    )
    if motion_terms:
        motion_evidence = ""
        if objective_facts:
            camera = objective_facts.get("camera_motion") or {}
            index = objective_facts.get("video_index") or {}
            if isinstance(camera, Mapping) or isinstance(index, Mapping):
                ratio = (
                    camera.get("dynamic_frame_ratio")
                    if isinstance(camera, Mapping)
                    else None
                ) or (
                    index.get("dynamic_frame_ratio")
                    if isinstance(index, Mapping)
                    else None
                )
                if ratio is not None:
                    level = (
                        "接近静止"
                        if float(ratio) < 0.1
                        else "轻微运动"
                        if float(ratio) < 0.35
                        else "明显运动"
                    )
                    motion_evidence = f"（程序光流证据：动态帧占比 {ratio}，画面整体{level}）"
        elements.append(
            {
                "key": "faith_motion",
                "title": "运镜动态",
                "question": (
                    f"计划声明了运镜（{'、'.join(motion_terms[:6])}），实际画面运动是否大方向一致？"
                    f"{motion_evidence}容错：只判大方向（有无运动、推拉vs平移），不判速度精度。"
                ),
            },
        )
    if len(shots) >= 2:
        elements.append(
            {
                "key": "faith_sequence",
                "title": "叙事顺序",
                "question": (
                    "多镜头的先后顺序是否与计划叙事顺序一致？逐镜顺序：\n"
                    + "\n".join(
                        f"  {index + 1}. {row['shot_id']}: {row['description'][:80]}"
                        for index, row in enumerate(shots[:8])
                    )
                ),
            },
        )
    return elements


def build_faithfulness_block(elements: list[dict[str, str]]) -> str:
    """User-text section for the faithfulness checklist."""
    if not elements:
        return ""
    lines = [
        "【计划忠实度五要素（faithfulness，逐要素判 ET/CT/NA）】",
        "对照计划逐要素判定：ET=大方向一致，CT=明确不符（必须给出证据帧时间戳、写明「计划要求 vs 实际画面」的对照描述与修改建议），NA=画面无法判断（必须给出理由）。计划未声明的要素已被程序剔除，不要自行新增要素。",
    ]
    for element in elements:
        lines.append(
            f"- {element['key']}（{element['title']}）：{element['question']}",
        )
    return "\n".join(lines)


__all__ = [
    "FAITHFULNESS_ELEMENT_KEYS",
    "build_faithfulness_block",
    "build_faithfulness_elements",
]
