# -*- coding: utf-8 -*-
"""Plugin provider registry operations for ProviderManager."""

from __future__ import annotations

import logging
from typing import Any

from .provider import Provider, ProviderInfo, project_model_windows

logger = logging.getLogger(__name__)


def _catalog_decision(provider_class: Any) -> bool | None:
    """The static-catalog decision for *provider_class*, or ``None`` when it
    cannot be known without an instance.

    ``None`` covers the pre-existing plugin pattern of overriding the
    instance-level ``_context_catalog_enabled`` alone: the class-level hook
    would answer for a class whose runtime resolution may differ, and a
    guessed window would then contradict the window the runtime enforces (and
    change again as soon as the provider is saved and re-read through
    ``get_info``). The caller reports no effective window for those models
    rather than a wrong one. A class declaring both hooks is trusted, since
    the class-level answer is then deliberate.
    """
    for klass in provider_class.__mro__:
        if klass is Provider:
            break
        if "_context_catalog_enabled" in vars(klass) and (
            "context_catalog_enabled" not in vars(klass)
        ):
            return None
    hook = getattr(provider_class, "context_catalog_enabled", None)
    return bool(hook()) if callable(hook) else True


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
        """Return plugin provider snapshots without materializing clients.

        The stored registration answers the provider list directly and never
        went through ``Provider.get_info``, so the read-only window projection
        is applied here, on the way out: the registration itself stays free of
        derived state. A registration whose catalog decision is unknown (see
        :func:`_catalog_decision`) is returned unprojected, so the list never
        shows a window the runtime may resolve differently.
        """
        infos: list[ProviderInfo] = []
        for registration in self._manager.plugin_providers.values():
            info = registration["info"]
            use_catalog = _catalog_decision(registration["class"])
            if use_catalog is None:
                infos.append(info)
                continue
            infos.append(
                project_model_windows(info, use_catalog=use_catalog),
            )
        return infos

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
