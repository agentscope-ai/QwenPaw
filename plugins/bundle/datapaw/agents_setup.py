# -*- coding: utf-8 -*-
"""Agent profile / workspace setup for the DataPaw plugin.

Mirrors the cloudpaw pattern (``plugins/bundle/cloudpaw/agents_setup.py``):
on plugin startup, ensure a stable ``agent_id="datapaw"`` profile exists in
host config, ensure its workspace directory exists, write an up-to-date
``agent.json``, and seed SOUL/PROFILE persona files into the workspace so
host's standard prompt assembly picks them up.

Three exported functions:

- ``ensure_builtin_agents``: idempotent install (called from ``_on_startup``)
- ``_seed_persona_md_files``: copy plugin's per-language SOUL/PROFILE into
  the workspace
- ``uninstall_builtin_agents``: remove profile / workspace / agent.json
  (called from ``patch_plugin_loader_unload`` in ``hooks.py``)
"""
from __future__ import annotations

import json
import logging
import shutil
import time
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

from constants import BUILTIN_DATAPAW_AGENT_ID, PLUGIN_DIR

logger = logging.getLogger(__name__)

# Tag used to mark plugin-bundled skill entries in the workspace manifest;
# uninstall path can grep this to know which entries it owns.
_PLUGIN_SKILL_SOURCE = "plugin:datapaw"


def _workspace_dir_for(agent_id: str) -> Path:
    """Compute the standard workspace dir under ``WORKING_DIR``."""
    return (Path(WORKING_DIR) / "workspaces" / agent_id).expanduser().resolve()


def ensure_builtin_agents() -> None:
    """Idempotent: ensure ``agent_id=datapaw`` profile + workspace + agent.json."""
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
        description="数据分析多步规划 agent，基于 DAG 任务图分阶段推进",
        workspace_dir=str(ws_dir),
        language=language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        # Enable host's plan mode plumbing so DataPaw inherits:
        # - /plan command pre-create gate
        # - post-mutation lock (_plan_awaiting_user_confirm)
        # - clear_plan_awaiting_user_confirm at start of each user turn
        # - broadcast_plan_update SSE channel (/api/plan/stream)
        # DataPaw's RuntimeStateManager replaces the host PlanNotebook
        # at agent init time but inherits all _plan_* flags via
        # DataPawAgent.__init__'s flag migration.
        plan=PlanConfig(enabled=True),
    )
    save_agent_config(agent_id, agent_cfg)
    _seed_persona_md_files(ws_dir, language=language)
    _install_plugin_skills(ws_dir)


def _seed_persona_md_files(ws_dir: Path, language: str = "zh") -> None:
    """Copy ``SOUL.md`` / ``PROFILE.md`` from the plugin into the workspace.

    Host's standard prompt assembly reads these files from the workspace
    and stitches them after ``AGENTS.md``.
    """
    src_dir = PLUGIN_DIR / "agents" / "datapaw" / language
    if not src_dir.exists():
        # Fall back to zh if the requested language pack is missing.
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


def _install_plugin_skills(ws_dir: Path) -> None:
    """Copy DataPaw plugin-bundled skills into the workspace and enable them.

    Host's QwenPawAgent only registers a skill if (a) its directory exists
    under ``<workspace>/skills/<name>/`` AND (b) the workspace ``skill.json``
    manifest has the entry with ``enabled=True`` and the active channel is
    in its ``channels`` list. This helper does both:

    1. Copy each ``plugins/bundle/datapaw/skills/<name>/`` to
       ``<workspace>/skills/<name>/``. Existing dirs with the same name are
       overwritten so plugin upgrades propagate cleanly.
    2. Run host's ``reconcile_workspace_manifest`` to populate manifest
       metadata (description, requirements, signature, …) from the on-disk
       SKILL.md.
    3. Patch the manifest in place: set ``enabled=True`` and
       ``source="plugin:datapaw"`` for each plugin skill.

    Idempotent: re-running on the same workspace just refreshes the files
    and re-asserts ``enabled=True`` without disturbing other manifest
    entries (e.g. the user's customized skills with ``source=customized``).
    """
    src_skills_dir = PLUGIN_DIR / "skills"
    if not src_skills_dir.exists():
        return

    dst_skills_dir = ws_dir / "skills"
    dst_skills_dir.mkdir(parents=True, exist_ok=True)

    plugin_skill_names: list[str] = []
    for src in sorted(src_skills_dir.iterdir()):
        if not src.is_dir() or not (src / "SKILL.md").exists():
            continue
        skill_name = src.name
        plugin_skill_names.append(skill_name)
        dst = dst_skills_dir / skill_name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    if not plugin_skill_names:
        return

    # Lazy host imports — keeps this module importable in isolation tests
    # that don't set up the full host package.
    from qwenpaw.agents.skill_system.registry import (
        reconcile_workspace_manifest,
    )
    from qwenpaw.agents.skill_system.store import (
        get_workspace_skill_manifest_path,
        write_json_atomic,
    )

    # Reconcile so manifest entries get created with full metadata.
    reconcile_workspace_manifest(ws_dir)

    # Read fresh from disk (the read_skill_manifest helper is mtime-cached
    # and may serve a stale snapshot taken before reconcile finished).
    manifest_path = get_workspace_skill_manifest_path(ws_dir)
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    skills = manifest.setdefault("skills", {})
    for name in plugin_skill_names:
        entry = skills.get(name)
        if entry is None:
            # Reconcile should have created this; if not, something is
            # wrong with the SKILL.md — just skip and log.
            logger.warning(
                "DataPaw plugin skill %r missing from manifest after"
                " reconcile; skipping enable",
                name,
            )
            continue
        entry["enabled"] = True
        entry["channels"] = entry.get("channels") or ["all"]
        entry["source"] = _PLUGIN_SKILL_SOURCE

    manifest["version"] = int(time.time() * 1000)
    write_json_atomic(manifest_path, manifest)
    logger.info(
        "Installed %d DataPaw plugin skills into %s",
        len(plugin_skill_names),
        ws_dir,
    )


def uninstall_builtin_agents() -> None:
    """Remove DataPaw builtin agent profile and its workspace.

    ``agent.json`` lives inside the workspace dir, so it goes away with the
    ``rmtree``; host has no separate ``delete_agent_config`` helper. If the
    user's ``active_agent`` happened to be ``datapaw``, it is reset to
    ``default`` so host doesn't end up pointing at a missing agent.
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
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
