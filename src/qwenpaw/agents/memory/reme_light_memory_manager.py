# -*- coding: utf-8 -*-
"""ReMe4-backed memory manager for agents.

The public class and registry key keep the historical ``ReMeLight`` naming so
existing agent configs continue to work, but the implementation delegates to
ReMe4's application/job framework.
"""

import logging
from contextlib import suppress
from typing import Any, TYPE_CHECKING

from agentscope.message import Msg, TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry
from .prompts import MEMORY_GUIDANCE_EN, MEMORY_GUIDANCE_ZH
from .reme_config import get_reme_app_config
from ..model_factory import create_model_and_formatter
from ...config import load_config
from ...config.config import load_agent_config

if TYPE_CHECKING:
    from reme import ReMe

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 50
NO_MEMORY_RESULTS = "(no memory results)"


def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


@memory_registry.register("remelight")
class ReMeLightMemoryManager(BaseMemoryManager):
    """Memory manager backed by ReMe4.

    ReMe4 uses the QwenPaw workspace root as its vault.  Daily memory,
    digest memory, search, auto-memory, and auto-dream are executed through
    ReMe4 jobs.
    """

    def __init__(self, working_dir: str, agent_id: str):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme: "ReMe | None" = None
        self._persisted_reply_ids: set[str] = set()
        logger.info(
            "ReMeLightMemoryManager init: agent_id=%s working_dir=%s",
            agent_id,
            working_dir,
        )

        try:
            from reme import ReMe as ReMeApp  # type: ignore

            agent_config = load_agent_config(self.agent_id)
            global_config = load_config()
            self._reme = ReMeApp(
                **get_reme_app_config(
                    working_dir=self.working_dir,
                    agent_config=agent_config,
                    user_timezone=getattr(
                        global_config,
                        "user_timezone",
                        None,
                    ),
                ),
            )
        except Exception as exc:
            logger.warning("ReMe4 import failed; memory disabled: %s", exc)

    async def start(self) -> None:
        """Start the embedded ReMe4 application."""
        if self._reme is None:
            return
        if getattr(self._reme, "is_started", False):
            return

        await self._update_qwenpaw_model()
        try:
            await self._reme.start()
        except Exception:
            try:
                await self._reme.close()
            except Exception:
                logger.exception("ReMe4 cleanup after failed start failed")
            raise

        logger.info(
            "ReMe4 memory manager started for agent '%s'",
            self.agent_id,
        )

    async def close(self) -> bool:
        """Close ReMe4 and cleanup background summary worker state."""
        logger.info(
            "ReMeLightMemoryManager closing: agent_id=%s",
            self.agent_id,
        )

        worker = self._worker_task
        if worker is not None and not worker.done():
            worker.cancel()
            with suppress(BaseException):
                await worker

        if self._reme is not None:
            try:
                await self._reme.close()
            except Exception:
                logger.exception("ReMe4 close failed")
                return False

        self._reme = None
        return True

    def get_memory_prompt(self, language: str = "zh") -> str:
        """Return memory guidance for system prompt injection."""
        prompts = {"zh": MEMORY_GUIDANCE_ZH, "en": MEMORY_GUIDANCE_EN}
        return prompts.get(language, MEMORY_GUIDANCE_EN)

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        return [self.memory_search]

    async def _update_qwenpaw_model(self) -> None:
        """Reuse QwenPaw's active model in ReMe4's default LLM component."""
        if self._reme is None:
            return

        model, _formatter = create_model_and_formatter(self.agent_id)
        await self._reme.update_component(
            "as_llm",
            "default",
            model=model,
        )

    async def _run_reme_job(
        self,
        name: str,
        *,
        needs_llm: bool = False,
        **kwargs: Any,
    ) -> Any | None:
        if self._reme is None or not getattr(self._reme, "is_started", False):
            logger.debug("ReMe4 job skipped; app not started: %s", name)
            return None
        try:
            if needs_llm:
                await self._update_qwenpaw_model()
            return await self._reme.run_job(name, **kwargs)
        except Exception:
            logger.exception("ReMe4 job failed: %s", name)
            return None

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolChunk:
        """Search ReMe4 memory."""
        query = query.strip()
        if not query:
            return _tool_chunk("Error: query cannot be empty", ok=False)

        response = await self._run_reme_job(
            "search",
            query=query,
            limit=max(1, max_results),
            min_score=max(0.0, min_score),
        )
        if response is None:
            return _tool_chunk("ReMe is not started.", ok=False)

        answer = str(getattr(response, "answer", "") or "").strip()
        if not answer:
            answer = NO_MEMORY_RESULTS
        ok = bool(getattr(response, "success", True))
        return _tool_chunk(answer, ok=ok)

    async def summarize(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Persist conversation messages through ReMe4 auto-memory."""
        if not messages:
            return ""

        response = await self._run_reme_job(
            "auto_memory",
            needs_llm=True,
            messages=[msg.model_dump(mode="json") for msg in messages],
            session_id=str(kwargs.get("session_id") or ""),
            memory_hint=str(kwargs.get("memory_hint") or ""),
        )
        if response is None:
            return ""
        return str(getattr(response, "answer", "") or "")

    async def retrieve(
        self,
        messages: list[Msg] | Msg,
        **_kwargs: Any,
    ) -> dict | None:
        """Retrieve relevant memory as transient text context."""
        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None

        agent_config = load_agent_config(self.agent_id)
        search_cfg = agent_config.running.reme_light_memory_config
        ms = search_cfg.auto_memory_search_config

        result = await self.memory_search(
            query=query,
            max_results=ms.max_results,
            min_score=ms.min_score,
        )
        text = self._chunk_text(result)
        if not text or text == NO_MEMORY_RESULTS:
            return None
        return {"query": query, "text": text}

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict | None:
        """Auto-search memory if configured."""
        del agent_name, kwargs
        agent_config = load_agent_config(self.agent_id)
        ms = agent_config.running.reme_light_memory_config
        if not ms.auto_memory_search_config.enabled:
            return None
        return await self.retrieve(messages)

    async def summarize_when_compact(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> None:
        """Schedule memory extraction when compaction occurs."""
        if not messages:
            return
        agent_config = load_agent_config(self.agent_id)
        cfg = agent_config.running.reme_light_memory_config
        if cfg.summarize_when_compact:
            self.add_summarize_task(messages=messages, **kwargs)

    async def auto_memory(
        self,
        all_messages: list[Msg],
        **kwargs: Any,
    ) -> None:
        """Auto-extract memory every configured N user messages."""
        agent_config = load_agent_config(self.agent_id)
        cfg = agent_config.running.reme_light_memory_config
        interval = cfg.auto_memory_interval
        if interval is None or interval <= 0:
            return

        reply_id = str(kwargs.get("reply_id") or "")
        if reply_id and reply_id in self._persisted_reply_ids:
            return

        user_count = sum(1 for msg in all_messages if msg.role == "user")
        if user_count < interval or user_count % interval != 0:
            return

        recent_messages = self._recent_interval_messages(
            all_messages,
            interval,
        )
        if not recent_messages:
            return

        if reply_id:
            self._persisted_reply_ids.add(reply_id)
        self.add_summarize_task(
            messages=recent_messages,
            session_id=str(kwargs.get("session_id") or ""),
        )

    async def dream(self, **kwargs: Any) -> None:
        """Run one ReMe4 auto-dream pass."""
        response = await self._run_reme_job(
            "auto_dream",
            needs_llm=True,
            date=str(kwargs.get("date") or ""),
            hint=str(kwargs.get("hint") or ""),
        )
        if response is not None and not getattr(response, "success", True):
            raise RuntimeError(str(getattr(response, "answer", "")))

    @staticmethod
    def _build_query(messages: list[Msg]) -> str:
        parts = []
        total = 0
        for msg in reversed(messages):
            if msg.role not in {"user", "assistant"}:
                continue
            text = (msg.get_text_content() or "").strip()
            if not text:
                continue
            remaining = MAX_QUERY_CHARS - total - (1 if parts else 0)
            if remaining <= 0:
                break
            parts.insert(0, text[-remaining:])
            total += min(len(text), remaining) + (1 if len(parts) > 1 else 0)
        return " ".join(parts).strip()

    @staticmethod
    def _chunk_text(chunk: ToolChunk) -> str:
        parts: list[str] = []
        for block in chunk.content:
            if isinstance(block, dict):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()

    @staticmethod
    def _recent_interval_messages(
        messages: list[Msg],
        interval: int,
    ) -> list[Msg]:
        seen = 0
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].role == "user":
                seen += 1
                if seen == interval:
                    return messages[idx:]
        return messages
