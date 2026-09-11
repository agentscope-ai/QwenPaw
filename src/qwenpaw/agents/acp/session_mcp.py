# -*- coding: utf-8 -*-
"""ACP session MCP normalization for QwenPaw transient Drivers."""

from __future__ import annotations

import hashlib
from typing import Any, TypeAlias

from acp.schema import HttpMcpServer, McpServerStdio, SseMcpServer

from ...drivers.constants import POLICY_EFFECT_ASK, PROTOCOL_MCP
from ...drivers.contracts import DriverCard
from ...drivers.policy_types import DriverPolicy

ACP_MCP_SCOPE_PREFIX = "acp-session:"

ACP_MCP_SERVER_TYPES: TypeAlias = HttpMcpServer | SseMcpServer | McpServerStdio


def acp_mcp_scope_id(session_id: str) -> str:
    """Return the transient Driver scope for one ACP session."""
    if not session_id.strip():
        raise ValueError("ACP session id must be non-empty")
    return f"{ACP_MCP_SCOPE_PREFIX}{session_id}"


def build_acp_mcp_driver_cards(
    session_id: str,
    mcp_servers: list[ACP_MCP_SERVER_TYPES] | None,
    *,
    session_cwd: str,
) -> list[DriverCard]:
    """Convert ACP MCP records into non-persistent QwenPaw DriverCards."""
    cards: list[DriverCard] = []
    seen_names: set[str] = set()
    for server in mcp_servers or []:
        name = _required_text(server, "name")
        if name in seen_names:
            raise ValueError(
                f"Duplicate ACP MCP server name in session: {name}",
            )
        seen_names.add(name)

        if isinstance(server, McpServerStdio):
            endpoint = {
                "transport": "stdio",
                "command": _required_text(server, "command"),
                "args": [str(item) for item in server.args],
                "cwd": _required_session_cwd(session_cwd),
                "env": _named_values(
                    server.env,
                    label="environment",
                    case_insensitive=True,
                ),
            }
        elif isinstance(server, SseMcpServer):
            endpoint = {
                "transport": "sse",
                "url": _required_text(server, "url"),
                "headers": _named_values(
                    server.headers,
                    label="HTTP header",
                    case_insensitive=True,
                ),
            }
        elif isinstance(server, HttpMcpServer):
            endpoint = {
                "transport": "streamable_http",
                "url": _required_text(server, "url"),
                "headers": _named_values(
                    server.headers,
                    label="HTTP header",
                    case_insensitive=True,
                ),
            }
        else:
            raise TypeError(
                f"Unsupported ACP MCP server type: "
                f"{type(server).__name__}",
            )

        cards.append(
            DriverCard(
                name=_transient_driver_name(session_id, name),
                protocol=PROTOCOL_MCP,
                endpoint=endpoint,
                config={
                    "display_name": name,
                    "description": "MCP server supplied by the ACP client.",
                    "acp_server_name": name,
                    "transient": True,
                },
                policy=DriverPolicy(default_effect=POLICY_EFFECT_ASK),
            ),
        )
    return cards


def _transient_driver_name(session_id: str, server_name: str) -> str:
    raw = f"{session_id}\0{server_name}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"acp_{digest}"


def _required_text(value: Any, field_name: str) -> str:
    if isinstance(value, dict):
        raw = value.get(field_name)
    else:
        raw = getattr(value, field_name, None)
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"ACP MCP server {field_name} must be non-empty")
    return text


def _named_values(
    values: list[Any],
    *,
    label: str,
    case_insensitive: bool = False,
) -> dict[str, str]:
    result: dict[str, str] = {}
    seen: set[str] = set()
    for item in values:
        name = _required_text(item, "name")
        compare_name = name.casefold() if case_insensitive else name
        if compare_name in seen:
            raise ValueError(f"Duplicate ACP MCP {label}: {name}")
        seen.add(compare_name)
        if isinstance(item, dict):
            raw_value = item.get("value")
        else:
            raw_value = getattr(item, "value", None)
        if raw_value is None:
            raise ValueError(f"ACP MCP {label} '{name}' has no value")
        result[name] = str(raw_value)
    return result


def _required_session_cwd(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ACP session cwd must be non-empty")
    return value


__all__ = [
    "ACP_MCP_SCOPE_PREFIX",
    "ACP_MCP_SERVER_TYPES",
    "acp_mcp_scope_id",
    "build_acp_mcp_driver_cards",
]
