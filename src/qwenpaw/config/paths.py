# -*- coding: utf-8 -*-
"""Path resolution helpers for configuration-owned directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR
from ..utils.io_utils import write_json_atomic


DEFAULT_AGENT_WORKSPACE_ROOT_ID = "default"
_WORKSPACE_ROOT_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$",
)
_WORKSPACE_ROOT_REGISTRY_FILE = "registry.json"
_workspace_root_registry_lock = threading.Lock()


def _working_dir_path(working_dir: Path | None) -> Path:
    """Return one absolute QwenPaw working directory."""
    base = working_dir or WORKING_DIR
    if not base.is_absolute():
        base = Path(os.path.abspath(base))
    return Path(os.path.realpath(base))


def _canonical_path(path: Path) -> Path:
    """Return a canonical path without requiring it to exist."""
    return Path(os.path.realpath(os.fspath(path)))


def _canonical_registered_root(path: str, working_dir: Path) -> Path:
    """Resolve stored relative paths against the QwenPaw working directory."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = working_dir / candidate
    return _canonical_path(candidate)


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


def _workspace_root_registry_file(working_dir: Path) -> Path:
    """Return the server-owned persistent root registry file."""
    return (
        _workspace_root_registry_path(working_dir)
        / _WORKSPACE_ROOT_REGISTRY_FILE
    )


