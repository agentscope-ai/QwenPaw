# -*- coding: utf-8 -*-
"""Migration Provider registry."""

from __future__ import annotations

from typing import Any

from ..models import SourceLocation
from .base import MigrationProvider
from .locator import canonical_provider_id, resolve_source_location


_REQUIRED_PLUGINS = {
    "codex": "qwenpaw-harness-codex",
    "qoder": "qwenpaw-harness-qoder",
}


class HarnessPluginRequiredError(RuntimeError):
    """The source's installed plugin has no active Harness contribution."""

    def __init__(self, source: str, plugin_id: str, state: str):
        self.detail = {
            "code": "harness_plugin_required",
            "source": source,
            "plugin_id": plugin_id,
            "state": state,
        }
        super().__init__(f"{source} requires {plugin_id} ({state})")


def harness_plugin_state(source: str) -> tuple[str, str]:
    """Read current ownership from memory without discovering source data."""
    from ...plugins.errors import SDKError
    from ...plugins.registry import PluginRegistry

    source = canonical_provider_id(source)
    plugin_id = _REQUIRED_PLUGINS[source]
    registry = PluginRegistry()
    state = registry.get_harness_states().get(plugin_id, "missing")
    # Retained failed cleanup owners must remain unavailable as well.
    # pylint: disable=protected-access
    entry = registry.backend_registry._entries.get(source)
    if (
        entry is not None
        and entry.owner.plugin_id == plugin_id
        and entry._context is not None
    ):
        try:
            entry.assert_active()
            return plugin_id, "available"
        except SDKError:
            if entry._context._instance.state.value == "failed":
                state = "failed"
    # pylint: enable=protected-access
    return plugin_id, state


def require_harness_plugin(source: str) -> None:
    """Reject migration before any provider construction or source probe."""
    source = canonical_provider_id(source)
    plugin_id, state = harness_plugin_state(source)
    if state != "available":
        raise HarnessPluginRequiredError(source, plugin_id, state)


def provider_names() -> tuple[str, ...]:
    """Return canonical source names currently supported for migration."""
    return ("codex", "qoder")


def create_migration_provider(
    source: str,
    workspace: Any,
    *,
    source_location: SourceLocation | None = None,
) -> MigrationProvider:
    """Create one read-only provider or raise a user-actionable error."""
    provider_id = canonical_provider_id(source)
    require_harness_plugin(provider_id)
    location = source_location or resolve_source_location(provider_id)
    if provider_id == "codex":
        from .codex import CodexMigrationProvider

        return CodexMigrationProvider(workspace, source_location=location)
    if provider_id == "qoder":
        from .qoder import QoderMigrationProvider

        return QoderMigrationProvider(workspace, source_location=location)
    raise AssertionError(f"Unreachable provider id: {provider_id}")


__all__ = [
    "MigrationProvider",
    "canonical_provider_id",
    "create_migration_provider",
    "provider_names",
    "resolve_source_location",
]
