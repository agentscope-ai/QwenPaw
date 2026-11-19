# -*- coding: utf-8 -*-
"""Host-only Mail/ACP admission using the current MCP runtime generation."""

# pylint: disable=protected-access

import logging

from ...drivers.errors import driver_error_diagnostic
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


def is_mcp_ready(loader=None, workspace_id=None, *, workspace=None) -> bool:
    return (
        mcp_unavailable_reason(loader, workspace_id, workspace=workspace)
        is None
    )


def mcp_unavailable_reason(loader=None, workspace_id=None, *, workspace=None):
    """Read existing admission evidence, without I/O or dependency checks."""
    registry = loader.registry if loader is not None else PluginRegistry()
    state = registry.describe_driver_protocol("mcp", loader=loader)
    if (
        state is None
        or state.plugin_id != PLUGIN_ID
        or not state.active
        or state.blocked
    ):
        coordinator = (
            registry.get_protocol_preparation()
            if loader is None
            else getattr(loader, "protocol_coordinator", None)
        )
        if loader is None:
            loader = getattr(coordinator, "loader", None)
        record = loader.get_loaded_plugin(PLUGIN_ID) if loader else None
        if record is not None and not record.enabled:
            return "plugin_disabled"
        if record is not None and record.status == "failed":
            return "plugin_load_failed"
        result = getattr(coordinator, "latest_result", None)
        if getattr(result, "status", None) in ("failed", "needs_review") or (
            state is not None
            and state.plugin_id == PLUGIN_ID
            and state.blocked
        ):
            return "startup_recovery_required"
        return "runtime_not_ready"
    eligibility = registry.protocol_eligibility
    if workspace_id is not None:
        workspace = workspace or registry.get_driver_workspace(workspace_id)
        service = getattr(workspace, "driver_manager", None)
        suspended = getattr(service, "is_protocol_suspended", None)
        if suspended is not None and suspended("mcp"):
            return "workspace_protocol_suspended"
    if (
        workspace_id is not None
        and eligibility is not None
        and not eligibility(workspace_id, "mcp", workspace=workspace)
    ):
        return "workspace_unavailable"
    return None


def require_mcp_ready(workspace_id=None, *, loader=None) -> None:
    """Admit new work only. Never use this on cancel/close/stop paths."""
    if not is_mcp_ready(loader, workspace_id):
        raise MCPUnavailableError()


async def prepare_mcp_for_use(loader=None, workspace_id=None) -> bool:
    """Try the existing local installer on an explicit feature-use trigger."""
    if is_mcp_ready(loader, workspace_id):
        return True
    from ..mcp_plugin_upgrade import get_coordinator

    coordinator = get_coordinator(loader)
    return (
        await coordinator.prepare_for_use(workspace_id)
        if coordinator is not None
        else False
    )


async def prepare_mcp_for_request(request, workspace_id) -> bool:
    """Prepare after a committed feature edit, without changing its response."""
    state = getattr(getattr(request, "app", None), "state", None)
    loader = getattr(state, "plugin_loader", None)
    if loader is None:
        return False
    return await prepare_mcp_for_use(loader, workspace_id)


async def reconcile_mcp_features(
    loader,
    plugin_id: str,
    *,
    record=None,
) -> None:
    """Resume enabled host services after an explicit plugin commit.

    Protocol projection happens before activation commits, when background
    Mail work must still be denied. Host install/enable/config endpoints call
    this only after the existing lifecycle transaction has finished.
    """
    if plugin_id != PLUGIN_ID:
        return
    from ..mcp_plugin_upgrade import get_coordinator

    coordinator = get_coordinator(loader)
    if not await coordinator.reconcile_explicit(record):
        return
    try:
        await coordinator._reconcile_live_workspaces(refresh=True)
    except Exception as exc:
        logger.warning(
            "MCP workspace reconciliation failed: %s",
            driver_error_diagnostic(exc),
        )
