# -*- coding: utf-8 -*-
"""Backup data models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ._utils.meta import generate_backup_id


class BackupScope(BaseModel):
    include_agents: bool = Field(
        default=True,
        description="Include agent workspaces",
    )
    include_global_config: bool = Field(
        default=True,
        description="Include global config.json",
    )
    include_secrets: bool = Field(
        default=False,
        description="Include secrets directory",
    )
    include_skill_pool: bool = Field(
        default=True,
        description="Include skill pool directory",
    )


class BackupMeta(BaseModel):
    id: str = Field(
        default_factory=generate_backup_id,
        description="Backup ID (qwenpaw-{version}-{timestamp}-{short8})",
    )
    name: str = Field(..., description="Backup name")
    description: str = Field(default="", description="Optional description")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    version: str = Field(default="1", description="Backup format version")
    scope: BackupScope = Field(default_factory=BackupScope)
    agent_count: int = Field(
        default=0,
        description="Number of agents in this backup",
    )
    qwenpaw_version: str = Field(
        default="",
        description="QwenPaw version when backup was created",
    )
    system_info: dict = Field(
        default_factory=dict,
        description="System information (OS, Python version, etc.)",
    )


class CreateBackupRequest(BaseModel):
    name: str = Field(..., description="Backup name")
    description: str = Field(default="")
    scope: BackupScope = Field(default_factory=BackupScope)
    agents: list[str] = Field(
        default_factory=list,
        description="Agent IDs to include when scope.include_agents is True. "
        "Must be the explicit list (even for 'all agents').",
    )


class RestoreBackupRequest(BaseModel):
    include_agents: bool = Field(
        default=True,
        description="Restore agent workspaces",
    )
    agent_ids: list[str] = Field(
        default_factory=list,
        description="Agent IDs to restore when include_agents is True. "
        "Must be the explicit list (even for 'all agents'). "
        "Ignored when include_agents is False.",
    )
    include_global_config: bool = Field(default=True)
    include_secrets: bool = Field(default=False)
    include_skill_pool: bool = Field(default=True)
    default_workspace_dir: Optional[str] = Field(
        default=None,
        description=(
            "Base directory for placing new agents' workspaces. "
            "When set, each new agent is placed at "
            "{default_workspace_dir}/{agent_id}/workspace. "
            "Defaults to {WORKING_DIR}/workspaces/{agent_id} if unspecified."
        ),
    )
    mode: Literal["full", "custom"] = Field(
        default="custom",
        description=(
            "Restore mode (mirrors the frontend full/custom selector):\n"
            "- 'full': complete replacement; config.json (incl. "
            "agents.profiles) is replaced wholesale, so agents "
            "added after the backup will be removed from the registry.\n"
            "- 'custom' (default): selective restore; when "
            "include_global_config is True, all top-level config "
            "keys come from the backup, but agents.profiles is "
            "rebuilt from the current local registry with only "
            "the agents listed in agent_ids (those actually being "
            "restored) overwritten from the backup.  Agents not in "
            "agent_ids keep their current local state, preventing "
            "ghost entries when include_agents is False."
        ),
    )


class DeleteBackupsRequest(BaseModel):
    ids: list[str] = Field(..., description="Backup IDs to delete")


class DeleteBackupsResponse(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)


class BackupDetail(BackupMeta):
    workspace_stats: dict[str, dict] = Field(
        default_factory=dict,
        description="Per-agent stats: {agent_id: {files: int, size: int}}",
    )


class BackupConflictError(Exception):
    """Raised when an imported backup's ID already exists on disk."""

    def __init__(self, existing_meta: BackupMeta) -> None:
        self.existing_meta = existing_meta
        super().__init__(f"backup_conflict: {existing_meta.id}")
