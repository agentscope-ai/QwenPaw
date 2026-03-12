# -*- coding: utf-8 -*-

from typing import Any, List

from fastapi import APIRouter, Body, HTTPException, Path, Request

from ...config import (
    load_config,
    save_config,
    get_heartbeat_config,
    ChannelConfig,
    ChannelConfigUnion,
    get_available_channels,
    ToolGuardConfig,
    ToolGuardRuleConfig,
)
from ..channels.registry import BUILTIN_CHANNEL_KEYS
from ...config.config import AgentsLLMRoutingConfig, HeartbeatConfig

from .schemas_config import HeartbeatBody

router = APIRouter(prefix="/config", tags=["config"])


@router.get(
    "/channels",
    summary="List all channels",
    description="Retrieve configuration for all available channels",
)
async def list_channels() -> dict:
    """List all channel configs (filtered by available channels)."""
    config = load_config()
    available = get_available_channels()

    # Get all channel configs from model_dump and __pydantic_extra__
    all_configs = config.channels.model_dump()
    extra = getattr(config.channels, "__pydantic_extra__", None) or {}
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
    channels_config: ChannelConfig = Body(
        ...,
        description="Complete channel configuration",
    ),
) -> ChannelConfig:
    """Update all channel configs."""
    config = load_config()
    config.channels = channels_config
    save_config(config)
    return channels_config


@router.get(
    "/channels/{channel_name}",
    response_model=ChannelConfigUnion,
    summary="Get channel config",
    description="Retrieve configuration for a specific channel by name",
)
async def get_channel(
    channel_name: str = Path(
        ...,
        description="Name of the channel to retrieve",
        min_length=1,
    ),
) -> ChannelConfigUnion:
    """Get a specific channel config by name."""
    available = get_available_channels()
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )
    config = load_config()
    single_channel_config = getattr(config.channels, channel_name, None)
    if single_channel_config is None:
        extra = getattr(config.channels, "__pydantic_extra__", None) or {}
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
    available = get_available_channels()
    if channel_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found",
        )
    config = load_config()

    # Create the appropriate config object based on channel_name
    if channel_name == "telegram":
        from ...config.config import TelegramConfig

        channel_config = TelegramConfig(**single_channel_config)
    elif channel_name == "dingtalk":
        from ...config.config import DingTalkConfig

        channel_config = DingTalkConfig(**single_channel_config)
    elif channel_name == "discord":
        from ...config.config import DiscordConfig

        channel_config = DiscordConfig(**single_channel_config)
    elif channel_name == "feishu":
        from ...config.config import FeishuConfig

        channel_config = FeishuConfig(**single_channel_config)
    elif channel_name == "qq":
        from ...config.config import QQConfig

        channel_config = QQConfig(**single_channel_config)
    elif channel_name == "imessage":
        from ...config.config import IMessageChannelConfig

        channel_config = IMessageChannelConfig(**single_channel_config)
    elif channel_name == "console":
        from ...config.config import ConsoleConfig

        channel_config = ConsoleConfig(**single_channel_config)
    elif channel_name == "voice":
        from ...config.config import VoiceChannelConfig

        channel_config = VoiceChannelConfig(**single_channel_config)
    else:
        # For custom channels, just use the dict
        channel_config = single_channel_config

    # Allow setting extra (plugin) channel config
    setattr(config.channels, channel_name, channel_config)
    save_config(config)
    return channel_config


@router.get(
    "/heartbeat",
    summary="Get heartbeat config",
    description="Return current heartbeat config (interval, target, etc.)",
)
async def get_heartbeat() -> Any:
    """Return effective heartbeat config (from file or default)."""
    hb = get_heartbeat_config()
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
    config = load_config()
    hb = HeartbeatConfig(
        enabled=body.enabled,
        every=body.every,
        target=body.target,
        active_hours=body.active_hours,
    )
    config.agents.defaults.heartbeat = hb
    save_config(config)

    cron_manager = getattr(request.app.state, "cron_manager", None)
    if cron_manager is not None:
        await cron_manager.reschedule_heartbeat()

    return hb.model_dump(mode="json", by_alias=True)


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
    config = load_config()
    config.agents.llm_routing = body
    save_config(config)
    return body


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
