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
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Iterator, Set

from agentscope.middleware import MiddlewareBase
from agentscope.message import Msg
from agentscope.tool import ToolResponse

from .tools.utils import (
    DEFAULT_MAX_BYTES,
    ToolResultPruner,
)
from ..constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)

if TYPE_CHECKING:
    from agentscope.agent import Agent

logger = logging.getLogger(__name__)
MAX_AUTO_MEMORY_TURN_MARKERS = 1000
AUTO_MEMORY_TURN_STATE_KEY = "qwenpaw_auto_memory_turn_state"
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


def auto_memory_turn_state(agent_state: Any) -> dict[str, Any]:
    """Return auto-memory lifecycle state persisted with ``AgentState``."""
    middle_context = getattr(agent_state, "middle_context", None)
    if not isinstance(middle_context, dict):
        middle_context = {}
        agent_state.middle_context = middle_context

    state = middle_context.get(AUTO_MEMORY_TURN_STATE_KEY)
    if not isinstance(state, dict):
        state = {}
        middle_context[AUTO_MEMORY_TURN_STATE_KEY] = state

    if not isinstance(state.get("pending"), list):
        state["pending"] = []
    if not isinstance(state.get("seen"), dict):
        state["seen"] = {}
    if not isinstance(state.get("snapshots"), dict):
        state["snapshots"] = {}
    if not isinstance(state.get("search"), dict):
        state["search"] = {}
    state.pop("searched_turn", None)
    state["version"] = 2
    return state


