# -*- coding: utf-8 -*-
"""Embedding updates and index-maintenance transactions for ReMe."""

# ReMeEmbedding is a lifecycle helper owned by the runtime and intentionally
# coordinates its private state under the runtime's locks.
# pylint: disable=protected-access

import logging
from collections.abc import Callable
from typing import Any

from ...config.config import (
    AgentProfileConfig,
    EmbeddingModelConfig,
    load_agent_config_async,
    update_agent_config_async,
)
from ...utils.io_utils import run_async_to_completion
from .embedding_model import (
    EmbeddingTestResult,
    embedding_config_fingerprint,
    embedding_vector_space_fingerprint,
    test_embedding_model,
)
from .reme_config import _is_embedding_enabled

logger = logging.getLogger(__name__)


class EmbeddingReindexUnavailableError(ValueError):
    """An embedding rebuild was requested without an enabled provider."""


class ReMeEmbedding:
    """Coordinate embedding state against a manager-owned ReMe runtime."""

    def __init__(
        self,
        runtime: Any,
        *,
        load_agent_config: Callable[..., Any] = load_agent_config_async,
        update_agent_config: Callable[..., Any] = update_agent_config_async,
    ) -> None:
        self.runtime = runtime
        self.load_agent_config = load_agent_config
        self.update_agent_config = update_agent_config

    async def test_and_stage(
        self,
        config: EmbeddingModelConfig,
    ) -> EmbeddingTestResult:
        model, result = await test_embedding_model(config)
        self.runtime._tested_embedding = (
            (embedding_config_fingerprint(config), model)
            if result.success and model is not None
            else None
        )
        return result

    async def apply_staged(self, config: EmbeddingModelConfig) -> bool:
        """Hot-apply a tested provider without rebuilding the ReMe runtime."""
        if self.runtime._reme is None or not getattr(
            self.runtime._reme,
            "is_started",
            False,
        ):
            return False
        staged = self.runtime._tested_embedding
        if staged is None or staged[0] != embedding_config_fingerprint(config):
            return False

        async with self.runtime._exclusive_reme_lifecycle("embedding-update"):
            reme = self.runtime._reme
            if reme is None or not getattr(reme, "is_started", False):
                return False
            old_config = self.runtime._active_embedding_config
            tested_model = staged[1]
            vector_space_changed = old_config is None or (
                embedding_vector_space_fingerprint(old_config)
                != embedding_vector_space_fingerprint(config)
            )
            file_store = await reme.update_component("file_store", "default")
            if vector_space_changed:
                await file_store.require_embedding_rebuild()
            else:
                if hasattr(tested_model, "context_size"):
                    tested_model.context_size = config.max_input_length
                await reme.update_component(
                    "as_embedding",
                    "default",
                    model=tested_model,
                )
                await reme.update_component(
                    "embedding_store",
                    "default",
                    enable_cache=config.enable_cache,
                    max_cache_size=config.max_cache_size,
                    max_input_length=config.max_input_length,
                    max_batch_size=config.max_batch_size,
                    health_check_timeout=config.health_check_timeout,
                )
                if not await file_store.resume_embedding(verified=True):
                    raise RuntimeError("ReMe refused to resume embedding")
                self.runtime._active_embedding_config = config.model_copy(
                    deep=True,
                )
            self.runtime._tested_embedding = None
            return True

    async def rebuild_index(self, scope: str = "all") -> Any:
        """Rebuild selected indexes while preserving host/runtime gates."""
        if scope not in {"all", "bm25", "embedding"}:
            raise ValueError("Unsupported reindex scope")
        if self.runtime.is_reindexing:
            raise RuntimeError("Memory index rebuild is already running")
        rebuilds_embedding = scope in {"all", "embedding"}
        async with (
            self.runtime._reindex_lock,
            self.runtime._exclusive_reme_lifecycle("reindex"),
        ):
            fingerprint = None
            if rebuilds_embedding:
                agent_config = await self.load_agent_config(
                    self.runtime.agent_id,
                )
                memory_config = agent_config.running.reme_light_memory_config
                target = memory_config.embedding_model_config.model_copy(
                    deep=True,
                )
                if not _is_embedding_enabled(target):
                    if scope == "embedding":
                        raise EmbeddingReindexUnavailableError(
                            "Embedding index rebuild requires an enabled "
                            "embedding configuration",
                        )
                    raise EmbeddingReindexUnavailableError(
                        "An all-scope index rebuild requires an enabled "
                        "embedding configuration",
                    )
                fingerprint = embedding_vector_space_fingerprint(target)
                prepared = await run_async_to_completion(
                    self._prepare_embedding_reindex(target, fingerprint),
                )
                if not prepared:
                    return None

            response = await self.runtime._run_reme_job(
                "reindex",
                raise_on_error=True,
                lifecycle_locked=True,
                scope=scope,
            )
            if not rebuilds_embedding or response is None:
                return response
            if response.success:
                assert fingerprint is not None
                await run_async_to_completion(
                    self._finalize_embedding_reindex(fingerprint),
                )
            return response

    async def _finalize_embedding_reindex(
        self,
        fingerprint: tuple[Any, ...],
    ) -> None:
        """Clear the matching requirement or restore the live vector gate."""
        requirement_cleared = False

        def clear_requirement(config: AgentProfileConfig) -> None:
            nonlocal requirement_cleared
            memory = config.running.reme_light_memory_config
            persisted = embedding_vector_space_fingerprint(
                memory.embedding_model_config,
            )
            if persisted == fingerprint:
                memory.needs_reindex = False
                memory.pending_reindex_embedding_config = None
                requirement_cleared = True

        try:
            await self.update_agent_config(
                self.runtime.agent_id,
                clear_requirement,
            )
        except Exception:
            try:
                await self.runtime._require_embedding_rebuild()
            except Exception:
                logger.exception(
                    "Failed to restore embedding gate for '%s'",
                    self.runtime.agent_id,
                )
            raise
        if not requirement_cleared:
            await self.runtime._require_embedding_rebuild()

    async def _prepare_embedding_reindex(
        self,
        target: EmbeddingModelConfig,
        fingerprint: tuple[Any, ...],
    ) -> bool:
        """Persist and enforce the live vector gate as one cancel-safe step."""
        await self._persist_reindex_requirement(fingerprint)
        reload_config = self.runtime._reload_embedding_config_unlocked
        if (
            self.runtime._active_embedding_config != target
            and not await reload_config()
        ):
            return False
        await self.runtime._require_embedding_rebuild()
        return True

    async def _persist_reindex_requirement(
        self,
        fingerprint: tuple[Any, ...],
    ) -> None:
        def persist(config: AgentProfileConfig) -> None:
            memory = config.running.reme_light_memory_config
            target = memory.embedding_model_config
            if not _is_embedding_enabled(target):
                raise EmbeddingReindexUnavailableError(
                    "Embedding configuration was disabled before "
                    "reindex started",
                )
            if embedding_vector_space_fingerprint(target) != fingerprint:
                raise RuntimeError(
                    "Embedding configuration changed before reindex started",
                )
            if not memory.needs_reindex:
                memory.pending_reindex_embedding_config = None
            memory.needs_reindex = True

        await self.update_agent_config(self.runtime.agent_id, persist)

    async def undo_reindex(self) -> EmbeddingModelConfig:
        """Restore indexed config, rolling runtime back if loading fails."""
        if self.runtime.is_reindexing:
            raise RuntimeError("Memory index rebuild is already running")
        async with (
            self.runtime._reindex_lock,
            self.runtime._exclusive_reme_lifecycle(
                "embedding-undo",
            ),
        ):
            return await run_async_to_completion(self._undo_reindex_unlocked())

    async def _undo_reindex_unlocked(self) -> EmbeddingModelConfig:
        """Complete persistence and runtime recovery before cancellation."""
        restored: EmbeddingModelConfig | None = None
        pending: EmbeddingModelConfig | None = None

        def restore_previous(config: AgentProfileConfig) -> None:
            nonlocal restored, pending
            memory = config.running.reme_light_memory_config
            previous = memory.pending_reindex_embedding_config
            if not memory.needs_reindex or previous is None:
                raise ValueError(
                    "No pending embedding index change can be undone",
                )
            pending = memory.embedding_model_config.model_copy(deep=True)
            restored = previous.model_copy(deep=True)
            memory.embedding_model_config = restored.model_copy(deep=True)
            memory.needs_reindex = False
            memory.pending_reindex_embedding_config = None

        await self.update_agent_config(
            self.runtime.agent_id,
            restore_previous,
        )
        indexed_loaded, indexed_error = await self._try_reload(
            "Failed to load indexed embedding configuration",
        )
        if not indexed_loaded:
            assert pending is not None and restored is not None

            def restore_pending(config: AgentProfileConfig) -> None:
                memory = config.running.reme_light_memory_config
                memory.embedding_model_config = pending.model_copy(
                    deep=True,
                )
                memory.needs_reindex = True
                memory.pending_reindex_embedding_config = restored.model_copy(
                    deep=True,
                )

            await self.update_agent_config(
                self.runtime.agent_id,
                restore_pending,
            )
            pending_loaded, pending_error = await self._try_reload(
                "Failed to restore pending embedding runtime",
            )
            message = (
                "Previous embedding configuration could not be loaded; "
                "pending embedding runtime was restored"
                if pending_loaded
                else "Previous embedding configuration and pending "
                "embedding runtime could not be loaded"
            )
            cause = pending_error or indexed_error
            if cause is not None:
                raise RuntimeError(message) from cause
            raise RuntimeError(message)
        assert restored is not None
        return restored

    async def _try_reload(
        self,
        log_message: str,
    ) -> tuple[bool, Exception | None]:
        try:
            loaded = await self.runtime._reload_embedding_config_unlocked()
            return loaded, None
        except Exception as exc:
            logger.exception(
                "%s for agent '%s'",
                log_message,
                self.runtime.agent_id,
            )
            return False, exc
