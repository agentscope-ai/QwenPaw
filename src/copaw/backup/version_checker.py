# -*- coding: utf-8 -*-
"""Version compatibility checker for user asset backup & migration.

Provides version parsing, compatibility checking, migration path
calculation, and chain migration for asset package schema versions.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Callable, Optional

from copaw.backup.errors import IncompatibleVersionError
from copaw.backup.models import (
    AssetManifest,
    CompatibilityLevel,
    CompatibilityResult,
    VersionInfo,
)

# ---------------------------------------------------------------------------
# Migration function registry
# ---------------------------------------------------------------------------
# Maps (from_major, to_major) to a callable that transforms the manifest dict.
# Currently empty — no actual migrations exist yet.
_MIGRATIONS: dict[tuple[int, int], Callable[[dict], dict]] = {}


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------
CURRENT_SCHEMA_VERSION: str = "copaw-assets.v1"


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def parse_version(version_str: str) -> VersionInfo:
    """Parse a schema version string into a :class:`VersionInfo`.

    Supported formats::

        copaw-assets.v1
        copaw-assets.v2.1

    Raises :class:`ValueError` for invalid formats.
    """
    pattern = r"^(?P<prefix>.+)\.v(?P<major>\d+)(?:\.(?P<minor>\d+))?$"
    match = re.match(pattern, version_str)
    if not match:
        raise ValueError(f"Invalid version format: {version_str}")
    return VersionInfo(
        prefix=match.group("prefix"),
        major=int(match.group("major")),
        minor=int(match.group("minor") or 0),
    )


def check_compatibility(
    manifest: AssetManifest,
) -> CompatibilityResult:
    """Check version compatibility.

    Compares an asset manifest against the current system.

    Returns a :class:`CompatibilityResult` describing the compatibility level,
    whether migration is needed, and the migration path (if any).
    """
    target = parse_version(CURRENT_SCHEMA_VERSION)

    # Step 1: parse source version
    try:
        source = parse_version(manifest.schema_version)
    except ValueError:
        return CompatibilityResult(
            level=CompatibilityLevel.INCOMPATIBLE,
            source_version=None,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message=f"Cannot parse version: {manifest.schema_version}",
        )

    # Step 2: check prefix
    if source.prefix != target.prefix:
        return CompatibilityResult(
            level=CompatibilityLevel.INCOMPATIBLE,
            source_version=source,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message=f"Unsupported asset package format: {source.prefix}",
        )

    # Step 3: compare major versions
    if source.major == target.major:
        return CompatibilityResult(
            level=CompatibilityLevel.FULL,
            source_version=source,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message="Fully compatible",
        )

    if source.major > target.major:
        return CompatibilityResult(
            level=CompatibilityLevel.INCOMPATIBLE,
            source_version=source,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message=(
                f"Asset package v{source.major} is newer than "
                f"current system v{target.major}. Please upgrade CoPaw."
            ),
        )

    # Step 4: source.major < target.major — check migration path
    migration_path = get_migration_path(source, target)
    if migration_path:
        return CompatibilityResult(
            level=CompatibilityLevel.MIGRATABLE,
            source_version=source,
            target_version=target,
            migration_needed=True,
            migration_path=migration_path,
            message=f"Migration required: {' -> '.join(migration_path)}",
        )

    s, t = source.major, target.major
    msg = f"Missing migration path from v{s} to v{t}"
    return CompatibilityResult(
        level=CompatibilityLevel.INCOMPATIBLE,
        source_version=source,
        target_version=target,
        migration_needed=False,
        migration_path=[],
        message=msg,
    )


def get_migration_path(source: VersionInfo, target: VersionInfo) -> list[str]:
    """Calculate the chain migration path from *source* to *target*.

    Returns a list like ``["v1 -> v2", "v2 -> v3"]``.
    Returns an empty list if any step is missing from :data:`_MIGRATIONS`.
    """
    path: list[str] = []
    current = source.major
    while current < target.major:
        next_ver = current + 1
        if (current, next_ver) not in _MIGRATIONS:
            return []  # migration chain is broken
        path.append(f"v{current} -> v{next_ver}")
        current = next_ver
    return path


def migrate_manifest(
    manifest_data: dict,
    source: VersionInfo,
    target: VersionInfo,
) -> dict:
    """Apply chain migration from *source* to *target* on *manifest_data*.

    Each step invokes the registered migration function and updates the
    ``schema_version`` key in the resulting dict.

    Raises :class:`IncompatibleVersionError` if a required migration
    function is missing.

    When ``source.major >= target.major`` the while-loop does not execute
    and the data is returned unchanged (no downgrade support).
    """
    current = source.major
    data = manifest_data.copy()

    while current < target.major:
        next_ver = current + 1
        migration_fn = _MIGRATIONS.get((current, next_ver))
        if migration_fn is None:
            raise IncompatibleVersionError(
                f"Missing migration function from v{current} to v{next_ver}",
            )
        data = migration_fn(data)
        data["schema_version"] = f"copaw-assets.v{next_ver}"
        current = next_ver

    return data


# ---------------------------------------------------------------------------
# VersionChecker class (convenience wrapper)
# ---------------------------------------------------------------------------


class VersionChecker:
    """High-level version compatibility checker.

    Wraps the module-level functions for use as an injectable service.
    """

    CURRENT_SCHEMA_VERSION: str = CURRENT_SCHEMA_VERSION

    @staticmethod
    def parse_version(version_str: str) -> VersionInfo:
        return parse_version(version_str)

    @staticmethod
    def check_compatibility(manifest: AssetManifest) -> CompatibilityResult:
        return check_compatibility(manifest)

    @staticmethod
    def get_migration_path(
        source: VersionInfo,
        target: VersionInfo,
    ) -> list[str]:
        return get_migration_path(source, target)

    @staticmethod
    def migrate_manifest(
        manifest_data: dict,
        source: VersionInfo,
        target: VersionInfo,
    ) -> dict:
        return migrate_manifest(manifest_data, source, target)


# ---------------------------------------------------------------------------
# Package validation (used by CLI ``copaw assets verify``)
# ---------------------------------------------------------------------------


def validate_package(zip_path: Path) -> dict:
    """Validate a ZIP asset package and return a diagnostic report.

    Returns a dict with keys:
    - ``valid`` (bool)
    - ``compatibility`` (CompatibilityResult | None)
    - ``manifest_issues`` (list[str])
    - ``zip_issues`` (list[str])
    """
    manifest_issues: list[str] = []
    zip_issues: list[str] = []
    compat: Optional[CompatibilityResult] = None

    if not zip_path.exists():
        return {
            "valid": False,
            "compatibility": None,
            "manifest_issues": [f"File not found: {zip_path}"],
            "zip_issues": [],
        }

    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        return {
            "valid": False,
            "compatibility": None,
            "manifest_issues": [f"Invalid ZIP file: {exc}"],
            "zip_issues": [],
        }

    with zf:
        names = set(zf.namelist())

        # Check manifest.json
        if "manifest.json" not in names:
            manifest_issues.append("manifest.json not found in ZIP")
        else:
            try:
                raw = json.loads(zf.read("manifest.json"))
                manifest = AssetManifest.model_validate(raw)
                compat = check_compatibility(manifest)

                # Verify referenced paths exist
                for entry in manifest.assets:
                    if entry.relative_path not in names:
                        rp = entry.relative_path
                        zip_issues.append(f"Missing file: {rp}")
            except (json.JSONDecodeError, Exception) as exc:
                manifest_issues.append(f"Invalid manifest.json: {exc}")

        # Check for path traversal
        for name in names:
            if ".." in name.split("/"):
                zip_issues.append(f"Path traversal detected: {name!r}")

    valid = (
        not manifest_issues
        and not zip_issues
        and compat is not None
        and compat.level.value != "incompatible"
    )

    return {
        "valid": valid,
        "compatibility": compat,
        "manifest_issues": manifest_issues,
        "zip_issues": zip_issues,
    }
