# -*- coding: utf-8 -*-
"""Deterministic pre-generation checks for authored R2V prompts.

Taste remains an LLM review concern. This module only checks contracts that
the Runtime can prove from Project state before a paid storyboard/video call:
presence, panel count/ratio, obvious layout contradictions, verbatim dialogue
coverage and provider-specific storyboard reference syntax.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any

from models import config as model_config
from models.reference_markers import CANONICAL_MARKER_PATTERN
from models.video_capabilities import (
    video_prompt_image_reference_markers,
    video_prompt_storyboard_reference_violation,
)
from services.prompt_text import dialogue_match_key, dialogue_spoken_lines

_BORDER_CONTRADICTION = re.compile(
    r"(?:\bno\s+(?:panel\s+)?borders?\b|无边框|不要边框|禁止边框|不画边框)",
    re.IGNORECASE,
)
_BENIGN_BORDER_CONTEXT = re.compile(
    r"(?:"
    r"无边框外层留白|外层无边框留白|"
    r"不画(?:第\s*\d+\s*个)?(?:带框)?(?:空槽|占位)|"
    r"(?:不要|禁止|不画)(?:装饰性)?外框|"
    r"unbordered\s+outer\s+(?:whitespace|margin)|"
    r"outer\s+(?:whitespace|margin)\s+without\s+borders?|"
    r"no\s+(?:decorative\s+)?outer\s+(?:border|frame)s?"
    r")",
    re.IGNORECASE,
)
_REFERENCE_ROLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "storyboard": re.compile(r"storyboard|分镜", re.IGNORECASE),
    "lineup": re.compile(r"cast\s+lineup|lineup|阵容图|群像", re.IGNORECASE),
    "character": re.compile(
        r"\bcharacter\b|角色|人物",
        re.IGNORECASE,
    ),
    "scene": re.compile(r"\b(?:scene|environment)\b|场景|环境", re.IGNORECASE),
    "prop": re.compile(r"\bprop\b|道具", re.IGNORECASE),
}


def _pointer_token(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _touches_element(
    base_pointer: str,
    changed_pointers: Sequence[str],
) -> bool:
    return any(
        pointer == base_pointer
        or pointer.startswith(base_pointer + "/")
        or base_pointer.startswith(pointer.rstrip("/") + "/")
        for pointer in changed_pointers
        if pointer.startswith("/")
    )


_CN_DIGITS = "零一二三四五六七八九"


def _chinese_numeral(value: int) -> str | None:
    """Render 1-99 the way prompts write it（九、十六、二十五）."""

    if not 1 <= value <= 99:
        return None
    tens, ones = divmod(value, 10)
    if tens == 0:
        return _CN_DIGITS[ones]
    prefix = "十" if tens == 1 else _CN_DIGITS[tens] + "十"
    return prefix + (_CN_DIGITS[ones] if ones else "")


def _declares_panel_count(prompt: str, count: int) -> bool:
    """Accept the shot count or the square-padded cell count.

    The runtime pads the grid to the next perfect square, so a six-shot sheet
    is a 3x3 of nine cells with three left blank. Both "6 panels" and
    "9 panels" describe that sheet honestly. Chinese numerals with the same
    panel nouns（"九宫格"）count too; a bare "格" still does not.
    """

    side = math.isqrt(count - 1) + 1 if count > 1 else 1
    values = tuple(dict.fromkeys((count, side * side)))
    patterns = [
        pattern
        for value in values
        for pattern in (
            rf"(?<!\d){value}\s*(?:个\s*)?(?:宫格|分镜格|分镜面板|故事板面板|面板)",
            rf"(?<!\d){value}\s*[- ]?\s*panels?\b",
            rf"\bpanels?\s*[:=]?\s*{value}(?!\d)",
        )
    ]
    for value in values:
        numeral = _chinese_numeral(value)
        if numeral:
            # The look-behind keeps "十六" from satisfying a check for 六.
            patterns.append(
                rf"(?<![{_CN_DIGITS}十]){numeral}"
                r"\s*(?:个\s*)?(?:宫格|分镜格|分镜面板|故事板面板|面板)",
            )
    return any(
        re.search(pattern, prompt, re.IGNORECASE) for pattern in patterns
    )


def _ratio_is_declared(prompt: str, aspect_ratio: str) -> bool:
    compact = re.sub(r"\s+", "", prompt).replace("∶", ":")
    return aspect_ratio.replace(" ", "") in compact


def _has_border_contradiction(
    prompt: str,
) -> bool:
    """Reject borderless panels but allow borderless outer whitespace."""

    unambiguous = _BENIGN_BORDER_CONTEXT.sub("", prompt)
    return _BORDER_CONTRADICTION.search(unambiguous) is not None


def _finding(
    *,
    code: str,
    pointer: str,
    message: str,
    suggestion: str,
    element_id: str,
) -> dict[str, str]:
    return {
        "code": code,
        "pointer": pointer,
        "element_id": element_id,
        "message": message,
        "suggestion": suggestion,
    }


def _reference_role_mismatches(
    prompt: str,
    creation: Mapping[str, Any],
    *,
    model_name: str,
    protocol_backend: str,
    language: str,
) -> list[tuple[str, str, str]]:
    """Find explicit numbered-reference role declarations that are swapped.

    Natural-language prompts are allowed to omit role labels. When the author
    does label a mapping, however, a declared prop in the Runtime's scene slot
    is provably wrong and must not reach a paid call.
    """

    expected_roles = ["storyboard"]
    expected_roles.extend(
        "lineup" for _ in (creation.get("cast_lineup_refs") or [])
    )
    expected_roles.extend(
        "character" for _ in (creation.get("character_refs") or [])
    )
    if creation.get("scene_ref"):
        expected_roles.append("scene")
    expected_roles.extend("prop" for _ in (creation.get("prop_refs") or []))

    # Prompts are authored canonically now and rendered per provider at
    # submit, so review sees [Image N]. Legacy prompts still hold the
    # provider's own form, so both are extracted and merged by position.
    all_markers = sorted(
        (
            *video_prompt_image_reference_markers(
                prompt,
                model_name,
                protocol_backend,
                language=language,
            ),
            *(
                (index, match.start(), match.group(0))
                for match in CANONICAL_MARKER_PATTERN.finditer(prompt or "")
                for index in (int(match.group(1)),)
            ),
        ),
        key=lambda item: item[1],
    )
    first_markers: dict[int, tuple[int, str]] = {}
    for index, offset, literal in all_markers:
        first_markers.setdefault(index, (offset, literal))
    mismatches: list[tuple[str, str, str]] = []
    for index, expected in enumerate(expected_roles, start=1):
        marker = first_markers.get(index)
        if marker is None:
            continue
        marker_start, literal = marker
        later = [
            offset
            for _number, offset, _text in all_markers
            if offset > marker_start
        ]
        end = min(later) if later else len(prompt)
        segment = prompt[marker_start:end]
        declared = {
            role
            for role, pattern in _REFERENCE_ROLE_PATTERNS.items()
            if pattern.search(segment)
        }
        # A paragraph may mention exclusions for another role; only a single
        # unambiguous declaration is strong enough to gate automatically.
        if len(declared) == 1:
            actual = next(iter(declared))
            if actual != expected:
                mismatches.append((literal, expected, actual))
    return mismatches


# One pass keeps every finding tied to the same changed-Element snapshot.
# pylint: disable-next=too-many-branches,too-many-statements
def check_changed_r2v_prompt_contracts(
    project_json: Mapping[str, Any],
    changed_pointers: Sequence[str],
) -> dict[str, Any]:
    """Return a JSON-ready contract report for changed R2V Elements."""

    settings = project_json.get("settings")
    settings = settings if isinstance(settings, Mapping) else {}
    aspect_ratio = str(settings.get("aspect_ratio") or "16:9")
    language = str(settings.get("language") or "zh-CN")
    video_model = model_config.get_video_model_name()
    video_backend = model_config.get_video_backend()

    timelines = project_json.get("timelines")
    timelines = timelines if isinstance(timelines, Mapping) else {}
    timeline_items = timelines.get("items")
    timeline_items = (
        timeline_items if isinstance(timeline_items, Mapping) else {}
    )

    findings: list[dict[str, str]] = []
    checked_elements: list[str] = []
    reviewed_pointers: list[str] = []
    for timeline_id, timeline in timeline_items.items():
        if not isinstance(timeline, Mapping):
            continue
        elements = timeline.get("elements_by_id")
        if not isinstance(elements, Mapping):
            continue
        for element_id, element in elements.items():
            if (
                not isinstance(element, Mapping)
                or element.get("enabled") is False
            ):
                continue
            creation = element.get("creation")
            if (
                not isinstance(creation, Mapping)
                or creation.get("type") != "r2v"
            ):
                continue
            base = (
                f"/timelines/items/{_pointer_token(timeline_id)}"
                f"/elements_by_id/{_pointer_token(element_id)}"
            )
            if not _touches_element(base, changed_pointers):
                continue
            checked_elements.append(str(element_id))

            shots = creation.get("shots")
            shots = shots if isinstance(shots, Mapping) else {}
            order = shots.get("order")
            order = order if isinstance(order, list) else []
            items = shots.get("items")
            items = items if isinstance(items, Mapping) else {}
            shot_count = len(order)
            shots_pointer = f"{base}/creation/shots"
            storyboard_pointer = f"{base}/creation/storyboard_prompt"
            video_pointer = f"{base}/creation/video_prompt"
            reviewed_pointers.extend(
                [shots_pointer, storyboard_pointer, video_pointer],
            )

            if shot_count == 0:
                findings.append(
                    _finding(
                        code="R2V_SHOTS_EMPTY",
                        pointer=shots_pointer,
                        element_id=str(element_id),
                        message="R2V Element 没有任何 Shot，无法编译连续分镜。",
                        suggestion="先按可观察状态变化创建有序 Shot；数量由内容决定。",
                    ),
                )

            storyboard_prompt = str(creation.get("storyboard_prompt") or "")
            if not storyboard_prompt.strip():
                findings.append(
                    _finding(
                        code="STORYBOARD_PROMPT_EMPTY",
                        pointer=storyboard_pointer,
                        element_id=str(element_id),
                        message="storyboard_prompt 为空，调度器不会提交付费生图。",
                        suggestion="直接编写制作级分镜 Prompt，不得使用一句话兜底。",
                    ),
                )
            else:
                if not _ratio_is_declared(storyboard_prompt, aspect_ratio):
                    findings.append(
                        _finding(
                            code="STORYBOARD_PANEL_RATIO_MISSING",
                            pointer=storyboard_pointer,
                            element_id=str(element_id),
                            message=(
                                f"storyboard_prompt 未声明每格内部画幅为 "
                                f"{aspect_ratio}。"
                            ),
                            suggestion=(
                                f"明确写入“每一个分镜格内部均为 {aspect_ratio}，"
                                "不得拉伸、裁切或改比”。"
                            ),
                        ),
                    )
                if shot_count and not _declares_panel_count(
                    storyboard_prompt,
                    shot_count,
                ):
                    findings.append(
                        _finding(
                            code="STORYBOARD_PANEL_COUNT_MISSING",
                            pointer=storyboard_pointer,
                            element_id=str(element_id),
                            message=(
                                "storyboard_prompt 未明确声明与 shots 一致的"
                                f" {shot_count} 格面板数。"
                            ),
                            suggestion=f"在交付模式开头明确写 {shot_count} 个分镜格。",
                        ),
                    )
                if shot_count > 1 and _has_border_contradiction(
                    storyboard_prompt,
                ):
                    findings.append(
                        _finding(
                            code="STORYBOARD_BORDER_CONTRADICTION",
                            pointer=storyboard_pointer,
                            element_id=str(element_id),
                            message=(
                                "多格 storyboard_prompt 同时要求无边框，"
                                "与 Runtime 的完整面板分隔合同冲突。"
                            ),
                            suggestion=(
                                "删除“无边框/No borders”，改为完整、清晰、"
                                "等尺寸的面板边界；只禁止装饰性外框。"
                            ),
                        ),
                    )

            video_prompt = str(creation.get("video_prompt") or "")
            if not video_prompt.strip():
                findings.append(
                    _finding(
                        code="VIDEO_PROMPT_EMPTY",
                        pointer=video_pointer,
                        element_id=str(element_id),
                        message="video_prompt 为空，调度器不会提交付费视频任务。",
                        suggestion="按 Shot 顺序、模型引用协议和明确结束状态完成编译。",
                    ),
                )
            else:
                reference_violation = (
                    video_prompt_storyboard_reference_violation(
                        video_prompt,
                        video_model,
                        video_backend,
                        language=language,
                    )
                )
                if reference_violation:
                    findings.append(
                        _finding(
                            code="VIDEO_REFERENCE_SYNTAX_INVALID",
                            pointer=video_pointer,
                            element_id=str(element_id),
                            message=reference_violation,
                            suggestion=(
                                "按当前模型协议重写第一 storyboard 引用；"
                                "不要套用其他 provider 的标记。"
                            ),
                        ),
                    )
                for literal, expected, actual in _reference_role_mismatches(
                    video_prompt,
                    creation,
                    model_name=video_model,
                    protocol_backend=video_backend,
                    language=language,
                ):
                    findings.append(
                        _finding(
                            code="VIDEO_REFERENCE_ROLE_MISMATCH",
                            pointer=video_pointer,
                            element_id=str(element_id),
                            message=(
                                f"{literal} 被声明为 {actual}，"
                                f"但 Runtime 该位置实际是 {expected}。"
                            ),
                            suggestion=(
                                "按 storyboard → cast lineup → character → "
                                "scene → prop → explicit extra refs 重排职责段。"
                            ),
                        ),
                    )
                prompt_key = dialogue_match_key(video_prompt)
                for shot_id in order:
                    shot = items.get(shot_id)
                    if not isinstance(shot, Mapping):
                        continue
                    dialogue = str(shot.get("dialogue") or "").strip()
                    missing_line = next(
                        (
                            line
                            for line in dialogue_spoken_lines(dialogue)
                            if dialogue_match_key(line) not in prompt_key
                        ),
                        None,
                    )
                    if missing_line is not None:
                        findings.append(
                            _finding(
                                code="VIDEO_DIALOGUE_MISSING",
                                pointer=video_pointer,
                                element_id=str(element_id),
                                message=(
                                    f"video_prompt 未逐字包含 Shot {shot_id} 的台词："
                                    f"{missing_line}"
                                ),
                                suggestion="补入台词原文、说话者与表演语气。",
                            ),
                        )

    return {
        "passed": not findings,
        "applicable": bool(checked_elements),
        "checked_elements": checked_elements,
        "reviewed_pointers": list(dict.fromkeys(reviewed_pointers)),
        "model": video_model,
        "backend": video_backend,
        "reference_order": (
            "storyboard → cast lineup → character → scene → prop → "
            "explicit extra refs"
        ),
        "findings": findings,
    }


__all__ = ["check_changed_r2v_prompt_contracts"]
