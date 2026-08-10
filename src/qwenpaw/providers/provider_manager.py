# -*- coding: utf-8 -*-
"""A Manager class to handle all providers, including built-in and custom ones.
It provides a unified interface to manage providers, such as listing available
providers, adding/removing custom providers, and fetching provider details."""
# pylint: disable=unused-import

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Literal

from agentscope.model import ChatModelBase

from qwenpaw.exceptions import ModelNotFoundException

from ..config.config import ModelSlotConfig
from ..constant import EnvVarLoader, SECRET_DIR
from ..exceptions import ProviderError
from ..utils.io_utils import (
    get_sync_path_lock,
    run_async_to_completion,
    run_sync_io,
)
from .provider import (
    ModelConnectionResult,
    ModelInfo,
    Provider,
    ProviderInfo,
    validate_custom_provider_id,
)
from . import provider_catalog as _provider_catalog
from . import model_catalog
from .capability_baseline import (
    CAPABILITY_URL_ENV,
    ExpectedCapabilityRegistry,
    update_capability_catalog,
)
from .provider_catalog import (
    BUILTIN_PROVIDERS,
    BUILTIN_PROVIDER_CATALOG_KEYS,
)
from .provider_manager_discovery import ProviderManagerDiscoveryMixin
from .provider_manager_persistence import (
    ProviderManagerPersistenceMixin,
)
from .plugin_provider_registry import PluginProviderRegistry
from .provider_annotations import ProviderAnnotationService

logger = logging.getLogger(__name__)

PluginUpdateKind = Literal[
    "replace",
    "config",
    "discovery",
    "availability",
    "configured_add",
    "configured_delete",
    "configured_update",
    "capability",
]
_AVAILABILITY_MODEL_FIELDS = (
    "availability_status",
    "availability_message",
    "availability_http_status",
    "availability_retryable",
    "availability_checked_at",
    "availability_verification",
)
_CAPABILITY_MODEL_FIELDS = (
    "supports_image",
    "supports_video",
    "supports_multimodal",
    "probe_source",
)
_CONNECTION_CONFIG_FIELDS = {
    "api_key",
    "base_url",
    "auth_mode",
    "custom_headers",
    "chat_model",
    "api_key_prefix",
    "api_key_prefixes",
}


# Preserve the catalog constants historically exported by this module.
for _catalog_name in _provider_catalog.__all__:
    globals()[_catalog_name] = getattr(_provider_catalog, _catalog_name)

# Keep static analyzers and existing public imports compatible with the
# historical provider_manager module surface.
KIMI_CODINGPLAN_MODELS = _provider_catalog.KIMI_CODINGPLAN_MODELS
KIMI_MODELS = _provider_catalog.KIMI_MODELS
MIMO_TOKENPLAN_MODELS = _provider_catalog.MIMO_TOKENPLAN_MODELS
OPENCODE_MODELS = _provider_catalog.OPENCODE_MODELS
PROVIDER_KIMI_CN = _provider_catalog.PROVIDER_KIMI_CN
PROVIDER_KIMI_CODINGPLAN = _provider_catalog.PROVIDER_KIMI_CODINGPLAN
PROVIDER_KIMI_INTL = _provider_catalog.PROVIDER_KIMI_INTL
PROVIDER_MIMO_TOKENPLAN = _provider_catalog.PROVIDER_MIMO_TOKENPLAN
PROVIDER_OPENCODE = _provider_catalog.PROVIDER_OPENCODE
PROVIDER_SILICONFLOW_CN = _provider_catalog.PROVIDER_SILICONFLOW_CN
PROVIDER_SILICONFLOW_INTL = _provider_catalog.PROVIDER_SILICONFLOW_INTL
PROVIDER_VOLCENGINE_CN = _provider_catalog.PROVIDER_VOLCENGINE_CN
PROVIDER_VOLCENGINE_CN_CODINGPLAN = (
    _provider_catalog.PROVIDER_VOLCENGINE_CN_CODINGPLAN
)
VOLCENGINE_CODINGPLAN_MODELS = _provider_catalog.VOLCENGINE_CODINGPLAN_MODELS
VOLCENGINE_MODELS = _provider_catalog.VOLCENGINE_MODELS


