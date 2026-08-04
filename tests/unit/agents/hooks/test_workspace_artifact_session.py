from qwenpaw.hooks.session.session_hook import (
    _merge_workspace_artifact_manifests,
)


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
