# -*- coding: utf-8 -*-
"""API routes for built-in tools management."""

from __future__ import annotations

from typing import List, Optional

from fastapi import (
    APIRouter,
    Body,
    HTTPException,
    Path,
    Request,
)
from pydantic import BaseModel, Field

from ..utils import schedule_agent_reload
from ...config import load_config

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInfo(BaseModel):
    """Tool information for API responses."""

    name: str = Field(..., description="Tool function name")
    enabled: bool = Field(..., description="Whether the tool is enabled")
    description: str = Field(default="", description="Tool description")
    async_execution: bool = Field(
        default=False,
        description="Whether to execute the tool asynchronously in background",
    )
    icon: Optional[str] = Field(default=None, description="Emoji icon for the tool")


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
                async_execution=tool_config.async_execution,
                icon=tool_config.icon,
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
    schedule_agent_reload(request, workspace.agent_id)

    # Return immediately (optimistic update)
    return ToolInfo(
        name=tool_config.name,
        enabled=tool_config.enabled,
        description=tool_config.description,
        async_execution=tool_config.async_execution,
        icon=tool_config.icon,
    )


@router.patch("/{tool_name}/async-execution", response_model=ToolInfo)
async def update_tool_async_execution(
    tool_name: str = Path(...),
    async_execution: bool = Body(..., embed=True),
    request: Request = None,
) -> ToolInfo:
    """Update tool async_execution setting for active agent.

    Args:
        tool_name: Tool function name
        async_execution: Whether to execute asynchronously
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

    # Update async_execution setting
    tool_config = agent_config.tools.builtin_tools[tool_name]
    tool_config.async_execution = async_execution

    # Save agent config
    save_agent_config(workspace.agent_id, agent_config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, workspace.agent_id)

    # Return immediately (optimistic update)
    return ToolInfo(
        name=tool_config.name,
        enabled=tool_config.enabled,
        description=tool_config.description,
        async_execution=tool_config.async_execution,
        icon=tool_config.icon,
    )
