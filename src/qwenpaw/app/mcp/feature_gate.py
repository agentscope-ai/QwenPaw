# -*- coding: utf-8 -*-
"""Host-only Mail/ACP admission using the current MCP runtime generation."""

# pylint: disable=protected-access

import logging

from ...plugins.errors import SDKError
from ...plugins.registry import PluginRegistry

PLUGIN_ID = "qwenpaw-mcp"
OFFICIAL_PLUGIN_PATH = "/market?tab=plugins&view=official"
logger = logging.getLogger(__name__)


class MCPUnavailableError(RuntimeError):
    """A recoverable feature failure; configuration and cleanup remain usable."""

    code = "mcp_plugin_unavailable"

    def __init__(self):
        super().__init__(
            "Mail and ACP require an available MCP plugin. "
            "Install, enable or repair MCP in QwenPaw's official plugins page: "
            + OFFICIAL_PLUGIN_PATH,
        )


def is_mcp_ready(loader=None, workspace_id=None) -> bool:
    """Read existing admission evidence, without I/O or dependency checks."""
    registry = loader.registry if loader is not None else PluginRegistry()
    descriptor = registry._driver_protocols.get("mcp")
    if descriptor is None or descriptor.owner.plugin_id != PLUGIN_ID:
        return False
    if loader is None:
        loader = descriptor.plugin._loader
    record = loader.get_loaded_plugin(PLUGIN_ID)
    if (
        record is None
        or not record.enabled
        or record.status != "active"
        or PLUGIN_ID in loader.startup_blocked_plugins
    ):
        return False
    try:
        descriptor.guard()
    except SDKError:
        return False
    eligibility = registry.protocol_eligibility
    if workspace_id is not None:
        manager = registry.get_workspace_manager()
        live = getattr(manager, "agents", getattr(manager, "workspaces", {}))
        workspace = live.get(workspace_id) or registry._stop_workspaces.get(
            workspace_id,
        )
        service = getattr(workspace, "driver_manager", None)
        if "mcp" in getattr(service, "_inactive", ()):
            return False
    return not (
        workspace_id is not None
        and eligibility is not None
        and not eligibility(workspace_id, "mcp")
    )


def require_mcp_ready(workspace_id=None, *, loader=None) -> None:
    """Admit new work only. Never use this on cancel/close/stop paths."""
    if not is_mcp_ready(loader, workspace_id):
        raise MCPUnavailableError()


async def prepare_mcp_for_use(loader=None, workspace_id=None) -> bool:
    """Try the existing local installer on an explicit feature-use trigger."""
    if is_mcp_ready(loader, workspace_id):
        return True
    from ..mcp_plugin_upgrade import get_coordinator

    if loader is None:
        resolver = PluginRegistry().protocol_resolver
        loader = getattr(getattr(resolver, "__self__", None), "loader", None)
    if loader is None:
        return False
    record = loader.get_loaded_plugin(PLUGIN_ID)
    if record is not None and record.status == "failed":
        return False
    coordinator = get_coordinator(loader)
    previous = coordinator.latest_result
    if previous is not None and previous.status in {"failed", "needs_review"}:
        return False
    try:
        await coordinator.ensure_protocol("mcp")
    except Exception:
        # Do not turn a saved feature into a failed config write.
        logger.warning("Local MCP preparation failed; use official plugins")
        return False
    return is_mcp_ready(loader, workspace_id)


async def prepare_mcp_for_request(request, workspace_id) -> bool:
    """Prepare after a committed feature edit, without changing its response."""
    state = getattr(getattr(request, "app", None), "state", None)
    loader = getattr(state, "plugin_loader", None)
    if loader is None:
        return False
    return await prepare_mcp_for_use(loader, workspace_id)


async def reconcile_mcp_features(loader, plugin_id: str) -> None:
    """Resume enabled host services after an explicit plugin commit.

    Protocol projection happens before activation commits, when background
    Mail work must still be denied. Host install/enable/config endpoints call
    this only after the existing lifecycle transaction has finished.
    """
    if plugin_id != PLUGIN_ID or not is_mcp_ready(loader):
        return
    from ..mcp_plugin_upgrade import get_coordinator

    try:
        await get_coordinator(loader)._reconcile_live_workspaces()
    except Exception:
        logger.warning("MCP is active but workspace service recovery failed")
