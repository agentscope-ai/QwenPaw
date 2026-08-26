# -*- coding: utf-8 -*-
"""Benign trailing closers execute the lossless prefix instead of failing.

Reproduces the 2026-08 production case: a 4.4KB streamed tool-call
argument ended with exactly one surplus ``}`` after a complete JSON
object, forcing a repair-and-retry turn even though dropping the tail
was provably lossless.
"""
from __future__ import annotations

import json

import pytest

from services.file_agent_runtime.model_client import _parse_tool_arguments
from services.file_agent_runtime.driver import _unfinished_video_element_ids
from services.project_files.models import (
    ArtifactSlot,
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
)


pytestmark = pytest.mark.unit


def test_single_surplus_closing_brace_is_accepted_as_strict():
    payload = {"projectId": "p-1", "program": ".", "jsonArgs": {"a": 1}}
    raw = json.dumps(payload) + "}"

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert arguments == payload
    assert parse_error is None
    assert repaired is False
    assert strict_error is None


def test_trailing_real_content_still_goes_through_repair():
    # The tail carries information (a truncated sibling key): accepting the
    # prefix would silently drop it, so the repair path must stay in charge.
    payload = {"projectId": "p-1", "jsonArgs": {"a": 1}}
    raw = json.dumps(payload) + ', "program": "."}'

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert strict_error is not None
    assert repaired or parse_error is not None
    assert arguments != payload or repaired


# ---------------------------------------------------------------------------
# YOLO completion loop: unfinished video detection
# ---------------------------------------------------------------------------


def _element(element_id: str, start_tick: int = 0) -> TimelineElement:
    shot = Shot(
        shot_id=f"{element_id}-shot",
        description="测试镜头",
        camera="⊙ 静止",
        framing="全景",
        duration_seconds=4,
    )
    return TimelineElement(
        element_id=element_id,
        label=element_id,
        span=TimelineSpan(start_tick=start_tick, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="测试叙事",
            storyboard_prompt="测试分镜",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )


def _project_with_elements(*element_ids: str) -> Project:
    project = Project.new(project_id="p-yolo", name="YOLO Loop")
    timeline = project.timelines.items["timeline:main"]
    for index, element_id in enumerate(element_ids):
        timeline.elements_by_id[element_id] = _element(
            element_id,
            start_tick=index * 4_000,
        )
    return project


def _finish_video(project: Project, element_id: str) -> None:
    slot_id = f"element:{element_id}:main"
    project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
        slot_id=slot_id,
        kind="element_video",
        owner_ref=f"element:{element_id}",
        version_ids=["artifact-version-x"],
        selected_version_id="artifact-version-x",
    )


def test_elements_without_main_video_are_unfinished():
    project = _project_with_elements("elem:a", "elem:b", "elem:c")
    _finish_video(project, "elem:b")

    assert _unfinished_video_element_ids(project) == ["elem:a", "elem:c"]


def test_unselected_video_slot_is_still_unfinished():
    project = _project_with_elements("elem:a")
    slot_id = "element:elem:a:main"
    project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
        slot_id=slot_id,
        kind="element_video",
        owner_ref="element:elem:a",
        version_ids=[],
        selected_version_id=None,
    )

    assert _unfinished_video_element_ids(project) == ["elem:a"]
