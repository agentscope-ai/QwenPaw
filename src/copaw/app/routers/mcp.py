# -*- coding: utf-8 -*-
"""API routes for MCP (Model Context Protocol) clients management."""

from __future__ import annotations

from typing import Dict, List, Optional, Literal

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ..utils import schedule_agent_reload
from ...config.config import MCPClientConfig

router = APIRouter(prefix="/mcp", tags=["mcp"])


class MCPClientInfo(BaseModel):
    """MCP client information for API responses."""

    key: str = Field(..., description="Unique client key identifier")
    name: str = Field(..., description="Client display name")
    description: str = Field(default="", description="Client description")
    enabled: bool = Field(..., description="Whether the client is enabled")
    transport: Literal["stdio", "streamable_http", "sse"] = Field(
        ...,
        description="MCP transport type",
    )
    url: str = Field(
        default="",
        description="Remote MCP endpoint URL (for HTTP/SSE transports)",
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers for remote transport",
    )
    command: str = Field(
        default="",
        description="Command to launch the MCP server",
    )
    args: List[str] = Field(
        default_factory=list,
        description="Command-line arguments",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables",
    )
    cwd: str = Field(
        default="",
        description="Working directory for stdio MCP command",
    )


class MCPClientCreateRequest(BaseModel):
    """Request body for creating/updating an MCP client."""

    name: str = Field(..., description="Client display name")
    description: str = Field(default="", description="Client description")
    enabled: bool = Field(
        default=True,
        description="Whether to enable the client",
    )
    transport: Literal["stdio", "streamable_http", "sse"] = Field(
        default="stdio",
        description="MCP transport type",
    )
    url: str = Field(
        default="",
        description="Remote MCP endpoint URL (for HTTP/SSE transports)",
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers for remote transport",
    )
    command: str = Field(
        default="",
        description="Command to launch the MCP server",
    )
    args: List[str] = Field(
        default_factory=list,
        description="Command-line arguments",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables",
    )
    cwd: str = Field(
        default="",
        description="Working directory for stdio MCP command",
    )


class MCPClientUpdateRequest(BaseModel):
    """Request body for updating an MCP client (all fields optional)."""

    name: Optional[str] = Field(None, description="Client display name")
    description: Optional[str] = Field(None, description="Client description")
    enabled: Optional[bool] = Field(
        None,
        description="Whether to enable the client",
    )
    transport: Optional[Literal["stdio", "streamable_http", "sse"]] = Field(
        None,
        description="MCP transport type",
    )
    url: Optional[str] = Field(
        None,
        description="Remote MCP endpoint URL (for HTTP/SSE transports)",
    )
    headers: Optional[Dict[str, str]] = Field(
        None,
        description="HTTP headers for remote transport",
    )
    command: Optional[str] = Field(
        None,
        description="Command to launch the MCP server",
    )
    args: Optional[List[str]] = Field(
        None,
        description="Command-line arguments",
    )
    env: Optional[Dict[str, str]] = Field(
        None,
        description="Environment variables",
    )
    cwd: Optional[str] = Field(
        None,
        description="Working directory for stdio MCP command",
    )


def _restore_original_values(
    incoming: Dict[str, str],
    existing: Dict[str, str],
) -> Dict[str, str]:
    """Preserve original values when incoming matches their masked form."""
    restored: Dict[str, str] = {}
    for k, v in incoming.items():
        if k in existing and v == _mask_env_value(existing[k]):
            restored[k] = existing[k]
        else:
            restored[k] = v
    return restored


def _mask_env_value(value: str) -> str:
    """
    Mask environment variable value showing first 2-3 chars and last 4 chars.

    Examples:
        sk-proj-1234567890abcdefghij1234 -> sk-****************************1234
        abc123456789xyz -> ab***********xyz (if no dash)
        my-api-key-value -> my-************lue
        short123 -> ******** (8 chars or less, fully masked)
    """
    if not value:
        return value

    length = len(value)
    if length <= 8:
        # For short values, just mask everything
        return "*" * length

    # Show first 2-3 characters (3 if there's a dash at position 2)
    prefix_len = 3 if length > 2 and value[2] == "-" else 2
    prefix = value[:prefix_len]

    # Show last 4 characters
    suffix = value[-4:]

    # Calculate masked section length (at least 4 asterisks)
    masked_len = max(length - prefix_len - 4, 4)

    return f"{prefix}{'*' * masked_len}{suffix}"


