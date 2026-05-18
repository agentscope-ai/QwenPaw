# -*- coding: utf-8 -*-
"""ADBPG Memory Manager for QwenPaw agents.

Provides long-term memory backed by AnalyticDB for PostgreSQL (ADBPG).
Context management (compaction, tool result pruning) is handled by
LightContextManager — this class only manages long-term memory storage
and retrieval.
"""
import asyncio
import json
import logging
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolUseBlock
from agentscope.tool import ToolResponse

from .adbpg_client import (
    ADBPGConfig,
    ADBPGMemoryClient,
    ConfigurationError,
    reset_configured_connections,
)
from .adbpg_prompts import ADBPG_MEMORY_GUIDANCE_EN, ADBPG_MEMORY_GUIDANCE_ZH
from .base_memory_manager import BaseMemoryManager, memory_registry
from ...config.config import load_agent_config

logger = logging.getLogger(__name__)


@memory_registry.register("adbpg")
class ADBPGMemoryManager(BaseMemoryManager):
    """ADBPG-backed long-term memory manager.

    Delegates storage and retrieval to AnalyticDB for PostgreSQL.
    Context management is handled by LightContextManager.
    """

    def __init__(self, working_dir: str, agent_id: str) -> None:
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._adbpg_config = None
        self._client: ADBPGMemoryClient | None = None
        self._effective_agent_id: str = "shared"
        self._effective_user_id: str = "shared"
        self._effective_run_id: str = "shared"
        self._auto_retrieved: bool = False
        self._persisted_msg_ids: set[str] = set()

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
            api_mode = getattr(cfg, "api_mode", "sql")
            if api_mode == "rest":
                if not cfg.rest_api_key:
                    raise ConfigurationError(
                        "ADBPG REST API key not configured.",
                    )
            else:
                if not cfg.host:
                    raise ConfigurationError("ADBPG host not configured.")

            config = ADBPGConfig(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=cfg.password,
                dbname=cfg.dbname,
                llm_model=cfg.llm_model,
                llm_api_key=cfg.llm_api_key,
                llm_base_url=cfg.llm_base_url,
                embedding_model=cfg.embedding_model,
                embedding_api_key=cfg.embedding_api_key,
                embedding_base_url=cfg.embedding_base_url,
                embedding_dims=cfg.embedding_dims,
                search_timeout=cfg.search_timeout,
                pool_minconn=cfg.pool_minconn,
                pool_maxconn=cfg.pool_maxconn,
                memory_isolation=cfg.memory_isolation,
                api_mode=api_mode,
                rest_api_key=cfg.rest_api_key,
                rest_base_url=cfg.rest_base_url,
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
            reset_configured_connections()
            client = ADBPGMemoryClient(config)
            client.configure()
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
        self._client = None
        return True

    def get_memory_prompt(self, language: str = "zh") -> str:
        """Return ADBPG memory guidance prompt."""
        prompts = {
            "zh": ADBPG_MEMORY_GUIDANCE_ZH,
            "en": ADBPG_MEMORY_GUIDANCE_EN,
        }
        return prompts.get(language, ADBPG_MEMORY_GUIDANCE_EN)

    def list_memory_tools(self) -> list[Callable[..., ToolResponse]]:
        """Return memory tools exposed to the agent."""
        return [self.memory_search]

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
            self._fire_and_forget_add([single])
        return (
            f"Persisted {len(user_messages)} user message(s) "
            f"to ADBPG for agent '{self.agent_id}'."
        )

    async def retrieve(
        self,
        messages: list[Msg] | Msg,
        **_kwargs,
    ) -> dict | None:
        """Auto-retrieve relevant memories from ADBPG.

        Returns a dict with injected tool_use/tool_result messages,
        or None if no relevant memory found.
        """
        if self._client is None:
            return None

        msgs: list[Msg] = (
            [messages] if isinstance(messages, Msg) else list(messages)
        )

        # Extract query from latest user message
        query = ""
        for msg in reversed(msgs):
            if msg.role == "user":
                query = (
                    msg.get_text_content()
                    if hasattr(msg, "get_text_content")
                    else str(msg.content)
                )
                break

        if not query or len(query.strip()) < 2:
            return None

        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self._client.search_memory(
                    query=query,
                    user_id=self._effective_user_id,
                    agent_id=self._effective_agent_id,
                    limit=3,
                ),
            )
            if not results:
                return None

            parts: list[str] = []
            for item in results:
                content = item.get("content", item.get("memory", ""))
                if content:
                    parts.append(f"- {content}")
            if not parts:
                return None

            text_content = "[Long-term Memory from ADBPG]\n" + "\n".join(parts)

            # Construct tool_use + tool_result message pair
            _id = uuid.uuid4().hex
            tool_input = {"query": query, "max_results": 3, "min_score": 0.1}
            agent_name = _kwargs.get("agent_name", "")

            assistant_msg = Msg(
                name=agent_name,
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Searching long-term memory...",
                    ),
                    ToolUseBlock(
                        type="tool_use",
                        id=_id,
                        name="memory_search",
                        input=tool_input,
                        raw_input=json.dumps(tool_input, ensure_ascii=False),
                    ),
                ],
            )

            tool_result_msg = Msg(
                name=agent_name,
                role="system",
                content=[
                    ToolResultBlock(
                        type="tool_result",
                        id=_id,
                        name="memory_search",
                        output=[TextBlock(type="text", text=text_content)],
                    ),
                ],
            )

            return {"msg": msgs + [assistant_msg, tool_result_msg]}

        except Exception as e:
            logger.warning(f"Auto-retrieve ADBPG memories failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Auto-memory lifecycle methods (PR #4204 interface)
    # ------------------------------------------------------------------

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs,
    ) -> dict | None:
        """Auto-search ADBPG memory before replying (pre_reply phase).

        ADBPG backend always performs auto-retrieval when client is available.
        """
        if self._client is None:
            return None
        return await self.retrieve(messages, agent_name=agent_name)

    async def summarize_when_compact(
        self,
        messages: list[Msg],
        **kwargs,
    ) -> None:
        """Persist compacted messages to ADBPG.

        Always triggers since ADBPG server-side handles fact extraction.
        """
        if not messages:
            return
        await self.summarize(messages)

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
            self._fire_and_forget_add([single])

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
    ) -> ToolResponse:
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
            `ToolResponse`:
                Search results with source and content.
        """
        parts: list[str] = []

        # Source 1: ADBPG semantic search
        if self._client is not None:
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: self._client.search_memory(
                        query=query,
                        user_id=self._effective_user_id,
                        agent_id=self._effective_agent_id,
                        limit=max_results,
                    ),
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
            local_hits = self._search_local_memory_files(
                query,
                max_results=max(max_results - len(parts), 3),
            )
            for filepath, snippet in local_hits:
                idx = len(parts) + 1
                parts.append(f"[{idx}] (file: {filepath})\n{snippet}")
        except Exception as e:
            logger.warning("Local memory file search failed: %s", e)

        if not parts:
            return ToolResponse(
                content=[
                    TextBlock(type="text", text="No relevant memories found."),
                ],
            )

        return ToolResponse(
            content=[
                TextBlock(type="text", text="\n\n".join(parts[:max_results])),
            ],
        )

    # ------------------------------------------------------------------
    # Session reset
    # ------------------------------------------------------------------

    def reset_turn_state(self) -> None:
        """Reset per-turn state.

        Call at the start of each conversation turn.
        """
        self._auto_retrieved = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

    def _fire_and_forget_add(self, user_messages: list[dict]) -> None:
        """Store messages to ADBPG in a background daemon thread."""
        if self._client is None:
            return
        agent_id = self._effective_agent_id
        user_id = self._effective_user_id
        run_id = self._effective_run_id
        client = self._client

        def _do_add() -> None:
            try:
                client.add_memory(
                    messages=user_messages,
                    user_id=user_id,
                    run_id=run_id,
                    agent_id=agent_id,
                )
            except Exception as e:
                logger.error(f"Background memory add failed: {e}")

        thread = threading.Thread(target=_do_add, daemon=True)
        thread.start()

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
