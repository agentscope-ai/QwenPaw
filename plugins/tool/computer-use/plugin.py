# -*- coding: utf-8 -*-
"""Computer Use tool plugin entry point.

Provides the ``computer_use`` desktop-automation tool, its governance
metadata, and the window-bound usage skill. Windows only; the backend
raises ``NotImplementedError`` on other platforms.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from qwenpaw.plugins.api import PluginApi

# Use a qwenpaw.* logger name so desktop log config actually captures us.
# ``__name__`` under plugin loading is ``plugin_computer_use_tool``, which
# currently never appears in qwenpaw.log.
logger = logging.getLogger("qwenpaw.plugins.computer_use_tool")

_PLUGIN_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

_TOOL_NAME = "computer_use"
_TOOL_DESCRIPTION = (
    "Desktop GUI automation with window-bound screenshots and inputs"
)


def _ensure_importable() -> None:
    """Expose the bundled ``computer_use_tool`` package on ``sys.path``."""
    plugin_dir = str(_PLUGIN_DIR)
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)


def _register_governance() -> None:
    """Register governance metadata for the ComputerUse policy tool.

    ``computer_use`` targets the ``action`` argument and is classified as
    an internal tool, so approval rules can gate individual actions.
    """
    from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY

    DEFAULT_REGISTRY.register("ComputerUse", "internal", "action")
    DEFAULT_REGISTRY.register_python_name("computer_use", "ComputerUse")
    logger.info("Registered ComputerUse governance metadata")


def _tool_descriptor() -> Any | None:
    """Return the ``ToolDescriptor`` attached to the ``computer_use`` func.

    The function is decorated with ``@tool_descriptor`` (enabled by default,
    async), so the descriptor is ready to hand to a per-workspace
    ``ToolRegistry``. Desktop automation is gated by the plugin's own feature
    switch rather than by per-agent tool enablement, so the tool is wired into
    every workspace and the switch decides whether it may act.
    """
    _ensure_importable()
    from computer_use_tool import computer_use

    return getattr(computer_use, "_tool_descriptor", None)


def _ensure_tool_enabled(agent_config: Any) -> bool:
    """Ensure this plugin's tool is enabled in one agent configuration."""
    from qwenpaw.config.config import BuiltinToolConfig, ToolsConfig

    if agent_config.tools is None:
        agent_config.tools = ToolsConfig()

    tool_config = agent_config.tools.builtin_tools.get(_TOOL_NAME)
    if tool_config is None:
        agent_config.tools.builtin_tools[_TOOL_NAME] = BuiltinToolConfig(
            name=_TOOL_NAME,
            enabled=True,
            description=_TOOL_DESCRIPTION,
            icon="screen",
        )
        return True

    if tool_config.enabled:
        return False

    tool_config.enabled = True
    return True


def _enable_tool_for_agent(agent_id: str) -> None:
    """Persist the plugin-owned tool setting for one agent."""
    from qwenpaw.config.config import load_agent_config, save_agent_config

    try:
        agent_config = load_agent_config(agent_id)
        if _ensure_tool_enabled(agent_config):
            save_agent_config(agent_id, agent_config)
    except Exception:  # noqa: BLE001 - do not break plugin startup
        logger.exception(
            "Failed to enable computer_use for agent '%s'",
            agent_id,
        )


def _enable_tool_for_existing_agents() -> None:
    """Make plugin availability the only enablement switch for its tool."""
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
        _enable_tool_for_agent(agent_id)


def _register_into_workspace(workspace: Any) -> None:
    """Register the ``computer_use`` descriptor into one workspace.

    ``PluginApi.register_tool`` only wires the tool into the UI config; it
    never reaches the per-workspace ``ToolRegistry`` that feeds the model's
    toolkit. This bridges that gap for our own tool without touching core.
    Idempotent: skips if the name is already present.
    """
    agent_id = getattr(workspace, "agent_id", "?")
    plugins = getattr(workspace, "plugins", None)
    tool_registry = getattr(plugins, "tool_registry", None)
    if tool_registry is None:
        logger.warning(
            "No tool_registry on workspace '%s'; skip toolkit wiring",
            agent_id,
        )
        return
    if _TOOL_NAME in tool_registry:
        logger.info(
            "'%s' already in toolkit for workspace '%s'",
            _TOOL_NAME,
            agent_id,
        )
        return
    desc = _tool_descriptor()
    if desc is None:
        logger.warning(
            "computer_use has no _tool_descriptor; skip toolkit wiring",
        )
        return
    try:
        tool_registry.register(desc)
        logger.info(
            "Wired '%s' into toolkit for workspace '%s' (tools=%s)",
            _TOOL_NAME,
            agent_id,
            len(tool_registry),
        )
    except Exception:  # noqa: BLE001 - never break workspace startup
        logger.exception(
            "computer_use toolkit registration failed for '%s'",
            agent_id,
        )


class ComputerUseToolPlugin:
    """Registers the ``computer_use`` tool, governance, and skill."""

    def register(self, api: PluginApi) -> None:
        _ensure_importable()

        from qwenpaw.app.computer_use import HostRuntimeProvider
        from computer_use_tool.router import build_router

        api.register_http_router(
            build_router(),
            prefix="/computer-use",
            tags=["computer-use"],
        )

        if not HostRuntimeProvider.is_available():
            logger.warning(
                "Computer Use native runtime is unavailable; tool "
                "registration is skipped",
            )
            return

        from computer_use_tool import computer_use

        api.register_tool(
            tool_name="computer_use",
            tool_func=computer_use,
            description=_TOOL_DESCRIPTION,
            icon="screen",
            enabled=True,
        )

        api.register_startup_hook(
            hook_name="computer_use_config",
            callback=_enable_tool_for_existing_agents,
            priority=55,
        )

        api.register_startup_hook(
            hook_name="computer_use_governance",
            callback=_register_governance,
            priority=40,
        )

        def _wire_existing_workspaces() -> None:
            # The plugin API exposes no public way to reach every workspace,
            # so the registration helper it uses internally is reused here.
            # pylint: disable=protected-access
            workspaces = list(api._get_all_workspaces())
            logger.info(
                "computer_use toolkit wiring: %d workspace(s)",
                len(workspaces),
            )
            if not workspaces:
                logger.warning(
                    "No workspaces available for computer_use toolkit wiring",
                )
                return
            for workspace in workspaces:
                _register_into_workspace(workspace)

        def _wire_new_workspace(workspace_info: dict) -> None:
            # pylint: disable=protected-access
            agent_id = workspace_info.get("agent_id")
            if isinstance(agent_id, str) and agent_id:
                _enable_tool_for_agent(agent_id)
            workspace = api._get_workspace_from_info(workspace_info)
            if workspace is None:
                logger.warning(
                    "computer_use toolkit: workspace not found for %s",
                    workspace_info.get("agent_id"),
                )
                return
            _register_into_workspace(workspace)

        api.register_startup_hook(
            hook_name="computer_use_toolkit",
            callback=_wire_existing_workspaces,
            priority=60,
        )

        api.register_workspace_created_hook(
            hook_name="computer_use_toolkit",
            callback=_wire_new_workspace,
            priority=60,
        )

        api.register_skill_provider(
            skills_dir=_PLUGIN_DIR / "skills",
            enabled_by_default=True,
            channels=["all"],
        )

        logger.info("Computer Use tool plugin registered")


plugin = ComputerUseToolPlugin()
