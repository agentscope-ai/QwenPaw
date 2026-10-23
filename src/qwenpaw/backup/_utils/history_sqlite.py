# -*- coding: utf-8 -*-
"""Locate SQLite history and prepare portable backup configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ...config.history_path import (
    DEFAULT_HISTORY_DB_FILENAME,
    resolve_history_db_path,
)

logger = logging.getLogger(__name__)

SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def history_agent_config_bytes(
    workspace: Path,
    archive_filename: str,
) -> bytes:
    """Normalize the archive config without rewriting the live workspace."""
    content = (workspace / f"agent.json").read_bytes()
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return content
    config = data
    for key in (f"running", f"light_context_config", f"scroll_config"):
        if not isinstance(config, dict):
            return content
        config = config.get(key)
    if isinstance(config, dict):
        config[f"db_filename"] = archive_filename
        return json.dumps(data, ensure_ascii=False, indent=2).encode(f"utf-8")
    return content


def configured_history_db_path(workspace: Path) -> Path:
    """Return the configured history path without side effects.

    Backup code must not call the normal agent-config loader because that
    loader can migrate or rewrite configuration. Invalid or missing config
    falls back to the runtime default.
    """
    filename = DEFAULT_HISTORY_DB_FILENAME
    workspace = workspace.expanduser().resolve()
    agent_json = workspace / "agent.json"
    if agent_json.is_file():
        try:
            data = json.loads(agent_json.read_text(encoding="utf-8"))
            configured = (
                data.get("running", {})
                .get("light_context_config", {})
                .get("scroll_config", {})
                .get("db_filename")
            )
            if isinstance(configured, str) and configured.strip():
                filename = configured
        except (AttributeError, json.JSONDecodeError, OSError):
            logger.warning(
                "Could not read history DB path from %s; using %s",
                agent_json,
                filename,
            )

    return resolve_history_db_path(workspace, filename)


def history_sidecar_paths(db_path: Path) -> set[Path]:
    """Return live SQLite sidecars that must never be archived directly."""
    return {
        Path(str(db_path) + suffix).resolve()
        for suffix in SQLITE_SIDECAR_SUFFIXES
    }


def archive_history_db_filename(workspace: Path, db_path: Path) -> str:
    """Choose a portable snapshot path without replacing workspace files."""
    if db_path.is_relative_to(workspace):
        return db_path.relative_to(workspace).as_posix()
    filename = DEFAULT_HISTORY_DB_FILENAME
    index = 0
    while any(
        (workspace / f"{filename}{suffix}").exists()
        or (workspace / f"{filename}{suffix}").is_symlink()
        for suffix in (f"", *SQLITE_SIDECAR_SUFFIXES)
    ):
        index += 1
        filename = f"history-{index}.db"
    return filename
