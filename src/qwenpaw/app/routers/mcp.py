# -*- coding: utf-8 -*-
"""API routes for MCP (Model Context Protocol) clients management."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Path, Request
from pydantic import BaseModel, Field

from ..mcp.config_service import (
    MCPConfigService,
    ensure_mcp_display_name_unique,
    ensure_mcp_driver_active,
)
from ..mcp.schemas import (
    MCPAccessPolicy,
    MCPAccessRule,
    MCPClientCreateRequest,
    MCPClientInfo,
    MCPClientUpdateRequest,
    MCPToolAccessOverride,
    MCPToolDefaultPolicy,
    MCPToolInfo,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])

__all__ = [
    "MCPAccessPolicy",
    "MCPAccessRule",
    "MCPClientCreateRequest",
    "MCPClientInfo",
    "MCPClientUpdateRequest",
    "MCPToolAccessOverride",
    "MCPToolDefaultPolicy",
    "MCPToolInfo",
    "router",
]


def _mcp_service(agent: Any) -> MCPConfigService:
    return MCPConfigService(agent)


async def _agent_for_request(request: Request) -> Any:
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def _ensure_mcp_driver_active(manager: Any, client_key: str) -> None:
    """Compatibility wrapper for existing tests."""
    await ensure_mcp_driver_active(manager, client_key)


async def _ensure_mcp_display_name_unique(
    agent: Any,
    display_name: str,
    *,
    client_key: str,
) -> None:
    """Compatibility wrapper for existing tests."""
    await ensure_mcp_display_name_unique(
        _mcp_service(agent),
        display_name,
        client_key=client_key,
    )


@router.get(
    "/tools/{client_key:path}",
    response_model=List[MCPToolInfo],
    summary="List tools from a connected MCP server",
)
async def list_mcp_tools(
    request: Request,
    client_key: str = Path(...),
) -> List[MCPToolInfo]:
    """Query a running MCP server for its available tools."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).list_tools(client_key)


class MCPToolWhitelistRequest(BaseModel):
    """Request body for updating tool whitelist."""

    tools: Optional[List[str]] = Field(
        default=None,
        description="List of tool names to enable. "
        "None means enable all tools (remove whitelist).",
    )


@router.put(
    "/tools/{client_key:path}",
    response_model=List[MCPToolInfo],
    summary="Update tool whitelist for an MCP client",
)
async def update_mcp_tool_whitelist(
    request: Request,
    client_key: str = Path(...),
    body: MCPToolWhitelistRequest = Body(...),
) -> List[MCPToolInfo]:
    """Update which tools are enabled for an MCP client.

    Pass a list of tool names to enable only those tools, or null to remove
    the whitelist and enable all tools. Returns the full tool list with
    enabled status.
    """
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).update_tool_whitelist(
        client_key,
        body.tools,
    )


@router.get(
    "/policy/{client_key:path}",
    response_model=MCPAccessPolicy,
    summary="Get saved MCP access policy",
)
async def get_mcp_policy(
    request: Request,
    client_key: str = Path(...),
) -> MCPAccessPolicy:
    """Return saved MCP access policy without querying the MCP server."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).get_policy(client_key)


@router.put(
    "/policy/{client_key:path}",
    response_model=MCPAccessPolicy,
    summary="Update saved MCP access policy",
)
async def update_mcp_policy(
    request: Request,
    client_key: str = Path(...),
    access: MCPAccessPolicy = Body(...),
) -> MCPAccessPolicy:
    """Update console-managed MCP policy without querying the MCP server."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).update_policy(client_key, access)


@router.get(
    "",
    response_model=List[MCPClientInfo],
    summary="List all MCP clients",
)
async def list_mcp_clients(request: Request) -> List[MCPClientInfo]:
    """Get list of all configured MCP clients."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).list_clients()


@router.post(
    "",
    response_model=MCPClientInfo,
    summary="Create a new MCP client",
    status_code=201,
)
async def create_mcp_client(
    request: Request,
    client_key: str = Body(..., embed=True),
    client: MCPClientCreateRequest = Body(..., embed=True),
) -> MCPClientInfo:
    """Create a new MCP client configuration."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).create_client(client_key, client)


@router.patch(
    "/toggle/{client_key:path}",
    response_model=MCPClientInfo,
    summary="Toggle MCP client enabled status",
)
async def toggle_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Toggle the enabled status of an MCP client."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).toggle_client(client_key)


# ---------------------------------------------------------------------------
# Catch-all routes using {client_key:path} — MUST be registered last
# because :path greedily matches any remaining path segments including '/'.
# ---------------------------------------------------------------------------


@router.get(
    "/{client_key:path}",
    response_model=MCPClientInfo,
    summary="Get MCP client details",
)
async def get_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Get details of a specific MCP client."""
    agent = await _agent_for_request(request)
    service = _mcp_service(agent)
    card = await service.load_card(client_key)
    return await service.build_info_from_card(card)


@router.put(
    "/{client_key:path}",
    response_model=MCPClientInfo,
    summary="Update an MCP client",
)
async def update_mcp_client(
    request: Request,
    client_key: str = Path(...),
    updates: MCPClientUpdateRequest = Body(...),
) -> MCPClientInfo:
    """Update an existing MCP client configuration."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).update_client(client_key, updates)


@router.delete(
    "/{client_key:path}",
    response_model=Dict[str, str],
    summary="Delete an MCP client",
)
async def delete_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> Dict[str, str]:
    """Delete an MCP client configuration."""
    agent = await _agent_for_request(request)
    return await _mcp_service(agent).delete_client(client_key)
