# -*- coding: utf-8 -*-
"""Path resolution helpers for configuration-owned directories."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR


DEFAULT_AGENT_WORKSPACE_ROOT_ID = "default"
_WORKSPACE_ROOT_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$",
)


def _working_dir_path(working_dir: Path | None) -> Path:
    """Return one absolute QwenPaw working directory."""
    base = Path(working_dir or WORKING_DIR).expanduser()
    if not base.is_absolute():
        base = Path(os.path.abspath(base))
    return Path(os.path.realpath(base))


def _canonical_path(path: Path) -> Path:
    """Return a canonical path without requiring it to exist."""
    return Path(os.path.realpath(os.fspath(path)))


def _reject_filesystem_root(path: Path, *, label: str) -> Path:
    """Reject a path that resolves to a filesystem root."""
    if path == Path(path.anchor):
        raise ValueError(f"{label} must not be a filesystem root")
    return path


def _resolve_contained_path(root: Path, child: str) -> Path:
    """Resolve one child and reject symlink or traversal escapes."""
    resolved_root = os.path.realpath(os.fspath(root))
    resolved_child = os.path.realpath(
        os.path.join(resolved_root, child),
    )
    try:
        common_path = os.path.commonpath(
            [resolved_root, resolved_child],
        )
    except ValueError as exc:
        raise ValueError(
            f"Path '{child}' escapes its configured root",
        ) from exc
    if os.path.normcase(common_path) != os.path.normcase(resolved_root):
        raise ValueError(
            f"Path '{child}' escapes its configured root",
        )
    return Path(resolved_child)


def sanitize_agent_path_segment(agent_id: str) -> str:
    """Return an agent ID that is safe to use as one path segment."""
    safe_agent_id = os.path.basename(agent_id)
    if (
        not agent_id
        or agent_id in {".", ".."}
        or agent_id != safe_agent_id
        or "/" in agent_id
        or "\\" in agent_id
    ):
        raise ValueError(
            f"Agent ID '{agent_id}' is not a valid path segment",
        )
    return safe_agent_id


def sanitize_workspace_root_id(root_id: str) -> str:
    """Return a normalized workspace root identifier."""
    normalized = root_id.strip()
    if not _WORKSPACE_ROOT_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid workspace root ID '{root_id}'")
    return normalized


def resolve_configured_path(
    value: str | Path,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve configured paths relative to QwenPaw's working directory."""
    base = _working_dir_path(working_dir)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return _canonical_path(path)


def resolve_agent_workspace_path(
    workspace_dir: str | Path | None,
    agent_id: str,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve a legacy workspace path or its default location."""
    base = _working_dir_path(working_dir)
    if workspace_dir is None or not str(workspace_dir).strip():
        safe_agent_id = sanitize_agent_path_segment(agent_id)
        return _resolve_contained_path(
            base / "workspaces",
            safe_agent_id,
        )
    return resolve_configured_path(workspace_dir, working_dir=base)


def resolve_agent_workspace_roots(
    configured_roots: Mapping[str, str | Path],
    *,
    working_dir: Path | None = None,
) -> dict[str, Path]:
    """Resolve locally configured roots that may contain workspaces."""
    base = _working_dir_path(working_dir)
    roots = {
        DEFAULT_AGENT_WORKSPACE_ROOT_ID: _canonical_path(
            base / "workspaces",
        ),
    }
    for raw_root_id, value in configured_roots.items():
        root_id = sanitize_workspace_root_id(raw_root_id)
        if root_id == DEFAULT_AGENT_WORKSPACE_ROOT_ID:
            raise ValueError(
                f"Workspace root ID '{root_id}' is reserved",
            )
        root = resolve_configured_path(value, working_dir=base)
        roots[root_id] = _reject_filesystem_root(
            root,
            label=f"Workspace root '{value}'",
        )
    return roots


def _select_workspace_root(
    root_id: str,
    roots: Mapping[str, Path],
) -> Path:
    """Select a trusted root without treating the ID as a path."""
    normalized = sanitize_workspace_root_id(root_id)
    for candidate_id, candidate_root in roots.items():
        if candidate_id == normalized:
            return candidate_root
    raise ValueError(
        f"Workspace root ID '{normalized}' is not configured",
    )


def resolve_workspace_identity(
    root_id: str,
    workspace_name: str,
    configured_roots: Mapping[str, str | Path],
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve a workspace from a trusted root and one safe name."""
    roots = resolve_agent_workspace_roots(
        configured_roots,
        working_dir=working_dir,
    )
    root = _select_workspace_root(root_id, roots)
    safe_name = sanitize_agent_path_segment(workspace_name)
    return _resolve_contained_path(root, safe_name)


def resolve_workspace_child_path(
    workspace_dir: Path,
    filename: str,
) -> Path:
    """Resolve a fixed file name inside a trusted workspace."""
    safe_filename = os.path.basename(filename)
    if safe_filename != filename or not safe_filename:
        raise ValueError(f"Invalid workspace file name '{filename}'")
    return _resolve_contained_path(workspace_dir, safe_filename)


def _legacy_root_id(path: Path) -> str:
    """Return a stable local identifier for one migrated root."""
    identity = os.path.normcase(os.fspath(path)).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:24]
    return f"legacy-{digest}"


