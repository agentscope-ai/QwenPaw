# -*- coding: utf-8 -*-
"""Validation helpers for MCP client identifier keys."""

from __future__ import annotations

import re

MCP_CLIENT_KEY_MAX_LEN = 100
MCP_CLIENT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

_RESERVED_KEY_PREFIXES = ("tools/", "toggle/", "oauth/", "reconnect/")


def validate_mcp_client_key(client_key: str) -> str | None:
    """Return an error message when *client_key* is invalid, else ``None``."""
    key = (client_key or "").strip()
    if not key:
        return "MCP client key must not be empty."
    if len(key) > MCP_CLIENT_KEY_MAX_LEN:
        return (
            f"MCP client key must be at most {MCP_CLIENT_KEY_MAX_LEN} characters."
        )
    if not MCP_CLIENT_KEY_PATTERN.fullmatch(key):
        return (
            "MCP client key may only contain letters, digits, hyphens, "
            "and underscores."
        )
    lower = key.lower()
    for prefix in _RESERVED_KEY_PREFIXES:
        bare = prefix.rstrip("/")
        if lower == bare or lower.startswith(prefix):
            return (
                f"MCP client key must not start with reserved prefix "
                f"'{prefix}'. Please choose a different key."
            )
    return None
