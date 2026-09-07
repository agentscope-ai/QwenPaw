# -*- coding: utf-8 -*-
"""
OpenViking-backed long-term memory for QwenPaw.

This backend participates in QwenPaw's native ``MemoryMiddleware`` lifecycle:
automatic recall happens before model calls and completed turns are persisted
after replies.  Context compression remains a QwenPaw/AgentScope concern.
"""

from __future__ import annotations
import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk
from ...config.config import load_agent_config
from ...constant import WORKING_DIR
from ...exceptions import ConfigurationException as ConfigurationError
from ...utils.io_utils import run_sync_io
from .base_memory_manager import BaseMemoryManager, memory_registry
from .openviking_client import (
    OpenVikingClient,
    OpenVikingClientConfig,
    OpenVikingConfigurationError,
    OpenVikingIdentity,
    OpenVikingServiceError,
)

logger = logging.getLogger(__name__)

NO_MEMORY_RESULTS = "No relevant memories found."
MAX_MEMORY_SEARCH_RESULTS = 20
INSTALLATION_ID_FILE = ".openviking-installation-id"
AUTO_COMMIT_POLICY = {
    "message_count_threshold": 20,
    "idle_timeout_seconds": 300,
    "keep_recent_count": 4,
    "min_commit_interval_seconds": 60,
}

MEMORY_GUIDANCE_EN = """## Long-term memory
OpenViking stores durable memories across chat sessions. Use `memory_search`
before answering questions about earlier decisions, facts, preferences, people,
dates, or unfinished work when the automatically recalled context is not
enough.
"""

MEMORY_GUIDANCE_ZH = """## 长期记忆
OpenViking 保存跨聊天会话的长期记忆。当自动召回的信息不足以回答此前的
决定、事实、偏好、人物、日期或未完成事项时，请使用 `memory_search`。
"""


