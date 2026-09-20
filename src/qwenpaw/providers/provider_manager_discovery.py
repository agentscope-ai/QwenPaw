# -*- coding: utf-8 -*-
"""Discovery, availability, and catalog operations for ProviderManager."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal

from ..constant import EnvVarLoader
from ..exceptions import ProviderError
from ..utils.io_utils import run_async_to_completion, run_sync_io
from ..utils.logging import sanitize_log_value
from . import capability_baseline
from . import model_catalog
from .capability_baseline import (
    CAPABILITY_URL_ENV,
)
from .provider import (
    ModelConnectionResult,
    ModelInfo,
    Provider,
)
from .provider_catalog import BUILTIN_PROVIDER_CATALOG_KEYS
from .provider_manager_host import ProviderManagerHost
from .provider_discovery import (
    ProviderModelDiscoveryResult,
    apply_discovery_metadata,
    classify_discovery_error,
    normalize_discovered_models,
)
from .model_sync import sync_due
from .provider_model_availability import (
    ProviderModelCheckResult,
    classify_model_check,
)

logger = logging.getLogger(__name__)


# The host's stubs are implemented by ProviderManager / the sibling
# mixin once the class is assembled; this mixin never instantiates
# standalone, so the inherited "abstract" members are intentional.
class ProviderManagerDiscoveryMixin(
    ProviderManagerHost,
):  # pylint: disable=abstract-method
    """Provide discovery, availability, and catalog manager operations."""

    async def fetch_provider_models(
        self,
        provider_id: str,
        save: bool = True,
    ) -> List[ModelInfo]:
        """Fetch the list of available models from a provider.

        Args:
            provider_id: The ID of the provider to fetch models from.
            save: If True, save the discovered models to the provider
                configuration. Defaults to True.

        Returns:
            List of ModelInfo objects representing available models.
        """
        result = await self.discover_provider_models(provider_id, save=save)
        return result.models if result.success else []

    def materialize_discovery_provider(
        self,
        provider_id: str,
        overrides: Dict | None = None,
    ) -> Provider:
        """Build a protocol-correct copy for one discovery operation."""
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        payload = provider.model_dump()
        payload.update(
            {
                key: value
                for key, value in (overrides or {}).items()
                if value is not None
            },
        )
        return self._provider_from_data(payload)

    async def _save_discovery_locked(
        self,
        provider_id: str,
        provider: Provider,
        *,
        revision: int,
        generation: int | None,
        **fields: Any,
    ) -> bool:
        """Persist a discovery outcome if its snapshot is still current."""
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            return await run_async_to_completion(
                self._save_discovery_snapshot(
                    provider_id,
                    provider,
                    revision=revision,
                    generation=generation,
                    **fields,
                ),
            )

    async def prepare_provider_model_discovery(
        self,
        provider_id: str,
    ) -> tuple[Provider, int, int] | None:
        """Reserve a persisted discovery without waiting for remote I/O."""
        provider_id = self._normalize_provider_id(provider_id)
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            provider = await run_sync_io(self.get_provider, provider_id)
            if provider is None:
                return None
            if provider.models_syncing:
                return None
            provider.models_syncing = True
            generation = self._discovery_generations.get(provider_id, 0) + 1
            self._discovery_generations[provider_id] = generation
            return (
                provider,
                self._provider_revision(provider_id),
                generation,
            )

    async def _clear_discovery_syncing(
        self,
        provider_id: str,
        generation: int | None,
    ) -> None:
        """Clear transient sync state only for the latest discovery."""
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            if generation != self._discovery_generations.get(provider_id):
                return
            provider = await run_sync_io(self.get_provider, provider_id)
            if provider is not None:
                provider.models_syncing = False

    # pylint: disable=too-many-branches,too-many-return-statements
    async def _save_discovery_snapshot(
        self,
        provider_id: str,
        expected_provider: Provider,
        *,
        revision: int,
        generation: int | None,
        fetched: List[ModelInfo] | None = None,
        models: List[ModelInfo] | None = None,
        synced_at: str | None = None,
        error: str | None = None,
    ) -> bool:
        """Persist discovery data before committing canonical state."""
        if generation != self._discovery_generations.get(provider_id):
            return False
        if not self._is_current_provider(
            provider_id,
            expected_provider,
            revision,
        ):
            return False
        provider = await run_sync_io(self.get_provider, provider_id)
        if provider is None:
            return False
        candidate = provider.configuration_snapshot()
        if error is None:
            apply_discovery_metadata(candidate, fetched or [], synced_at or "")
            by_id = {model.id: model for model in models or []}
            for configured in candidate.models + candidate.extra_models:
                remote = by_id.get(configured.id)
                if remote is not None:
                    configured.remote_missing = remote.remote_missing
                    configured.requires_paid_confirmation = (
                        remote.requires_paid_confirmation
                    )
            candidate.discovered_models = [
                model.model_copy(deep=True) for model in models or []
            ]
            candidate.models_last_synced_at = synced_at
            candidate.models_last_sync_error = None
        else:
            candidate.models_last_sync_error = error
        candidate.models_syncing = False
        if provider_id in self.plugin_providers:
            persisted = self._merge_plugin_snapshot(
                provider_id,
                candidate,
                "discovery",
                model_id=None,
                fields=None,
            )
        else:
            persisted = self._merge_provider_snapshot(
                provider_id,
                candidate,
                "discovery",
                model_id=None,
                fields=None,
            )
        provider_path = await self._provider_config_path_async(provider_id)
        await run_sync_io(
            self._save_provider_snapshot_locked,
            provider_id,
            persisted,
            provider_path,
        )
        if generation != self._discovery_generations.get(provider_id) or not (
            self._is_current_provider(
                provider_id,
                expected_provider,
                revision,
            )
        ):
            await self._restore_latest_snapshot(provider_id, provider_path)
            return False
        await self._commit_provider_snapshot(provider_id, persisted)
        return True

    # This orchestration method intentionally keeps fetch, normalization,
    # catalog merge, persistence, and fallback handling in one transaction.
    # pylint: disable=too-many-branches,too-many-statements
    async def discover_provider_models(
        self,
        provider_id: str,
        *,
        save: bool = True,
        timeout: float = 10,
        provider_override: Provider | None = None,
        prepared_discovery: tuple[Provider, int, int] | None = None,
    ) -> ProviderModelDiscoveryResult:
        """Discover, normalize and optionally persist a provider's models.

        A failed refresh never mutates the last successful cache or the
        user-added model list.
        """
        provider_id = self._normalize_provider_id(provider_id)
        provider = await run_sync_io(self.get_provider, provider_id)
        if provider is None:
            return ProviderModelDiscoveryResult(
                success=False,
                used_static_fallback=True,
                error=f"Provider '{provider_id}' not found",
                error_kind="configuration",
            )
        if (
            provider_id not in self.plugin_providers
            and not provider.support_model_discovery
            and provider.discovery_strategy
            in {f"catalog_only", f"unsupported"}
        ):
            return ProviderModelDiscoveryResult(
                success=False,
                models=await run_sync_io(provider.discovery_candidates),
                used_static_fallback=True,
                error=provider.discovery_support_reason,
                error_kind=f"unsupported",
            )
        generation = None
        if save:
            if prepared_discovery is None:
                prepared_discovery = (
                    await self.prepare_provider_model_discovery(
                        provider_id,
                    )
                )
            if prepared_discovery is None:
                return ProviderModelDiscoveryResult(
                    success=False,
                    models=await run_sync_io(provider.discovery_candidates),
                    last_synced_at=provider.models_last_synced_at,
                    used_static_fallback=True,
                    error="Model discovery is already in progress",
                    error_kind="configuration",
                )
            provider, revision, generation = prepared_discovery
        else:
            revision = self._provider_revision(provider_id)
        fetch_provider = provider_override or provider

        try:
            if save and not self._is_current_provider(
                provider_id,
                provider,
                revision,
            ):
                return ProviderModelDiscoveryResult(
                    success=False,
                    models=await run_sync_io(provider.discovery_candidates),
                    last_synced_at=provider.models_last_synced_at,
                    used_static_fallback=True,
                    error="Model discovery was superseded by a newer update",
                    error_kind="configuration",
                )
            previous_api_ids = {
                model.id
                for model in provider.discovered_models
                if model.discovery_origin in {None, "api", "both"}
            }
            removed_ids = set(provider.removed_model_ids)
            fetched = await fetch_provider.fetch_models(timeout=timeout)
            fetched = [model for model in fetched if model.id.strip()]
            if not fetched:
                raise ValueError(f"Provider returned no models")
            fetched = [
                model
                for model in fetched
                if model.id.strip() not in removed_ids
            ]

            synced_at = datetime.now(timezone.utc).isoformat()
            models, api_ids = await run_sync_io(
                normalize_discovered_models, provider, fetched, synced_at
            )

            if save:
                committed = await self._save_discovery_locked(
                    provider_id,
                    provider,
                    revision=revision,
                    generation=generation,
                    fetched=fetched,
                    models=models,
                    synced_at=synced_at,
                )
                if not committed:
                    return ProviderModelDiscoveryResult(
                        success=False,
                        models=await run_sync_io(
                            provider.discovery_candidates
                        ),
                        last_synced_at=provider.models_last_synced_at,
                        used_static_fallback=True,
                        error=(
                            "Model discovery was superseded by a newer update"
                        ),
                        error_kind="configuration",
                    )
            current_removed = set(provider.removed_model_ids)
            models = [
                model for model in models if model.id not in current_removed
            ]

            return ProviderModelDiscoveryResult(
                success=True,
                models=await run_sync_io(
                    lambda: [
                        fetch_provider.model_capabilities(m) for m in models
                    ]
                ),
                discovered_count=sum(
                    model_id not in previous_api_ids for model_id in api_ids
                ),
                last_synced_at=synced_at,
            )
        except Exception as exc:
            error = Provider.sanitize_connection_message(
                str(exc) or exc.__class__.__name__,
            )
            logger.warning("Model discovery failed; using static fallback")
            if save:
                committed = await self._save_discovery_locked(
                    provider_id,
                    provider,
                    revision=revision,
                    generation=generation,
                    error=error,
                )
                if not committed:
                    return ProviderModelDiscoveryResult(
                        success=False,
                        models=await run_sync_io(
                            provider.discovery_candidates
                        ),
                        last_synced_at=provider.models_last_synced_at,
                        used_static_fallback=True,
                        error=(
                            "Model discovery was superseded by a newer update"
                        ),
                        error_kind="configuration",
                    )
            return ProviderModelDiscoveryResult(
                success=False,
                models=await run_sync_io(provider.discovery_candidates),
                last_synced_at=provider.models_last_synced_at,
                used_static_fallback=True,
                error=error,
                error_kind=classify_discovery_error(exc, error),
            )
        finally:
            if save:
                await self._clear_discovery_syncing(provider_id, generation)

    # pylint: enable=too-many-branches,too-many-statements

    @classmethod
    def _classify_model_check(
        cls,
        success: bool,
        message: str,
        *,
        http_status: int | None = None,
        error_kind: str | None = None,
        verification: Literal[
            "live",
            "provider_only",
            "catalog",
            "unverified",
        ] = "unverified",
    ) -> ProviderModelCheckResult:
        """Compatibility wrapper for availability classification."""
        return classify_model_check(
            success,
            message,
            http_status=http_status,
            error_kind=error_kind,
            verification=verification,
        )

    async def check_provider_model(
        self,
        provider_id: str,
        model_id: str,
        timeout: float = 5,
    ) -> ProviderModelCheckResult:
        """Check a model and cache its structured availability result."""
        provider_id = self._normalize_provider_id(provider_id)
        provider = await run_sync_io(self.get_provider, provider_id)
        if provider is None:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        revision = self._provider_revision(provider_id)

        raw_result = await provider.check_model_connection(
            model_id=model_id,
            timeout=timeout,
        )
        if isinstance(raw_result, ModelConnectionResult):
            result = self._classify_model_check(
                raw_result.success,
                raw_result.message,
                http_status=raw_result.http_status,
                error_kind=raw_result.error_kind,
                verification=raw_result.verification,
            )
        else:
            success, message = raw_result
            result = self._classify_model_check(success, message)

        if not self._is_current_provider(provider_id, provider, revision):
            return result

        normalized_id = model_id.strip()
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            if not self._is_current_provider(provider_id, provider, revision):
                return result
            candidate = provider.configuration_snapshot()
            if (
                candidate.get_model_info(normalized_id) is None
                and candidate.get_discovered_model_info(normalized_id) is None
            ):
                pool = await run_sync_io(candidate.discovery_candidates)
                card = next((m for m in pool if m.id == normalized_id), None)
                if card is not None:
                    candidate.discovered_models.append(
                        card.model_copy(deep=True)
                    )
            changed = False
            for collection in (
                candidate.models,
                candidate.extra_models,
                candidate.discovered_models,
            ):
                for model in collection:
                    if model.id.strip() != normalized_id:
                        continue
                    model.availability_status = result.status
                    model.availability_message = result.message or None
                    model.availability_http_status = result.http_status
                    model.availability_retryable = result.retryable
                    model.availability_checked_at = result.checked_at
                    model.availability_verification = result.verification
                    changed = True
            if changed:
                await self._save_provider_config_locked(
                    provider_id,
                    candidate,
                    update_kind="availability",
                    model_id=normalized_id,
                    fields=None,
                )

        return result

    def startup_sync_provider_ids(self) -> list[str]:
        """Return providers eligible for non-blocking startup discovery."""
        provider_ids: list[str] = []
        for provider in (
            *self.builtin_providers.values(),
            *self.custom_providers.values(),
        ):
            if (
                provider.model_sync_mode != "startup"
                or not provider.support_model_discovery
                or not sync_due(provider)
            ):
                continue
            if provider.discovery_requires_auth and not provider.api_key:
                continue
            provider_ids.append(provider.id)
        return provider_ids

    async def sync_startup_provider_models(
        self,
        provider_ids: list[str] | None = None,
    ) -> None:
        """Refresh startup-enabled provider catalogs without failing boot."""
        if provider_ids is None:
            provider_ids = self.startup_sync_provider_ids()
        if not provider_ids:
            return

        semaphore = asyncio.Semaphore(3)

        async def sync_one(provider_id: str):
            async with semaphore:
                return await self.discover_provider_models(provider_id)

        results = await asyncio.gather(
            *(sync_one(provider_id) for provider_id in provider_ids),
            return_exceptions=True,
        )
        for provider_id, result in zip(provider_ids, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Startup model sync failed for %s: %s",
                    sanitize_log_value(provider_id),
                    sanitize_log_value(str(result)),
                )

    async def sync_remote_catalogs(self) -> None:
        """Update configured OTA catalogs without blocking startup."""
        updates: list[tuple[str, Callable[[], Any]]] = []
        if EnvVarLoader.get_bool(model_catalog.METADATA_ENABLED_ENV, False):
            updates.append(
                (f"metadata", model_catalog.update_model_metadata),
            )
        if EnvVarLoader.get_str(model_catalog.CATALOG_URL_ENV):
            updates.append(
                ("model", model_catalog.update_model_catalog),
            )
        if EnvVarLoader.get_str(CAPABILITY_URL_ENV):
            updates.append(
                (
                    "capability",
                    capability_baseline.update_capability_catalog,
                ),
            )
        for label, update in updates:
            try:
                await asyncio.to_thread(update)
                if label == "model":
                    catalog = await asyncio.to_thread(
                        model_catalog.load_model_catalog,
                    )
                    await self._refresh_builtin_catalog(catalog)
                elif label == f"capability":
                    await asyncio.to_thread(
                        self._capability_registry.reload,
                    )
                    self._apply_default_annotations(refresh=True)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to update %s catalog: %s",
                    label,
                    exc,
                )

    async def _refresh_builtin_catalog(
        self,
        catalog: dict[str, list[ModelInfo]],
    ) -> None:
        """Apply a validated model catalog without replacing user state."""
        for provider_id, catalog_key in BUILTIN_PROVIDER_CATALOG_KEYS.items():
            provider = self.builtin_providers.get(provider_id)
            if provider is None or catalog_key not in catalog:
                continue
            lock = self._provider_save_locks.setdefault(
                provider_id,
                asyncio.Lock(),
            )
            async with lock:
                provider.models = self._merge_catalog_models(
                    provider.models,
                    catalog[catalog_key],
                )
                self._bump_provider_revision(provider_id)
        self._apply_default_annotations()

    @staticmethod
    def _merge_catalog_models(
        current_models: list[ModelInfo],
        catalog_models: list[ModelInfo],
    ) -> list[ModelInfo]:
        """Merge catalog metadata while retaining runtime model state."""
        ordered_ids = [model.id for model in current_models]
        by_id = {model.id: model for model in current_models}
        for catalog_model in catalog_models:
            current = by_id.get(catalog_model.id)
            if current is None:
                model = catalog_model.model_copy(deep=True)
                model.source = "builtin"
                ordered_ids.append(model.id)
                by_id[model.id] = model
                continue

            payload = current.model_dump()
            overrides = set(current.config_overrides)
            user_output_capability = current.max_output_length_source == "user"
            for field in catalog_model.model_fields_set:
                if field in overrides:
                    continue
                if (
                    field.startswith("max_output_length")
                    and user_output_capability
                ):
                    continue
                if current.max_input_length_configured and field in {
                    "max_input_length",
                    "max_input_length_configured",
                }:
                    continue
                payload[field] = getattr(catalog_model, field)
            merged = ModelInfo.model_validate(payload)
            merged.source = "builtin"
            by_id[merged.id] = merged
        return [by_id[model_id] for model_id in ordered_ids]
