# -*- coding: utf-8 -*-
"""Asset import engine.

Validates and imports asset packages into a workspace.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from qwenpaw.backup.errors import (
    IncompatibleVersionError,
    InsufficientStorageError,
    InvalidAssetPackageError,
)
from qwenpaw.backup.models import (
    AssetEntry,
    AssetManifest,
    AssetType,
    CompatibilityLevel,
    ConflictInfo,
    ConflictStrategy,
    ImportResult,
)
from qwenpaw.backup.sanitizer import SENSITIVE_FIELDS
from qwenpaw.backup.version_checker import (
    check_compatibility,
    migrate_manifest,
    parse_version,
)

logger = logging.getLogger(__name__)

MAX_ZIP_SIZE_BYTES: int = 500 * 1024 * 1024
MAX_DECOMPRESSED_SIZE_BYTES: int = 1 * 1024 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _generate_rename_path(relative_path: str) -> str:
    """``preferences/config.json`` → ``preferences/config.conflict.json``"""
    p = Path(relative_path)
    return str(p.with_name(f"{p.stem}.conflict{p.suffix}"))


def _merge_preferences(existing: dict, incoming: dict) -> dict:
    """Merge *incoming* into *existing*, preserving sensitive field values."""
    merged: dict = {}
    for key, inc_val in incoming.items():
        ext_val = existing.get(key)

        if key in SENSITIVE_FIELDS and ext_val is not None:
            merged[key] = ext_val
        elif isinstance(inc_val, dict) and isinstance(ext_val, dict):
            merged[key] = _merge_preferences(ext_val, inc_val)
        elif (
            isinstance(inc_val, list)
            and isinstance(ext_val, list)
            and len(ext_val) == len(inc_val)
        ):
            merged[key] = [
                _merge_preferences(e, i)
                if isinstance(e, dict) and isinstance(i, dict)
                else i
                for e, i in zip(ext_val, inc_val)
            ]
        else:
            merged[key] = inc_val

    for key, val in existing.items():
        merged.setdefault(key, val)
    return merged


class AssetImporter:
    """Validates and imports asset packages into a target workspace."""

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = workspace_dir

    def _validate_zip(self, zip_path: Path) -> AssetManifest:
        """Validate ZIP and return its manifest.

        Raises InvalidAssetPackageError.
        """
        if not zip_path.exists():
            raise InvalidAssetPackageError(
                f"ZIP file not found: {zip_path}",
            )
        if zip_path.stat().st_size > MAX_ZIP_SIZE_BYTES:
            raise InvalidAssetPackageError(
                "ZIP file exceeds 500 MB limit",
            )

        try:
            zf = zipfile.ZipFile(zip_path, "r")
        except zipfile.BadZipFile as exc:
            raise InvalidAssetPackageError(f"Invalid ZIP file: {exc}") from exc

        with zf:
            if "manifest.json" not in zf.namelist():
                raise InvalidAssetPackageError(
                    "manifest.json not found in ZIP archive",
                )
            try:
                manifest = AssetManifest.model_validate(
                    json.loads(zf.read("manifest.json")),
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                raise InvalidAssetPackageError(
                    f"Invalid manifest.json: {exc}",
                ) from exc

            target_resolved = self._workspace_dir.resolve()
            total_decompressed = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if ".." in name.split("/"):
                    raise InvalidAssetPackageError(
                        "Path traversal detected in" f" ZIP entry: {name!r}",
                    )
                resolved = (target_resolved / name).resolve()
                try:
                    resolved.relative_to(target_resolved)
                except ValueError as exc:
                    raise InvalidAssetPackageError(
                        "ZIP entry resolves outside"
                        f" target directory: {name!r}",
                    ) from exc
                total_decompressed += info.file_size

            if total_decompressed > MAX_DECOMPRESSED_SIZE_BYTES:
                raise InvalidAssetPackageError(
                    f"Decompressed size"
                    f" ({total_decompressed} bytes)"
                    " exceeds 1 GB limit",
                )
        return manifest

    def _detect_conflicts(
        self,
        manifest: AssetManifest,
        target_dir: Path,
        strategy: ConflictStrategy,
    ) -> tuple[list[AssetEntry], list[AssetEntry], list[ConflictInfo]]:
        """Return (to_import, to_skip, conflicts)."""
        to_import: list[AssetEntry] = []
        to_skip: list[AssetEntry] = []
        conflicts: list[ConflictInfo] = []

        for entry in manifest.assets:
            target_path = target_dir / entry.relative_path
            if not target_path.exists():
                to_import.append(entry)
                continue

            if _sha256(target_path.read_bytes()) == entry.sha256:
                to_skip.append(entry)
                continue

            conflict = ConflictInfo(
                asset_entry=entry,
                existing_path=target_path,
                reason="内容不同",
            )
            if strategy == ConflictStrategy.OVERWRITE:
                to_import.append(entry)
            elif strategy == ConflictStrategy.SKIP:
                to_skip.append(entry)
                conflicts.append(conflict)
            elif strategy == ConflictStrategy.RENAME:
                renamed = entry.model_copy(
                    update={
                        "relative_path": _generate_rename_path(
                            entry.relative_path,
                        ),
                    },
                )
                to_import.append(renamed)
                conflicts.append(conflict)
            else:  # ASK
                conflicts.append(conflict)

        return to_import, to_skip, conflicts

    def _apply_asset(
        self,
        entry: AssetEntry,
        data: bytes,
        strategy: ConflictStrategy,  # pylint: disable=unused-argument  # noqa: E501
    ) -> None:
        """Write a single asset.

        Merges sensitive fields for preference files.
        """
        target_path = self._workspace_dir / entry.relative_path
        if entry.asset_type == AssetType.PREFERENCES and target_path.exists():
            try:
                existing = json.loads(target_path.read_text(encoding="utf-8"))
                incoming = json.loads(data.decode("utf-8"))
                data = json.dumps(
                    _merge_preferences(existing, incoming),
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)

    def _migrate_if_needed(
        self,
        zip_path: Path,
        manifest: AssetManifest,
    ) -> AssetManifest:
        """Check version compatibility; auto-migrate if MIGRATABLE."""
        compat = check_compatibility(manifest)
        if compat.level == CompatibilityLevel.INCOMPATIBLE:
            raise IncompatibleVersionError(compat.message)
        if compat.level == CompatibilityLevel.FULL:
            return manifest
        with zipfile.ZipFile(zip_path, "r") as zf:
            raw = json.loads(zf.read("manifest.json"))
        migrated = migrate_manifest(
            raw,
            parse_version(manifest.schema_version),
            compat.target_version,
        )
        return AssetManifest.model_validate(migrated)

    @staticmethod
    def _check_disk_space(target_dir: Path, needed_bytes: int) -> None:
        try:
            disk = shutil.disk_usage(
                target_dir if target_dir.exists() else Path.home(),
            )
            if disk.free < needed_bytes * 2:
                raise InsufficientStorageError(
                    f"Insufficient disk space:"
                    f" {disk.free} free,"
                    f" need {needed_bytes * 2}",
                )
        except OSError:
            pass

    @staticmethod
    def _resolve_zip_path(
        entry: AssetEntry,
        zip_names: set[str],
        manifest: AssetManifest,
    ) -> Optional[str]:
        """Find actual ZIP path for *entry* (handles RENAME fallback)."""
        if entry.relative_path in zip_names:
            return entry.relative_path
        for orig in manifest.assets:
            if (
                orig.sha256 == entry.sha256
                and orig.name == entry.name
                and orig.relative_path in zip_names
            ):
                return orig.relative_path
        return None

    def _import_one(
        self,
        entry: AssetEntry,
        zf: zipfile.ZipFile,
        zip_names: set[str],
        manifest: AssetManifest,
        strategy: ConflictStrategy,
        result: ImportResult,
    ) -> None:
        """Read, verify, and write one asset entry."""
        zip_path = self._resolve_zip_path(entry, zip_names, manifest)
        if zip_path is None:
            result.errors.append(
                f"File not found in ZIP: {entry.relative_path}",
            )
            return
        data = zf.read(zip_path)
        actual_sha = _sha256(data)
        if actual_sha != entry.sha256:
            result.errors.append(
                f"SHA256 mismatch for"
                f" {entry.relative_path}:"
                f" expected {entry.sha256},"
                f" got {actual_sha}",
            )
            return
        self._apply_asset(entry, data, strategy)
        result.imported.append(entry.relative_path)

    async def import_assets(
        self,
        zip_path: Path,
        strategy: ConflictStrategy = ConflictStrategy.ASK,
        asset_types: Optional[list[AssetType]] = None,
    ) -> ImportResult:
        """Import assets from a ZIP package into the workspace."""
        result = ImportResult()
        manifest = self._migrate_if_needed(
            zip_path,
            self._validate_zip(zip_path),
        )

        if asset_types is not None:
            type_set = set(asset_types)
            manifest = manifest.model_copy(
                update={
                    "assets": [
                        e for e in manifest.assets if e.asset_type in type_set
                    ],
                },
            )

        self._check_disk_space(
            self._workspace_dir,
            sum(e.size_bytes for e in manifest.assets),
        )

        to_import, to_skip, conflicts = self._detect_conflicts(
            manifest,
            self._workspace_dir,
            strategy,
        )
        result.skipped = [e.relative_path for e in to_skip]
        result.conflicts = conflicts

        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_names = set(zf.namelist())
            for entry in to_import:
                try:
                    self._import_one(
                        entry,
                        zf,
                        zip_names,
                        manifest,
                        strategy,
                        result,
                    )
                except Exception as exc:
                    result.errors.append(
                        f"Error importing {entry.relative_path}: {exc}",
                    )
        return result
