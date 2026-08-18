# -*- coding: utf-8 -*-
"""PowerContext-backed QwenPaw memory manager."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...config.config import PowerContextMemoryConfig, load_agent_config
from .base_memory_manager import BaseMemoryManager, memory_registry
from .powercontext_client import (
    PowerContextConfig,
    PowerContextMemoryClient,
    truncate_utf8_text,
)
from .powercontext_prompts import (
    POWERCONTEXT_MEMORY_GUIDANCE_EN,
    POWERCONTEXT_MEMORY_GUIDANCE_ZH,
)

logger = logging.getLogger(__name__)


@memory_registry.register("powercontext")
class PowerContextMemoryManager(BaseMemoryManager):
    def __init__(self, working_dir: str, agent_id: str) -> None:
        super().__init__(working_dir, agent_id)
        self._client: PowerContextMemoryClient | None = None
        self._config: PowerContextMemoryConfig | None = None
        self._pending: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        cfg = load_agent_config(
            self.agent_id,
        ).running.powercontext_memory_config
        self._config = cfg
        if cfg is None or not cfg.base_url.strip():
            logger.warning("PowerContext is not configured; backend disabled")
            return
        try:
            self._client = PowerContextMemoryClient(
                PowerContextConfig(
                    base_url=cfg.base_url.strip(),
                    token=cfg.token.strip(),
                    scope_id=cfg.scope_id.strip() or f"agent:{self.agent_id}",
                    timeout=cfg.timeout,
                ),
            )
        except Exception as exc:
            logger.warning("PowerContext initialization failed: %s", exc)
            self._client = None

    async def close(self) -> bool:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
            self._pending.clear()
        client, self._client = self._client, None
        if client is None:
            return True
        try:
            await client.close()
            return True
        except Exception:
            logger.exception("PowerContext close failed")
            return False

    def get_memory_config(self) -> Any:
        return load_agent_config(
            self.agent_id,
        ).running.powercontext_memory_config

    def get_memory_prompt(self) -> str:
        language = (
            getattr(load_agent_config(self.agent_id), "language", "zh") or "zh"
        )
        return (
            POWERCONTEXT_MEMORY_GUIDANCE_ZH
            if language == "zh"
            else POWERCONTEXT_MEMORY_GUIDANCE_EN
        )

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        return [self.memory_search, self.memory_remember]

    def get_auto_memory_interval(self) -> int:
        return 1

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict | None:
        del agent_name
        del kwargs
        if self._client is None or not getattr(
            self._config.auto_memory_search_config,
            "enabled",
            True,
        ):
            return None
        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None
        max_results = getattr(
            self._config.auto_memory_search_config,
            "max_results",
            3,
        )
        result = await self.memory_search(
            query,
            max_results,
        )
        if result.state != ToolResultState.SUCCESS:
            return None
        text = self._chunk_text(result)
        if not text or text == "No relevant memories found.":
            return None
        return {
            "query": query,
            "text": text,
            "msg": msgs
            + [
                self._build_auto_memory_search_msg(
                    query=query,
                    max_results=max_results,
                    text=text,
                ),
            ],
        }

    async def auto_memory(
        self,
        all_messages: list[Msg],
        **kwargs: Any,
    ) -> None:
        del kwargs
        if self._client is None:
            return
        all_messages = self._messages_without_auto_memory_search(all_messages)
        user = [
            m.get_text_content().strip()
            for m in all_messages
            if m.role == "user" and m.get_text_content().strip()
        ]
        assistant = [
            m.get_text_content().strip()
            for m in all_messages
            if m.role == "assistant" and m.get_text_content().strip()
        ]
        if not user:
            return
        text = "用户目标/输入:\n" + "\n".join(user[-3:])
        if assistant:
            text += "\n\nAgent结果:\n" + "\n".join(assistant[-2:])
        self._schedule_remember("task_state", truncate_utf8_text(text))

    async def summarize(self, messages: list[Msg], **kwargs: Any) -> str:
        await self.auto_memory(messages, **kwargs)
        return ""

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.0,
    ) -> ToolChunk:
        """Search PowerContext memories and include their exact Citation."""
        if self._client is None:
            return self._tool_error("PowerContext is not configured.")

        parts: list[str] = []
        try:
            for hit in await self._client.search(
                query=query,
                limit=max_results,
            ):
                score = float(hit.get("score", 0.0))
                text = hit.get("text", "")
                citation = self._memory_citation(hit)
                if text and score >= min_score:
                    parts.append(
                        self._format_memory_hit(
                            index=len(parts) + 1,
                            score=score,
                            text=text,
                            citation=citation,
                        ),
                    )
        except Exception as exc:
            logger.warning("PowerContext memory search failed: %s", exc)
            return self._tool_error(
                f"PowerContext memory search failed: {exc}",
            )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text="\n\n".join(parts) or "No relevant memories found.",
                ),
            ],
        )

    async def memory_remember(self, kind: str, text: str) -> ToolChunk:
        """Explicitly persist one important memory in PowerContext."""
        if self._client is None:
            return self._tool_error("PowerContext is not configured.")
        if not kind.strip() or not text.strip():
            return self._tool_error("Both kind and text are required.")
        try:
            await self._client.remember(
                kind=kind.strip(),
                text=truncate_utf8_text(text.strip()),
            )
        except Exception as exc:
            logger.warning(
                "PowerContext explicit memory write failed: %s",
                exc,
            )
            return self._tool_error(f"PowerContext memory write failed: {exc}")
        return self._tool_success("Memory saved to PowerContext.")

    def _scope_id(self) -> str:
        return (
            getattr(self._config, "scope_id", None) or f"agent:{self.agent_id}"
        )

    @staticmethod
    def _memory_citation(hit: dict[str, Any]) -> dict[str, Any] | None:
        citation = hit.get("citation") or {}
        memory_ref = citation.get("memory_ref") or {}
        entry_id = citation.get("entry_id")
        entry_version_id = citation.get("entry_version_id")
        family = memory_ref.get("family")
        artifact_id = memory_ref.get("artifact_id")
        revision = memory_ref.get("revision")
        if not entry_id or not entry_version_id:
            return None
        if not family or not artifact_id or not revision:
            return None
        return {
            "memory_ref": {
                "family": family,
                "artifact_id": artifact_id,
                "revision": revision,
            },
            "entry_id": entry_id,
            "entry_version_id": entry_version_id,
        }

    def _format_memory_hit(
        self,
        *,
        index: int,
        score: float,
        text: str,
        citation: dict[str, Any] | None,
    ) -> str:
        if citation is None:
            citation_text = "citation: unavailable"
        else:
            memory_ref = citation["memory_ref"]
            citation_text = (
                f"family: {memory_ref['family']}, "
                f"artifact_id: {memory_ref['artifact_id']}, "
                f"revision: {memory_ref['revision']}, "
                f"entry_id: {citation['entry_id']}, "
                f"entry_version_id: {citation['entry_version_id']}, "
                f"scope: {self._scope_id()}"
            )
        return (
            f"[{index}] (powercontext, score: {score:.2f}, "
            f"{citation_text})\n{text}"
        )

    @staticmethod
    def _tool_success(text: str) -> ToolChunk:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text=text)],
        )

    @staticmethod
    def _tool_error(text: str) -> ToolChunk:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text=text)],
        )

    def _schedule_remember(self, kind: str, text: str) -> None:
        client = self._client
        if client is None:
            return

        async def write() -> None:
            try:
                await client.remember(kind=kind, text=text)
            except Exception as exc:
                logger.warning("PowerContext memory write failed: %s", exc)

        task = asyncio.create_task(write())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    @staticmethod
    def _chunk_text(chunk: ToolChunk) -> str:
        return "\n".join(
            str(getattr(block, "text", ""))
            for block in chunk.content or []
            if getattr(block, "text", "")
        )