def _read_workspace_root_registry(
    working_dir: Path,
    *,
    strict: bool = False,
) -> dict[str, str]:
    """Read valid string entries from the persistent root registry."""
    registry_file = _workspace_root_registry_file(working_dir)
    try:
        payload = json.loads(registry_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError(
                f"Workspace root registry is unreadable: {registry_file}",
            ) from exc
        return {}
    if not isinstance(payload, dict):
        if strict:
            raise ValueError(
                f"Workspace root registry is invalid: {registry_file}",
            )
        return {}
    raw_roots = payload.get("roots", payload)
    if not isinstance(raw_roots, dict):
        if strict:
            raise ValueError(
                f"Workspace root registry is invalid: {registry_file}",
            )
        return {}
    if strict and any(
        not isinstance(root_id, str) or not isinstance(path, str)
        for root_id, path in raw_roots.items()
    ):
        raise ValueError(
            f"Workspace root registry is invalid: {registry_file}",
        )
    return {
        root_id: path
        for root_id, path in raw_roots.items()
        if isinstance(root_id, str) and isinstance(path, str)
    }


def _write_workspace_root_registry(
    working_dir: Path,
    roots: Mapping[str, str],
) -> None:
    """Atomically persist canonical workspace root paths."""
    write_json_atomic(
        _workspace_root_registry_file(working_dir),
        {"version": 1, "roots": dict(sorted(roots.items()))},
        sort_keys=True,
    )


def register_agent_workspace_root(
    root_id: str,
    root_path: str | Path,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Register an existing local directory under one opaque root ID."""
    normalized_id = sanitize_workspace_root_id(root_id)
    if normalized_id == DEFAULT_AGENT_WORKSPACE_ROOT_ID:
        raise ValueError(f"Workspace root ID '{root_id}' is reserved")
    base = _working_dir_path(working_dir)
    candidate = Path(root_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    canonical = _reject_filesystem_root(
        _canonical_path(candidate),
        label=f"Workspace root '{normalized_id}'",
    )
    if not canonical.is_dir():
        raise ValueError(
            f"Workspace root '{canonical}' is not an existing directory",
        )

    directory_alias = _workspace_root_registry_path(base) / normalized_id
    if directory_alias.is_dir():
        alias_target = _canonical_path(directory_alias)
        raise ValueError(
            f"Workspace root ID '{normalized_id}' is already registered "
            f"by directory alias '{alias_target}'",
        )

    with _workspace_root_registry_lock:
        roots = _read_workspace_root_registry(base, strict=True)
        existing = roots.get(normalized_id)
        if existing is not None:
            existing_path = _canonical_registered_root(existing, base)
            if existing_path != canonical:
                raise ValueError(
                    f"Workspace root ID '{normalized_id}' is already "
                    f"registered for '{existing_path}'",
                )
        roots[normalized_id] = os.fspath(canonical)
        _write_workspace_root_registry(base, roots)
    return canonical


def unregister_agent_workspace_root(
    root_id: str,
    *,
    working_dir: Path | None = None,
) -> bool:
    """Remove one persistent root registration without deleting files."""
    normalized_id = sanitize_workspace_root_id(root_id)
    if normalized_id == DEFAULT_AGENT_WORKSPACE_ROOT_ID:
        raise ValueError(f"Workspace root ID '{root_id}' is reserved")
    base = _working_dir_path(working_dir)
    directory_alias = _workspace_root_registry_path(base) / normalized_id
    if directory_alias.is_dir():
        raise ValueError(
            f"Workspace root ID '{normalized_id}' is managed by directory "
            f"alias '{_canonical_path(directory_alias)}'",
        )
    with _workspace_root_registry_lock:
        roots = _read_workspace_root_registry(base, strict=True)
        if roots.pop(normalized_id, None) is None:
            return False
        _write_workspace_root_registry(base, roots)
    return True


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
    entries: list[Path] = []
    if registry.is_dir():
        try:
            entries = sorted(registry.iterdir(), key=lambda entry: entry.name)
        except OSError:
            entries = []

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

    for raw_id, raw_path in _read_workspace_root_registry(base).items():
        try:
            root_id = sanitize_workspace_root_id(raw_id)
            root = _reject_filesystem_root(
                _canonical_registered_root(raw_path, base),
                label=f"Workspace root '{root_id}'",
            )
        except ValueError:
            continue
        if (
            root_id in roots
            or root_id == DEFAULT_AGENT_WORKSPACE_ROOT_ID
            or not root.is_dir()
        ):
            continue
        roots[root_id] = root
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
    roots: Mapping[str, Path] | None = None,
) -> Path:
    """Resolve a workspace from a registered root and one safe name."""
    active_roots = (
        roots
        if roots is not None
        else resolve_agent_workspace_roots(working_dir=working_dir)
    )
    root = _select_workspace_root(root_id, active_roots)
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
    roots: Mapping[str, Path],
) -> tuple[Path, set[str]]:
    """Return trusted resolved and registry-alias forms for a workspace."""
    resolved = resolve_workspace_identity(
        root_id,
        workspace_name,
        working_dir=working_dir,
        roots=roots,
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
    roots: Mapping[str, Path] | None = None,
) -> tuple[str, str, Path]:
    """Match or safely register one locally configured legacy workspace."""
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
    active_roots = (
        roots
        if roots is not None
        else resolve_agent_workspace_roots(working_dir=base)
    )
    for root_id in active_roots:
        resolved, candidates = _registered_workspace_path_texts(
            root_id,
            workspace_name,
            working_dir=base,
            roots=active_roots,
        )
        if normalized_workspace in candidates:
            return root_id, workspace_name, resolved

    workspace = Path(workspace_text).expanduser()
    if not workspace.is_absolute():
        workspace = base / workspace
    workspace = _canonical_path(workspace)
    root = workspace.parent
    digest = hashlib.blake2b(
        os.path.normcase(os.fspath(root)).encode("utf-8"),
        digest_size=8,
    ).hexdigest()
    root_id = f"legacy-{digest}"
    register_agent_workspace_root(
        root_id,
        root,
        working_dir=base,
    )
    resolved = resolve_workspace_identity(
        root_id,
        workspace_name,
        working_dir=base,
    )
    return root_id, workspace_name, resolved


def migrate_legacy_agent_workspace_profiles(
    data: dict[str, Any],
    *,
    working_dir: Path | None = None,
) -> bool:
    """Migrate local legacy workspace paths to trusted identities."""
    base = _working_dir_path(working_dir)
    legacy_roots = data.pop("agent_workspace_roots", None)
    changed = legacy_roots is not None
    roots = resolve_agent_workspace_roots(working_dir=base)
    if isinstance(legacy_roots, dict):
        for root_id, root_path in legacy_roots.items():
            if not isinstance(root_id, str) or not isinstance(root_path, str):
                continue
            normalized_id = sanitize_workspace_root_id(root_id)
            known_root = roots.get(normalized_id)
            legacy_root = _canonical_registered_root(root_path, base)
            if known_root is not None and known_root == legacy_root:
                continue
            register_agent_workspace_root(
                normalized_id,
                root_path,
                working_dir=base,
            )
            roots[normalized_id] = legacy_root
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
        if isinstance(root_id, str) and isinstance(workspace_name, str):
            resolved = resolve_workspace_identity(
                root_id,
                workspace_name,
                working_dir=base,
                roots=roots,
            )
        else:
            (
                root_id,
                workspace_name,
                resolved,
            ) = derive_legacy_workspace_identity(
                raw_profile.get("workspace_dir"),
                raw_agent_id,
                working_dir=base,
                roots=roots,
            )
            roots[root_id] = resolved.parent

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
