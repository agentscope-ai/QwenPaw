# -*- coding: utf-8 -*-
"""Persistence and migration operations for ProviderManager."""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Literal

from ..config.config import ModelSlotConfig
from ..exceptions import ProviderError
from ..security.secret_store import (
    PROVIDER_SECRET_FIELDS,
    decrypt_dict_fields,
    is_encrypted,
)
from ..utils.io_utils import (
    get_sync_path_lock,
    run_async_to_completion,
    run_sync_io,
)
from .anthropic_provider import AnthropicProvider
from .dashscope_provider import DashScopeProvider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from .openai_response_provider import OpenAIResponseProvider
from .openrouter_provider import OpenRouterProvider
from .provider import ModelInfo, Provider, ProviderInfo
from .provider_discovery import (
    DISCOVERY_MODEL_FIELDS as _DISCOVERY_MODEL_FIELDS,
)
from .provider_model_state import (
    restore_model_state,
    serialize_model_state,
)
from .provider_persistence import (
    replace_with_retry,
    write_provider_snapshot,
)

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


class ProviderManagerPersistenceMixin:
    """Provide provider snapshot persistence and migration operations."""

    active_model: ModelSlotConfig | None

    def _save_provider(
        self,
        provider: Provider,
        is_builtin: bool = False,
        skip_if_exists: bool = False,
    ):
        """Save a provider configuration to disk.

        Sensitive fields (``api_key``) are encrypted before writing.
        """
        provider_dir = self.builtin_path if is_builtin else self.custom_path
        provider_path = self._safe_provider_path(provider_dir, provider.id)
        with get_sync_path_lock(provider_path):
            if skip_if_exists and provider_path.exists():
                return
            self._save_provider_snapshot(
                provider.id,
                provider,
                provider_path=provider_path,
            )

    def _save_plugin_provider(self, provider: Provider):
        """Save a plugin provider configuration to disk.

        Sensitive fields (``api_key``) are encrypted before writing.
        """
        provider_path = self.plugin_path / f"{provider.id}.json"
        with get_sync_path_lock(provider_path):
            self._save_provider_snapshot(
                provider.id,
                provider,
                provider_path=provider_path,
            )

    def save_provider_config(
        self,
        provider_id: str,
        provider: Provider | None = None,
    ) -> None:
        """Persist the current in-memory provider state to disk.

        Args:
            provider_id: The provider to save.
            provider: Optional pre-resolved provider instance. When
                supplied, this instance is saved directly — important
                for plugin providers where ``get_provider`` returns a
                fresh copy each time.
        """
        if provider is None:
            provider = self.get_provider(provider_id)
        if provider is None:
            return
        provider_path = self._provider_config_path(provider_id)
        with get_sync_path_lock(provider_path):
            if provider_id in self.plugin_providers:
                self.plugin_providers[provider_id]["info"] = ProviderInfo(
                    **provider.model_dump(),
                )
            self._save_provider_snapshot(provider_id, provider)

    @staticmethod
    def _copy_model_fields(
        target: Provider,
        source: Provider,
        model_id: str,
        fields: tuple[str, ...] | set[str],
    ) -> None:
        """Copy operation-owned fields for one model between snapshots."""
        for target_collection, source_collection in zip(
            (
                target.models,
                target.extra_models,
                target.discovered_models,
            ),
            (
                source.models,
                source.extra_models,
                source.discovered_models,
            ),
        ):
            target_model = next(
                (model for model in target_collection if model.id == model_id),
                None,
            )
            source_model = next(
                (model for model in source_collection if model.id == model_id),
                None,
            )
            if target_model is None or source_model is None:
                continue
            for field in fields:
                if field in source_model.__class__.model_fields:
                    setattr(target_model, field, getattr(source_model, field))

    def _merge_plugin_snapshot(
        self,
        provider_id: str,
        result: Provider,
        update_kind: PluginUpdateKind,
        *,
        model_id: str | None,
        fields: set[str] | None,
    ) -> Provider:
        """Merge an operation result into the latest plugin snapshot."""
        plugin = self.plugin_providers[provider_id]
        latest = plugin["class"](**plugin["info"].model_dump())
        if update_kind == "replace":
            return result.model_copy(deep=True)
        if update_kind == "config":
            for field in fields or set():
                if field in latest.__class__.model_fields:
                    setattr(latest, field, getattr(result, field))
            if _CONNECTION_CONFIG_FIELDS.intersection(fields or set()):
                self._reset_model_availability(latest)
            return latest
        if update_kind == "discovery":
            latest.discovered_models = [
                model.model_copy(deep=True)
                for model in result.discovered_models
            ]
            latest.models_last_synced_at = result.models_last_synced_at
            latest.models_last_sync_error = result.models_last_sync_error
            latest.models_syncing = result.models_syncing
            for model in result.configured_models():
                self._copy_model_fields(
                    latest,
                    result,
                    model.id,
                    _DISCOVERY_MODEL_FIELDS,
                )
            return latest
        return self._merge_plugin_model_update(
            latest,
            result,
            update_kind=update_kind,
            model_id=model_id,
            fields=fields,
        )

    def _merge_plugin_model_update(
        self,
        latest: Provider,
        result: Provider,
        *,
        update_kind: PluginUpdateKind,
        model_id: str | None,
        fields: set[str] | None,
    ) -> Provider:
        """Merge a model-scoped operation into a plugin snapshot."""
        if model_id is None:
            raise ValueError(f"{update_kind} requires a model ID")
        if update_kind == "availability":
            self._copy_model_fields(
                latest,
                result,
                model_id,
                _AVAILABILITY_MODEL_FIELDS,
            )
        elif update_kind == "configured_add":
            latest.removed_model_ids = [
                item for item in latest.removed_model_ids if item != model_id
            ]
            added = next(
                (
                    model
                    for model in result.extra_models
                    if model.id == model_id
                ),
                None,
            )
            if added is not None:
                latest.extra_models = [
                    model
                    for model in latest.extra_models
                    if model.id != model_id
                ]
                latest.extra_models.append(added.model_copy(deep=True))
        elif update_kind == "configured_delete":
            removed_ids = set(latest.removed_model_ids)
            removed_ids.add(model_id)
            latest.removed_model_ids = sorted(removed_ids)
            latest.extra_models = [
                model for model in latest.extra_models if model.id != model_id
            ]
            latest.discovered_models = [
                model
                for model in latest.discovered_models
                if model.id != model_id
            ]
        elif update_kind == "configured_update":
            model_fields = set(fields or set())
            model_fields.add("config_overrides")
            if "max_input_length" in model_fields:
                model_fields.add("max_input_length_configured")
            self._copy_model_fields(
                latest,
                result,
                model_id,
                model_fields,
            )
        elif update_kind == "capability":
            self._copy_model_fields(
                latest,
                result,
                model_id,
                _CAPABILITY_MODEL_FIELDS,
            )
        return latest

    async def save_provider_config_async(
        self,
        provider_id: str,
        provider: Provider | None = None,
        *,
        update_kind: PluginUpdateKind = "replace",
        model_id: str | None = None,
        fields: set[str] | None = None,
    ) -> None:
        """Persist provider state without blocking the event loop."""
        provider_id = self._normalize_provider_id(provider_id)
        if provider is None:
            provider = self.get_provider(provider_id)
        if provider is None:
            return
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            await run_async_to_completion(
                self._save_provider_config_locked(
                    provider_id,
                    provider,
                    update_kind=update_kind,
                    model_id=model_id,
                    fields=fields,
                ),
            )

    async def _save_provider_config_locked(
        self,
        provider_id: str,
        provider: Provider,
        *,
        update_kind: PluginUpdateKind,
        model_id: str | None,
        fields: set[str] | None,
    ) -> None:
        """Save a provider while its per-provider lock is held."""
        provider_path = self._provider_config_path(provider_id)
        if provider_id in self.plugin_providers:
            snapshot = self._merge_plugin_snapshot(
                provider_id,
                provider,
                update_kind,
                model_id=model_id,
                fields=fields,
            )
        else:
            snapshot = self._merge_provider_snapshot(
                provider_id,
                provider,
                update_kind,
                model_id=model_id,
                fields=fields,
            )
        await run_sync_io(
            self._save_provider_snapshot_locked,
            provider_id,
            snapshot,
            provider_path,
        )
        self._commit_provider_snapshot(provider_id, snapshot)

    def _commit_provider_snapshot(
        self,
        provider_id: str,
        snapshot: Provider,
    ) -> None:
        """Commit a successfully persisted snapshot on the event loop."""
        if provider_id in self.plugin_providers:
            self.plugin_providers[provider_id]["info"] = ProviderInfo(
                **snapshot.model_dump(),
            )
            return
        current = self.get_provider(provider_id)
        if current is not None:
            self._copy_provider_state(current, snapshot)

    def _merge_and_save_provider_snapshot(
        self,
        provider_id: str,
        provider: Provider,
        update_kind: PluginUpdateKind,
        model_id: str | None,
        fields: set[str] | None,
    ) -> Provider:
        """Merge and persist one provider under the shared file lock."""
        provider_path = self._provider_config_path(provider_id)
        with get_sync_path_lock(provider_path):
            if provider_id in self.plugin_providers:
                snapshot = self._merge_plugin_snapshot(
                    provider_id,
                    provider,
                    update_kind,
                    model_id=model_id,
                    fields=fields,
                )
            else:
                snapshot = self._merge_provider_snapshot(
                    provider_id,
                    provider,
                    update_kind,
                    model_id=model_id,
                    fields=fields,
                )
            self._save_provider_snapshot(provider_id, snapshot)
            if provider_id in self.plugin_providers:
                self.plugin_providers[provider_id][
                    "info"
                ] = ProviderInfo.model_validate(snapshot.model_dump())
            else:
                current = self.get_provider(provider_id)
                if current is not None and current is not provider:
                    self._copy_provider_state(current, snapshot)
            return snapshot

    @staticmethod
    def _copy_provider_state(target: Provider, source: Provider) -> None:
        """Replace one in-memory provider state with a deep snapshot."""
        snapshot = source.model_copy(deep=True)
        for field in target.__class__.model_fields:
            if field in {"models", "extra_models", "discovered_models"}:
                existing = {
                    model.id: model for model in getattr(target, field)
                }
                copied_models = []
                for source_model in getattr(snapshot, field):
                    target_model = existing.get(source_model.id)
                    if target_model is None:
                        copied_models.append(source_model)
                        continue
                    for model_field in target_model.__class__.model_fields:
                        setattr(
                            target_model,
                            model_field,
                            getattr(source_model, model_field),
                        )
                    copied_models.append(target_model)
                setattr(target, field, copied_models)
                continue
            setattr(target, field, getattr(snapshot, field))

    def _save_provider_snapshot_locked(
        self,
        provider_id: str,
        provider: Provider,
        provider_path: Path,
    ) -> None:
        """Write a detached snapshot under the shared filesystem lock."""
        with get_sync_path_lock(provider_path):
            self._save_provider_snapshot(
                provider_id,
                provider,
                provider_path=provider_path,
            )

    def _merge_provider_snapshot(
        self,
        provider_id: str,
        result: Provider,
        update_kind: PluginUpdateKind,
        *,
        model_id: str | None,
        fields: set[str] | None,
    ) -> Provider:
        """Merge an operation result into the current provider snapshot."""
        current = self.get_provider(provider_id)
        if current is None or current is result:
            return result.model_copy(deep=True)
        latest = current.model_copy(deep=True)
        if update_kind == "replace":
            snapshot = result.model_copy(deep=True)
            snapshot.removed_model_ids = list(current.removed_model_ids)
            return snapshot
        if update_kind == "config":
            for field in fields or set():
                if field in latest.__class__.model_fields:
                    setattr(latest, field, getattr(result, field))
            if _CONNECTION_CONFIG_FIELDS.intersection(fields or set()):
                self._reset_model_availability(latest)
            return latest
        if update_kind == "discovery":
            latest.discovered_models = [
                model.model_copy(deep=True)
                for model in result.discovered_models
            ]
            latest.models_last_synced_at = result.models_last_synced_at
            latest.models_last_sync_error = result.models_last_sync_error
            latest.models_syncing = result.models_syncing
            for model in result.configured_models():
                self._copy_model_fields(
                    latest,
                    result,
                    model.id,
                    _DISCOVERY_MODEL_FIELDS,
                )
            return latest
        return self._merge_plugin_model_update(
            latest,
            result,
            update_kind=update_kind,
            model_id=model_id,
            fields=fields,
        )

    async def register_plugin_provider_async(
        self,
        provider_id: str,
        provider_class,
        label: str,
        base_url: str,
        metadata: Dict,
    ) -> None:
        """Register a plugin provider without blocking the event loop."""
        revision = self._bump_provider_revision(provider_id)
        registration = await asyncio.to_thread(
            self._prepare_plugin_registration,
            provider_id,
            provider_class,
            label,
            base_url,
            metadata,
        )
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            if revision != self._provider_revision(provider_id):
                return
            self.plugin_providers[provider_id] = registration

    def _prepare_plugin_registration(
        self,
        provider_id: str,
        provider_class,
        label: str,
        base_url: str,
        metadata: Dict,
    ) -> dict:
        """Build plugin registration data without touching shared state."""
        default_models = []
        if hasattr(provider_class, "get_default_models"):
            try:
                default_models = provider_class.get_default_models()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    f"Failed to get default models for {provider_id}: {exc}",
                )
        provider_info = ProviderInfo(
            id=provider_id,
            name=label,
            base_url=base_url,
            api_key="",
            chat_model=metadata.get("chat_model", "OpenAIChatModel"),
            models=default_models,
            is_custom=False,
            require_api_key=metadata.get("require_api_key", True),
            meta=metadata.get("meta", {}),
        )
        saved_config_path = self.plugin_path / f"{provider_id}.json"
        if saved_config_path.exists():
            try:
                with open(saved_config_path, "r", encoding="utf-8") as handle:
                    saved_config = decrypt_dict_fields(
                        json.load(handle),
                        PROVIDER_SECRET_FIELDS,
                    )
                for field in (
                    "api_key",
                    "base_url",
                    "generate_kwargs",
                    "custom_headers",
                    "auth_mode",
                    "hidden_model_ids",
                    "removed_model_ids",
                ):
                    if field in saved_config:
                        setattr(provider_info, field, saved_config[field])
                for field in ("extra_models", "discovered_models"):
                    if field in saved_config:
                        setattr(
                            provider_info,
                            field,
                            [
                                ModelInfo.model_validate(model)
                                for model in saved_config[field]
                            ],
                        )
                provider_info.models_last_synced_at = saved_config.get(
                    "models_last_synced_at",
                )
                provider_info.models_last_sync_error = saved_config.get(
                    "models_last_sync_error",
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    f"Failed to load saved config for {provider_id}: {exc}",
                )
        return {"info": provider_info, "class": provider_class}

    @staticmethod
    def _replace_with_retry(
        src: str,
        dst: str,
        *,
        attempts: int = 5,
        delay: float = 0.1,
    ) -> None:
        """Compatibility wrapper for atomic replacement with retry."""
        replace_with_retry(src, dst, attempts=attempts, delay=delay)

    def _save_provider_snapshot(
        self,
        provider_id: str,
        provider: Provider,
        *,
        provider_path: Path | None = None,
    ) -> None:
        """Serialize and atomically write a provider snapshot."""
        if provider_path is None:
            provider_path = self._provider_config_path(
                provider_id,
                provider.id,
            )
        write_provider_snapshot(
            provider,
            provider_path,
            replace_operation=self._replace_with_retry,
        )

    def _provider_config_path(
        self,
        provider_id: str,
        file_provider_id: str | None = None,
    ) -> Path:
        """Return the canonical persisted path for one provider."""
        if provider_id in self.plugin_providers:
            provider_dir = self.plugin_path
        elif provider_id in self.builtin_providers:
            provider_dir = self.builtin_path
        else:
            provider_dir = self.custom_path
        return self._safe_provider_path(
            provider_dir,
            file_provider_id or provider_id,
        )

    @staticmethod
    def _safe_provider_path(provider_dir: Path, provider_id: str) -> Path:
        """Keep a provider snapshot inside its designated directory."""
        provider_path = provider_dir / f"{provider_id}.json"
        if provider_path.parent.resolve() != provider_dir.resolve():
            raise ProviderError(
                message=f"Provider ID '{provider_id}' escapes its storage.",
            )
        return provider_path

    def load_provider(
        self,
        provider_id: str,
        is_builtin: bool = False,
    ) -> Provider | None:
        """Load a provider configuration from disk.

        Encrypted fields are transparently decrypted.  If a legacy
        plaintext ``api_key`` is detected it is re-encrypted in place.
        """
        provider_dir = self.builtin_path if is_builtin else self.custom_path
        provider_path = self._safe_provider_path(provider_dir, provider_id)
        if not provider_path.exists():
            return None
        try:
            with open(provider_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            needs_rewrite = self._maybe_migrate_plaintext(
                data,
                PROVIDER_SECRET_FIELDS,
            )
            data = decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
            provider = self._provider_from_data(data)
            provider.models_syncing = False

            if needs_rewrite:
                try:
                    self._save_provider(
                        provider,
                        is_builtin=is_builtin,
                        skip_if_exists=False,
                    )
                except Exception as enc_err:
                    logger.debug(
                        "Deferred plaintext→encrypted migration"
                        " for provider '%s': %s",
                        provider_id,
                        enc_err,
                    )

            return provider
        except Exception as e:
            logger.warning(
                "Failed to load provider '%s' from %s: %s",
                provider_id,
                provider_path,
                e,
            )
            return None

    @staticmethod
    def _maybe_migrate_plaintext(
        data: dict,
        secret_fields: frozenset[str],
    ) -> bool:
        """Return ``True`` when *data* contains plaintext secret fields
        that should be re-encrypted on disk."""
        for field in secret_fields:
            value = data.get(field)
            if isinstance(value, str) and value and not is_encrypted(value):
                return True
        return False

    def _provider_from_data(self, data: Dict) -> Provider:
        """Deserialize provider data to a concrete provider type."""
        provider_id = str(data.get("id", ""))
        chat_model = str(data.get("chat_model", ""))

        if provider_id == "openrouter":
            provider_type = OpenRouterProvider
        elif provider_id == "anthropic" or chat_model == "AnthropicChatModel":
            provider_type = AnthropicProvider
        elif provider_id == "gemini" or chat_model == "GeminiChatModel":
            provider_type = GeminiProvider
        elif provider_id == "dashscope" or chat_model == "DashScopeChatModel":
            provider_type = DashScopeProvider
        elif provider_id == "ollama":
            provider_type = OllamaProvider
        elif chat_model == "OpenAIResponseModel":
            provider_type = OpenAIResponseProvider
        else:
            provider_type = OpenAIProvider
        return provider_type.model_validate(data)

    def save_active_model(self, active_model: ModelSlotConfig):
        """Atomically save the active provider/model configuration."""
        active_path = self.root_path / "active_model.json"
        fd, temp_name = tempfile.mkstemp(
            prefix=".active_model.",
            suffix=".tmp",
            dir=self.root_path,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    active_model.model_dump(),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_with_retry(temp_name, str(active_path))
            try:
                os.chmod(active_path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass

    async def save_active_model_async(
        self,
        active_model: ModelSlotConfig,
    ) -> None:
        """Persist the active model without blocking the event loop."""
        lock = self._provider_save_locks.setdefault(
            "__active_model__",
            asyncio.Lock(),
        )
        snapshot = active_model.model_copy(deep=True)
        async with lock:
            await run_sync_io(self.save_active_model, snapshot)

    def clear_active_model(self, provider_id: str | None = None) -> bool:
        """Clear the active provider/model configuration.

        If provider_id is provided, only clear when it matches the current
        active provider.
        """
        if self.active_model is None:
            return False
        # Normalize provider ID for backward compatibility
        if provider_id is not None:
            provider_id = self._normalize_provider_id(provider_id)
        if (
            provider_id is not None
            and self.active_model.provider_id != provider_id
        ):
            return False

        self.active_model = None
        active_path = self.root_path / "active_model.json"
        try:
            active_path.unlink()
        except (FileNotFoundError, OSError):
            pass
        return True

    async def clear_active_model_async(
        self,
        provider_id: str | None = None,
    ) -> bool:
        """Clear the active model without blocking the event loop."""
        if provider_id is not None:
            provider_id = self._normalize_provider_id(provider_id)
        lock = self._provider_save_locks.setdefault(
            "__active_model__",
            asyncio.Lock(),
        )

        async def clear_model() -> bool:
            async with lock:
                if self.active_model is None:
                    return False
                if (
                    provider_id is not None
                    and self.active_model.provider_id != provider_id
                ):
                    return False
                active_path = self.root_path / "active_model.json"
                await run_sync_io(active_path.unlink, missing_ok=True)
                self.active_model = None
                return True

        return await run_async_to_completion(clear_model())

    def load_active_model(self) -> ModelSlotConfig | None:
        """Load the active provider/model configuration from disk."""
        active_path = self.root_path / "active_model.json"
        if not active_path.exists():
            return None
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return ModelSlotConfig.model_validate(data)
        except Exception:
            return None

    def _migrate_copaw_config(self) -> None:
        """Migrate copaw-local provider config to qwenpaw-local."""
        # 1. Migrate active model configuration (only provider_id)
        if (
            self.active_model
            and self.active_model.provider_id == "copaw-local"
        ):
            self.active_model.provider_id = "qwenpaw-local"
            self.save_active_model(self.active_model)
            logger.info(
                "Migrated active model provider from "
                "'copaw-local' to 'qwenpaw-local'",
            )

        # 2. Migrate stored provider config file
        copaw_config_path = self.builtin_path / "copaw-local.json"
        if not copaw_config_path.exists():
            return

        try:
            # Load old config and apply to new provider instance
            with open(copaw_config_path, "r", encoding="utf-8") as f:
                old_config = json.load(f)

            # Get the new built-in provider instance
            provider = self.builtin_providers.get("qwenpaw-local")
            if not provider:
                return

            # Apply migrated configuration (preserve extra_models as-is)
            if "extra_models" in old_config:
                provider.extra_models = [
                    ModelInfo.model_validate(model)
                    for model in old_config["extra_models"]
                ]
            if "base_url" in old_config:
                provider.base_url = old_config["base_url"]
            if "generate_kwargs" in old_config:
                provider.generate_kwargs = old_config["generate_kwargs"]

            # Save using standard persistence logic (with encryption)
            self._save_provider(provider, is_builtin=True)

            # Remove old config file
            copaw_config_path.unlink()
            logger.info(
                "Migrated provider config from "
                "'copaw-local.json' to 'qwenpaw-local.json'",
            )
        except Exception as exc:
            logger.warning("Failed to migrate copaw-local config: %s", exc)

    def _migrate_legacy_providers(self):
        """Migrate from legacy providers.json format to the new structure."""
        from . import provider_manager as provider_manager_module

        legacy_path = provider_manager_module.SECRET_DIR / "providers.json"
        if legacy_path.exists() and legacy_path.is_file():
            with open(legacy_path, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            builtin_providers = legacy_data.get("providers", {})
            custom_providers = legacy_data.get("custom_providers", {})
            active_model = legacy_data.get("active_llm", {})
            # Migrate built-in providers
            for provider_id, config in builtin_providers.items():
                provider = self.get_provider(provider_id)
                if not provider:
                    logger.warning(
                        "Legacy provider '%s' not found in"
                        " registry, skipping migration for this provider.",
                        provider_id,
                    )
                    continue
                if "api_key" in config:
                    provider.api_key = config["api_key"]
                if "extra_models" in config:
                    provider.extra_models = [
                        ModelInfo.model_validate(model)
                        for model in config["extra_models"]
                    ]
                if not provider.freeze_url and "base_url" in config:
                    provider.base_url = config["base_url"]
                self._save_provider(provider, is_builtin=True)
            self._migrate_legacy_custom_providers(custom_providers)
            self._migrate_legacy_active_model(active_model)
            # Remove legacy file after migration
            try:
                os.remove(legacy_path)
            except Exception:
                logger.warning(
                    "Failed to remove legacy providers.json after migration.",
                )

    def _migrate_legacy_custom_providers(
        self,
        custom_providers: dict,
    ) -> None:
        """Persist custom providers from the legacy configuration."""
        for provider_id, data in custom_providers.items():
            custom_provider = OpenAIProvider(
                id=provider_id,
                name=data.get("name", provider_id),
                base_url=data.get("base_url", ""),
                api_key=data.get("api_key", ""),
                is_custom=True,
            )
            if "models" in data:
                custom_provider.extra_models = [
                    ModelInfo.model_validate(model) for model in data["models"]
                ]
            if "chat_model" in data:
                custom_provider.chat_model = data["chat_model"]
            self._save_provider(custom_provider, is_builtin=False)

    def _migrate_legacy_active_model(self, active_model: dict) -> None:
        """Persist the active model from the legacy configuration."""
        if not active_model:
            return
        try:
            if active_model.get("provider_id") == "copaw-local":
                active_model["provider_id"] = "qwenpaw-local"
            migrated = ModelSlotConfig.model_validate(active_model)
            self.active_model = migrated
            self.save_active_model(migrated)
        except Exception:
            logger.warning(
                "Failed to migrate active model, using default.",
            )

    def _init_from_storage(self):
        """Initialize all providers and active model from disk storage."""
        for builtin in self.builtin_providers.values():
            provider = self.load_provider(builtin.id, is_builtin=True)
            if provider:
                self._restore_builtin_provider(builtin, provider)
        # Load custom providers
        for provider_file in self.custom_path.glob("*.json"):
            provider = self.load_provider(provider_file.stem, is_builtin=False)
            if provider:
                self.custom_providers[provider.id] = provider
        # Load active model config
        active_model = self.load_active_model()
        if active_model:
            self.active_model = active_model

        # Migrate copaw-local to qwenpaw-local for backwards compatibility
        self._migrate_copaw_config()

    @staticmethod
    def _restore_builtin_provider(
        builtin: Provider,
        provider: Provider,
    ) -> None:
        """Restore persisted configuration onto a built-in provider."""
        if not builtin.freeze_url:
            builtin.base_url = provider.base_url
        builtin.api_key = provider.api_key
        if provider.auth_mode != "api_key":
            builtin.auth_mode = provider.auth_mode
        if provider.custom_headers:
            builtin.custom_headers = provider.custom_headers
        if hasattr(builtin, "max_inline_media_bytes"):
            builtin.max_inline_media_bytes = provider.max_inline_media_bytes

        builtin_model_ids = {model.id for model in builtin.models}
        builtin.extra_models = [
            model
            for model in provider.extra_models
            if model.id not in builtin_model_ids
        ]
        builtin.discovered_models = provider.discovered_models
        builtin.models_last_synced_at = provider.models_last_synced_at
        builtin.models_last_sync_error = provider.models_last_sync_error
        builtin.models_syncing = False
        builtin.hidden_model_ids = list(provider.hidden_model_ids)
        builtin.removed_model_ids = list(provider.removed_model_ids)
        builtin.generate_kwargs.update(provider.generate_kwargs)

        stored_model_config = {
            model.id: serialize_model_state(model) for model in provider.models
        }
        for model in provider.extra_models:
            if model.id in builtin_model_ids:
                stored_model_config.setdefault(
                    model.id,
                    serialize_model_state(model),
                )
        for model in builtin.models:
            config = stored_model_config.get(model.id)
            if config:
                restore_model_state(model, config)
