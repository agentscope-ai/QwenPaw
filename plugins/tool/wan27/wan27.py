# -*- coding: utf-8 -*-
"""Wan 2.7 Video Generation Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_tool_module():
    """Load wan27_tool.py from this plugin's directory via importlib."""
    tool_path = os.path.join(_PLUGIN_DIR, "wan27_tool.py")
    spec = importlib.util.spec_from_file_location(
        "wan27_tool",
        tool_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Wan27ToolPlugin:
    """Wan 2.7 Video Generation Tool Plugin.

    Registers text_to_video_wan, image_to_video_wan, and
    reference_to_video_wan tools into the Agent's toolkit.
    """

    def register(self, api: PluginApi):
        """Register Wan 2.7 video tools.

        Args:
            api: PluginApi instance.
        """
        tool = _load_tool_module()

        api.register_tool(
            tool_name="text_to_video_wan",
            tool_func=tool.text_to_video_wan,
            description=("Generate videos from text prompts " "using Wan 2.7"),
            icon="🎬",
        )

        api.register_tool(
            tool_name="image_to_video_wan",
            tool_func=tool.image_to_video_wan,
            description=("Generate videos from images using Wan 2.7"),
            icon="🎞️",
        )

        api.register_tool(
            tool_name="reference_to_video_wan",
            tool_func=tool.reference_to_video_wan,
            description=(
                "Generate videos with character references " "using Wan 2.7"
            ),
            icon="🎭",
        )

        logger.info("Wan 2.7 tool plugin registered")


# Export plugin instance
plugin = Wan27ToolPlugin()
