# -*- coding: utf-8 -*-
"""SACP Agent Registry CRUD API.

Provides REST endpoints for managing SACP agent configurations.
Agents are stored in ~/.qwenpaw/sacp_agents.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Path as PathParam, Response
from pydantic import BaseModel

from qwenpaw.meetings.models.sacp_agent import (
    SACPAgentConfig,
    SACPAgentsStorage,
    CreateSACPAgentRequest,
    SACPAgentHealthCheckResult,
    HealthStatus,
    UpdateSACPAgentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sacp-agents", tags=["sacp-agents"])

STORAGE_PATH = Path.home() / ".qwenpaw" / "sacp_agents.json"


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _load_storage() -> SACPAgentsStorage:
    """Load agent storage from disk, creating with defaults if missing."""
    if not STORAGE_PATH.exists():
        storage = SACPAgentsStorage(version="1.0", agents=[])
        _save_storage(storage)
        return storage
    try:
        data = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
        return SACPAgentsStorage(**data)
    except Exception:
        # Corrupted — start fresh
        return SACPAgentsStorage(version="1.0", agents=[])


def _save_storage(storage: SACPAgentsStorage) -> None:
    """Persist agent storage to disk."""
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_PATH.write_text(
        storage.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SACPAgentsResponse(SACPAgentConfig):
    pass


class HealthCheckResponse(BaseModel):
    agent_id: str
    status: HealthStatus
    checked_at: datetime
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[SACPAgentsResponse],
    summary="List all SACP agents",
    responses={200: {"description": "List of all registered SACP agents"}},
)
async def list_agents() -> list[SACPAgentsResponse]:
    """Return all configured SACP agents."""
    storage = _load_storage()
    return [
        SACPAgentsResponse(**agent.model_dump()) for agent in storage.agents
    ]


@router.post(
    "",
    response_model=SACPAgentsResponse,
    status_code=201,
    summary="Create a new SACP agent",
    responses={
        201: {"description": "Agent created successfully"},
        409: {"description": "Agent with this name already exists"},
    },
)
async def create_agent(
    request: CreateSACPAgentRequest,
) -> SACPAgentsResponse:
    """Register a new SACP agent.

    A unique agent ID and creation timestamp are generated server-side.
    """
    storage = _load_storage()

    # Check for duplicate name
    if any(a.name == request.name for a in storage.agents):
        raise HTTPException(
            status_code=409,
            detail=f"An agent named '{request.name}' already exists",
        )

    now = _now()
    agent = SACPAgentConfig(
        id=str(uuid.uuid4()),
        name=request.name,
        description=request.description,
        url=request.url,
        auth_key=request.auth_key,
        is_internal=request.is_internal,
        internal_agent_id=request.internal_agent_id,
        health_status=HealthStatus.UNKNOWN,
        last_health_check=None,
        last_health_error=None,
        consecutive_failures=0,
        health_check_enabled=request.health_check_enabled,
        health_check_interval=request.health_check_interval,
        created_at=now,
        updated_at=now,
    )
    storage.agents.append(agent)
    _save_storage(storage)
    return SACPAgentsResponse(**agent.model_dump())


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


class SettingsUpdateRequest(BaseModel):
    global_internal_auth_key: Optional[str] = None


@router.get(
    "/settings",
    response_model=SACPAgentsStorage,
    summary="Get SACP agents settings",
    responses={200: {"description": "SACP agents settings"}},
)
async def get_settings() -> SACPAgentsStorage:
    """Return the SACP agents storage (includes global settings)."""
    return _load_storage()


@router.put(
    "/settings",
    response_model=SACPAgentsStorage,
    summary="Update SACP agents settings",
    responses={200: {"description": "Updated settings"}},
)
async def update_settings(
    request: SettingsUpdateRequest,
) -> SACPAgentsStorage:
    """Update global SACP agents settings.

    When global_internal_auth_key is updated, automatically syncs all
    internal agents:
    - Existing internal agents: updates their auth_key to the global key
    - Missing internal agents: auto-creates them with health_check_enabled=true
    """
    storage = _load_storage()

    if request.global_internal_auth_key is not None:
        storage.global_internal_auth_key = request.global_internal_auth_key

        # Sync internal agents: fetch from /agents endpoint
        # and update/create entries
        try:
            from ...config.utils import load_config

            config = load_config()
            now = _now()

            # For each agent in config, ensure it exists in storage
            # All agents in config.agents.profiles are internal qwenpaw agents
            for agent_id, _agent_ref in config.agents.profiles.items():
                existing = None
                for agent in storage.agents:
                    if agent.internal_agent_id == agent_id:
                        existing = agent
                        break

                if existing:
                    # Update auth_key to global key
                    existing.auth_key = request.global_internal_auth_key
                    existing.updated_at = now
                else:
                    # Auto-add missing internal agent with
                    # health_check_enabled=true
                    new_agent = SACPAgentConfig(
                        id=str(uuid.uuid4()),
                        name=agent_id,
                        description=f"Internal agent: {agent_id}",
                        url="",
                        auth_key=request.global_internal_auth_key,
                        is_internal=True,
                        internal_agent_id=agent_id,
                        health_status=HealthStatus.UNKNOWN,
                        last_health_check=None,
                        last_health_error=None,
                        consecutive_failures=0,
                        health_check_enabled=True,
                        health_check_interval=300,
                        created_at=now,
                        updated_at=now,
                    )
                    storage.agents.append(new_agent)
        except Exception:
            # If sync fails (e.g., no config available), just save settings
            pass

    _save_storage(storage)
    return storage


# ---------------------------------------------------------------------------
# Entity endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/entity/{agent_id}",
    response_model=SACPAgentsResponse,
    summary="Get a single SACP agent",
    responses={
        200: {"description": "Agent details"},
        404: {"description": "Agent not found"},
    },
)
async def get_agent(
    agent_id: str = PathParam(..., description="The agent ID"),
) -> SACPAgentsResponse:
    """Return details for a specific SACP agent."""
    storage = _load_storage()
    for agent in storage.agents:
        if agent.id == agent_id:
            return SACPAgentsResponse(**agent.model_dump())
    raise HTTPException(
        status_code=404,
        detail=f"Agent '{agent_id}' not found",
    )


@router.put(
    "/entity/{agent_id}",
    response_model=SACPAgentsResponse,
    summary="Update an SACP agent",
    responses={
        200: {"description": "Agent updated"},
        404: {"description": "Agent not found"},
        409: {"description": "Agent name already in use"},
    },
)
async def update_agent(
    agent_id: str = PathParam(..., description="The agent ID"),
    request: UpdateSACPAgentRequest = ...,
) -> SACPAgentsResponse:
    """Update mutable fields on an existing SACP agent.

    Only provided fields are updated (partial update).
    """
    storage = _load_storage()

    for i, agent in enumerate(storage.agents):
        if agent.id == agent_id:
            # Check name collision (exclude self)
            if request.name is not None:
                for other in storage.agents:
                    if other.id != agent_id and other.name == request.name:
                        raise HTTPException(
                            status_code=409,
                            detail=f"duplicated agent named '{request.name}'",
                        )

            # Merge updates
            update_data = request.model_dump(
                exclude_unset=True,
                exclude_none=True,
            )
            updated = agent.model_copy(update=update_data)
            updated.updated_at = _now()
            storage.agents[i] = updated
            _save_storage(storage)
            return SACPAgentsResponse(**updated.model_dump())

    raise HTTPException(
        status_code=404,
        detail=f"Agent '{agent_id}' not found",
    )


@router.delete(
    "/entity/{agent_id}",
    status_code=204,
    summary="Delete an SACP agent",
    responses={
        204: {"description": "Agent deleted"},
        404: {"description": "Agent not found"},
    },
)
async def delete_agent(
    agent_id: str = PathParam(..., description="The agent ID"),
) -> Response:
    """Remove an SACP agent from the registry."""
    storage = _load_storage()
    for i, agent in enumerate(storage.agents):
        if agent.id == agent_id:
            storage.agents.pop(i)
            _save_storage(storage)
            return Response(status_code=204)
    raise HTTPException(
        status_code=404,
        detail=f"Agent '{agent_id}' not found",
    )


# ---------------------------------------------------------------------------
# Health check endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/health_check",
    response_model=list[HealthCheckResponse],
    summary="Trigger batch health check for all agents",
    responses={200: {"description": "Health check results for all agents"}},
)
async def trigger_batch_health_check() -> list[HealthCheckResponse]:
    """Perform health check against all SACP agents.

    Returns results for all agents with health_check_enabled=true.
    """
    storage = _load_storage()
    results: list[HealthCheckResponse] = []

    for i, agent in enumerate(storage.agents):
        if not agent.health_check_enabled:
            continue

        result = await _probe_agent(agent)
        agent.health_status = result.status
        agent.last_health_check = result.checked_at
        agent.last_health_error = result.error
        if result.status == HealthStatus.UNHEALTHY:
            agent.consecutive_failures += 1
        else:
            agent.consecutive_failures = 0
        agent.updated_at = _now()
        storage.agents[i] = agent
        results.append(
            HealthCheckResponse(
                agent_id=agent.id,
                status=result.status,
                checked_at=result.checked_at,
                error=result.error,
            ),
        )

    _save_storage(storage)
    return results


@router.post(
    "/health_check/{agent_id}",
    response_model=HealthCheckResponse,
    summary="Trigger a health check for an agent",
    responses={
        200: {"description": "Health check result"},
        404: {"description": "Agent not found"},
    },
)
async def trigger_health_check(
    agent_id: str = PathParam(..., description="The agent ID"),
) -> HealthCheckResponse:
    """Perform an on-demand health check against an SACP agent.

    Sends a lightweight probe to the agent's URL and records the result.
    """
    storage = _load_storage()

    for i, agent in enumerate(storage.agents):
        if agent.id == agent_id:
            # Try to reach the agent's health endpoint
            result = await _probe_agent(agent)
            agent.health_status = result.status
            agent.last_health_check = result.checked_at
            agent.last_health_error = result.error
            if result.status == HealthStatus.UNHEALTHY:
                agent.consecutive_failures += 1
            else:
                agent.consecutive_failures = 0
            agent.updated_at = _now()
            storage.agents[i] = agent
            _save_storage(storage)
            return HealthCheckResponse(
                agent_id=agent.id,
                status=result.status,
                checked_at=result.checked_at,
                error=result.error,
            )

    raise HTTPException(
        status_code=404,
        detail=f"Agent '{agent_id}' not found",
    )


@router.post(
    "/enable-channel/{agent_id}",
    summary="Enable SACP channel on an internal agent",
    responses={
        200: {"description": "Channel enabled"},
        404: {"description": "Agent not found"},
        400: {"description": "Not an internal agent"},
    },
)
async def enable_sacp_channel(
    agent_id: str = PathParam(..., description="The agent ID"),
) -> dict:
    """Enable the sacp channel on an internal agent's agent.json config.

    This is a convenience endpoint for the frontend to enable the SACP channel
    without needing to fetch and submit the full AgentProfileConfig.
    """
    storage = _load_storage()
    sacp_agent = None
    for a in storage.agents:
        if a.id == agent_id:
            sacp_agent = a
            break
    if not sacp_agent:
        raise HTTPException(status_code=404, detail="SACP agent not found")
    if not sacp_agent.is_internal:
        raise HTTPException(
            status_code=400,
            detail="Only internal agents need SACP channel",
        )

    internal_id = sacp_agent.internal_agent_id
    if not internal_id:
        raise HTTPException(
            status_code=400,
            detail="Internal agent has no internal_agent_id",
        )

    from ...config.utils import load_agent_config, save_agent_config
    from ...config.config import SACPChannelConfig

    agent_config = load_agent_config(internal_id)

    # Ensure channels.sacp exists with enabled=True
    if (
        not hasattr(agent_config.channels, "sacp")
        or agent_config.channels.sacp is None
    ):
        agent_config.channels.sacp = SACPChannelConfig(enabled=True)
    else:
        agent_config.channels.sacp.enabled = True

    save_agent_config(internal_id, agent_config)

    logger.info(
        f"Enabled sacp channel for agent {agent_id} (internal: {internal_id})",
    )
    return {"ok": True, "agent_id": agent_id, "internal_agent_id": internal_id}


# ---------------------------------------------------------------------------
# Health probe helper
# ---------------------------------------------------------------------------


async def _probe_agent(agent: SACPAgentConfig) -> SACPAgentHealthCheckResult:
    """Send a lightweight probe to the agent's /health endpoint."""
    # For internal agents, verify the agent exists in config
    # and sacp channel is enabled
    if agent.is_internal:
        return await _agent_check_inner(agent)

    if not agent.url:
        return SACPAgentHealthCheckResult(
            agent_id=agent.id,
            status=HealthStatus.UNHEALTHY,
            checked_at=_now(),
            error="Agent has no URL configured",
        )
    return await _agent_check_outer(agent)


