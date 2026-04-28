# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks
"""API routes for built-in tools management."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ...config import load_config
from ..utils import schedule_agent_reload

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolConfigFieldType(str, Enum):
    """Tool configuration field types."""

    TEXT = "text"
    PASSWORD = "password"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"
    TEXTAREA = "textarea"


class ToolConfigField(BaseModel):
    """Tool configuration field definition."""

    name: str = Field(..., description="Field name")
    label: str = Field(..., description="Display label")
    type: ToolConfigFieldType = Field(
        ...,
        description="Field type",
    )
    required: bool = Field(
        default=False,
        description="Whether field is required",
    )
    placeholder: Optional[str] = Field(None, description="Placeholder text")
    help: Optional[str] = Field(None, description="Help text")
    options: Optional[List[str]] = Field(
        None,
        description="Options for select type",
    )
    default: Optional[Any] = Field(None, description="Default value")
    min: Optional[float] = Field(None, description="Minimum value for number")
    max: Optional[float] = Field(None, description="Maximum value for number")


class ToolInfo(BaseModel):
    """Tool information for API responses."""

    name: str = Field(..., description="Tool function name")
    enabled: bool = Field(..., description="Whether the tool is enabled")
    description: str = Field(default="", description="Tool description")
    async_execution: bool = Field(
        default=False,
        description="Whether to execute the tool asynchronously in background",
    )
    icon: str = Field(default="🔧", description="Emoji icon for the tool")
    requires_config: bool = Field(
        default=False,
        description="Whether tool requires configuration",
    )
    config_fields: Optional[list[ToolConfigField]] = Field(
        None,
        description="Configuration field definitions",
    )
    config_values: Optional[dict[str, Any]] = Field(
        None,
        description="Current configuration values (sensitive fields masked)",
    )


class ToolConfigUpdate(BaseModel):
    """Tool configuration update request."""

    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool configuration key-value pairs",
    )


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
    from ...plugins.registry import PluginRegistry

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

    # Get plugin registry for config metadata
    registry = PluginRegistry()

    # Optimize: Preload all manifests to avoid N+1 queries
    all_manifests = registry.get_all_plugin_manifests()

    # Build tool_name -> manifest mapping
    tool_to_manifest = {}
    for manifest in all_manifests.values():
        meta = manifest.get("meta", {})
        tool_name = meta.get("tool_name")
        if tool_name:
            tool_to_manifest[tool_name] = manifest

    tools_list = []
    for tool_config in builtin_tools.values():
        tool_info = ToolInfo(
            name=tool_config.name,
            enabled=tool_config.enabled,
            description=tool_config.description,
            async_execution=tool_config.async_execution,
            icon=tool_config.icon or "",
        )

        # Add config metadata from plugin manifest (using cached mapping)
        manifest = tool_to_manifest.get(tool_config.name)
        if manifest and "meta" in manifest:
            meta = manifest["meta"]
            tool_info.requires_config = meta.get(
                "requires_config",
                False,
            )
            # Convert config_fields to Pydantic models
            config_fields_data = meta.get("config_fields", [])
            if config_fields_data:
                tool_info.config_fields = [
                    ToolConfigField(**field) for field in config_fields_data
                ]

            # Get current config values (masked) from agent config
            config = registry.get_tool_config(
                tool_config.name,
                workspace.agent_id,
            )
            if config:
                masked_config = dict(config)
                # Mask password fields
                for field in config_fields_data:
                    if (
                        field.get("type") == "password"
                        and field["name"] in masked_config
                    ):
                        if masked_config[field["name"]]:
                            masked_config[field["name"]] = "***"
                tool_info.config_values = masked_config

        tools_list.append(tool_info)

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


@router.get("/{tool_name}/config")
async def get_tool_config(
    tool_name: str = Path(...),
    request: Request = None,
) -> dict[str, Any]:
    """Get tool configuration (sensitive fields masked).

    Args:
        tool_name: Tool function name
        request: FastAPI request

    Returns:
        Tool configuration with sensitive fields masked
    """
    from ...plugins.registry import PluginRegistry
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    registry = PluginRegistry()

    # Get tool config for this agent
    config = registry.get_tool_config(tool_name, workspace.agent_id) or {}

    # Mask sensitive fields
    plugin_id = registry.get_plugin_id_for_tool(tool_name)
    if plugin_id:
        manifest = registry.get_plugin_manifest(plugin_id)
        if manifest and "meta" in manifest:
            config_fields = manifest["meta"].get("config_fields", [])
            masked_config = dict(config)
            for field in config_fields:
                if (
                    field.get("type") == "password"
                    and field["name"] in masked_config
                ):
                    if masked_config[field["name"]]:
                        masked_config[field["name"]] = "***"
            return masked_config

    return config


@router.post("/{tool_name}/config")
async def update_tool_config(
    tool_name: str = Path(...),
    body: ToolConfigUpdate = Body(...),
    request: Request = None,
) -> dict[str, str]:
    """Update tool configuration.

    Args:
        tool_name: Tool function name
        body: Configuration update
        request: FastAPI request

    Returns:
        Success response

    Raises:
        HTTPException: If update fails
    """
    from ...plugins.registry import PluginRegistry
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    registry = PluginRegistry()

    # Get plugin manifest to check for password fields
    plugin_id = registry.get_plugin_id_for_tool(tool_name)
    config_to_save = dict(body.config)

    if plugin_id:
        manifest = registry.get_plugin_manifest(plugin_id)
        if manifest and "meta" in manifest:
            config_fields = manifest["meta"].get("config_fields", [])

            # Get existing config
            existing_config = (
                registry.get_tool_config(
                    tool_name,
                    workspace.agent_id,
                )
                or {}
            )

            # Preserve existing password values if user sent masked value
            for field in config_fields:
                if field.get("type") == "password":
                    field_name = field["name"]
                    new_value = config_to_save.get(field_name)

                    # If value is "***" (masked), keep existing value
                    if new_value == "***" and field_name in existing_config:
                        config_to_save[field_name] = existing_config[
                            field_name
                        ]

    # Save tool config for this agent
    try:
        registry.set_tool_config(tool_name, workspace.agent_id, config_to_save)

        # Hot reload config to apply changes without full restart
        schedule_agent_reload(request, workspace.agent_id)

        return {"status": "success", "message": "Configuration updated"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update config: {str(e)}",
        ) from e
