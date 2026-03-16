# -*- coding: utf-8 -*-
"""API routes for built-in tools management."""

from __future__ import annotations

from typing import List

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Request,
)
from pydantic import BaseModel, Field

from ...config import load_config

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInfo(BaseModel):
    """Tool information for API responses."""

    name: str = Field(..., description="Tool function name")
    enabled: bool = Field(..., description="Whether the tool is enabled")
    description: str = Field(default="", description="Tool description")


@router.get("", response_model=List[ToolInfo])
async def list_tools(
    request: Request,
) -> List[ToolInfo]:
    """List all built-in tools and enabled status for active agent.

    Returns:
        List of tool information
    """
    from ..agent_context import get_agent_for_request
    from ...config.config import load_agent_config

    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)

    # Ensure tools config exists with defaults
    if not agent_config.tools or not agent_config.tools.builtin_tools:
        # Fallback to global config if agent config has no tools
        config = load_config()
        tools_config = config.tools if hasattr(config, "tools") else None
        if not tools_config:
            return []
        builtin_tools = tools_config.builtin_tools
    else:
        builtin_tools = agent_config.tools.builtin_tools

    tools_list = []
    for tool_config in builtin_tools.values():
        tools_list.append(
            ToolInfo(
                name=tool_config.name,
                enabled=tool_config.enabled,
                description=tool_config.description,
            ),
        )

    return tools_list


@router.patch("/{tool_name}/toggle", response_model=ToolInfo)
async def toggle_tool(
    tool_name: str = Path(...),
    request: Request = None,
) -> ToolInfo:
    """Toggle tool enabled status for active agent.

    Args:
        tool_name: Tool function name
        request: FastAPI request

    Returns:
        Updated tool information

    Raises:
        HTTPException: If tool not found
    """
    from ..agent_context import get_agent_for_request
    from ...config.config import load_agent_config, save_agent_config

    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)

    if (
        not agent_config.tools
        or tool_name not in agent_config.tools.builtin_tools
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found",
        )

    # Toggle enabled status
    tool_config = agent_config.tools.builtin_tools[tool_name]
    tool_config.enabled = not tool_config.enabled

    # Save agent config
    save_agent_config(workspace.agent_id, agent_config)

    # Hot reload config (async, non-blocking)
    import asyncio

    async def reload_in_background():
        try:
            manager = request.app.state.multi_agent_manager
            await manager.reload_agent(workspace.agent_id)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"Background reload failed: {e}",
            )

    asyncio.create_task(reload_in_background())

    # Return immediately (optimistic update)
    return ToolInfo(
        name=tool_config.name,
        enabled=tool_config.enabled,
        description=tool_config.description,
    )
