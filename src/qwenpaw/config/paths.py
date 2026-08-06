# -*- coding: utf-8 -*-
"""Path resolution helpers for configuration-owned directories."""

import os
from pathlib import Path

from ..constant import WORKING_DIR


def resolve_configured_path(
    value: str | Path,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve configured paths relative to QwenPaw's working directory."""
    base = Path(working_dir or WORKING_DIR).expanduser()
    if not base.is_absolute():
        base = Path(os.path.abspath(base))
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return Path(os.path.abspath(path))


def resolve_agent_workspace_path(
    workspace_dir: str | Path | None,
    agent_id: str,
    *,
    working_dir: Path | None = None,
) -> Path:
    """Resolve an agent workspace or return its default workspace path."""
    base = Path(working_dir or WORKING_DIR).expanduser()
    if not base.is_absolute():
        base = Path(os.path.abspath(base))
    if workspace_dir is None or not str(workspace_dir).strip():
        return Path(os.path.abspath(base / "workspaces" / agent_id))
    return resolve_configured_path(workspace_dir, working_dir=base)
