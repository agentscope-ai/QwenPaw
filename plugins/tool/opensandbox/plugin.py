# -*- coding: utf-8 -*-
"""OpenSandbox plugin entry point."""

import importlib.util
import json
import logging
import shutil
from pathlib import Path

from qwenpaw.plugins.api import PluginApi

_PLUGIN_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

_PLUGIN_SKILLS = ["opensandbox"]


def _load_tool_module():
    """Load the OpenSandbox tool module from this plugin directory."""
    tool_path = _PLUGIN_DIR / "tools" / "shell.py"
    spec = importlib.util.spec_from_file_location(
        "opensandbox_shell_tool",
        tool_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load OpenSandbox tool module: {tool_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _update_pool_manifest(pool_dir: Path) -> None:
    manifest_path = pool_dir / "skill.json"
    try:
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = {"skills": {}, "builtin_skill_names": []}

        skills = manifest.setdefault("skills", {})
        for skill_name in _PLUGIN_SKILLS:
            if (pool_dir / skill_name).exists():
                skills[skill_name] = {
                    "source": "plugin:opensandbox",
                    "protected": False,
                }

        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to update skill pool manifest: %s", exc)


def _install_plugin_skills() -> None:
    """Copy bundled OpenSandbox skills into the shared skill pool."""
    try:
        from qwenpaw.agents.skill_system import (
            ensure_skill_pool_initialized,
            get_skill_pool_dir,
        )
    except ImportError:
        logger.warning("Cannot import skill_system; skill install skipped")
        return

    try:
        ensure_skill_pool_initialized()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Skill pool init failed: %s", exc)
        return

    pool_dir = get_skill_pool_dir()
    skills_src = _PLUGIN_DIR / "skills"
    for skill_name in _PLUGIN_SKILLS:
        src = skills_src / skill_name
        dst = pool_dir / skill_name
        if not src.exists():
            logger.warning("OpenSandbox skill source missing: %s", src)
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.info("Installed OpenSandbox skill to pool: %s", skill_name)

    _update_pool_manifest(pool_dir)
    _sync_plugin_skills_to_agents()


def _sync_plugin_skills_to_agents() -> None:
    """Copy bundled skills into existing agent workspaces, disabled by default."""
    try:
        from qwenpaw.agents.skill_system import SkillPoolService, SkillService
        from qwenpaw.agents.skill_system.store import get_workspace_skills_dir
        from qwenpaw.config.utils import load_config
    except ImportError as exc:
        logger.warning("Cannot sync OpenSandbox skills to agents: %s", exc)
        return

    try:
        config = load_config()
        profiles = getattr(getattr(config, "agents", None), "profiles", {})
        if not profiles:
            return

        pool_service = SkillPoolService()
        for agent_id, profile in profiles.items():
            workspace_dir = Path(profile.workspace_dir).expanduser()
            if not workspace_dir.exists():
                continue

            for skill_name in _PLUGIN_SKILLS:
                skill_dir = get_workspace_skills_dir(workspace_dir) / skill_name
                already_present = skill_dir.exists()
                result = pool_service.download_to_workspace(
                    skill_name,
                    workspace_dir,
                    overwrite=False,
                )
                if not result.get("success"):
                    reason = result.get("reason") or result.get("type")
                    logger.debug(
                        "OpenSandbox skill sync skipped for agent %s: %s",
                        agent_id,
                        reason,
                    )
                    continue

                if not already_present:
                    SkillService(workspace_dir).disable_skill(skill_name)
                    logger.info(
                        "Added OpenSandbox skill to agent %s disabled",
                        agent_id,
                    )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("OpenSandbox skill sync failed: %s", exc)


class OpenSandboxPlugin:
    """Register OpenSandbox tools into QwenPaw."""

    def register(self, api: PluginApi) -> None:
        """Register OpenSandbox tool functions."""
        tool = _load_tool_module()
        api.register_startup_hook(
            hook_name="opensandbox_install_skills",
            callback=_install_plugin_skills,
            priority=50,
        )
        api.register_tool(
            tool_name="execute_opensandbox_command",
            tool_func=tool.execute_opensandbox_command,
            description="Execute shell commands inside OpenSandbox",
            icon="terminal",
        )
        logger.info("OpenSandbox plugin registered")


plugin = OpenSandboxPlugin()