@memory_registry.register("openviking")
class OpenVikingMemoryManager(BaseMemoryManager):
    """Long-term memory manager backed by OpenViking's REST API."""

    def __init__(self, working_dir: str, agent_id: str) -> None:
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._config: Any | None = None
        self._client: OpenVikingClient | None = None
        self._identity = OpenVikingIdentity("unknown", "unknown")
        self._installation_id = ""
        self._ready_sessions: set[str] = set()
        self._persisted_msg_ids: set[str] = set()

    async def start(self) -> None:
        """Load configuration and validate permanent errors immediately.

        Temporary network failures are fail-open: the client remains alive and
        later turns retry normally. Authentication failures are raised clearly
        so the workspace reports an invalid backend configuration.
        """
        agent_config = await run_sync_io(load_agent_config, self.agent_id)
        self._config = getattr(
            agent_config.running,
            "openviking_memory_config",
            None,
        )
        if self._config is None:
            raise ConfigurationError(
                "OpenViking memory configuration is missing.",
            )

        base_url = str(self._config.base_url or "").strip()
        api_key = str(self._config.api_key or "").strip()
        if not base_url:
            raise ConfigurationError("OpenViking server endpoint is required.")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError(
                "OpenViking server endpoint must be an http(s) URL.",
            )
        if not api_key:
            raise ConfigurationError("OpenViking API key is required.")

        self._installation_id = await run_sync_io(
            self._load_or_create_installation_id,
        )
        self._client = OpenVikingClient(
            OpenVikingClientConfig(
                base_url=base_url,
                api_key=api_key,
                request_timeout=float(self._config.request_timeout),
            ),
        )
        try:
            self._identity = await self._client.resolve_identity()
        except OpenVikingConfigurationError as exc:
            await self._client.close()
            self._client = None
            raise ConfigurationError(str(exc)) from exc
        except OpenVikingServiceError:
            logger.warning(
                "OpenViking is temporarily unavailable during startup; "
                "memory calls will retry and normal conversation remains "
                "enabled.",
                exc_info=True,
            )

    async def close(self) -> bool:
        """Close HTTP resources; writes are awaited in ``auto_memory``."""
        client = self._client
        self._client = None
        if client is None:
            return True
        try:
            await client.close()
            return True
        except Exception:
            logger.exception("OpenViking client close failed")
            return False

    def get_memory_config(self) -> Any:
        """Return the current backend-specific configuration."""
        return load_agent_config(
            self.agent_id,
        ).running.openviking_memory_config

    def get_memory_prompt(self) -> str:
        """Return localized guidance for the explicit memory search tool."""
        language = load_agent_config(self.agent_id).language or "zh"
        return MEMORY_GUIDANCE_ZH if language == "zh" else MEMORY_GUIDANCE_EN

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        """Expose an explicit search in addition to automatic recall."""
        return [self.memory_search]

    def get_auto_memory_interval(self) -> int:
        """Persist each completed external user/assistant turn."""
        return 1

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict | None:
        """Recall a locally revalidated, token-budgeted OpenViking context."""
        del agent_name
        client = self._client
        if client is None:
            return None

        memory_config, estimate_divisor = await run_sync_io(
            self._load_search_config,
        )
        search_config = memory_config.auto_memory_search_config
        if not search_config.enabled:
            return None

        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None
        qwenpaw_session_id = str(kwargs.get("session_id") or "")
        if not qwenpaw_session_id:
            logger.warning(
                "OpenViking auto recall skipped: missing QwenPaw session ID",
            )
            return None

        max_results = max(1, int(search_config.max_results))
        token_budget = int(memory_config.retrieval_token_budget)
        try:
            await self._ensure_identity()
            session_id = self._map_session_id(qwenpaw_session_id)
            result = await client.search_context(
                query=query,
                session_id=session_id,
                max_results=max_results,
                token_budget=token_budget,
            )
        except OpenVikingConfigurationError as exc:
            logger.error(
                "OpenViking automatic recall configuration is invalid: %s",
                exc,
            )
        except OpenVikingServiceError:
            logger.warning(
                "OpenViking automatic recall failed open",
                exc_info=True,
            )
        else:
            text = str(
                result.get("digest") or result.get("rendered") or "",
            ).strip()
            if text:
                max_bytes = max(1, int(token_budget * estimate_divisor))
                text = self._clip_utf8(text, max_bytes)
                assistant_msg = self._build_auto_memory_search_msg(
                    query=query,
                    max_results=max_results,
                    text=text,
                    estimate_divisor=estimate_divisor,
                )
                return {
                    "query": query,
                    "text": text,
                    "msg": msgs + [assistant_msg],
                }

        return None

    async def auto_memory(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Append one sanitized completed turn and apply the commit policy."""
        client = self._client
        if client is None:
            return ""
        qwenpaw_session_id = str(kwargs.get("session_id") or "")
        if not qwenpaw_session_id:
            logger.warning(
                "OpenViking persistence skipped: missing session ID",
            )
            return ""

        sanitized = self._messages_without_auto_memory_search(messages)
        new_messages = [
            msg
            for msg in sanitized
            if msg.role in {"user", "assistant"}
            and msg.id not in self._persisted_msg_ids
        ]
        payload = self._serialize_completed_turn(new_messages)
        if not payload:
            return ""

        try:
            await self._ensure_identity()
            session_id = self._map_session_id(qwenpaw_session_id)
            await self._ensure_session(session_id)
            await client.add_messages(session_id, payload)
            if self._config.commit_policy == "every_turn":
                await client.commit(session_id)
        except OpenVikingConfigurationError as exc:
            logger.error(
                "OpenViking persistence configuration is invalid: %s",
                exc,
            )
            return ""
        except OpenVikingServiceError:
            logger.warning("OpenViking persistence failed open", exc_info=True)
            return ""

        self._persisted_msg_ids.update(msg.id for msg in new_messages)
        return (
            f"Processed {len(new_messages)} message(s) to OpenViking for "
            f"agent '{self.agent_id}'."
        )

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> ToolChunk:
        """Search long-term memories in the authenticated OpenViking tenant."""
        del kwargs
        query = query.strip()
        if not query:
            return self._tool_chunk("Error: query cannot be empty", ok=False)
        client = self._client
        if client is None:
            return self._tool_chunk("OpenViking is not configured.", ok=False)
        result_limit = min(MAX_MEMORY_SEARCH_RESULTS, max(1, int(max_results)))
        try:
            await self._ensure_identity()
            results = await client.search_memories(
                query=query,
                max_results=result_limit,
            )
        except OpenVikingConfigurationError as exc:
            return self._tool_chunk(str(exc), ok=False)
        except OpenVikingServiceError:
            logger.warning(
                "OpenViking explicit search failed open",
                exc_info=True,
            )
            return self._tool_chunk(
                "OpenViking is temporarily unavailable.",
                ok=False,
            )

        parts: list[str] = []
        for index, item in enumerate(results[:result_limit], start=1):
            uri = str(item.get("uri") or "")
            abstract = str(
                item.get("abstract")
                or item.get("content")
                or item.get("text")
                or "",
            ).strip()
            score = item.get("score")
            score_text = (
                f", score={float(score):.3f}" if score is not None else ""
            )
            parts.append(f"[{index}] {uri}{score_text}\n{abstract}".rstrip())
        return self._tool_chunk("\n\n".join(parts) or NO_MEMORY_RESULTS)

    async def _ensure_session(self, session_id: str) -> None:
        if session_id in self._ready_sessions or self._client is None:
            return
        auto_policy = (
            AUTO_COMMIT_POLICY
            if self._config.commit_policy == "auto"
            else None
        )
        await self._client.ensure_session(
            session_id,
            auto_commit_policy=auto_policy,
        )
        self._ready_sessions.add(session_id)

    async def _ensure_identity(self) -> None:
        """Retry tenant discovery after a fail-open startup outage."""
        if self._identity.account_id != "unknown" or self._client is None:
            return
        self._identity = await self._client.resolve_identity()

    def _load_search_config(self) -> tuple[Any, float]:
        agent_config = load_agent_config(self.agent_id)
        return (
            agent_config.running.openviking_memory_config,
            self._resolve_token_estimate_divisor(agent_config),
        )

    def _map_session_id(self, qwenpaw_session_id: str) -> str:
        """Map namespace + install + agent + chat to one collision-safe ID."""
        material = "\x1f".join(
            (
                self._identity.namespace,
                self._installation_id,
                self.agent_id,
                qwenpaw_session_id,
            ),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]
        return f"qwenpaw-{digest}"

    def _load_or_create_installation_id(self) -> str:
        """Persist a random installation boundary outside agent workspaces."""
        marker = Path(WORKING_DIR) / INSTALLATION_ID_FILE
        try:
            existing = marker.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            existing = ""
        if existing:
            return existing

        marker.parent.mkdir(parents=True, exist_ok=True)
        candidate = uuid4().hex
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return marker.read_text(encoding="utf-8").strip()
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(candidate)
        return candidate

    @staticmethod
    def _serialize_completed_turn(messages: list[Msg]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        current_turn_id = ""
        for msg in messages:
            text = (msg.get_text_content() or "").strip()
            if not text:
                continue
            if msg.role == "user":
                current_turn_id = msg.id
            payload.append(
                {
                    "role": msg.role,
                    "content": text,
                    "turn_id": current_turn_id or msg.id,
                    "message_kind": (
                        "user_query"
                        if msg.role == "user"
                        else "assistant_step"
                    ),
                    "source_message_ids": [msg.id],
                },
            )
        return payload

    @staticmethod
    def _clip_utf8(text: str, max_bytes: int) -> str:
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        suffix = "\n[OpenViking context truncated by QwenPaw]"
        suffix_bytes = suffix.encode("utf-8")
        body_limit = max(0, max_bytes - len(suffix_bytes))
        body = encoded[:body_limit].decode("utf-8", errors="ignore")
        if body:
            return f"{body}{suffix}"
        return suffix_bytes[:max_bytes].decode("utf-8", errors="ignore")

    @staticmethod
    def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
        return ToolChunk(
            is_last=True,
            state=(ToolResultState.SUCCESS if ok else ToolResultState.ERROR),
            content=[TextBlock(type="text", text=text)],
        )
