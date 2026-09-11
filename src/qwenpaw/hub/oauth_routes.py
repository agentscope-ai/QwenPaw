# -*- coding: utf-8 -*-
"""Stable OAuth route mapping for managed Hub runtimes."""

from __future__ import annotations

import re

_PROVIDER_OAUTH_START = re.compile(
    r"^providers/(?P<provider_id>[A-Za-z0-9_.-]+)/oauth/start$",
)
_MCP_OAUTH_START = re.compile(
    r"^(?:agents/[^/]+/)?mcp/oauth/start/[^/].*$",
)


def oauth_callback_route(method: str, path: str) -> str | None:
    """Map a managed OAuth start request to its stable Hub route."""
    if method != "POST":
        return None
    provider_match = _PROVIDER_OAUTH_START.fullmatch(path)
    if provider_match:
        provider_id = provider_match.group("provider_id")
        return f"providers/{provider_id}"
    if _MCP_OAUTH_START.fullmatch(path):
        return "mcp"
    return None


def runtime_oauth_callback_path(callback_route: str) -> str | None:
    """Resolve an allowlisted Hub callback route inside one runtime."""
    if callback_route == "mcp":
        return "/api/mcp/oauth/callback"
    provider_prefix = "providers/"
    if callback_route.startswith(provider_prefix):
        provider_id = callback_route[len(provider_prefix) :]
        if re.fullmatch(r"[A-Za-z0-9_.-]+", provider_id):
            return f"/api/providers/{provider_id}/oauth/callback"
    return None
