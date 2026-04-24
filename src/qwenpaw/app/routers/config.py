# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ..utils import schedule_agent_reload
from ...config import (
    load_config,
    save_config,
    ChannelConfig,
    ChannelConfigUnion,
    get_available_channels,
    ToolGuardConfig,
    ToolGuardRuleConfig,
)
from ..channels.registry import BUILTIN_CHANNEL_KEYS
from ...config.config import (
    AgentsLLMRoutingConfig,
    ConsoleConfig,
    DingTalkConfig,
    DiscordConfig,
    FeishuConfig,
    HeartbeatConfig,
    IMessageChannelConfig,
    MatrixConfig,
    MattermostConfig,
    MQTTConfig,
    QQConfig,
    SIPChannelConfig,
    SkillScannerConfig,
    SkillScannerWhitelistEntry,
    TelegramConfig,
    VoiceChannelConfig,
    WecomConfig,
)
from ...agents.acp.core import ACPConfig, ACPAgentConfig

from .schemas_config import (
    ChannelHealthResponse,
    ChannelRestartResponse,
    HeartbeatBody,
)
from ..channels.qrcode_auth_handler import (
    QRCODE_AUTH_HANDLERS,
    generate_qrcode_image,
)

router = APIRouter(prefix="/config", tags=["config"])


_CHANNEL_CONFIG_CLASS_MAP = {
    "telegram": TelegramConfig,
    "dingtalk": DingTalkConfig,
    "discord": DiscordConfig,
    "feishu": FeishuConfig,
    "qq": QQConfig,
    "imessage": IMessageChannelConfig,
    "console": ConsoleConfig,
    "voice": VoiceChannelConfig,
    "sip": SIPChannelConfig,
    "mattermost": MattermostConfig,
    "mqtt": MQTTConfig,
    "matrix": MatrixConfig,
    "wecom": WecomConfig,
}
_ALLOWED_ACP_TOOL_PARSE_MODES = {
    "call_title",
    "update_detail",
    "call_detail",
}


def _is_local_provider(provider) -> bool:
    from urllib.parse import urlparse

    if getattr(provider, "is_local", False):
        return True
    base_url = getattr(provider, "base_url", "") or ""
    if not base_url:
        return False
    try:
        hostname = urlparse(base_url).hostname or ""
    except Exception:
        return False
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _validate_routing_config(body: AgentsLLMRoutingConfig) -> None:
    from ...config.config import has_configured_model_slot
    from ...providers import ProviderManager

    selected_slot = body.local if body.mode == "local_first" else body.cloud
    if body.enabled and not has_configured_model_slot(selected_slot):
        raise HTTPException(
            status_code=400,
            detail="Configure the selected mode slot before enabling routing.",
        )

    if (
        body.enabled
        and has_configured_model_slot(body.local)
        and has_configured_model_slot(body.cloud)
        and body.local.provider_id == body.cloud.provider_id
        and body.local.model == body.cloud.model
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Local and cloud slots must point to different "
                "provider/model pairs."
            ),
        )

    if not body.enabled:
        return

    manager = ProviderManager.get_instance()
    selected_kind = "local" if body.mode == "local_first" else "cloud"

    if not has_configured_model_slot(selected_slot):
        return

    provider = manager.get_provider(selected_slot.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{selected_slot.provider_id}' not found.",
        )
    if not provider.has_model(selected_slot.model):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{selected_slot.model}' not found for provider "
                f"'{selected_slot.provider_id}'."
            ),
        )

    is_local_provider = _is_local_provider(provider)
    if selected_kind == "local" and not is_local_provider:
        raise HTTPException(
            status_code=400,
            detail="Local slot must use a local or loopback provider.",
        )
    if selected_kind == "cloud" and is_local_provider:
        raise HTTPException(
            status_code=400,
            detail="Cloud slot must use a non-local provider.",
        )


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
    available = get_available_channels()

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
    for key in available:
        if key in all_configs:
            channel_data = (
                dict(all_configs[key])
                if isinstance(all_configs[key], dict)
                else all_configs[key]
            )
        else:
            # Channel registered but no config saved yet, use empty default
            channel_data = {"enabled": False, "bot_prefix": ""}
        if isinstance(channel_data, dict):
            channel_data["isBuiltin"] = key in BUILTIN_CHANNEL_KEYS
        result[key] = channel_data

    return result


