# -*- coding: utf-8 -*-
"""Top-level restore orchestration used by the HTTP router.

Separating orchestration from the core restore logic keeps the router thin
and makes the stop-agent → restore → restart-agent flow independently testable.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ._ops.storage import get_backup
from ._ops.restore import restore
from .models import RestoreBackupRequest

logger = logging.getLogger(__name__)


def _preload_agents_background(
    preload_fn: Callable[[str], Awaitable[bool]],
    agent_ids: list[str],
) -> None:
    """Fire-and-forget: schedule background preload for *agent_ids*.

    Creates a single asyncio task that iterates the list sequentially so
    that a failure for one agent does not prevent others from being restarted.
    """

    async def _run() -> None:
        for agent_id in agent_ids:
            try:
                await preload_fn(agent_id)
            except Exception as exc:
                logger.warning(
                    "Background preload failed for '%s' after restore: %s",
                    agent_id,
                    exc,
                )

    asyncio.create_task(_run())


async def execute_restore(
    backup_id: str,
    req: RestoreBackupRequest,
    *,
    stop_agent_fn: Callable[[str], Awaitable[bool]] | None = None,
    preload_agent_fn: Callable[[str], Awaitable[bool]] | None = None,
    list_running_agent_ids_fn: Callable[[], list[str]] | None = None,
) -> None:
    """Orchestrate a restore: stop agents → restore files → restart agents.

    Parameters
    ----------
    backup_id:
        ID of the backup to restore.
    req:
        Restore parameters (agents, config, secrets, skill pool).
    stop_agent_fn:
        Async callable that stops a single agent by ID.  ``None`` when no
        ``MultiAgentManager`` is available (e.g. tests).
    preload_agent_fn:
        Async callable that preloads a single agent by ID after restore.
        ``None`` when no ``MultiAgentManager`` is available.
    list_running_agent_ids_fn:
        Sync callable that returns all currently running agent IDs.  Used to
        expand the stop set when ``include_secrets`` or
        ``include_skill_pool`` is True, because those directories may contain
        files held open by any running agent (not only the restored ones).
        ``None`` when no ``MultiAgentManager`` is available.

    Raises
    ------
    FileNotFoundError
        When the backup does not exist.
    Exception
        Any other error from the underlying restore; the caller is responsible
        for translating these to HTTP responses.
    """
    detail = await get_backup(backup_id)
    if detail is None:
        raise FileNotFoundError(f"Backup not found: {backup_id}")

    if req.include_agents:
        req_agent_set = set(req.agent_ids)
        affected_agents = [
            aid for aid in detail.workspace_stats if aid in req_agent_set
        ]
    else:
        affected_agents = []

    # When restoring secrets or the skill pool, ALL running agents may hold
    # open file handles inside those directories (especially on Windows).
    # Expand the stop set to every currently running agent so that directory
    # renames succeed.
    agents_to_stop: list[str] = list(affected_agents)
    if (req.include_secrets or req.include_skill_pool) and (
        list_running_agent_ids_fn is not None
    ):
        running = list_running_agent_ids_fn()
        extra = [aid for aid in running if aid not in set(agents_to_stop)]
        if extra:
            logger.info(
                "include_secrets/include_skill_pool: also stopping "
                "non-restored agents to release file handles: %s",
                extra,
            )
            agents_to_stop = agents_to_stop + extra

    logger.info(
        "execute_restore: backup_id=%s affected_agents=%s agents_to_stop=%s",
        backup_id,
        affected_agents,
        agents_to_stop,
    )

    # Stop all agents that may hold open handles before file operations.
    # On Windows, open handles inside the workspace / secrets / skill-pool
    # directories prevent the atomic directory rename in the restore logic.
    if stop_agent_fn is not None:
        for agent_id in agents_to_stop:
            logger.info("Stopping agent '%s' before restore", agent_id)
            await stop_agent_fn(agent_id)

    try:
        await restore(backup_id, req)
        logger.info(
            "execute_restore finished successfully: backup_id=%s",
            backup_id,
        )
    except Exception:
        logger.exception(
            "execute_restore failed for backup_id=%s",
            backup_id,
        )
        raise
    finally:
        # Always restart every agent we stopped, even if the restore failed,
        # so the service recovers gracefully.
        if preload_agent_fn is not None and agents_to_stop:
            logger.info(
                "Scheduling background preload for agents: %s",
                agents_to_stop,
            )
            _preload_agents_background(preload_agent_fn, agents_to_stop)
