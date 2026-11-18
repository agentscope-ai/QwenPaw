# -*- coding: utf-8 -*-
"""Script invalidation follows the inputs of the affected narrative node."""

from __future__ import annotations

import copy

import pytest

from services.project_files.edit_impact import apply_frontend_edit_impacts

NODES = ("prologue", "ending-a", "ending-b", "hidden")


def _project():
    return {
        "name": "Linear story",
        "settings": {"target_duration_seconds": 60},
        "timelines": {
            "order": list(NODES),
            "items": {
                node: {
                    "title": node,
                    "synopsis": f"Synopsis of {node}",
                    "description": f"Saved script of {node}",
                    "planned_duration_seconds": 30,
                }
                for node in NODES
            },
        },
        "assets": {
            "artifact_slots_by_id": {
                f"script:{node}": {
                    "kind": "timeline_script",
                    "owner_ref": f"timeline:{node}",
                    "selected_version_id": f"script-v1:{node}",
                }
                for node in NODES
            },
            "artifact_versions_by_id": {
                f"script-v1:{node}": {"stale": False} for node in NODES
            },
        },
    }


def _invalidated(base, candidate, pointers):
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        pointers,
        base=base,
    )
    expected_ids = {
        version_id
        for version_id, version in updated["assets"][
            "artifact_versions_by_id"
        ].items()
        if version["stale"]
    }
    assert impact.invalidated_artifact_version_ids == expected_ids
    assert candidate["assets"] == base["assets"]  # No in-place mutation.
    return {key.removeprefix("script-v1:") for key in expected_ids}


@pytest.mark.parametrize("field", ["description", "planned_duration_seconds"])
def test_local_script_inputs_only_invalidate_their_owner(field):
    base = _project()
    candidate = copy.deepcopy(base)
    candidate["timelines"]["items"]["ending-b"][field] = (
        "Revised body" if field == "description" else 90
    )
    assert _invalidated(
        base,
        candidate,
        [f"/timelines/items/ending-b/{field}"],
    ) == {"ending-b"}


def test_duration_default_only_affects_scripts_without_an_override():
    base = _project()
    base["timelines"]["items"]["ending-b"]["planned_duration_seconds"] = None
    candidate = copy.deepcopy(base)
    candidate["settings"]["target_duration_seconds"] = 90
    assert _invalidated(
        base,
        candidate,
        ["/settings/target_duration_seconds"],
    ) == {"ending-b"}


@pytest.mark.parametrize("field", ["title", "synopsis"])
def test_shared_narrative_outline_changes_still_invalidate_scripts(field):
    # Every draft explicitly consumes the live outline for continuity.
    base = _project()
    candidate = copy.deepcopy(base)
    candidate["timelines"]["items"]["ending-b"][field] = "New story premise"
    assert _invalidated(
        base,
        candidate,
        [f"/timelines/items/ending-b/{field}"],
    ) == set(NODES)


def test_project_creative_brief_still_invalidates_scripts():
    base = _project()
    candidate = copy.deepcopy(base)
    candidate["strategy"] = {"creative_brief": "Change the story genre"}
    assert _invalidated(base, candidate, ["/strategy"]) == set(NODES)


def test_noop_and_frozen_history_do_not_invalidate_scripts():
    base = _project()
    candidate = copy.deepcopy(base)
    candidate["timelines"]["items"]["snapshot:prologue:1"] = copy.deepcopy(
        candidate["timelines"]["items"]["prologue"],
    )
    candidate["timelines"]["order"].append("snapshot:prologue:1")
    assert not _invalidated(
        base,
        candidate,
        ["/timelines"],
    )
