"""PowerContext-backed QwenPaw memory manager."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...config.config import load_agent_config
from .base_memory_manager import BaseMemoryManager, memory_registry
from .powercontext_client import PowerContextConfig, PowerContextMemoryClient
from .powercontext_prompts import POWERCONTEXT_MEMORY_GUIDANCE_EN, POWERCONTEXT_MEMORY_GUIDANCE_ZH

logger = logging.getLogger(__name__)


@memory_registry.register("powercontext")
class PowerContextMemoryManager(BaseMemoryManager):
    def __init__(self, working_dir: str, agent_id: str) -> None:
        super().__init__(working_dir, agent_id)
        self._client: PowerContextMemoryClient | None = None
        self._config = None
        self._pending: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        cfg = load_agent_config(self.agent_id).running.powercontext_memory_config
        self._config = cfg
        if cfg is None or not cfg.base_url.strip():
            logger.warning("PowerContext is not configured; backend disabled")
            return
        try:
            self._client = PowerContextMemoryClient(PowerContextConfig(
                base_url=cfg.base_url.strip(), token=cfg.token.strip(),
                scope_id=cfg.scope_id.strip() or f"agent:{self.agent_id}", timeout=cfg.timeout,
            ))
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
        return load_agent_config(self.agent_id).running.powercontext_memory_config

    def get_memory_prompt(self) -> str:
        language = getattr(load_agent_config(self.agent_id), "language", "zh") or "zh"
        return POWERCONTEXT_MEMORY_GUIDANCE_ZH if language == "zh" else POWERCONTEXT_MEMORY_GUIDANCE_EN

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        return [self.memory_search]

    def get_auto_memory_interval(self) -> int:
        return 1

    async def auto_memory_search(self, messages: list[Msg] | Msg, **kwargs: Any) -> dict | None:
        del kwargs
        if self._client is None or not getattr(self._config.auto_memory_search_config, "enabled", True):
            return None
        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None
        result = await self.memory_search(query, getattr(self._config.auto_memory_search_config, "max_results", 3))
        text = self._chunk_text(result)
        if not text or text == "No relevant memories found.":
            return None
        return {
            "query": query,
            "text": text,
            "msg": msgs + [self._build_auto_memory_search_msg(query=query, max_results=3, text=text)],
        }

    async def auto_memory(self, all_messages: list[Msg], **kwargs: Any) -> None:
        del kwargs
        if self._client is None:
            return
        user = [m.get_text_content().strip() for m in all_messages if m.role == "user" and m.get_text_content().strip()]
        assistant = [m.get_text_content().strip() for m in all_messages if m.role == "assistant" and m.get_text_content().strip()]
        if not user:
            return
        text = "用户目标/输入:\n" + "\n".join(user[-3:])
        if assistant:
            text += "\n\nAgent结果:\n" + "\n".join(assistant[-2:])
        self._schedule_remember("task_state", text[:8000])

    async def summarize(self, messages: list[Msg], **kwargs: Any) -> str:
        await self.auto_memory(messages, **kwargs)
        return ""

    async def memory_search(self, query: str, max_results: int = 5, min_score: float = 0.0) -> ToolChunk:
        parts: list[str] = []
        if self._client is not None:
            try:
                for hit in await self._client.search(query=query, limit=max_results):
                    score = float(hit.get("score", 0.0))
                    text = hit.get("text", "")
                    if text and score >= min_score:
                        parts.append(f"[{len(parts)+1}] (powercontext, score: {score:.2f})\n{text}")
            except Exception as exc:
                logger.warning("PowerContext memory search failed: %s", exc)
        return ToolChunk(is_last=True, state=ToolResultState.SUCCESS, content=[TextBlock(type="text", text="\n\n".join(parts) or "No relevant memories found.")])

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
        return "\n".join(str(getattr(block, "text", "")) for block in chunk.content or [] if getattr(block, "text", ""))
