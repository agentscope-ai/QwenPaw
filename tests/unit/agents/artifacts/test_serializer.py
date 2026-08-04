# -*- coding: utf-8 -*-
from qwenpaw.agents.artifacts import (
    ArtifactCollection,
    WorkspaceArtifact,
    WorkspaceChange,
    serialize_manifest,
)


def test_serialize_manifest_is_versioned_metadata_only() -> None:
    collection = ArtifactCollection(
        artifacts=(
            WorkspaceArtifact(
                path="reports/report.xlsx",
                name="report.xlsx",
                extension=".xlsx",
                mime_type="application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet",
                size=12,
                modified_ns=34,
                change="created",
                preview="none",
            ),
        ),
        changes=(WorkspaceChange("reports/report.xlsx", "created"),),
    )

    manifest = serialize_manifest(
        collection,
        agent_id="analyst",
        chat_id="chat-1",
        turn_id="turn-1",
        created_at="2026-08-03T00:00:00+00:00",
    )

    assert manifest["version"] == 1
    assert manifest["agent_id"] == "analyst"
    assert manifest["artifacts"][0]["path"] == "reports/report.xlsx"
    assert "absolute" not in str(manifest)
    assert "content" not in manifest["artifacts"][0]
