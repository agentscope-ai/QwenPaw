# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

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


def _overlay(element_id, *, enabled=True, **creation) -> TimelineElement:
    creation.setdefault("text", "测试文案")
    return TimelineElement(
        element_id=element_id,
        enabled=enabled,
        span=TimelineSpan(start_tick=0, duration_tick=100),
        location=ElementLocation(),
        creation=OverlayCreation(**creation),
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


def _flag(services) -> bool:
    return _timeline_has_text_overlays_without_motion(
        services,
        "proj-1",
        "tl-1",
    )


_MOTION = {
    "html": "<!doctype html><html><body>styled</body></html>",
    "fps": 24,
    "loop": True,
}


def test_no_text_overlays_returns_false(tmp_path) -> None:
    services, _ = _services_and_project(tmp_path)
    assert _flag(services) is False


@pytest.mark.parametrize(
    ("overlays", "expected"),
    [
        pytest.param(
            {"overlay-1": {"motion": _MOTION}, "overlay-2": {}},
            True,
            id="mixed-motion-and-no-motion",
        ),
        pytest.param(
            {"overlay-1": {"enabled": False}},
            False,
            id="disabled-overlay-ignored",
        ),
        # Text-free decoration overlays never need a caption motion design.
        pytest.param(
            {"overlay-1": {"text": "", "prompt": "decoration"}},
            False,
            id="text-free-decoration-overlay-ignored",
        ),
    ],
)
def test_text_overlay_motion_flag(tmp_path, overlays, expected) -> None:
    services, snapshot = _services_and_project(tmp_path)
    timeline = Timeline(
        timeline_id="tl-1",
        elements_by_id={
            element_id: _overlay(element_id, **kwargs)
            for element_id, kwargs in overlays.items()
        },
    )
    _with_timeline(services, snapshot, timeline)

    assert _flag(services) is expected
