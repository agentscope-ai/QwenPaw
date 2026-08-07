# -*- coding: utf-8 -*-
"""Computer Use tool plugin entry point.

Provides the ``computer_use`` desktop-automation tool, its governance
metadata, and the window-bound usage skill. Windows and macOS are supported
through the native helper; the tool is skipped where no helper runtime is
available.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from qwenpaw.plugins.api import PluginApi

# Use a qwenpaw.* logger name so desktop log config actually captures us.
# ``__name__`` under plugin loading is ``plugin_computer_use``, which
# currently never appears in qwenpaw.log.
logger = logging.getLogger("qwenpaw.plugins.computer_use")

_PLUGIN_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

_TOOL_NAME = "computer_use"
_TOOL_DESCRIPTION = (
    "Desktop GUI automation with window-bound screenshots and inputs"
)


def _ensure_importable() -> None:
    """Expose the bundled ``computer_use`` package on ``sys.path``."""
    plugin_dir = str(_PLUGIN_DIR)
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)


def _seed_tool_config(agent_config: Any) -> bool:
    """Add this plugin's tool to one agent configuration when missing.

    Only an absent entry is written. An existing entry carries the user's
    own choice -- including having turned the tool off for that agent --
    and overwriting it here would silently undo that choice on every
    startup.
    """
    from qwenpaw.config.config import BuiltinToolConfig, ToolsConfig

    if agent_config.tools is None:
        agent_config.tools = ToolsConfig()

    if _TOOL_NAME in agent_config.tools.builtin_tools:
        return False

    agent_config.tools.builtin_tools[_TOOL_NAME] = BuiltinToolConfig(
        name=_TOOL_NAME,
        enabled=True,
        description=_TOOL_DESCRIPTION,
        icon="screen",
    )
    return True


def _seed_tool_for_agent(agent_id: str) -> None:
    """Persist the plugin-owned tool setting for one agent."""
    from qwenpaw.config.config import load_agent_config, save_agent_config

    try:
        agent_config = load_agent_config(agent_id)
        if _seed_tool_config(agent_config):
            save_agent_config(agent_id, agent_config)
    except Exception:  # noqa: BLE001 - do not break plugin startup
        logger.exception(
            "Failed to seed computer_use for agent '%s'",
            agent_id,
        )


def _seed_tool_for_existing_agents() -> None:
    """Expose the tool to every agent that has not chosen otherwise."""
    from qwenpaw.config.utils import load_config

    profiles = (
        getattr(
            getattr(load_config(), "agents", None),
            "profiles",
            {},
        )
        or {}
    )
    for agent_id in profiles:
        _seed_tool_for_agent(agent_id)


class ComputerUseToolPlugin:
    """Registers the ``computer_use`` tool, governance, and skill.

    The plugin's feature switch is the master gate: off means no call may
    act, for any agent. While it is on, each agent's own tool setting --
    seeded to enabled, then left alone -- decides whether that agent
    exposes the tool.
    """

    def register(self, api: PluginApi) -> None:
        _ensure_importable()

        from qwenpaw.app.computer_use import HostRuntimeProvider
        from computer_use.router import build_router

        api.register_http_router(
            build_router(),
            prefix="/computer-use",
            tags=["computer-use"],
        )

        if not HostRuntimeProvider.is_available():
            status = HostRuntimeProvider.status()
            reason = (
                "this platform has no native helper"
                if not status.supported_platform
                else "the desktop host offered no runtime"
            )
            logger.warning(
                "Computer Use tool registration is skipped: %s",
                reason,
            )
            return

        from computer_use import computer_use
        from computer_use.lifecycle import ComputerUseTurnEndHook

        # One call carries the whole pipeline: governance (classified
        # internal, approval rules gate on the ``action`` argument),
        # runtime bridging into every live workspace, bootstrap wiring
        # for future ones, and the current agent's config entry.
        api.register_tool(
            tool_name=_TOOL_NAME,
            tool_func=computer_use,
            description=_TOOL_DESCRIPTION,
            icon="screen",
            enabled=True,
            tool_type="internal",
            target_param="action",
        )

        api.register_startup_hook(
            hook_name="computer_use_config",
            callback=_seed_tool_for_existing_agents,
            priority=55,
        )

        def _seed_new_workspace(workspace_info: dict) -> None:
            agent_id = workspace_info.get("agent_id")
            if isinstance(agent_id, str) and agent_id:
                _seed_tool_for_agent(agent_id)

        api.register_workspace_created_hook(
            hook_name="computer_use_config",
            callback=_seed_new_workspace,
            priority=60,
        )

        api.register_skill_provider(
            skills_dir=_PLUGIN_DIR / "skills",
            enabled_by_default=True,
            channels=["all"],
        )

        # The host opens a turn per request; this closes it again, so the
        # native connection and the helper's per-turn state are released
        # rather than held until some later request supplies a new id.
        api.register_runtime_hook(ComputerUseTurnEndHook())

        logger.info("Computer Use tool plugin registered")


plugin = ComputerUseToolPlugin()