def reset_auto_memory_turn_state(agent_state: Any) -> None:
    """Forget all conversation-scoped auto-memory lifecycle state."""
    middle_context = getattr(agent_state, "middle_context", None)
    if isinstance(middle_context, dict):
        middle_context.pop(AUTO_MEMORY_TURN_STATE_KEY, None)


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
        search_state = turn_state["search"]
        if turn_marker and turn_marker != search_state.get("turn_marker"):
            # Replace the cache before searching so evidence from the previous
            # user turn can never leak into the new one. A failed search is
            # retried on the next model call because no turn marker is stored.
            turn_state["search"] = {}
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
                memory_msgs = self._extract_memory_messages(
                    result,
                    context_len=len(agent.state.context),
                )
                self._save_search_cache(
                    turn_state,
                    turn_marker=turn_marker,
                    messages=memory_msgs,
                )

        memory_msgs = self._load_search_cache(
            turn_state,
            turn_marker=turn_marker,
        )
        if memory_msgs:
            input_kwargs["messages"] = self._inject_search_messages(
                list(input_kwargs.get("messages") or []),
                memory_msgs=memory_msgs,
                turn_marker=turn_marker,
            )
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
            pending_markers.clear()
            turn_state["snapshots"].clear()
            turn_state.pop("retry", None)
            return

        # Pending markers are persisted independently from the live context.
        # Drop orphaned markers before applying the interval so stale state
        # cannot make every subsequent user turn look like a full batch.
        self._discard_unresolved_pending_markers(agent, turn_state)
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

        automation_request = self._is_automation_request(agent)

        source_context: list[Msg] = []
        pending_markers: list[str] = []
        compression_state: tuple[Any, tuple[str, ...]] | None = None
        try:
            pending_markers = list(
                self._auto_memory_turn_state(agent)["pending"],
            )
            if pending_markers:
                source_context = deepcopy(list(agent.state.context))
                compression_state = self._compression_state(agent)
        except Exception:
            logger.exception(
                "MemoryMiddleware could not snapshot pending turns",
            )

        try:
            await next_handler(**input_kwargs)
        except BaseException:
            # Scroll may rebuild the live context and only then discover that
            # it still exceeds the hard limit. Preserve the pre-compression
            # messages before propagating that original failure/cancellation.
            if self._compression_changed(agent, compression_state):
                try:
                    self._save_turn_snapshots(
                        self._auto_memory_turn_state(agent),
                        source_context=source_context,
                        turn_markers=pending_markers,
                    )
                except Exception:
                    logger.exception(
                        "MemoryMiddleware could not preserve snapshots after "
                        "compression failure",
                    )
            raise

        if source_context and compression_state is not None:
            try:
                if self._did_compress_context(agent, compression_state):
                    turn_state = self._auto_memory_turn_state(agent)
                    self._save_turn_snapshots(
                        turn_state,
                        source_context=source_context,
                        turn_markers=pending_markers,
                    )
                    if not automation_request:
                        await self._flush_auto_memory(agent)
            except Exception:
                logger.exception(
                    "MemoryMiddleware post-compression auto-memory flush "
                    "failed",
                )

    async def _flush_auto_memory(
        self,
        agent: "Agent",
        *,
        count: int | None = None,
    ) -> None:
        if self._is_automation_request(agent):
            logger.debug(
                "MemoryMiddleware auto_memory skipped for automation source: "
                "agent=%s",
                agent.name,
            )
            return

        turn_state = self._auto_memory_turn_state(agent)
        pending_markers = turn_state["pending"]
        if not pending_markers:
            return

        # Flushes can also be triggered by context compression, without first
        # passing through on_reply(), so enforce the same invariant here.
        self._discard_unresolved_pending_markers(agent, turn_state)
        if not pending_markers:
            return

        messages: list[Msg] = []
        resolved_markers: list[str] = []
        for turn_marker in list(pending_markers):
            if count is not None and len(resolved_markers) >= count:
                break
            turn_messages = self._load_turn_snapshot(
                turn_state,
                turn_marker,
            )
            if not turn_messages:
                turn_messages = self._messages_for_user_turn(
                    list(agent.state.context),
                    turn_marker=turn_marker,
                )
            if not turn_messages:
                continue
            resolved_markers.append(turn_marker)
            messages.extend(turn_messages)

        if not messages:
            return

        try:
            await self._memory_manager.auto_memory(
                messages,
                session_id=self._agent_session_id(agent),
            )
        except Exception:
            logger.exception("MemoryMiddleware auto_memory failed")
            self._save_turn_snapshots_from_resolved_messages(
                turn_state,
                turn_markers=resolved_markers,
                messages=messages,
            )
            return

        submitted = set(resolved_markers)
        pending_markers[:] = [
            marker for marker in pending_markers if marker not in submitted
        ]
        snapshots = turn_state["snapshots"]
        for marker in submitted:
            snapshots.pop(marker, None)

    def _discard_unresolved_pending_markers(
        self,
        agent: "Agent",
        turn_state: dict[str, Any],
    ) -> None:
        """Remove markers whose turn payload is no longer recoverable."""
        # Legacy retry state is intentionally ignored. At worst it may cause
        # redundant messages, which the memory LLM can deduplicate; migration
        # is not worth the added complexity.
        pending_markers = turn_state["pending"]
        if not pending_markers:
            return

        context = list(agent.state.context)
        unresolved: list[str] = []
        for turn_marker in pending_markers:
            if self._load_turn_snapshot(turn_state, turn_marker):
                continue
            if self._messages_for_user_turn(
                context,
                turn_marker=turn_marker,
            ):
                continue
            unresolved.append(turn_marker)

        if not unresolved:
            return

        stale = set(unresolved)
        pending_markers[:] = [
            marker for marker in pending_markers if marker not in stale
        ]
        logger.warning(
            "MemoryMiddleware discarded unresolved pending markers: %s",
            unresolved,
        )

    @classmethod
    def _save_turn_snapshots(
        cls,
        turn_state: dict[str, Any],
        *,
        source_context: list["Msg"],
        turn_markers: list[str],
    ) -> None:
        snapshots = turn_state["snapshots"]
        for marker in turn_markers:
            if marker in snapshots:
                continue
            messages = cls._messages_for_user_turn(
                source_context,
                turn_marker=marker,
            )
            if not messages:
                continue
            try:
                snapshots[marker] = [
                    msg.model_dump(mode="json") for msg in messages
                ]
            except Exception:
                logger.exception(
                    "MemoryMiddleware could not save turn snapshot: %s",
                    marker,
                )

    @classmethod
    def _save_turn_snapshots_from_resolved_messages(
        cls,
        turn_state: dict[str, Any],
        *,
        turn_markers: list[str],
        messages: list["Msg"],
    ) -> None:
        cls._save_turn_snapshots(
            turn_state,
            source_context=messages,
            turn_markers=turn_markers,
        )

    @staticmethod
    def _load_turn_snapshot(
        turn_state: dict[str, Any],
        turn_marker: str,
    ) -> list["Msg"]:
        snapshots = turn_state["snapshots"]
        raw_messages = snapshots.get(turn_marker)
        if not isinstance(raw_messages, list) or not raw_messages:
            return []
        try:
            return [
                msg if isinstance(msg, Msg) else Msg.model_validate(msg)
                for msg in raw_messages
            ]
        except Exception:
            logger.exception(
                "MemoryMiddleware invalid turn snapshot: %s",
                turn_marker,
            )
            snapshots.pop(turn_marker, None)
            return []

    @staticmethod
    def _save_search_cache(
        turn_state: dict[str, Any],
        *,
        turn_marker: str,
        messages: list["Msg"],
    ) -> None:
        try:
            turn_state["search"] = {
                "turn_marker": turn_marker,
                "messages": [msg.model_dump(mode="json") for msg in messages],
            }
        except Exception:
            logger.exception("MemoryMiddleware could not save search cache")
            turn_state["search"] = {}

    @staticmethod
    def _load_search_cache(
        turn_state: dict[str, Any],
        *,
        turn_marker: str,
    ) -> list["Msg"]:
        search = turn_state.get("search")
        if (
            not isinstance(search, dict)
            or search.get("turn_marker") != turn_marker
        ):
            return []
        raw_messages = search.get("messages")
        if not isinstance(raw_messages, list):
            return []
        try:
            return [
                msg if isinstance(msg, Msg) else Msg.model_validate(msg)
                for msg in raw_messages
            ]
        except Exception:
            logger.exception("MemoryMiddleware invalid search cache")
            turn_state["search"] = {}
            return []

    @staticmethod
    def _inject_search_messages(
        messages: list["Msg"],
        *,
        memory_msgs: list["Msg"],
        turn_marker: str,
    ) -> list["Msg"]:
        """Insert transient evidence after its query, preserving chronology."""
        existing_ids = {msg.id for msg in messages}
        injected = [msg for msg in memory_msgs if msg.id not in existing_ids]
        if not injected:
            return messages

        insert_at = len(messages)
        for idx, msg in enumerate(messages):
            if msg.id == turn_marker:
                insert_at = idx + 1
        messages[insert_at:insert_at] = injected
        return messages

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
    def _compression_state(
        agent: "Agent",
    ) -> tuple[Any, tuple[str, ...]]:
        return (
            agent.state.summary,
            tuple(msg.id for msg in agent.state.context),
        )

    @classmethod
    def _did_compress_context(
        cls,
        agent: "Agent",
        before: tuple[Any, tuple[str, ...]],
    ) -> bool:
        context_manager = getattr(agent, "_context_manager", None)
        stats = getattr(context_manager, "last_compress", None)
        if isinstance(stats, dict):
            return bool(stats.get("evicted") or stats.get("folded"))
        return cls._compression_state(agent) != before

    @classmethod
    def _compression_changed(
        cls,
        agent: "Agent",
        before: tuple[Any, tuple[str, ...]] | None,
    ) -> bool:
        """Best-effort compression inspection for exception cleanup paths."""
        if before is None:
            return False
        try:
            return cls._did_compress_context(agent, before)
        except Exception:
            logger.exception(
                "MemoryMiddleware could not inspect compression result",
            )
            return False

    @staticmethod
    def _extract_memory_messages(
        result: Any,
        *,
        context_len: int,
    ) -> list["Msg"]:
        if not isinstance(result, dict):
            return []
        msgs = result.get("msg") or result.get("messages")
        if not isinstance(msgs, list):
            return []

        injected = msgs[context_len:] if len(msgs) > context_len else msgs
        return [
            msg
            for msg in injected
            if hasattr(msg, "has_content_blocks")
            and (
                msg.has_content_blocks("tool_call")
                or msg.has_content_blocks("tool_result")
            )
        ]

    def _auto_memory_interval(self) -> int:
        return int(self._memory_manager.get_auto_memory_interval())

    def _auto_memory_turn_state(self, agent: "Agent") -> dict[str, Any]:
        return auto_memory_turn_state(agent.state)

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

    @classmethod
    def _messages_for_user_turn(
        cls,
        messages: list["Msg"],
        *,
        turn_marker: str,
    ) -> list["Msg"]:
        """Return one complete external-user turn without internal controls."""
        start_idx: int | None = None
        for idx, msg in enumerate(messages):
            if cls._is_external_user_query(msg) and msg.id == turn_marker:
                start_idx = idx
                break
        if start_idx is None:
            return []

        end_idx = len(messages)
        for idx in range(start_idx + 1, len(messages)):
            if cls._is_external_user_query(messages[idx]):
                end_idx = idx
                break
        return [
            msg
            for msg in messages[start_idx:end_idx]
            if msg.role != "user" or cls._is_external_user_query(msg)
        ]


