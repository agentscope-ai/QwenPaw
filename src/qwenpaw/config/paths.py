# -*- coding: utf-8 -*-
"""Path resolution helpers for configuration-owned directories."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR


DEFAULT_AGENT_WORKSPACE_ROOT_ID = "default"
_WORKSPACE_ROOT_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$",
)


def _working_dir_path(working_dir: Path | None) -> Path:
    """Return one absolute QwenPaw working directory."""
    base = working_dir or WORKING_DIR
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


def _workspace_root_registry_path(working_dir: Path) -> Path:
    """Return the server-managed workspace root registry directory."""
    return working_dir / "workspace-roots"


def resolve_agent_workspace_roots(
    *,
    working_dir: Path | None = None,
) -> dict[str, Path]:
    """Enumerate server-managed roots that may contain workspaces."""
    base = _working_dir_path(working_dir)
    roots = {
        DEFAULT_AGENT_WORKSPACE_ROOT_ID: _canonical_path(
            base / "workspaces",
        ),
    }
    registry = _workspace_root_registry_path(base)
    if not registry.is_dir():
        return roots

    try:
        entries = sorted(registry.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return roots

    for entry in entries:
        try:
            root_id = sanitize_workspace_root_id(entry.name)
        except ValueError:
            continue
        if root_id == DEFAULT_AGENT_WORKSPACE_ROOT_ID or not entry.is_dir():
            continue
        root = _canonical_path(entry)
        try:
            roots[root_id] = _reject_filesystem_root(
                root,
                label=f"Workspace root '{root_id}'",
            )
        except ValueError:
            continue
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
        f"Workspace root ID '{normalized}' is not registered",
    )


def resolve_workspace_identity(
    root_id: str,
    workspace_name: str,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve a workspace from a registered root and one safe name."""
    roots = resolve_agent_workspace_roots(working_dir=working_dir)
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


def _normalize_path_text(value: str) -> str:
    """Normalize path text without interpreting it as a filesystem path."""
    normalized = value.strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    if os.name == "nt":
        normalized = normalized.casefold()
    return normalized


def _trusted_path_texts(path: Path, working_dir: Path) -> set[str]:
    """Return accepted text forms derived only from one trusted path."""
    texts = {_normalize_path_text(os.fspath(path))}
    try:
        relative = path.relative_to(working_dir)
    except ValueError:
        pass
    else:
        texts.add(_normalize_path_text(os.fspath(relative)))
    home = Path.home()
    try:
        relative_home = path.relative_to(home)
    except ValueError:
        pass
    else:
        texts.add(
            _normalize_path_text(
                f"~/{relative_home.as_posix()}",
            ),
        )
    return texts


def _registered_workspace_path_texts(
    root_id: str,
    workspace_name: str,
    *,
    working_dir: Path,
) -> tuple[Path, set[str]]:
    """Return trusted resolved and registry-alias forms for a workspace."""
    resolved = resolve_workspace_identity(
        root_id,
        workspace_name,
        working_dir=working_dir,
    )
    if root_id == DEFAULT_AGENT_WORKSPACE_ROOT_ID:
        registered_root = working_dir / "workspaces"
    else:
        registered_root = _workspace_root_registry_path(working_dir) / root_id
    candidates = _trusted_path_texts(resolved, working_dir)
    candidates.update(
        _trusted_path_texts(
            registered_root / workspace_name,
            working_dir,
        ),
    )
    return resolved, candidates


def derive_legacy_workspace_identity(
    workspace_dir: str | Path | None,
    agent_id: str,
    *,
    working_dir: Path | None = None,
) -> tuple[str, str, Path]:
    """Match one legacy workspace to an already registered root."""
    safe_agent_id = sanitize_agent_path_segment(agent_id)
    base = _working_dir_path(working_dir)
    if workspace_dir is None or not os.fspath(workspace_dir).strip():
        root_id = DEFAULT_AGENT_WORKSPACE_ROOT_ID
        resolved = resolve_workspace_identity(
            root_id,
            safe_agent_id,
            working_dir=base,
        )
        return root_id, safe_agent_id, resolved

    workspace_text = os.fspath(workspace_dir).strip()
    normalized_workspace = _normalize_path_text(workspace_text)
    workspace_name = sanitize_agent_path_segment(
        normalized_workspace.rsplit("/", maxsplit=1)[-1],
    )
    for root_id in resolve_agent_workspace_roots(working_dir=base):
        resolved, candidates = _registered_workspace_path_texts(
            root_id,
            workspace_name,
            working_dir=base,
        )
        if normalized_workspace in candidates:
            return root_id, workspace_name, resolved

    raise ValueError(
        f"Legacy workspace for agent '{safe_agent_id}' is not registered",
    )


def migrate_legacy_agent_workspace_profiles(
    data: dict[str, Any],
    *,
    working_dir: Path | None = None,
) -> bool:
    """Migrate workspace paths only when they match registered roots."""
    changed = data.pop("agent_workspace_roots", None) is not None
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return changed
    profiles = agents.get("profiles")
    if not isinstance(profiles, dict):
        return changed

    for raw_agent_id, raw_profile in profiles.items():
        if not isinstance(raw_agent_id, str) or not isinstance(
            raw_profile,
            dict,
        ):
            continue
        root_id = raw_profile.get("workspace_root_id")
        workspace_name = raw_profile.get("workspace_name")
        try:
            if isinstance(root_id, str) and isinstance(
                workspace_name,
                str,
            ):
                resolved = resolve_workspace_identity(
                    root_id,
                    workspace_name,
                    working_dir=working_dir,
                )
            else:
                raise ValueError("Workspace identity is incomplete")
        except ValueError:
            (
                root_id,
                workspace_name,
                resolved,
            ) = derive_legacy_workspace_identity(
                raw_profile.get("workspace_dir"),
                raw_agent_id,
                working_dir=working_dir,
            )

        resolved_text = os.fspath(resolved)
        updates = {
            "workspace_root_id": root_id,
            "workspace_name": workspace_name,
            "workspace_dir": resolved_text,
        }
        for key, value in updates.items():
            if raw_profile.get(key) != value:
                raw_profile[key] = value
                changed = True
    return changed