class ProviderManager(
    ProviderManagerDiscoveryMixin,
    ProviderManagerPersistenceMixin,
):  # pylint: disable=too-many-public-methods
    """A manager class to handle all providers,
    including built-in and custom ones."""

    _instance = None

    def __init__(self) -> None:
        # Initialize provider manager, load providers from registry and store
        # any necessary state (e.g., cached models).
        self.builtin_providers: Dict[str, Provider] = {}
        self.custom_providers: Dict[str, Provider] = {}
        self.plugin_providers: Dict[str, Dict] = {}  # Plugin providers
        self.active_model: ModelSlotConfig | None = None
        self._provider_save_locks: dict[str, asyncio.Lock] = {}
        self._discovery_generations: dict[str, int] = {}
        self._provider_revisions: dict[str, int] = {}
        self.root_path = SECRET_DIR / "providers"
        self.builtin_path = self.root_path / "builtin"
        self.custom_path = self.root_path / "custom"
        self.plugin_path = self.root_path / "plugin"  # Plugin provider configs
        self._plugin_registry = PluginProviderRegistry(self)
        self._prepare_disk_storage()
        self._init_builtins()
        try:
            self._migrate_legacy_providers()
        except Exception as e:
            logger.warning("Failed to migrate legacy providers: %s", e)
        self._init_from_storage()
        self._capability_registry = ExpectedCapabilityRegistry()
        self._annotation_service = ProviderAnnotationService(
            self._capability_registry,
        )
        self._apply_default_annotations()

    def _prepare_disk_storage(self):
        """Prepare directory structure"""
        for path in [
            self.root_path,
            self.builtin_path,
            self.custom_path,
            self.plugin_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o700)  # Restrict permissions for security
            except Exception:
                pass

    def _init_builtins(self):
        """Register the ordered built-in provider catalog."""
        catalog = model_catalog.load_model_catalog()
        for provider in BUILTIN_PROVIDERS:
            builtin = provider.model_copy(deep=True)
            catalog_key = BUILTIN_PROVIDER_CATALOG_KEYS.get(provider.id)
            if catalog_key is not None:
                builtin.models = [
                    model.model_copy(deep=True)
                    for model in catalog.get(catalog_key, builtin.models)
                ]
            self._add_builtin(builtin)

    def _add_builtin(self, provider: Provider):
        # Built-in definitions may reuse model lists across regional variants.
        # Each manager instance needs independent model objects for persisted
        # overrides and discovery metadata.
        self.builtin_providers[provider.id] = provider.model_copy(deep=True)

    async def list_provider_info(self) -> List[ProviderInfo]:
        tasks = [
            provider.get_info() for provider in self.builtin_providers.values()
        ]
        tasks += [
            provider.get_info() for provider in self.custom_providers.values()
        ]
        tasks += [
            self._get_plugin_provider_info(provider_info)
            for provider_info in self._plugin_registry.list_provider_infos()
        ]

        provider_infos = await asyncio.gather(*tasks)
        return list(provider_infos)

    async def _get_plugin_provider_info(
        self,
        provider_info: ProviderInfo,
    ) -> ProviderInfo:
        """Helper to return plugin provider info as async task."""
        return provider_info

    @staticmethod
    def _normalize_provider_id(provider_id: str) -> str:
        """Normalize provider ID for backward compatibility.

        Maps legacy 'copaw-local' to 'qwenpaw-local'.
        """
        if provider_id == "copaw-local":
            return "qwenpaw-local"
        return provider_id

    def get_provider(self, provider_id: str) -> Provider | None:
        # Return a provider instance by its ID. This will be used to create
        # chat model instances for the agent.
        # Normalize provider ID for backward compatibility
        provider_id = self._normalize_provider_id(provider_id)
        plugin_provider = self._plugin_registry.get_provider(provider_id)
        if plugin_provider is not None:
            return plugin_provider
        if provider_id in self.builtin_providers:
            return self.builtin_providers[provider_id]
        if provider_id in self.custom_providers:
            return self.custom_providers[provider_id]
        return None

    async def get_provider_info(self, provider_id: str) -> ProviderInfo | None:
        provider = self.get_provider(provider_id)
        return await provider.get_info() if provider else None

    def get_active_model(self) -> ModelSlotConfig | None:
        # Return the currently active provider/model configuration.
        return self.active_model

    def update_provider(self, provider_id: str, config: Dict) -> bool:
        # Update the configuration of a provider (e.g., base URL, API key).
        # This will be called when the user edits a provider's settings in the
        # UI. It should update the in-memory provider instance and persist the
        # changes to providers.json.
        # Normalize provider ID for backward compatibility
        provider_id = self._normalize_provider_id(provider_id)
        return self._update_provider_transaction(provider_id, config)

    async def update_provider_async(
        self,
        provider_id: str,
        config: Dict,
    ) -> bool:
        """Update a provider and persist its snapshot off the event loop."""
        provider_id = self._normalize_provider_id(provider_id)
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            return await run_async_to_completion(
                self._update_provider_async_locked(provider_id, config),
            )

    async def _update_provider_async_locked(
        self,
        provider_id: str,
        config: Dict,
    ) -> bool:
        """Persist a detached update snapshot, then commit it in memory."""
        provider = self.get_provider(provider_id)
        if provider is None:
            return False
        revision = self._provider_revision(provider_id)
        candidate = provider.model_copy(deep=True)
        before_update = candidate.model_dump()
        candidate.update_config(config)
        changed_fields = {
            field
            for field in config
            if field in candidate.__class__.model_fields
            and before_update.get(field) != getattr(candidate, field)
        }
        if _CONNECTION_CONFIG_FIELDS.intersection(changed_fields):
            self._reset_model_availability(candidate)
            candidate.models_syncing = False

        provider_path = self._provider_config_path(provider_id)
        await run_sync_io(
            self._save_provider_snapshot_locked,
            provider_id,
            candidate,
            provider_path,
        )

        if not self._is_current_provider(provider_id, provider, revision):
            return False
        current = self.get_provider(provider_id)
        if current is None:
            return False
        if provider_id in self.plugin_providers:
            self.plugin_providers[provider_id]["info"] = ProviderInfo(
                **candidate.model_dump(),
            )
        else:
            self._copy_provider_state(current, candidate)
        if changed_fields:
            self._bump_provider_revision(provider_id)
        return True

    def _update_provider_transaction(
        self,
        provider_id: str,
        config: Dict,
        *,
        expected_provider: Provider | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        """Update memory and disk under the shared provider path lock."""
        provider_path = self._provider_config_path(provider_id)
        with get_sync_path_lock(provider_path):
            provider = self.get_provider(provider_id)
            if provider is None:
                return False
            if (
                expected_revision is not None
                and not self._is_current_provider(
                    provider_id,
                    expected_provider or provider,
                    expected_revision,
                )
            ):
                return False
            self._merge_persisted_discovery_state(provider_id, provider)
            before_update = provider.model_dump()
            provider.update_config(config)
            changed_fields = {
                field
                for field in config
                if field in provider.__class__.model_fields
                and before_update.get(field) != getattr(provider, field)
            }
            if _CONNECTION_CONFIG_FIELDS.intersection(changed_fields):
                self._reset_model_availability(provider)
                provider.models_syncing = False
            if changed_fields:
                self._bump_provider_revision(provider_id)
            self._save_provider_snapshot(provider_id, provider)
            if provider_id in self.plugin_providers:
                self.plugin_providers[provider_id]["info"] = ProviderInfo(
                    **provider.model_dump(),
                )
            return True

    def _merge_persisted_discovery_state(
        self,
        provider_id: str,
        provider: Provider,
    ) -> None:
        """Keep a completed discovery snapshot during a legacy sync update."""
        if provider_id in self.plugin_providers:
            return
        persisted = self.load_provider(
            provider_id,
            is_builtin=provider_id in self.builtin_providers,
        )
        if persisted is None or persisted.models_last_synced_at is None:
            return
        provider.discovered_models = [
            model.model_copy(deep=True)
            for model in persisted.discovered_models
        ]
        provider.models_last_synced_at = persisted.models_last_synced_at
        provider.models_last_sync_error = persisted.models_last_sync_error

    def _bump_provider_revision(self, provider_id: str) -> int:
        """Advance the revision used to reject stale async operations."""
        revision = self._provider_revisions.get(provider_id, 0) + 1
        self._provider_revisions[provider_id] = revision
        return revision

    def _provider_revision(self, provider_id: str) -> int:
        """Return the current runtime revision for a provider."""
        return self._provider_revisions.get(provider_id, 0)

    def _is_current_provider(
        self,
        provider_id: str,
        provider: Provider,
        revision: int,
    ) -> bool:
        """Check that an async operation still targets the live provider."""
        if revision != self._provider_revision(provider_id):
            return False
        if provider_id in self.plugin_providers:
            return True
        return self.get_provider(provider_id) is provider

    @staticmethod
    def _reset_model_availability(provider: Provider) -> None:
        """Invalidate probe results after connection settings change."""
        for model in provider.models + provider.extra_models:
            model.availability_status = "unverified"
            model.availability_message = None
            model.availability_http_status = None
            model.availability_retryable = True
            model.availability_checked_at = None
            model.availability_verification = "unverified"
        for model in provider.discovered_models:
            model.availability_status = "unverified"
            model.availability_message = None
            model.availability_http_status = None
            model.availability_retryable = True
            model.availability_checked_at = None
            model.availability_verification = "unverified"

    def start_local_model_resume(self, local_manager) -> None:
        """Schedule background restore of the active local model server."""
        task = asyncio.create_task(
            self._resume_local_model(local_manager),
            name="qwenpaw-local-model-resume",
        )
        task.add_done_callback(self._on_local_model_resume_done)

    @staticmethod
    def _on_local_model_resume_done(task: asyncio.Task[None]) -> None:
        """Log unexpected failures from background local model restore."""
        if task.cancelled():
            return

        exc = task.exception()
        if exc is not None:
            logger.warning(
                "Background local model restore failed: %s",
                exc,
                exc_info=exc,
            )
        logger.info("Background local model restore completed")

    def _resolve_custom_provider_id(self, provider_id: str) -> str:
        """Resolve provider ID conflicts for a custom provider."""
        base_id = provider_id
        if base_id in self.builtin_providers:
            base_id = f"{base_id}-custom"

        resolved_id = base_id
        while (
            resolved_id in self.builtin_providers
            or resolved_id in self.custom_providers
            or resolved_id in self.plugin_providers
        ):
            resolved_id = f"{resolved_id}-new"

        return resolved_id

    async def add_custom_provider(self, provider_data: ProviderInfo):
        # Add a new custom provider with the given data. This will update the
        # providers.json file and make the new provider available in the UI.
        try:
            requested_id = validate_custom_provider_id(provider_data.id)
        except ValueError as exc:
            raise ProviderError(message=str(exc)) from exc
        provider_payload = provider_data.model_dump()
        # ``max_input_length`` equal to the historical 128K default is only
        # distinguishable from an omitted value while the request model still
        # carries Pydantic's field-presence information. Preserve that intent
        # before model_dump/storage erase it. This is deliberately scoped to
        # the user-facing custom-provider ingestion path: legacy provider JSON
        # serialized every default field, so applying the same inference while
        # loading from disk would incorrectly mark all old 128K defaults as
        # explicit overrides.
        for field in ("models", "extra_models"):
            source_models = getattr(provider_data, field, ())
            payload_models = provider_payload.get(field, ())
            for source, payload in zip(source_models, payload_models):
                if "max_input_length" in source.model_fields_set:
                    payload["max_input_length_configured"] = True
        provider_payload["id"] = self._resolve_custom_provider_id(
            requested_id,
        )
        provider_payload["is_custom"] = True
        provider = self._provider_from_data(
            provider_payload,
        )  # Validate provider data
        provider.support_model_discovery = provider.chat_model in {
            "OpenAIChatModel",
            "OpenAIResponseModel",
            "AnthropicChatModel",
            "GeminiChatModel",
        }
        # For custom providers, we assume they don't support connection check
        # without model config, to avoid false negatives in the UI.
        provider.support_connection_check = False
        await self.save_provider_config_async(provider.id, provider)
        self.custom_providers[provider.id] = provider
        self._bump_provider_revision(provider.id)
        return await provider.get_info()

    def remove_custom_provider(self, provider_id: str) -> bool:
        # Remove a custom provider by its ID. This will update the
        # providers.json file and remove the provider from the UI.
        if provider_id in self.custom_providers:
            self._bump_provider_revision(provider_id)
            del self.custom_providers[provider_id]
            provider_path = self._provider_config_path(provider_id)
            if provider_path.exists():
                os.remove(provider_path)
            return True
        return False

    async def remove_custom_provider_async(self, provider_id: str) -> bool:
        """Remove a custom provider without blocking the event loop."""
        provider_id = self._normalize_provider_id(provider_id)
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )

        async def remove_provider() -> bool:
            async with lock:
                if provider_id not in self.custom_providers:
                    return False
                provider_path = self._provider_config_path(provider_id)
                await run_sync_io(provider_path.unlink, missing_ok=True)
                self._bump_provider_revision(provider_id)
                del self.custom_providers[provider_id]
                return True

        return await run_async_to_completion(remove_provider())

    async def activate_model(self, provider_id: str, model_id: str):
        # Set the active provider and model for the agent. This will update
        # providers.json and determine which provider/model is used when the
        # agent creates chat model instances.
        # Normalize provider ID for backward compatibility
        provider_id = self._normalize_provider_id(provider_id)
        provider = self.get_provider(provider_id)
        if not provider:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        if not provider.has_model(model_id):
            raise ModelNotFoundException(
                model_name=f"{provider_id}/{model_id}",
                details={"provider_id": provider_id, "model_id": model_id},
            )
        model_info = provider.get_model_info(model_id)
        if model_info and model_info.availability_status in {
            "permission_denied",
            "model_not_found",
            "incompatible_api",
        }:
            reason = (
                model_info.availability_message
                or model_info.availability_status
            )
            raise ProviderError(
                message=(
                    f"Model '{model_id}' cannot be activated: " f"{reason}"
                ),
            )
        active_model = ModelSlotConfig(
            provider_id=provider_id,
            model=model_id,
        )
        await self.save_active_model_async(active_model)
        self.active_model = active_model

        # Drop a stale ``rejects_media`` entry for this model so that a
        # transient upstream failure (e.g. a gateway misroute) does not
        # keep stripping images after re-selection.  Other capabilities
        # and other models are left untouched.
        from .model_capability_cache import get_capability_cache

        get_capability_cache().forget(
            f"{provider_id}:{model_id}",
            "rejects_media",
        )

        self.maybe_probe_multimodal(provider_id, model_id)

    def maybe_probe_multimodal(self, provider_id: str, model_id: str) -> None:
        """Schedule multimodal probing for a model if capability is unknown."""
        provider = self.get_provider(provider_id)
        # Auto-probe multimodal if not yet probed
        for model in provider.all_models():
            if model.id == model_id and model.supports_multimodal is None:
                asyncio.create_task(
                    self._auto_probe_multimodal(provider_id, model_id),
                )
                break

    async def _auto_probe_multimodal(
        self,
        provider_id: str,
        model_id: str,
    ) -> None:
        """Background probe that doesn't block model activation."""
        try:
            result = await self.probe_model_multimodal(provider_id, model_id)
            logger.info(
                "Auto-probe for %s/%s: image=%s, video=%s",
                provider_id,
                model_id,
                result.get("supports_image"),
                result.get("supports_video"),
            )
            # Heal a poisoned ``rejects_media`` cache entry: if the
            # probe actually saw the image, force ``rejects_media`` to
            # False so subsequent ``_reasoning`` calls stop stripping
            # media.  Without this, a stale entry written from an
            # unrelated 400 (request too large, malformed block fields)
            # would silently drop every future image.
            if result.get("supports_image"):
                from .model_capability_cache import get_capability_cache

                get_capability_cache().learn(
                    f"{provider_id}:{model_id}",
                    "rejects_media",
                    False,
                )
        except Exception as e:
            logger.warning("Auto-probe multimodal failed: %s", e)

    async def add_model_to_provider(
        self,
        provider_id: str,
        model_info: ModelInfo,
    ) -> ProviderInfo:
        provider_id = self._normalize_provider_id(provider_id)
        provider = self.get_provider(provider_id)
        if not provider:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        discovered = next(
            (
                model
                for model in provider.discovered_models
                if model.id.strip() == model_info.id.strip()
            ),
            None,
        )
        if discovered is not None:
            if discovered.availability_status in {
                "permission_denied",
                "model_not_found",
                "incompatible_api",
            }:
                reason = (
                    discovered.availability_message
                    or discovered.availability_status
                )
                raise ProviderError(
                    message=(
                        f"Model '{model_info.id}' cannot be added: "
                        f"{reason}"
                    ),
                )
            # Preserve API-reported metadata when a catalog candidate becomes
            # an explicitly configured model.
            payload = discovered.model_dump()
            payload.update(
                {
                    "id": model_info.id,
                    "name": model_info.name or discovered.name,
                    "source": "user",
                },
            )
            for field in model_info.model_fields_set:
                payload[field] = getattr(model_info, field)
            model_info = ModelInfo.model_validate(payload)

        added, error_message = await provider.add_model(model_info)
        if not added:
            raise ProviderError(
                message=error_message,
                details={
                    "provider_id": provider_id,
                    "model_id": model_info.id,
                },
            )

        self._bump_provider_revision(provider_id)
        await self.save_provider_config_async(
            provider_id,
            provider,
            update_kind="configured_add",
            model_id=model_info.id.strip(),
        )
        return await provider.get_info()

    async def set_model_hidden(
        self,
        provider_id: str,
        model_id: str,
        *,
        hidden: bool,
    ) -> ProviderInfo:
        """Persist whether one discovery candidate is hidden from the UI."""
        provider_id = self._normalize_provider_id(provider_id)
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        model_id = model_id.strip()
        if not model_id:
            raise ProviderError(message="Model ID cannot be empty.")
        hidden_ids = set(provider.hidden_model_ids)
        if hidden:
            hidden_ids.add(model_id)
        else:
            hidden_ids.discard(model_id)
        provider.hidden_model_ids = sorted(hidden_ids)
        await self.save_provider_config_async(
            provider_id,
            provider,
            update_kind="config",
            model_id=None,
            fields={"hidden_model_ids"},
        )
        return await provider.get_info()

    async def update_model_config(
        self,
        provider_id: str,
        model_id: str,
        config: Dict,
    ) -> ProviderInfo:
        """Update per-model configuration and persist to disk."""
        provider_id = self._normalize_provider_id(provider_id)
        provider = self.get_provider(provider_id)
        if not provider:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        if not provider.update_model_config(model_id, config):
            raise ModelNotFoundException(
                model_name=f"{provider_id}/{model_id}",
                details={"provider_id": provider_id, "model_id": model_id},
            )

        await self.save_provider_config_async(
            provider_id,
            provider,
            update_kind="configured_update",
            model_id=model_id.strip(),
            fields=set(config),
        )
        return await provider.get_info()

    async def delete_model_from_provider(
        self,
        provider_id: str,
        model_id: str,
    ) -> ProviderInfo:
        provider_id = self._normalize_provider_id(provider_id)
        provider = self.get_provider(provider_id)
        if not provider:
            raise ProviderError(
                message=f"Provider '{provider_id}' not found.",
            )
        await provider.delete_model(model_id=model_id)

        self._bump_provider_revision(provider_id)
        await self.save_provider_config_async(
            provider_id,
            provider,
            update_kind="configured_delete",
            model_id=model_id.strip(),
        )
        return await provider.get_info()

    async def probe_model_multimodal(
        self,
        provider_id: str,
        model_id: str,
        image_only: bool = False,
    ) -> dict:
        """Probe a model's multimodal capabilities and persist the result.

        Args:
            provider_id: Provider identifier.
            model_id: Model identifier.
            image_only: When True, skip the video probe for a faster result.
                Only ``supports_image`` will be accurate; ``supports_video``
                will remain at its previous value (not updated).
        """
        provider_id = self._normalize_provider_id(provider_id)
        provider = self.get_provider(provider_id)
        if not provider:
            return {"error": f"Provider '{provider_id}' not found"}

        result = await provider.probe_model_multimodal(
            model_id,
            image_only=image_only,
        )

        # Update the model's capability flags.
        # For image_only probes, leave supports_video untouched so a
        # subsequent full probe can fill it in correctly.
        for model in provider.all_models():
            if model.id == model_id:
                model.supports_image = result.supports_image
                if not image_only:
                    model.supports_video = result.supports_video
                    model.supports_multimodal = result.supports_multimodal
                else:
                    # Partial update: derive supports_multimodal from
                    # image alone; video will be updated by the full probe.
                    if result.supports_image:
                        model.supports_multimodal = True
                model.probe_source = getattr(
                    result,
                    "probe_source",
                    "probed",
                )
                break

        # Compare probe result against expected baseline
        from .capability_baseline import compare_probe_result

        registry = ExpectedCapabilityRegistry()
        expected = registry.get_expected(provider_id, model_id)
        if expected:
            discrepancies = compare_probe_result(
                expected,
                result.supports_image,
                result.supports_video,
            )
            for d in discrepancies:
                logger.warning(
                    "Probe discrepancy: %s/%s %s expected=%s actual=%s (%s)",
                    d.provider_id,
                    d.model_id,
                    d.field,
                    d.expected,
                    d.actual,
                    d.discrepancy_type,
                )

        await self.save_provider_config_async(
            provider_id,
            provider,
            update_kind="capability",
            model_id=model_id.strip(),
        )
        return {
            "supports_image": result.supports_image,
            "supports_video": result.supports_video,
            "supports_multimodal": result.supports_multimodal,
            "image_message": result.image_message,
            "video_message": result.video_message,
        }

    def _apply_default_annotations(self, *, refresh: bool = False) -> None:
        """Apply doc-based default annotations for unprobed models."""
        self._annotation_service = ProviderAnnotationService(
            self._capability_registry,
        )
        self._annotation_service.apply(
            self.builtin_providers.values(),
            refresh=refresh,
        )

    async def _resume_local_model(self, local_manager) -> None:
        """Resume the active local model server from the previous run."""

        async def _clear_local_provider() -> None:
            await self.update_provider_async(
                "qwenpaw-local",
                {
                    "base_url": "",
                    "extra_models": [],
                },
            )

        local_models = self.get_provider("qwenpaw-local").extra_models
        model_id = local_models[0].id if local_models else None
        if model_id is None:
            return

        installed, _ = local_manager.check_llamacpp_installation()
        if not installed:
            logger.info(
                "Skipping local model restore because"
                " llama.cpp is not installed.",
            )
            await _clear_local_provider()
            return

        if not local_manager.is_model_downloaded(model_id):
            logger.warning(
                "Skipping local model restore because"
                " model is not downloaded: %s",
                model_id,
            )
            await _clear_local_provider()
            return

        try:
            setup_result = await local_manager.setup_server(model_id)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            logger.warning(
                "Failed to restore local model server for %s: %s",
                model_id,
                exc,
            )
            await _clear_local_provider()
            return

        await self.update_provider_async(
            "qwenpaw-local",
            {
                "base_url": f"http://127.0.0.1:{setup_result.port}/v1",
                "extra_models": [setup_result.model_info],
            },
        )

    def register_plugin_provider(
        self,
        provider_id: str,
        provider_class,
        label: str,
        base_url: str,
        metadata: Dict,
    ):
        """Register a plugin provider.

        Args:
            provider_id: Provider ID
            provider_class: Provider class
            label: Display label
            base_url: API base URL
            metadata: Additional metadata
        """
        self._plugin_registry.register(
            provider_id,
            provider_class,
            label,
            base_url,
            metadata,
        )

    def unregister_plugin_provider(self, provider_id: str) -> bool:
        """Remove a plugin provider from memory.

        Removes the provider from ``self.plugin_providers`` so it no
        longer appears in the model list.  The persisted configuration
        file (``plugin_path/{provider_id}.json``) is intentionally
        kept on disk so that user-configured keys survive a
        reinstall.

        Args:
            provider_id: Plugin provider identifier to remove.

        Returns:
            ``True`` if the provider was found and removed,
            ``False`` if it was not registered.
        """
        return self._plugin_registry.unregister(provider_id)

    @staticmethod
    def get_instance() -> "ProviderManager":
        """Get the singleton instance of ProviderManager."""
        if ProviderManager._instance is None:
            ProviderManager._instance = ProviderManager()
        return ProviderManager._instance

    @staticmethod
    def get_active_chat_model() -> ChatModelBase:
        """Get the currently active provider/model configuration."""
        manager = ProviderManager.get_instance()
        model = manager.get_active_model()
        if model is None or model.provider_id == "" or model.model == "":
            raise ProviderError(
                message="No active model configured.",
            )
        provider = manager.get_provider(model.provider_id)
        if provider is None:
            raise ProviderError(
                message=f"Active provider '{model.provider_id}' not found.",
            )
        return provider.get_chat_model_instance(model.model)
