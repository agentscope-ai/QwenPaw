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
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("qwenpaw").getChild("plugin.cloudpaw.routers.a2a")

router = APIRouter(prefix="", tags=["a2a"])

# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class ImportedAgentResponse(BaseModel):
    url: str
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    skills: Optional[list] = None
    capabilities: Optional[dict] = None
    auth_type: str = "gateway"


class ImportResponse(BaseModel):
    agents: list[ImportedAgentResponse]


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


def _sanitize_card_name(name: str) -> str:
    """Convert a card name like 'ECS Backup Assistant' into a stable alias.

    Strips non-alphanumeric characters, collapses whitespace, lowercases,
    and joins with hyphens.
    E.g. ``'ECS Backup Assistant'`` -> ``'ecs-backup-assistant'``.
    """
    result = re.sub(r"[^a-zA-Z0-9一-鿿\s-]+", "", name)
    result = result.strip()
    result = re.sub(r"[\s_]+", "-", result)
    return result.lower() or "unknown"


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
        # Fallback display name from registry when card is unavailable
        if reg_info.get("card_name"):
            data["name"] = reg_info["card_name"]
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

    logger.info(
        "list_agents: %d agents in config, active=%s",
        len(agents_cfg),
        active,
    )

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
    logger.info("list_agents: returning %d agents", len(result))
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

    # Try to connect first to get the Agent Card (includes `name`)
    card_info: dict | None = None
    connect_error: str | None = None
    try:
        card_info = await manager.connect(
            agent_url=body.url,
            auth_type=body.auth_type or "",
            auth_token=body.auth_token or "",
            gateway_config=body.gateway_config,
        )
        logger.info(
            "register_agent: connected to %s, card name='%s'",
            body.url,
            card_info.get("name"),
        )
    except Exception as exc:
        connect_error = str(exc)
        logger.warning("Failed to connect to %s: %s", body.url, exc)

    # Derive alias: explicit alias > sanitised card name > URL hostname
    alias: str
    if body.alias:
        alias = _sanitize_card_name(body.alias)
        card_name = body.alias.strip()
    elif card_info and card_info.get("name"):
        alias = _sanitize_card_name(card_info["name"])
        card_name = card_info["name"]
    else:
        from urllib.parse import urlparse

        parsed = urlparse(body.url)
        alias = parsed.hostname or body.url
        card_name = ""

    if not card_name and card_info and card_info.get("name"):
        card_name = card_info["name"]

    logger.info(
        "register_agent: alias='%s' card_name='%s' url='%s'",
        alias,
        card_name,
        body.url,
    )

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
    if card_name:
        reg_info["card_name"] = card_name

    agents_cfg[alias] = reg_info
    _save_config(ws_dir, agents_cfg)

    if connect_error:
        return _build_entry_response(reg_info, None, error=connect_error)
    logger.info("register_agent: registered alias='%s'", alias)

    return _build_entry_response(reg_info, card_info)


@router.put(
    "/agents",
    response_model=AgentEntryResponse,
    summary="Rename A2A agent alias",
)
async def rename_agent(
    request: Request,
    alias: str = Query(..., description="Current alias"),
) -> AgentEntryResponse:
    """Rename an existing agent's alias."""
    ws_dir = await _get_workspace_dir(request)
    agents_cfg = _load_config(ws_dir)

    body_data = await request.json()
    new_alias = body_data.get("new_alias", "").strip()
    if not new_alias:
        raise HTTPException(
            status_code=400,
            detail="Alias cannot be empty",
        )
    # Validate alias format: no whitespace (breaks /a2a shortcut parsing)
    if re.search(r"\s", new_alias):
        raise HTTPException(
            status_code=400,
            detail="Alias cannot contain whitespace",
        )

    reg = agents_cfg.get(alias)
    if not reg:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{alias}' not found",
        )

    if new_alias in agents_cfg and agents_cfg[new_alias]["url"] != reg["url"]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Alias '{new_alias}' is already used for "
                f"a different agent"
            ),
        )

    # Re-register under the new alias
    agents_cfg.pop(alias)
    reg["alias"] = new_alias
    agents_cfg[new_alias] = reg
    _save_config(ws_dir, agents_cfg)
    logger.info("rename_agent: '%s' -> '%s'", alias, new_alias)

    manager = _get_manager()
    card_info = await manager.get_card_info(reg["url"])
    return _build_entry_response(reg, card_info)


@router.delete("/agents", summary="Delete A2A agent")
async def delete_agent(
    request: Request,
    alias: str = Query(..., description="Alias to delete"),
) -> dict:
    logger.info("delete_agent: alias='%s'", alias)
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

    logger.info("delete_agent: deleted alias='%s' url='%s'", alias, reg["url"])
    return {"status": "ok"}


