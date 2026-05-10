# -*- coding: utf-8 -*-
"""OpenWond Draw Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class OpenWondDrawToolPlugin:
    """OpenWond Draw Tool Plugin.

    Registers generate_image_openwond tool into the Agent's toolkit.
    """

    def register(self, api: PluginApi):
        """Register the OpenWond draw tool.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering OpenWond Draw tool...")

        api.register_startup_hook(
            hook_name="register_openwond_draw_tool",
            callback=self._register_tool,
            priority=50,
        )

        logger.info("✓ OpenWond Draw tool plugin registered")

    def _register_tool(self):
        """Register the generate_image_openwond tool to Agent toolkit."""
        try:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            tool_path = os.path.join(plugin_dir, "tool.py")

            spec = importlib.util.spec_from_file_location(
                "openwond_draw_tool",
                tool_path,
            )
            tool_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tool_module)

            generate_image_openwond = tool_module.generate_image_openwond

            import qwenpaw.agents.tools as tools_module

            setattr(
                tools_module,
                "generate_image_openwond",
                generate_image_openwond,
            )
            if "generate_image_openwond" not in tools_module.__all__:
                tools_module.__all__.append("generate_image_openwond")

            logger.info(
                "✓ Registered tool function: generate_image_openwond",
            )

            from qwenpaw.config.config import (
                BuiltinToolConfig,
                load_agent_config,
                save_agent_config,
            )
            from qwenpaw.app.agent_context import get_current_agent_id

            try:
                agent_id = get_current_agent_id()
                if not agent_id:
                    return

                agent_config = load_agent_config(agent_id)

                if not agent_config.tools:
                    from qwenpaw.config.config import ToolsConfig
                    agent_config.tools = ToolsConfig()

                tool_name = "generate_image_openwond"
                existing_names = [
                    t.name for t in (
                        agent_config.tools.builtin_tools or []
                    )
                ]
                if tool_name not in existing_names:
                    tool_cfg = BuiltinToolConfig(
                        name=tool_name,
                        enabled=True,
                    )
                    if agent_config.tools.builtin_tools is None:
                        agent_config.tools.builtin_tools = []
                    agent_config.tools.builtin_tools.append(tool_cfg)

                save_agent_config(agent_config)
                logger.info(
                    f"✓ Tool added to agent {agent_id} config",
                )

            except Exception as e:
                logger.warning(
                    f"Could not update agent config: {e}",
                )

        except Exception as e:
            logger.error(
                f"Failed to register openwond draw tool: {e}",
            )
