# -*- coding: utf-8 -*-
"""Migration Provider registry."""

from __future__ import annotations

from typing import Any

from .base import MigrationProvider
from .codex import CodexMigrationProvider
from .locator import canonical_provider_id, resolve_source_location
from .qoder import QoderMigrationProvider


def provider_names() -> tuple[str, ...]:
    """Return canonical source names currently supported for migration."""
    return ("codex", "qoder")


def create_migration_provider(
    source: str,
    workspace: Any,
) -> MigrationProvider:
    """Create one read-only provider or raise a user-actionable error."""
    provider_id = canonical_provider_id(source)
    location = resolve_source_location(provider_id)
    if provider_id == "codex":
        return CodexMigrationProvider(workspace, source_location=location)
    if provider_id == "qoder":
        return QoderMigrationProvider(workspace, source_location=location)
    raise AssertionError(f"Unreachable provider id: {provider_id}")


__all__ = [
    "MigrationProvider",
    "canonical_provider_id",
    "create_migration_provider",
    "provider_names",
    "resolve_source_location",
]
