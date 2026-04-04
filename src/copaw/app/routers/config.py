# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel

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
    SkillScannerConfig,
    SkillScannerWhitelistEntry,
    TelegramConfig,
    VoiceChannelConfig,
    WecomConfig,
    WhatsAppConfig,
)

from .schemas_config import HeartbeatBody
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
    "mattermost": MattermostConfig,
    "mqtt": MQTTConfig,
    "matrix": MatrixConfig,
    "wecom": WecomConfig,
    "whatsapp": WhatsAppConfig,
}


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
    paths = fg.sensitive_files
    if not paths:
        from ...security.tool_guard.guardians.file_guardian import (
            _DEFAULT_DENY_DIRS,
        )

        paths = list(_DEFAULT_DENY_DIRS)
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
        fg.sensitive_files = body.paths

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


# ── WhatsApp auth (QR / pair code) ────────────────────────────
# Per-agent pairing state keyed by agent_id.
# CoPaw runs as a single-process server; concurrent pairing for
# different agents is safe because each gets its own state dict.
_whatsapp_pair_states: dict[str, dict] = {}

def _get_wa_pair_state(agent_id: str) -> dict:
    """Get or create per-agent WhatsApp pairing state."""
    if agent_id not in _whatsapp_pair_states:
        _whatsapp_pair_states[agent_id] = {
            "client": None, "code": None, "status": "idle", "qr_data": None, "task": None,
        }
    return _whatsapp_pair_states[agent_id]


def _get_wa_auth_dir(agent) -> str:
    """Resolve WhatsApp auth directory from agent config."""
    wa_cfg = getattr(agent.config.channels, "whatsapp", None)
    auth_dir = "~/.copaw/credentials/whatsapp/default"
    if wa_cfg:
        auth_dir = getattr(wa_cfg, "auth_dir", auth_dir) or auth_dir
    return auth_dir


@router.post(
    "/channels/whatsapp/pair",
    summary="Start WhatsApp pairing",
    description="Start WhatsApp pairing. Returns a pair code to enter on your phone.",
)
async def start_whatsapp_pair(request: Request, phone: str = "") -> dict:
    """Start WhatsApp pair code auth. Requires E.164 phone number."""
    if not phone or not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone number required in E.164 format (e.g. +85212345678)")
    import asyncio
    try:
        from neonize.aioze.client import NewAClient
        from neonize.events import ConnectedEv, QREv
    except ImportError:
        raise HTTPException(status_code=500, detail="neonize not installed")

    from ..agent_context import get_agent_for_request
    agent = await get_agent_for_request(request)
    auth_dir = _get_wa_auth_dir(agent)
    state = _get_wa_pair_state(agent.agent_id)

    from pathlib import Path
    db_path = str(Path(auth_dir).expanduser() / "neonize.db")
    Path(auth_dir).expanduser().mkdir(parents=True, exist_ok=True)

    # Disconnect any existing pairing client for this agent
    old_client = state.get("client")
    if old_client:
        try:
            await old_client.disconnect()
        except Exception:
            pass

    state["status"] = "pairing"
    state["code"] = None
    state["qr_data"] = None

    client = NewAClient(name=db_path)
    state["client"] = client

    @client.event(ConnectedEv)
    async def on_connected(c, evt):
        state["status"] = "connected"

    @client.qr
    async def on_qr(c, qr_bytes):
        import base64
        try:
            import segno
            import io
            qr = segno.make_qr(qr_bytes)
            buf = io.BytesIO()
            qr.save(buf, kind="png", scale=5, border=2)
            state["qr_data"] = base64.b64encode(buf.getvalue()).decode()
        except Exception:
            state["qr_data"] = base64.b64encode(qr_bytes).decode()

    state["task"] = await client.connect()
    await asyncio.sleep(3)

    try:
        code = await client.PairPhone(phone, True)
        state["code"] = code
        state["status"] = "waiting_pair"
        return {"status": "waiting_pair", "pair_code": code, "phone": phone}
    except Exception as e:
        await asyncio.sleep(2)
        if state["qr_data"]:
            return {"status": "waiting_qr", "qr_image": state["qr_data"]}
        return {"status": "error", "detail": str(e)}


@router.get(
    "/channels/whatsapp/pair/status",
    summary="Check WhatsApp pairing status",
)
async def check_whatsapp_pair_status(request: Request) -> dict:
    """Check current WhatsApp pairing status."""
    from ..agent_context import get_agent_for_request
    agent = await get_agent_for_request(request)
    state = _get_wa_pair_state(agent.agent_id)
    result = {"status": state["status"]}
    if state["code"]:
        result["pair_code"] = state["code"]
    if state["qr_data"]:
        result["qr_image"] = state["qr_data"]
    return result


