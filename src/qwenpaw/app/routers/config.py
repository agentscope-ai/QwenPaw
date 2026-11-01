# -*- coding: utf-8 -*-

import asyncio
from contextlib import AsyncExitStack, suppress
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path as FilePath
from typing import Any, List, Optional, cast

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)
from pydantic import BaseModel, Field, ValidationError

from ...agents.acp.core import ACPAgentConfig, ACPConfig
from ...agents.acp.node_runtime import (
    ACPNodeRuntimeStatus,
    get_node_runtime_status,
    resolve_node_runtime,
)
from ...config import (
    ChannelConfig,
    ToolGuardConfig,
    ToolGuardRuleConfig,
    load_config,
)
from ...config.utils import mutate_config
from ...config.config import (
    AgentsLLMRoutingConfig,
    HeartbeatConfig,
    SkillScannerConfig,
    SkillScannerWhitelistEntry,
    ThemeConfig,
)
from ...utils.io_utils import run_async_to_completion, run_sync_io
from ...config.timezone import normalize_tz
from ..channels.conflict import (
    get_channel_bot_identity,
    get_channel_config,
)
from ..channels.qrcode_auth_handler import (
    generate_qrcode_image,
)
from ..channels.management import ManagementError
from ..channels.qrcode_sessions import resolve_channel_management_scope_async
from ..channels.registry import BUILTIN_CHANNEL_KEYS
from ..channels.catalog import (
    get_configurable_channel_catalog_async,
    clean_channel_config,
)
from ..utils import schedule_agent_reload
from .schemas_config import (
    ChannelConflictAgent,
    ChannelConflictResponse,
    ChannelHealthResponse,
    ChannelRestartResponse,
    HeartbeatBody,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get(
    "/theme",
    response_model=dict,
    summary="Get Console theme",
)
async def get_theme() -> dict:
    """Return the sparse user theme, or an empty object for defaults."""
    config = await run_sync_io(load_config)
    if config.theme is None:
        return {}
    return config.theme.model_dump(exclude_none=True)


@router.put(
    "/theme",
    response_model=ThemeConfig,
    response_model_exclude_none=True,
    summary="Update Console theme",
)
async def put_theme(theme: ThemeConfig = Body(...)) -> ThemeConfig:
    """Replace the sparse user theme without reloading agents."""

    def apply_theme(config: Any) -> None:
        config.theme = theme if theme.model_dump(exclude_none=True) else None

    result = await run_sync_io(mutate_config, apply_theme)
    return result.theme or ThemeConfig()


@router.delete(
    "/theme",
    status_code=204,
    summary="Reset Console theme",
)
async def delete_theme() -> None:
    """Remove the user theme and restore built-in Console defaults."""

    def clear_theme(config: Any) -> None:
        config.theme = None

    await run_sync_io(mutate_config, clear_theme)


def _channel_config_class(name: str) -> Optional[type[BaseModel]]:
    """Config model for a built-in channel, None for plugin channels.

    Built-in channel shapes are declared once as ``ChannelConfig``
    fields, so deriving them here cannot drift when a channel is added
    later. This is the same source of truth doctor already walks.
    """
    field = ChannelConfig.model_fields.get(name)
    annotation = field.annotation if field is not None else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _validated_channel_config(
    name: str,
    values: dict,
    *,
    official_description=None,
):
    """Use trusted static schemas with or without installed channel code."""
    from ...plugins.registry import PluginRegistry
    from ...plugins.channel_config import validate_channel_config
    from ...plugins.official_channel_catalog import official_channel_owners
    from ...plugins.official_channels import bundled_channel_description

    if not isinstance(values, dict):
        raise HTTPException(
            status_code=422,
            detail="Channel configuration must be an object",
        )
    if name == "slack" and values.get("allow_from") is None:
        values = {**values, "allow_from": []}
    row = PluginRegistry().get_channel_catalog_entry(name)
    try:
        schema = None
        if row is not None and row.description_record is not None:
            schema = row.description_record.descriptor.config_schema
        elif name in official_channel_owners():
            plugin_id = official_channel_owners()[name]
            description = official_description or bundled_channel_description(
                plugin_id,
            )
            schema = description.descriptor.config_schema
        if schema is not None:
            return validate_channel_config(
                schema,
                clean_channel_config(values, schema),
            )
        values = clean_channel_config(values)
        model = _channel_config_class(name)
        if model is not None:
            return model.model_validate(values).model_dump(mode="json")
        return values
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_context=False),
        ) from exc
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _validated_channel_config_async(name: str, values: dict):
    """Prefetch official schemas without moving registry reads off-loop."""
    from ...plugins.registry import PluginRegistry
    from ...plugins.official_channel_catalog import official_channel_owners
    from ...plugins.official_channels import bundled_channel_description

    description = None
    owner = official_channel_owners().get(name)
    row = PluginRegistry().get_channel_catalog_entry(name)
    if owner is not None and (row is None or row.description_record is None):
        try:
            description = await run_sync_io(bundled_channel_description, owner)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _validated_channel_config(
        name,
        values,
        official_description=description,
    )


def _save_channel_updates(agent_id: str, updates: dict) -> ChannelConfig:
    """Merge only requested channels into the latest persisted config."""
    from ...config.config import mutate_agent_config

    def apply_channels(candidate: Any) -> None:
        current = candidate.channels.model_dump() if candidate.channels else {}
        candidate.channels = ChannelConfig.model_validate(
            {**current, **updates},
        )

    try:
        saved = mutate_agent_config(agent_id, apply_channels)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_context=False),
        ) from exc
    # The mutator always assigns a validated ChannelConfig before saving.
    return cast(ChannelConfig, saved.channels)


async def _save_channel_updates_async(request, agent_id, updates):
    """Finish publication and captured-agent reload before caller cancellation."""

    async def persist():
        saved = await run_sync_io(_save_channel_updates, agent_id, updates)
        schedule_agent_reload(request, agent_id)
        return saved

    return await run_async_to_completion(persist())


_ALLOWED_ACP_TOOL_PARSE_MODES = {
    "call_title",
    "update_detail",
    "call_detail",
}


class ACPNodeRuntimeUpdate(BaseModel):
    node_path: str = ""


