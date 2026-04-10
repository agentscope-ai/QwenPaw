# -*- coding: utf-8 -*-
"""Agent discovery tool for listing configured agents."""

import json
from typing import Optional

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...app.services.agent_communicate import fetch_agents_async, filter_agents
from ...config.utils import read_last_api


DEFAULT_AGENT_LIST_BASE_URL = "http://127.0.0.1:8088"


def _tool_response(text: str) -> ToolResponse:
    """Wrap text into a standard tool response."""
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _resolve_base_url(base_url: Optional[str]) -> str:
    """Resolve the API base URL for agent discovery tool calls."""
    if base_url:
        return base_url.rstrip("/")

    last_api = read_last_api()
    if last_api is not None:
        host, port = last_api
        return f"http://{host}:{port}"

    return DEFAULT_AGENT_LIST_BASE_URL


def _format_agents(
    agents: list[dict[str, object]],
    include_workspace: bool,
) -> str:
    """Format agents into a concise human-readable list."""
    if not agents:
        return "No matching agents found."

    lines = [f"Found {len(agents)} agent(s):", ""]
    for agent in agents:
        agent_id = str(agent.get("id", "")) or "<unknown>"
        name = str(agent.get("name", "")) or "<unnamed>"
        enabled = bool(agent.get("enabled", False))
        description = str(agent.get("description", "")).strip()
        workspace_dir = str(agent.get("workspace_dir", "")).strip()

        header = f"- {agent_id} ({name})"
        if not enabled:
            header += " [disabled]"
        lines.append(header)
        if description:
            lines.append(f"  description: {description}")
        if include_workspace and workspace_dir:
            lines.append(f"  workspace_dir: {workspace_dir}")

    return "\n".join(lines)


async def list_agents(
    enabled_only: bool = True,
    include_workspace: bool = False,
    base_url: Optional[str] = None,
    json_output: bool = False,
) -> ToolResponse:
    """List available agents so the current agent can pick a valid target ID.

    Runtime agents should normally call ``list_agents()`` first, then pass the
    chosen ID into ``agent_chat(to_agent=...)``.

    Examples:
        List enabled agents:
            list_agents()

        Include disabled agents and workspace directories:
            list_agents(enabled_only=False, include_workspace=True)

    Args:
        enabled_only: Return only enabled agents by default.
        include_workspace: Include each agent's workspace directory.
        base_url: Optional API base URL, defaults to the local app endpoint.
        json_output: Return raw JSON payload instead of formatted text.

    Returns:
        ToolResponse with either formatted text or JSON.
    """
    resolved_base_url = _resolve_base_url(base_url)

    try:
        result = await fetch_agents_async(resolved_base_url, timeout=30.0)
        agents = filter_agents(result.agents, enabled_only=enabled_only)

        if json_output:
            return _tool_response(
                json.dumps({"agents": agents}, ensure_ascii=False, indent=2),
            )
        return _tool_response(_format_agents(agents, include_workspace))
    except ValueError as e:
        return _tool_response(f"Error: {e}")
    except httpx.HTTPError as e:
        return _tool_response(f"Error: failed to list agents: {e}")
