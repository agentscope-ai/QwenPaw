# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectToolError,
    AgentProjectTools,
)
from services.project_files.candidate_normalization import (
    normalize_project_candidate,
)
from services.project_files.models import Project
from services.project_files.store import ProjectStore


pytestmark = pytest.mark.unit


def _variant_entities(**variant_extra) -> dict:
    return {
        "items": {
            "char:hero": {
                "entity_id": "char:hero",
                "kind": "character",
                "name": "Hero",
                "required_variant_ids": ["var:default"],
                "variants": {
                    "items": {
                        "var:default": {
                            "variant_id": "var:default",
                            **variant_extra,
                        },
                    },
                    "order": ["var:default"],
                },
            },
        },
        "order": ["char:hero"],
    }


def test_identity_echoes_are_stripped_with_receipts():
    candidate = Project.new(
        project_id="project-1",
        name="Initial",
    ).model_dump(mode="json")
    candidate["visual"]["entities"] = _variant_entities(
        entityId="char:hero",
        variantId="var:default",
    )
    candidate["visual"]["entities"]["items"]["char:hero"][
        "entityId"
    ] = "char:hero"

    receipts = normalize_project_candidate(candidate)

    assert sorted(receipts) == [
        "/visual/entities/items/char:hero/entityId",
        "/visual/entities/items/char:hero/variants/items/var:default/"
        "entityId",
        "/visual/entities/items/char:hero/variants/items/var:default/"
        "variantId",
    ]
    # The candidate now validates cleanly: echoes carried zero information.
    Project.model_validate(candidate)


def test_real_snake_case_identity_fields_are_never_stripped():
    candidate = Project.new(
        project_id="project-1",
        name="Initial",
    ).model_dump(mode="json")
    candidate["visual"]["entities"] = _variant_entities()

    receipts = normalize_project_candidate(candidate)

    assert not receipts
    entity = candidate["visual"]["entities"]["items"]["char:hero"]
    assert entity["entity_id"] == "char:hero"
    assert entity["variants"]["items"]["var:default"]["variant_id"] == (
        "var:default"
    )


def test_jq_project_commits_echoed_variants_and_reports_normalization(
    tmp_path,
):
    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id="project-1", name="Initial"))
    tools = AgentProjectTools(
        store,
        context=AgentProjectToolContext(
            origin="runtime_task",
            caused_by_request_id="request-1",
            caused_by_message_seq=1,
        ),
    )
    tools.invoke("read_project", {"projectId": "project-1"})

    result = tools.invoke(
        "jq_project",
        {
            "projectId": "project-1",
            "program": ".visual.entities = $entities",
            "jsonArgs": {
                "entities": _variant_entities(entityId="char:hero"),
            },
        },
    )

    assert result["normalizedPointers"] == [
        "/visual/entities/items/char:hero/variants/items/var:default/"
        "entityId",
    ]
    variant = result["project"]["visual"]["entities"]["items"]["char:hero"][
        "variants"
    ]["items"]["var:default"]
    assert "entityId" not in variant

    # A mismatched echo is information-bearing and must still fail loudly.
    with pytest.raises(AgentProjectToolError) as caught:
        tools.invoke(
            "jq_project",
            {
                "projectId": "project-1",
                "program": ".visual.entities = $entities",
                "jsonArgs": {
                    "entities": _variant_entities(
                        entityId="char:someone-else",
                    ),
                },
            },
        )
    assert caught.value.code == "JQ_PROJECT_SCHEMA_INVALID"
    assert "entityId" in str(caught.value)


def _make_timeline_with_shots_and_overlays(
    shots: list[tuple[str, int, int]],
    overlays: list[tuple[str, int, int]],
) -> dict:
    """Helper to create a timeline dict with shot and overlay elements."""
    elements_by_id = {}
    for shot_id, start, dur in shots:
        elements_by_id[shot_id] = {
            "element_id": shot_id,
            "span": {"start_tick": start, "duration_tick": dur},
            "creation": {"type": "edit"},
            "location": None,
            "z_index": 0,
            "outputs": {},
            "render_source": None,
        }
    for ov_id, start, dur in overlays:
        elements_by_id[ov_id] = {
            "element_id": ov_id,
            "span": {"start_tick": start, "duration_tick": dur},
            "creation": {"type": "overlay", "text": "test"},
            "location": {
                "coordinate_space": "normalized_canvas",
                "x": 0.5,
                "y": 0.5,
                "width": 1.0,
                "height": 0.2,
                "anchor_x": 0.5,
                "anchor_y": 0.5,
            },
            "z_index": 100,
            "outputs": {},
            "render_source": None,
        }
    return {
        "timeline_id": "timeline:main",
        "ticks_per_second": 1000,
        "elements_by_id": elements_by_id,
    }


