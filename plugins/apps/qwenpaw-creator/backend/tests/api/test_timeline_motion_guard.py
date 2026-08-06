# -*- coding: utf-8 -*-
from __future__ import annotations

from api.file_execution_routes import (
    _timeline_has_text_overlays_without_motion,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    OverlayCreation,
    Project,
    Timeline,
    TimelineElement,
    TimelineSpan,
)


def _services_and_project(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    snapshot = services.projects.create(
        Project.new(project_id="proj-1", name="Test"),
    )
    return services, snapshot


def _text_overlay(
    element_id: str,
    *,
    motion: dict | None = None,
    enabled: bool = True,
) -> TimelineElement:
    creation = OverlayCreation(
        text="测试文案",
        motion=motion,
    )
    return TimelineElement(
        element_id=element_id,
        enabled=enabled,
        span=TimelineSpan(start_tick=0, duration_tick=100),
        location=ElementLocation(),
        creation=creation,
    )


def _with_timeline(services, snapshot, timeline):
    updated = snapshot.project.model_dump(mode="json")
    tid = timeline.timeline_id
    updated["timelines"]["items"][tid] = timeline.model_dump(mode="json")
    if tid not in updated["timelines"]["order"]:
        updated["timelines"]["order"].append(tid)
    updated["generation"] = snapshot.generation + 1
    return services.projects.replace(
        "proj-1",
        Project.model_validate(updated),
        expected_etag=snapshot.etag,
    )


_MOTION = {
    "html": "<!doctype html><html><body>styled</body></html>",
    "fps": 24,
    "loop": True,
}


def test_no_text_overlays_returns_false(tmp_path) -> None:
    services, _ = _services_and_project(tmp_path)
    assert (
        _timeline_has_text_overlays_without_motion(
            services,
            "proj-1",
            "tl-1",
        )
        is False
    )


def test_all_text_overlays_have_motion_returns_false(tmp_path) -> None:
    services, snapshot = _services_and_project(tmp_path)
    timeline = Timeline(
        timeline_id="tl-1",
        elements_by_id={
            "overlay-1": _text_overlay("overlay-1", motion=_MOTION),
            "overlay-2": _text_overlay("overlay-2", motion=_MOTION),
        },
    )
    _with_timeline(services, snapshot, timeline)

    assert (
        _timeline_has_text_overlays_without_motion(
            services,
            "proj-1",
            "tl-1",
        )
        is False
    )


def test_text_overlay_without_motion_returns_true(tmp_path) -> None:
    services, snapshot = _services_and_project(tmp_path)
    timeline = Timeline(
        timeline_id="tl-1",
        elements_by_id={
            "overlay-1": _text_overlay("overlay-1"),
        },
    )
    _with_timeline(services, snapshot, timeline)

    assert (
        _timeline_has_text_overlays_without_motion(
            services,
            "proj-1",
            "tl-1",
        )
        is True
    )


def test_disabled_overlay_is_ignored(tmp_path) -> None:
    services, snapshot = _services_and_project(tmp_path)
    timeline = Timeline(
        timeline_id="tl-1",
        elements_by_id={
            "overlay-1": _text_overlay("overlay-1", enabled=False),
        },
    )
    _with_timeline(services, snapshot, timeline)

    assert (
        _timeline_has_text_overlays_without_motion(
            services,
            "proj-1",
            "tl-1",
        )
        is False
    )


def test_decoration_overlay_is_ignored(tmp_path) -> None:
    services, snapshot = _services_and_project(tmp_path)
    # Text-free decoration overlays never require a caption motion design.
    creation = OverlayCreation(
        text="",
        prompt="decoration",
    )
    element = TimelineElement(
        element_id="overlay-1",
        span=TimelineSpan(start_tick=0, duration_tick=100),
        location=ElementLocation(),
        creation=creation,
    )
    timeline = Timeline(
        timeline_id="tl-1",
        elements_by_id={"overlay-1": element},
    )
    _with_timeline(services, snapshot, timeline)

    assert (
        _timeline_has_text_overlays_without_motion(
            services,
            "proj-1",
            "tl-1",
        )
        is False
    )


def test_mixed_motion_and_no_motion_returns_true(tmp_path) -> None:
    services, snapshot = _services_and_project(tmp_path)
    timeline = Timeline(
        timeline_id="tl-1",
        elements_by_id={
            "overlay-1": _text_overlay("overlay-1", motion=_MOTION),
            "overlay-2": _text_overlay("overlay-2"),
        },
    )
    _with_timeline(services, snapshot, timeline)

    assert (
        _timeline_has_text_overlays_without_motion(
            services,
            "proj-1",
            "tl-1",
        )
        is True
    )
