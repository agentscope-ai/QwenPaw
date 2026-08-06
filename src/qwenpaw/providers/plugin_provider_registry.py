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
        registration = self._manager.plugin_providers.get(provider_id)
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

    def register(
        self,
        provider_id: str,
        provider_class: type[Provider],
        label: str,
        base_url: str,
        metadata: dict,
    ) -> None:
        """Register a plugin provider using the compatibility transaction."""
        prepare_registration = getattr(
            self._manager,
            "_prepare_plugin_registration",
        )
        registration = prepare_registration(
            provider_id,
            provider_class,
            label,
            base_url,
            metadata,
        )
        self._manager.plugin_providers[provider_id] = registration
        bump_revision = getattr(self._manager, "_bump_provider_revision")
        bump_revision(provider_id)

    def unregister(self, provider_id: str) -> bool:
        """Remove a plugin registration while retaining persisted config."""
        if provider_id not in self._manager.plugin_providers:
            logger.warning(
                f"unregister_plugin_provider: '{provider_id}' not found",
            )
            return False
        del self._manager.plugin_providers[provider_id]
        bump_revision = getattr(self._manager, "_bump_provider_revision")
        bump_revision(provider_id)
        logger.info(
            f"Unregistered plugin provider '{provider_id}' from memory",
        )
        return True
