# -*- coding: utf-8 -*-
"""Top-level restore orchestration used by the HTTP router.

Separating orchestration from the core restore logic keeps the router thin
and makes the stop-agent -> restore -> restart-agent flow independently
testable.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ._ops.storage import get_backup
from ._ops.restore import preflight_restore, restore
from .models import BackupMeta, RestoreBackupRequest
from ..config.utils import load_config

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
    stop_browsers_fn: Callable[[list[str]], Awaitable[None]] | None = None,
    preload_agent_fn: Callable[[str], Awaitable[bool]] | None = None,
    list_running_agent_ids_fn: Callable[[], list[str]] | None = None,
) -> BackupMeta:
    """Orchestrate a restore: stop agents -> restore files -> restart agents.

    Parameters
    ----------
    backup_id:
        ID of the backup to restore.
    req:
        Restore parameters (agents, config, secrets, skill pool).
    stop_agent_fn:
        Async callable that stops a single agent by ID.  ``None`` when no
        ``MultiAgentManager`` is available (e.g. tests).
    stop_browsers_fn:
        Async callable that closes QwenPaw-managed browser instances for the
        supplied workspace directories before those directories are restored.
        Browser profiles live inside workspaces and can keep Windows directory
        renames from succeeding. ``None`` when browser management is
        unavailable.
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

    # Trust/signature validation must happen before stopping workspaces.  The
    # legacy trust prompt is a validation step; stopping and background
    # reloading agents before the user confirms can race the second restore
    # attempt on Windows and leave workspace directories temporarily locked.
    await asyncio.to_thread(preflight_restore, backup_id, req)

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

    if affected_agents and stop_browsers_fn is not None:
        logger.info("Stopping managed browsers before workspace restore")
        await stop_browsers_fn(_workspace_dirs_for_agents(agents_to_stop))

    try:
        meta = await restore(backup_id, req)
        logger.info(
            "execute_restore finished successfully: backup_id=%s",
            backup_id,
        )
        return meta
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


def _workspace_dirs_for_agents(agent_ids: list[str]) -> list[str]:
    """Return configured workspace directories for *agent_ids*.

    Browser state is keyed by workspace directory, not by backup ID.  The
    restore orchestrator resolves the paths before the config on disk may be
    replaced so browser cleanup can stay scoped to the affected workspaces.
    """
    config = load_config()
    workspace_dirs: list[str] = []
    seen: set[str] = set()
    for agent_id in agent_ids:
        ref = config.agents.profiles.get(agent_id)
        if ref is None or not ref.workspace_dir:
            continue
        if ref.workspace_dir in seen:
            continue
        seen.add(ref.workspace_dir)
        workspace_dirs.append(ref.workspace_dir)
    return workspace_dirs
