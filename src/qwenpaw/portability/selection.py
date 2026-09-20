# -*- coding: utf-8 -*-
"""Select the user-approved subset of a provider inventory."""

from __future__ import annotations

from typing import Any

from .models import ImportSelection, MigrationPlan, ProviderInventory

PLAN_SELECTION_FIELDS = {
    "memory": "memory",
    "scheduled_task": "cron",
    "skill": "skills",
    "mcp": "mcp",
    "plugin": "plugins",
}

_FIELDS = {
    "memory": "memory_projects",
    "cron": "scheduled_tasks",
    "skills": "skills",
    "mcp": "mcp_servers",
    "plugins": "plugins",
}


def validate_plan_selection(
    plan: MigrationPlan,
    selection: ImportSelection | None,
) -> None:
    """Reject blocked preview assets even when a client selects them."""
    chosen = (
        {field: set(getattr(selection, field)) for field in _FIELDS}
        if selection is not None
        else None
    )
    for action in plan.actions:
        field = PLAN_SELECTION_FIELDS.get(action.asset_type)
        if (
            action.blocked_reason
            and field
            and (chosen is None or action.source_id in chosen[field])
        ):
            raise ValueError(f"{action.name}: {action.blocked_reason}")


def _selected(values: list[Any], ids: set[str], label: str) -> list[Any]:
    available = {item.source_id for item in values}
    unknown = ids - available
    if unknown:
        raise ValueError(f"unknown {label} selection: {sorted(unknown)[0]}")
    return [item for item in values if item.source_id in ids]


def bound_mcp_plugin(server: Any) -> str:
    """Return the plugin that must be installed before this MCP can run."""
    parent = str(server.metadata.get("source_plugin") or "")
    return (
        parent
        if parent and server.metadata.get("source_plugin_relative_cwd")
        else ""
    )


def select_inventory(
    inventory: ProviderInventory,
    selection: ImportSelection,
) -> ProviderInventory:
    """Return a deep copy containing only selected assets."""
    chosen = {key: set(getattr(selection, key)) for key in _FIELDS}
    for server in inventory.mcp_servers:
        parent = bound_mcp_plugin(server)
        if (
            server.source_id in chosen["mcp"]
            and parent
            and parent not in chosen["plugins"]
        ):
            raise ValueError(
                f"plugin-owned MCP {server.source_id} requires {parent}",
            )
        if parent in chosen["plugins"]:
            chosen["mcp"].add(server.source_id)

    updates = {
        field: _selected(getattr(inventory, field), chosen[key], key)
        for key, field in _FIELDS.items()
    }
    selected_plugins = updates["plugins"]
    marketplace_refs = {item.marketplace for item in selected_plugins}
    updates["marketplaces"] = [
        item
        for item in inventory.marketplaces
        if item.source_id in marketplace_refs or item.name in marketplace_refs
    ]
    updates["sessions"] = (
        list(inventory.sessions) if selection.sessions else []
    )
    updates["ignored_session_ids"] = (
        list(inventory.ignored_session_ids) if selection.sessions else []
    )
    return inventory.model_copy(update=updates, deep=True)


__all__ = [
    "PLAN_SELECTION_FIELDS",
    "bound_mcp_plugin",
    "select_inventory",
    "validate_plan_selection",
]
