# -*- coding: utf-8 -*-
"""Grok Video Tool Plugin Entry Point.

Registers ``generate_video_grok`` into the Agent's toolkit.  One tool,
two modes: pure text-to-video by default; image-to-video when the
caller passes ``image_url``.
"""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_tool_module():
    tool_path = os.path.join(_PLUGIN_DIR, "grok_video_tool.py")
    spec = importlib.util.spec_from_file_location(
        "grok_video_tool",
        tool_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrokVideoToolPlugin:
    """Grok Video Tool Plugin."""

    def register(self, api: PluginApi):
        tool = _load_tool_module()

        api.register_tool(
            tool_name="generate_video_grok",
            tool_func=tool.generate_video_grok,
            description=(
                "Generate a short video with xAI Grok Imagine. "
                "Text-to-video by default; image-to-video when image_url "
                "is provided. Generation typically takes 30-90 seconds."
            ),
            icon="🎬",
        )


plugin = GrokVideoToolPlugin()
