# -*- coding: utf-8 -*-
"""GPT Image 2 Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class GPTImage2ToolPlugin:
    """GPT Image 2 Tool Plugin.

    Registers the generate_image_gpt tool into the Agent's toolkit.
    This is a pure backend plugin - no frontend code required.
    """

    def register(self, api: PluginApi):
        """Register the GPT Image 2 tool.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering GPT Image 2 tool...")

        # Register startup hook to add tool to toolkit
        api.register_startup_hook(
            hook_name="register_gpt_image2_tool",
            callback=self._register_tool,
            priority=50,
        )

        logger.info("✓ GPT Image 2 tool plugin registered")

    def _register_tool(self):
        """Register the generate_image_gpt tool to Agent toolkit.

        This is called during application startup.
        """
        try:
            # Load tool module
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            tool_path = os.path.join(plugin_dir, "tool.py")

            spec = importlib.util.spec_from_file_location(
                "gpt_image2_tool",
                tool_path,
            )
            tool_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tool_module)

            generate_image_gpt = tool_module.generate_image_gpt

            # Register tool function globally
            import qwenpaw.agents.tools as tools_module

            setattr(tools_module, "generate_image_gpt", generate_image_gpt)
            if "generate_image_gpt" not in tools_module.__all__:
                tools_module.__all__.append("generate_image_gpt")

            logger.info("✓ Registered tool function: generate_image_gpt")

            # Add tool to current agent's config
            # Note: This will be executed when the agent starts up
            from qwenpaw.config.config import (
                BuiltinToolConfig,
                load_agent_config,
                save_agent_config,
            )
            from qwenpaw.app.agent_context import get_current_agent_id

            tool_name = "generate_image_gpt"

            try:
                # Get current agent ID
                agent_id = get_current_agent_id()
                if not agent_id:
                    logger.warning(
                        "No current agent ID found, "
                        "tool will be registered later",
                    )
                    return

                # Load agent config
                agent_config = load_agent_config(agent_id)

                # Ensure tools config exists
                if not agent_config.tools:
                    from qwenpaw.config.config import ToolsConfig

                    agent_config.tools = ToolsConfig()

                # Add tool if not exists
                if tool_name not in agent_config.tools.builtin_tools:
                    agent_config.tools.builtin_tools[
                        tool_name
                    ] = BuiltinToolConfig(
                        name=tool_name,
                        enabled=False,  # Default disabled
                        description=(
                            "Generate images using OpenAI GPT Image 2"
                        ),
                        display_to_user=True,
                        async_execution=False,
                        icon="🎨",
                    )
                    save_agent_config(agent_id, agent_config)
                    logger.info(
                        f"✓ Added {tool_name} to agent {agent_id} "
                        f"(disabled)",
                    )
                else:
                    logger.info(
                        f"Tool {tool_name} already exists in agent "
                        f"{agent_id}",
                    )
            except Exception as ex:
                logger.warning(
                    f"Failed to add tool to current agent: {ex}. "
                    f"Tool will be available after restart.",
                )

        except Exception as e:
            logger.error(
                f"Failed to register GPT Image 2 tool: {e}",
                exc_info=True,
            )


# Export plugin instance
plugin = GPTImage2ToolPlugin()
