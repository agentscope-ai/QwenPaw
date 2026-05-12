# -*- coding: utf-8 -*-
"""GPT Image 2 Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_tool_module():
    """Load gpt_image2_tool.py from this plugin's directory via importlib."""
    tool_path = os.path.join(_PLUGIN_DIR, "gpt_image2_tool.py")
    spec = importlib.util.spec_from_file_location(
        "gpt_image2_tool",
        tool_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GPTImage2ToolPlugin:
    """GPT Image 2 Tool Plugin.

    Registers generate_image_gpt and edit_image_gpt tools into
    the Agent's toolkit.
    """

    def register(self, api: PluginApi):
        """Register GPT Image 2 tools.

        Args:
            api: PluginApi instance.
        """
        tool = _load_tool_module()

        api.register_tool(
            tool_name="generate_image_gpt",
            tool_func=tool.generate_image_gpt,
            description=("Generate images using OpenAI GPT Image 2"),
            icon="🎨",
        )

        api.register_tool(
            tool_name="edit_image_gpt",
            tool_func=tool.edit_image_gpt,
            description=(
                "Edit or generate images using reference images "
                "with OpenAI GPT Image 2"
            ),
            icon="🖼️",
        )

        logger.info("GPT Image 2 tool plugin registered")


# Export plugin instance
plugin = GPTImage2ToolPlugin()
