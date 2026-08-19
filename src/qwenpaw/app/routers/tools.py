# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks,too-many-branches,too-many-statements
"""API routes for built-in tools management."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ...config import load_config
from ...config.config import AgentProfileConfig, update_agent_config_async
from ...config.utils import mutate_config
from ...drivers.credentials.types import CredentialRecord
from ...security.secret_store import (
    mask_secret_value,
    restore_masked_secret_value,
)
from ...utils.io_utils import run_sync_io
from ..driver_config_service import DriverConfigService
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


_BUILTIN_TOOL_CONFIG_FIELDS: dict[str, list[dict]] = {
    "web_search": [
        {
            "name": "provider",
            "label": "Provider",
            "type": "select",
            "options": ["tavily", "anysearch"],
            "default": "tavily",
        },
        {
            "name": "api_key",
            "label": "API Key (optional)",
            "type": "password",
        },
    ],
}


def _builtin_credential_ref(tool_name: str, config: dict) -> str:
    """Return the credential-store ref for a builtin tool's password field,
    or "" when provider is missing/blank or keyless (caller must skip
    credential I/O)."""
    provider = str(config.get("provider") or "").strip()
    if not provider:
        return ""
    if tool_name == "web_search" and provider == "tavily":
        return ""
    return f"tool/{tool_name}/{provider}"


def _persist_browser_experimental(config: dict[str, Any]) -> None:
    """Persist Browser-card gating before the next process registration."""
    experimental = config.get("experimental")
    if not isinstance(experimental, bool):
        return

    def apply_experimental(application_config: Any) -> None:
        application_config.browser.experimental = experimental

    mutate_config(apply_experimental)


def _build_tool_info(tool_config: Any, tool_name: str) -> ToolInfo:
    """Build a complete ToolInfo from a tool config, including plugin metadata.

    Reads requires_config, config_fields and config_values from the plugin
    manifest so that every endpoint returns a consistent, complete response.

    Args:
        tool_config: BuiltinToolConfig instance
        tool_name: Tool function name

    Returns:
        Fully populated ToolInfo
    """
    from ...plugins.registry import PluginRegistry

    tool_info = ToolInfo(
        name=tool_config.name,
        enabled=tool_config.enabled,
        description=tool_config.description,
        async_execution=tool_config.async_execution,
        icon=tool_config.icon or "",
    )

    registry = PluginRegistry()
    plugin_id = registry.get_plugin_id_for_tool(tool_name)
    manifest = registry.get_plugin_manifest(plugin_id) if plugin_id else None

    if manifest and "meta" in manifest:
        meta = manifest["meta"]

        config_fields_data = None
        requires_config = False

        for t in meta.get("tools", []):
            if isinstance(t, dict) and t.get("name") == tool_name:
                requires_config = t.get("requires_config", False)
                config_fields_data = t.get("config_fields", [])
                break

        if config_fields_data is None:
            requires_config = meta.get("requires_config", False)
            config_fields_data = meta.get("config_fields", [])

        tool_info.requires_config = requires_config

        if config_fields_data:
            tool_info.config_fields = [
                ToolConfigField(**field) for field in config_fields_data
            ]

        if tool_config.config:
            masked_config = dict(tool_config.config)
            for field in config_fields_data:
                if (
                    field.get("type") == "password"
                    and field["name"] in masked_config
                ):
                    if masked_config[field["name"]]:
                        masked_config[field["name"]] = "***"
            tool_info.config_values = masked_config

    if tool_name == "browser":
        config_values: dict[str, Any] = {
            "experimental": load_config().browser.experimental,
        }
        try:
            from ...agents.tools import browser_track_effective

            config_values["experimental_effective"] = browser_track_effective()
        except Exception:
            pass
        tool_info.config_values = config_values
    elif tool_name in _BUILTIN_TOOL_CONFIG_FIELDS:
        tool_info.config_fields = [
            ToolConfigField(**f)
            for f in _BUILTIN_TOOL_CONFIG_FIELDS[tool_name]
        ]
        if tool_config.config:
            tool_info.config_values = dict(tool_config.config)

    return tool_info


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

    return [
        _build_tool_info(tool_config, tool_config.name)
        for tool_config in builtin_tools.values()
    ]


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

    return _build_tool_info(tool_config, tool_name)


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

    return _build_tool_info(tool_config, tool_name)


@router.get("/{tool_name}/config")
async def get_tool_config(
    tool_name: str = Path(...),
    request: Request = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Get tool configuration (sensitive fields masked).

    Args:
        tool_name: Tool function name
        request: FastAPI request
        provider: Optional provider to query credentials for (builtin tools
            with per-provider credential slots, e.g. web_search). When
            provided, the credential ref is computed from this value instead
            of the currently saved config, so the frontend can show the key
            for a provider the user is *about to* select.

    Returns:
        Tool configuration with sensitive fields masked
    """
    from ...plugins.registry import PluginRegistry
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    registry = PluginRegistry()

    # Get tool config for this agent
    config = (
        await run_sync_io(
            registry.get_tool_config,
            tool_name,
            workspace.agent_id,
        )
        or {}
    )

    # Mask sensitive fields
    plugin_id = registry.get_plugin_id_for_tool(tool_name)
    if plugin_id:
        manifest = registry.get_plugin_manifest(plugin_id)
        if manifest and "meta" in manifest:
            meta = manifest["meta"]

            # Try to get tool-specific config fields first
            config_fields = None
            tools = meta.get("tools", [])
            if isinstance(tools, list):
                for tool in tools:
                    if (
                        isinstance(tool, dict)
                        and tool.get("name") == tool_name
                    ):
                        config_fields = tool.get("config_fields", [])
                        break

            # Fallback to global config fields
            if config_fields is None:
                config_fields = meta.get("config_fields", [])

            masked_config = dict(config)
            for field in config_fields:
                if (
                    field.get("type") == "password"
                    and field["name"] in masked_config
                ):
                    if masked_config[field["name"]]:
                        masked_config[field["name"]] = "***"
            return masked_config

    elif tool_name in _BUILTIN_TOOL_CONFIG_FIELDS:
        result = dict(config)
        pw_field = next(
            (
                f
                for f in _BUILTIN_TOOL_CONFIG_FIELDS[tool_name]
                if f["type"] == "password"
            ),
            None,
        )
        if pw_field:
            ref_provider = (provider or "").strip() or result.get("provider")
            if ref_provider:
                result["provider"] = ref_provider
                ref = _builtin_credential_ref(
                    tool_name,
                    {"provider": ref_provider},
                )
                if ref:
                    record = await DriverConfigService(
                        workspace,
                    ).load_optional_credential(ref)
                    key = record.secrets.get("api_key", "") if record else ""
                    if key:
                        result[pw_field["name"]] = mask_secret_value(key)
        return result

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
    requested_config = dict(body.config)
    password_fields: set[str] = set()

    # Builtin-tool credential slot handling (web_search api_key): the key
    # never lands in agent.json; it lives in the driver credential store
    # under a per-provider ref. The mutation is deferred until after
    # agent.json is committed, with config rollback on credential failure.
    credential_action: tuple[str, ...] = ()
    credential_service: DriverConfigService | None = None
    old_tool_config: dict[str, Any] = {}

    def _restore_tool_config(agent_config: AgentProfileConfig) -> None:
        tool_config = agent_config.tools.builtin_tools[tool_name]
        tool_config.config = dict(old_tool_config) if old_tool_config else None

    if plugin_id:
        manifest = registry.get_plugin_manifest(plugin_id)
        if manifest and "meta" in manifest:
            meta = manifest["meta"]

            # Try to get tool-specific config fields first
            config_fields = None
            tools = meta.get("tools", [])
            if isinstance(tools, list):
                for tool in tools:
                    if (
                        isinstance(tool, dict)
                        and tool.get("name") == tool_name
                    ):
                        config_fields = tool.get("config_fields", [])
                        break

            # Fallback to global config fields
            if config_fields is None:
                config_fields = meta.get("config_fields", [])

            for field in config_fields:
                if field.get("type") == "password":
                    password_fields.add(field["name"])

    elif tool_name in _BUILTIN_TOOL_CONFIG_FIELDS:
        pw_field = next(
            (
                f
                for f in _BUILTIN_TOOL_CONFIG_FIELDS[tool_name]
                if f["type"] == "password"
            ),
            None,
        )
        if pw_field and pw_field["name"] in requested_config:
            incoming = requested_config.pop(pw_field["name"])
            ref = _builtin_credential_ref(tool_name, requested_config)
            if ref:
                credential_service = DriverConfigService(workspace)
                old_record = await credential_service.load_optional_credential(
                    ref,
                )
                old_key = (
                    old_record.secrets.get("api_key", "") if old_record else ""
                )
                new_key = restore_masked_secret_value(incoming, old_key)
                if new_key:
                    credential_action = ("put", ref, new_key)
                elif old_record:
                    credential_action = ("delete", ref)

    def apply_tool_config(agent_config: AgentProfileConfig) -> None:
        nonlocal old_tool_config
        if (
            not agent_config.tools
            or tool_name not in agent_config.tools.builtin_tools
        ):
            raise ValueError(f"Tool '{tool_name}' not found in agent")

        tool_config = agent_config.tools.builtin_tools[tool_name]
        existing_config = tool_config.config or {}
        if not old_tool_config:
            old_tool_config = dict(existing_config)
        config_to_save = dict(requested_config)
        for field_name in password_fields:
            if (
                config_to_save.get(field_name) == "***"
                and field_name in existing_config
            ):
                config_to_save[field_name] = existing_config[field_name]
        tool_config.config = config_to_save

    # Save tool config for this agent
    try:
        agent_config = await update_agent_config_async(
            workspace.agent_id,
            apply_tool_config,
        )
        persisted_config = dict(
            agent_config.tools.builtin_tools[tool_name].config,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update config: {str(e)}",
        ) from e

    # Credential mutation for builtin tools (web_search api_key) is deferred
    # until agent.json is safely committed, and the config is rolled back if
    # the credential write fails — the two stores cannot drift silently
    # (review #7081, Issue 2).
    if credential_action:
        try:
            if credential_action[0] == "put":
                await credential_service.credential_store.put(
                    CredentialRecord(
                        ref=credential_action[1],
                        kind="static",
                        secrets={"api_key": credential_action[2]},
                    ),
                )
            else:
                await credential_service.credential_store.delete(
                    credential_action[1],
                )
        except Exception as e:
            try:
                await update_agent_config_async(
                    workspace.agent_id,
                    _restore_tool_config,
                )
            except Exception:
                pass  # Best-effort rollback; the config write already failed.
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save credential: {str(e)}",
            ) from e

    if tool_name == "browser":
        await run_sync_io(
            _persist_browser_experimental,
            persisted_config,
        )
        if persisted_config.get("experimental") is True:
            from ...browser.runtime.managed_playwright import (
                start_managed_chromium_download,
            )

            start_managed_chromium_download()

    # Hot reload config to apply changes without full restart
    schedule_agent_reload(request, workspace.agent_id)

    return {"status": "success", "message": "Configuration updated"}