@router.get(
    "/channels/types",
    summary="List channel types",
    description="Return all available channel type identifiers",
)
async def list_channel_types() -> List[str]:
    """Return available channel type identifiers (env-filtered)."""
    return list(get_available_channels())


@router.put(
    "/channels",
    response_model=ChannelConfig,
    summary="Update all channels",
    description="Update configuration for all channels at once",
)
async def put_channels(
    request: Request,
    channels_config: ChannelConfig = Body(
        ...,
        description="Complete channel configuration",
    ),
) -> ChannelConfig:
    """Update all channel configs."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)
    agent.config.channels = channels_config
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return channels_config


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

    available = get_available_channels()
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
        "Stop and re-start a specific channel" " without restarting the agent"
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
            detail=(f"Failed to restart channel" f" '{channel_name}': {exc}"),
        ) from exc


# ── Unified QR code endpoints for all channels ─────────────────────────────


@router.get(
    "/channels/{channel}/qrcode",
    summary="Get channel authorization QR code",
    description=(
        "Fetch a QR code image (base64 PNG) for the given channel. "
        "Supported channels: " + ", ".join(QRCODE_AUTH_HANDLERS.keys())
    ),
)
async def get_channel_qrcode(request: Request, channel: str) -> dict:
    """Return {qrcode_img, poll_token} for the requested channel."""
    handler = QRCODE_AUTH_HANDLERS.get(channel)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"QR code not supported for channel: {channel}",
        )

    result = await handler.fetch_qrcode(request)
    qrcode_img = generate_qrcode_image(result.scan_url)
    return {"qrcode_img": qrcode_img, "poll_token": result.poll_token}


@router.get(
    "/channels/{channel}/qrcode/status",
    summary="Poll channel QR code authorization status",
)
async def get_channel_qrcode_status(
    request: Request,
    channel: str,
    token: str,
) -> dict:
    """Return {status, credentials} for the requested channel."""
    handler = QRCODE_AUTH_HANDLERS.get(channel)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"QR code not supported for channel: {channel}",
        )

    result = await handler.poll_status(token, request)
    return {"status": result.status, "credentials": result.credentials}


@router.get(
    "/channels/{channel_name}",
    response_model=ChannelConfigUnion,
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
) -> ChannelConfigUnion:
    """Get a specific channel config by name."""
    from ..agent_context import get_agent_for_request

    available = get_available_channels()
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
    return single_channel_config


@router.put(
    "/channels/{channel_name}",
    response_model=ChannelConfigUnion,
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
) -> ChannelConfigUnion:
    """Update a specific channel config by name."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    available = get_available_channels()
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )

    agent = await get_agent_for_request(request)

    # Initialize channels if not exists
    if agent.config.channels is None:
        agent.config.channels = ChannelConfig()

    config_class = _CHANNEL_CONFIG_CLASS_MAP.get(channel_name)
    if config_class is not None:
        channel_config = config_class(**single_channel_config)
    else:
        # For custom channels, just use the dict
        channel_config = single_channel_config

    # Set channel config in agent's config
    setattr(agent.config.channels, channel_name, channel_config)
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return channel_config


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
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)
    agent.config.acp = acp_config
    save_agent_config(agent.agent_id, agent.config)
    schedule_agent_reload(request, agent.agent_id)
    return agent.config.acp


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
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

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
    from ..agent_context import get_agent_for_request
    from ...config.config import HeartbeatConfig as HeartbeatConfigModel

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
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)
    hb = HeartbeatConfig(
        enabled=body.enabled,
        every=body.every,
        target=body.target,
        active_hours=body.active_hours,
    )
    agent.config.heartbeat = hb
    save_agent_config(agent.agent_id, agent.config)

    # Reschedule heartbeat (async, non-blocking)
    import asyncio

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


