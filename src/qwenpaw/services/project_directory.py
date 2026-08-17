# -*- coding: utf-8 -*-
"""Resolve the project directory independently from agent workspace state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR


def normalize_project_dir(
    value: str | Path,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve a project path against the QwenPaw working directory."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (working_dir or WORKING_DIR) / path
    return path.resolve()


def session_project_dir(meta: dict[str, Any] | None) -> str | None:
    """Read the controlled Session project override from Chat metadata."""
    if not isinstance(meta, dict):
        return None
    runtime_context = meta.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return None
    value = runtime_context.get("project_dir")
    return value if isinstance(value, str) and value.strip() else None


def resolve_effective_project_dir(
    workspace_dir: Path,
    *,
    agent_project_dir: str | None = None,
    session_override: str | None = None,
    trusted_override: str | None = None,
    active_mode_override: str | None = None,
    fork_project_dir: str | None = None,
    working_dir: Path | None = None,
) -> tuple[Path, str]:
    """Resolve one immutable project directory snapshot and its source."""
    candidates = (
        ("fork", fork_project_dir),
        ("active_mode", active_mode_override),
        ("request", trusted_override),
        ("session", session_override),
        ("agent", agent_project_dir),
    )
    for source, value in candidates:
        if isinstance(value, str) and value.strip():
            return (
                normalize_project_dir(value, working_dir=working_dir),
                source,
            )
    return workspace_dir.expanduser().resolve(), "workspace_fallback"
