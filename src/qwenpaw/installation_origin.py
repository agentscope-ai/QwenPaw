# -*- coding: utf-8 -*-
"""Installer-owned resource identity for platform feedback links.

Never infer provenance from package metadata, display names, or local ids.
Only a successful install from a canonical platform URL creates a record.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from .utils.io_utils import write_json_atomic

_PLATFORM = "https://platform.agentscope.io"
_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_UUID = re.compile(
    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z",
)


class InstallationOrigin(BaseModel):
    """A platform identity retained separately from a package manifest."""

    model_config = ConfigDict(extra="forbid")
    provider: Literal["agentscope-platform"] = "agentscope-platform"
    resource_id: str
    resource_type: Literal["plugin", "app", "skill"]
    installed_version: str | None = None
    source_url: str


def origin_from_platform_url(
    source_url: str,
    resource_type: Literal["plugin", "app", "skill"],
    installed_version: str | None = None,
) -> dict[str, Any] | None:
    """Parse only HTTPS platform resource/archive URLs used by installers."""
    try:
        parsed = urlparse(source_url)
    except ValueError:
        return None
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    collection = "skills" if resource_type == "skill" else "plugins"
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "platform.agentscope.io"
        or parsed.query
        or parsed.fragment
        or parts[0] != collection
    ):
        return None
    if len(parts) == 2 and _UUID.fullmatch(parts[1]):
        resource_id = parts[1]
        canonical_path = f"/{collection}/{resource_id}"
    elif len(parts) in (3, 6):
        owner = parts[1].removeprefix("@")
        name = parts[2]
        if not all(
            _PART.fullmatch(p) and p not in {".", ".."} for p in (owner, name)
        ):
            return None
        if len(parts) == 6 and (
            parts[3:5] != ["archive", "zip"]
            or not _PART.fullmatch(parts[5])
            or parts[5] in {".", ".."}
        ):
            return None
        resource_id = f"@{owner}/{name}"
        canonical_path = f"/{collection}/@{quote(owner)}/{quote(name)}"
    else:
        return None
    return InstallationOrigin(
        resource_id=resource_id,
        resource_type=resource_type,
        installed_version=installed_version or None,
        source_url=f"{_PLATFORM}{canonical_path}",
    ).model_dump(exclude_none=True)


def validated_origin(value: Any) -> dict[str, Any] | None:
    """Read a stored record, never recover missing identity from a name."""
    try:
        origin = InstallationOrigin.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        return None
    canonical = origin_from_platform_url(
        origin.source_url,
        origin.resource_type,
        origin.installed_version,
    )
    if canonical is None or canonical["resource_id"] != origin.resource_id:
        return None
    return canonical


def _record_path(plugins_dir: Path, plugin_id: str) -> Path:
    key = hashlib.sha256(plugin_id.encode("utf-8")).hexdigest()
    return plugins_dir / ".installation-origins" / f"{key}.json"


def write_plugin_origin(
    plugins_dir: Path,
    plugin_id: str,
    origin: dict[str, Any] | None,
) -> None:
    """Replace provenance on every install; local installs clear it."""
    path = _record_path(plugins_dir, plugin_id)
    normalized = validated_origin(origin)
    if normalized is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {"local_id": plugin_id, "origin": normalized})


def read_plugin_origin(
    plugins_dir: Path,
    plugin_id: str,
) -> dict[str, Any] | None:
    """Read installer metadata outside the untrusted package directory."""
    try:
        record = json.loads(_record_path(plugins_dir, plugin_id).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("local_id") != plugin_id:
        return None
    return validated_origin(record.get("origin"))
