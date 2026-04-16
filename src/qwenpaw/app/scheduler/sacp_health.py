# -*- coding: utf-8 -*-
"""SACP Agent Health Check Scheduler.

Runs periodic health checks against all registered SACP agents using
APScheduler (AsyncIOScheduler). Each agent's individual interval is respected
when scheduling its next check.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from qwenpaw.meetings.models.sacp_agent import (
    SACPAgentConfig,
    SACPAgentsStorage,
    HealthStatus,
)

logger = logging.getLogger(__name__)

STORAGE_PATH = Path.home() / ".qwenpaw" / "sacp_agents.json"


# ---------------------------------------------------------------------------
# Storage helpers (mirrors sacp_agents.py)
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
# Health probe (mirrors sacp_agents.py)
# ---------------------------------------------------------------------------


async def _probe_agent(agent: SACPAgentConfig) -> HealthStatus:
    """Send a lightweight probe to the agent's /health endpoint.

    Mirrors the probe logic in sacp_agents.py for consistency.
    """
    # For internal agents, verify the agent exists in config
    # and sacp channel is enabled
    status = HealthStatus.UNHEALTHY
    if agent.is_internal and agent.internal_agent_id:
        from ...config.utils import load_agent_config

        internal_id = agent.internal_agent_id
        agent_config = load_agent_config(internal_id)
        sacp_cfg = getattr(agent_config.channels, "sacp", None)
        if sacp_cfg and getattr(sacp_cfg, "enabled", True):
            status = HealthStatus.HEALTHY
    elif agent.url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{agent.url.rstrip('/')}/health",
                    headers=(
                        {"Authorization": f"Bearer {agent.auth_key}"}
                        if agent.auth_key
                        else {}
                    ),
                )
                if 200 <= response.status_code < 300:
                    status = HealthStatus.HEALTHY
        except Exception:  # noqa: BLE001
            logger.exception("Failed to connect to SACP agent(outer)")

    return status


# ---------------------------------------------------------------------------
# Per-agent health check job
# ---------------------------------------------------------------------------


async def _check_agent(agent_id: str) -> None:
    """Load agent from storage and update its health status in storage."""
    storage = _load_storage()

    for i, agent in enumerate(storage.agents):
        if agent.id != agent_id:
            continue

        # Skip disabled agents
        if not agent.health_check_enabled:
            return

        status = await _probe_agent(agent)
        if status == HealthStatus.HEALTHY:
            agent.mark_healthy()
        else:
            agent.mark_unhealthy(
                agent.last_health_error or "Health check failed",
            )

        storage.agents[i] = agent
        _save_storage(storage)
        logger.debug(
            "Health check result for agent %s (%s): %s",
            agent.name,
            agent.id,
            status.value,
        )
        return


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

_scheduler: Optional[AsyncIOScheduler] = None


def start_scheduler() -> None:
    """Start the SACP health check scheduler.

    Schedules each enabled agent with its own per-agent interval.
    """
    global _scheduler
    if _scheduler is not None:
        logger.warning("SACP health scheduler is already running")
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")
    storage = _load_storage()

    for agent in storage.agents:
        if not agent.health_check_enabled:
            continue
        interval = max(agent.health_check_interval, 60)  # minimum 60s
        _scheduler.add_job(
            _check_agent,
            "interval",
            seconds=interval,
            args=[agent.id],
            id=f"health_{agent.id}",
            replace_existing=True,
        )
        logger.debug(
            "Scheduled health check for agent %s (%s) every %ds",
            agent.name,
            agent.id,
            interval,
        )

    _scheduler.start()
    logger.info("SACP health check scheduler started")


def stop_scheduler() -> None:
    """Stop the SACP health check scheduler."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("SACP health check scheduler stopped")
