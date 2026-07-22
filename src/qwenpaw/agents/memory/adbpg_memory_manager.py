# -*- coding: utf-8 -*-
"""ADBPG Memory Manager for QwenPaw agents.

Provides long-term memory backed by AnalyticDB for PostgreSQL (ADBPG).
Context compaction is handled natively by AgentScope's
``Agent.compress_context()``; tool result pruning is handled by
``ToolResultPruningMiddleware``. This class only manages long-term
memory storage and retrieval.
"""
import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentscope.message import Msg, TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from .adbpg_client import (
    ADBPGConfig,
    ADBPGMemoryClient,
)
from .adbpg_prompts import ADBPG_MEMORY_GUIDANCE_EN, ADBPG_MEMORY_GUIDANCE_ZH
from .base_memory_manager import BaseMemoryManager, memory_registry
from ...config.config import load_agent_config
from ...exceptions import ConfigurationException as ConfigurationError

logger = logging.getLogger(__name__)


@memory_registry.register("adbpg")
class ADBPGMemoryManager(BaseMemoryManager):
    """ADBPG-backed long-term memory manager.

    Delegates storage and retrieval to AnalyticDB for PostgreSQL.
    Context compaction and tool result pruning are handled by the
    agent's native compression and ``ToolResultPruningMiddleware``.
    """

    def __init__(self, working_dir: str, agent_id: str) -> None:
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._adbpg_config = None
        self._client: ADBPGMemoryClient | None = None
        self._effective_agent_id: str = "shared"
        self._effective_user_id: str = "shared"
        self._effective_run_id: str = "shared"
        self._persisted_msg_ids: set[str] = set()
        self._pending_add_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Abstract methods (required)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize ADBPGMemoryClient from agent config."""
        agent_config = load_agent_config(self.agent_id)
        self._adbpg_config = getattr(
            agent_config.running,
            "adbpg_memory_config",
            None,
        )

        if not self._adbpg_config:
            logger.warning(
                "No adbpg_memory_config for agent '%s'. "
                "Long-term memory DISABLED.",
                self.agent_id,
            )
            self._client = None
            return

        # Resolve isolation modes
        cfg = self._adbpg_config
        self._effective_agent_id = (
            self.agent_id if cfg.memory_isolation else "shared"
        )

        try:
            if not cfg.rest_base_url.strip():
                raise ConfigurationError("ADBPG REST base URL not configured.")
            if not cfg.rest_api_key.strip():
                raise ConfigurationError("ADBPG REST API key not configured.")

            config = ADBPGConfig(
                search_timeout=cfg.search_timeout,
                rest_api_key=cfg.rest_api_key.strip(),
                rest_base_url=cfg.rest_base_url.strip(),
            )
        except Exception as e:
            logger.warning(
                "ADBPG config incomplete for agent '%s': %s. "
                "Long-term memory DISABLED.",
                self.agent_id,
                e,
            )
            self._client = None
            return

        try:
            client = ADBPGMemoryClient(config)
            self._client = client
            logger.info(
                "ADBPGMemoryManager started for agent '%s'.",
                self.agent_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to connect to ADBPG for agent '%s': %s. "
                "Long-term memory DISABLED.",
                self.agent_id,
                e,
            )
            self._client = None

    async def close(self) -> bool:
        """Clean up resources."""
        if self._pending_add_tasks:
            await asyncio.gather(
                *list(self._pending_add_tasks),
                return_exceptions=True,
            )
            self._pending_add_tasks.clear()

        client = self._client
        self._client = None
        if client is None:
            return True
        try:
            await client.close()
            return True
        except Exception:
            logger.exception("ADBPG close failed")
            return False

    def get_memory_config(self) -> Any:
        """Return ADBPG memory configuration."""
        agent_config = load_agent_config(self.agent_id)
        return agent_config.running.adbpg_memory_config

    def get_memory_prompt(self) -> str:
        """Return ADBPG memory guidance prompt."""
        agent_config = load_agent_config(self.agent_id)
        language = getattr(agent_config, "language", "zh") or "zh"
        prompts = {
            "zh": ADBPG_MEMORY_GUIDANCE_ZH,
            "en": ADBPG_MEMORY_GUIDANCE_EN,
        }
        return prompts.get(language, ADBPG_MEMORY_GUIDANCE_EN)

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        """Return memory tools exposed to the agent."""
        return [self.memory_search]

    def get_auto_memory_interval(self) -> int:
        """Persist ADBPG user messages every turn."""
        return 1

    # ------------------------------------------------------------------
    # Optional methods (override)
    # ------------------------------------------------------------------

    async def summarize(self, messages: list[Msg], **_kwargs) -> str:
        """Persist user messages to ADBPG via fire-and-forget."""
        if self._client is None:
            return ""
        user_messages = self._filter_user_messages(messages)
        if not user_messages:
            return ""
        for single in user_messages:
            self._schedule_add([single])
        return (
            f"Persisted {len(user_messages)} user message(s) "
            f"to ADBPG for agent '{self.agent_id}'."
        )

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict | None:
        """Auto-search ADBPG memory before the model call."""
        del agent_name
        del kwargs
        if self._client is None:
            return None

        memory_cfg = self.get_memory_config()
        search_cfg = getattr(memory_cfg, "auto_memory_search_config", None)
        if not getattr(search_cfg, "enabled", False):
            return None

        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None

        max_results = max(1, int(getattr(search_cfg, "max_results", 3)))
        result = await self.memory_search(
            query=query,
            max_results=max_results,
        )
        text = self._tool_chunk_text(result).strip()
        if not text or text == "No relevant memories found.":
            return None

        assistant_msg = self._build_auto_memory_search_msg(
            query=query,
            max_results=max_results,
            text=text,
        )
        return {
            "query": query,
            "text": text,
            "msg": msgs + [assistant_msg],
        }

    async def auto_memory(
        self,
        all_messages: list[Msg],
        **kwargs,
    ) -> None:
        """Persist new user messages to ADBPG every turn.

        ADBPG server-side handles fact extraction, so we persist on every
        turn (interval=1) without filtering by interval config.
        """
        if self._client is None:
            return

        all_messages = self._messages_without_auto_memory_search(all_messages)

        # Only persist messages not already sent
        new_messages = [
            msg
            for msg in all_messages
            if msg.role == "user" and msg.id not in self._persisted_msg_ids
        ]
        if not new_messages:
            return

        user_messages = self._filter_user_messages(new_messages)
        for single in user_messages:
            self._schedule_add([single])

        # Track persisted message IDs
        for msg in new_messages:
            self._persisted_msg_ids.add(msg.id)

    # ------------------------------------------------------------------
    # Tool function
    # ------------------------------------------------------------------

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolChunk:
        """Search memories from both ADBPG and local memory files.

        Combines results from two sources:
        1. ADBPG database (semantic search)
        2. Local MEMORY.md and memory/*.md files (keyword matching)

        Args:
            query (`str`):
                The semantic search query.
            max_results (`int`, optional):
                Maximum number of results. Defaults to 5.
            min_score (`float`, optional):
                Minimum relevance score. Defaults to 0.1.

        Returns:
            `ToolChunk`:
                Search results with source and content.
        """
        parts: list[str] = []

        # Source 1: ADBPG semantic search
        if self._client is not None:
            try:
                results = await self._client.search_memory(
                    query=query,
                    user_id=self._effective_user_id,
                    agent_id=self._effective_agent_id,
                    limit=max_results,
                )
                for item in results or []:
                    content = item.get("content", item.get("memory", ""))
                    score = item.get("score", 0)
                    if score < min_score or not content:
                        continue
                    idx = len(parts) + 1
                    parts.append(
                        f"[{idx}] (adbpg, score: {score:.2f})\n{content}",
                    )
            except Exception as e:
                logger.warning("ADBPG memory search failed: %s", e)

        # Source 2: Local memory files (keyword match)
        try:
            loop = asyncio.get_running_loop()
            local_hits = await loop.run_in_executor(
                None,
                lambda: self._search_local_memory_files(
                    query,
                    max_results=max(max_results - len(parts), 3),
                ),
            )
            for filepath, snippet in local_hits:
                idx = len(parts) + 1
                parts.append(f"[{idx}] (file: {filepath})\n{snippet}")
        except Exception as e:
            logger.warning("Local memory file search failed: %s", e)

        if not parts:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.SUCCESS,
                content=[
                    TextBlock(type="text", text="No relevant memories found."),
                ],
            )

        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(type="text", text="\n\n".join(parts[:max_results])),
            ],
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_chunk_text(chunk: ToolChunk) -> str:
        parts = []
        for block in chunk.content or []:
            text = getattr(block, "text", "")
            if text:
                parts.append(str(text))
        return "\n".join(parts)

    @staticmethod
    def _filter_user_messages(messages: list[Msg]) -> list[dict]:
        """Extract role=user messages for ADBPG storage."""
        return [
            {
                "role": "user",
                "content": (
                    msg.get_text_content()
                    if hasattr(msg, "get_text_content")
                    else str(msg.content)
                ),
            }
            for msg in messages
            if msg.role == "user"
        ]

    def _schedule_add(self, user_messages: list[dict]) -> None:
        """Schedule async memory persistence without blocking the reply."""
        if self._client is None:
            return
        agent_id = self._effective_agent_id
        user_id = self._effective_user_id
        run_id = self._effective_run_id
        client = self._client

        async def _do_add() -> None:
            try:
                await client.add_memory(
                    messages=user_messages,
                    user_id=user_id,
                    run_id=run_id,
                    agent_id=agent_id,
                )
            except Exception as e:
                logger.error(f"Background memory add failed: {e}")

        task = asyncio.create_task(_do_add())
        self._pending_add_tasks.add(task)
        task.add_done_callback(self._pending_add_tasks.discard)

    def _search_local_memory_files(
        self,
        query: str,
        max_results: int = 3,
    ) -> list[tuple[str, str]]:
        """Keyword-search MEMORY.md and memory/*.md files."""
        workspace = Path(self.working_dir).expanduser()
        candidates: list[Path] = []

        memory_md = workspace / "MEMORY.md"
        if memory_md.is_file():
            candidates.append(memory_md)

        memory_dir = workspace / "memory"
        if memory_dir.is_dir():
            candidates.extend(sorted(memory_dir.glob("*.md")))

        if not candidates:
            return []

        tokens = {t for t in query.lower().split() if len(t) >= 2}
        if not tokens:
            return []

        scored: list[tuple[float, str, str]] = []
        for filepath in candidates:
            try:
                text = filepath.read_text(encoding="utf-8")
            except Exception:
                continue
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            for para in paragraphs:
                lower = para.lower()
                hits = sum(1 for t in tokens if t in lower)
                if hits == 0:
                    continue
                score = hits / len(tokens)
                rel_path = str(filepath.relative_to(workspace))
                snippet = para if len(para) <= 500 else para[:500] + "..."
                scored.append((score, rel_path, snippet))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(path, snippet) for _, path, snippet in scored[:max_results]]
