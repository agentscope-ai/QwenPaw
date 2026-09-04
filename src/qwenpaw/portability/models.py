# -*- coding: utf-8 -*-
"""Stable models shared by QwenPaw import flows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..harnesses.events import HarnessHistoryItem


class SourceLocation(BaseModel):
    """Resolved provider data roots and the evidence used to choose them."""

    provider_id: str
    data_home: str
    data_home_source: str = "default"
    user_data_home: str = ""
    runtime_path: str = ""
    data_home_exists: bool = False
    user_data_home_exists: bool = False


class SourceSkill(BaseModel):
    """One provider-owned Skill that can be staged into QwenPaw."""

    source_id: str
    name: str
    directory: Path
    description: str = ""


class SourceMCPServer(BaseModel):
    """One external MCP launch configuration ready for safe translation."""

    source_id: str
    name: str
    transport: str = "stdio"
    enabled: bool = False
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    auth_status: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceMemoryFile(BaseModel):
    """One immutable Markdown resource owned by an external memory store."""

    source_path: Path
    relative_path: Path


class SourceMemoryProject(BaseModel):
    """Project-scoped external memory resources ready for safe staging."""

    source_id: str
    project_key: str
    cwd: str = ""
    files: list[SourceMemoryFile] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceMarketplace(BaseModel):
    """A third-party plugin Marketplace source, not an installed cache."""

    source_id: str
    name: str
    source: str = ""
    source_type: str = "unknown"
    ref_name: str = ""


class SourcePlugin(BaseModel):
    """An enabled external plugin that should use native installation."""

    source_id: str
    name: str
    marketplace: str
    version: str = ""
    install_source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceScheduledTask(BaseModel):
    """Staged task; ``enabled`` is source provenance, not authorization."""

    source_id: str
    name: str
    schedule_type: str = "unsupported"
    cron: str = ""
    run_at: datetime | None = None
    timezone: str = "UTC"
    prompt: str = ""
    cwd: str = ""
    enabled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceSession(BaseModel):
    """Provider-neutral external conversation ready for materialization."""

    source_id: str
    title: str = "Imported conversation"
    cwd: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    history: list[HarnessHistoryItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderInventory(BaseModel):
    """Bounded, read-only inventory returned by a Migration Provider."""

    provider_id: str
    provider_name: str
    detected: bool
    locator: str = ""
    sessions: list[SourceSession] = Field(default_factory=list)
    ignored_session_ids: list[str] = Field(default_factory=list)
    skills: list[SourceSkill] = Field(default_factory=list)
    mcp_servers: list[SourceMCPServer] = Field(default_factory=list)
    memory_projects: list[SourceMemoryProject] = Field(default_factory=list)
    marketplaces: list[SourceMarketplace] = Field(default_factory=list)
    plugins: list[SourcePlugin] = Field(default_factory=list)
    scheduled_tasks: list[SourceScheduledTask] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportAssetState(StrEnum):
    """States exposed by the Console import workflow."""

    PENDING = "pending"
    REPAIRING = "repairing"
    READY = "ready"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    EXISTING = "existing"


class ImportSelection(BaseModel):
    """User-selected subset of one provider inventory."""

    sessions: bool = True
    memory: list[str] = Field(default_factory=list)
    cron: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    mcp: list[str] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicates(self) -> "ImportSelection":
        for field in ("memory", "cron", "skills", "mcp", "plugins"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {field} selection")
        return self


class ImportAssetResult(BaseModel):
    """Stable per-asset result used by the Console."""

    asset_type: str
    source_id: str
    name: str
    state: ImportAssetState = ImportAssetState.PENDING
    enabled: bool | None = None
    message: str = ""
    requires_sessions: bool = False


class MigrationAssetPlan(BaseModel):
    """One selectable asset in a migration plan."""

    asset_type: str
    source_id: str
    name: str
    requires_sessions: bool = False


class MigrationPlan(BaseModel):
    """Persisted dry-run plan that can be verified again before apply."""

    plan_id: str
    schema_version: str = "1"
    source: str
    agent_id: str
    created_at: datetime
    asset_fingerprints: dict[str, str] = Field(default_factory=dict)
    actions: list[MigrationAssetPlan] = Field(default_factory=list)
    state: str = "ready"


__all__ = [
    "ImportAssetResult",
    "ImportAssetState",
    "ImportSelection",
    "MigrationAssetPlan",
    "MigrationPlan",
    "ProviderInventory",
    "SourceMarketplace",
    "SourceMemoryFile",
    "SourceMemoryProject",
    "SourcePlugin",
    "SourceScheduledTask",
    "SourceSession",
    "SourceSkill",
    "SourceMCPServer",
    "SourceLocation",
]
