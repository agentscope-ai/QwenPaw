# -*- coding: utf-8 -*-

from __future__ import annotations

from urllib.parse import unquote

import pytest
from playwright.sync_api import expect

from pages.plan_page import PlanPage


pytestmark = pytest.mark.timeline


def _location() -> dict:
    return {
        "coordinate_space": "normalized_canvas",
        "x": 0,
        "y": 0,
        "width": 1,
        "height": 1,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
        "rotation_degrees": 0,
        "opacity": 1,
    }


def _elements() -> dict:
    return {
        "r2v-opening": {
            "element_id": "r2v-opening",
            "label": "开场主画面",
            "enabled": True,
            "span": {"start_tick": 0, "duration_tick": 8000},
            "location": _location(),
            "z_index": 0,
            "creation": {
                "type": "r2v",
                "intent": "建立开场",
                "narrative": "小猫在晨光中醒来",
            },
            "outputs": {},
            "render_source": None,
            "provenance_refs": [],
        },
        "overlay-title": {
            "element_id": "overlay-title",
            "label": "开场标题",
            "enabled": True,
            "span": {"start_tick": 2000, "duration_tick": 4000},
            "location": {
                **_location(),
                "x": 0.1,
                "y": 0.08,
                "width": 0.8,
                "height": 0.2,
            },
            "z_index": 10,
            "creation": {
                "type": "overlay",
                "overlay_kind": "pet_os",
                "text": "今天也要元气满满",
                "vibe": "warm",
                "prompt": "",
                "reference_version_ids": [],
            },
            "outputs": {},
            "render_source": None,
            "provenance_refs": [],
        },
    }


def test_project_and_plan_use_only_timeline_element_contract(
    page,
    api,
    project,
):
    project_id = project["projectId"]
    snapshot = api.project_snapshot(project_id)
    document = snapshot["project"]
    assert document["schema_version"] == 2
    assert document["timelines"]["order"] == ["timeline:main"]
    assert "sections" not in document
    assert "units" not in document

    timeline = document["timelines"]["items"]["timeline:main"]
    updated = api.replace_elements(
        project_id,
        snapshot=snapshot,
        timeline_id=timeline["timeline_id"],
        before=timeline["elements_by_id"],
        elements=_elements(),
    )
    assert set(
        updated["project"]["timelines"]["items"]["timeline:main"][
            "elements_by_id"
        ],
    ) == {"r2v-opening", "overlay-title"}

    plan = PlanPage(page).open(project_id)
    expect(page.get_by_text("2 Elements", exact=True)).to_be_visible()
    expect(plan.element_list_item("r2v-opening")).to_be_visible()
    expect(plan.element_list_item("overlay-title")).to_be_visible()
    expect(plan.element_block("r2v-opening")).to_be_visible()
    expect(plan.element_block("overlay-title")).to_be_visible()

    plan.select_element("overlay-title")
    assert "element=overlay-title" in unquote(page.url)
    expect(plan.element_list_item("overlay-title")).to_have_attribute(
        "data-element-list-item",
        "overlay-title",
    )


def test_collapsed_overlap_picker_and_large_video_preview(page, api, project):
    project_id = project["projectId"]
    snapshot = api.project_snapshot(project_id)
    timeline = snapshot["project"]["timelines"]["items"]["timeline:main"]
    api.replace_elements(
        project_id,
        snapshot=snapshot,
        timeline_id=timeline["timeline_id"],
        before=timeline["elements_by_id"],
        elements=_elements(),
    )

    plan = PlanPage(page).open(project_id).collapse_timeline()
    plan.select_timeline_fraction(0.45)
    candidates = page.locator("[data-timeline-point-candidates]")
    expect(candidates).to_be_visible()
    expect(candidates.get_by_role("button")).to_have_count(2)
    candidates.get_by_role("button", name="开场标题", exact=True).click()
    expect(plan.element_detail("overlay-title")).to_be_visible()

    preview = plan.open_video_preview()
    expect(preview.get_by_text("尚无 Timeline 成片", exact=True)).to_be_visible()
    box = preview.bounding_box()
    assert box is not None
    assert box["height"] >= 380
    assert abs(box["width"] / box["height"] - 16 / 9) < 0.12
