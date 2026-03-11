# -*- coding: utf-8 -*-
"""Runtime-safe workspace bootstrap helpers."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..agents.skills_manager import (
    get_active_skills_dir,
    sync_skills_to_working_dir,
)
from ..agents.utils import copy_md_files
from ..config import get_config_path, load_config, save_config
from ..config.config import Config, HeartbeatConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkspaceBootstrapResult:
    """Describe runtime bootstrap actions."""

    config_created: bool = False
    config_updated: bool = False
    heartbeat_initialized: bool = False
    md_files_copied: int = 0
    md_language_initialized: bool = False
    skills_initialized: bool = False
    skills_synced: int = 0
    skills_skipped: int = 0


def ensure_runtime_workspace_initialized() -> WorkspaceBootstrapResult:
    """Create the default workspace scaffold without overwriting user data.

    This bootstrap is designed for container/runtime startup, not interactive
    setup. It only fills in missing defaults for an uninitialized workspace.
    Once the workspace scaffold is marked as installed, later runs leave user
    deletions and customizations alone.
    """

    result = WorkspaceBootstrapResult()
    config_path = get_config_path()
    config_exists = config_path.is_file()
    config = load_config(config_path) if config_exists else Config()

    if not config_exists:
        result.config_created = True
        result.config_updated = True

    if config.agents.defaults.heartbeat is None:
        config.agents.defaults.heartbeat = HeartbeatConfig()
        result.heartbeat_initialized = True
        result.config_updated = True

    scaffold_uninitialized = config.agents.installed_md_files_language is None
    if scaffold_uninitialized:
        copied = copy_md_files(config.agents.language, skip_existing=True)
        result.md_files_copied = len(copied)
        config.agents.installed_md_files_language = config.agents.language
        result.md_language_initialized = True
        result.config_updated = True

        active_skills_dir = get_active_skills_dir()
        if not active_skills_dir.exists():
            synced, skipped = sync_skills_to_working_dir(
                skill_names=None,
                force=False,
            )
            result.skills_initialized = True
            result.skills_synced = synced
            result.skills_skipped = skipped

    if result.config_updated:
        save_config(config, config_path)

    logger.info(
        "Workspace bootstrap: config_created=%s config_updated=%s "
        "heartbeat_initialized=%s md_files_copied=%d "
        "md_language_initialized=%s skills_initialized=%s "
        "skills_synced=%d skills_skipped=%d",
        result.config_created,
        result.config_updated,
        result.heartbeat_initialized,
        result.md_files_copied,
        result.md_language_initialized,
        result.skills_initialized,
        result.skills_synced,
        result.skills_skipped,
    )
    return result
