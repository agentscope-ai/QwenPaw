# -*- coding: utf-8 -*-
"""OpenSandbox plugin entry point."""

import json
import logging
import shutil
import sys
from copy import deepcopy
from pathlib import Path

from qwenpaw.plugins.api import PluginApi

_PLUGIN_DIR = Path(__file__).resolve().parent
_LAUNCHER_FILE = "opensandbox_mcp_launcher.py"

logger = logging.getLogger(__name__)

_PLUGIN_SKILLS = ["opensandbox"]
_MCP_CLIENT_KEY = "opensandbox"
_MCP_ENV_API_KEY = "OPEN_SANDBOX_API_KEY"
_MCP_ENV_DOMAIN = "OPEN_SANDBOX_DOMAIN"
_MCP_ENV_USE_SERVER_PROXY = "OPEN_SANDBOX_USE_SERVER_PROXY"
_MCP_PROXY_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_MCP_PROXY_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_LEGACY_TOOL_NAMES = frozenset(
    {
        "execute_opensandbox_command",
        "check_opensandbox_status",
        "inspect_opensandbox_upload",
    },
)


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


def _default_mcp_env() -> dict[str, str]:
    """Default official OpenSandbox MCP runtime environment."""
    return {
        _MCP_ENV_API_KEY: "",
    }


def _default_mcp_args() -> list[str]:
    """Default OpenSandbox MCP launcher arguments."""
    return [
        str(_PLUGIN_DIR / _LAUNCHER_FILE),
        "--domain",
        "127.0.0.1:8080",
        "--protocol",
        "http",
        "--use-server-proxy",
    ]


def _is_legacy_bundled_mcp_client(client: object) -> bool:
    """Return True when an existing client points to our removed wrapper."""
    args = getattr(client, "args", None) or []
    return any(str(arg).endswith("mcp_server.py") for arg in args)


def _is_managed_launcher_mcp_client(client: object) -> bool:
    """Return True when an existing client points to our launcher."""
    args = getattr(client, "args", None) or []
    return any(str(arg).endswith(_LAUNCHER_FILE) for arg in args)


def _copy_mcp_client_config(client: object):
    """Copy an MCP client config across supported Pydantic versions."""
    model_copy = getattr(client, "model_copy", None)
    if callable(model_copy):
        return model_copy(deep=True)
    return deepcopy(client)


def _refresh_launcher_args(args: object, default_args: list[str]) -> list[str]:
    """Refresh only the launcher path and preserve user connection args."""
    if not isinstance(args, list):
        return list(default_args)

    refreshed = [str(arg) for arg in args]
    for index, arg in enumerate(refreshed):
        if arg.endswith(_LAUNCHER_FILE):
            refreshed[index] = str(_PLUGIN_DIR / _LAUNCHER_FILE)
            return refreshed
    return list(default_args)


def _has_arg(args: list[str], option: str) -> bool:
    """Return True if args include an option in split or --key=value form."""
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def _set_arg_value(args: list[str], option: str, value: str) -> list[str]:
    """Set an argument value without disturbing the rest of the command."""
    updated = list(args)
    for index, arg in enumerate(updated):
        if arg == option:
            if index + 1 < len(updated) and not updated[index + 1].startswith(
                "--",
            ):
                updated[index + 1] = value
                return updated
            updated.insert(index + 1, value)
            return updated
        if arg.startswith(f"{option}="):
            updated[index] = f"{option}={value}"
            return updated

    updated.extend([option, value])
    return updated


def _has_server_proxy_arg(args: list[str]) -> bool:
    """Return True when args already define server proxy behavior."""
    return _has_arg(args, "--use-server-proxy") or _has_arg(
        args,
        "--no-use-server-proxy",
    )


