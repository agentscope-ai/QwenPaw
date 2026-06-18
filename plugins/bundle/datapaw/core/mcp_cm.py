# -*- coding: utf-8 -*-
"""Context Manager (CM) MCP client helpers for long-running execute_sql."""
from __future__ import annotations

from typing import Any

# Wall-clock timeout for MCP tools/call (agentscope execution_timeout /
# mcp ClientSession fail_after). 40min covers 30min SQL + buffer.
CM_MCP_SSE_READ_TIMEOUT = 2400.0

CM_MCP_URL_MARKER = "/mcp/v1/cm"

CM_MCP_KNOWN_NAMES = frozenset(
    {
        "dataagent context manager",
        "context manager",
    },
)


def _url_matches_cm(url: str) -> bool:
    return CM_MCP_URL_MARKER in (url or "").lower()


def is_cm_mcp_config(client_config: Any) -> bool:
    """Return True when *client_config* points at the CM MCP endpoint."""
    url = getattr(client_config, "url", "") or ""
    if _url_matches_cm(url):
        return True
    name = (getattr(client_config, "name", "") or "").lower()
    return name in CM_MCP_KNOWN_NAMES


def is_cm_mcp_client(client: Any) -> bool:
    """Return True for a connected or configured CM HttpStatefulClient."""
    url = getattr(client, "url", "") or ""
    if _url_matches_cm(url):
        return True
    info = getattr(client, "_qwenpaw_rebuild_info", None)
    if isinstance(info, dict) and _url_matches_cm(info.get("url") or ""):
        return True
    name = (getattr(client, "name", "") or "").lower()
    return name in CM_MCP_KNOWN_NAMES


def apply_cm_mcp_long_timeouts(client: Any) -> None:
    """Raise httpx / execution timeouts on CM streamable HTTP clients."""
    from qwenpaw.app.mcp.stateful_client import HttpStatefulClient

    if not isinstance(client, HttpStatefulClient):
        return
    client.sse_read_timeout = CM_MCP_SSE_READ_TIMEOUT
    client.read_timeout_seconds = CM_MCP_SSE_READ_TIMEOUT