@router.get(
    "/channels",
    summary="List all channels",
    description="Retrieve configuration for all available channels",
)
async def list_channels(request: Request) -> dict:
    """List all channel configs (filtered by available channels)."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    agent_config = agent.config
    available = await get_configurable_channel_catalog_async(
        agent.config.channels.model_dump() if agent.config.channels else (),
    )

    # Get channel configs from agent's config (with fallback to empty)
    channels_config = agent_config.channels
    if channels_config is None:
        # No channels config yet, use empty defaults
        all_configs = {}
    else:
        all_configs = channels_config.model_dump()
        extra = getattr(channels_config, "__pydantic_extra__", None) or {}
        all_configs.update(extra)

    # Return all available channels (use default config if not saved)
    result = {}
    for key, metadata in available.items():
        if key in all_configs:
            channel_data = (
                dict(all_configs[key])
                if isinstance(all_configs[key], dict)
                else all_configs[key]
            )
        else:
            # Channel registered but no config saved yet, use empty default
            channel_data = dict(
                metadata.get(
                    "defaults",
                    {"enabled": False, "bot_prefix": ""},
                ),
            )
        if isinstance(channel_data, dict):
            channel_data["isBuiltin"] = key in BUILTIN_CHANNEL_KEYS
        result[key] = channel_data

    return result


@router.get(
    "/channels/types",
    summary="List channel types",
    description="Return all available channel type identifiers",
)
async def list_channel_types(request: Request) -> List[str]:
    """Configurable types are independent of runtime gates."""
    return list(await list_channel_schemas(request))


@router.get("/channels/schemas", summary="Get editable channel schemas")
async def list_channel_schemas(request: Request) -> dict:
    from ...channel_protocol.management import MANAGEMENT_CAPABILITIES
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    saved = agent.config.channels.model_dump() if agent.config.channels else {}
    result = await get_configurable_channel_catalog_async(saved)
    loader = getattr(request.app.state, "plugin_loader", None)
    ready = set()
    if loader is not None:
        for key, row in result.items():
            record = loader.get_loaded_plugin(row.get("plugin_id", key))
            if record is not None and record.status == "failed":
                row.update(
                    availability="failed",
                    diagnostic="; ".join(record.diagnostics),
                )
            elif (
                record is not None
                and record.enabled
                and "channel_validation_passed" in record.diagnostics
            ):
                row["availability"] = "validated"
                ready.add(key)
    manager = getattr(agent, "channel_manager", None)
    if manager is not None:
        for key, row in result.items():
            if row.get("process_mode") != "runner_process":
                continue
            channel = await manager.get_channel(key)
            process = getattr(channel, "channel_process", None)
            if process is None:
                continue
            health = process.health_snapshot()
            row["runtime_state"] = health["platform_state"]
            if (
                health["state"] == "ready"
                and health["platform_state"] == "connected"
            ):
                row["availability"] = "running"
            elif health["last_error"]:
                row.update(
                    availability="failed",
                    diagnostic=health["last_error"],
                )
    registry = getattr(loader, "registry", None)
    workspace_dir = getattr(agent, "workspace_dir", None)
    if workspace_dir is not None:
        workspace_dir = str(FilePath(workspace_dir).expanduser().resolve())
    occupied = (
        {
            lease.key.name
            for lease in registry.runtime_owners.leases()
            if lease.key.kind == "channel"
            and lease.key.scope_id == workspace_dir
        }
        if registry is not None
        else set()
    )
    for key, row in result.items():
        entry = (
            registry.get_channel_catalog_entry(key)
            if registry is not None and key in ready
            else None
        )
        description = entry.description_record if entry is not None else None
        row["qrcode_available"] = bool(
            workspace_dir is not None
            and description is not None
            and MANAGEMENT_CAPABILITIES["qrcode.fetch"]
            in description.descriptor.capabilities
            and key not in occupied,
        )
        if row.get("availability") in {"running", "validated"}:
            row.pop("repair", None)
    return result


@router.put(
    "/channels",
    response_model=ChannelConfig,
    summary="Update all channels",
    description="Update configuration for all channels at once",
)
async def put_channels(
    request: Request,
    channels_config: dict = Body(
        ...,
        description="Complete channel configuration",
    ),
) -> ChannelConfig:
    """Update all channel configs."""
    from ...config.config import load_agent_config
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    persisted = await run_sync_io(load_agent_config, agent.agent_id)
    current = persisted.channels.model_dump() if persisted.channels else {}
    from ...plugins.channel_config import channel_config_dict

    incoming = channel_config_dict(channels_config)
    keys = getattr(channels_config, "model_fields_set", incoming.keys())
    updates = {}
    changed = []
    for key in keys:
        value = await _validated_channel_config_async(key, incoming[key])
        if current.get(key) != value:
            changed.append(key)
        updates[key] = value
    sessions = getattr(request.app.state, "channel_qrcode_sessions", None)
    async with AsyncExitStack() as stack:
        if sessions is not None and changed:
            await stack.enter_async_context(
                sessions.operation_guard(agent.agent_id, tuple(changed)),
            )
        saved_channels = await _save_channel_updates_async(
            request,
            agent.agent_id,
            updates,
        )

    return saved_channels


# ── Channel health check & restart ─────────────────────────────────────────


async def _resolve_channel_manager(
    request: Request,
    channel_name: str = Path(
        ...,
        description="Name of the channel",
        min_length=1,
    ),
):
    """Shared dependency: validate channel name and return channel_manager."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    available = await get_configurable_channel_catalog_async(
        agent.config.channels.model_dump() if agent.config.channels else (),
    )
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not available",
        )

    agent = await get_agent_for_request(request)
    channel_manager = agent.channel_manager
    if channel_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Channel manager not initialized",
        )
    return channel_manager


@router.get(
    "/channels/{channel_name}/health",
    response_model=ChannelHealthResponse,
    summary="Health check for a channel",
    description="Return the runtime health status of a specific channel",
)
async def get_channel_health(
    channel_name: str = Path(
        ...,
        description="Name of the channel to check",
        min_length=1,
    ),
    channel_manager=Depends(_resolve_channel_manager),
) -> ChannelHealthResponse:
    """Return health status for a specific channel."""
    try:
        return await channel_manager.get_channel_health(
            channel_name,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Channel '{channel_name}' is not running."
                " It may be disabled or not configured."
            ),
        ) from exc


