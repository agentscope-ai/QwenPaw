# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
# mypy: ignore-errors
"""ReMeLight-backed memory manager for CoPaw agents."""

import importlib.metadata
import json
import logging
import os
import platform
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from agentscope.message import Msg, TextBlock
from agentscope.tool import Toolkit, ToolResponse

from copaw.agents.memory.base_memory_manager import BaseMemoryManager
from copaw.agents.model_factory import create_model_and_formatter
from copaw.agents.tools import read_file, write_file, edit_file
from copaw.agents.utils import get_copaw_token_counter
from copaw.config import load_config
from copaw.config.config import load_agent_config
from copaw.config.context import (
    set_current_workspace_dir,
    set_current_recent_max_bytes,
)
from copaw.configs import copaw_config

if TYPE_CHECKING:
    from reme.memory.file_based.reme_in_memory_memory import ReMeInMemoryMemory

logger = logging.getLogger(__name__)

_EXPECTED_REME_VERSION = "0.3.1.8"


class ReMeLightMemoryManager(BaseMemoryManager):
    """Memory manager that wraps ReMeLight for CoPaw agents via composition.

    Holds a ``ReMeLight`` instance (``self._reme``) and delegates all
    lifecycle / search / compaction calls to it.

    Capabilities:
    - Conversation compaction via compact_memory()
    - Memory summarization with file tools via summary_memory()
    - Vector and full-text search via memory_search()
    """

    def __init__(self, working_dir: str, agent_id: str):
        """Initialize with ReMeLight.

        Args:
            working_dir: Working directory for memory storage.
            agent_id: Agent ID for config loading.

        Embedding priority: config > env var (EMBEDDING_API_KEY /
        EMBEDDING_BASE_URL / EMBEDDING_MODEL_NAME).
        Backend: MEMORY_STORE_BACKEND env var (auto/local/chroma,
        default auto).
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme_version_ok: bool = self._check_reme_version()
        self._reme = None

        logger.info(
            f"ReMeLightMemoryManager init: "
            f"agent_id={agent_id}, working_dir={working_dir}",
        )

        backend_env = copaw_config.MEMORY_STORE_BACKEND
        if backend_env == "auto":
            if platform.system() == "Windows":
                memory_backend = "local"
            else:
                try:
                    import chromadb  # noqa: F401 pylint: disable=unused-import

                    memory_backend = "chroma"
                except Exception as e:
                    logger.warning(
                        f"""
