# -*- coding: utf-8 -*-
"""Browse agent workspace files for file-baseline protected path picker."""
from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_BROWSE_ROOT = "skills"

_SKIP_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
    },
)


def _is_skipped_name(name: str) -> bool:
    return name.startswith(".") or name in _SKIP_NAMES


def _normalize_browse_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().strip("/")
    if ".." in normalized.split("/"):
        raise ValueError(f"Invalid browse path: {path!r}")
    return normalized


def _resolve_browse_dir(workspace_dir: Path, relative_path: str) -> tuple[Path, str]:
    workspace_root = workspace_dir.expanduser().resolve()
    normalized = _normalize_browse_relative_path(relative_path)
    target = workspace_root if not normalized else (workspace_root / normalized).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace: {relative_path!r}") from exc
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {normalized or '.'}")
    if not target.is_dir():
        raise ValueError(f"Browse path must be a directory: {normalized}")
    current_rel = "" if target == workspace_root else target.relative_to(workspace_root).as_posix()
    return target, current_rel


def browse_workspace_protectable_files(
    *,
    workspace_dir: Path,
    agent_id: str,
    relative_path: str = DEFAULT_BROWSE_ROOT,
) -> dict[str, Any]:
    """List one directory level under the agent workspace for path picking."""
    workspace_root = workspace_dir.expanduser().resolve()
    default_path = (
        DEFAULT_BROWSE_ROOT
        if (workspace_root / DEFAULT_BROWSE_ROOT).is_dir()
        else ""
    )

    browse_rel = _normalize_browse_relative_path(relative_path or "")
    if browse_rel == DEFAULT_BROWSE_ROOT and not (workspace_root / DEFAULT_BROWSE_ROOT).is_dir():
        browse_rel = ""

    current_dir, current_rel = _resolve_browse_dir(workspace_root, browse_rel)
    parent_rel = ""
    if current_rel:
        parent = Path(current_rel).parent
        parent_rel = "" if str(parent) == "." else parent.as_posix()

    entries: list[dict[str, Any]] = []
    for item in sorted(
        current_dir.iterdir(),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    ):
        if _is_skipped_name(item.name):
            continue
        rel_path = f"{current_rel}/{item.name}" if current_rel else item.name
        if item.is_dir():
            entries.append(
                {
                    "name": item.name,
                    "type": "dir",
                    "rel_path": rel_path,
                },
            )
            continue
        if item.is_file():
            try:
                size = item.stat().st_size
            except OSError:
                size = 0
            entries.append(
                {
                    "name": item.name,
                    "type": "file",
                    "rel_path": rel_path,
                    "size": size,
                },
            )

    return {
        "agent_id": agent_id,
        "workspace_label": workspace_root.name,
        "current_path": current_rel,
        "parent_path": parent_rel,
        "default_path": default_path,
        "entries": entries,
    }
