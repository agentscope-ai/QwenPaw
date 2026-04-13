# -*- coding: utf-8 -*-
"""Data models for user asset backup & migration."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AssetType(str, Enum):
    """Types of exportable user assets."""

    PREFERENCES = "preferences"
    MEMORIES = "memories"
    SKILLS = "skills"
    TOOLS = "tools"
    GLOBAL_CONFIG = "global_config"


class ConflictStrategy(str, Enum):
    """Strategy for resolving import conflicts."""

    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"
    ASK = "ask"


class CompatibilityLevel(str, Enum):
    """Version compatibility level between asset packages."""

    FULL = "full"
    MIGRATABLE = "migratable"
    INCOMPATIBLE = "incompatible"


# ---------------------------------------------------------------------------
# Pydantic models (serialisable to / from JSON)
# ---------------------------------------------------------------------------


class AssetEntry(BaseModel):
    """A single asset entry inside an asset package manifest."""

    asset_type: AssetType
    name: str
    relative_path: str
    sha256: str
    size_bytes: int
    metadata: dict = Field(default_factory=dict)


class AssetManifest(BaseModel):
    """Top-level manifest stored as ``manifest.json`` inside a ZIP package."""

    schema_version: str = "copaw-assets.v1"
    created_at: str
    source_agent_id: str
    source_device_id: str
    copaw_version: str
    assets: list[AssetEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dataclasses (internal use, not persisted to JSON)
# ---------------------------------------------------------------------------


@dataclass
class ConflictInfo:
    """Describes a single import conflict."""

    asset_entry: AssetEntry
    existing_path: Path
    reason: str


@dataclass
class ExportOptions:
    """Options controlling an asset export operation."""

    workspace_dir: Path
    include_preferences: bool = True
    include_memories: bool = True
    include_skills: bool = True
    include_tools: bool = True
    include_global_config: bool = True
    output_path: Optional[Path] = None


@dataclass
class ExportResult:
    """Result returned after a successful export."""

    zip_path: Path
    manifest: AssetManifest
    total_size_bytes: int
    asset_count: int


@dataclass
class ImportResult:
    """Result returned after an import operation."""

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    conflicts: list[ConflictInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BackupConfig:
    """Configuration for the daily backup scheduler."""

    enabled: bool = False
    schedule: str = "0 2 * * *"
    retention_days: int = 7
    max_backups: int = 30
    include_types: list[AssetType] = field(
        default_factory=lambda: list(AssetType),
    )


@dataclass
class BackupResult:
    """Result returned after a backup operation."""

    backup_path: Path
    timestamp: str
    size_bytes: int
    asset_count: int
    success: bool
    error: Optional[str] = None


@dataclass
class VersionInfo:
    """Parsed schema version information."""

    prefix: str
    major: int
    minor: int = 0


@dataclass
class CompatibilityResult:
    """Result of a version compatibility check."""

    level: CompatibilityLevel
    source_version: Optional[VersionInfo]
    target_version: VersionInfo
    migration_needed: bool
    migration_path: list[str] = field(default_factory=list)
    message: str = ""
