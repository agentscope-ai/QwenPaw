# -*- coding: utf-8 -*-
"""Version compatibility checker and schema migration for asset packages."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Callable

from copaw.backup.errors import IncompatibleVersionError
from copaw.backup.models import (
    AssetManifest,
    CompatibilityLevel,
    CompatibilityResult,
    VersionInfo,
)

CURRENT_SCHEMA_VERSION: str = "copaw-assets.v1"

# Minimum CoPaw version that can produce valid v1 packages
_MIN_COPAW_VERSION: str = "0.1.0"

# Required top-level manifest fields
_REQUIRED_MANIFEST_FIELDS: set[str] = {
    "schema_version",
    "created_at",
    "source_agent_id",
    "source_device_id",
    "copaw_version",
    "assets",
}

# Required fields per asset entry
_REQUIRED_ENTRY_FIELDS: set[str] = {
    "asset_type",
    "name",
    "relative_path",
    "sha256",
    "size_bytes",
}

# Valid asset type values
_VALID_ASSET_TYPES: set[str] = {
    "preferences",
    "memories",
    "skills",
    "tools",
    "global_config",
}

# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------
# Maps (from_major, to_major) to a function that transforms the manifest dict.
_MIGRATIONS: dict[tuple[int, int], Callable[[dict], dict]] = {
    # Example: (1, 2): migrate_v1_to_v2,
}

# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(
    r"^(?P<prefix>.+)\.v(?P<major>\d+)(?:\.(?P<minor>\d+))?$",
)


def parse_version(version_str: str) -> VersionInfo:
    """Parse a schema version string into a :class:`VersionInfo`.

    Supported formats::

        copaw-assets.v1
        copaw-assets.v2.1

    Raises :class:`ValueError` for invalid formats.
    """
    match = _VERSION_RE.match(version_str)
    if not match:
        raise ValueError(f"无效的版本格式: {version_str}")
    return VersionInfo(
        prefix=match.group("prefix"),
        major=int(match.group("major")),
        minor=int(match.group("minor") or 0),
    )


# ---------------------------------------------------------------------------
# Compatibility check
# ---------------------------------------------------------------------------


def check_compatibility(manifest: AssetManifest) -> CompatibilityResult:
    """Check compatibility of *manifest* with current version."""
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
            message=f"无法解析版本号: {manifest.schema_version}",
        )

    # Step 2: prefix mismatch → INCOMPATIBLE
    if source.prefix != target.prefix:
        return CompatibilityResult(
            level=CompatibilityLevel.INCOMPATIBLE,
            source_version=source,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message=f"不支持的资产包格式: {source.prefix}",
        )

    # Step 3: same major → FULL
    # (minor differences are forward/backward compatible)
    if source.major == target.major:
        return CompatibilityResult(
            level=CompatibilityLevel.FULL,
            source_version=source,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message="版本完全兼容",
        )

    # Step 4: source major > target major → INCOMPATIBLE
    if source.major > target.major:
        return CompatibilityResult(
            level=CompatibilityLevel.INCOMPATIBLE,
            source_version=source,
            target_version=target,
            migration_needed=False,
            migration_path=[],
            message=(
                f"资产包版本 v{source.major}"
                f" 高于当前系统 v{target.major}，"
                "请升级 CoPaw"
            ),
        )

    # Step 5: source major < target major → check migration path
    migration_path = get_migration_path(source, target)
    if migration_path:
        return CompatibilityResult(
            level=CompatibilityLevel.MIGRATABLE,
            source_version=source,
            target_version=target,
            migration_needed=True,
            migration_path=migration_path,
            message=f"需要迁移: {' -> '.join(migration_path)}",
        )

    return CompatibilityResult(
        level=CompatibilityLevel.INCOMPATIBLE,
        source_version=source,
        target_version=target,
        migration_needed=False,
        migration_path=[],
        message=(f"缺少从 v{source.major}" f" 到 v{target.major} 的迁移路径"),
    )


# ---------------------------------------------------------------------------
# Strict manifest validation
# ---------------------------------------------------------------------------


def validate_manifest_strict(  # pylint: disable=too-many-branches
    manifest_data: dict,
) -> list[str]:
    """Perform strict validation on raw manifest data.

    Returns a list of warning/error strings.
    Empty list means valid.
    """
    issues: list[str] = []

    # Check required top-level fields
    for field in _REQUIRED_MANIFEST_FIELDS:
        if field not in manifest_data:
            issues.append(f"Missing required field: {field}")

    # Validate schema_version format
    sv = manifest_data.get("schema_version", "")
    if sv:
        try:
            parse_version(sv)
        except ValueError:
            issues.append(f"Invalid schema_version format: {sv!r}")

    # Validate copaw_version is present and non-empty
    cv = manifest_data.get("copaw_version", "")
    if not cv or not isinstance(cv, str):
        issues.append("copaw_version is missing or empty")

    # Validate created_at is present and non-empty
    ca = manifest_data.get("created_at", "")
    if not ca or not isinstance(ca, str):
        issues.append("created_at is missing or empty")

    # Validate source identifiers
    for id_field in ("source_agent_id", "source_device_id"):
        val = manifest_data.get(id_field, "")
        if not val or not isinstance(val, str):
            issues.append(f"{id_field} is missing or empty")

    # Validate assets array
    assets = manifest_data.get("assets")
    if assets is None:
        return issues  # already reported above
    if not isinstance(assets, list):
        issues.append(
            "assets should be a list," f" got {type(assets).__name__}",
        )
        return issues

    seen_paths: set[str] = set()
    for i, entry in enumerate(assets):
        if not isinstance(entry, dict):
            issues.append(
                f"assets[{i}]: expected dict, got {type(entry).__name__}",
            )
            continue

        # Required entry fields
        for field in _REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                issues.append(f"assets[{i}]: missing field '{field}'")

        # Validate asset_type value
        atype = entry.get("asset_type", "")
        if atype and atype not in _VALID_ASSET_TYPES:
            issues.append(f"assets[{i}]: unknown asset_type '{atype}'")

        # Validate sha256 format (64 hex chars)
        sha = entry.get("sha256", "")
        if sha and (
            len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha)
        ):
            issues.append(f"assets[{i}]: invalid sha256 format")

        # Validate size_bytes is non-negative
        size = entry.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size < 0):
            issues.append(f"assets[{i}]: invalid size_bytes: {size}")

        # Check for duplicate paths
        rp = entry.get("relative_path", "")
        if rp:
            if rp in seen_paths:
                issues.append(f"assets[{i}]: duplicate relative_path '{rp}'")
            seen_paths.add(rp)

    return issues


def validate_package(  # pylint: disable=too-many-statements
    zip_path: Path,
) -> dict:
    """Validate a ZIP asset package comprehensively.

    Returns a dict with keys:
    - valid (bool): overall pass/fail
    - compatibility (CompatibilityResult or None)
    - manifest_issues (list[str]): strict validation issues
    - zip_issues (list[str]): ZIP structure issues
    - summary (str): human-readable summary
    """
    result: dict = {
        "valid": True,
        "compatibility": None,
        "manifest_issues": [],
        "zip_issues": [],
        "summary": "",
    }

    zip_path = Path(zip_path)
    if not zip_path.exists():
        result["valid"] = False
        result["zip_issues"].append(f"File not found: {zip_path}")
        result["summary"] = "File not found"
        return result

    # Open ZIP
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        result["valid"] = False
        result["zip_issues"].append(f"Invalid ZIP: {exc}")
        result["summary"] = "Invalid ZIP file"
        return result

    with zf:
        # Check manifest exists
        if "manifest.json" not in zf.namelist():
            result["valid"] = False
            result["zip_issues"].append("manifest.json not found")
            result["summary"] = "Missing manifest.json"
            return result

        # Parse manifest
        try:
            raw = json.loads(zf.read("manifest.json"))
        except json.JSONDecodeError as exc:
            result["valid"] = False
            result["manifest_issues"].append(f"Invalid JSON: {exc}")
            result["summary"] = "Malformed manifest.json"
            return result

        # Strict manifest validation
        issues = validate_manifest_strict(raw)
        result["manifest_issues"] = issues

        # Version compatibility
        try:
            manifest = AssetManifest.model_validate(raw)
            compat = check_compatibility(manifest)
            result["compatibility"] = compat
        except Exception as exc:
            result["valid"] = False
            result["manifest_issues"].append(f"Manifest parse error: {exc}")
            result["summary"] = "Cannot parse manifest"
            return result

        # Check ZIP entries match manifest assets
        zip_names = set(zf.namelist())
        for entry_data in raw.get("assets", []):
            rp = entry_data.get("relative_path", "")
            if rp and rp not in zip_names:
                result["zip_issues"].append(
                    f"Manifest references missing file: {rp}",
                )

        # Check for path traversal
        for name in zf.namelist():
            if ".." in name.split("/"):
                result["zip_issues"].append(f"Path traversal: {name}")

    if issues or result["zip_issues"]:
        result["valid"] = False

    # Build summary
    compat = result["compatibility"]
    parts = []
    if compat:
        parts.append(
            f"Schema: {raw.get('schema_version', '?')}"
            f" → {CURRENT_SCHEMA_VERSION}",
        )
        parts.append(f"Compatibility: {compat.level.value}")
        if compat.level == CompatibilityLevel.INCOMPATIBLE:
            result["valid"] = False
    n_issues = len(result["manifest_issues"]) + len(result["zip_issues"])
    parts.append(f"Issues: {n_issues}")
    parts.append(f"Assets: {len(raw.get('assets', []))}")
    result["summary"] = " | ".join(parts)

    return result


# ---------------------------------------------------------------------------
# Migration path
# ---------------------------------------------------------------------------


def get_migration_path(source: VersionInfo, target: VersionInfo) -> list[str]:
    """Compute the chain migration path from *source* to *target*.

    Returns a list like ``["v1 -> v2", "v2 -> v3"]`` when every step has a
    registered migration function, or an empty list if the chain is broken.
    """
    path: list[str] = []
    current = source.major
    while current < target.major:
        next_ver = current + 1
        if (current, next_ver) not in _MIGRATIONS:
            return []  # chain broken
        path.append(f"v{current} -> v{next_ver}")
        current = next_ver
    return path


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def migrate_manifest(
    manifest_data: dict,
    source: VersionInfo,
    target: VersionInfo,
) -> dict:
    """Execute chain migration from *source* to *target* on *manifest_data*.

    Each step applies the registered migration function and updates
    ``schema_version`` in the result dict.

    Raises :class:`IncompatibleVersionError` if a migration
    function is missing.
    """
    current = source.major
    data = manifest_data.copy()

    while current < target.major:
        next_ver = current + 1
        migration_fn = _MIGRATIONS.get((current, next_ver))
        if migration_fn is None:
            raise IncompatibleVersionError(
                f"缺少从 v{current} 到 v{next_ver} 的迁移函数",
            )
        data = migration_fn(data)
        data["schema_version"] = f"{target.prefix}.v{next_ver}"
        current = next_ver

    return data