@router.post(
    "/channels/{channel_name}/restart",
    response_model=ChannelRestartResponse,
    summary="Restart a channel",
    description=(
        "Stop and re-start a specific channel without restarting the agent"
    ),
)
async def restart_channel(
    channel_name: str = Path(
        ...,
        description="Name of the channel to restart",
        min_length=1,
    ),
    channel_manager=Depends(_resolve_channel_manager),
) -> ChannelRestartResponse:
    """Restart a specific channel."""
    try:
        return await channel_manager.restart_channel(
            channel_name,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Channel '{channel_name}' is not running."
                " It may be disabled or not configured."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(f"Failed to restart channel '{channel_name}': {exc}"),
        ) from exc


# ── Unified QR code endpoints for all channels ─────────────────────────────


def _management_http_error(error: ManagementError) -> HTTPException:
    reason = error.reason_code
    status = 502
    if reason in {"PLUGIN_NOT_INSTALLED", "CHANNEL_UNAVAILABLE"}:
        status = 404
    elif reason == "PLUGIN_DISABLED":
        status = 403
    elif reason in {"MANAGEMENT_INVALID_REQUEST", "MANAGEMENT_UNSUPPORTED"}:
        status = 400
    elif reason in {
        "MANAGEMENT_BUSY",
        "ACCOUNT_IN_USE",
        "SOURCE_REVISION_MISMATCH",
        "IDENTITY_MISMATCH",
    }:
        status = 409
    elif reason == "MANAGEMENT_TIMEOUT":
        status = 504
    elif reason in {"MANAGEMENT_CLOSED", "MANAGEMENT_CLEANUP_FAILED"}:
        status = 503
    return HTTPException(status, reason)


async def _managed_qrcode_sessions(request, channel):
    """Select QR descriptors, including offline official takeover metadata."""
    from ...channel_protocol.management import MANAGEMENT_CAPABILITIES
    from ...plugins.official_channel_catalog import official_channel_owners
    from ...plugins.official_channels import bundled_channel_description

    loader = getattr(request.app.state, "plugin_loader", None)
    row = (
        loader.registry.get_channel_catalog_entry(channel) if loader else None
    )
    description = row.description_record if row is not None else None
    if description is None:
        owner = official_channel_owners().get(channel)
        if owner is not None:
            try:
                description = await run_sync_io(
                    bundled_channel_description,
                    owner,
                )
            except (OSError, ValueError, KeyError):
                raise HTTPException(503, "CHANNEL_UNAVAILABLE") from None
    if description is None or (
        MANAGEMENT_CAPABILITIES["qrcode.fetch"]
        not in description.descriptor.capabilities
    ):
        raise HTTPException(
            status_code=404,
            detail=f"QR code not supported for channel: {channel}",
        )
    sessions = getattr(request.app.state, "channel_qrcode_sessions", None)
    if sessions is None:
        raise HTTPException(503, "MANAGEMENT_CLOSED")
    return sessions


async def _qrcode_request(request, operation):
    """Disconnect cancels only this request's session waiter."""
    finished = asyncio.Event()

    async def disconnected():
        while not finished.is_set() and not await request.is_disconnected():
            await asyncio.sleep(0.1)

    task = asyncio.create_task(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait(
            (task, watcher),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if watcher in done:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise HTTPException(499, "Client disconnected")
        return await task
    except ManagementError as error:
        raise _management_http_error(error) from None
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise
        raise HTTPException(400, "QR session is no longer active") from None
    finally:
        finished.set()
        watcher.cancel()
        if not task.done():
            task.cancel()
        await run_async_to_completion(
            asyncio.gather(task, watcher, return_exceptions=True),
        )


@router.get(
    "/channels/{channel}/qrcode",
    summary="Get channel authorization QR code",
    description=(
        "Fetch a QR code image (base64 PNG) for the given channel. "
        "Available for channel descriptors that declare the QR-code "
        "management capability."
    ),
)
async def get_channel_qrcode(request: Request, channel: str) -> dict:
    """Return {qrcode_img, poll_token} for the requested channel."""
    sessions = await _managed_qrcode_sessions(request, channel)
    scope = await resolve_channel_management_scope_async(request, channel)
    result = await _qrcode_request(
        request,
        sessions.fetch(scope, dict(request.query_params)),
    )
    return {
        "qrcode_img": generate_qrcode_image(result.scan_url),
        "poll_token": result.poll_token,
    }


@router.get(
    "/channels/{channel}/qrcode/status",
    summary="Poll channel QR code authorization status",
    description=(
        "Poll a scoped QR session for a channel descriptor that declares "
        "the QR-code management capability."
    ),
)
async def get_channel_qrcode_status(
    request: Request,
    channel: str,
    token: str,
) -> dict:
    """Return {status, credentials} for the requested channel."""
    sessions = await _managed_qrcode_sessions(request, channel)
    scope = await resolve_channel_management_scope_async(request, channel)
    result = await _qrcode_request(request, sessions.poll(scope, token))
    return {"status": result.status, "credentials": result.credentials}


@router.delete("/channels/{channel}/qrcode", status_code=204)
async def cancel_channel_qrcode(
    request: Request,
    channel: str,
    token: str,
) -> None:
    """Revoke one exact scoped QR handle and settle its actual worker."""
    sessions = getattr(request.app.state, "channel_qrcode_sessions", None)
    if sessions is None:
        raise HTTPException(503, "MANAGEMENT_CLOSED")
    scope = await resolve_channel_management_scope_async(request, channel)
    try:
        await sessions.cancel(scope, token)
    except ManagementError as error:
        raise _management_http_error(error) from None


@router.get(
    "/channels/{channel_name}",
    response_model=dict,
    summary="Get channel config",
    description="Retrieve configuration for a specific channel by name",
)
async def get_channel(
    request: Request,
    channel_name: str = Path(
        ...,
        description="Name of the channel to retrieve",
        min_length=1,
    ),
) -> dict:
    """Get a specific channel config by name."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    available = await get_configurable_channel_catalog_async(
        agent.config.channels.model_dump() if agent.config.channels else (),
    )
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )

    agent = await get_agent_for_request(request)
    channels = agent.config.channels
    if channels is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not configured",
        )

    single_channel_config = getattr(channels, channel_name, None)
    if single_channel_config is None:
        extra = getattr(channels, "__pydantic_extra__", None) or {}
        single_channel_config = extra.get(channel_name)
    if single_channel_config is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )
    if isinstance(single_channel_config, BaseModel):
        return single_channel_config.model_dump(mode="json")
    return single_channel_config


@router.post(
    "/channels/{channel_name}/conflict-check",
    response_model=ChannelConflictResponse,
    summary="Check channel Bot conflicts",
    description="Check whether another running agent uses the same Bot",
)
async def check_channel_conflict(
    request: Request,
    channel_name: str = Path(
        ...,
        description="Name of the channel to check",
        min_length=1,
    ),
    single_channel_config: dict = Body(
        ...,
        description="Proposed channel configuration",
    ),
) -> ChannelConflictResponse:
    """Check a proposed config against channels in running agents."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    available = await get_configurable_channel_catalog_async(
        agent.config.channels.model_dump() if agent.config.channels else (),
    )
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )

    if not single_channel_config.get("enabled", False):
        return ChannelConflictResponse(conflict=False)

    proposed_identity = get_channel_bot_identity(
        channel_name,
        single_channel_config,
    )
    if proposed_identity is None:
        return ChannelConflictResponse(conflict=False)

    current_agent = await get_agent_for_request(request)
    current_agent_id = current_agent.agent_id
    manager = request.app.state.multi_agent_manager
    conflicts = []

    for agent_id, workspace in list(manager.agents.items()):
        workspace_agent_id = getattr(workspace, "agent_id", agent_id)
        if current_agent_id in (agent_id, workspace_agent_id):
            continue

        channel_manager = getattr(workspace, "channel_manager", None)
        running_channels = getattr(channel_manager, "channels", ())
        if not any(
            getattr(channel, "channel", None) == channel_name
            for channel in running_channels
        ):
            continue

        other_config = get_channel_config(
            getattr(workspace.config, "channels", None),
            channel_name,
        )
        if (
            get_channel_bot_identity(
                channel_name,
                other_config,
            )
            != proposed_identity
        ):
            continue

        agent_name = getattr(workspace.config, "name", "") or agent_id
        conflicts.append(
            ChannelConflictAgent(
                agent_id=agent_id,
                agent_name=str(agent_name),
            ),
        )

    conflicts.sort(key=lambda item: item.agent_id)
    return ChannelConflictResponse(
        conflict=bool(conflicts),
        agents=conflicts,
    )