def discard_auto_memory_turns(
    agent_state: Any,
    turn_markers: set[str],
) -> None:
    """Discard pending state for turns submitted by another lifecycle path."""
    if not turn_markers:
        return
    state = auto_memory_turn_state(agent_state)
    state["pending"][:] = [
        marker for marker in state["pending"] if marker not in turn_markers
    ]
    snapshots = state["snapshots"]
    for marker in turn_markers:
        snapshots.pop(marker, None)


class ToolResultPruningMiddleware(MiddlewareBase):
    """Truncate oversized tool-call results around each acting step.

    Implements the ``on_acting`` hook: each ``ToolResponse`` is capped before
    it is yielded into the agent context, then every historical ``tool_result``
    block in the agent's context is scanned and pruned according to tiered byte
    thresholds.

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
        self._pruner = ToolResultPruner(tool_results_dir)
        self._agent_id = agent_id

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

    def _prune_tool_results(  # pylint: disable=R0912
        self,
        messages: list["Msg"],
    ) -> None:
        if not messages:
            return

        recent_count = 0
        for msg in reversed(messages):
            if not isinstance(msg.content, list) or not any(
                self._block_type(b) == "tool_result" for b in msg.content
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

                effective_max = (
                    self._recent_max_bytes
                    if tool_id in exempt_tool_ids
                    else max_bytes
                )
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
                    max_bytes=effective_max,
                    metadata=block_metadata,
                )
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
                if self._block_type(block) not in ("tool_use", "tool_call"):
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