def derive_legacy_workspace_identity(
    workspace_dir: str | Path | None,
    agent_id: str,
    configured_roots: MutableMapping[str, str],
    *,
    working_dir: Path | None = None,
) -> tuple[str, str, Path]:
    """Convert one trusted local legacy path into root/name identity."""
    safe_agent_id = sanitize_agent_path_segment(agent_id)
    if workspace_dir is None or not str(workspace_dir).strip():
        root_id = DEFAULT_AGENT_WORKSPACE_ROOT_ID
        resolved = resolve_workspace_identity(
            root_id,
            safe_agent_id,
            configured_roots,
            working_dir=working_dir,
        )
        return root_id, safe_agent_id, resolved

    resolved = _reject_filesystem_root(
        resolve_configured_path(
            workspace_dir,
            working_dir=working_dir,
        ),
        label=f"Agent workspace '{workspace_dir}'",
    )
    workspace_name = sanitize_agent_path_segment(resolved.name)
    parent = resolved.parent
    roots = resolve_agent_workspace_roots(
        configured_roots,
        working_dir=working_dir,
    )
    for root_id, root in roots.items():
        if os.path.normcase(os.fspath(root)) == os.path.normcase(
            os.fspath(parent),
        ):
            return root_id, workspace_name, resolved

    root_id = _legacy_root_id(parent)
    existing = configured_roots.get(root_id)
    if existing is not None:
        existing_path = resolve_configured_path(
            existing,
            working_dir=working_dir,
        )
        if os.path.normcase(os.fspath(existing_path)) != os.path.normcase(
            os.fspath(parent),
        ):
            raise ValueError(
                f"Workspace root ID collision for '{parent}'",
            )
    configured_roots[root_id] = os.fspath(parent)
    return root_id, workspace_name, resolved


def migrate_legacy_agent_workspace_profiles(
    data: dict[str, Any],
    *,
    working_dir: Path | None = None,
) -> bool:
    """Migrate root config workspace paths without moving user files."""
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return False
    profiles = agents.get("profiles")
    if not isinstance(profiles, dict):
        return False

    raw_roots = data.setdefault("agent_workspace_roots", {})
    if not isinstance(raw_roots, dict):
        return False
    configured_roots: MutableMapping[str, str] = raw_roots
    changed = False

    for raw_agent_id, raw_profile in profiles.items():
        if not isinstance(raw_agent_id, str) or not isinstance(
            raw_profile,
            dict,
        ):
            continue
        root_id = raw_profile.get("workspace_root_id")
        workspace_name = raw_profile.get("workspace_name")
        if isinstance(root_id, str) and isinstance(workspace_name, str):
            continue
        root_id, workspace_name, resolved = derive_legacy_workspace_identity(
            raw_profile.get("workspace_dir"),
            raw_agent_id,
            configured_roots,
            working_dir=working_dir,
        )
        raw_profile["workspace_root_id"] = root_id
        raw_profile["workspace_name"] = workspace_name
        raw_profile["workspace_dir"] = os.fspath(resolved)
        changed = True
    return changed
