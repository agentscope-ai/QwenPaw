# -*- coding: utf-8 -*-
# pylint: disable=relative-beyond-top-level
"""Agent profile / workspace setup for the DataPaw plugin.

On plugin startup, ensure a stable ``agent_id="datapaw"`` profile exists in
host config, ensure its workspace directory exists, write an up-to-date
``agent.json``, and seed SOUL/PROFILE persona files into the workspace so
host's standard prompt assembly picks them up.

Exported functions:

- ``ensure_builtin_agents``: idempotent install (called from ``_on_startup``)
- ``uninstall_builtin_agents``: remove profile / workspace / agent.json
  (called from ``_on_uninstall`` in ``plugin.py``)
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    ChannelConfig,
    HeartbeatConfig,
    MCPConfig,
    PlanConfig,
)
from qwenpaw.config.utils import (
    load_config,
    save_agent_config,
    save_config,
)
from qwenpaw.constant import WORKING_DIR

from .constants import BUILTIN_DATAPAW_AGENT_ID, PLUGIN_DIR
from .core.i18n import tr

logger = logging.getLogger(__name__)


def _workspace_dir_for(agent_id: str) -> Path:
    """Compute the standard workspace dir under ``WORKING_DIR``."""
    return (Path(WORKING_DIR) / "workspaces" / agent_id).expanduser().resolve()


def ensure_builtin_agents() -> None:
    """Idempotent: ensure ``agent_id=datapaw`` profile + workspace."""
    config = load_config()
    agent_id = BUILTIN_DATAPAW_AGENT_ID
    expected_ws = _workspace_dir_for(agent_id)

    if agent_id in config.agents.profiles:
        ref = config.agents.profiles[agent_id]
        actual_ws = Path(ref.workspace_dir).expanduser().resolve()
        if actual_ws != expected_ws:
            logger.warning(
                "Agent %s workspace mismatch (expected %s, found %s); "
                "leaving existing profile untouched",
                agent_id,
                expected_ws,
                actual_ws,
            )
            return
        ws_dir = actual_ws
    else:
        expected_ws.mkdir(parents=True, exist_ok=True)
        config.agents.profiles[agent_id] = AgentProfileRef(
            id=agent_id,
            workspace_dir=str(expected_ws),
        )
        save_config(config)
        logger.info("Registered DataPaw agent at %s", expected_ws)
        ws_dir = expected_ws

    language = config.agents.language or "zh"

    agent_cfg = AgentProfileConfig(
        id=agent_id,
        name="DataPaw",
        description=tr("agent.description", language),
        workspace_dir=str(ws_dir),
        language=language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        plan=PlanConfig(enabled=True),
    )
    save_agent_config(agent_id, agent_cfg)
    _seed_persona_md_files(ws_dir, language=language)


def _seed_persona_md_files(ws_dir: Path, language: str = "zh") -> None:
    """Copy ``SOUL.md`` / ``PROFILE.md`` from the plugin into the workspace.

    Host's standard prompt assembly reads these files from the workspace
    and stitches them after ``AGENTS.md``.
    """
    src_dir = PLUGIN_DIR / "agents" / "datapaw" / language
    if not src_dir.exists():
        logger.warning(
            "DataPaw persona dir missing for language=%r; falling back to zh",
            language,
        )
        src_dir = PLUGIN_DIR / "agents" / "datapaw" / "zh"
    for fname in ("SOUL.md", "PROFILE.md"):
        src = src_dir / fname
        dst = ws_dir / fname
        if src.exists():
            shutil.copy2(src, dst)


_WORKSPACE_PRESERVE = {"sessions", "artifacts", "chats.json", "jobs.json"}


def uninstall_builtin_agents() -> None:
    """Remove DataPaw agent profile and workspace plugin artifacts.

    Preserves user data directories (sessions, artifacts, dag) that
    contain conversation history and generated files.
    """
    config = load_config()
    profile = config.agents.profiles.pop(BUILTIN_DATAPAW_AGENT_ID, None)
    if profile is None:
        return
    if (
        getattr(config.agents, "active_agent", None)
        == BUILTIN_DATAPAW_AGENT_ID
    ):
        config.agents.active_agent = "default"
    save_config(config)
    ws = Path(profile.workspace_dir)
    if not ws.exists():
        return
    for item in ws.iterdir():
        if item.name in _WORKSPACE_PRESERVE:
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