chromadb import failed, falling back to `local` backend.
This is often caused by an outdated system SQLite (requires >= 3.35).
Please upgrade your system SQLite to >= 3.35.
See: https://docs.trychroma.com/docs/overview/troubleshooting#sqlite
| Error: {e}
                        """,
                    )
                    memory_backend = "local"
        else:
            memory_backend = backend_env

        from reme.reme_light import ReMeLight

        emb_config = self.get_embedding_config()
        vector_enabled = bool(emb_config["base_url"]) and bool(
            emb_config["model_name"],
        )

        log_cfg = {
            **emb_config,
            "api_key": self._mask_key(emb_config["api_key"]),
        }
        logger.info(
            f"Embedding config: {log_cfg}, vector_enabled={vector_enabled}",
        )

        fts_enabled = copaw_config.FTS_ENABLED

        agent_config = load_agent_config(self.agent_id)
        rebuild_on_start = (
            agent_config.running.memory_summary.rebuild_memory_index_on_start
        )

        self._reme = ReMeLight(
            working_dir=working_dir,
            default_embedding_model_config=emb_config,
            default_file_store_config={
                "backend": memory_backend,
                "store_name": "copaw",
                "vector_enabled": vector_enabled,
                "fts_enabled": fts_enabled,
            },
            default_file_watcher_config={
                "rebuild_index_on_start": rebuild_on_start,
            },
        )

        self.summary_toolkit = Toolkit()
        self.summary_toolkit.register_tool_function(read_file)
        self.summary_toolkit.register_tool_function(write_file)
        self.summary_toolkit.register_tool_function(edit_file)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_key(key: str) -> str:
        """Mask API key, showing first 5 chars only."""
        return key[:5] + "*" * (len(key) - 5) if len(key) > 5 else key

    @staticmethod
    def _check_reme_version() -> bool:
        """Return False (and warn) when installed reme-ai version
        mismatches."""
        try:
            installed = importlib.metadata.version("reme-ai")
        except importlib.metadata.PackageNotFoundError:
            return True
        if installed != _EXPECTED_REME_VERSION:
            logger.warning(
                f"reme-ai version mismatch: installed={installed}, "
                f"expected={_EXPECTED_REME_VERSION}. "
                f"Run `pip install reme-ai=={_EXPECTED_REME_VERSION}`"
                " to align.",
            )
            return False
        return True

    def _warn_if_version_mismatch(self) -> None:
        """Warn once per call if the cached version check failed."""
        if not self._reme_version_ok:
            logger.warning(
                "reme-ai version mismatch, "
                f"expected={_EXPECTED_REME_VERSION}. "
                f"Run `pip install reme-ai=={_EXPECTED_REME_VERSION}`"
                " to align.",
            )

    def _prepare_model_formatter(self) -> None:
        """Lazily initialize chat_model and formatter if not already set."""
        self._warn_if_version_mismatch()
        if self.chat_model is None or self.formatter is None:
            self.chat_model, self.formatter = create_model_and_formatter(
                self.agent_id,
            )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_embedding_config(self) -> dict:
        """Return embedding config with priority:
        config > env var > default."""
        self._warn_if_version_mismatch()
        cfg = load_agent_config(self.agent_id).running.embedding_config
        return {
            "backend": cfg.backend,
            "api_key": cfg.api_key or copaw_config.EMBEDDING_API_KEY,
            "base_url": cfg.base_url or copaw_config.EMBEDDING_BASE_URL,
            "model_name": cfg.model_name or copaw_config.EMBEDDING_MODEL_NAME,
            "dimensions": cfg.dimensions,
            "enable_cache": cfg.enable_cache,
            "use_dimensions": cfg.use_dimensions,
            "max_cache_size": cfg.max_cache_size,
            "max_input_length": cfg.max_input_length,
            "max_batch_size": cfg.max_batch_size,
        }

    async def restart_embedding_model(self):
        """Restart the embedding model with current config."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return
        await self._reme.restart(
            restart_config={
                "embedding_models": {"default": self.get_embedding_config()},
            },
        )

    # ------------------------------------------------------------------
    # BaseMemoryManager interface
    # ------------------------------------------------------------------

    async def start(self):
        """Start the ReMeLight lifecycle."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.start()

    async def close(self) -> bool:
        """Close ReMeLight and perform cleanup."""
        self._warn_if_version_mismatch()
        logger.info(
            f"ReMeLightMemoryManager closing: agent_id={self.agent_id}",
        )
        if self._reme is None:
            return True
        result = await self._reme.close()
        logger.info(
            "ReMeLight closed: agent_id=%s, result=%s",
            self.agent_id,
            result,
        )
        return result

    async def compact_tool_result(self, **kwargs):
        """Compact tool results by truncating large outputs."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.compact_tool_result(**kwargs)

    async def check_context(self, **kwargs):
        """Check context size and determine if compaction is needed."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.check_context(**kwargs)

    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
        **_kwargs,
    ) -> str:
        """Compact messages into a condensed summary.

        Returns the compacted string, or empty string on failure.
        """
        self._prepare_model_formatter()

        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.context_compact

        if extra_instruction:
            result = await self._reme.compact_memory(
                messages=messages,
                as_llm=self.chat_model,
                as_llm_formatter=self.formatter,
                as_token_counter=get_copaw_token_counter(agent_config),
                language=agent_config.language,
                max_input_length=agent_config.running.max_input_length,
                compact_ratio=cc.memory_compact_ratio,
                previous_summary=previous_summary,
                return_dict=True,
                add_thinking_block=cc.compact_with_thinking_block,
                extra_instruction=extra_instruction,
            )
        else:
            # Compatible with older versions of ReMe
            result = await self._reme.compact_memory(
                messages=messages,
                as_llm=self.chat_model,
                as_llm_formatter=self.formatter,
                as_token_counter=get_copaw_token_counter(agent_config),
                language=agent_config.language,
                max_input_length=agent_config.running.max_input_length,
                compact_ratio=cc.memory_compact_ratio,
                previous_summary=previous_summary,
                return_dict=True,
                add_thinking_block=cc.compact_with_thinking_block,
            )

        if isinstance(result, str):
            logger.error(
                "compact_memory returned str instead of dict, "
                f"result: {result[:200]}... "
                "Please install the latest reme package.",
            )
            return result

        if not result.get("is_valid", True):
            unique_id = uuid.uuid4().hex[:8]
            filepath = os.path.join(
                agent_config.workspace_dir,
                f"compact_invalid_{unique_id}.json",
            )
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logger.error(
                    f"Invalid compact result saved to {filepath}. "
                    f"user_msg: {result.get('user_message', '')[:200]}..., "
                    "history_compact: "
                    f"{result.get('history_compact', '')[:200]}...",
                )
                logger.error(
                    "Please upload the log: "
                    "https://github.com/agentscope-ai/CoPaw/issues",
                )
            except Exception as _e:
                logger.error(f"Failed to save invalid compact result: {_e}")
            return ""

        return result.get("history_compact", "")

    async def summary_memory(self, messages: list[Msg], **_kwargs) -> str:
        """Generate a comprehensive summary of the given messages."""
        self._prepare_model_formatter()

        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.context_compact

        set_current_workspace_dir(Path(self.working_dir))
        recent_max_bytes = (
            agent_config.running.tool_result_compact.recent_max_bytes
        )
        set_current_recent_max_bytes(recent_max_bytes)

        return await self._reme.summary_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
            as_token_counter=get_copaw_token_counter(agent_config),
            toolkit=self.summary_toolkit,
            language=agent_config.language,
            max_input_length=agent_config.running.max_input_length,
            compact_ratio=cc.memory_compact_ratio,
            timezone=load_config().user_timezone or None,
            add_thinking_block=cc.compact_with_thinking_block,
        )

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """Search stored memories for relevant content."""
        self._warn_if_version_mismatch()
        if self._reme is None or not getattr(self._reme, "_started", False):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="ReMe is not started, report github issue!",
                    ),
                ],
            )
        return await self._reme.memory_search(
            query=query,
            max_results=max_results,
            min_score=min_score,
        )

    def get_in_memory_memory(self, **_kwargs) -> "ReMeInMemoryMemory | None":
        """Retrieve the in-memory memory object with token counting support."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        agent_config = load_agent_config(self.agent_id)
        return self._reme.get_in_memory_memory(
            as_token_counter=get_copaw_token_counter(agent_config),
        )
