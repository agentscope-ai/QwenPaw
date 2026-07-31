# -*- coding: utf-8 -*-
"""Native AgentScope 2.0 middleware implementations for QwenPaw.

Most per-request setup (ContextVars,
bootstrap injection, skill env overrides, file/media processing) is
handled by lifecycle hooks.

Middlewares in this module wrap the agent's inner reasoning loop via
agentscope's ``MiddlewareBase`` hooks.

Currently provided:

* :class:`ToolResultPruningMiddleware` — truncation of current and historical
  tool-call outputs so oversized results don't exhaust the context budget.
"""

import asyncio
import logging
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Iterator

from agentscope.middleware import MiddlewareBase
from agentscope.message import Msg
from agentscope.tool import ToolResponse

from .tools.utils import (
    DEFAULT_MAX_BYTES,
    ToolResultPruner,
)
from ..constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    MEMORY_MIDDLE_CONTEXT_KEY,
    QWENPAW_MESSAGE_TAG_KEY,
)

if TYPE_CHECKING:
    from agentscope.agent import Agent

logger = logging.getLogger(__name__)
MAX_AUTO_MEMORY_TURN_MARKERS = 1000
_AUTOMATION_MEMORY_SKIP_SOURCES = frozenset({"cron", "heartbeat"})
_TOOL_RESULT_METADATA_KEY = "qwenpaw_tool_result_metadata"
_MANUAL_COMPACT_MEMORY_BY_HANDLER: ContextVar[bool] = ContextVar(
    "manual_compact_memory_by_handler",
    default=False,
)


