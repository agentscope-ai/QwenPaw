# -*- coding: utf-8 -*-
"""ReMe-backed memory manager for agents.

The public class and registry key keep the historical ``ReMeLight`` naming so
existing agent configs continue to work, but the implementation delegates to
ReMe's application/job framework.
"""

import json
import logging
import uuid
from contextlib import suppress
from typing import Any, TYPE_CHECKING

from agentscope.message import Msg, TextBlock
from agentscope.message import ToolCallBlock, ToolCallState
from agentscope.message import ToolResultBlock, ToolResultState
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry
from .prompts import build_memory_guidance_prompt
from .reme_config import get_reme_app_config
from ..model_factory import create_model_and_formatter
from ...config import load_config
from ...config.config import load_agent_config, AgentProfileConfig

if TYPE_CHECKING:
    from reme import ReMe
    from reme.application import Response

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
    """Memory manager backed by ReMe.

    ReMe uses the QwenPaw workspace root as its vault.  Daily memory,
    digest memory, search, auto-memory, and auto-dream are executed through
    ReMe jobs.
    """

    def __init__(self, working_dir: str, agent_id: str):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme: "ReMe | None" = None
        logger.info(
            "ReMeLightMemoryManager init: agent_id=%s working_dir=%s",
            agent_id,
            working_dir,
        )

        try:
            from reme import ReMe as ReMeApp  # type: ignore

            agent_config: AgentProfileConfig = load_agent_config(self.agent_id)
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
            logger.warning("ReMe import failed; memory disabled: %s", exc)

    async def start(self) -> None:
        """Start the embedded ReMe application."""
        if self._reme is None:
            return

        await self._update_qwenpaw_model()
        try:
            await self._reme.start()
            logger.info(
                "ReMe memory manager started for agent '%s'",
                self.agent_id,
            )
        except Exception:
            logger.exception("ReMe start failed")
            return

        agent_config = load_agent_config(self.agent_id)
        cfg = agent_config.running.reme_light_memory_config
        if cfg.rebuild_memory_index_on_start:
            await self._run_reme_job("reindex")
            logger.info(
                "Memory index rebuilt on start for agent '%s'",
                self.agent_id,
            )

    async def close(self) -> bool:
        """Close ReMe and cleanup background summary worker state."""
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
                logger.exception("ReMe close failed")
                return False

        self._reme = None
        return True

    def get_memory_prompt(self) -> str:
        """Return memory guidance for system prompt injection."""
        agent_config = load_agent_config(self.agent_id)
        cfg = agent_config.running.reme_light_memory_config
        return build_memory_guidance_prompt(
            agent_config.language,
            daily_dir=cfg.daily_dir,
        )

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        return [self.memory_search]

    async def _update_qwenpaw_model(self) -> None:
        """Reuse QwenPaw's active model in ReMe's default LLM component."""
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
    ) -> "Response | None":
        if self._reme is None or not getattr(self._reme, "is_started", False):
            logger.debug("ReMe job skipped; app not started: %s", name)
            return None
        try:
            if needs_llm:
                await self._update_qwenpaw_model()
            return await self._reme.run_job(name, **kwargs)
        except Exception:
            logger.exception("ReMe job failed: %s", name)
            return None

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolChunk:
        """Search ReMe memory."""
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

        answer = str(response.answer or "").strip()
        if not answer:
            answer = NO_MEMORY_RESULTS
        return _tool_chunk(answer, ok=response.success)

    async def summarize(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Persist conversation messages through ReMe auto-memory."""
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
        return str(response.answer or "")

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict | None:
        """Auto-search memory and expose it as a completed tool interaction."""
        del kwargs
        agent_config = load_agent_config(self.agent_id)
        memory_cfg = agent_config.running.reme_light_memory_config
        if not memory_cfg.auto_memory_search_config.enabled:
            return None

        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None

        search_cfg = memory_cfg.auto_memory_search_config

        response = await self._run_reme_job(
            "search",
            query=query,
            limit=max(1, search_cfg.max_results),
            min_score=max(0.0, search_cfg.min_score),
        )
        if response is None or not response.success:
            return None

        text = str(response.answer or "").strip()
        if not text:
            return None

        tool_call_id = uuid.uuid4().hex
        tool_input = {
            "query": query,
            "max_results": search_cfg.max_results,
            "min_score": search_cfg.min_score,
        }
        assistant_msg = Msg(
            name=agent_name or self.agent_id,
            role="assistant",
            content=[
                TextBlock(text="Searching memory for relevant context..."),
                ToolCallBlock(
                    id=tool_call_id,
                    name="memory_search",
                    input=json.dumps(tool_input, ensure_ascii=False),
                    state=ToolCallState.FINISHED,
                ),
            ],
        )
        tool_result_msg = Msg(
            name=agent_name or self.agent_id,
            role="assistant",
            content=[
                ToolResultBlock(
                    id=tool_call_id,
                    name="memory_search",
                    output=[TextBlock(text=text)],
                    state=ToolResultState.SUCCESS,
                ),
            ],
        )
        return {
            "query": query,
            "text": text,
            "msg": msgs + [assistant_msg, tool_result_msg],
        }

    async def auto_memory(
        self,
        all_messages: list[Msg],
        **kwargs: Any,
    ) -> None:
        """Auto-extract memory for a prepared reply batch."""
        if not kwargs.get("reply_ids") or not all_messages:
            return

        self.add_summarize_task(
            messages=all_messages,
            session_id=str(kwargs.get("session_id") or ""),
        )

    async def dream(self, **kwargs: Any) -> None:
        """Run one ReMe auto-dream pass."""
        response = await self._run_reme_job(
            "auto_dream",
            needs_llm=True,
            date=str(kwargs.get("date") or ""),
            hint=str(kwargs.get("hint") or ""),
        )
        if response is not None and not response.success:
            raise RuntimeError(str(response.answer))

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
