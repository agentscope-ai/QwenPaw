# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Deterministic, in-memory migrations for ``project.json`` documents.

Schema migrations are intentionally separate from Project content commits.
They upgrade an older raw document before Pydantic validation; persisting the
upgraded form still has to go through the normal Project commit boundary.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from .models import CURRENT_PROJECT_SCHEMA_VERSION


class ProjectMigrationError(ValueError):
    """The raw Project cannot be upgraded without losing authority."""


ProjectMigration = Callable[[dict[str, Any]], dict[str, Any]]


# A migration registered under N must return exactly schema_version N + 1.
PROJECT_MIGRATIONS: dict[int, ProjectMigration] = {}


def migrate_project_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached document at the current Project schema version.

    Each step is applied to a deep copy and must preserve ``project_id``.  A
    future schema or a missing migration fails closed; unknown fields are left
    for the current strict Pydantic model to reject after migration.
    """

    if not isinstance(raw, Mapping):
        raise ProjectMigrationError("project.json root must be an object")
    document = copy.deepcopy(dict(raw))
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectMigrationError(
            "project.json schema_version must be an integer",
        )
    if version < 1:
        # Schemas predating the first file-native Project document require an
        # out-of-band one-time conversion. Accepting an unregistered v0
        # document in the Runtime would silently guess at its meaning.
        if version not in PROJECT_MIGRATIONS:
            raise ProjectMigrationError(
                f"no Project migration is registered for schema_version {version}",
            )
    if version > CURRENT_PROJECT_SCHEMA_VERSION:
        raise ProjectMigrationError(
            "project.json was written by a newer schema: "
            f"{version} > {CURRENT_PROJECT_SCHEMA_VERSION}",
        )

    original_project_id = document.get("project_id")
    while version < CURRENT_PROJECT_SCHEMA_VERSION:
        migration = PROJECT_MIGRATIONS.get(version)
        if migration is None:
            raise ProjectMigrationError(
                f"no Project migration is registered for schema_version {version}",
            )
        candidate = migration(copy.deepcopy(document))
        if not isinstance(candidate, dict):
            raise ProjectMigrationError(
                f"Project migration {version} must return one JSON object",
            )
        next_version = candidate.get("schema_version")
        if next_version != version + 1:
            raise ProjectMigrationError(
                f"Project migration {version} must produce schema_version {version + 1}",
            )
        if candidate.get("project_id") != original_project_id:
            raise ProjectMigrationError(
                f"Project migration {version} cannot change project_id",
            )
        document = candidate
        version = next_version
    return document


__all__ = [
    "PROJECT_MIGRATIONS",
    "ProjectMigration",
    "ProjectMigrationError",
    "migrate_project_document",
]
