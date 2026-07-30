# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Typed side effects for explicit frontend Element draft commits.

User operations remain ordinary schema-v2 JSON Pointer edits.  Before the
Project commit is published, this module derives which selected artifacts no
longer describe the edited Project and marks those immutable versions stale in
the same transaction.  The bytes and slot history are retained.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from html import escape, unescape
import re
from typing import Any, Mapping, Sequence

from .json_pointer import split_pointer


@dataclass(slots=True)
class EditImpact:
    affected_element_ids: set[str] = field(default_factory=set)
    affected_timeline_ids: set[str] = field(default_factory=set)
    invalidated_artifact_version_ids: set[str] = field(default_factory=set)
    render_timeline_ids: set[str] = field(default_factory=set)
    regeneration_required: bool = False

    def response(self) -> dict[str, Any]:
        return {
            "affectedElementIds": sorted(self.affected_element_ids),
            "affectedTimelineIds": sorted(self.affected_timeline_ids),
            "invalidatedArtifactVersionIds": sorted(
                self.invalidated_artifact_version_ids,
            ),
            "renderTimelineIds": sorted(self.render_timeline_ids),
            "regenerationRequired": self.regeneration_required,
            "renderBlockedByGeneration": self.regeneration_required,
        }


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(document: Mapping[str, Any], *path: str) -> dict[str, Any]:
    current: Any = document
    for token in path:
        current = _record(current).get(token)
    return _record(current)


def _timeline_element(
    document: Mapping[str, Any],
    timeline_id: str,
    element_id: str,
) -> dict[str, Any] | None:
    timeline = _items(document, "timelines", "items").get(timeline_id)
    element = _items(_record(timeline), "elements_by_id").get(element_id)
    return element if isinstance(element, dict) else None


def _find_element(
    document: Mapping[str, Any],
    element_id: str,
) -> tuple[str, dict[str, Any]] | None:
    for timeline_id, raw_timeline in _items(
        document,
        "timelines",
        "items",
    ).items():
        element = _items(_record(raw_timeline), "elements_by_id").get(
            element_id,
        )
        if isinstance(element, dict):
            return timeline_id, element
    return None


def _selected_version_id(
    document: Mapping[str, Any],
    slot_id: str,
) -> str | None:
    slot = _items(
        document,
        "assets",
        "artifact_slots_by_id",
    ).get(slot_id)
    selected = _record(slot).get("selected_version_id")
    return selected if isinstance(selected, str) and selected else None


def _mark_selected_stale(
    document: dict[str, Any],
    slot_id: str,
    *,
    reason: str,
    impact: EditImpact,
) -> None:
    version_id = _selected_version_id(document, slot_id)
    if version_id is None:
        return
    version = _items(
        document,
        "assets",
        "artifact_versions_by_id",
    ).get(version_id)
    if not isinstance(version, dict):
        return
    version["stale"] = True
    version["stale_reason"] = reason
    impact.invalidated_artifact_version_ids.add(version_id)