@router.get(
    "/agents/llm-routing",
    response_model=AgentsLLMRoutingConfig,
    summary="Get agent LLM routing settings",
)
async def get_agents_llm_routing(
    agent_id: str | None = None,
) -> AgentsLLMRoutingConfig:
    """Return effective routing settings.

    Without ``agent_id``, returns the global routing config. With ``agent_id``,
    returns the agent-specific routing config when it is meaningfully set;
    otherwise falls back to the global config. An explicit agent
    ``active_model`` masks inherited global routing, so this endpoint
    reports ``enabled=False`` in that case.
    """
    from ...config.config import (
        has_configured_model_slot,
        load_agent_config,
        routing_has_explicit_override,
    )

    config = load_config()
    if agent_id:
        agent_config = load_agent_config(agent_id)
        routing_cfg = agent_config.llm_routing
        if routing_has_explicit_override(routing_cfg):
            return routing_cfg
        if has_configured_model_slot(agent_config.active_model):
            return AgentsLLMRoutingConfig(enabled=False)
    return config.agents.llm_routing


@router.put(
    "/agents/llm-routing",
    response_model=AgentsLLMRoutingConfig,
    summary="Update agent LLM routing settings",
)
async def put_agents_llm_routing(
    request: Request,
    body: AgentsLLMRoutingConfig = Body(...),
    agent_id: str | None = None,
) -> AgentsLLMRoutingConfig:
    """Update routing settings.

    Without ``agent_id``, updates the global routing config. With ``agent_id``,
    writes the agent-specific routing config and schedules an agent reload.
    """
    from ...config.config import load_agent_config, save_agent_config

    _validate_routing_config(body)

    if agent_id:
        agent_config = load_agent_config(agent_id)
        agent_config.llm_routing = body
        save_agent_config(agent_id, agent_config)
        schedule_agent_reload(request, agent_id)
        return body

    config = load_config()
    config.agents.llm_routing = body
    save_config(config)
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
    config = load_config()
    config.user_timezone = tz
    save_config(config)
    return {"timezone": tz}


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
    config = load_config()
    config.security.tool_guard = body
    save_config(config)

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


# ── Security / File Guard ────────────────────────────────────────────


class FileGuardResponse(BaseModel):
    enabled: bool = True
    paths: List[str] = []


class FileGuardUpdateBody(BaseModel):
    enabled: Optional[bool] = None
    paths: Optional[List[str]] = None


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
    return FileGuardResponse(enabled=fg.enabled, paths=paths)


@router.put(
    "/security/file-guard",
    response_model=FileGuardResponse,
    summary="Update file guard settings",
)
async def put_file_guard(
    body: FileGuardUpdateBody,
) -> FileGuardResponse:
    config = load_config()
    fg = config.security.file_guard

    if body.enabled is not None:
        fg.enabled = body.enabled
    if body.paths is not None:
        from ...security.tool_guard.guardians.file_guardian import (
            ensure_file_guard_paths,
        )

        fg.sensitive_files = ensure_file_guard_paths(body.paths)

    save_config(config)

    from ...security.tool_guard.engine import get_guard_engine

    engine = get_guard_engine()
    engine.reload_rules()

    return FileGuardResponse(
        enabled=fg.enabled,
        paths=fg.sensitive_files,
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
    config = load_config()
    config.security.skill_scanner = body
    save_config(config)
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

    config = load_config()
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
    save_config(config)
    return {"whitelisted": True, "skill_name": skill_name}


@router.delete(
    "/security/skill-scanner/whitelist/{skill_name}",
    summary="Remove a skill from the whitelist",
)
async def remove_from_whitelist(
    skill_name: str = Path(..., min_length=1),
) -> dict:
    config = load_config()
    scanner_cfg = config.security.skill_scanner
    original_len = len(scanner_cfg.whitelist)
    scanner_cfg.whitelist = [
        e for e in scanner_cfg.whitelist if e.skill_name != skill_name
    ]
    if len(scanner_cfg.whitelist) == original_len:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found in whitelist",
        )
    save_config(config)
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

    config = load_config()
    config.security.allow_no_auth_hosts = normalized_hosts
    save_config(config)
    return AllowNoAuthHostsResponse(hosts=normalized_hosts)