def _build_client_info(key: str, client: MCPClientConfig) -> MCPClientInfo:
    """Build MCPClientInfo from config with masked env values."""
    # Mask environment variable values for security
    masked_env = (
        {k: _mask_env_value(v) for k, v in client.env.items()}
        if client.env
        else {}
    )
    masked_headers = (
        {k: _mask_env_value(v) for k, v in client.headers.items()}
        if client.headers
        else {}
    )

    return MCPClientInfo(
        key=key,
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=client.transport,
        url=client.url,
        headers=masked_headers,
        command=client.command,
        args=client.args,
        env=masked_env,
        cwd=client.cwd,
    )


@router.get(
    "",
    response_model=List[MCPClientInfo],
    summary="List all MCP clients",
)
async def list_mcp_clients(request: Request) -> List[MCPClientInfo]:
    """Get list of all configured MCP clients."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    mcp_config = agent.config.mcp
    if mcp_config is None or not mcp_config.clients:
        return []

    return [
        _build_client_info(key, client)
        for key, client in mcp_config.clients.items()
    ]


@router.get(
    "/{client_key}",
    response_model=MCPClientInfo,
    summary="Get MCP client details",
)
async def get_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Get details of a specific MCP client."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    mcp_config = agent.config.mcp
    if mcp_config is None:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client = mcp_config.clients.get(client_key)
    if client is None:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")
    return _build_client_info(client_key, client)


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
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config, MCPConfig

    agent = await get_agent_for_request(request)

    # Initialize mcp config if not exists
    if agent.config.mcp is None:
        agent.config.mcp = MCPConfig(clients={})

    # Check if client already exists
    if client_key in agent.config.mcp.clients:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' already exists. Use PUT to "
            f"update.",
        )

    # Create new client config
    new_client = MCPClientConfig(
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=client.transport,
        url=client.url,
        headers=client.headers,
        command=client.command,
        args=client.args,
        env=client.env,
        cwd=client.cwd,
    )

    # Add to agent's config and save
    agent.config.mcp.clients[client_key] = new_client
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return _build_client_info(client_key, new_client)


@router.put(
    "/{client_key}",
    response_model=MCPClientInfo,
    summary="Update an MCP client",
)
async def update_mcp_client(
    request: Request,
    client_key: str = Path(...),
    updates: MCPClientUpdateRequest = Body(...),
) -> MCPClientInfo:
    """Update an existing MCP client configuration."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    existing = agent.config.mcp.clients[client_key]

    # Update fields if provided
    update_data = updates.model_dump(exclude_unset=True)

    # Restore masked env/header values to originals before replacing
    if "env" in update_data and update_data["env"] is not None:
        update_data["env"] = _restore_original_values(
            update_data["env"],
            existing.env or {},
        )

    if "headers" in update_data and update_data["headers"] is not None:
        update_data["headers"] = _restore_original_values(
            update_data["headers"],
            existing.headers or {},
        )

    merged_data = existing.model_dump(mode="json")
    merged_data.update(update_data)
    updated_client = MCPClientConfig.model_validate(merged_data)
    agent.config.mcp.clients[client_key] = updated_client

    # Save updated config
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return _build_client_info(client_key, updated_client)


@router.patch(
    "/{client_key}/toggle",
    response_model=MCPClientInfo,
    summary="Toggle MCP client enabled status",
)
async def toggle_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Toggle the enabled status of an MCP client."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client = agent.config.mcp.clients[client_key]

    # Toggle enabled status
    client.enabled = not client.enabled
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return _build_client_info(client_key, client)


@router.delete(
    "/{client_key}",
    response_model=Dict[str, str],
    summary="Delete an MCP client",
)
async def delete_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> Dict[str, str]:
    """Delete an MCP client configuration."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    # Remove client
    del agent.config.mcp.clients[client_key]
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return {"message": f"MCP client '{client_key}' deleted successfully"}
