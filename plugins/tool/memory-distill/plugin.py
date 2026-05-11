# -*- coding: utf-8 -*-
"""Memory Distillation Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class MemoryDistillToolPlugin:
    """Memory Distillation Tool Plugin.

    Registers consolidate_memory and distill_memory tools into the
    Agent's toolkit. These tools help agents consolidate daily notes,
    detect genuinely new information via title-diffing, and maintain
    MEMORY.md efficiently.
    """

    def register(self, api: PluginApi):
        """Register the memory distillation tools.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering Memory Distillation tools...")

        api.register_startup_hook(
            hook_name="register_memory_distill_tools",
            callback=self._register_tools,
            priority=50,
        )

        logger.info("✓ Memory Distillation tool plugin registered")

    def _register_tools(self):
        """Register the consolidate_memory and distill_memory tools."""
        try:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            tool_path = os.path.join(plugin_dir, "tool.py")

            spec = importlib.util.spec_from_file_location(
                "memory_distill_tool",
                tool_path,
            )
            tool_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tool_module)

            # Register all tools
            import qwenpaw.agents.tools as tools_module

            tool_functions = [
                "consolidate_memory",
                "distill_memory",
                "inspect_memory",
            ]

            for func_name in tool_functions:
                func = getattr(tool_module, func_name, None)
                if func:
                    setattr(tools_module, func_name, func)
                    if func_name not in tools_module.__all__:
                        tools_module.__all__.append(func_name)
                    logger.info(f"✓ Registered tool function: {func_name}")

            # Add tools to current agent's config
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

                for func_name in tool_functions:
                    tool_cfg = BuiltinToolConfig(
                        name=func_name,
                        enabled=True,
                    )
                    existing_names = [
                        t.name
                        for t in (agent_config.tools.builtin_tools or [])
                    ]
                    if func_name not in existing_names:
                        if agent_config.tools.builtin_tools is None:
                            agent_config.tools.builtin_tools = []
                        agent_config.tools.builtin_tools.append(tool_cfg)

                save_agent_config(agent_config)
                logger.info(f"✓ Tools added to agent {agent_id} config")

            except Exception as e:
                logger.warning(
                    f"Could not update agent config: {e}",
                )

        except Exception as e:
            logger.error(
                f"Failed to register memory distill tools: {e}",
            )
