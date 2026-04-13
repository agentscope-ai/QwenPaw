# -*- coding: utf-8 -*-
"""Unit tests for AssetImporter."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from qwenpaw.backup.errors import (
    IncompatibleVersionError,
    InvalidAssetPackageError,
)
from qwenpaw.backup.importer import (
    AssetImporter,
    _generate_rename_path,
    _merge_preferences,
)
from qwenpaw.backup.models import AssetType, ConflictStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_test_zip(
    zip_path: Path,
    files: dict[str, bytes],
    manifest_override: dict | None = None,
) -> None:
    """Build a test ZIP with given files and auto-generated manifest."""
    assets = []
    for rel_path, content in files.items():
        if rel_path == "manifest.json":
            continue
        # Determine asset type from path prefix
        if rel_path.startswith("preferences/"):
            atype = "preferences"
        elif rel_path.startswith("memories/"):
            atype = "memories"
        elif rel_path.startswith("skills/"):
            atype = "skills"
        elif rel_path.startswith("tools/"):
            atype = "tools"
        else:
            atype = "preferences"

        assets.append(
            {
                "asset_type": atype,
                "name": Path(rel_path).name,
                "relative_path": rel_path,
                "sha256": _sha256(content),
                "size_bytes": len(content),
                "metadata": {},
            },
        )

    manifest = {
        "schema_version": "copaw-assets.v1",
        "created_at": "2025-01-01T00:00:00Z",
        "source_agent_id": "test-agent",
        "source_device_id": "test-device",
        "copaw_version": "0.1.0",
        "assets": assets,
    }
    if manifest_override:
        manifest.update(manifest_override)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for rel_path, content in files.items():
            if rel_path != "manifest.json":
                zf.writestr(rel_path, content)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidateZip:
    """Tests for _validate_zip."""

    def test_missing_zip(self, tmp_path: Path) -> None:
        importer = AssetImporter(workspace_dir=tmp_path)
        with pytest.raises(InvalidAssetPackageError, match="not found"):
            importer._validate_zip(  # pylint: disable=protected-access
                tmp_path / "nonexistent.zip",
            )

    def test_invalid_zip(self, tmp_path: Path) -> None:
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_text("not a zip file")
        importer = AssetImporter(workspace_dir=tmp_path)
        with pytest.raises(InvalidAssetPackageError, match="Invalid ZIP"):
            importer._validate_zip(bad_zip)  # pylint: disable=protected-access

    def test_missing_manifest(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "no_manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("some_file.txt", "hello")
        importer = AssetImporter(workspace_dir=tmp_path)
        with pytest.raises(
            InvalidAssetPackageError,
            match="manifest.json not found",
        ):
            importer._validate_zip(  # pylint: disable=protected-access
                zip_path,
            )

    def test_invalid_manifest_json(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "bad_manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", "not valid json{{{")
        importer = AssetImporter(workspace_dir=tmp_path)
        with pytest.raises(InvalidAssetPackageError, match="Invalid manifest"):
            importer._validate_zip(  # pylint: disable=protected-access
                zip_path,
            )

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "traversal.zip"
        manifest = {
            "schema_version": "copaw-assets.v1",
            "created_at": "2025-01-01T00:00:00Z",
            "source_agent_id": "a",
            "source_device_id": "d",
            "copaw_version": "0.1.0",
            "assets": [],
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("../etc/passwd", "evil")
        importer = AssetImporter(workspace_dir=tmp_path)
        with pytest.raises(InvalidAssetPackageError, match="Path traversal"):
            importer._validate_zip(  # pylint: disable=protected-access
                zip_path,
            )

    def test_valid_zip(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "valid.zip"
        content = b'{"key": "value"}'
        _build_test_zip(zip_path, {"preferences/config.json": content})
        importer = AssetImporter(workspace_dir=tmp_path)
        manifest = importer._validate_zip(  # pylint: disable=protected-access
            zip_path,
        )
        assert len(manifest.assets) == 1


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImportAssets:
    """Tests for import_assets."""

    @pytest.mark.asyncio
    async def test_import_to_empty_workspace(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        zip_path = tmp_path / "pkg.zip"
        content = json.dumps({"setting": "value"}).encode()
        _build_test_zip(zip_path, {"preferences/config.json": content})

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        assert len(result.imported) == 1
        assert len(result.skipped) == 0
        assert (ws / "preferences" / "config.json").exists()

    @pytest.mark.asyncio
    async def test_import_skip_same_content(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        content = json.dumps({"setting": "value"}).encode()

        # Pre-create the file with same content
        pref_dir = ws / "preferences"
        pref_dir.mkdir()
        (pref_dir / "config.json").write_bytes(content)

        zip_path = tmp_path / "pkg.zip"
        _build_test_zip(zip_path, {"preferences/config.json": content})

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        assert len(result.skipped) == 1
        assert len(result.imported) == 0

    @pytest.mark.asyncio
    async def test_import_skip_different_content(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        pref_dir = ws / "preferences"
        pref_dir.mkdir()
        (pref_dir / "config.json").write_bytes(b"existing content")

        zip_path = tmp_path / "pkg.zip"
        _build_test_zip(zip_path, {"preferences/config.json": b"new content"})

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        assert len(result.skipped) == 1
        assert len(result.conflicts) == 1
        # Original file unchanged
        assert (pref_dir / "config.json").read_bytes() == b"existing content"

    @pytest.mark.asyncio
    async def test_import_overwrite(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        pref_dir = ws / "preferences"
        pref_dir.mkdir()
        (pref_dir / "config.json").write_bytes(b"old")

        new_content = b"new content"
        zip_path = tmp_path / "pkg.zip"
        _build_test_zip(zip_path, {"preferences/config.json": new_content})

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(
            zip_path,
            ConflictStrategy.OVERWRITE,
        )

        assert len(result.imported) == 1
        assert (pref_dir / "config.json").read_bytes() == new_content

    @pytest.mark.asyncio
    async def test_import_rename(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        pref_dir = ws / "preferences"
        pref_dir.mkdir()
        (pref_dir / "config.json").write_bytes(b"existing")

        new_content = b"new content"
        zip_path = tmp_path / "pkg.zip"
        _build_test_zip(zip_path, {"preferences/config.json": new_content})

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(
            zip_path,
            ConflictStrategy.RENAME,
        )

        assert len(result.imported) == 1
        # Original file unchanged
        assert (pref_dir / "config.json").read_bytes() == b"existing"
        # Renamed file created
        assert (pref_dir / "config.conflict.json").read_bytes() == new_content

    @pytest.mark.asyncio
    async def test_import_selective_types(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        zip_path = tmp_path / "pkg.zip"
        _build_test_zip(
            zip_path,
            {
                "preferences/config.json": b'{"a": 1}',
                "tools/tools_config.json": b'{"tool": true}',
            },
        )

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(
            zip_path,
            ConflictStrategy.SKIP,
            asset_types=[AssetType.PREFERENCES],
        )

        assert len(result.imported) == 1
        assert (ws / "preferences" / "config.json").exists()
        assert not (ws / "tools" / "tools_config.json").exists()

    @pytest.mark.asyncio
    async def test_import_preserves_sensitive_fields(
        self,
        tmp_path: Path,
    ) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        pref_dir = ws / "preferences"
        pref_dir.mkdir()

        existing = {"bot_token": "my-secret-token", "name": "old-name"}
        (pref_dir / "config.json").write_text(
            json.dumps(existing),
            encoding="utf-8",
        )

        incoming = {
            "bot_token": "***REDACTED***",
            "name": "new-name",
            "extra": True,
        }
        incoming_bytes = json.dumps(incoming).encode()
        zip_path = tmp_path / "pkg.zip"
        _build_test_zip(zip_path, {"preferences/config.json": incoming_bytes})

        importer = AssetImporter(workspace_dir=ws)
        await importer.import_assets(
            zip_path,
            ConflictStrategy.OVERWRITE,
        )

        merged = json.loads(
            (pref_dir / "config.json").read_text(encoding="utf-8"),
        )
        assert merged["bot_token"] == "my-secret-token"  # preserved
        assert merged["name"] == "new-name"  # updated
        assert merged["extra"] is True  # new field added

    @pytest.mark.asyncio
    async def test_import_sha256_mismatch(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        zip_path = tmp_path / "pkg.zip"

        # Build ZIP with wrong checksum in manifest
        content = b"hello world"
        manifest = {
            "schema_version": "copaw-assets.v1",
            "created_at": "2025-01-01T00:00:00Z",
            "source_agent_id": "a",
            "source_device_id": "d",
            "copaw_version": "0.1.0",
            "assets": [
                {
                    "asset_type": "preferences",
                    "name": "config.json",
                    "relative_path": "preferences/config.json",
                    "sha256": "0" * 64,
                    "size_bytes": len(content),
                    "metadata": {},
                },
            ],
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("preferences/config.json", content)

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        assert len(result.errors) == 1
        assert "SHA256 mismatch" in result.errors[0]

    @pytest.mark.asyncio
    async def test_import_incompatible_version(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        zip_path = tmp_path / "pkg.zip"
        content = b"data"
        _build_test_zip(
            zip_path,
            {"preferences/config.json": content},
            manifest_override={"schema_version": "copaw-assets.v99"},
        )

        importer = AssetImporter(workspace_dir=ws)
        with pytest.raises(IncompatibleVersionError):
            await importer.import_assets(zip_path, ConflictStrategy.SKIP)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_generate_rename_path(self) -> None:
        assert (
            _generate_rename_path("preferences/config.json")
            == "preferences/config.conflict.json"
        )
        assert (
            _generate_rename_path("tools/tool.yaml")
            == "tools/tool.conflict.yaml"
        )
        assert _generate_rename_path("file") == "file.conflict"

    def test_merge_preferences_preserves_sensitive(self) -> None:
        existing = {"bot_token": "secret", "name": "old"}
        incoming = {"bot_token": "***REDACTED***", "name": "new"}
        merged = _merge_preferences(existing, incoming)
        assert merged["bot_token"] == "secret"
        assert merged["name"] == "new"

    def test_merge_preferences_nested(self) -> None:
        existing = {
            "channels": {"discord": {"bot_token": "secret", "enabled": False}},
        }
        incoming = {
            "channels": {
                "discord": {"bot_token": "***REDACTED***", "enabled": True},
            },
        }
        merged = _merge_preferences(existing, incoming)
        assert merged["channels"]["discord"]["bot_token"] == "secret"
        assert merged["channels"]["discord"]["enabled"] is True
