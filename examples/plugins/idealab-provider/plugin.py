# -*- coding: utf-8 -*-
"""Alibaba IdeaLab Provider Plugin for CoPaw."""

from qwenpaw.plugins.api import PluginApi
import logging

logger = logging.getLogger(__name__)


class IdeaLabProviderPlugin:
    """Alibaba IdeaLab Provider Plugin."""

    def register(self, api: PluginApi):
        """Register plugin capabilities.

        Args:
            api: Plugin API instance
        """
        import os
        import importlib.util

        # Load provider module from same directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        provider_path = os.path.join(plugin_dir, "provider.py")

        spec = importlib.util.spec_from_file_location("idealab_provider", provider_path)
        provider_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provider_module)

        IdeaLabProvider = provider_module.IdeaLabProvider

        api.register_provider(
            provider_id="idealab",
            provider_class=IdeaLabProvider,
            label="Alibaba IdeaLab",
            base_url="https://idealab.alibaba-inc.com/api/openai/v1",
            chat_model="OpenAIChatModel",
            require_api_key=True,
            support_model_discovery=False,
        )

        logger.info("✓ Alibaba IdeaLab Provider registered")


# Export plugin instance
plugin = IdeaLabProviderPlugin()
