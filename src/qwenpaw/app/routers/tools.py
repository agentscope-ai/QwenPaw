# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks,too-many-branches
"""API routes for built-in tools management."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel, Field, model_validator

from ...config import load_config, save_config
from ...identity.runtime import get_identity_schema, is_multi_user_enabled
from ..utils import schedule_agent_reload

router = APIRouter(prefix="/tools", tags=["tools"])

_RETIRED_PRODUCT_TOOLS = frozenset({"delegate_external_agent"})


def _is_tool_published(tool_name: str) -> bool:
    """返回工具是否仍属于当前产品能力。"""
    return tool_name not in _RETIRED_PRODUCT_TOOLS


def _ensure_tool_is_published(tool_name: str) -> None:
    if not _is_tool_published(tool_name):
        raise HTTPException(status_code=404, detail="Tool not found")


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
        description="Current non-sensitive configuration values",
    )
    credential_status: dict[
        str,
        Literal["missing", "configured", "revoked"],
    ] = Field(default_factory=dict)
    can_edit: bool = True
    policy_locked: bool = False
    policy_reason: Optional[str] = None


class ToolCredentialAction(BaseModel):
    """Explicit mutation for one password field."""

    action: Literal["keep", "replace", "delete"]
    value: Optional[str] = None

    @model_validator(mode="after")
    def validate_value(self) -> "ToolCredentialAction":
        """Require a value only when replacing a credential."""
        if self.action == "replace":
            if not isinstance(self.value, str) or not self.value:
                raise ValueError("replace requires a non-empty value")
        elif self.value is not None:
            raise ValueError(f"{self.action} does not accept a value")
        return self


class ToolConfigView(BaseModel):
    """Safe tool configuration projection returned to Console."""

    config: dict[str, Any] = Field(default_factory=dict)
    credential_status: dict[str, Literal["missing", "configured", "revoked"]] = (
        Field(default_factory=dict)
    )


class ToolConfigUpdate(BaseModel):
    """Tool configuration update request."""

    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive tool configuration key-value pairs",
    )
    credential_updates: dict[str, ToolCredentialAction] = Field(
        default_factory=dict,
        description="Explicit password field mutations",
    )


def _project_safe_tool_config(
    config: dict[str, Any],
    config_fields: list[dict[str, Any]],
    *,
    credential_status: Optional[dict[str, str]] = None,
) -> ToolConfigView:
    """Return declared non-password values and password status only."""
    password_names = {
        str(field.get("name"))
        for field in config_fields
        if field.get("type") == "password" and field.get("name")
    }
    allowed_non_sensitive = {
        str(field.get("name"))
        for field in config_fields
        if field.get("type") != "password" and field.get("name")
    }
    safe = {
        name: value
        for name, value in config.items()
        if name in allowed_non_sensitive
    }
    statuses = {
        name: str((credential_status or {}).get(name, "missing"))
        for name in password_names
    }
    return ToolConfigView(config=safe, credential_status=statuses)


def _validate_tool_config_update(
    body: ToolConfigUpdate,
    config_fields: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, ToolCredentialAction]]:
    """Validate that normal values and password actions stay separated."""
    field_types = {
        str(field["name"]): str(field.get("type") or "text")
        for field in config_fields
        if field.get("name")
    }
    unknown_config = set(body.config) - set(field_types)
    password_in_config = {
        name for name in body.config if field_types.get(name) == "password"
    }
    invalid_actions = {
        name
        for name in body.credential_updates
        if field_types.get(name) != "password"
    }
    if unknown_config or password_in_config or invalid_actions:
        raise ValueError("invalid tool configuration fields")
    for name, value in body.config.items():
        field_type = field_types[name]
        valid = (
            (
                field_type in {"text", "textarea", "select"}
                and isinstance(value, str)
            )
            or (
                field_type == "number"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            )
            or (field_type == "boolean" and isinstance(value, bool))
        )
        if not valid:
            raise ValueError(f"invalid value for tool configuration field: {name}")
    return dict(body.config), dict(body.credential_updates)


def _tool_config_fields(registry: Any, tool_name: str) -> list[dict[str, Any]]:
    """Return manifest fields for one installed tool."""
    if tool_name == "browser":
        return [
            {
                "name": "experimental",
                "label": "Browser implementation",
                "type": "boolean",
                "required": False,
            }
        ]
    plugin_id = registry.get_plugin_id_for_tool(tool_name)
    if not plugin_id:
        return []
    manifest = registry.get_plugin_manifest(plugin_id)
    if not manifest or "meta" not in manifest:
        return []
    meta = manifest["meta"]
    for tool in meta.get("tools", []):
        if isinstance(tool, dict) and tool.get("name") == tool_name:
            return list(tool.get("config_fields", []))
    return list(meta.get("config_fields", []))


def _password_field_names(
    config_fields: list[dict[str, Any]],
) -> list[str]:
    return [
        str(field["name"])
        for field in config_fields
        if field.get("type") == "password" and field.get("name")
    ]


def _tool_credential_service():
    from ...drivers.credentials.postgres_store import PostgresCredentialStore
    from ..tools.credentials import ToolCredentialService

    return ToolCredentialService(
        store=PostgresCredentialStore(schema=get_identity_schema()),
    )


def _persisted_tool_config(agent_id: str, tool_name: str) -> dict[str, Any]:
    """Read raw Agent config without merging runtime-only credentials."""
    from ...config.config import load_agent_config

    config = load_agent_config(agent_id)
    if not config.tools or tool_name not in config.tools.builtin_tools:
        return {}
    return dict(config.tools.builtin_tools[tool_name].config or {})


def _ensure_browser_policy_allows_agent_change(tool_name: str) -> None:
    """Reject Agent-level Browser mutations while platform policy disables it."""
    if tool_name != "browser":
        return
    from ...browser.policy import effective_browser_policy

    policy = effective_browser_policy(
        load_config().browser,
        multi_user=is_multi_user_enabled(),
    )
    if not policy.allowed:
        raise HTTPException(status_code=403, detail=policy.reason)


def _persist_browser_experimental(config: dict[str, Any]) -> None:
    """Persist Browser-card gating before the next process registration."""
    experimental = config.get("experimental")
    if not isinstance(experimental, bool):
        return
    application_config = load_config()
    application_config.browser.experimental = experimental
    save_config(application_config)
    if experimental:
        from ...browser.runtime.managed_playwright import (
            start_managed_chromium_download,
        )

        start_managed_chromium_download()


def _build_tool_info(
    tool_config: Any,
    tool_name: str,
    *,
    can_edit: bool = True,
) -> ToolInfo:
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
        can_edit=can_edit,
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

        stored_config = dict(tool_config.config or {})
        if stored_config or config_fields_data:
            legacy_status = {
                str(field["name"]): (
                    "configured"
                    if stored_config.get(str(field["name"]))
                    else "missing"
                )
                for field in config_fields_data
                if field.get("type") == "password" and field.get("name")
            }
            projection = _project_safe_tool_config(
                stored_config,
                config_fields_data,
                credential_status=legacy_status,
            )
            tool_info.config_values = projection.config
            tool_info.credential_status = projection.credential_status

    if tool_name == "browser":
        from ...browser.policy import effective_browser_policy

        browser_config = load_config().browser
        policy = effective_browser_policy(
            browser_config,
            multi_user=is_multi_user_enabled(),
        )
        config_values: dict[str, Any] = {
            "experimental": browser_config.experimental,
            "multi_user_allowed": policy.allowed,
        }
        try:
            from ...agents.tools import browser_track_effective

            config_values["experimental_effective"] = browser_track_effective()
        except Exception:
            pass
        tool_info.config_values = config_values
        if policy.locked:
            tool_info.enabled = False
            tool_info.policy_locked = True
            tool_info.policy_reason = policy.reason
            tool_info.can_edit = False

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

    from ..agent_context import get_agent_access_state
    from ...access.agent_repository import AgentResourceRole

    role, historical_read_only = get_agent_access_state(request)
    can_edit = role in {
        AgentResourceRole.OWNER,
        AgentResourceRole.COLLABORATOR,
    } and not historical_read_only
    result: list[ToolInfo] = []
    credential_service = (
        _tool_credential_service() if is_multi_user_enabled() else None
    )
    registry = PluginRegistry()
    for tool_config in builtin_tools.values():
        if not _is_tool_published(tool_config.name):
            continue
        info = _build_tool_info(
            tool_config,
            tool_config.name,
            can_edit=can_edit,
        )
        if credential_service is not None:
            fields = _tool_config_fields(registry, tool_config.name)
            password_fields = _password_field_names(fields)
            if password_fields:
                loaded = await credential_service.load_tool(
                    agent_id=workspace.agent_id,
                    tool_name=tool_config.name,
                    password_fields=password_fields,
                )
                info.credential_status = {
                    name: "configured" if name in loaded else "missing"
                    for name in password_fields
                }
        result.append(info)
    return result


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

    _ensure_tool_is_published(tool_name)
    workspace = await get_agent_for_request(request)
    _ensure_browser_policy_allows_agent_change(tool_name)
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

    _ensure_tool_is_published(tool_name)
    workspace = await get_agent_for_request(request)
    _ensure_browser_policy_allows_agent_change(tool_name)
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


@router.get("/{tool_name}/config", response_model=ToolConfigView)
async def get_tool_config(
    tool_name: str = Path(...),
    request: Request = None,
) -> ToolConfigView:
    """Get non-sensitive configuration and credential status.

    Args:
        tool_name: Tool function name
        request: FastAPI request

    Returns:
        Tool configuration with sensitive fields masked
    """
    from ...plugins.registry import PluginRegistry
    from ..agent_context import get_agent_for_request

    _ensure_tool_is_published(tool_name)
    workspace = await get_agent_for_request(request)
    registry = PluginRegistry()

    # Get tool config for this agent
    config = _persisted_tool_config(workspace.agent_id, tool_name)

    config_fields = _tool_config_fields(registry, tool_name)
    if not config_fields and registry.get_plugin_id_for_tool(tool_name) is None:
        # Built-ins without plugin configuration have an empty safe view.
        return ToolConfigView()
    password_fields = _password_field_names(config_fields)
    if is_multi_user_enabled():
        service = _tool_credential_service()
        loaded = await service.load_tool(
            agent_id=workspace.agent_id,
            tool_name=tool_name,
            password_fields=password_fields,
        )
        legacy_status = {
            name: "configured" if name in loaded else "missing"
            for name in password_fields
        }
    else:
        legacy_status = {
            name: "configured" if config.get(name) else "missing"
            for name in password_fields
        }
    return _project_safe_tool_config(
        config,
        config_fields,
        credential_status=legacy_status,
    )


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

    _ensure_tool_is_published(tool_name)
    workspace = await get_agent_for_request(request)
    registry = PluginRegistry()

    plugin_id = registry.get_plugin_id_for_tool(tool_name)
    if not plugin_id and tool_name != "browser":
        raise HTTPException(status_code=404, detail="Tool configuration not found")
    if tool_name == "browser" and is_multi_user_enabled():
        raise HTTPException(
            status_code=403,
            detail="Browser platform policy cannot be changed from an Agent",
        )
    config_fields = _tool_config_fields(registry, tool_name)
    try:
        config_to_save, credential_actions = _validate_tool_config_update(
            body,
            config_fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing_config = _persisted_tool_config(workspace.agent_id, tool_name)
    password_names = set(_password_field_names(config_fields))
    if not is_multi_user_enabled():
        for field_name in password_names:
            if field_name in existing_config:
                config_to_save[field_name] = existing_config[field_name]
        for field_name, action in credential_actions.items():
            if action.action == "replace":
                config_to_save[field_name] = action.value
            elif action.action == "delete":
                config_to_save.pop(field_name, None)

    actor_user_id = None
    if is_multi_user_enabled() and credential_actions:
        from ...access.dependencies import get_actor

        actor_user_id = get_actor(request).user_id
        if actor_user_id is None:
            raise HTTPException(status_code=403, detail="forbidden")

    # Save tool config for this agent
    try:
        registry.set_tool_config(tool_name, workspace.agent_id, config_to_save)

        if is_multi_user_enabled() and credential_actions:
            try:
                await _tool_credential_service().apply_actions(
                    agent_id=workspace.agent_id,
                    tool_name=tool_name,
                    actions={
                        name: (action.action, action.value)
                        for name, action in credential_actions.items()
                    },
                    actor_user_id=actor_user_id,
                )
            except Exception:
                registry.set_tool_config(
                    tool_name,
                    workspace.agent_id,
                    existing_config,
                )
                raise

        if tool_name == "browser":
            _persist_browser_experimental(config_to_save)

        # Hot reload config to apply changes without full restart
        schedule_agent_reload(request, workspace.agent_id)

        return {"status": "success", "message": "Configuration updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update config: {str(e)}",
        ) from e
