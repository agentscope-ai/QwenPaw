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


def test_mismatched_echo_values_are_kept_for_validation():
    candidate = Project.new(
        project_id="project-1",
        name="Initial",
    ).model_dump(mode="json")
    # The echo names another entity: that is information, not redundancy.
    candidate["visual"]["entities"] = _variant_entities(
        entityId="char:someone-else",
    )

    receipts = normalize_project_candidate(candidate)

    assert not receipts
    variant = candidate["visual"]["entities"]["items"]["char:hero"][
        "variants"
    ]["items"]["var:default"]
    assert variant["entityId"] == "char:someone-else"


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


def test_timeline_element_and_shot_echoes_are_stripped():
    candidate = Project.new(
        project_id="project-1",
        name="Initial",
    ).model_dump(mode="json")
    timeline = candidate["timelines"]["items"]["timeline:main"]
    timeline["timelineId"] = "timeline:main"
    timeline["elements_by_id"]["el:intro"] = {
        "elementId": "el:intro",
        "creation": {
            "type": "r2v",
            "shots": {
                "items": {
                    "shot:1": {"shot_id": "shot:1", "shotId": "shot:1"},
                },
                "order": ["shot:1"],
            },
        },
    }

    receipts = normalize_project_candidate(candidate)

    assert sorted(receipts) == [
        "/timelines/items/timeline:main/elements_by_id/el:intro/creation/"
        "shots/items/shot:1/shotId",
        "/timelines/items/timeline:main/elements_by_id/el:intro/elementId",
        "/timelines/items/timeline:main/timelineId",
    ]


def test_timeline_order_echoing_element_keys_is_stripped():
    # Observed: the EntityCollection items/order convention generalized
    # onto Timeline, whose elements_by_id is a plain dict.
    candidate = Project.new(
        project_id="project-1",
        name="Initial",
    ).model_dump(mode="json")
    timeline = candidate["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["el:intro"] = {"elementId": "el:intro"}
    timeline["order"] = ["el:intro"]

    receipts = normalize_project_candidate(candidate)

    assert "/timelines/items/timeline:main/order" in receipts
    assert "order" not in timeline


def test_timeline_order_naming_unknown_elements_is_kept():
    # An order naming elements that do not exist carries information
    # (a dangling reference) and must fail validation instead.
    candidate = Project.new(
        project_id="project-1",
        name="Initial",
    ).model_dump(mode="json")
    timeline = candidate["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["el:intro"] = {}
    timeline["order"] = ["el:intro", "el:ghost"]

    receipts = normalize_project_candidate(candidate)

    assert not receipts
    assert timeline["order"] == ["el:intro", "el:ghost"]


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