@router.put(
    "/channels/{channel_name}",
    response_model=dict,
    summary="Update channel config",
    description="Update configuration for a specific channel by name",
)
async def put_channel(
    request: Request,
    channel_name: str = Path(
        ...,
        description="Name of the channel to update",
        min_length=1,
    ),
    single_channel_config: dict = Body(
        ...,
        description="Updated channel configuration",
    ),
) -> dict:
    """Update a specific channel config by name."""
    from ...config.config import load_agent_config, update_agent_config_async
    from ..agent_context import get_agent_for_request

    token = request.headers.get("X-Channel-Auth-Session")
    if token is not None:
        scope = await resolve_channel_management_scope_async(
            request,
            channel_name,
        )
        sessions = getattr(request.app.state, "channel_qrcode_sessions", None)
        if sessions is None:
            raise HTTPException(503, "MANAGEMENT_CLOSED")
        values = deepcopy(single_channel_config)
        if channel_name == "wechat":
            for key in ("bot_token_file", "base_url"):
                values.setdefault(key, scope.config.get(key, ""))
        validated = await _validated_channel_config_async(channel_name, values)
        channel_config = ChannelConfig.model_validate(
            {channel_name: validated},
        ).model_dump(mode="json")[channel_name]

        def apply_channel(candidate):
            root = load_config()
            profile = root.agents.profiles.get(scope.workspace_id)
            if (
                profile is None
                or not profile.enabled
                or FilePath(profile.workspace_dir).expanduser().resolve()
                != scope.workspace_dir
            ):
                raise HTTPException(403, "Channel scope changed")
            current = (
                candidate.channels.model_dump() if candidate.channels else {}
            )
            if current.get(channel_name) != scope.config:
                raise HTTPException(409, "Channel configuration changed")
            candidate.channels = ChannelConfig.model_validate(
                {**current, channel_name: channel_config},
            )

        async def persist():
            saved = await update_agent_config_async(
                scope.workspace_id,
                apply_channel,
            )
            schedule_agent_reload(request, scope.workspace_id)
            return saved.channels.model_dump(mode="json")[channel_name]

        try:
            return await sessions.save_confirmed(
                scope,
                token,
                channel_config,
                persist,
            )
        except ManagementError as error:
            raise _management_http_error(error) from None

    agent = await get_agent_for_request(request)
    persisted = await run_sync_io(load_agent_config, agent.agent_id)
    current = persisted.channels.model_dump() if persisted.channels else {}
    available = await get_configurable_channel_catalog_async(
        current,
    )
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )

    channel_config = await _validated_channel_config_async(
        channel_name,
        single_channel_config,
    )
    changed = current.get(channel_name) != channel_config
    sessions = getattr(request.app.state, "channel_qrcode_sessions", None)
    async with AsyncExitStack() as stack:
        if sessions is not None and changed:
            await stack.enter_async_context(
                sessions.operation_guard(agent.agent_id, channel_name),
            )
        saved_channels = await _save_channel_updates_async(
            request,
            agent.agent_id,
            {channel_name: channel_config},
        )

    return saved_channels.model_dump(mode="json")[channel_name]


