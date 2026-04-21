# -*- coding: utf-8 -*-
"""Helpers for creating backups: agents, global config, secrets, skill pool."""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any

from .._utils.constants import (
    PREFIX_CONFIG,
    PREFIX_SECRETS,
    PREFIX_SKILL_POOL,
    PREFIX_WORKSPACES,
)
from ...constant import CONFIG_FILE, SECRET_DIR, WORKING_DIR

logger = logging.getLogger(__name__)


def add_agent_workspaces(
    zf: zipfile.ZipFile,
    valid_agents: list[tuple[str, Any]],
    progress_callback=None,
    stop_event=None,
) -> bool:
    """Add each agent's workspace directory to the zip.

    Returns:
        False if stop_event was set (cancelled), True otherwise.
    """
    total = len(valid_agents)
    logger.info(
        "Backing up %d agent(s): %s",
        total,
        [aid for aid, _ in valid_agents],
    )

    for i, (aid, ref) in enumerate(valid_agents):
        if stop_event and stop_event.is_set():
            return False

        if progress_callback:
            progress_callback(i, total, aid)

        ws = Path(ref.workspace_dir).expanduser().resolve()
        if ws.is_dir():
            file_count = 0
            for entry in sorted(ws.rglob("*")):
                if entry.is_file():
                    rel = entry.relative_to(ws).as_posix()
                    arcname = f"{PREFIX_WORKSPACES}{aid}/{rel}"
                    zf.write(entry, arcname)
                    file_count += 1
            logger.debug(
                "Agent '%s': %d file(s) added from %s",
                aid,
                file_count,
                ws,
            )
        else:
            logger.warning(
                "Agent '%s' workspace directory not found: %s",
                aid,
                ws,
            )

    return not (stop_event and stop_event.is_set())


def add_global_config(zf: zipfile.ZipFile) -> None:
    """Add the global config file to the zip."""
    cfg_src = WORKING_DIR / CONFIG_FILE
    if cfg_src.is_file():
        zf.write(cfg_src, PREFIX_CONFIG)
        logger.info("Global config added to backup: %s", cfg_src)
    else:
        logger.warning(
            "include_global_config=True but config file not found: %s",
            cfg_src,
        )


def add_secrets(zf: zipfile.ZipFile, stop_event=None) -> bool:
    """Add all files from the secrets directory to the zip.

    Returns ``False`` if *stop_event* was set before or during the operation
    (cancelled), ``True`` otherwise.
    """
    if not SECRET_DIR.is_dir():
        logger.warning("Secrets directory not found: %s", SECRET_DIR)
        return True
    file_count = 0
    for entry in sorted(SECRET_DIR.rglob("*")):
        if stop_event and stop_event.is_set():
            return False
        if entry.is_file():
            arcname = (
                f"{PREFIX_SECRETS}{entry.relative_to(SECRET_DIR).as_posix()}"
            )
            zf.write(entry, arcname)
            file_count += 1
    logger.info(
        "Secrets backed up: %d file(s) from %s",
        file_count,
        SECRET_DIR,
    )
    return True


def add_skill_pool(zf: zipfile.ZipFile, stop_event=None) -> bool:
    """Add all files from the skill pool directory to the zip.

    Returns ``False`` if *stop_event* was set before or during the operation
    (cancelled), ``True`` otherwise.
    """
    from ...agents.skills_manager import get_skill_pool_dir

    skill_pool_dir = get_skill_pool_dir()
    if not skill_pool_dir.is_dir():
        logger.warning("Skill pool directory not found: %s", skill_pool_dir)
        return True
    logger.info("Backing up skill pool from %s", skill_pool_dir)
    file_count = 0
    for entry in sorted(skill_pool_dir.rglob("*")):
        if stop_event and stop_event.is_set():
            return False
        if entry.is_file():
            rel = entry.relative_to(skill_pool_dir).as_posix()
            arcname = f"{PREFIX_SKILL_POOL}{rel}"
            logger.debug("  Adding %s", arcname)
            zf.write(entry, arcname)
            file_count += 1
    logger.info("Skill pool backed up: %d file(s)", file_count)
    return True


def add_files_to_zip(
    zf: zipfile.ZipFile,
    meta,
    progress_callback=None,
    stop_event=None,
    valid_agents=None,
) -> list[str]:
    """Add files to zip based on backup scope.

    Args:
        zf: ZipFile object to write to
        meta: Backup metadata with scope information
        progress_callback: Optional callback(current_index, total, agent_id)
        stop_event: Optional threading.Event to support cancellation
        valid_agents: Pre-computed ``(aid, ref)`` pairs to back up.
                      Empty list when meta.scope.include_agents is False.

    Returns:
        List of agent IDs that were backed up, or empty list if cancelled
    """
    if valid_agents is None:
        valid_agents = []

    if valid_agents and not add_agent_workspaces(
        zf,
        valid_agents,
        progress_callback,
        stop_event,
    ):
        return []

    if meta.scope.include_global_config:
        add_global_config(zf)
    if meta.scope.include_secrets:
        if not add_secrets(zf, stop_event):
            return []
    if meta.scope.include_skill_pool:
        if not add_skill_pool(zf, stop_event):
            return []

    return [aid for aid, _ in valid_agents]
