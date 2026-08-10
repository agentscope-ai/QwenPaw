# -*- coding: utf-8 -*-
from qwenpaw.hooks.session.session_hook import (
    _merge_workspace_artifact_manifests,
)
from qwenpaw.agents.artifacts import merge_artifact_root_mappings


def test_manifest_merge_preserves_history_without_new_artifacts() -> None:
    prior = [{"version": 1, "turn_id": "turn-1"}]

    result = _merge_workspace_artifact_manifests(
        {"workspace_artifact_manifests": prior},
        None,
    )

    assert result == prior


def test_manifest_merge_replaces_duplicate_turn() -> None:
    result = _merge_workspace_artifact_manifests(
        {
            "workspace_artifact_manifests": [
                {"version": 1, "turn_id": "turn-1", "value": "old"},
            ],
        },
        {"version": 1, "turn_id": "turn-1", "value": "new"},
    )

    assert result == [
        {"version": 1, "turn_id": "turn-1", "value": "new"},
    ]


def test_manifest_merge_keeps_latest_two_hundred() -> None:
    prior = [
        {"version": 1, "turn_id": f"turn-{index}"} for index in range(205)
    ]

    result = _merge_workspace_artifact_manifests(
        {"workspace_artifact_manifests": prior},
        None,
    )

    assert len(result) == 200
    assert result[0]["turn_id"] == "turn-5"


def test_root_mapping_merge_keeps_only_referenced_roots() -> None:
    manifests = [
        {
            "version": 3,
            "artifacts": [{"root_ref": "root-new"}],
            "changes": [],
        },
    ]

    result = merge_artifact_root_mappings(
        {
            "workspace_artifact_roots": {
                "root-old": {"root": "project", "path": "old"},
            },
        },
        manifests,
        {"root-new": {"root": "project", "path": "new"}},
    )

    assert result == {
        "root-new": {"root": "project", "path": "new"},
    }
