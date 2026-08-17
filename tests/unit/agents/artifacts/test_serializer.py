# -*- coding: utf-8 -*-
from qwenpaw.agents.artifacts import (
    ArtifactCollection,
    WorkspaceArtifact,
    WorkspaceChange,
    parse_manifest,
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
                root="project",
            ),
        ),
        changes=(
            WorkspaceChange(
                "reports/report.xlsx",
                "created",
                "project",
            ),
        ),
    )

    manifest = serialize_manifest(
        collection,
        agent_id="analyst",
        chat_id="chat-1",
        turn_id="turn-1",
        created_at="2026-08-03T00:00:00+00:00",
    )

    assert manifest["version"] == 2
    assert manifest["agent_id"] == "analyst"
    assert manifest["artifacts"][0]["path"] == "reports/report.xlsx"
    assert manifest["artifacts"][0]["root"] == "project"
    assert manifest["changes"][0]["root"] == "project"
    assert "absolute" not in str(manifest)
    assert "content" not in manifest["artifacts"][0]


def test_parse_manifest_normalizes_version_one_root() -> None:
    manifest = {
        "version": 1,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "created_at": "2026-08-03T00:00:00+00:00",
        "artifacts": [
            {
                "path": "report.txt",
                "name": "report.txt",
                "extension": ".txt",
                "mime_type": "text/plain",
                "size": 12,
                "modified_ns": 34,
                "change": "created",
                "preview": "text",
            },
        ],
        "changes": [{"path": "report.txt", "change": "created"}],
        "truncated": False,
    }

    parsed = parse_manifest(manifest)

    assert parsed is not None
    assert parsed["artifacts"][0]["root"] == "workspace"
    assert parsed["changes"][0]["root"] == "workspace"


def test_parse_manifest_rejects_unsafe_path() -> None:
    manifest = {
        "version": 2,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "created_at": "2026-08-03T00:00:00+00:00",
        "artifacts": [],
        "changes": [
            {
                "path": "../outside.txt",
                "change": "created",
                "root": "project",
            },
        ],
        "truncated": False,
    }

    assert parse_manifest(manifest) is None


def test_serialize_version_three_includes_opaque_root_reference() -> None:
    collection = ArtifactCollection(
        artifacts=(
            WorkspaceArtifact(
                path="report.txt",
                name="report.txt",
                extension=".txt",
                mime_type="text/plain",
                size=12,
                modified_ns=34,
                change="created",
                preview="text",
                root="project",
            ),
        ),
        changes=(WorkspaceChange("report.txt", "created", "project"),),
    )

    manifest = serialize_manifest(
        collection,
        agent_id="analyst",
        chat_id="chat-1",
        turn_id="turn-1",
        root_refs={"project": "root-1"},
    )

    assert manifest["version"] == 3
    assert manifest["artifacts"][0]["root_ref"] == "root-1"
    assert manifest["changes"][0]["root_ref"] == "root-1"
    assert parse_manifest(manifest) == manifest
