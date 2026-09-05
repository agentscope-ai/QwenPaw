# -*- coding: utf-8 -*-
"""Shared MCP tool-call timeout parsing."""

from __future__ import annotations

import math
from typing import Annotated, Any

import httpx
from mcp.shared.exceptions import McpError
from pydantic import BeforeValidator, Field
from pydantic.fields import FieldInfo

DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS: float = 60 * 5
MAX_MCP_TOOL_CALL_TIMEOUT_SECONDS: float = 24 * 60 * 60
MCP_REQUEST_TIMEOUT_CODE = 408
MCP_TOOL_CALL_TIMEOUT_FIELD = "tool_call_timeout"
MCP_TOOL_CALL_TIMEOUT_DESCRIPTION = (
    "Maximum duration of one MCP tools/call request in seconds. For HTTP "
    "transports, the SSE read budget is raised to at least this value; HTTP "
    "connect, write, and pool timeouts are unchanged."
)


def _reject_boolean_timeout(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("must be a positive number")
    return value


MCPToolCallTimeout = Annotated[
    float,
    BeforeValidator(_reject_boolean_timeout),
]


def is_mcp_request_timeout(
    exc: BaseException,
    *,
    json_rpc_error_type: type[BaseException] | None = None,
) -> bool:
    """Return whether an exception tree represents an MCP request timeout."""
    if isinstance(exc, httpx.ReadTimeout):
        return True
    if isinstance(exc, McpError):
        error = getattr(exc, "error", None)
        if getattr(error, "code", None) == MCP_REQUEST_TIMEOUT_CODE:
            return True
    if (
        json_rpc_error_type is not None
        and isinstance(exc, json_rpc_error_type)
        and getattr(exc, "code", None) == MCP_REQUEST_TIMEOUT_CODE
    ):
        return True
    sub_excs = getattr(exc, "exceptions", None)
    return bool(sub_excs) and all(
        is_mcp_request_timeout(
            item,
            json_rpc_error_type=json_rpc_error_type,
        )
        for item in sub_excs
    )


def mcp_tool_call_timeout_field(default: Any) -> FieldInfo:
    """Build the shared Pydantic field for MCP tool-call deadlines."""
    return Field(
        default=default,
        gt=0,
        le=MAX_MCP_TOOL_CALL_TIMEOUT_SECONDS,
        allow_inf_nan=False,
        description=MCP_TOOL_CALL_TIMEOUT_DESCRIPTION,
    )


def get_mcp_tool_call_timeout(endpoint: dict[str, Any]) -> float:
    """Return a validated tool-call timeout from an MCP endpoint."""
    if MCP_TOOL_CALL_TIMEOUT_FIELD in endpoint:
        return parse_mcp_tool_call_timeout(
            endpoint[MCP_TOOL_CALL_TIMEOUT_FIELD],
        )
    return DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS


def parse_mcp_tool_call_timeout(value: Any) -> float:
    """Parse a configured MCP tool-call timeout in seconds."""
    if value is None:
        raise ValueError("must be provided when present")
    _reject_boolean_timeout(value)
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("must be a positive number")
        raw_value = value.strip()
    else:
        raw_value = value
    try:
        timeout = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("must be a positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("must be a positive number")
    if timeout > MAX_MCP_TOOL_CALL_TIMEOUT_SECONDS:
        raise ValueError(
            "must be less than or equal to "
            f"{MAX_MCP_TOOL_CALL_TIMEOUT_SECONDS:g}",
        )
    return timeout
