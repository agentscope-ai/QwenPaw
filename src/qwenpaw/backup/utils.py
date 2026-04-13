# -*- coding: utf-8 -*-
"""Shared utilities for the backup module."""
from __future__ import annotations

import json
from pathlib import Path


def get_agent_id(workspace_dir: Path) -> str:
    """Read agent id from workspace agent.json."""
    agent_json = workspace_dir / "agent.json"
    if agent_json.exists():
        try:
            data = json.loads(
                agent_json.read_text(encoding="utf-8"),
            )
            return data.get("id", "unknown")
        except (json.JSONDecodeError, OSError):
            pass
    return "unknown"
