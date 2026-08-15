# -*- coding: utf-8 -*-
"""Plugin provider registry operations for ProviderManager."""

from __future__ import annotations

import logging
from typing import Any

from .provider import Provider, ProviderInfo

logger = logging.getLogger(__name__)


class PluginProviderRegistry:
    """Manage plugin provider instances and in-memory registrations."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def get_provider(self, provider_id: str) -> Provider | None:
        """Materialize one registered plugin provider."""
        normalize_id = getattr(self._manager, "_normalize_provider_id")
        provider_key = normalize_id(provider_id)
        registration = self._manager.plugin_providers.get(provider_key)
        if registration is None:
            return None
        provider_info = registration["info"]
        provider_class = registration["class"]
        return provider_class(**provider_info.model_dump())

    def list_provider_infos(self) -> list[ProviderInfo]:
        """Return plugin provider snapshots without materializing clients."""
        return [
            registration["info"]
            for registration in self._manager.plugin_providers.values()
        ]

    def unregister(self, provider_id: str) -> bool:
        """Remove a plugin registration while retaining persisted config."""
        normalize_id = getattr(self._manager, "_normalize_provider_id")
        provider_key = normalize_id(provider_id)
        if provider_key not in self._manager.plugin_providers:
            logger.warning(
                f"unregister_plugin_provider: '{provider_id}' not found",
            )
            return False
        del self._manager.plugin_providers[provider_key]
        bump_revision = getattr(self._manager, "_bump_provider_revision")
        bump_revision(provider_key)
        logger.info(
            f"Unregistered plugin provider '{provider_id}' from memory",
        )
        return True
