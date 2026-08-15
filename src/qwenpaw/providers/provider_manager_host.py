# -*- coding: utf-8 -*-
"""Declared host contract shared by ProviderManager's mixins.

``ProviderManager`` is assembled from two mixins that live in separate
files (discovery and persistence).  Both operate on manager state and on
helpers defined in one of the *other* two files; without a declared
contract those cross-file ``self._*`` references are invisible to static
checking, so renaming a member in one file silently breaks the others.

``ProviderManagerHost`` makes that contract explicit: every attribute or
method a mixin uses but does not define MUST be declared here.  The
mixins inherit this class, which puts the declarations at the end of the
MRO -- real implementations in ``ProviderManager`` or a sibling mixin
always win at runtime, while mypy/pylint can verify each mixin against
the declared surface in isolation.

When a mixin starts using a new cross-file member, declare it here in
the section matching where the implementation lives.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict

from ..config.config import ModelSlotConfig
from .capability_baseline import ExpectedCapabilityRegistry
from .provider import Provider
from .provider_update_fields import PluginUpdateKind


class ProviderManagerHost:
    """Attributes and helpers the manager guarantees to its mixins."""

    # ------------------------------------------------------------------
    # State owned by ProviderManager.__init__
    # ------------------------------------------------------------------
    builtin_providers: Dict[str, Provider]
    custom_providers: Dict[str, Provider]
    plugin_providers: Dict[str, Dict]
    active_model: ModelSlotConfig | None

    root_path: Path
    builtin_path: Path
    custom_path: Path
    plugin_path: Path

    _provider_save_locks: dict[str, asyncio.Lock]
    _discovery_generations: dict[str, int]
    _provider_storage_paths: dict[tuple[str, str], Path]
    _capability_registry: ExpectedCapabilityRegistry

    # ------------------------------------------------------------------
    # Helpers implemented by ProviderManager
    # ------------------------------------------------------------------
    def get_provider(self, provider_id: str) -> Provider | None:
        raise NotImplementedError

    @staticmethod
    def _normalize_provider_id(provider_id: str) -> str:
        raise NotImplementedError

    def _bump_provider_revision(self, provider_id: str) -> int:
        raise NotImplementedError

    def _provider_revision(self, provider_id: str) -> int:
        raise NotImplementedError

    def _is_current_provider(
        self,
        provider_id: str,
        provider: Provider,
        revision: int,
    ) -> bool:
        raise NotImplementedError

    @staticmethod
    def _reset_model_availability(provider: Provider) -> None:
        raise NotImplementedError

    def _ensure_plugin_provider_id_available(
        self,
        provider_id: str,
    ) -> str:
        raise NotImplementedError

    def _apply_default_annotations(self, *, refresh: bool = False) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers implemented by ProviderManagerPersistenceMixin
    # ------------------------------------------------------------------
    @staticmethod
    def _copy_provider_state(target: Provider, source: Provider) -> None:
        raise NotImplementedError

    def _provider_from_data(self, data: Dict) -> Provider:
        raise NotImplementedError

    async def _provider_config_path_async(
        self,
        provider_id: str,
        file_provider_id: str | None = None,
    ) -> Path:
        raise NotImplementedError

    def _save_provider_snapshot_locked(
        self,
        provider_id: str,
        provider: Provider,
        provider_path: Path,
    ) -> None:
        raise NotImplementedError

    async def _restore_latest_snapshot(
        self,
        provider_id: str,
        provider_path: Path,
    ) -> None:
        raise NotImplementedError

    async def _save_provider_config_locked(
        self,
        provider_id: str,
        provider: Provider,
        *,
        update_kind: PluginUpdateKind,
        model_id: str | None,
        fields: set[str] | None,
    ) -> None:
        raise NotImplementedError

    def _merge_provider_snapshot(
        self,
        provider_id: str,
        result: Provider,
        update_kind: PluginUpdateKind,
        *,
        model_id: str | None,
        fields: set[str] | None,
    ) -> Provider:
        raise NotImplementedError

    def _merge_plugin_snapshot(
        self,
        provider_id: str,
        result: Provider,
        update_kind: PluginUpdateKind,
        *,
        model_id: str | None,
        fields: set[str] | None,
    ) -> Provider:
        raise NotImplementedError