@router.post(
    "/agents/refresh",
    response_model=AgentEntryResponse,
    summary="Refresh Agent Card",
)
async def refresh_agent(
    request: Request,
    alias: str = Query(..., description="Alias to refresh"),
) -> AgentEntryResponse:
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
# Batch import from AgentHub
# ------------------------------------------------------------------

_AGENTHUB_BASE_URL = "https://agenthub.cn-beijing.aliyuncs.com"
_AGENTHUB_API_URL = f"{_AGENTHUB_BASE_URL}/agents"  # Agent list API endpoint
_AGENTHUB_PAGE_SIZE = 10


@router.get(
    "/import",
    response_model=ImportResponse,
    summary="Batch import agents from AgentHub",
)
async def import_agents() -> ImportResponse:
    """Fetch all agents from AgentHub using cursor-based pagination.

    Fetches agents via maxResults/nextToken, accumulating all results
    before returning.  Key parameters (base URL, page size) are module-level
    variables for easy tuning.
    """
    import httpx

    all_results: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First page
            logger.info(
                "AgentHub import: fetching first page from %s (maxResults=%d)",
                _AGENTHUB_API_URL,
                _AGENTHUB_PAGE_SIZE,
            )
            resp = await client.get(
                _AGENTHUB_API_URL,
                params={"maxResults": _AGENTHUB_PAGE_SIZE},
            )
            resp.raise_for_status()
            data = resp.json()
            total_count = data.get("totalCount", 0)
            page_results = data.get("results", [])
            logger.info(
                "AgentHub import: page 1, got %d agents, totalCount=%d",
                len(page_results),
                total_count,
            )
            all_results.extend(page_results)

            # Subsequent pages via nextToken
            next_token = data.get("nextToken", "")
            page_index = 1
            while next_token:
                page_index += 1
                logger.info(
                    "AgentHub import: fetching page %d (nextToken=%s...)",
                    page_index,
                    next_token[:20],
                )
                resp = await client.get(
                    _AGENTHUB_API_URL,
                    params={
                        "maxResults": _AGENTHUB_PAGE_SIZE,
                        "nextToken": next_token,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                page_results = data.get("results", [])
                all_results.extend(page_results)
                logger.info(
                    "AgentHub import: page %d, got %d agents",
                    page_index,
                    len(page_results),
                )
                next_token = data.get("nextToken", "")

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "AgentHub import HTTP error: %d — %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=(
                "Failed to fetch agents from AgentHub: "
                f"{exc.response.text[:200]}"
            ),
        ) from exc
    except httpx.RequestError as exc:
        logger.warning(
            "AgentHub import network error: %s",
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Network error connecting to AgentHub: {exc}",
        ) from exc
    except Exception as exc:
        logger.warning("AgentHub import unexpected error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {exc}",
        ) from exc

    agents: list[ImportedAgentResponse] = []
    for item in all_results:
        interfaces = item.get("supportedInterfaces", [])
        if not interfaces:
            continue
        agent_url = interfaces[0].get("url", "")
        if not agent_url:
            continue

        agents.append(
            ImportedAgentResponse(
                url=agent_url,
                name=item.get("name", agent_url),
                description=item.get("description"),
                version=item.get("version"),
                skills=item.get("skills"),
                capabilities=item.get("capabilities"),
                auth_type="gateway",
            ),
        )

    logger.info(
        "AgentHub import complete: fetched %d raw, returned %d with URLs",
        len(all_results),
        len(agents),
    )

    return ImportResponse(agents=agents)


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

    logger.info(
        "direct_call: agent_alias='%s' agent_url='%s'",
        body.agent_alias,
        body.agent_url,
    )

    agent_id = request.headers.get("X-Agent-Id")
    if not agent_id:
        from qwenpaw.config.utils import load_config

        agent_id = load_config().agents.active_agent or "default"
    set_current_agent_id(agent_id)

    from tools.a2a_call import a2a_call

    # a2a_call is an async generator; iterate and take the final chunk
    final_chunk = None
    async for chunk in a2a_call(
        message=body.message,
        agent_alias=body.agent_alias,
        agent_url=body.agent_url,
        context_id=body.context_id,
    ):
        final_chunk = chunk

    if final_chunk is None:
        return {"error": "A2A call produced no result"}

    result: dict = {}
    for block in final_chunk.content:
        if block.get("type") == "text":
            try:
                result = json.loads(block["text"])
            except (json.JSONDecodeError, TypeError):
                result = {"response_text": block["text"]}
    logger.info("direct_call: response received")
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
