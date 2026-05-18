# -*- coding: utf-8 -*-
"""REST API endpoints for A2A remote agent management (per-agent scoped).

Endpoints:
    GET    /a2a/agents           – list registered agents for current agent
    POST   /a2a/agents           – register (discover + connect)
    DELETE /a2a/agents/{alias}   – disconnect and remove
    POST   /a2a/agents/{alias}/refresh – re-fetch Agent Card

All endpoints are scoped to the current QwenPaw agent via ``X-Agent-Id``
header, mirroring MCP/ACP configuration patterns.  Persistent storage
uses ``workspaces/{agent_id}/a2a_config.json``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/a2a", tags=["a2a"])

# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class RegisterRequest(BaseModel):
    url: str = Field(..., description="Remote A2A Agent base URL")
    alias: Optional[str] = Field(None, description="Human-readable alias")
    auth_type: Optional[str] = Field(
        "",
        description="bearer | api_key | gateway | ''",
    )
    auth_token: Optional[str] = Field(
        "",
        description="Token/key value (not needed for gateway)",
    )
    gateway_config: Optional[dict] = Field(
        None,
        description="Gateway-specific config overrides",
    )


class AgentEntryResponse(BaseModel):
    url: str
    alias: str = ""
    auth_type: str = ""
    status: str = ""
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    skills: Optional[list] = None
    interfaces: Optional[list] = None
    capabilities: Optional[dict] = None
    error: Optional[str] = None


class AgentsListResponse(BaseModel):
    agents: list[AgentEntryResponse]


# ------------------------------------------------------------------
# Per-agent persistent config helpers
# ------------------------------------------------------------------

_A2A_CONFIG_FILENAME = "a2a_config.json"


async def _get_workspace_dir(request: Request) -> Path:
    """Resolve workspace directory for the current agent via X-Agent-Id."""
    from qwenpaw.app.agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    return agent.workspace_dir


def _config_path(workspace_dir: Path) -> Path:
    return workspace_dir / _A2A_CONFIG_FILENAME


def _load_config(workspace_dir: Path) -> dict[str, dict]:
    """Load per-agent A2A config: {alias -> registration_info}."""
    path = _config_path(workspace_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("agents", {})
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _save_config(workspace_dir: Path, agents: dict[str, dict]) -> None:
    """Persist per-agent A2A config."""
    path = _config_path(workspace_dir)
    path.write_text(
        json.dumps({"agents": agents}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------


def _get_manager():
    from modules.a2a.client_manager import get_a2a_manager

    return get_a2a_manager()


def _make_alias(url: str, alias: str | None) -> str:
    """Derive alias: explicit alias, or sanitised URL host."""
    if alias:
        return alias.strip()
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or url


def _build_entry_response(
    reg_info: dict,
    card_info: dict | None,
    error: str | None = None,
) -> AgentEntryResponse:
    """Merge registry info and live card info into one response."""
    data: dict = {
        "url": reg_info["url"],
        "alias": reg_info["alias"],
        "auth_type": reg_info.get("auth_type", ""),
    }
    if card_info:
        data["status"] = card_info.get("status", "connected")
        data["name"] = card_info.get("name")
        data["description"] = card_info.get("description")
        data["version"] = card_info.get("version")
        data["skills"] = card_info.get("skills")
        data["interfaces"] = card_info.get("interfaces")
        data["capabilities"] = card_info.get("capabilities")
    else:
        data["status"] = "disconnected"
    if error:
        data["error"] = error
        data["status"] = "error"
    return AgentEntryResponse(**data)


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="List A2A agents",
)
async def list_agents(
    request: Request,
    active: bool = False,
) -> AgentsListResponse:
    ws_dir = await _get_workspace_dir(request)
    agents_cfg = _load_config(ws_dir)
    manager = _get_manager()

    result: list[AgentEntryResponse] = []
    for alias, reg in agents_cfg.items():
        reg["alias"] = alias
        card_info = await manager.get_card_info(reg["url"])
        if not card_info and active:
            try:
                card_info = await manager.connect(
                    agent_url=reg["url"],
                    auth_type=reg.get("auth_type", ""),
                    auth_token=reg.get("auth_token", ""),
                    gateway_config=reg.get("gateway_config"),
                )
            except Exception as exc:
                logger.debug("active probe failed for %s: %s", reg["url"], exc)
        entry = _build_entry_response(reg, card_info)
        if not active or entry.status == "connected":
            result.append(entry)
    return AgentsListResponse(agents=result)


@router.post(
    "/agents",
    response_model=AgentEntryResponse,
    summary="Register A2A agent",
)
async def register_agent(
    request: Request,
    body: RegisterRequest,
) -> AgentEntryResponse:
    ws_dir = await _get_workspace_dir(request)
    agents_cfg = _load_config(ws_dir)
    manager = _get_manager()

    alias = _make_alias(body.url, body.alias)

    existing = agents_cfg.get(alias)
    if existing and existing["url"] != body.url:
        raise HTTPException(
            status_code=409,
            detail=f"Alias '{alias}' is already used for a different URL",
        )

    reg_info = {
        "url": body.url,
        "alias": alias,
        "auth_type": body.auth_type or "",
        "auth_token": body.auth_token or "",
        "gateway_config": body.gateway_config or {},
    }

    try:
        card_info = await manager.connect(
            agent_url=body.url,
            auth_type=body.auth_type or "",
            auth_token=body.auth_token or "",
            gateway_config=body.gateway_config,
        )
    except Exception as exc:
        logger.warning("Failed to connect to %s: %s", body.url, exc)
        agents_cfg[alias] = reg_info
        _save_config(ws_dir, agents_cfg)
        return _build_entry_response(reg_info, None, error=str(exc))

    agents_cfg[alias] = reg_info
    _save_config(ws_dir, agents_cfg)

    return _build_entry_response(reg_info, card_info)


@router.delete("/agents/{alias}", summary="Delete A2A agent")
async def delete_agent(request: Request, alias: str) -> dict:
    ws_dir = await _get_workspace_dir(request)
    agents_cfg = _load_config(ws_dir)

    reg = agents_cfg.pop(alias, None)
    if not reg:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{alias}' not found",
        )

    _save_config(ws_dir, agents_cfg)

    manager = _get_manager()
    try:
        await manager.disconnect(reg["url"])
    except Exception as exc:
        logger.warning("Error disconnecting %s: %s", reg["url"], exc)

    return {"status": "ok"}


@router.post(
    "/agents/{alias}/refresh",
    response_model=AgentEntryResponse,
    summary="Refresh Agent Card",
)
async def refresh_agent(request: Request, alias: str) -> AgentEntryResponse:
    ws_dir = await _get_workspace_dir(request)
    agents_cfg = _load_config(ws_dir)

    reg = agents_cfg.get(alias)
    if not reg:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{alias}' not found",
        )
    reg["alias"] = alias

    manager = _get_manager()

    try:
        await manager.disconnect(reg["url"])
    except Exception:
        pass

    try:
        card_info = await manager.connect(
            agent_url=reg["url"],
            auth_type=reg.get("auth_type", ""),
            auth_token=reg.get("auth_token", ""),
            gateway_config=reg.get("gateway_config"),
        )
    except Exception as exc:
        logger.warning("Refresh failed for %s: %s", reg["url"], exc)
        return _build_entry_response(reg, None, error=str(exc))

    return _build_entry_response(reg, card_info)


# ------------------------------------------------------------------
# Direct A2A call endpoint (REST + SSE)
# ------------------------------------------------------------------


class A2ACallRequest(BaseModel):
    message: str = Field(..., description="Message to send to remote agent")
    agent_alias: str = Field("", description="Alias of registered agent")
    agent_url: str = Field("", description="Direct URL of remote agent")
    context_id: str = Field(
        "",
        description="Session context ID for multi-turn",
    )


@router.post(
    "/call",
    summary="Direct A2A call with SSE streaming support",
)
async def direct_call(request: Request, body: A2ACallRequest) -> dict:
    """Initiate a direct A2A call to a remote agent.

    While this endpoint processes the call, the frontend can subscribe
    to GET /a2a/call/stream for real-time progress via SSE.
    """
    from modules.a2a.call_stream import get_stream
    from qwenpaw.app.agent_context import set_current_agent_id

    if get_stream() is not None:
        raise HTTPException(
            status_code=409,
            detail="An A2A call is already in progress",
        )

    agent_id = request.headers.get("X-Agent-Id")
    if not agent_id:
        from qwenpaw.config.utils import load_config

        agent_id = load_config().agents.active_agent or "default"
    set_current_agent_id(agent_id)

    from tools.a2a_call import a2a_call

    tool_resp = await a2a_call(
        message=body.message,
        agent_alias=body.agent_alias,
        agent_url=body.agent_url,
        context_id=body.context_id,
    )

    result: dict = {}
    for block in tool_resp.content:
        if block.get("type") == "text":
            try:
                result = json.loads(block["text"])
            except (json.JSONDecodeError, TypeError):
                result = {"response_text": block["text"]}
    return result


# ------------------------------------------------------------------
# SSE stream for real-time a2a_call progress
# ------------------------------------------------------------------


@router.get(
    "/call/stream",
    summary="SSE stream for active a2a_call",
)
async def stream_call(request: Request):
    """Server-Sent Events stream that relays a2a_call progress to the browser.

    The frontend subscribes to this endpoint while a tool call is in
    progress.  Each event is a JSON object with keys:
        response_text, task_state, event_count  — progress update
        done: true                               — call finished
    """
    from modules.a2a.call_stream import read_stream_sse

    async def event_generator():
        async for chunk in read_stream_sse():
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