def _element_slot_ids(
    document: Mapping[str, Any],
    element_id: str,
    element: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    storyboard: set[str] = set()
    generated: set[str] = set()
    outputs = _record(element.get("outputs"))
    for name, raw_output in outputs.items():
        slot_id = _record(raw_output).get("slot_id")
        if not isinstance(slot_id, str) or not slot_id:
            continue
        if name == "storyboard":
            storyboard.add(slot_id)
        else:
            generated.add(slot_id)
    slots = _items(document, "assets", "artifact_slots_by_id")
    for slot_id in (
        f"element:{element_id}:storyboard",
        f"element:{element_id}:video",
        f"element:{element_id}:main",
    ):
        if slot_id not in slots:
            continue
        if slot_id.endswith(":storyboard"):
            storyboard.add(slot_id)
        else:
            generated.add(slot_id)
    return storyboard, generated


def _mark_timeline_render_stale(
    document: dict[str, Any],
    timeline_id: str,
    impact: EditImpact,
) -> None:
    impact.affected_timeline_ids.add(timeline_id)
    impact.render_timeline_ids.add(timeline_id)
    owner_ref = f"timeline:{timeline_id}"
    for slot_id, raw_slot in _items(
        document,
        "assets",
        "artifact_slots_by_id",
    ).items():
        slot = _record(raw_slot)
        if slot.get("owner_ref") != owner_ref:
            continue
        _mark_selected_stale(
            document,
            slot_id,
            reason="时间线内容已修改，需要重新合成",
            impact=impact,
        )
        version_id = _selected_version_id(document, slot_id)
        version = _items(
            document,
            "assets",
            "artifact_versions_by_id",
        ).get(version_id)
        if not isinstance(version, dict):
            continue
        metadata = dict(_record(version.get("metadata")))
        raw_pending_ids = metadata.get("pendingAffectedElementIds")
        pending_ids = (
            {
                value
                for value in raw_pending_ids
                if isinstance(value, str) and value
            }
            if isinstance(raw_pending_ids, list)
            else set()
        )
        pending_ids.update(impact.affected_element_ids)
        if pending_ids:
            # Keep the invalidation scope with the stale render itself.  The
            # frontend can then continue using completed frames outside these
            # Element spans after navigation or a full page refresh.
            metadata["pendingAffectedElementIds"] = sorted(pending_ids)
            version["metadata"] = metadata


def _invalidate_r2v_outputs(
    document: dict[str, Any],
    element_id: str,
    element: Mapping[str, Any],
    *,
    include_storyboard: bool,
    impact: EditImpact,
) -> None:
    storyboard_slots, video_slots = _element_slot_ids(
        document,
        element_id,
        element,
    )
    target_slots = set(video_slots)
    if include_storyboard:
        target_slots.update(storyboard_slots)
    impact.regeneration_required = True
    for slot_id in target_slots:
        _mark_selected_stale(
            document,
            slot_id,
            reason="Element 生成输入已修改，需要重新生成",
            impact=impact,
        )


_R2V_VIDEO_ONLY_FIELDS = {
    "video_prompt",
    "video_reference_version_ids",
}
_EDIT_METADATA_FIELDS = {"intent", "reason"}
_OVERLAY_GENERATION_INPUT_FIELDS = {
    "overlay_kind",
    "vibe",
    "prompt",
    "reference_version_ids",
}
_TEXT_OVERLAY_KINDS = {"pet_os", "interview_summary"}
_BODY_PATTERN = re.compile(
    r"(?is)(<body\b[^>]*>)(.*?)(</body\s*>)",
)
_HTML_TOKEN_PATTERN = re.compile(r"(?is)(<!--.*?-->|<[^>]+>)")


def _rebind_motion_copy(
    motion_html: str,
    *,
    old_text: str,
    new_text: str,
) -> str | None:
    # pylint: disable=too-many-branches,too-many-statements
    """Replace only visible copy while preserving the motion document.

    Generated caption cards may split one sentence over ``<br>`` or several
    animated spans.  Work on visible text nodes and distribute the new copy
    across the same nodes, leaving every tag, class and CSS animation intact.
    """

    old_copy = re.sub(r"\s+", "", old_text)
    new_copy = new_text.strip()
    if not old_copy or old_copy == re.sub(r"\s+", "", new_copy):
        return motion_html
    body_match = _BODY_PATTERN.search(motion_html)
    if body_match is None:
        return None
    body = body_match.group(2)
    tokens = _HTML_TOKEN_PATTERN.split(body)
    text_nodes: list[tuple[int, str, int, int]] = []
    visible_parts: list[str] = []
    visible_offset = 0
    suppressed_depth = 0
    for index, token in enumerate(tokens):
        if not token:
            continue
        if token.startswith("<"):
            tag_match = re.match(r"(?is)<\s*(/?)\s*([a-z0-9:-]+)", token)
            if tag_match is not None and tag_match.group(2).lower() == "style":
                if tag_match.group(1):
                    suppressed_depth = max(0, suppressed_depth - 1)
                elif not token.rstrip().endswith("/>"):
                    suppressed_depth += 1
            continue
        if suppressed_depth:
            continue
        normalized = re.sub(r"\s+", "", unescape(token))
        if not normalized:
            continue
        start = visible_offset
        visible_offset += len(normalized)
        text_nodes.append((index, normalized, start, visible_offset))
        visible_parts.append(normalized)

    visible = "".join(visible_parts)
    copy_start = visible.find(old_copy)
    if copy_start < 0:
        return None
    copy_end = copy_start + len(old_copy)
    affected: list[tuple[int, str, int, int, int]] = []
    for index, normalized, node_start, node_end in text_nodes:
        overlap_start = max(copy_start, node_start)
        overlap_end = min(copy_end, node_end)
        if overlap_end <= overlap_start:
            continue
        affected.append(
            (
                index,
                normalized,
                overlap_start - node_start,
                overlap_end - node_start,
                overlap_end - overlap_start,
            ),
        )
    if not affected:
        return None

    total_weight = sum(item[4] for item in affected)
    consumed_weight = 0
    consumed_copy = 0
    for position, (
        index,
        normalized,
        local_start,
        local_end,
        weight,
    ) in enumerate(
        affected,
    ):
        consumed_weight += weight
        next_copy = (
            len(new_copy)
            if position == len(affected) - 1
            else round(len(new_copy) * consumed_weight / total_weight)
        )
        replacement = new_copy[consumed_copy:next_copy]
        consumed_copy = next_copy
        tokens[index] = escape(
            normalized[:local_start] + replacement + normalized[local_end:],
            quote=False,
        )

    rebound_body = "".join(tokens)
    return (
        motion_html[: body_match.start(2)]
        + rebound_body
        + motion_html[body_match.end(2) :]
    )


def _apply_element_path(  # pylint: disable=too-many-branches
    document: dict[str, Any],
    tokens: tuple[str, ...],
    impact: EditImpact,
    *,
    base_document: Mapping[str, Any] | None = None,
) -> None:
    if (
        len(tokens) < 5
        or tokens[0] != "timelines"
        or tokens[1] != "items"
        or tokens[3] != "elements_by_id"
    ):
        return
    timeline_id, element_id = tokens[2], tokens[4]
    element = _timeline_element(document, timeline_id, element_id)
    if element is None:
        return
    impact.affected_element_ids.add(element_id)
    suffix = tokens[5:]
    if not suffix:
        _mark_timeline_render_stale(document, timeline_id, impact)
        return
    if suffix[0] == "label":
        return

    creation = _record(element.get("creation"))
    creation_type = creation.get("type")
    if creation_type == "edit" and (
        len(suffix) >= 2
        and suffix[0] == "creation"
        and suffix[1] in _EDIT_METADATA_FIELDS
    ):
        return

    if creation_type == "r2v":
        include_storyboard = True
        generated_input_changed = False
        if suffix[0] == "creation":
            generated_input_changed = True
            include_storyboard = not (
                len(suffix) >= 2 and suffix[1] in _R2V_VIDEO_ONLY_FIELDS
            )
        elif suffix[:2] == ("span", "duration_tick"):
            generated_input_changed = True
            include_storyboard = False
        if generated_input_changed:
            _invalidate_r2v_outputs(
                document,
                element_id,
                element,
                include_storyboard=include_storyboard,
                impact=impact,
            )
    elif (
        creation_type == "overlay"
        and len(suffix) >= 2
        and suffix[0] == "creation"
    ):
        field_name = suffix[1]
        overlay_kind = creation.get("overlay_kind")
        generation_input_changed = (
            field_name in _OVERLAY_GENERATION_INPUT_FIELDS
            or (field_name == "text" and overlay_kind == "motion")
        )
        motion = creation.get("motion")
        if (
            field_name == "text"
            and overlay_kind in _TEXT_OVERLAY_KINDS
            and isinstance(motion, dict)
            and isinstance(motion.get("html"), str)
            and base_document is not None
        ):
            base_element = _timeline_element(
                base_document,
                timeline_id,
                element_id,
            )
            base_creation = _record(
                _record(base_element).get("creation"),
            )
            old_text = base_creation.get("text")
            new_text = creation.get("text")
            if isinstance(old_text, str) and isinstance(new_text, str):
                rebound = _rebind_motion_copy(
                    motion["html"],
                    old_text=old_text,
                    new_text=new_text,
                )
                if rebound is not None:
                    motion["html"] = rebound
                else:
                    # Legacy documents that no longer contain their authority
                    # copy cannot be safely rebound.  Keep the established
                    # deterministic fallback rather than rendering stale text.
                    creation["motion"] = None
        elif (
            field_name in _OVERLAY_GENERATION_INPUT_FIELDS
            or (field_name == "text" and overlay_kind == "motion")
        ) and creation.get("motion") is not None:
            # Styling/prompt changes intentionally request a new projection.
            creation["motion"] = None
        if generation_input_changed:
            _, generated_slots = _element_slot_ids(
                document,
                element_id,
                element,
            )
            impact.regeneration_required = True
            for slot_id in generated_slots:
                _mark_selected_stale(
                    document,
                    slot_id,
                    reason="Overlay 生成输入已修改，需要重新生成",
                    impact=impact,
                )

    _mark_timeline_render_stale(document, timeline_id, impact)


def _apply_slot_selection_path(
    document: dict[str, Any],
    tokens: tuple[str, ...],
    impact: EditImpact,
) -> None:
    if (
        len(tokens) != 4
        or tokens[:2] != ("assets", "artifact_slots_by_id")
        or tokens[3] != "selected_version_id"
    ):
        return
    slot_id = tokens[2]
    slot = _items(document, "assets", "artifact_slots_by_id").get(slot_id)
    owner_ref = _record(slot).get("owner_ref")
    if not isinstance(owner_ref, str) or not owner_ref.startswith("element:"):
        return
    element_id = owner_ref.removeprefix("element:")
    found = _find_element(document, element_id)
    if found is None:
        return
    timeline_id, element = found
    impact.affected_element_ids.add(element_id)
    if slot_id.endswith(":storyboard"):
        _, video_slots = _element_slot_ids(document, element_id, element)
        impact.regeneration_required = True
        for video_slot_id in video_slots:
            _mark_selected_stale(
                document,
                video_slot_id,
                reason="Storyboard 当前版本已切换，需要重新生成视频",
                impact=impact,
            )
    _mark_timeline_render_stale(document, timeline_id, impact)


def _pointer_value(
    document: Mapping[str, Any] | None,
    tokens: tuple[str, ...],
) -> tuple[bool, Any]:
    """Walk the JSON Pointer token chain; return (exists, value)."""

    node: Any = document
    for token in tokens:
        if isinstance(node, Mapping):
            if token not in node:
                return False, None
            node = node[token]
        elif isinstance(node, list):
            try:
                index = int(token)
            except ValueError:
                return False, None
            if not 0 <= index < len(node):
                return False, None
            node = node[index]
        else:
            return False, None
    return True, node


def _pointer_unchanged(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    tokens: tuple[str, ...],
) -> bool:
    """True when the submitted pointer value matches in base and candidate."""

    base_found, base_value = _pointer_value(base, tokens)
    candidate_found, candidate_value = _pointer_value(candidate, tokens)
    return base_found == candidate_found and base_value == candidate_value


def apply_frontend_edit_impacts(
    candidate: Mapping[str, Any],
    submitted_pointers: Sequence[str],
    *,
    base: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], EditImpact]:
    """Return a candidate with all derived stale flags applied atomically."""

    document = copy.deepcopy(dict(candidate))
    impact = EditImpact()
    for pointer in dict.fromkeys(submitted_pointers):
        tokens = split_pointer(pointer)
        if base is not None and _pointer_unchanged(base, document, tokens):
            # The pointer was submitted but its value equals the baseline
            # (no-op edit): must not invalidate any generated artifact or
            # final video.
            continue
        _apply_element_path(
            document,
            tokens,
            impact,
            base_document=base,
        )
        _apply_slot_selection_path(document, tokens, impact)
    return document, impact


