# -*- coding: utf-8 -*-
"""Deterministic pre-generation checks for authored R2V prompts.

Taste remains an LLM review concern. This module only checks contracts that
the Runtime can prove from Project state before a paid storyboard/video call:
presence, panel count/ratio, obvious layout contradictions, verbatim dialogue
coverage and provider-specific storyboard reference syntax.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import re
from typing import Any

from models import config as model_config
from models.reference_markers import CANONICAL_MARKER_PATTERN
from models.video_capabilities import (
    video_prompt_image_reference_markers,
    video_prompt_storyboard_reference_violation,
)
from services.storyboard_layout import declared_storyboard_panel_count
from services.prompt_text import missing_narrative_dialogue

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


def _canonical_type_roles(creation: Mapping[str, Any]) -> list[str]:
    """Reference roles in the automatic-chain order.

    With no authored ``video_reference_version_ids`` the runtime falls back to
    the canonical chain (storyboard → lineup → character → scene → prop), so
    counting each bound reference type reconstructs the real ``[Image N]``
    order exactly.
    """

    roles = ["storyboard"]
    roles.extend("lineup" for _ in (creation.get("cast_lineup_refs") or []))
    roles.extend("character" for _ in (creation.get("character_refs") or []))
    if creation.get("scene_ref"):
        roles.append("scene")
    roles.extend("prop" for _ in (creation.get("prop_refs") or []))
    return roles


def _bound_entity_roles(creation: Mapping[str, Any]) -> dict[str, str]:
    """Map bound asset/lineup owner references to semantic reference roles."""

    roles: dict[str, str] = {}
    for ref in creation.get("cast_lineup_refs") or []:
        roles[f"lineup:{ref}"] = "lineup"
    for ref in creation.get("character_refs") or []:
        roles[f"asset:{ref}"] = "character"
    scene_ref = creation.get("scene_ref")
    if scene_ref:
        roles[f"asset:{scene_ref}"] = "scene"
    for ref in creation.get("prop_refs") or []:
        roles[f"asset:{ref}"] = "prop"
    return roles


def _version_owner_entities(project_json: Mapping[str, Any]) -> dict[str, str]:
    """Map version IDs to qualified asset/lineup owner references."""

    assets = project_json.get("assets")
    assets = assets if isinstance(assets, Mapping) else {}
    owners: dict[str, str] = {}
    for registry in ("artifact_versions_by_id", "source_versions_by_id"):
        table = assets.get(registry)
        if not isinstance(table, Mapping):
            continue
        for version_id, version in table.items():
            if not isinstance(version, Mapping):
                continue
            owner = version.get("owner_ref")
            if isinstance(owner, str) and owner.startswith(
                ("asset:", "lineup:"),
            ):
                owners[str(version_id)] = owner
    return owners


def _expected_reference_roles(
    project_json: Mapping[str, Any],
    element: Mapping[str, Any],
    creation: Mapping[str, Any],
    element_id: str,
    load_project: Callable[[], Any],
) -> list[str | None]:
    """Resolve the role actually bound to each runtime ``[Image N]`` slot.

    An explicit ``video_reference_version_ids`` list preserves authored order,
    with this Element's storyboard reserved first even before generation and
    its own storyboard versions dropped. The canonical type order therefore
    no longer predicts the positions. Label each slot from its bound owner;
    a slot whose owner cannot be resolved stays ``None`` and is never gated,
    because a false block on a paid call is worse than a missed label.
    """

    explicit = list(
        dict.fromkeys(
            str(version_id)
            for version_id in (
                creation.get("video_reference_version_ids") or []
            )
        ),
    )
    if not explicit:
        from pydantic import ValidationError as SchemaValidationError
        from domain.errors import ValidationError
        from services.project_files.models import R2VCreation
        from services.media_files.visual_reference_resolution import (
            resolve_r2v_visual_reference_version_ids,
        )

        project = load_project()
        if project is None:
            # Partial text-review fixtures have no materialized selections.
            # Actual Projects always use the same resolver as the executor.
            return _canonical_type_roles(creation)
        try:
            live_creation = R2VCreation.model_validate(creation)
            explicit = list(
                resolve_r2v_visual_reference_version_ids(
                    project,
                    live_creation,
                    (),
                ),
            )
        except SchemaValidationError:
            return _canonical_type_roles(creation)
        except ValidationError:
            # Dependency validation supplies the actionable missing-input
            # error. Do not invent shifted role slots for unresolved inputs.
            return ["storyboard"]

    assets = project_json.get("assets")
    assets = assets if isinstance(assets, Mapping) else {}
    slots = assets.get("artifact_slots_by_id")
    slots = slots if isinstance(slots, Mapping) else {}
    outputs = element.get("outputs")
    outputs = outputs if isinstance(outputs, Mapping) else {}
    storyboard_output = outputs.get("storyboard")
    storyboard_output = (
        storyboard_output if isinstance(storyboard_output, Mapping) else {}
    )
    slot_id = str(
        storyboard_output.get("slot_id") or f"element:{element_id}:storyboard",
    )
    slot = slots.get(slot_id)
    slot = slot if isinstance(slot, Mapping) else {}
    selected = slot.get("selected_version_id")
    storyboard_id = str(selected) if selected else None
    own_versions = {
        str(version_id) for version_id in (slot.get("version_ids") or ())
    }
    if storyboard_id:
        own_versions.add(storyboard_id)

    entity_roles = _bound_entity_roles(creation)
    version_owners = _version_owner_entities(project_json)
    roles: list[str | None] = ["storyboard"]
    for version_id in explicit:
        if version_id in own_versions:
            continue
        entity = version_owners.get(version_id)
        roles.append(entity_roles.get(entity) if entity else None)
    return roles


def _reference_role_mismatches(
    prompt: str,
    expected_roles: Sequence[str | None],
    *,
    model_name: str,
    protocol_backend: str,
    language: str,
) -> list[tuple[str, str, str]]:
    """Find explicit numbered-reference role declarations that are swapped.

    Natural-language prompts are allowed to omit role labels. When the author
    does label a mapping, however, a declared prop in the Runtime's scene
    slot is provably wrong and must not reach a paid call. ``expected_roles``
    carries the role bound to each real ``[Image N]`` slot; an unresolved
    (``None``) slot is skipped rather than guessed.
    """

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
        if expected is None:
            # Unresolved owner: never guess a role for a paid-call gate.
            continue
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
    validated_project: list[Any] = []

    def load_project() -> Any:
        if not validated_project:
            from pydantic import ValidationError as SchemaValidationError
            from services.project_files.models import Project

            try:
                validated_project.append(Project.model_validate(project_json))
            except SchemaValidationError:
                validated_project.append(None)
        return validated_project[0]

    checked_elements: list[str] = []
    reviewed_pointers: list[str] = []
    for timeline_id, timeline in timeline_items.items():
        if str(timeline_id).startswith("snapshot:") or not isinstance(
            timeline,
            Mapping,
        ):
            # Historical copies are immutable and have no generation nodes.
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

            storyboard_pointer = f"{base}/creation/storyboard_prompt"
            video_pointer = f"{base}/creation/video_prompt"
            reviewed_pointers.extend([storyboard_pointer, video_pointer])

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
                panel_count = declared_storyboard_panel_count(
                    storyboard_prompt,
                )
                if panel_count is None:
                    findings.append(
                        _finding(
                            code="STORYBOARD_PANEL_COUNT_MISSING",
                            pointer=storyboard_pointer,
                            element_id=str(element_id),
                            message=("分镜图未明确写清关键帧数量或网格排布，" "或数量说明互相矛盾。"),
                            suggestion=(
                                "写明实际画布比例、关键帧数量、几列几行和阅读顺序；"
                                "数量由动作推进与衔接需要决定，不必等于视频镜头数。"
                            ),
                        ),
                    )
                if (
                    panel_count
                    and panel_count > 1
                    and _has_border_contradiction(
                        storyboard_prompt,
                    )
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
                        suggestion="按片段叙述的动作顺序、模型引用协议和明确结束状态完成编译。",
                    ),
                )
            else:
                for line in missing_narrative_dialogue(
                    str(creation.get("narrative") or ""),
                    video_prompt,
                ):
                    findings.append(
                        _finding(
                            code="VIDEO_DIALOGUE_MISSING",
                            pointer=video_pointer,
                            element_id=str(element_id),
                            message=f"视频提示词遗漏片段叙述中的对白或旁白：{line}",
                            suggestion="将已写明的台词原文、说话者和声音方式保留在视频提示词中。",
                        ),
                    )
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
                expected_roles = _expected_reference_roles(
                    project_json,
                    element,
                    creation,
                    str(element_id),
                    load_project,
                )
                for literal, expected, actual in _reference_role_mismatches(
                    video_prompt,
                    expected_roles,
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
