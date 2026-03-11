# -*- coding: utf-8 -*-
"""API routes for built-in tools management."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from ...config import load_config, save_config

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInfo(BaseModel):
    """Tool information for API responses."""

    name: str = Field(..., description="Tool function name")
    enabled: bool = Field(..., description="Whether the tool is enabled")
    description: str = Field(default="", description="Tool description")


@router.get("", response_model=List[ToolInfo])
async def list_tools() -> List[ToolInfo]:
    """List all built-in tools and their enabled status.

    Returns:
        List of tool information
    """
    config = load_config()

    # Ensure tools config exists with defaults
    if not hasattr(config, "tools"):
        config.tools = {}

    tools_list = []
    for tool_config in config.tools.builtin_tools.values():
        tools_list.append(
            ToolInfo(
                name=tool_config.name,
                enabled=tool_config.enabled,
                description=tool_config.description,
            ),
        )

    return tools_list


@router.patch("/{tool_name}/toggle", response_model=ToolInfo)
async def toggle_tool(tool_name: str = Path(...)) -> ToolInfo:
    """Toggle tool enabled status.

    Args:
        tool_name: Tool function name

    Returns:
        Updated tool information

    Raises:
        HTTPException: If tool not found
    """
    config = load_config()

    if tool_name not in config.tools.builtin_tools:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found",
        )

    # Toggle enabled status
    tool_config = config.tools.builtin_tools[tool_name]
    tool_config.enabled = not tool_config.enabled

    # Save config
    save_config(config)

    return ToolInfo(
        name=tool_config.name,
        enabled=tool_config.enabled,
        description=tool_config.description,
    )
