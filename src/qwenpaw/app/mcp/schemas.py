# -*- coding: utf-8 -*-
"""Pydantic schemas for MCP Console APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MCPClientOAuthStatus(BaseModel):
    """Summarised OAuth status returned in client info."""

    authorized: bool = False
    expires_at: float = 0.0
    scope: str = ""
    client_id: str = ""


class MCPAccessSummary(BaseModel):
    """Small access policy summary for MCP client cards."""

    default_effect: Literal["allow", "ask", "deny"] = "deny"
    overrides_count: int = 0


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
    tools: Optional[List[str]] = Field(
        default=None,
        description="Tool whitelist. Only listed tools will be loaded. "
        "None means load all tools.",
    )
    oauth_status: Optional[MCPClientOAuthStatus] = Field(
        default=None,
        description="OAuth token status (None if OAuth not configured)",
    )
    access_summary: MCPAccessSummary = Field(
        default_factory=MCPAccessSummary,
        description="Summarised MCP access policy",
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
    tools: Optional[List[str]] = Field(
        default=None,
        description="Tool whitelist. Only listed tools will be loaded. "
        "None means load all tools.",
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
    tools: Optional[List[str]] = Field(
        None,
        description="Tool whitelist (omit to leave unchanged). "
        "Set to null to remove the whitelist.",
    )


class MCPAccessRule(BaseModel):
    """Console-managed access rule for one MCP source/object tuple."""

    source_type: Literal["channel"] = Field(
        default="channel",
        description="Where the tool call comes from",
    )
    source_value: str = Field(
        default="console",
        description="Concrete source, e.g. console, dingtalk",
    )
    subject_type: Literal["all", "user"] = Field(
        default="all",
        description="Object scope within the source",
    )
    subject_value: str = Field(
        default="",
        description="Concrete object value when subject_type is user",
    )
    effect: Literal["allow", "ask", "deny"] = Field(
        ...,
        description="Access effect for this source/object tuple",
    )


class MCPAccessPrincipalOption(BaseModel):
    """Selectable source-scoped principal discovered from recent chats."""

    source_type: Literal["channel"] = Field(
        default="channel",
        description="Where the tool call comes from",
    )
    source_value: str = Field(
        ...,
        description="Concrete source, e.g. console, dingtalk",
    )
    subject_type: Literal["user"] = Field(
        default="user",
        description="Selectable object type",
    )
    subject_value: str = Field(
        ...,
        description="User identifier within the selected source",
    )
    label: str = Field(default="", description="Display label")
    chat_id: str = Field(default="", description="Recent chat UUID")
    chat_name: str = Field(default="", description="Recent chat name")
    session_id: str = Field(default="", description="Recent session ID")
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Most recent chat update timestamp",
    )


class MCPToolDefaultPolicy(BaseModel):
    """Console-managed default policy for one MCP tool."""

    tool_name: str = Field(..., description="MCP tool name")
    effect: Literal["allow", "ask", "deny"] = Field(
        ...,
        description="Default effect for this tool",
    )


class MCPToolAccessOverride(MCPAccessRule):
    """Console-managed access override for one MCP source/object/tool tuple."""

    tool_name: str = Field(..., description="MCP tool name")


class MCPAccessPolicy(BaseModel):
    """Console-friendly MCP access policy payload."""

    default_effect: Literal["allow", "ask", "deny"] = Field(
        default="deny",
        description="Default effect when no MCP rule matches",
    )
    client_overrides: List[MCPAccessRule] = Field(
        default_factory=list,
        description="Console-managed MCP-wide source/object overrides",
    )
    tool_defaults: List[MCPToolDefaultPolicy] = Field(
        default_factory=list,
        description="Console-managed default effects for individual tools",
    )
    tool_overrides: List[MCPToolAccessOverride] = Field(
        default_factory=list,
        description="Console-managed per-source/per-object/per-tool overrides",
    )
    unmanaged_rules_count: int = Field(
        default=0,
        description="Rules preserved but not editable by the console",
    )


class MCPToolInfo(BaseModel):
    """MCP tool information returned from a connected server."""

    name: str = Field(..., description="Tool name")
    description: str = Field(default="", description="Tool description")
    enabled: bool = Field(
        default=True,
        description="Whether this tool is enabled (passes the whitelist)",
    )
    input_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for the tool's input parameters",
    )