@router.get(
    "/acp",
    response_model=ACPConfig,
    summary="Get ACP config",
    description="Retrieve ACP configuration for current agent",
)
async def get_acp_config(request: Request) -> ACPConfig:
    """Return ACP config for the current agent."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    return agent.config.acp or ACPConfig()


@router.put(
    "/acp",
    response_model=ACPConfig,
    summary="Update ACP config",
    description="Update ACP configuration for current agent",
)
async def put_acp_config(
    request: Request,
    acp_config: ACPConfig = Body(
        ...,
        description="Complete ACP configuration",
    ),
) -> ACPConfig:
    """Update ACP config for the current agent."""
    from ...config.config import save_agent_config
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    agent.config.acp = acp_config
    save_agent_config(agent.agent_id, agent.config)
    schedule_agent_reload(request, agent.agent_id)
    return agent.config.acp


@router.get(
    "/acp/node-runtime",
    response_model=ACPNodeRuntimeStatus,
    summary="Get ACP Node runtime",
    description="Return configured and detected Node runtimes for ACP",
)
async def get_acp_node_runtime() -> ACPNodeRuntimeStatus:
    """Return global ACP Node runtime status."""
    node_path = load_config().acp.node_path
    return await asyncio.to_thread(get_node_runtime_status, node_path)


@router.put(
    "/acp/node-runtime",
    response_model=ACPNodeRuntimeStatus,
    summary="Update ACP Node runtime",
    description="Update the global Node runtime used by ACP subprocesses",
)
async def put_acp_node_runtime(
    body: ACPNodeRuntimeUpdate = Body(...),
) -> ACPNodeRuntimeStatus:
    """Update global ACP Node runtime path."""
    node_path = body.node_path.strip()
    if node_path:
        candidate = await asyncio.to_thread(resolve_node_runtime, node_path)
        if not candidate.available:
            raise HTTPException(
                status_code=400,
                detail={
                    "reason_code": candidate.reason_code,
                    "reason": candidate.reason,
                },
            )

    def apply_node_path(config: Any) -> None:
        config.acp.node_path = node_path

    config = await run_sync_io(mutate_config, apply_node_path)
    return await asyncio.to_thread(
        get_node_runtime_status,
        config.acp.node_path,
    )


@router.get(
    "/acp/{agent_name}",
    response_model=ACPAgentConfig,
    summary="Get ACP agent config",
    description="Retrieve ACP configuration for a specific ACP agent",
)
async def get_acp_agent_config(
    request: Request,
    agent_name: str = Path(
        ...,
        description="Name of the ACP agent to retrieve",
        min_length=1,
    ),
) -> ACPAgentConfig:
    """Return config for one ACP agent."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    acp_config = agent.config.acp or ACPConfig()
    acp_agent = acp_config.agents.get(agent_name)
    if acp_agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"ACP agent '{agent_name}' not found",
        )
    return acp_agent


@router.put(
    "/acp/{agent_name}",
    response_model=ACPAgentConfig,
    summary="Update ACP agent config",
    description="Update ACP configuration for a specific ACP agent",
)
async def put_acp_agent_config(
    request: Request,
    agent_name: str = Path(
        ...,
        description="Name of the ACP agent to update",
        min_length=1,
    ),
    acp_agent_config: ACPAgentConfig = Body(
        ...,
        description="Updated ACP agent configuration",
    ),
) -> ACPAgentConfig:
    """Update config for one ACP agent."""
    from ...config.config import save_agent_config
    from ..agent_context import get_agent_for_request

    if acp_agent_config.tool_parse_mode not in _ALLOWED_ACP_TOOL_PARSE_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid tool_parse_mode. Allowed values: "
                + ", ".join(sorted(_ALLOWED_ACP_TOOL_PARSE_MODES))
            ),
        )

    agent = await get_agent_for_request(request)
    if agent.config.acp is None:
        agent.config.acp = ACPConfig()

    agent_name = agent_name.strip()
    if not agent_name:
        raise HTTPException(
            status_code=400,
            detail="ACP agent name cannot be empty",
        )

    agent.config.acp.agents[agent_name] = acp_agent_config
    save_agent_config(agent.agent_id, agent.config)
    schedule_agent_reload(request, agent.agent_id)
    return agent.config.acp.agents[agent_name]


@router.get(
    "/heartbeat",
    summary="Get heartbeat config",
    description="Return current heartbeat config (interval, target, etc.)",
)
async def get_heartbeat(request: Request) -> Any:
    """Return effective heartbeat config (from file or default)."""
    from ...config.config import HeartbeatConfig as HeartbeatConfigModel
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    hb = agent.config.heartbeat
    if hb is None:
        # Use default if not configured
        hb = HeartbeatConfigModel()
    return hb.model_dump(mode="json", by_alias=True)


@router.put(
    "/heartbeat",
    summary="Update heartbeat config",
    description="Update heartbeat and hot-reload the scheduler",
)
async def put_heartbeat(
    request: Request,
    body: HeartbeatBody = Body(..., description="Heartbeat configuration"),
) -> Any:
    """Update heartbeat config and reschedule the heartbeat job."""
    from ...config.config import save_agent_config
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    hb = HeartbeatConfig(
        enabled=body.enabled,
        every=body.every,
        target=body.target,
        timeout_seconds=body.timeout_seconds,
        active_hours=body.active_hours,
    )
    agent.config.heartbeat = hb
    save_agent_config(agent.agent_id, agent.config)

    # Reschedule heartbeat (async, non-blocking)
    async def reschedule_in_background():
        try:
            if agent.cron_manager is not None:
                await agent.cron_manager.reschedule_heartbeat()
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"Background reschedule failed: {e}",
            )

    asyncio.create_task(reschedule_in_background())

    return hb.model_dump(mode="json", by_alias=True)


@router.post(
    "/heartbeat/run",
    summary="Run heartbeat now",
    description="Trigger one heartbeat execution immediately",
)
async def run_heartbeat_now(request: Request) -> Any:
    """Trigger one heartbeat run in background for quick testing."""
    import logging

    from ..agent_context import get_agent_for_request
    from ..crons.heartbeat import run_heartbeat_once

    workspace = await get_agent_for_request(request)

    async def _run_once_bg() -> None:
        try:
            await run_heartbeat_once(
                workspace=workspace,
                channel_manager=workspace.channel_manager,
                agent_id=workspace.agent_id,
                workspace_dir=workspace.workspace_dir,
            )
        except Exception as e:  # pylint: disable=broad-except
            logging.getLogger(__name__).exception(
                "manual heartbeat run failed: %s",
                e,
            )

    asyncio.create_task(_run_once_bg())
    return {"started": True}


