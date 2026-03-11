# -*- coding: utf-8 -*-
"""Runtime-safe workspace bootstrap helpers."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

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


def _get_md_template_dir(language: str) -> Path:
    md_files_dir = (
        Path(__file__).resolve().parent.parent
        / "agents"
        / "md_files"
        / language
    )
    if md_files_dir.exists():
        return md_files_dir
    return (
        Path(__file__).resolve().parent.parent / "agents" / "md_files" / "en"
    )


def _has_complete_md_scaffold(language: str, working_dir: Path) -> bool:
    """Return whether the workspace already contains the md scaffold."""
    md_files_dir = _get_md_template_dir(language)
    expected_files = [md_file.name for md_file in md_files_dir.glob("*.md")]
    return bool(expected_files) and all(
        (working_dir / filename).is_file() for filename in expected_files
    )


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
        working_dir = config_path.parent
        if _has_complete_md_scaffold(config.agents.language, working_dir):
            config.agents.installed_md_files_language = config.agents.language
            result.md_language_initialized = True
            result.config_updated = True
        else:
            logger.warning(
                "Workspace bootstrap could not verify md scaffold in %s",
                working_dir,
            )

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

    logger.info("Workspace bootstrap: %s", result)
    return result