@contextmanager
def manual_compact_memory_by_handler() -> Iterator[None]:
    """Let the command handler exclusively schedule manual compact memory."""
    token = _MANUAL_COMPACT_MEMORY_BY_HANDLER.set(True)
    try:
        yield
    finally:
        _MANUAL_COMPACT_MEMORY_BY_HANDLER.reset(token)


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

    async def on_system_prompt(
        self,
        # pylint: disable=unused-argument
        agent: "Agent",
        current_prompt: str,
    ) -> str:
        prompt = self._memory_manager.get_memory_prompt()
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
        if self._is_automation_request(agent):
            return await next_handler(**input_kwargs)

        query_msg = self._latest_external_user_query(agent.state.context)
        turn_marker = query_msg.id if query_msg is not None else ""
        turn_state = self._auto_memory_turn_state(agent)
        if turn_marker and turn_marker != turn_state.get("searched_turn"):
            turn_state["searched_turn"] = turn_marker
            try:
                result = await self._memory_manager.auto_memory_search(
                    query_msg,
                    agent_name=agent.name,
                    session_id=agent.state.session_id,
                    user_turn_id=turn_marker,
                )
            except Exception:
                logger.exception(
                    "MemoryMiddleware auto_memory_search failed",
                )
            else:
                messages = list(input_kwargs.get("messages") or [])
                memory_msgs = self._extract_memory_messages(
                    result,
                    existing_ids={
                        msg.id for msg in agent.state.context if msg.id
                    },
                )
                if memory_msgs:
                    messages.extend(memory_msgs)
                    input_kwargs["messages"] = messages
        return await next_handler(**input_kwargs)

    # pylint: disable=stop-iteration-return
    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        async for item in next_handler(**input_kwargs):
            yield item

        if self._is_automation_request(agent):
            return

        turn_state = self._auto_memory_turn_state(agent)
        pending_markers = turn_state["pending"]
        seen_markers = turn_state["seen"]
        turn_marker = self._latest_user_turn_marker(agent.state.context)
        if not turn_marker or turn_marker in seen_markers:
            return

        seen_markers[turn_marker] = None
        if len(seen_markers) > MAX_AUTO_MEMORY_TURN_MARKERS:
            oldest_key = next(iter(seen_markers))
            seen_markers.pop(oldest_key)
        pending_markers.append(turn_marker)

        interval = self._auto_memory_interval()
        if interval <= 0:
            self._discard_pending_turns(
                turn_state,
                list(pending_markers),
            )
            return
        if len(pending_markers) < interval:
            return

        await self._flush_auto_memory(
            agent,
            count=interval,
        )

    async def on_compress_context(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> None:
        if _MANUAL_COMPACT_MEMORY_BY_HANDLER.get():
            await next_handler(**input_kwargs)
            return

        if self._is_automation_request(agent):
            await next_handler(**input_kwargs)
            return

        # AgentScope's middleware hook is invoked before the concrete
        # compressor has evaluated its threshold. Snapshot only pending turns
        # so an actually-evicted turn remains available to long-term memory,
        # then react to Scroll's real outcome. The copy must be deep because
        # Scroll can fold tool-result blocks in place. Restricting it to
        # pending turns avoids copying the full context on every reasoning
        # step that ultimately needs no compression.
        context_before: list[Msg] = []
        try:
            turn_state = self._auto_memory_turn_state(agent)
            pending_before = list(turn_state["pending"])
            if pending_before:
                context_before = deepcopy(
                    self._messages_for_pending_turns(
                        list(agent.state.context),
                        turn_markers=pending_before,
                        cached=turn_state["pending_messages"],
                    ),
                )
        except Exception:
            logger.exception(
                "MemoryMiddleware could not snapshot pending turns",
            )
        await next_handler(**input_kwargs)

        try:
            cfg = self._memory_config()
            pending_markers = self._auto_memory_turn_state(agent)["pending"]
            if (
                getattr(cfg, "summarize_when_compact", False)
                and pending_markers
                and self._did_compress_context(agent)
            ):
                await self._flush_auto_memory(
                    agent,
                    source_context=context_before,
                )
        except Exception:
            logger.exception(
                "MemoryMiddleware post-compression auto-memory flush failed",
            )

    async def _flush_auto_memory(
        self,
        agent: "Agent",
        *,
        count: int | None = None,
        source_context: list["Msg"] | None = None,
    ) -> None:
        if self._is_automation_request(agent):
            logger.debug(
                "MemoryMiddleware auto_memory skipped for automation source: "
                "agent=%s",
                agent.name,
            )
            # Defensive: clear in case on_reply guard was bypassed
            turn_state = self._auto_memory_turn_state(agent)
            self._discard_pending_turns(
                turn_state,
                list(turn_state["pending"]),
            )
            return

        turn_state = self._auto_memory_turn_state(agent)
        pending_markers = turn_state["pending"]
        if not pending_markers:
            return

        turn_markers = list(
            pending_markers if count is None else pending_markers[:count],
        )

        available_context = (
            source_context
            if source_context is not None
            else list(agent.state.context)
        )
        messages = self._messages_for_pending_turns(
            available_context,
            turn_markers=turn_markers,
            cached=turn_state["pending_messages"],
        )
        if not messages:
            self._discard_pending_turns(turn_state, turn_markers)
            return

        try:
            await self._memory_manager.auto_memory(
                messages,
                session_id=self._agent_session_id(agent),
            )
        except Exception:
            self._cache_pending_messages(
                turn_state,
                available_context,
                turn_markers,
            )
            logger.exception("MemoryMiddleware auto_memory failed")
        else:
            self._discard_pending_turns(turn_state, turn_markers)

    @staticmethod
    def _discard_pending_turns(
        turn_state: dict[str, Any],
        submitted: list[str],
    ) -> None:
        submitted_set = set(submitted)
        turn_state["pending"][:] = [
            marker
            for marker in turn_state["pending"]
            if marker not in submitted_set
        ]
        cached = turn_state["pending_messages"]
        for marker in submitted_set:
            cached.pop(marker, None)

    @classmethod
    def _cache_pending_messages(
        cls,
        turn_state: dict[str, Any],
        messages: list["Msg"],
        turn_markers: list[str],
    ) -> None:
        """Persist failed batches so eviction cannot make retries empty."""
        cached = turn_state["pending_messages"]
        for marker in turn_markers:
            batch = cls._messages_for_user_turns(
                messages,
                turn_markers=[marker],
            )
            if batch:
                try:
                    cached[marker] = [
                        msg.model_dump(mode="json") for msg in batch
                    ]
                except Exception:
                    logger.warning(
                        "Could not cache auto-memory retry batch for %s",
                        marker,
                        exc_info=True,
                    )

    @classmethod
    def _messages_for_pending_turns(
        cls,
        messages: list["Msg"],
        *,
        turn_markers: list[str],
        cached: dict[str, Any],
    ) -> list["Msg"]:
        """Resolve pending turns from live context or persisted retry data."""
        resolved: list[Msg] = []
        for marker in turn_markers:
            batch = cls._messages_for_user_turns(
                messages,
                turn_markers=[marker],
            )
            if batch:
                resolved.extend(batch)
                continue
            raw_batch = cached.get(marker)
            if not isinstance(raw_batch, list):
                continue
            for raw in raw_batch:
                try:
                    resolved.append(
                        raw
                        if isinstance(raw, Msg)
                        else Msg.model_validate(raw),
                    )
                except Exception:
                    logger.warning(
                        "Ignoring invalid cached auto-memory message for %s",
                        marker,
                        exc_info=True,
                    )
        return resolved

    @staticmethod
    def _agent_session_id(agent: "Agent") -> str:
        session_id = str(getattr(agent.state, "session_id", "") or "")
        if session_id:
            return session_id
        request_context = getattr(agent, "_request_context", None) or {}
        if isinstance(request_context, dict):
            return str(request_context.get("session_id") or "")
        return ""

    @staticmethod
    def _is_automation_request(agent: "Agent") -> bool:
        """Return True when the request originates from non-user automation."""
        request_context = getattr(agent, "_request_context", None) or {}
        if not isinstance(request_context, dict):
            return False
        source = str(request_context.get("source") or "").strip().lower()
        return source in _AUTOMATION_MEMORY_SKIP_SOURCES

    @staticmethod
    def _did_compress_context(agent: "Agent") -> bool:
        scroll = getattr(agent, "_scroll_context", None)
        stats = getattr(scroll, "last_compress", None)
        if not isinstance(stats, dict):
            return False
        return bool(stats.get("evicted") or stats.get("folded"))

    @staticmethod
    def _extract_memory_messages(
        result: Any,
        *,
        existing_ids: set[str],
    ) -> list["Msg"]:
        if not isinstance(result, dict):
            return []
        msgs = result.get("msg") or result.get("messages")
        if not isinstance(msgs, list):
            return []

        return [
            msg
            for msg in msgs
            if hasattr(msg, "has_content_blocks")
            and getattr(msg, "id", None) not in existing_ids
            and (
                msg.has_content_blocks("tool_call")
                or msg.has_content_blocks("tool_result")
            )
        ]

    def _auto_memory_interval(self) -> int:
        return int(self._memory_manager.get_auto_memory_interval())

    def _memory_config(self) -> Any:
        return self._memory_manager.get_memory_config()

    def _auto_memory_turn_state(self, agent: "Agent") -> dict[str, Any]:
        """Return lifecycle state in AgentScope's persisted middleware slot."""
        state = agent.state.middle_context.setdefault(
            MEMORY_MIDDLE_CONTEXT_KEY,
            {
                "pending": [],
                "seen": {},
                "pending_messages": {},
            },
        )
        # Additive normalization keeps checkpoints produced by earlier
        # versions valid while making failed batches durable across rebuilds.
        state.setdefault("pending", [])
        state.setdefault("seen", {})
        state.setdefault("pending_messages", {})
        return state

    @staticmethod
    def _message_tag(msg: "Msg") -> str:
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get(QWENPAW_MESSAGE_TAG_KEY) or "")

    @classmethod
    def _is_external_user_query(cls, msg: "Msg") -> bool:
        return (
            msg.role == "user"
            and cls._message_tag(msg) == EXTERNAL_USER_QUERY_MESSAGE_TAG
        )

    @classmethod
    def _latest_external_user_query(
        cls,
        messages: list["Msg"],
    ) -> "Msg | None":
        for msg in reversed(messages):
            if cls._is_external_user_query(msg):
                return msg
        return None

    @classmethod
    def _latest_user_turn_marker(cls, messages: list["Msg"]) -> str:
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if not cls._is_external_user_query(msg):
                continue
            return msg.id
        return ""

    @classmethod
    def _messages_for_user_turns(
        cls,
        messages: list["Msg"],
        *,
        turn_markers: list[str],
    ) -> list["Msg"]:
        targets = set(turn_markers)
        if not targets:
            return []

        first_idx: int | None = None
        last_idx: int | None = None
        for idx, msg in enumerate(messages):
            if cls._is_external_user_query(msg) and msg.id in targets:
                if first_idx is None:
                    first_idx = idx
                last_idx = idx

        if first_idx is None or last_idx is None:
            return []

        end_idx = len(messages)
        for idx in range(last_idx + 1, len(messages)):
            if cls._is_external_user_query(messages[idx]):
                end_idx = idx
                break

        return [
            msg
            for msg in messages[first_idx:end_idx]
            if msg.role != "user" or cls._is_external_user_query(msg)
        ]