@router.get(
    "/agents/llm-routing",
    response_model=AgentsLLMRoutingConfig,
    summary="Get agent LLM routing settings",
)
async def get_agents_llm_routing() -> AgentsLLMRoutingConfig:
    config = load_config()
    return config.agents.llm_routing


@router.put(
    "/agents/llm-routing",
    response_model=AgentsLLMRoutingConfig,
    summary="Update agent LLM routing settings",
)
async def put_agents_llm_routing(
    body: AgentsLLMRoutingConfig = Body(...),
) -> AgentsLLMRoutingConfig:
    def apply_routing(config: Any) -> None:
        config.agents.llm_routing = body

    await run_sync_io(mutate_config, apply_routing)
    return body


# ── User Timezone ────────────────────────────────────────────────────


@router.get(
    "/user-timezone",
    summary="Get user timezone",
    description="Return the configured user IANA timezone",
)
async def get_user_timezone() -> dict:
    config = load_config()
    return {"timezone": config.user_timezone}


@router.put(
    "/user-timezone",
    summary="Update user timezone",
    description="Set the user IANA timezone",
)
async def put_user_timezone(
    body: dict = Body(..., description="Body with 'timezone' key"),
) -> dict:
    tz = body.get("timezone", "").strip()
    if not tz:
        raise HTTPException(status_code=400, detail="timezone is required")
    resolved = normalize_tz(tz)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid IANA timezone: {tz!r}",
        )

    def apply_timezone(config: Any) -> None:
        config.user_timezone = resolved

    await run_sync_io(mutate_config, apply_timezone)
    return {"timezone": resolved}


# ── Security / Tool Guard ────────────────────────────────────────────


@router.get(
    "/security/tool-guard",
    response_model=ToolGuardConfig,
    summary="Get tool guard settings",
)
async def get_tool_guard() -> ToolGuardConfig:
    config = load_config()
    return config.security.tool_guard


@router.put(
    "/security/tool-guard",
    response_model=ToolGuardConfig,
    summary="Update tool guard settings",
)
async def put_tool_guard(
    body: ToolGuardConfig = Body(...),
) -> ToolGuardConfig:
    def apply_tool_guard(config: Any) -> None:
        config.security.tool_guard = body

    await run_sync_io(mutate_config, apply_tool_guard)

    from ...security.tool_guard.engine import get_guard_engine

    engine = get_guard_engine()
    engine.enabled = body.enabled
    engine.reload_rules()

    return body


@router.get(
    "/security/tool-guard/builtin-rules",
    response_model=List[ToolGuardRuleConfig],
    summary="List built-in guard rules from YAML files",
)
async def get_builtin_rules() -> List[ToolGuardRuleConfig]:
    from ...security.tool_guard.guardians.rule_guardian import (
        load_rules_from_directory,
    )

    rules = load_rules_from_directory()
    return [
        ToolGuardRuleConfig(
            id=r.id,
            tools=r.tools,
            params=r.params,
            category=r.category.value,
            severity=r.severity.value,
            patterns=r.patterns,
            exclude_patterns=r.exclude_patterns,
            description=r.description,
            remediation=r.remediation,
        )
        for r in rules
    ]


# ── Security / Sandbox ───────────────────────────────────────────────


class SandboxSettingBody(BaseModel):
    """Global governance sandbox switch (``security.sandbox_enabled``)."""

    enabled: bool = Field(
        default=False,
        description=(
            "When True, shell tools with no matching rule run inside the "
            "sandbox without prompting. When False (default), such calls "
            "run directly without the sandbox (no prompt)."
        ),
    )


class SandboxStatusResponse(BaseModel):
    """Sandbox config + runtime effective status."""

    enabled: bool = Field(
        description="The configured value of security.sandbox_enabled.",
    )
    effective: bool = Field(
        description=(
            "Whether the sandbox is actually active this session. "
            "May be False even when enabled=True (e.g. non-admin on Windows)."
        ),
    )
    reason: Optional[str] = Field(
        default=None,
        description=(
            "When effective != enabled, explains why. "
            "None when effective == enabled."
        ),
    )


async def _sandbox_effective_status(
    enabled: bool,
) -> tuple[bool, Optional[str]]:
    """Return (effective, reason) for the sandbox setting.

    Checks both platform-level permissions (admin on Windows) and
    actual sandbox capability availability.

    The capability probe runs in a thread-pool worker via
    ``asyncio.to_thread`` so that the (potentially blocking) first
    call never stalls the async event loop.  Subsequent calls hit
    the ``lru_cache`` and return instantly.
    """
    if not enabled:
        return False, None

    # Check if sandbox backend is actually available on this platform.
    # probe_sandbox_support() is lru_cache'd; the first call may block
    # (subprocess.run on Linux), so we offload it to a thread.
    from ...sandbox import probe_sandbox_support

    capability = await asyncio.to_thread(probe_sandbox_support)
    if not capability.supported:
        return False, "unsupported"

    # Check platform-level permissions — on Windows, an unelevated
    # sandbox is available but offers weaker isolation than the
    # elevated (admin) sandbox.
    from ...utils.platform import is_windows_admin

    if not is_windows_admin():
        return True, "unelevated"

    return True, None


@router.get(
    "/security/sandbox",
    response_model=SandboxStatusResponse,
    summary="Get global sandbox switch",
)
async def get_sandbox_setting(
    enabled: Optional[bool] = Query(
        default=None,
        description=(
            "If provided, compute effective/reason for this proposed value "
            "without persisting it. Useful for the frontend to preview the "
            "runtime status before saving."
        ),
    ),
) -> SandboxStatusResponse:
    config = load_config()
    current_enabled = config.security.sandbox_enabled
    # Use the proposed value if provided, otherwise the current config value.
    target_enabled = enabled if enabled is not None else current_enabled
    effective, reason = await _sandbox_effective_status(target_enabled)
    return SandboxStatusResponse(
        enabled=target_enabled,
        effective=effective,
        reason=reason,
    )