def _migrate_env_connection_args(
    args: list[str],
    existing_env: object,
) -> list[str]:
    """Move non-secret OpenSandbox env settings into launcher args."""
    if not isinstance(existing_env, dict):
        return args

    migrated_args = list(args)
    env = {str(key): str(value) for key, value in existing_env.items()}

    domain = env.get(_MCP_ENV_DOMAIN, "").strip()
    if domain and not _has_arg(migrated_args, "--domain"):
        migrated_args = _set_arg_value(migrated_args, "--domain", domain)

    proxy_value = env.get(_MCP_ENV_USE_SERVER_PROXY, "").strip().lower()
    if proxy_value and not _has_server_proxy_arg(migrated_args):
        if proxy_value in _MCP_PROXY_TRUE_VALUES:
            migrated_args.append("--use-server-proxy")
        elif proxy_value in _MCP_PROXY_FALSE_VALUES:
            migrated_args.append("--no-use-server-proxy")

    return migrated_args


def _merge_mcp_env(
    existing_env: object,
    default_env: dict[str, str],
) -> dict[str, str]:
    """Preserve only OpenSandbox API key in MCP env."""
    merged = dict(default_env)
    if isinstance(existing_env, dict):
        for key, value in existing_env.items():
            if str(key) == _MCP_ENV_API_KEY:
                merged[_MCP_ENV_API_KEY] = str(value)
    return merged


def _refresh_managed_mcp_client(existing: object, default_client: object):
    """Refresh generated paths without overwriting user connection config."""
    refreshed = _copy_mcp_client_config(existing)
    refreshed.command = getattr(
        default_client,
        "command",
        sys.executable or "python",
    )
    refreshed.cwd = getattr(default_client, "cwd", str(_PLUGIN_DIR))
    refreshed.transport = getattr(default_client, "transport", "stdio")
    refreshed.args = _migrate_env_connection_args(
        _refresh_launcher_args(
            getattr(existing, "args", None),
            getattr(default_client, "args", _default_mcp_args()),
        ),
        getattr(existing, "env", None),
    )
    refreshed.env = _merge_mcp_env(
        getattr(existing, "env", None),
        getattr(default_client, "env", _default_mcp_env()),
    )
    return refreshed


def _mcp_client_changed(left: object, right: object) -> bool:
    """Return True when sync-managed MCP fields differ."""
    fields = ("command", "cwd", "transport", "args", "env")
    return any(
        getattr(left, field, None) != getattr(right, field, None)
        for field in fields
    )


