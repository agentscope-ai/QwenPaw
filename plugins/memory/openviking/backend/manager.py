# -*- coding: utf-8 -*-
"""OpenViking memory backend implemented as a QwenPaw memory plugin."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.memory import (
    AutoMemorySearchOptions,
    BaseMemoryManager,
    MemoryBackendContext,
)

from .client import (
    OpenVikingClient,
    OpenVikingClientConfig,
    OpenVikingConfigurationError,
    OpenVikingIdentity,
    OpenVikingServiceError,
    safe_openviking_exception_summary,
)
from .config import OpenVikingMemoryConfig
from .prompts import (
    OPENVIKING_MEMORY_GUIDANCE_EN,
    OPENVIKING_MEMORY_GUIDANCE_ZH,
    OPENVIKING_NO_MEMORY_RESULTS,
    OPENVIKING_UNTRUSTED_HISTORY_NOTICE,
)

logger = __import__("logging").getLogger(__name__)

MAX_MEMORY_SEARCH_RESULTS = 20
TRUNCATION_MARKER = "\n[OpenViking result truncated by QwenPaw]"
AUTO_COMMIT_POLICY = {
    "message_count_threshold": 20,
    "idle_timeout_seconds": 300,
    "keep_recent_count": 4,
    "min_commit_interval_seconds": 60,
}


def get_or_create_installation_id(host_working_dir: str | Path) -> str:
    """Create a plugin-owned installation boundary with private permissions."""
    root = Path(host_working_dir).expanduser().resolve()
    marker = root / "plugin-state" / "memory-openviking" / "installation-id"
    try:
        existing = marker.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{32}", existing):
            return existing
    except FileNotFoundError:
        pass
    else:
        raise ValueError(f"Invalid OpenViking installation id in {marker}")

    marker.parent.mkdir(parents=True, exist_ok=True)
    generated = uuid.uuid4().hex
    try:
        descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        existing = marker.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", existing):
            raise ValueError(
                f"Invalid OpenViking installation id in {marker}",
            ) from exc
        return existing
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(generated)
    return generated


class OpenVikingMemoryManager(BaseMemoryManager):
    """Long-term memory manager backed by OpenViking's REST API.

    All remote results are treated as untrusted historical material.  The
    manager owns only OpenViking-specific state; generic worker lifecycle is
    deliberately kept in :class:`BaseMemoryManager`.
    """

    def __init__(self, context: MemoryBackendContext) -> None:
        super().__init__(context=context)
        self._config: OpenVikingMemoryConfig | None = None
        self._client: OpenVikingClient | None = None
        self._identity: OpenVikingIdentity | None = None
        self._installation_id = ""
        self._ready_sessions: set[str] = set()
        self._persisted_msg_ids: set[str] = set()
        # A successful append followed by a failed commit is a partial
        # success.  Keep these IDs separate so retrying does not append the
        # same turn again.  OpenViking v0.4.x exposes no idempotency key, so
        # this is the strongest guarantee possible after a known success.
        self._pending_commit_msg_ids: dict[str, set[str]] = {}

    async def start(self) -> None:
        """Read plugin-owned config and prepare a reusable REST client."""
        config = OpenVikingMemoryConfig.model_validate(
            self.context.backend_config,
        )
        self._config = config
        if not config.api_key:
            logger.warning("OpenViking is not configured; backend disabled")
            return
        try:
            self._installation_id = await asyncio.to_thread(
                get_or_create_installation_id,
                self.context.host_working_dir,
            )
            self._client = OpenVikingClient(
                OpenVikingClientConfig(
                    base_url=config.base_url,
                    api_key=config.api_key,
                    request_timeout=config.request_timeout,
                ),
            )
            await self._ensure_identity()
        except OpenVikingConfigurationError as exc:
            await self._close_backend()
            logger.warning(
                "OpenViking configuration is invalid: %s",
                self._safe_exception_summary(exc),
            )
        except OpenVikingServiceError as exc:
            # A transient startup outage must not prevent normal chats.  The
            # client stays open and the first later use re-resolves identity.
            logger.warning(
                "OpenViking is temporarily unavailable at startup: %s",
                self._safe_exception_summary(exc),
            )

    async def _close_backend(self) -> bool:
        """Close HTTP resources after BaseMemoryManager drains its worker."""
        client, self._client = self._client, None
        self._identity = None
        self._ready_sessions.clear()
        if client is None:
            return True
        try:
            await client.close()
            return True
        except Exception as exc:
            logger.warning(
                "OpenViking client close failed: %s",
                self._safe_exception_summary(exc, client=client),
            )
            return False

    def get_memory_prompt(self) -> str:
        if self._client is None:
            return ""
        return (
            OPENVIKING_MEMORY_GUIDANCE_ZH
            if self.context.language == "zh"
            else OPENVIKING_MEMORY_GUIDANCE_EN
        )

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        if self._client is None:
            return []

        @wraps(self.memory_search)
        async def openviking_memory_search(
            query: str,
            max_results: int = 5,
        ) -> ToolChunk:
            return await self.memory_search(query, max_results)

        # Keep the public name stable for model prompts, while making the
        # network boundary visible to the strict governance policy.
        setattr(
            openviking_memory_search,
            "_qwenpaw_policy_name",
            "OpenVikingMemorySearch",
        )
        return [openviking_memory_search]

    def get_auto_memory_interval(self) -> int:
        return 1 if self._client is not None else 0

    async def get_auto_memory_search_options(
        self,
    ) -> AutoMemorySearchOptions | None:
        config = self._config
        if (
            self._client is None
            or config is None
            or not config.auto_memory_search_config.enabled
        ):
            return None
        return AutoMemorySearchOptions(
            max_results=config.auto_memory_search_config.max_results,
            estimate_divisor=self.context.token_estimate_divisor,
        )

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Recall with the actual QwenPaw session supplied by middleware.

        OpenViking's context endpoint needs a session id.  The generic base
        helper intentionally has no session parameter, therefore this small
        plugin override preserves that backend-specific REST contract while
        retaining its synthetic-message format.
        """
        del agent_name
        options = await self.get_auto_memory_search_options()
        session_id = str(kwargs.get("session_id") or "")
        if options is None or not session_id:
            return None
        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None
        max_results = max(1, int(options.max_results))
        result = await self._search_context_for_session(
            query=query,
            qwenpaw_session_id=session_id,
            max_results=max_results,
            estimate_divisor=options.estimate_divisor,
        )
        if result is None or result.state != ToolResultState.SUCCESS:
            return None
        text = self._tool_chunk_text(result).strip()
        if not text or text == OPENVIKING_NO_MEMORY_RESULTS:
            return None
        message = self._build_auto_memory_search_msg(
            query=query,
            max_results=max_results,
            text=text,
            estimate_divisor=options.estimate_divisor,
        )
        return {"query": query, "text": text, "msg": msgs + [message]}

    async def auto_memory(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Append one sanitized turn and retry a known failed commit safely."""
        client = self._client
        session_id = str(kwargs.get("session_id") or "")
        if client is None or not session_id:
            return ""

        sanitized = self._messages_without_auto_memory_search(messages)
        candidates = [
            message
            for message in sanitized
            if message.role in {"user", "assistant"}
            and message.id not in self._persisted_msg_ids
        ]
        try:
            await self._ensure_identity()
            remote_session_id = self._map_session_id(session_id)
            await self._ensure_session(remote_session_id)
            pending = self._pending_commit_msg_ids.setdefault(
                remote_session_id,
                set(),
            )
            # Do not append a turn whose append call already completed before
            # the commit call failed.  See the note in __init__.
            new_messages = [
                message for message in candidates if message.id not in pending
            ]
            payload = self._serialize_completed_turn(new_messages)
            if payload:
                await client.add_messages(remote_session_id, payload)
                new_ids = {message.id for message in new_messages}
                if self._config and self._config.commit_policy == "every_turn":
                    pending.update(new_ids)
                else:
                    self._persisted_msg_ids.update(new_ids)

            if self._config and self._config.commit_policy == "every_turn":
                if pending:
                    await client.commit(remote_session_id)
                    self._persisted_msg_ids.update(pending)
                    pending.clear()
            return (
                f"Processed {len(new_messages)} message(s) to OpenViking for "
                f"agent '{self.agent_id}'."
            )
        except OpenVikingConfigurationError as exc:
            logger.warning(
                "OpenViking persistence configuration is invalid: %s",
                self._safe_exception_summary(exc),
            )
        except OpenVikingServiceError as exc:
            logger.warning(
                "OpenViking persistence failed open: %s",
                self._safe_exception_summary(exc),
            )
        return ""

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> ToolChunk:
        """Search remote long-term memories under an explicit trust notice."""
        del kwargs
        query = query.strip()
        if not query:
            return self._tool_chunk("Error: query cannot be empty", ok=False)
        if self._client is None:
            return self._tool_chunk("OpenViking is not configured.", ok=False)
        limit = min(MAX_MEMORY_SEARCH_RESULTS, max(1, int(max_results)))
        try:
            await self._ensure_identity()
            results = await self._client.search_memories(
                query=query,
                max_results=limit,
            )
        except OpenVikingConfigurationError as exc:
            return self._tool_chunk(
                "OpenViking configuration is invalid: "
                + self._safe_exception_summary(exc),
                ok=False,
            )
        except OpenVikingServiceError as exc:
            logger.warning(
                "OpenViking explicit search failed: %s",
                self._safe_exception_summary(exc),
            )
            return self._tool_chunk(
                "OpenViking is temporarily unavailable.",
                ok=False,
            )

        parts: list[str] = []
        for index, item in enumerate(results[:limit], start=1):
            uri = str(item.get("uri") or "")
            abstract = str(
                item.get("abstract")
                or item.get("content")
                or item.get("text")
                or "",
            ).strip()
            score = item.get("score")
            try:
                score_text = f", score={float(score):.3f}"
            except (TypeError, ValueError):
                score_text = ""
            parts.append(f"[{index}] {uri}{score_text}\n{abstract}".rstrip())
        if not parts:
            return self._tool_chunk(OPENVIKING_NO_MEMORY_RESULTS)
        return self._tool_chunk(
            OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n" + "\n\n".join(parts),
        )

    async def _search_context_for_session(
        self,
        *,
        query: str,
        qwenpaw_session_id: str,
        max_results: int,
        estimate_divisor: float,
    ) -> ToolChunk | None:
        client = self._client
        config = self._config
        if client is None or config is None:
            return None
        try:
            await self._ensure_identity()
            result = await client.search_context(
                query=query,
                session_id=self._map_session_id(qwenpaw_session_id),
                max_results=max_results,
                token_budget=config.retrieval_token_budget,
            )
        except OpenVikingConfigurationError as exc:
            logger.warning(
                "OpenViking automatic recall configuration is invalid: %s",
                self._safe_exception_summary(exc),
            )
            return None
        except OpenVikingServiceError as exc:
            logger.warning(
                "OpenViking automatic recall failed open: %s",
                self._safe_exception_summary(exc),
            )
            return None
        text = str(
            result.get("digest") or result.get("rendered") or "",
        ).strip()
        if not text:
            return None
        max_bytes = max(
            0,
            int(config.retrieval_token_budget * estimate_divisor),
        )
        text = self._clip_utf8(
            OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n" + text,
            self._auto_search_result_budget(
                query=query,
                max_results=max_results,
                max_context_bytes=max_bytes,
                estimate_divisor=estimate_divisor,
            ),
        )
        if not text:
            return None
        return self._tool_chunk(text)

    async def _ensure_session(self, session_id: str) -> None:
        if session_id in self._ready_sessions or self._client is None:
            return
        policy = (
            AUTO_COMMIT_POLICY
            if self._config and self._config.commit_policy == "auto"
            else None
        )
        await self._client.ensure_session(
            session_id,
            auto_commit_policy=policy,
        )
        self._ready_sessions.add(session_id)

    async def _ensure_identity(self) -> None:
        if self._identity is not None or self._client is None:
            return
        self._identity = await self._client.resolve_identity()

    def _map_session_id(self, qwenpaw_session_id: str) -> str:
        identity = self._identity or OpenVikingIdentity("unknown", "unknown")
        material = "\x1f".join(
            (
                identity.namespace,
                self._installation_id,
                self.agent_id,
                qwenpaw_session_id,
            ),
        )
        return (
            "qwenpaw-"
            + hashlib.sha256(
                material.encode("utf-8"),
            ).hexdigest()[:40]
        )

    @staticmethod
    def _serialize_completed_turn(messages: list[Msg]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        current_turn_id = ""
        for message in messages:
            text = (message.get_text_content() or "").strip()
            if not text:
                continue
            if message.role == "user":
                current_turn_id = message.id
            payload.append(
                {
                    "role": message.role,
                    "content": text,
                    "turn_id": current_turn_id or message.id,
                    "message_kind": (
                        "user_query"
                        if message.role == "user"
                        else "assistant_step"
                    ),
                    "source_message_ids": [message.id],
                },
            )
        return payload

    @staticmethod
    def _clip_utf8(text: str, max_bytes: int) -> str:
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        suffix = TRUNCATION_MARKER.encode("utf-8")
        body_limit = max(0, max_bytes - len(suffix))
        body = encoded[:body_limit].decode("utf-8", errors="ignore")
        if body:
            return body + TRUNCATION_MARKER
        return suffix[:max_bytes].decode("utf-8", errors="ignore")

    @staticmethod
    def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
            content=[TextBlock(type="text", text=text)],
        )

    def _safe_exception_summary(
        self,
        exc: BaseException,
        *,
        client: Any | None = None,
    ) -> str:
        source = client if client is not None else self._client
        api_key = str(getattr(getattr(source, "config", None), "api_key", ""))
        return safe_openviking_exception_summary(exc, api_key=api_key)

    def _auto_search_result_budget(
        self,
        *,
        query: str,
        max_results: int,
        max_context_bytes: int,
        estimate_divisor: float,
    ) -> int:
        """Reserve synthetic message metadata inside the configured budget."""
        message = self._build_auto_memory_search_msg(
            query=query,
            max_results=max_results,
            text="",
            estimate_divisor=estimate_divisor,
        )
        overhead = 0
        for block in message.content:
            overhead += len(str(getattr(block, "text", "")).encode("utf-8"))
            overhead += len(
                str(getattr(block, "thinking", "")).encode("utf-8"),
            )
            overhead += len(
                (
                    str(getattr(block, "name", ""))
                    + str(getattr(block, "input", ""))
                ).encode("utf-8"),
            )
        return max(0, max_context_bytes - overhead)
