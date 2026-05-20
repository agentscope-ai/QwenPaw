# -*- coding: utf-8 -*-
"""Grok Image Tool Plugin Entry Point.

Registers two tools into the Agent's toolkit:
- ``generate_image_grok`` — text-to-image via
  ``/v1/images/generations``
- ``edit_image_grok`` — image-to-image / multi-image edit via
  ``/v1/images/edits``

Mirrors upstream's ``gpt-image2`` plugin convention: ``register_tool``
API + per-plugin file naming + single ``register()`` method.
"""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_tool_module():
    """Load grok_image_tool.py from this plugin's directory via importlib."""
    tool_path = os.path.join(_PLUGIN_DIR, "grok_image_tool.py")
    spec = importlib.util.spec_from_file_location(
        "grok_image_tool",
        tool_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrokImageToolPlugin:
    """Grok Image Tool Plugin.

    Registers ``generate_image_grok`` and ``edit_image_grok`` tools.
    """

    def register(self, api: PluginApi):
        tool = _load_tool_module()

        api.register_tool(
            tool_name="generate_image_grok",
            tool_func=tool.generate_image_grok,
            description=(
                "Generate a new image from a text prompt using xAI "
                "Grok Imagine (Aurora). Text-to-image only — to edit "
                "an existing image, use the `edit_image_grok` tool instead."
            ),
            icon="🎨",
        )

        api.register_tool(
            tool_name="edit_image_grok",
            tool_func=tool.edit_image_grok,
            description=(
                "Edit an existing image or compose from multiple "
                "references using xAI Grok Imagine. Source images accept "
                "an http(s) URL or a `data:image/...;base64,...` URI."
            ),
            icon="🖼️",
        )


# Export plugin instance — picked up by the loader.
plugin = GrokImageToolPlugin()
