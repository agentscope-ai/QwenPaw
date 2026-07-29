# -*- coding: utf-8 -*-
"""Shared helpers for media tools that operate on Timeline Elements."""

from __future__ import annotations

from typing import Any

from domain.errors import ConflictError, NotFoundError, ValidationError
from services.project_files.models import (
    ArtifactSlot,
    ElementOutput,
    Project,
    Timeline,
    TimelineElement,
)


def target_element_id(target_ref: str, *, command: str) -> str:
    prefix = "element:"
    if target_ref.startswith(prefix) and target_ref[len(prefix) :]:
        return target_ref[len(prefix) :]
    raise ValidationError(f"{command} targetRef 必须是 element:<id>")


def find_timeline_element(
    project: Project,
    element_id: str,
) -> tuple[Timeline, TimelineElement]:
    found: tuple[Timeline, TimelineElement] | None = None
    for timeline in project.timelines.items.values():
        element = timeline.elements_by_id.get(element_id)
        if element is None:
            continue
        if (
            found is not None
        ):  # Project graph validation normally prevents this.
            raise ConflictError(f"Element ID 在多个 Timeline 中重复: {element_id}")
        found = (timeline, element)
    if found is None:
        raise NotFoundError("Timeline Element 不存在")
    return found


def element_output_slot_id(element_id: str, output_name: str) -> str:
    return f"element:{element_id}:{output_name}"


def selected_element_output(
    project: Project,
    element: TimelineElement,
    output_name: str,
) -> tuple[ArtifactSlot, str] | None:
    output = element.outputs.get(output_name)
    if output is None:
        return None
    slot = project.assets.artifact_slots_by_id.get(output.slot_id)
    if slot is None or slot.selected_version_id is None:
        return None
    return slot, slot.selected_version_id


def candidate_element(
    candidate: dict[str, Any],
    element_id: str,
) -> dict[str, Any]:
    timelines = candidate.get("timelines", {}).get("items", {})
    for timeline in timelines.values():
        element = timeline.get("elements_by_id", {}).get(element_id)
        if element is not None:
            return element
    raise ConflictError("Timeline Element 已不存在")


def bind_candidate_output(
    candidate: dict[str, Any],
    *,
    element_id: str,
    output_name: str,
    slot_id: str,
    select_for_render: bool,
) -> None:
    element = candidate_element(candidate, element_id)
    outputs = element.setdefault("outputs", {})
    raw_output = outputs.get(output_name)
    expected = ElementOutput(slot_id=slot_id).model_dump(mode="json")
    if raw_output is not None and raw_output != expected:
        raise ConflictError("Element named output 已绑定到其他 ArtifactSlot")
    outputs[output_name] = expected
    if select_for_render:
        element["render_source"] = {
            "type": "element_output",
            "element_id": element_id,
            "output_name": output_name,
            "source_in_tick": 0,
            "source_out_tick": None,
            "playback_rate": 1.0,
            "loop": False,
        }


__all__ = [
    "bind_candidate_output",
    "candidate_element",
    "element_output_slot_id",
    "find_timeline_element",
    "selected_element_output",
    "target_element_id",
]