def _sync_opensandbox_mcp_client_to_agents() -> None:
    """Register the official OpenSandbox MCP client on existing agents.

    Newly registered clients are disabled by default so each agent can opt in.
    User-customized ``opensandbox`` MCP client settings are left untouched.
    """
    try:
        from qwenpaw.config.config import (
            MCPClientConfig,
            MCPConfig,
            load_agent_config,
            save_agent_config,
        )
        from qwenpaw.config.utils import load_config
    except ImportError as exc:
        logger.warning("Cannot sync OpenSandbox MCP client to agents: %s", exc)
        return

    try:
        config = load_config()
        profiles = getattr(getattr(config, "agents", None), "profiles", {})
        if not profiles:
            return

        client = MCPClientConfig(
            name="OpenSandbox MCP",
            description=(
                "Official OpenSandbox MCP server for sandbox lifecycle, "
                "command execution, files, metrics, and endpoints."
            ),
            enabled=False,
            transport="stdio",
            command=sys.executable or "python",
            args=_default_mcp_args(),
            env=_default_mcp_env(),
            cwd=str(_PLUGIN_DIR),
        )

        for agent_id, profile in profiles.items():
            workspace_dir = Path(
                getattr(profile, "workspace_dir", ""),
            ).expanduser()
            if workspace_dir and not workspace_dir.exists():
                continue
            agent_config = load_agent_config(agent_id)
            if agent_config.mcp is None:
                agent_config.mcp = MCPConfig(clients={})
            if _MCP_CLIENT_KEY in agent_config.mcp.clients:
                existing = agent_config.mcp.clients[_MCP_CLIENT_KEY]
                if _is_legacy_bundled_mcp_client(existing):
                    migrated_client = _copy_mcp_client_config(client)
                    migrated_client.enabled = existing.enabled
                    agent_config.mcp.clients[_MCP_CLIENT_KEY] = migrated_client
                    save_agent_config(agent_id, agent_config)
                    logger.info(
                        "Migrated OpenSandbox MCP client on agent %s "
                        "to launcher",
                        agent_id,
                    )
                    continue
                if _is_managed_launcher_mcp_client(existing):
                    refreshed_client = _refresh_managed_mcp_client(
                        existing,
                        client,
                    )
                    if not _mcp_client_changed(existing, refreshed_client):
                        continue
                    agent_config.mcp.clients[
                        _MCP_CLIENT_KEY
                    ] = refreshed_client
                    save_agent_config(agent_id, agent_config)
                    logger.info(
                        "Refreshed OpenSandbox MCP client paths on agent %s",
                        agent_id,
                    )
                    continue
                continue
            agent_config.mcp.clients[
                _MCP_CLIENT_KEY
            ] = _copy_mcp_client_config(client)
            save_agent_config(agent_id, agent_config)
            logger.info(
                "Added OpenSandbox MCP client to agent %s disabled",
                agent_id,
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("OpenSandbox MCP client sync failed: %s", exc)


def _remove_legacy_tool_entries_from_agents() -> None:
    """Remove stale non-MCP OpenSandbox tools from existing configs."""
    try:
        from qwenpaw.config.config import (
            load_agent_config,
            save_agent_config,
        )
        from qwenpaw.config.utils import load_config, save_config
    except ImportError as exc:
        logger.warning("Cannot clean legacy OpenSandbox tools: %s", exc)
        return

    try:
        config = load_config()

        root_tools = getattr(
            getattr(config, "tools", None),
            "builtin_tools",
            None,
        )
        if isinstance(root_tools, dict):
            changed_root = False
            for tool_name in _LEGACY_TOOL_NAMES:
                if tool_name in root_tools:
                    del root_tools[tool_name]
                    changed_root = True
            if changed_root:
                save_config(config)
                logger.info(
                    "Removed legacy OpenSandbox tools from root config",
                )

        profiles = getattr(getattr(config, "agents", None), "profiles", {})
        if not profiles:
            return

        for agent_id, profile in profiles.items():
            workspace_dir = Path(
                getattr(profile, "workspace_dir", ""),
            ).expanduser()
            if workspace_dir and not workspace_dir.exists():
                continue

            agent_config = load_agent_config(agent_id)
            builtin_tools = getattr(
                getattr(agent_config, "tools", None),
                "builtin_tools",
                None,
            )
            if not isinstance(builtin_tools, dict):
                continue

            removed = [
                tool_name
                for tool_name in _LEGACY_TOOL_NAMES
                if tool_name in builtin_tools
            ]
            if not removed:
                continue

            for tool_name in removed:
                del builtin_tools[tool_name]
            save_agent_config(agent_id, agent_config)
            logger.info(
                "Removed legacy OpenSandbox tools from agent %s: %s",
                agent_id,
                ", ".join(sorted(removed)),
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("OpenSandbox legacy tool cleanup failed: %s", exc)


def _sync_plugin_skills_to_agents() -> None:
    """Copy bundled skills into existing agent workspaces.

    Newly synced skills are disabled by default.
    """
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
                skill_dir = (
                    get_workspace_skills_dir(workspace_dir) / skill_name
                )
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


def _startup_setup() -> None:
    """Install bundled assets and register the MCP client."""
    try:
        _install_plugin_skills()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("OpenSandbox skill install failed: %s", exc)
    _remove_legacy_tool_entries_from_agents()
    _sync_opensandbox_mcp_client_to_agents()


class OpenSandboxPlugin:
    """Register OpenSandbox startup integration into QwenPaw."""

    def register(self, api: PluginApi) -> None:
        """Register startup setup for skills and MCP client wiring."""
        api.register_startup_hook(
            hook_name="opensandbox_install_skills",
            callback=_startup_setup,
            priority=50,
        )
        logger.info("OpenSandbox plugin registered startup integration")


plugin = OpenSandboxPlugin()
