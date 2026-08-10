# -*- coding: utf-8 -*-
"""Merge artifact extensions into backend-neutral session state."""

from __future__ import annotations

from typing import Any

MAX_WORKSPACE_ARTIFACT_MANIFESTS = 200


def merge_artifact_manifests(
    session_state: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Preserve history and append one deduplicated bounded manifest."""
    loaded = session_state or {}
    prior = loaded.get("workspace_artifact_manifests", [])
    manifests = [item for item in prior if isinstance(item, dict)]
    if manifest is not None:
        turn_id = manifest.get("turn_id")
        manifests = [
            item for item in manifests if item.get("turn_id") != turn_id
        ]
        manifests.append(manifest)
    return manifests[-MAX_WORKSPACE_ARTIFACT_MANIFESTS:]


def merge_artifact_root_mappings(
    session_state: dict[str, Any] | None,
    manifests: list[dict[str, Any]],
    root_mappings: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    """Merge trusted roots and discard mappings no longer in history."""
    loaded = session_state or {}
    prior = loaded.get("workspace_artifact_roots", {})
    roots = (
        {
            key: value
            for key, value in prior.items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        if isinstance(prior, dict)
        else {}
    )
    if root_mappings:
        roots.update(root_mappings)
    referenced: set[str] = set()
    for manifest in manifests:
        for item in manifest.get("artifacts", []):
            if isinstance(item, dict) and isinstance(
                item.get("root_ref"),
                str,
            ):
                referenced.add(item["root_ref"])
        for item in manifest.get("changes", []):
            if isinstance(item, dict) and isinstance(
                item.get("root_ref"),
                str,
            ):
                referenced.add(item["root_ref"])
    return {key: roots[key] for key in referenced if key in roots}


__all__ = [
    "MAX_WORKSPACE_ARTIFACT_MANIFESTS",
    "merge_artifact_manifests",
    "merge_artifact_root_mappings",
]
