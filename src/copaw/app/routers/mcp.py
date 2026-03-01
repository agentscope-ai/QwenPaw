# -*- coding: utf-8 -*-
"""API routes for MCP (Model Context Protocol) clients management."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Literal

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

from ...config import load_config, save_config
from ...config.config import MCPClientConfig

router = APIRouter(prefix="/mcp", tags=["mcp"])
_INVALID_COMMAND_CHARS_RE = re.compile(r"[\x00\r\n]")


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
    baseUrl: Optional[str] = Field(
        default=None,
        description="Legacy alias of url for backward compatibility",
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
    baseUrl: Optional[str] = Field(
        None,
        description="Legacy alias of url for backward compatibility",
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

def _validate_command_input(command: str) -> str:
    """Reject command strings with control characters."""
    sanitized = (command or "").strip()
    if sanitized and _INVALID_COMMAND_CHARS_RE.search(sanitized):
        raise HTTPException(
            status_code=400,
            detail="MCP client command contains invalid control characters.",
        )
    return sanitized

def _normalize_legacy_url(url: Optional[str], base_url: Optional[str]) -> str:
    """Normalize URL aliases from older payload formats."""
    return (url or base_url or "").strip()


def _coerce_transport_for_legacy_payload(
    transport: Literal["stdio", "streamable_http", "sse"],
    url: str,
    command: str,
    transport_explicit: bool,
) -> Literal["stdio", "streamable_http", "sse"]:
    """Auto-switch to HTTP transport for URL-only legacy payloads."""
    if transport_explicit:
        return transport
    if transport == "stdio" and url and not command.strip():
        return "streamable_http"
    return transport


@router.get(
    "",
    response_model=List[MCPClientInfo],
    summary="List all MCP clients",
)
async def list_mcp_clients() -> List[MCPClientInfo]:
    """Get list of all configured MCP clients."""
    config = load_config()
    return [
        _build_client_info(key, client)
        for key, client in config.mcp.clients.items()
    ]


@router.get(
    "/{client_key}",
    response_model=MCPClientInfo,
    summary="Get MCP client details",
)
async def get_mcp_client(client_key: str = Path(...)) -> MCPClientInfo:
    """Get details of a specific MCP client."""
    config = load_config()
    client = config.mcp.clients.get(client_key)
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
    client_key: str = Body(..., embed=True),
    client: MCPClientCreateRequest = Body(..., embed=True),
) -> MCPClientInfo:
    """Create a new MCP client configuration."""
    config = load_config()

    # Check if client already exists
    if client_key in config.mcp.clients:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' already exists. Use PUT to "
            f"update.",
        )

    # Create new client config
    transport_explicit = "transport" in client.model_fields_set
    normalized_url = _normalize_legacy_url(client.url, client.baseUrl)
    normalized_command = _validate_command_input(client.command)
    normalized_transport = _coerce_transport_for_legacy_payload(
        client.transport,
        normalized_url,
        normalized_command,
        transport_explicit,
    )
    new_client = MCPClientConfig(
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=normalized_transport,
        url=normalized_url,
        headers=client.headers,
        command=normalized_command,
        args=client.args,
        env=client.env,
        cwd=client.cwd,
    )

    # Add to config and save
    config.mcp.clients[client_key] = new_client
    save_config(config)

    return _build_client_info(client_key, new_client)


@router.put(
    "/{client_key}",
    response_model=MCPClientInfo,
    summary="Update an MCP client",
)
async def update_mcp_client(
    client_key: str = Path(...),
    updates: MCPClientUpdateRequest = Body(...),
) -> MCPClientInfo:
    """Update an existing MCP client configuration."""
    config = load_config()

    # Check if client exists
    existing = config.mcp.clients.get(client_key)
    if existing is None:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    # Update fields if provided
    update_data = updates.model_dump(exclude_unset=True)
    if "baseUrl" in update_data and not update_data.get("url"):
        update_data["url"] = update_data["baseUrl"]
    update_data.pop("baseUrl", None)

    if "url" in update_data:
        incoming_transport = update_data.get("transport", existing.transport)
        transport_explicit = "transport" in update_data
        incoming_command = update_data.get("command", existing.command) or ""
        incoming_url = (update_data.get("url") or "").strip()
        update_data["transport"] = _coerce_transport_for_legacy_payload(
            incoming_transport,
            incoming_url,
            incoming_command,
            transport_explicit,
        )
    if "command" in update_data and update_data["command"] is not None:
        update_data["command"] = _validate_command_input(update_data["command"])

    # Special handling for env: merge with existing, don't replace
    if "env" in update_data and update_data["env"] is not None:
        updated_env = existing.env.copy() if existing.env else {}
        updated_env.update(update_data["env"])
        update_data["env"] = updated_env

    merged_data = existing.model_dump(mode="json")
    merged_data.update(update_data)
    updated_client = MCPClientConfig.model_validate(merged_data)
    config.mcp.clients[client_key] = updated_client

    # Save updated config
    save_config(config)

    return _build_client_info(client_key, updated_client)


@router.patch(
    "/{client_key}/toggle",
    response_model=MCPClientInfo,
    summary="Toggle MCP client enabled status",
)
async def toggle_mcp_client(
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Toggle the enabled status of an MCP client."""
    config = load_config()

    client = config.mcp.clients.get(client_key)
    if client is None:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    # Toggle enabled status
    client.enabled = not client.enabled
    save_config(config)

    return _build_client_info(client_key, client)


@router.delete(
    "/{client_key}",
    response_model=Dict[str, str],
    summary="Delete an MCP client",
)
async def delete_mcp_client(
    client_key: str = Path(...),
) -> Dict[str, str]:
    """Delete an MCP client configuration."""
    config = load_config()

    if client_key not in config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    # Remove client
    del config.mcp.clients[client_key]
    save_config(config)

    return {"message": f"MCP client '{client_key}' deleted successfully"}
