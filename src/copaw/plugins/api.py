# -*- coding: utf-8 -*-
"""Plugin API for plugin developers."""

from typing import Any, Dict, Type
import logging

logger = logging.getLogger(__name__)


class PluginApi:
    """Plugin API - Interface for plugin developers.

    This class provides the API that plugins use to register their
    capabilities with CoPaw.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        manifest: Dict[str, Any] = None,
    ):
        """Initialize plugin API.

        Args:
            plugin_id: Unique plugin identifier
            config: Plugin configuration dictionary
            manifest: Plugin manifest dictionary (from plugin.json)
        """
        self.plugin_id = plugin_id
        self.config = config
        self.manifest = manifest or {}
        self._registry = None

    def set_registry(self, registry):
        """Set registry reference (called by loader).

        Args:
            registry: PluginRegistry instance
        """
        self._registry = registry

    def register_provider(
        self,
        provider_id: str,
        provider_class: Type,
        label: str = "",
        base_url: str = "",
        **metadata,
    ):
        """Register a custom LLM Provider.

        Args:
            provider_id: Unique provider identifier
            provider_class: Provider class (inherits from BaseProvider)
            label: Display name for the provider
            base_url: API base URL
            **metadata: Additional metadata (chat_model, require_api_key, etc.)

        Example:
            >>> api.register_provider(
            ...     provider_id="my-provider",
            ...     provider_class=MyProvider,
            ...     label="My Custom Provider",
            ...     base_url="https://api.example.com/v1",
            ...     chat_model="OpenAIChatModel",
            ...     require_api_key=True,
            ... )
        """
        if self._registry:
            # Merge plugin manifest meta with provider metadata
            merged_metadata = dict(metadata)
            if "meta" in self.manifest:
                merged_metadata["meta"] = self.manifest["meta"]

            self._registry.register_provider(
                plugin_id=self.plugin_id,
                provider_id=provider_id,
                provider_class=provider_class,
                label=label or provider_id,
                base_url=base_url,
                metadata=merged_metadata,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered provider "
                f"'{provider_id}'",
            )

    @property
    def runtime(self):
        """Access runtime helper functions.

        Returns:
            RuntimeHelpers instance or None
        """
        if self._registry:
            return self._registry.get_runtime_helpers()
        return None
