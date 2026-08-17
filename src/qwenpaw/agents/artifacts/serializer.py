# -*- coding: utf-8 -*-
"""Serialize artifact metadata into the versioned chat manifest contract."""

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

from .models import ArtifactCollection, ArtifactRoot

_SUPPORTED_MANIFEST_VERSIONS = frozenset({1, 2, 3})
_ARTIFACT_CHANGES = frozenset({"created", "modified"})
_CHANGES = frozenset({"created", "modified", "deleted"})
_PREVIEW_KINDS = frozenset(
    {"image", "pdf", "markdown", "csv", "text", "none"},
)
_ROOTS = frozenset({"workspace", "project"})


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_non_negative_integer(value: Any) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )


def _is_relative_artifact_path(value: Any) -> bool:
    if not _is_non_empty_string(value) or "\\" in value or "\0" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(
        part not in {"", ".", ".."} for part in path.parts
    )


def _parse_root(value: Any, version: int) -> str | None:
    if version == 1 and value is None:
        return "workspace"
    if isinstance(value, str) and value in _ROOTS:
        return value
    return None


def _parse_artifact(value: Any, version: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    root = _parse_root(value.get("root"), version)
    fields_are_valid = all(
        (
            _is_relative_artifact_path(value.get("path")),
            _is_non_empty_string(value.get("name")),
            isinstance(value.get("extension"), str),
            _is_non_empty_string(value.get("mime_type")),
            _is_non_negative_integer(value.get("size")),
            _is_non_negative_integer(value.get("modified_ns")),
            value.get("change") in _ARTIFACT_CHANGES,
            value.get("preview") in _PREVIEW_KINDS,
        ),
    )
    if root is None or not fields_are_valid:
        return None
    parsed = {
        "path": value["path"],
        "name": value["name"],
        "extension": value["extension"],
        "mime_type": value["mime_type"],
        "size": value["size"],
        "modified_ns": value["modified_ns"],
        "change": value["change"],
        "preview": value["preview"],
        "root": root,
    }
    if version == 3:
        root_ref = value.get("root_ref")
        if not _is_non_empty_string(root_ref):
            return None
        parsed["root_ref"] = root_ref
    return parsed


def _parse_change(value: Any, version: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    root = _parse_root(value.get("root"), version)
    if (
        root is None
        or not _is_relative_artifact_path(value.get("path"))
        or value.get("change") not in _CHANGES
    ):
        return None
    parsed = {
        "path": value["path"],
        "change": value["change"],
        "root": root,
    }
    if version == 3:
        root_ref = value.get("root_ref")
        if not _is_non_empty_string(root_ref):
            return None
        parsed["root_ref"] = root_ref
    return parsed


def parse_manifest(value: Any) -> dict[str, Any] | None:
    """Validate and normalize a persisted artifact manifest."""
    if not isinstance(value, dict):
        return None
    version = value.get("version")
    artifacts = value.get("artifacts")
    changes = value.get("changes")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in _SUPPORTED_MANIFEST_VERSIONS
    ):
        return None
    fields_are_valid = all(
        (
            _is_non_empty_string(value.get("agent_id")),
            _is_non_empty_string(value.get("chat_id")),
            _is_non_empty_string(value.get("turn_id")),
            _is_non_empty_string(value.get("created_at")),
            isinstance(artifacts, list),
            isinstance(changes, list),
            isinstance(value.get("truncated"), bool),
        ),
    )
    if not fields_are_valid:
        return None
    parsed_artifacts = [_parse_artifact(item, version) for item in artifacts]
    parsed_changes = [_parse_change(item, version) for item in changes]
    if any(item is None for item in parsed_artifacts + parsed_changes):
        return None
    return {
        "version": version,
        "agent_id": value["agent_id"],
        "chat_id": value["chat_id"],
        "turn_id": value["turn_id"],
        "created_at": value["created_at"],
        "artifacts": parsed_artifacts,
        "changes": parsed_changes,
        "truncated": value["truncated"],
    }


def serialize_manifest(
    collection: ArtifactCollection,
    *,
    agent_id: str,
    chat_id: str,
    turn_id: str,
    created_at: str | None = None,
    root_refs: Mapping[ArtifactRoot, str] | None = None,
) -> dict[str, Any]:
    """Return JSON-compatible metadata without file bytes or absolute paths."""
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    return {
        "version": 3 if root_refs is not None else 2,
        "agent_id": agent_id,
        "chat_id": chat_id,
        "turn_id": turn_id,
        "created_at": timestamp,
        "artifacts": [
            {
                "path": artifact.path,
                "name": artifact.name,
                "extension": artifact.extension,
                "mime_type": artifact.mime_type,
                "size": artifact.size,
                "modified_ns": artifact.modified_ns,
                "change": artifact.change,
                "preview": artifact.preview,
                "root": artifact.root,
                **(
                    {"root_ref": root_refs[artifact.root]}
                    if root_refs is not None
                    else {}
                ),
            }
            for artifact in collection.artifacts
        ],
        "changes": [
            {
                "path": change.path,
                "change": change.change,
                "root": change.root,
                **(
                    {"root_ref": root_refs[change.root]}
                    if root_refs is not None
                    else {}
                ),
            }
            for change in collection.changes
        ],
        "truncated": collection.truncated,
    }
