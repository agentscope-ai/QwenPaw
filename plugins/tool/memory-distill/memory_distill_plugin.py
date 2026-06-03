# -*- coding: utf-8 -*-
"""Memory Distillation Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class MemoryDistillToolPlugin:
    """Memory Distillation Tool Plugin."""

    def register(self, api: PluginApi):
        """Register memory distillation tools via PluginApi."""
        logger.info("Registering Memory Distillation tools...")

        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        tool_path = os.path.join(plugin_dir, "memory_distill_tool.py")
        spec = importlib.util.spec_from_file_location(
            "memory_distill_tool",
            tool_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Failed to load memory distill tool module from {tool_path}",
            )
        tool_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool_module)

        api.register_tool(
            "distill_memory",
            tool_module.distill_memory,
            description=(
                "Distill daily notes into MEMORY.md using title-diffing to "
                "find genuinely new information."
            ),
            icon="🧠",
            enabled=False,
        )
        api.register_tool(
            "consolidate_memory",
            tool_module.consolidate_memory,
            description=(
                "Run the full memory consolidation pipeline: distill, "
                "archive, clean, and audit."
            ),
            icon="🧠",
            enabled=False,
        )
        api.register_tool(
            "inspect_memory",
            tool_module.inspect_memory,
            description=(
                "Inspect MEMORY.md and daily notes health, size, and recent "
                "activity."
            ),
            icon="🔍",
            enabled=False,
        )

        logger.info("✓ Memory Distillation tool plugin registered")