def test_overlay_local_ticks_corrected_to_global():
    """Overlay with shot-local ticks should be corrected to global ticks."""
    shots = [
        ("shot:01", 0, 8000),
        ("shot:02", 8000, 8000),
        ("shot:03", 16000, 8000),
    ]
    # Overlay meant for shot:03 but with local ticks [4000, 7500)
    # Should be corrected to [20000, 23500)
    overlays = [("subtitle:03b:6", 4000, 3500)]
    timeline = _make_timeline_with_shots_and_overlays(shots, overlays)
    candidate = {
        "timelines": {"items": {"timeline:main": timeline}},
    }

    from services.project_files.candidate_normalization import (
        correct_overlay_local_ticks,
    )

    receipts = correct_overlay_local_ticks(candidate)

    assert len(receipts) == 1
    assert "+16000 via shot:03" in receipts[0]
    elem = candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "subtitle:03b:6"
    ]
    assert elem["span"]["start_tick"] == 20000


def test_overlay_with_correct_global_ticks_not_modified():
    """Overlay with correct global ticks should not be modified."""
    shots = [
        ("shot:01", 0, 8000),
        ("shot:02", 8000, 8000),
    ]
    # Overlay with correct global ticks [9000, 12000) - intersects shot:02
    overlays = [("subtitle:02a", 9000, 3000)]
    timeline = _make_timeline_with_shots_and_overlays(shots, overlays)
    candidate = {
        "timelines": {"items": {"timeline:main": timeline}},
    }

    from services.project_files.candidate_normalization import (
        correct_overlay_local_ticks,
    )

    receipts = correct_overlay_local_ticks(candidate)

    assert len(receipts) == 0
    elem = candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "subtitle:02a"
    ]
    assert elem["span"]["start_tick"] == 9000


def test_ambiguous_overlay_not_corrected():
    """Overlay that matches multiple shots should not be corrected."""
    # Two shots with same duration - overlay could belong to either
    shots = [
        ("shot:01", 0, 5000),
        ("shot:02", 5000, 5000),
    ]
    # Overlay with local ticks [1000, 3000) - could be in either shot
    overlays = [("subtitle:ambiguous", 1000, 2000)]
    timeline = _make_timeline_with_shots_and_overlays(shots, overlays)
    candidate = {
        "timelines": {"items": {"timeline:main": timeline}},
    }

    from services.project_files.candidate_normalization import (
        correct_overlay_local_ticks,
    )

    receipts = correct_overlay_local_ticks(candidate)

    # Should not be corrected because both offsets produce valid intersections
    assert len(receipts) == 0
    elem = candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "subtitle:ambiguous"
    ]
    assert elem["span"]["start_tick"] == 1000


def test_existing_overlay_in_base_not_processed():
    """Overlays that exist in base should not be processed."""
    shots = [
        ("shot:01", 0, 8000),
        ("shot:02", 8000, 8000),
    ]
    # Overlay with local ticks that exists in base
    overlays = [("subtitle:existing", 1000, 2000)]
    timeline = _make_timeline_with_shots_and_overlays(shots, overlays)
    candidate = {
        "timelines": {"items": {"timeline:main": timeline}},
    }
    base = {
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {"subtitle:existing": {}},
                },
            },
        },
    }

    from services.project_files.candidate_normalization import (
        correct_overlay_local_ticks,
    )

    receipts = correct_overlay_local_ticks(candidate, base=base)

    # Should not be corrected because it exists in base
    assert len(receipts) == 0
    elem = candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "subtitle:existing"
    ]
    assert elem["span"]["start_tick"] == 1000


def test_normalize_project_candidate_includes_tick_corrections():
    """normalize_project_candidate should include tick correction receipts."""
    shots = [
        ("shot:01", 0, 8000),
        ("shot:02", 8000, 8000),
    ]
    overlays = [("subtitle:02a", 1000, 2000)]  # local ticks for shot:02
    timeline = _make_timeline_with_shots_and_overlays(shots, overlays)
    candidate = {
        "timelines": {"items": {"timeline:main": timeline}},
        "visual": {"entities": {"items": {}, "order": []}},
    }
    base = {
        "timelines": {"items": {"timeline:main": {"elements_by_id": {}}}},
        "visual": {"entities": {"items": {}, "order": []}},
    }

    receipts = normalize_project_candidate(candidate, base=base)

    tick_receipts = [r for r in receipts if "+8000" in r]
    assert len(tick_receipts) == 1
    elem = candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "subtitle:02a"
    ]
    assert elem["span"]["start_tick"] == 9000
