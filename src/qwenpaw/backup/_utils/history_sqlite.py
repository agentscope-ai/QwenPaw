# -*- coding: utf-8 -*-
"""Locate SQLite scroll history safely inside an agent workspace."""

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


def configured_history_db_path(workspace: Path) -> Path:
    """Return the configured in-workspace history path without side effects.

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