@router.put(
    "/security/sandbox",
    response_model=SandboxStatusResponse,
    summary="Update global sandbox switch",
)
async def put_sandbox_setting(
    body: SandboxSettingBody = Body(...),
) -> SandboxStatusResponse:
    config = await run_sync_io(load_config)
    current_enabled = config.security.sandbox_enabled

    # Idempotent: if the value hasn't changed, return current status
    # without triggering the admin guard. This prevents partial-save
    # issues when the frontend saves other security settings alongside
    # an unchanged sandbox value.
    if body.enabled == current_enabled:
        effective, reason = await _sandbox_effective_status(body.enabled)
        return SandboxStatusResponse(
            enabled=body.enabled,
            effective=effective,
            reason=reason,
        )

    def apply_sandbox(config: Any) -> None:
        config.security.sandbox_enabled = body.enabled

    await run_sync_io(mutate_config, apply_sandbox)
    effective, reason = await _sandbox_effective_status(body.enabled)
    return SandboxStatusResponse(
        enabled=body.enabled,
        effective=effective,
        reason=reason,
    )


# ── Security / Sandbox Deny Paths Protection ─────────────────────────


class DenyPathsProtectionBody(BaseModel):
    """Request body for enabling/disabling deny paths protection."""

    enabled: bool = Field(
        description=(
            "When True, applies deny ACLs on the current user for "
            "configured sensitive paths. When False, removes those ACLs."
        ),
    )


class DenyPathsProtectionResponse(BaseModel):
    """Response with deny paths protection status."""

    active: bool = Field(
        description="Whether deny paths protection is currently active.",
    )
    protected_paths: List[str] = Field(
        default_factory=list,
        description="Paths currently protected with deny ACLs.",
    )
    failed_paths: List[str] = Field(
        default_factory=list,
        description="Paths that failed to have ACLs applied/removed.",
    )
    platform_supported: bool = Field(
        description="Whether this feature is available on the "
        "current platform.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Additional status message.",
    )


@router.get(
    "/security/sandbox/deny-paths-protection",
    response_model=DenyPathsProtectionResponse,
    summary="Get deny paths protection status",
)
async def get_deny_paths_protection() -> DenyPathsProtectionResponse:
    import sys

    if sys.platform != "win32":
        return DenyPathsProtectionResponse(
            active=False,
            protected_paths=[],
            failed_paths=[],
            platform_supported=False,
            message="Deny paths protection via ACLs is only "
            "available on Windows.",
        )

    from ...sandbox.windows_unelevated_sandbox import DenyPathsProtection

    protection = DenyPathsProtection()
    status = protection.status()
    return DenyPathsProtectionResponse(
        active=status["active"],
        protected_paths=status.get("protected_paths", []),
        failed_paths=[],
        platform_supported=True,
    )


@router.put(
    "/security/sandbox/deny-paths-protection",
    response_model=DenyPathsProtectionResponse,
    summary="Enable or disable deny paths protection",
)
async def put_deny_paths_protection(
    body: DenyPathsProtectionBody = Body(...),
) -> DenyPathsProtectionResponse:
    import sys

    if sys.platform != "win32":
        return DenyPathsProtectionResponse(
            active=False,
            protected_paths=[],
            failed_paths=[],
            platform_supported=False,
            message="Deny paths protection via ACLs is only "
            "available on Windows.",
        )

    from ...governance.policy import DEFAULT_SANDBOX_DENY_PATHS
    from ...sandbox.windows_unelevated_sandbox import DenyPathsProtection

    protection = DenyPathsProtection()
    lock = protection.get_lock()

    async with lock:  # pylint: disable=not-async-context-manager
        if body.enabled:
            result = await asyncio.to_thread(
                protection.enable,
                DEFAULT_SANDBOX_DENY_PATHS,
            )
            return DenyPathsProtectionResponse(
                active=result.get("status") == "enabled"
                or result.get("status") == "already_active",
                protected_paths=result.get("protected_paths", []),
                failed_paths=result.get("failed_paths", []),
                platform_supported=True,
                message=result.get("message"),
            )
        else:
            result = await asyncio.to_thread(protection.disable)
            return DenyPathsProtectionResponse(
                active=False,
                protected_paths=[],
                failed_paths=result.get("failed_paths", []),
                platform_supported=True,
            )


# ── Security / File Guard ────────────────────────────────────────────


class FileGuardResponse(BaseModel):
    enabled: bool = True
    paths: List[str] = []
    allow_preview_outside_workspace: bool = False


class FileGuardUpdateBody(BaseModel):
    enabled: Optional[bool] = None
    paths: Optional[List[str]] = None
    allow_preview_outside_workspace: Optional[bool] = None


@router.get(
    "/security/file-guard",
    response_model=FileGuardResponse,
    summary="Get file guard settings",
)
async def get_file_guard() -> FileGuardResponse:
    config = load_config()
    fg = config.security.file_guard
    from ...security.tool_guard.guardians.file_guardian import (
        ensure_file_guard_paths,
    )

    paths = ensure_file_guard_paths(fg.sensitive_files or [])
    return FileGuardResponse(
        enabled=fg.enabled,
        paths=paths,
        allow_preview_outside_workspace=fg.allow_preview_outside_workspace,
    )


@router.put(
    "/security/file-guard",
    response_model=FileGuardResponse,
    summary="Update file guard settings",
)
async def put_file_guard(
    body: FileGuardUpdateBody,
) -> FileGuardResponse:
    def apply_file_guard(config: Any) -> None:
        file_guard = config.security.file_guard
        if body.enabled is not None:
            file_guard.enabled = body.enabled
        if body.paths is not None:
            from ...security.tool_guard.guardians.file_guardian import (
                ensure_file_guard_paths,
            )

            file_guard.sensitive_files = ensure_file_guard_paths(body.paths)
        if body.allow_preview_outside_workspace is not None:
            file_guard.allow_preview_outside_workspace = (
                body.allow_preview_outside_workspace
            )

    config = await run_sync_io(mutate_config, apply_file_guard)
    fg = config.security.file_guard

    from ...security.tool_guard.engine import get_guard_engine

    engine = get_guard_engine()
    engine.reload_rules()

    return FileGuardResponse(
        enabled=fg.enabled,
        paths=fg.sensitive_files,
        allow_preview_outside_workspace=fg.allow_preview_outside_workspace,
    )