class ToolResultPruningMiddleware(MiddlewareBase):
    """Truncate oversized tool-call results around each acting step.

    Each ``ToolResponse`` is capped before it enters agent context. Historical
    results are scanned with the same byte limit so metadata from older
    snapshots is normalized without reviving the removed Native tiering.

    Full tool outputs are saved to ``{tool_results_dir}/{uuid}.txt``
    before truncation so they remain recoverable.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        recent_max_bytes: int = DEFAULT_MAX_BYTES,
        tool_results_dir: str = "",
    ) -> None:
        self._enabled = enabled
        self._recent_max_bytes = recent_max_bytes
        self._pruner = ToolResultPruner(tool_results_dir)

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],  # pylint: disable=unused-argument
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        events: list[Any] = []
        async for event in next_handler():
            if isinstance(event, ToolResponse):
                event = await self.prune_tool_response_async(event)
            events.append(event)
            yield event

        if not self._enabled or not events:
            return

        try:
            messages = list(agent.state.context)
            await asyncio.to_thread(self._prune_tool_results, messages)
        except Exception:
            logger.exception("ToolResultPruningMiddleware failed")

    # ------------------------------------------------------------------
    # Core pruning logic (ported from LightContextManager)
    # ------------------------------------------------------------------

    def prune_tool_response(
        self,
        response: ToolResponse,
    ) -> ToolResponse:
        """Cap the current ToolResponse before it enters agent context."""
        if not self._enabled:
            return response

        # Current responses are pruned per text block, not by aggregate
        # ToolResponse byte size. Multi-block truncation metadata is kept by
        # content index so one block cannot influence another block's retry
        # location or cached file path.
        self._pruner.prune_output(
            response.content or [],
            max_bytes=self._recent_max_bytes,
            metadata=response.metadata,
        )

        return response

    async def prune_tool_response_async(
        self,
        response: ToolResponse,
    ) -> ToolResponse:
        """Prune a response without blocking the asyncio event loop."""
        return await asyncio.to_thread(self.prune_tool_response, response)

    def _prune_tool_results(self, messages: list["Msg"]) -> None:
        if not messages:
            return

        for msg in messages:
            if not isinstance(msg.content, list):
                continue

            for block in msg.content:
                if self._block_type(block) != "tool_result":
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

                block_metadata = (
                    block.setdefault("metadata", {})
                    if isinstance(block, dict)
                    else getattr(block, "metadata", None)
                )
                # AgentScope ToolResultBlock may not expose metadata. Persist
                # pruning state on the owning message in that case.
                if not isinstance(block_metadata, dict):
                    msg_metadata = (
                        msg.setdefault("metadata", {})
                        if isinstance(msg, dict)
                        else getattr(msg, "metadata", None)
                    )
                    if not isinstance(msg_metadata, dict):
                        msg_metadata = {}
                        if not isinstance(msg, dict):
                            msg.metadata = msg_metadata
                    by_tool = msg_metadata.setdefault(
                        _TOOL_RESULT_METADATA_KEY,
                        {},
                    )
                    block_metadata = by_tool.setdefault(tool_id, {})
                pruned, _ = self._pruner.prune_output(
                    output,
                    max_bytes=self._recent_max_bytes,
                    metadata=block_metadata,
                )
                if isinstance(block, dict):
                    block["output"] = pruned
                else:
                    block.output = pruned

    @staticmethod
    def _block_type(block: Any) -> str | None:
        if isinstance(block, dict):
            return block.get("type")
        return getattr(block, "type", None)


class LangfuseToolSpanMiddleware(MiddlewareBase):
    """Record each tool execution as a Langfuse tool observation.

    Yields ``None`` from ``tool_span`` when Langfuse is disabled or the
    client is unavailable; the ``observation is not None`` guard handles
    this gracefully.
    """

    async def on_acting(
        self,
        agent: "Agent",  # pylint: disable=unused-argument
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        from ..observability.langfuse import get_current_trace, tool_span

        if get_current_trace() is None:
            async for event in next_handler():
                yield event
            return

        tool_call = input_kwargs.get("tool_call")
        tool_name = getattr(tool_call, "name", "unknown")
        tool_input = getattr(tool_call, "input", None)

        async with tool_span(
            name=tool_name,
            input=tool_input,
            metadata={"tool_call_id": getattr(tool_call, "id", None)},
        ) as observation:
            final_response = None
            async for event in next_handler():
                if isinstance(event, ToolResponse):
                    final_response = event
                yield event
            if observation is not None and final_response is not None:
                observation.update(
                    output={
                        "content": [
                            getattr(b, "text", str(b))
                            for b in (final_response.content or [])
                        ],
                    },
                )
