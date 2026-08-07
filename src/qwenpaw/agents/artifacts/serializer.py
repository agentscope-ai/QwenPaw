# -*- coding: utf-8 -*-
"""Serialize artifact metadata into the versioned chat manifest contract."""

from datetime import datetime, timezone
from typing import Any

from .models import ArtifactCollection


def serialize_manifest(
    collection: ArtifactCollection,
    *,
    agent_id: str,
    chat_id: str,
    turn_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Return JSON-compatible metadata without file bytes or absolute paths."""
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    return {
        "version": 2,
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
            }
            for artifact in collection.artifacts
        ],
        "changes": [
            {
                "path": change.path,
                "change": change.change,
                "root": change.root,
            }
            for change in collection.changes
        ],
        "truncated": collection.truncated,
    }
