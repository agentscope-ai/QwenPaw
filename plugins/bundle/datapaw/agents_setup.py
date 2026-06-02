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

from core.i18n import tr
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

# Sibling-module imports last because the conditional ``if/else`` block
# is a non-import statement and would otherwise force all following
# imports into ``wrong-import-position``. Conditional pattern: relative
# when host's PluginLoader sets ``__package__ = "plugin_datapaw"``,
# absolute when imported via the sys.path-based test conftest. Required
# so the plugin can co-exist with other plugins (e.g. cloudpaw) that
# ship a top-level ``constants`` module of their own.
if __package__:
    # pylint: disable-next=relative-beyond-top-level
    from .constants import BUILTIN_DATAPAW_AGENT_ID, PLUGIN_DIR
else:
    from constants import (  # type: ignore[no-redef]
        BUILTIN_DATAPAW_AGENT_ID,
        PLUGIN_DIR,
    )

logger = logging.getLogger(__name__)

# Tag used to mark plugin-bundled skill entries in the workspace manifest;
# uninstall path can grep this to know which entries it owns.
_PLUGIN_SKILL_SOURCE = "plugin:datapaw"

# Filename used to cache per-skill src-dir mtimes so we can skip the
# rmtree+copytree round-trip when nothing has changed since last install.
_SKILL_VERSIONS_FILENAME = ".datapaw_versions.json"


def _max_mtime(root: Path) -> float:
    """Return the recursive max ``st_mtime`` of all files under ``root``.

    Used as a cheap content-change signal — we trade hash exactness for an
    O(N) directory walk and no IO past ``stat()``. Acceptable because the
    cache only gates a 12-skill copy on startup; a false-negative skip
    (very unlikely without a manual ``touch -t`` backdate) is recovered
    by deleting :const:`_SKILL_VERSIONS_FILENAME`.
    """
    best = 0.0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if mt > best:
                best = mt
    return best


def _load_skill_versions(versions_file: Path) -> dict[str, float]:
    """Read the per-skill mtime cache; empty dict on any failure."""
    if not versions_file.exists():
        return {}
    try:
        with versions_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Defensive: only keep numeric entries so a corrupt cache doesn't
    # promote a bogus value into the short-circuit comparison.
    return {
        name: float(mt)
        for name, mt in data.items()
        if isinstance(name, str) and isinstance(mt, (int, float))
    }


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


def _patch_workspace_manifest_for_plugin_skills(
    ws_dir: Path,
    plugin_skill_names: list[str],
) -> None:
    """Reconcile host's skill manifest and flip plugin skills to enabled.

    Coupling note: this function reads and writes the on-disk shape of
    host's ``skill.json``. If host renames the ``enabled`` / ``channels``
    / ``source`` fields, or adds a required field, this code silently
    breaks at install time. Isolating it here keeps the host-data-shape
    coupling in a single, labelled place rather than scattered inside
    :func:`_install_plugin_skills`.
    """
    # Lazy host imports — keep this function importable in isolation
    # tests that don't set up the full host package.
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

    Per-skill ``rmtree+copytree`` is short-circuited via a cached
    ``{skill_name: src_max_mtime}`` map stored at
    ``<ws>/skills/.datapaw_versions.json``; on subsequent startups, skills
    whose src has not been touched skip the file copy. The manifest
    reconcile + enable patch still runs every time since it costs little
    and protects against externally tampered manifest entries.
    """
    src_skills_dir = PLUGIN_DIR / "skills"
    if not src_skills_dir.exists():
        return

    dst_skills_dir = ws_dir / "skills"
    dst_skills_dir.mkdir(parents=True, exist_ok=True)

    versions_file = dst_skills_dir / _SKILL_VERSIONS_FILENAME
    cached_versions = _load_skill_versions(versions_file)
    updated_versions: dict[str, float] = {}

    plugin_skill_names: list[str] = []
    for src in sorted(src_skills_dir.iterdir()):
        if not src.is_dir() or not (src / "SKILL.md").exists():
            continue
        skill_name = src.name
        plugin_skill_names.append(skill_name)
        dst = dst_skills_dir / skill_name

        src_mtime = _max_mtime(src)
        cached_mtime = cached_versions.get(skill_name)
        if (
            dst.exists()
            and cached_mtime is not None
            and cached_mtime >= src_mtime
        ):
            # Source unchanged since the last install — keep the cached
            # mtime so it survives this round-trip and skip the copy.
            updated_versions[skill_name] = cached_mtime
            continue

        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        updated_versions[skill_name] = src_mtime

    if not plugin_skill_names:
        return

    _patch_workspace_manifest_for_plugin_skills(ws_dir, plugin_skill_names)

    # Persist the mtime cache last so a partial install (manifest write
    # fails) does not poison the short-circuit for the next startup.
    try:
        versions_file.write_text(
            json.dumps(updated_versions, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.warning(
            "Failed to write %s; next startup will redo all skill copies.",
            versions_file,
            exc_info=True,
        )

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
