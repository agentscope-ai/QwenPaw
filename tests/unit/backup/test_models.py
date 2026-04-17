# -*- coding: utf-8 -*-
"""Unit tests for backup data models."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.backup.models import (
    AssetEntry,
    AssetManifest,
    AssetType,
    BackupConfig,
    BackupResult,
    CompatibilityLevel,
    CompatibilityResult,
    ConflictStrategy,
    ExportOptions,
    ImportResult,
    VersionInfo,
)
from qwenpaw.backup.errors import (
    IncompatibleVersionError,
    InsufficientStorageError,
    InvalidAssetPackageError,
)


# ---------------------------------------------------------------------------
# AssetManifest serialization / deserialization
# ---------------------------------------------------------------------------


class TestAssetManifestSerialization:
    """Validates: Requirements 2.1, 2.2"""

    def test_manifest_round_trip_json(self) -> None:
        entry = AssetEntry(
            asset_type=AssetType.PREFERENCES,
            name="agent.json",
            relative_path="preferences/agent.json",
            sha256="abc123" * 8,
            size_bytes=1024,
        )
        manifest = AssetManifest(
            schema_version="copaw-assets.v1",
            created_at="2025-01-01T00:00:00Z",
            source_agent_id="agent-001",
            source_device_id="device-001",
            copaw_version="1.0.0b1",
            assets=[entry],
        )

        json_str = manifest.model_dump_json()
        restored = AssetManifest.model_validate_json(json_str)

        assert restored.schema_version == manifest.schema_version
        assert restored.created_at == manifest.created_at
        assert restored.source_agent_id == manifest.source_agent_id
        assert restored.source_device_id == manifest.source_device_id
        assert restored.copaw_version == manifest.copaw_version
        assert len(restored.assets) == 1
        assert restored.assets[0].name == "agent.json"
        assert restored.assets[0].sha256 == entry.sha256

    def test_manifest_from_dict(self) -> None:
        data = {
            "schema_version": "copaw-assets.v1",
            "created_at": "2025-06-01T12:00:00Z",
            "source_agent_id": "a1",
            "source_device_id": "d1",
            "copaw_version": "1.0.0",
            "assets": [
                {
                    "asset_type": "memories",
                    "name": "memory_index.json",
                    "relative_path": "memories/memory_index.json",
                    "sha256": "deadbeef" * 8,
                    "size_bytes": 512,
                },
            ],
        }
        manifest = AssetManifest.model_validate(data)
        assert manifest.assets[0].asset_type == AssetType.MEMORIES
        assert manifest.assets[0].size_bytes == 512

    def test_manifest_default_assets_empty(self) -> None:
        manifest = AssetManifest(
            created_at="2025-01-01T00:00:00Z",
            source_agent_id="a",
            source_device_id="d",
            copaw_version="1.0.0",
        )
        assert manifest.assets == []
        assert manifest.schema_version == "copaw-assets.v1"

    def test_manifest_to_dict_and_back(self) -> None:
        manifest = AssetManifest(
            created_at="2025-01-01T00:00:00Z",
            source_agent_id="a",
            source_device_id="d",
            copaw_version="1.0.0",
            assets=[
                AssetEntry(
                    asset_type=AssetType.TOOLS,
                    name="tools_config.json",
                    relative_path="tools/tools_config.json",
                    sha256="f" * 64,
                    size_bytes=256,
                    metadata={"version": 2},
                ),
            ],
        )
        d = manifest.model_dump()
        restored = AssetManifest.model_validate(d)
        assert restored == manifest


# ---------------------------------------------------------------------------
# AssetEntry validation
# ---------------------------------------------------------------------------


class TestAssetEntryValidation:
    """Validates: Requirements 2.2"""

    def test_valid_entry(self) -> None:
        entry = AssetEntry(
            asset_type=AssetType.SKILLS,
            name="my_skill",
            relative_path="skills/my_skill/SKILL.md",
            sha256="a" * 64,
            size_bytes=2048,
        )
        assert entry.asset_type == AssetType.SKILLS
        assert entry.metadata == {}

    def test_entry_with_metadata(self) -> None:
        entry = AssetEntry(
            asset_type=AssetType.PREFERENCES,
            name="config.json",
            relative_path="preferences/config.json",
            sha256="b" * 64,
            size_bytes=100,
            metadata={"partial": True},
        )
        assert entry.metadata == {"partial": True}

    def test_entry_invalid_asset_type_raises(self) -> None:
        with pytest.raises(Exception):
            AssetEntry(
                asset_type="invalid_type",  # type: ignore[arg-type]
                name="x",
                relative_path="x",
                sha256="c" * 64,
                size_bytes=0,
            )

    def test_entry_missing_required_field_raises(self) -> None:
        with pytest.raises(Exception):
            AssetEntry(
                asset_type=AssetType.TOOLS,
                name="x",
                # missing relative_path, sha256, size_bytes
            )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# VersionInfo defaults
# ---------------------------------------------------------------------------


class TestVersionInfoDefaults:
    def test_default_minor_is_zero(self) -> None:
        vi = VersionInfo(prefix="copaw-assets", major=1)
        assert vi.minor == 0

    def test_explicit_minor(self) -> None:
        vi = VersionInfo(prefix="copaw-assets", major=2, minor=3)
        assert vi.major == 2
        assert vi.minor == 3

    def test_equality(self) -> None:
        a = VersionInfo(prefix="copaw-assets", major=1, minor=0)
        b = VersionInfo(prefix="copaw-assets", major=1)
        assert a == b


# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------


class TestEnums:
    def test_asset_type_values(self) -> None:
        assert set(AssetType) == {
            AssetType.PREFERENCES,
            AssetType.MEMORIES,
            AssetType.SKILLS,
            AssetType.TOOLS,
            AssetType.GLOBAL_CONFIG,
        }

    def test_conflict_strategy_values(self) -> None:
        assert set(ConflictStrategy) == {
            ConflictStrategy.SKIP,
            ConflictStrategy.OVERWRITE,
            ConflictStrategy.RENAME,
            ConflictStrategy.ASK,
        }

    def test_compatibility_level_values(self) -> None:
        assert set(CompatibilityLevel) == {
            CompatibilityLevel.FULL,
            CompatibilityLevel.MIGRATABLE,
            CompatibilityLevel.INCOMPATIBLE,
        }


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TestCustomExceptions:
    def test_invalid_asset_package_error(self) -> None:
        err = InvalidAssetPackageError("manifest.json missing")
        assert str(err) == "manifest.json missing"
        assert isinstance(err, Exception)

    def test_incompatible_version_error(self) -> None:
        err = IncompatibleVersionError("v3 > current v1")
        assert "v3" in str(err)
        assert isinstance(err, Exception)

    def test_insufficient_storage_error(self) -> None:
        err = InsufficientStorageError("need 500MB, only 100MB free")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# Dataclass smoke tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_export_options_defaults(self) -> None:
        opts = ExportOptions(workspace_dir=Path("/tmp/ws"))
        assert opts.include_preferences is True
        assert opts.include_memories is True
        assert opts.include_skills is True
        assert opts.include_tools is True
        assert opts.output_path is None

    def test_import_result_defaults(self) -> None:
        result = ImportResult()
        assert not result.imported
        assert not result.skipped
        assert not result.conflicts
        assert not result.errors

    def test_backup_config_defaults(self) -> None:
        cfg = BackupConfig()
        assert cfg.enabled is False
        assert cfg.schedule == "0 2 * * *"
        assert cfg.retention_days == 7
        assert cfg.max_backups == 30
        assert set(cfg.include_types) == set(AssetType)

    def test_backup_result_error_optional(self) -> None:
        result = BackupResult(
            backup_path=Path("/tmp/backup.zip"),
            timestamp="2025-01-01T00:00:00Z",
            size_bytes=1024,
            asset_count=5,
            success=True,
        )
        assert result.error is None

    def test_compatibility_result_defaults(self) -> None:
        vi = VersionInfo(prefix="copaw-assets", major=1)
        cr = CompatibilityResult(
            level=CompatibilityLevel.FULL,
            source_version=vi,
            target_version=vi,
            migration_needed=False,
        )
        assert not cr.migration_path
        assert cr.message == ""
