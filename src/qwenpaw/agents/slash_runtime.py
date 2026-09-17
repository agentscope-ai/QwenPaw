# -*- coding: utf-8 -*-
"""Slash invocation parsing and prompt rendering."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

SlashKind = Literal["tool", "mcp_client", "mcp_tool"]


@dataclass(frozen=True)
class SlashRoute:
    """Resolved slash route for explicit tool or MCP selection."""

    kind: SlashKind
    args: str
    tool_name: str = ""
    client_key: str = ""
    mcp_tool_name: str = ""
    error: str = ""


def _split_slash(query: str | None) -> tuple[str, str] | None:
    text = str(query or "").strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split(None, 1)
    if not parts:
        return None
    command = parts[0].strip().lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return (command, args) if command else None


def _split_name_args(args: str) -> tuple[str, str]:
    parts = str(args or "").strip().split(None, 1)
    if not parts:
        return "", ""
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


def _enabled_builtin_tools(agent_config: Any) -> set[str]:
    tools_cfg = getattr(agent_config, "tools", None)
    builtin = getattr(tools_cfg, "builtin_tools", None) or {}
    return {
        name
        for name, tool in builtin.items()
        if getattr(tool, "enabled", True)
    }


def _enabled_mcp_clients(agent_config: Any) -> set[str]:
    mcp_cfg = getattr(agent_config, "mcp", None)
    clients = getattr(mcp_cfg, "clients", None) or {}
    return {
        key
        for key, client in clients.items()
        if getattr(client, "enabled", True)
    }


def resolve_slash_route(
    query: str | None,
    agent_config: Any,
) -> SlashRoute | None:
    """Resolve explicit `/tool` and `/mcp` invocations."""
    split = _split_slash(query)
    if split is None:
        return None
    command, rest = split

    if command == "tool":
        tool_name, args = _split_name_args(rest)
        if not tool_name:
            return SlashRoute(
                kind="tool",
                args="",
                error="请在 `/tool` 后指定工具名，例如 `/tool get_current_time 当前时间`。",
            )
        if tool_name not in _enabled_builtin_tools(agent_config):
            return SlashRoute(
                kind="tool",
                tool_name=tool_name,
                args=args,
                error=f"工具 `{tool_name}` 未启用或不存在。",
            )
        return SlashRoute(kind="tool", tool_name=tool_name, args=args)

    if command == "mcp":
        target, args = _split_name_args(rest)
        if not target:
            return SlashRoute(
                kind="mcp_client",
                args="",
                error=(
                    "请在 `/mcp` 后指定 MCP client 或 tool，例如 "
                    "`/mcp tavily.search 搜索内容`。"
                ),
            )

        enabled_clients = _enabled_mcp_clients(agent_config)
        if "." in target:
            client_key, tool_name = target.split(".", 1)
            if client_key not in enabled_clients:
                return SlashRoute(
                    kind="mcp_tool",
                    client_key=client_key,
                    mcp_tool_name=tool_name,
                    args=args,
                    error=f"MCP client `{client_key}` 未启用或不存在。",
                )
            if not tool_name:
                return SlashRoute(
                    kind="mcp_tool",
                    client_key=client_key,
                    args=args,
                    error="请指定 MCP tool 名称。",
                )
            return SlashRoute(
                kind="mcp_tool",
                client_key=client_key,
                mcp_tool_name=tool_name,
                args=args,
            )

        if target not in enabled_clients:
            return SlashRoute(
                kind="mcp_client",
                client_key=target,
                args=args,
                error=f"MCP client `{target}` 未启用或不存在。",
            )
        return SlashRoute(kind="mcp_client", client_key=target, args=args)

    return None


def route_to_prompt(route: SlashRoute) -> str:
    """Render route instructions for the agent turn."""
    if route.error:
        return ""
    payload = {
        "kind": route.kind,
        "tool_name": route.tool_name,
        "client_key": route.client_key,
        "mcp_tool_name": route.mcp_tool_name,
        "args": route.args,
    }
    if route.kind == "tool":
        instruction = (
            f"The user explicitly selected built-in tool `{route.tool_name}`. "
            "Before answering, call that tool if it can satisfy the task. "
            "Use the user's remaining text as the tool/task context."
        )
    elif route.kind == "mcp_tool":
        instruction = (
            "The user explicitly selected an MCP tool: "
            f"`{route.client_key}.{route.mcp_tool_name}`. "
            "Use the matching MCP tool registered from that client before "
            "answering. If the tool is unavailable, explain that clearly."
        )
    else:
        instruction = (
            f"The user explicitly selected MCP client `{route.client_key}`. "
            "Prefer tools from that client for this request. If no matching "
            "tool is available, explain that clearly."
        )
    return (
        "[Slash routing]\n"
        f"{instruction}\n"
        f"Routing metadata: {json.dumps(payload, ensure_ascii=False)}\n"
        "---\n"
    )
