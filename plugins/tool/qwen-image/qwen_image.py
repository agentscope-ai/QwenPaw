# -*- coding: utf-8 -*-
"""Qwen-Image Tool Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_tool_module():
    """Load qwen_image_tool.py from this plugin's directory via importlib."""
    tool_path = os.path.join(_PLUGIN_DIR, "qwen_image_tool.py")
    spec = importlib.util.spec_from_file_location(
        "qwen_image_tool",
        tool_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QwenImageToolPlugin:
    """Qwen-Image Tool Plugin.

    Registers generate_image_qwen and edit_image_qwen tools into
    the Agent's toolkit.
    """

    def register(self, api: PluginApi):
        """Register Qwen-Image tools.

        Args:
            api: PluginApi instance.
        """
        tool = _load_tool_module()

        api.register_tool(
            tool_name="generate_image_qwen",
            tool_func=tool.generate_image_qwen,
            description=(
                "Generate images from text prompts " "using Qwen-Image"
            ),
            icon="🖼️",
        )

        api.register_tool(
            tool_name="edit_image_qwen",
            tool_func=tool.edit_image_qwen,
            description="Edit or fuse images using Qwen-Image",
            icon="✏️",
        )

        logger.info("Qwen-Image tool plugin registered")


# Export plugin instance
plugin = QwenImageToolPlugin()
