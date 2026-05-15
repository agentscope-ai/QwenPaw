# -*- coding: utf-8 -*-
"""Helpers to read per-agent A2A configuration from workspace.

Used by ``a2a_list`` and ``a2a_call`` tools to resolve registered
A2A agents by alias without requiring the caller to know URLs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_A2A_CONFIG_FILENAME = "a2a_config.json"


def _get_workspace_dir() -> Path | None:
    """Resolve workspace directory for the current agent via context."""
    try:
        from qwenpaw.app.agent_context import get_current_agent_id
        from qwenpaw.config.utils import load_config

        agent_id = get_current_agent_id()
        config = load_config()

        ref = config.agents.profiles.get(agent_id)
        if ref:
            return Path(ref.workspace_dir).expanduser()
    except Exception as exc:
        logger.debug("Failed to resolve workspace dir: %s", exc)
    return None


def load_a2a_agents() -> dict[str, dict]:
    """Load per-agent A2A config: {alias -> registration_info}."""
    ws_dir = _get_workspace_dir()
    if not ws_dir:
        return {}
    path = ws_dir / _A2A_CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("agents", {})
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def resolve_agent_by_alias(alias: str) -> dict | None:
    """Look up a registered agent by alias, returning its config dict."""
    agents = load_a2a_agents()
    return agents.get(alias)
