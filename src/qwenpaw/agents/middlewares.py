# -*- coding: utf-8 -*-
"""Native AgentScope 2.0 middleware implementations for QwenPaw.

Most per-request setup (ContextVars,
bootstrap injection, skill env overrides, file/media processing) is
handled by lifecycle hooks.

Middlewares in this module wrap the agent's inner reasoning loop via
agentscope's ``MiddlewareBase`` hooks.

Currently provided:

* :class:`ToolResultPruningMiddleware` — tiered truncation of tool-call
  outputs so oversized results don't exhaust the context budget.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Set

from agentscope.middleware import MiddlewareBase
from agentscope.message import SystemMsg

from .tools.utils import truncate_text_output, DEFAULT_MAX_BYTES
from ..constant import TRUNCATION_NOTICE_MARKER

if TYPE_CHECKING:
    from agentscope.agent import Agent
    from agentscope.message import Msg

logger = logging.getLogger(__name__)


class MemoryMiddleware(MiddlewareBase):
    """Attach long-term memory behavior to AgentScope 2.0 agents.

    The middleware owns lifecycle-level memory behavior only:

    * system prompt guidance injection
    * temporary auto-memory-search context injection for model calls
    * post-reply auto-memory scheduling

    Tool registration remains part of toolkit construction.
    """

    def __init__(self, *, memory_manager: Any) -> None:
        self._memory_manager = memory_manager
        self._searched_reply_ids: set[str] = set()
        self._persisted_reply_ids: set[str] = set()

    async def on_system_prompt(
        self,
        agent: "Agent",
        current_prompt: str,
    ) -> str:
        language = getattr(agent, "_language", "zh")
        prompt = self._memory_manager.get_memory_prompt(language)
        if not prompt or prompt in current_prompt:
            return current_prompt
        if current_prompt.strip():
            return f"{current_prompt.rstrip()}\n\n{prompt.strip()}"
        return prompt.strip()

    async def on_model_call(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        reply_id = getattr(agent.state, "reply_id", "") or ""
        if reply_id and reply_id not in self._searched_reply_ids:
            self._searched_reply_ids.add(reply_id)
            await self._inject_memory_context(agent, input_kwargs)
        return await next_handler(**input_kwargs)

    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        async for item in next_handler(**input_kwargs):
            yield item

        reply_id = getattr(agent.state, "reply_id", "") or ""
        if reply_id and reply_id in self._persisted_reply_ids:
            return
        if reply_id:
            self._persisted_reply_ids.add(reply_id)

        try:
            await self._memory_manager.auto_memory(
                list(agent.state.context),
                session_id=getattr(agent.state, "session_id", ""),
                reply_id=reply_id,
            )
        except Exception:
            logger.exception("MemoryMiddleware auto_memory failed")

    async def _inject_memory_context(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
    ) -> None:
        try:
            result = await self._memory_manager.auto_memory_search(
                list(agent.state.context),
                agent_name=getattr(agent, "name", ""),
                session_id=getattr(agent.state, "session_id", ""),
                reply_id=getattr(agent.state, "reply_id", ""),
            )
        except Exception:
            logger.exception("MemoryMiddleware auto_memory_search failed")
            return

        text = self._extract_memory_text(result)
        if not text:
            return

        messages = list(input_kwargs.get("messages") or [])
        memory_msg = SystemMsg(
            name="memory",
            content=(
                "Relevant long-term memory retrieved for this turn:\n\n"
                f"{text}"
            ),
        )

        # Keep the original system prompt first, then add transient memory
        # context before the conversation messages.
        insert_at = 1 if messages else 0
        messages.insert(insert_at, memory_msg)
        input_kwargs["messages"] = messages

    @staticmethod
    def _extract_memory_text(result: Any) -> str:
        if result is None:
            return ""
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict):
            text = result.get("text") or result.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()
            msgs = result.get("msg")
            if isinstance(msgs, list):
                parts = [
                    getattr(msg, "get_text_content", lambda: "")()
                    for msg in msgs
                ]
                return "\n".join(p for p in parts if p).strip()
        return ""


class ToolResultPruningMiddleware(MiddlewareBase):
    """Truncate oversized tool-call results after each acting step.

    Implements the ``on_acting`` hook: the inner tool execution runs
    first, then every ``tool_result`` block in the agent's context is
    scanned and pruned according to tiered byte thresholds.

    * **Recent** tool results (the last ``recent_n`` tool-bearing messages)
      are capped at ``recent_max_bytes``.
    * **Older** tool results are shrunk to ``old_max_bytes``.
    * Tools whose name appears in ``exempt_tool_names``, or whose
      ``read_file`` input references an extension in
      ``exempt_file_extensions``, always use the larger
      ``recent_max_bytes`` limit.

    Full tool outputs are saved to ``{tool_results_dir}/{uuid}.txt``
    before truncation so they remain recoverable.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        recent_n: int = 2,
        old_max_bytes: int = 3000,
        recent_max_bytes: int = DEFAULT_MAX_BYTES,
        exempt_file_extensions: set[str] | None = None,
        exempt_tool_names: set[str] | None = None,
        tool_results_dir: str = "",
        agent_id: str = "default",
    ) -> None:
        self._enabled = enabled
        self._recent_n = recent_n
        self._old_max_bytes = old_max_bytes
        self._recent_max_bytes = recent_max_bytes
        self._exempt_extensions = exempt_file_extensions or set()
        self._exempt_tools = exempt_tool_names or set()
        self._tool_results_dir = tool_results_dir
        self._agent_id = agent_id

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],  # pylint: disable=unused-argument
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        events: list[Any] = []
        async for event in next_handler():
            events.append(event)
            yield event

        if not self._enabled or not events:
            return

        try:
            messages = list(agent.state.context)
            self._prune_tool_results(messages)
        except Exception:
            logger.exception("ToolResultPruningMiddleware failed")

    # ------------------------------------------------------------------
    # Core pruning logic (ported from LightContextManager)
    # ------------------------------------------------------------------

    def _prune_tool_results(self, messages: list["Msg"]) -> None:
        if not messages:
            return

        recent_count = 0
        for msg in reversed(messages):
            if not isinstance(msg.content, list) or not any(
                (isinstance(b, dict) and b.get("type") == "tool_result")
                or getattr(b, "type", None) == "tool_result"
                for b in msg.content
            ):
                break
            recent_count += 1
        split_index = max(
            0,
            len(messages) - max(recent_count, self._recent_n),
        )

        exempt_tool_ids = self._detect_exempt_tool_ids(messages)

        for idx, msg in enumerate(messages):
            if not isinstance(msg.content, list):
                continue
            is_recent = idx >= split_index
            max_bytes = (
                self._recent_max_bytes if is_recent else self._old_max_bytes
            )

            for block in msg.content:
                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype != "tool_result":
                    continue

                tool_id = (
                    block.get("id", "")
                    if isinstance(block, dict)
                    else getattr(block, "id", "")
                )
                output = (
                    block.get("output")
                    if isinstance(block, dict)
                    else getattr(block, "output", None)
                )
                if not output:
                    continue

                effective_max = (
                    self._recent_max_bytes
                    if tool_id in exempt_tool_ids
                    else max_bytes
                )
                pruned = self._prune_output(output, effective_max)
                if isinstance(block, dict):
                    block["output"] = pruned
                else:
                    block.output = pruned

    def _detect_exempt_tool_ids(self, messages: list["Msg"]) -> Set[str]:
        exempt_ids: Set[str] = set()
        for msg in messages:
            if not isinstance(msg.content, list):
                continue
            for block in msg.content:
                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype not in ("tool_use", "tool_call"):
                    continue

                tool_id = (
                    block.get("id", "")
                    if isinstance(block, dict)
                    else getattr(block, "id", "")
                )
                if not tool_id:
                    continue

                tool_name = (
                    (
                        block.get("name", "")
                        if isinstance(block, dict)
                        else getattr(block, "name", "")
                    )
                    or ""
                ).lower()
                raw_input = (
                    block.get("raw_input")
                    if isinstance(block, dict)
                    else getattr(block, "raw_input", None)
                ) or ""
                if isinstance(raw_input, dict):
                    raw_input = str(raw_input)
                raw_input = raw_input.lower()

                if tool_name in self._exempt_tools:
                    exempt_ids.add(tool_id)
                    continue

                if tool_name == "read_file":
                    for ext in self._exempt_extensions:
                        if ext in raw_input:
                            exempt_ids.add(tool_id)
                            break

        return exempt_ids

    def _prune_output(
        self,
        output: str | list[dict],
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> str | list[dict]:
        if isinstance(output, str):
            return self._truncate_tool_result(output, max_bytes, encoding)
        if isinstance(output, list):
            for block in output:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = self._truncate_tool_result(
                        block.get("text", ""),
                        max_bytes,
                        encoding,
                    )
        return output

    def _truncate_tool_result(
        self,
        content: str,
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> str:
        if not content:
            return content

        if TRUNCATION_NOTICE_MARKER in content:
            return truncate_text_output(
                content,
                max_bytes=max_bytes,
                encoding=encoding,
            )

        try:
            content_bytes = len(content.encode(encoding))
        except UnicodeEncodeError:
            return content

        if content_bytes <= max_bytes + 100:
            return content

        saved_path: str | None = None
        if self._tool_results_dir:
            try:
                tool_result_dir = Path(self._tool_results_dir)
                tool_result_dir.mkdir(parents=True, exist_ok=True)
                fp = tool_result_dir / f"{uuid.uuid4().hex}.txt"
                fp.write_text(content, encoding=encoding)
                saved_path = str(fp)
            except OSError as e:
                logger.warning("Failed to save tool result to file: %s", e)

        return truncate_text_output(
            content,
            start_line=1,
            total_lines=content.count("\n") + 1,
            max_bytes=max_bytes,
            file_path=saved_path,
            encoding=encoding,
        )