# ── Security / Skill Scanner ────────────────────────────────────────


@router.get(
    "/security/skill-scanner",
    response_model=SkillScannerConfig,
    summary="Get skill scanner settings",
)
async def get_skill_scanner() -> SkillScannerConfig:
    config = load_config()
    return config.security.skill_scanner


@router.put(
    "/security/skill-scanner",
    response_model=SkillScannerConfig,
    summary="Update skill scanner settings",
)
async def put_skill_scanner(
    body: SkillScannerConfig = Body(...),
) -> SkillScannerConfig:
    def apply_skill_scanner(config: Any) -> None:
        config.security.skill_scanner = body

    await run_sync_io(mutate_config, apply_skill_scanner)
    return body


@router.get(
    "/security/skill-scanner/blocked-history",
    summary="Get blocked skills history",
)
async def get_blocked_history() -> list:
    from ...security.skill_scanner import get_blocked_history as _get_history

    records = _get_history()
    return [r.to_dict() for r in records]


@router.delete(
    "/security/skill-scanner/blocked-history",
    summary="Clear all blocked skills history",
)
async def delete_blocked_history() -> dict:
    from ...security.skill_scanner import clear_blocked_history

    clear_blocked_history()
    return {"cleared": True}


@router.delete(
    "/security/skill-scanner/blocked-history/{index}",
    summary="Remove a single blocked history entry",
)
async def delete_blocked_entry(
    index: int = Path(..., ge=0),
) -> dict:
    from ...security.skill_scanner import remove_blocked_entry

    ok = remove_blocked_entry(index)
    if not ok:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"removed": True}


class WhitelistAddRequest(BaseModel):
    skill_name: str
    content_hash: str = ""


@router.post(
    "/security/skill-scanner/whitelist",
    summary="Add a skill to the whitelist",
)
async def add_to_whitelist(
    body: WhitelistAddRequest = Body(...),
) -> dict:
    skill_name = body.skill_name.strip()
    content_hash = body.content_hash
    if not skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")

    def add_entry(config: Any) -> None:
        scanner_cfg = config.security.skill_scanner
        for entry in scanner_cfg.whitelist:
            if entry.skill_name == skill_name:
                raise HTTPException(
                    status_code=409,
                    detail=f"Skill '{skill_name}' is already whitelisted",
                )
        scanner_cfg.whitelist.append(
            SkillScannerWhitelistEntry(
                skill_name=skill_name,
                content_hash=content_hash,
                added_at=datetime.now(timezone.utc).isoformat(),
            ),
        )

    await run_sync_io(mutate_config, add_entry)
    return {"whitelisted": True, "skill_name": skill_name}


@router.delete(
    "/security/skill-scanner/whitelist/{skill_name}",
    summary="Remove a skill from the whitelist",
)
async def remove_from_whitelist(
    skill_name: str = Path(..., min_length=1),
) -> dict:
    def remove_entry(config: Any) -> None:
        scanner_cfg = config.security.skill_scanner
        original_len = len(scanner_cfg.whitelist)
        scanner_cfg.whitelist = [
            entry
            for entry in scanner_cfg.whitelist
            if entry.skill_name != skill_name
        ]
        if len(scanner_cfg.whitelist) == original_len:
            raise HTTPException(
                status_code=404,
                detail=f"Skill '{skill_name}' not found in whitelist",
            )

    await run_sync_io(mutate_config, remove_entry)
    return {"removed": True, "skill_name": skill_name}


# ── Security / Allow No Auth Hosts ────────────────────────────────────


class AllowNoAuthHostsResponse(BaseModel):
    """Response model for allow_no_auth_hosts configuration."""

    hosts: List[str] = Field(
        description="List of IP addresses allowed without authentication",
    )


class AllowNoAuthHostsUpdateBody(BaseModel):
    """Request body for updating allow_no_auth_hosts configuration."""

    hosts: List[str] = Field(
        description="List of IP addresses allowed without authentication",
    )


@router.get(
    "/security/allow-no-auth-hosts",
    response_model=AllowNoAuthHostsResponse,
    summary="Get allow no auth hosts configuration",
)
async def get_allow_no_auth_hosts() -> AllowNoAuthHostsResponse:
    """Get the list of IP addresses allowed without authentication."""
    config = load_config()
    return AllowNoAuthHostsResponse(
        hosts=config.security.allow_no_auth_hosts,
    )


@router.put(
    "/security/allow-no-auth-hosts",
    response_model=AllowNoAuthHostsResponse,
    summary="Update allow no auth hosts configuration",
)
async def put_allow_no_auth_hosts(
    body: AllowNoAuthHostsUpdateBody = Body(...),
) -> AllowNoAuthHostsResponse:
    """Update the list of IP addresses allowed without authentication.

    Validates and normalizes each IP address:
    - Strips whitespace
    - Removes empty strings
    - Deduplicates entries
    - Validates as literal IPv4/IPv6 using ipaddress module
    - Returns 400 on invalid IP addresses
    """
    import ipaddress

    # Normalize and validate IP addresses
    normalized_hosts = []
    seen = set()
    invalid_ips = []

    for host in body.hosts:
        # Strip whitespace
        host = host.strip()

        # Skip empty strings
        if not host:
            continue

        # Validate IP address format
        try:
            # This validates and normalizes the IP address
            ip_obj = ipaddress.ip_address(host)
            # Use the compressed string representation
            normalized_ip = str(ip_obj)

            # Deduplicate
            if normalized_ip not in seen:
                seen.add(normalized_ip)
                normalized_hosts.append(normalized_ip)
        except ValueError:
            invalid_ips.append(host)

    # Return 400 if any invalid IP addresses were provided
    if invalid_ips:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid IP address(es): {', '.join(invalid_ips)}. "
                "Only literal IPv4/IPv6 addresses are allowed."
            ),
        )

    def apply_hosts(config: Any) -> None:
        config.security.allow_no_auth_hosts = normalized_hosts

    await run_sync_io(mutate_config, apply_hosts)
    return AllowNoAuthHostsResponse(hosts=normalized_hosts)