async def _agent_check_inner(
    agent: SACPAgentConfig,
) -> SACPAgentHealthCheckResult:
    try:
        from ...config.utils import load_agent_config

        internal_id = agent.internal_agent_id
        if not internal_id:
            return SACPAgentHealthCheckResult(
                agent_id=agent.id,
                status=HealthStatus.UNHEALTHY,
                checked_at=_now(),
                error="Internal agent has no internal_agent_id",
            )

        agent_config = load_agent_config(internal_id)
        # Verify agent is registered in global config
        from ...config.utils import load_config as load_global_config

        global_config = load_global_config()
        if internal_id not in global_config.agents.profiles:
            return SACPAgentHealthCheckResult(
                agent_id=agent.id,
                status=HealthStatus.UNHEALTHY,
                checked_at=_now(),
                error=f"Internal agent '{internal_id}' not found",
            )
        sacp_cfg = getattr(agent_config.channels, "sacp", None)
        if not sacp_cfg or not getattr(sacp_cfg, "enabled", False):
            return SACPAgentHealthCheckResult(
                agent_id=agent.id,
                status=HealthStatus.UNHEALTHY,
                checked_at=_now(),
                error=f"SACP channel is not enabled for {internal_id}",
            )

        return SACPAgentHealthCheckResult(
            agent_id=agent.id,
            status=HealthStatus.HEALTHY,
            checked_at=_now(),
            error=None,
        )
    except Exception as exc:
        return SACPAgentHealthCheckResult(
            agent_id=agent.id,
            status=HealthStatus.UNHEALTHY,
            checked_at=_now(),
            error=str(exc),
        )


async def _agent_check_outer(
    agent: SACPAgentConfig,
) -> SACPAgentHealthCheckResult:
    health_url = f"{agent.url.rstrip('/')}/health"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                health_url,
                headers=(
                    {"Authorization": f"Bearer {agent.auth_key}"}
                    if agent.auth_key
                    else {}
                ),
            )
            if 200 <= response.status_code < 300:
                return SACPAgentHealthCheckResult(
                    agent_id=agent.id,
                    status=HealthStatus.HEALTHY,
                    checked_at=_now(),
                    error=None,
                )
            else:
                return SACPAgentHealthCheckResult(
                    agent_id=agent.id,
                    status=HealthStatus.UNHEALTHY,
                    checked_at=_now(),
                    error=f"HTTP {response.status_code}",
                )
    except httpx.TimeoutException:
        return SACPAgentHealthCheckResult(
            agent_id=agent.id,
            status=HealthStatus.UNHEALTHY,
            checked_at=_now(),
            error="Connection timed out",
        )
    except Exception as exc:  # noqa: BLE001
        return SACPAgentHealthCheckResult(
            agent_id=agent.id,
            status=HealthStatus.UNHEALTHY,
            checked_at=_now(),
            error=str(exc),
        )