def summarize_committed_edit_impact(
    project: Mapping[str, Any],
    changed_pointers: Sequence[str],
) -> EditImpact:
    """Reconstruct the response contract from a finalized transaction."""

    impact = EditImpact()
    # Re-running the classifier on a copy is deterministic and also covers
    # the no-selected-artifact case where the commit contains no induced
    # stale path.
    _, classified = apply_frontend_edit_impacts(project, changed_pointers)
    impact.affected_element_ids.update(classified.affected_element_ids)
    impact.affected_timeline_ids.update(classified.affected_timeline_ids)
    impact.invalidated_artifact_version_ids.update(
        classified.invalidated_artifact_version_ids,
    )
    impact.render_timeline_ids.update(classified.render_timeline_ids)
    impact.regeneration_required = classified.regeneration_required

    versions = _items(project, "assets", "artifact_versions_by_id")
    for pointer in changed_pointers:
        tokens = split_pointer(pointer)
        if (
            len(tokens) < 4
            or tokens[:2] != ("assets", "artifact_versions_by_id")
            or tokens[3] not in {"stale", "stale_reason"}
        ):
            continue
        version_id = tokens[2]
        version = _record(versions.get(version_id))
        if not version.get("stale"):
            continue
        impact.invalidated_artifact_version_ids.add(version_id)
        owner_ref = version.get("owner_ref")
        if isinstance(owner_ref, str) and owner_ref.startswith("timeline:"):
            timeline_id = owner_ref.removeprefix("timeline:")
            impact.affected_timeline_ids.add(timeline_id)
            impact.render_timeline_ids.add(timeline_id)
        elif isinstance(owner_ref, str) and owner_ref.startswith("element:"):
            element_id = owner_ref.removeprefix("element:")
            impact.affected_element_ids.add(element_id)
            impact.regeneration_required = True
    return impact


__all__ = [
    "EditImpact",
    "apply_frontend_edit_impacts",
    "summarize_committed_edit_impact",
]