@router.post(
    "/channels/whatsapp/pair/stop",
    summary="Stop WhatsApp pairing",
)
async def stop_whatsapp_pair(request: Request) -> dict:
    """Stop the WhatsApp pairing process."""
    from ..agent_context import get_agent_for_request
    agent = await get_agent_for_request(request)
    state = _get_wa_pair_state(agent.agent_id)
    client = state.get("client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    state.update({"client": None, "code": None, "status": "idle", "qr_data": None, "task": None})
    return {"status": "stopped"}


@router.post(
    "/channels/whatsapp/qrcode",
    summary="Get WhatsApp QR code for linking",
)
async def get_whatsapp_qrcode(request: Request) -> dict:
    """Start WhatsApp QR auth. Returns QR code image for scanning."""
    import asyncio
    import base64
    import io
    try:
        from neonize.aioze.client import NewAClient
        from neonize.events import ConnectedEv
        import segno
    except ImportError:
        raise HTTPException(status_code=500, detail="neonize or segno not installed")

    from ..agent_context import get_agent_for_request
    agent = await get_agent_for_request(request)
    auth_dir = _get_wa_auth_dir(agent)
    state = _get_wa_pair_state(agent.agent_id)

    from pathlib import Path
    db_path = str(Path(auth_dir).expanduser() / "neonize.db")
    Path(auth_dir).expanduser().mkdir(parents=True, exist_ok=True)

    qr_ready = asyncio.Event()
    qr_result = {"image": None}

    client = NewAClient(name=db_path)
    state["client"] = client
    state["status"] = "waiting_qr"

    @client.event(ConnectedEv)
    async def on_connected(c, evt):
        state["status"] = "connected"

    @client.qr
    async def on_qr(c, qr_bytes):
        try:
            qr = segno.make_qr(qr_bytes)
            buf = io.BytesIO()
            qr.save(buf, kind="png", scale=6, border=2)
            qr_result["image"] = base64.b64encode(buf.getvalue()).decode()
            qr_ready.set()
        except Exception:
            qr_result["image"] = None
            qr_ready.set()

    state["task"] = await client.connect()

    try:
        await asyncio.wait_for(qr_ready.wait(), timeout=15)
    except asyncio.TimeoutError:
        pass

    if qr_result["image"]:
        state["qr_data"] = qr_result["image"]
        return {"status": "waiting_qr", "qr_image": qr_result["image"]}
    else:
        return {"status": "error", "detail": "QR code not generated"}


@router.post(
    "/channels/whatsapp/unbind",
    summary="Unbind WhatsApp session",
    description="Delete the WhatsApp session database so the next connection requires re-pairing.",
)
async def unbind_whatsapp(request: Request) -> dict:
    """Delete neonize.db to force re-authentication on next start."""
    from pathlib import Path as _P

    from ..agent_context import get_agent_for_request
    agent = await get_agent_for_request(request)
    auth_dir = _get_wa_auth_dir(agent)
    state = _get_wa_pair_state(agent.agent_id)

    db_path = _P(auth_dir).expanduser() / "neonize.db"
    if db_path.exists():
        db_path.unlink()
        state.update({"client": None, "code": None, "status": "idle", "qr_data": None, "task": None})
        return {"status": "unbound", "detail": "Session deleted. Restart CoPaw to re-pair."}
    return {"status": "idle", "detail": "No session found."}


@router.get(
    "/channels/whatsapp/status",
    summary="Get WhatsApp connection status",
)
async def get_whatsapp_status(request: Request) -> dict:
    """Check if WhatsApp is linked."""
    try:
        from pathlib import Path
        from ..agent_context import get_agent_for_request
        agent = await get_agent_for_request(request)
        auth_dir = _get_wa_auth_dir(agent)
        db_path = Path(auth_dir).expanduser() / "neonize.db"
        if not db_path.exists():
            return {"linked": False, "phone": None}
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute("SELECT * FROM whatsmeow_device LIMIT 1").fetchall()
            if rows:
                return {"linked": True, "phone": "linked"}
            return {"linked": False, "phone": None}
        except Exception:
            return {"linked": False, "phone": None}
        finally:
            conn.close()
    except Exception as e:
        return {"linked": False, "error": str(e)}
