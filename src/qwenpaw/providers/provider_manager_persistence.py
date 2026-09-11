# -*- coding: utf-8 -*-
"""Persistence and migration operations for ProviderManager."""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Literal

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
from .provider_manager_host import ProviderManagerHost
from .provider_discovery import (
    DISCOVERY_MODEL_FIELDS as _DISCOVERY_MODEL_FIELDS,
)
from .provider_model_state import (
    migrate_provider_snapshot,
    restore_model_state,
    serialize_model_state,
)
from .provider_discovery_policy import apply_custom_discovery_policy
from . import provider_persistence
from .provider_update_fields import (
    AVAILABILITY_MODEL_FIELDS as _AVAILABILITY_MODEL_FIELDS,
    CAPABILITY_MODEL_FIELDS as _CAPABILITY_MODEL_FIELDS,
    CONNECTION_CONFIG_FIELDS as _CONNECTION_CONFIG_FIELDS,
    PluginUpdateKind,
)

logger = logging.getLogger(__name__)

ProviderStorageKind = Literal["builtin", "custom", "plugin"]


# The host's stubs are implemented by ProviderManager / the sibling
# mixin once the class is assembled; this mixin never instantiates
# standalone, so the inherited "abstract" members are intentional.
class ProviderManagerPersistenceMixin(
    ProviderManagerHost,
):  # pylint: disable=abstract-method
    """Provide provider snapshot persistence and migration operations."""

    async def _mutate_provider_async(
        self,
        provider_id: str,
        operation: Callable[[Provider], Awaitable[Any]],
    ) -> Any:
        """Persist a provider mutation before committing live state."""
        provider_id = self._normalize_provider_id(provider_id)
        lock = self._provider_save_locks.setdefault(
            provider_id,
            asyncio.Lock(),
        )
        async with lock:
            provider = self.get_provider(provider_id)
            if provider is None:
                return None
            candidate = provider.model_copy(deep=True)
            result = await operation(candidate)
            provider_path = await self._provider_config_path_async(provider_id)
            snapshot = candidate.model_copy(deep=True)

            async def persist_and_commit() -> None:
                await run_sync_io(
                    self._save_provider_snapshot_locked,
                    provider_id,
                    snapshot,
                    provider_path,
                )
                self._commit_provider_snapshot(provider_id, snapshot)
                self._bump_provider_revision(provider_id)

            await run_async_to_completion(persist_and_commit())
            return result

    def _save_provider(
        self,
        provider: Provider,
        is_builtin: bool = False,
        skip_if_exists: bool = False,
    ):
        """Save a provider configuration to disk.

        Sensitive fields (``api_key``) are encrypted before writing.
        """
        storage_kind: ProviderStorageKind = (
            "builtin" if is_builtin else "custom"
        )
        provider_path = self._provider_path_for_kind(
            storage_kind,
            provider.id,
        )
        with get_sync_path_lock(provider_path):
            if skip_if_exists and provider_path.exists():
                return
            self._save_provider_snapshot(
                provider.id,
                provider,
                provider_path=provider_path,
            )

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
        provider_path = await self._provider_config_path_async(provider_id)
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
        if (
            current is not None
            and provider_id in self.custom_providers
            and current.__class__ is not snapshot.__class__
        ):
            self.custom_providers[provider_id] = snapshot.model_copy(
                deep=True,
            )
        elif current is not None:
            self._copy_provider_state(current, snapshot)

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

    async def _restore_latest_snapshot(
        self,
        provider_id: str,
        provider_path: Path,
    ) -> None:
        """Rewrite the on-disk snapshot from the live provider state.

        Compensates a detached write that lost the revision/generation
        race: without the rewrite, the stale snapshot stays on disk and
        the concurrent winning update is silently swallowed on the next
        restart.  When the provider was removed mid-flight, the stale
        write already resurrected its file -- delete it instead, or the
        removed provider would come back on the next startup glob.
        """
        latest = self.get_provider(provider_id)
        if latest is None:
            await run_sync_io(
                self._remove_orphan_snapshot,
                provider_path,
            )
            return
        await run_sync_io(
            self._save_provider_snapshot_locked,
            provider_id,
            latest.model_copy(deep=True),
            provider_path,
        )

    @staticmethod
    def _remove_orphan_snapshot(provider_path: Path) -> None:
        """Delete a snapshot written for a since-removed provider."""
        with get_sync_path_lock(provider_path):
            try:
                provider_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Failed to remove orphan provider snapshot at %s",
                    provider_path,
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
        *,
        metadata: Dict,
    ) -> None:
        """Register a plugin provider without blocking the event loop."""
        provider_key = self._ensure_plugin_provider_id_available(provider_id)
        provider_path = await self._provider_path_for_kind_async(
            "plugin",
            provider_id,
        )
        revision = self._bump_provider_revision(provider_key)
        registration = await asyncio.to_thread(
            self._prepare_plugin_registration,
            provider_id,
            provider_class,
            label,
            base_url,
            metadata=metadata,
            saved_config_path=provider_path,
        )
        lock = self._provider_save_locks.setdefault(
            provider_key,
            asyncio.Lock(),
        )
        async with lock:
            if revision != self._provider_revision(provider_key):
                return
            self.plugin_providers[provider_key] = registration

    def _prepare_plugin_registration(
        self,
        provider_id: str,
        provider_class,
        label: str,
        base_url: str,
        *,
        metadata: Dict,
        saved_config_path: Path,
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
        if saved_config_path.exists():
            try:
                with open(saved_config_path, "r", encoding="utf-8") as handle:
                    snapshot = json.load(handle)
                snapshot_migrated = migrate_provider_snapshot(snapshot)
                saved_config = decrypt_dict_fields(
                    snapshot,
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
                if snapshot_migrated:
                    provider_persistence.write_snapshot_payload(
                        snapshot,
                        saved_config_path,
                    )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    f"Failed to load saved config for {provider_id}: {exc}",
                )
        return {"info": provider_info, "class": provider_class}

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
        provider_persistence.write_provider_snapshot(
            provider,
            provider_path,
        )

    def _provider_config_path(
        self,
        provider_id: str,
        file_provider_id: str | None = None,
    ) -> Path:
        """Return the canonical persisted path for one provider."""
        provider_id = self._normalize_provider_id(provider_id)
        if provider_id in self.plugin_providers:
            storage_kind: ProviderStorageKind = "plugin"
        elif provider_id in self.builtin_providers:
            storage_kind = "builtin"
        else:
            storage_kind = "custom"
        return self._provider_path_for_kind(
            storage_kind,
            file_provider_id or provider_id,
        )

    async def _provider_config_path_async(
        self,
        provider_id: str,
        file_provider_id: str | None = None,
    ) -> Path:
        """Resolve and cache a provider path without blocking the loop."""
        provider_id = self._normalize_provider_id(provider_id)
        if provider_id in self.plugin_providers:
            storage_kind: ProviderStorageKind = "plugin"
        elif provider_id in self.builtin_providers:
            storage_kind = "builtin"
        else:
            storage_kind = "custom"
        return await self._provider_path_for_kind_async(
            storage_kind,
            file_provider_id or provider_id,
        )

    async def _provider_path_for_kind_async(
        self,
        storage_kind: ProviderStorageKind,
        provider_id: str,
    ) -> Path:
        """Resolve one provider path without blocking the event loop."""
        provider_key = self._normalize_provider_id(provider_id)
        storage_key = (storage_kind, provider_key)
        tracked_path = self._provider_storage_paths.get(storage_key)
        if tracked_path is not None:
            return tracked_path

        provider_dir = {
            "builtin": self.builtin_path,
            "custom": self.custom_path,
            "plugin": self.plugin_path,
        }[storage_kind]
        provider_path = await run_sync_io(
            self._safe_provider_path,
            provider_dir,
            provider_key,
        )
        self._provider_storage_paths[storage_key] = provider_path
        return provider_path

    def _provider_path_for_kind(
        self,
        storage_kind: ProviderStorageKind,
        provider_id: str,
    ) -> Path:
        """Resolve one provider identity to a stable persisted path."""
        provider_key = self._normalize_provider_id(provider_id)
        storage_key = (storage_kind, provider_key)
        tracked_path = self._provider_storage_paths.get(storage_key)
        if tracked_path is not None:
            return tracked_path

        provider_dir = {
            "builtin": self.builtin_path,
            "custom": self.custom_path,
            "plugin": self.plugin_path,
        }[storage_kind]
        provider_path = self._safe_provider_path(
            provider_dir,
            provider_key,
        )
        self._provider_storage_paths[storage_key] = provider_path
        return provider_path

    def _index_provider_storage_paths(self) -> None:
        """Index legacy provider filenames before async operations begin."""
        provider_dirs: tuple[tuple[ProviderStorageKind, Path], ...] = (
            ("builtin", self.builtin_path),
            ("custom", self.custom_path),
            ("plugin", self.plugin_path),
        )
        for storage_kind, provider_dir in provider_dirs:
            provider_files = sorted(
                provider_dir.glob("*.json"),
                key=lambda path: (
                    self._normalize_provider_id(path.stem),
                    path.name,
                ),
            )
            for provider_path in provider_files:
                self._remember_provider_path(
                    storage_kind,
                    provider_path.stem,
                    provider_path,
                )

    def _remember_provider_path(
        self,
        storage_kind: ProviderStorageKind,
        provider_id: str,
        provider_path: Path,
    ) -> bool:
        """Track a loaded legacy path without replacing an earlier choice."""
        provider_key = self._normalize_provider_id(provider_id)
        storage_key = (storage_kind, provider_key)
        tracked_path = self._provider_storage_paths.get(storage_key)
        if tracked_path is None:
            self._provider_storage_paths[storage_key] = provider_path
            return True
        if tracked_path == provider_path:
            return True
        logger.warning(
            f"Ignoring provider file {provider_path} because identity "
            f"'{provider_key}' already uses {tracked_path}.",
        )
        return False

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
        *,
        provider_path: Path | None = None,
    ) -> Provider | None:
        """Load a provider configuration from disk.

        Encrypted fields are transparently decrypted.  If a legacy
        plaintext ``api_key`` is detected it is re-encrypted in place.
        """
        storage_kind: ProviderStorageKind = (
            "builtin" if is_builtin else "custom"
        )
        if provider_path is None:
            provider_path = self._provider_path_for_kind(
                storage_kind,
                provider_id,
            )
        if not provider_path.exists():
            return None
        try:
            with open(provider_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            needs_rewrite = migrate_provider_snapshot(data)
            needs_rewrite = (
                self._maybe_migrate_plaintext(
                    data,
                    PROVIDER_SECRET_FIELDS,
                )
                or needs_rewrite
            )
            data = decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
            if storage_kind == "custom" and not data.get("is_custom"):
                data["is_custom"] = True
                needs_rewrite = True
            provider = self._provider_from_data(data)
            provider.models_syncing = False
            if not self._remember_provider_path(
                storage_kind,
                provider.id,
                provider_path,
            ):
                return None

            if needs_rewrite:
                try:
                    self._save_provider(
                        provider,
                        is_builtin=is_builtin,
                        skip_if_exists=False,
                    )
                except Exception as enc_err:
                    logger.debug(
                        "Deferred plaintext->encrypted migration"
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
        provider = provider_type.model_validate(data)
        apply_custom_discovery_policy(provider)
        return provider

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
            provider_persistence.replace_with_retry(
                temp_name,
                str(active_path),
            )
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
        """Persist and commit the active model as one transaction."""
        lock = self._provider_save_locks.setdefault(
            "__active_model__",
            asyncio.Lock(),
        )
        snapshot = active_model.model_copy(deep=True)

        async def save_and_commit() -> None:
            async with lock:
                await run_sync_io(self.save_active_model, snapshot)
                self.active_model = snapshot

        await run_async_to_completion(save_and_commit())

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
                    and self._normalize_provider_id(
                        self.active_model.provider_id,
                    )
                    != provider_id
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
        # Derive from the instance path (root_path = SECRET_DIR /
        # "providers") so test isolation only needs to patch the
        # manager's SECRET_DIR, never this module.
        legacy_path = self.root_path.parent / "providers.json"
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
            payload = {
                "id": provider_id,
                "name": data.get("name", provider_id),
                "base_url": data.get("base_url", ""),
                "api_key": data.get("api_key", ""),
                "chat_model": data.get("chat_model", "OpenAIChatModel"),
                "extra_models": data.get("models", []),
                "is_custom": True,
            }
            custom_provider = self._provider_from_data(payload)
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
        provider_files = sorted(
            self.custom_path.glob("*.json"),
            key=lambda path: (
                self._normalize_provider_id(path.stem),
                path.name,
            ),
        )
        for provider_file in provider_files:
            provider = self.load_provider(
                provider_file.stem,
                is_builtin=False,
                provider_path=provider_file,
            )
            if provider:
                provider_key = self._normalize_provider_id(provider.id)
                if provider_key in self.custom_providers:
                    logger.warning(
                        f"Ignoring provider file {provider_file} because "
                        f"identity '{provider_key}' is already loaded.",
                    )
                    continue
                self.custom_providers[provider_key] = provider
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
        unavailable_model_ids = getattr(
            builtin,
            "_UNAVAILABLE_MODEL_IDS",
            frozenset(),
        )
        builtin.extra_models = [
            model
            for model in provider.extra_models
            if model.id not in builtin_model_ids
            and model.id not in unavailable_model_ids
        ]
        builtin.discovered_models = [
            model
            for model in provider.discovered_models
            if model.id not in unavailable_model_ids
        ]
        builtin.models_last_synced_at = provider.models_last_synced_at
        builtin.models_last_sync_error = provider.models_last_sync_error
        builtin.models_syncing = False
        builtin.hidden_model_ids = list(provider.hidden_model_ids)
        builtin.removed_model_ids = list(provider.removed_model_ids)
        builtin.generate_kwargs.update(provider.generate_kwargs)

        # Catalog model metadata is authoritative. Persisted model state can
        # contain an older is_free value from before the catalog was updated.
        catalog_free_flags = {
            model.id: model.is_free for model in builtin.models
        }

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
            if model.id in catalog_free_flags:
                model.is_free = catalog_free_flags[model.id]
