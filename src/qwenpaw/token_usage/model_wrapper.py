# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

import logging
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Literal

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage

from ..utils.model_response import safe_attr
from .buffer import _UsageEvent
from .manager import _usage_agent_id, get_token_usage_manager

logger = logging.getLogger(__name__)

# Must stay aligned with agents.utils.tool_message_utils._TOOL_CALL_TYPES.
_TOOL_CALL_TYPES = ("tool_use", "tool_call")


def _content_blocks(result: Any) -> Sequence[Any] | None:
    """Return non-empty content blocks, or None if content is absent."""
    content = safe_attr(result, "content")
    if isinstance(content, (str, bytes)) or not isinstance(content, Sequence):
        return None
    if not content:
        return None
    return content


def _tool_ids(result: Any) -> tuple[set[str], int] | None:
    """Named tool ids and anonymous count, or None if content is absent."""
    content = _content_blocks(result)
    if content is None:
        return None
    named: set[str] = set()
    anon = 0
    for block in content:
        if safe_attr(block, "type") not in _TOOL_CALL_TYPES:
            continue
        tid = (
            safe_attr(block, "id")
            or safe_attr(block, "tool_call_id")
            or safe_attr(block, "call_id")
        )
        if tid:
            named.add(str(tid))
        else:
            anon += 1
    return named, anon


def _count_tool_calls(result: Any) -> int | None:
    """Count tool_call blocks in this chunk, or None if content is absent."""
    ids = _tool_ids(result)
    if ids is None:
        return None
    named, anon = ids
    return len(named) + anon


class TokenRecordingModelWrapper(ChatModelBase):
    """Wraps a ChatModelBase to record token usage on each call."""

    _usage_by_session: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        provider_id: str,
        model: ChatModelBase,
        compact_threshold: float | None = None,
    ) -> None:
        # agentscope 2.0 ChatModelBase requires credential/model/parameters.
        # Forward the wrapped model's own values so the base attributes stay
        # consistent (some downstream code reads ``self.model`` for logging).
        super().__init__(
            credential=getattr(model, "credential", None),
            model=getattr(model, "model", "unknown"),
            parameters=getattr(model, "parameters", None)
            or ChatModelBase.Parameters(),
            stream=getattr(model, "stream", True),
            context_size=getattr(model, "context_size", 32768),
        )
        self._model = model
        # AgentScope 2.0.6 consults ``agent.model.formatter`` before the
        # model call to validate incoming media blocks.  ChatModelBase does
        # not define that attribute itself, so transparent wrappers must
        # preserve the concrete provider model's formatter explicitly.
        formatter = getattr(model, "formatter", None)
        if formatter is not None:
            self.formatter = formatter
        self._provider_id = provider_id
        # Auto-compaction threshold (fraction of the window) for the UI, or
        # None when compaction is disabled/unknown.
        self._compact_threshold = compact_threshold

    def _record_usage(
        self,
        usage: ChatUsage | None,
        result: Any | None = None,
        tool_calls: int | None = None,
    ) -> None:
        """Enqueue a usage event synchronously — never blocks the caller."""
        if usage is None:
            return
        pt = getattr(usage, "input_tokens", 0) or 0
        ct = getattr(usage, "output_tokens", 0) or 0
        if pt <= 0 and ct <= 0:
            return

        if tool_calls is None:
            try:
                tool_calls = _count_tool_calls(result) or 0
            except Exception:
                logger.debug(
                    "token_usage: failed to count tool calls",
                    exc_info=True,
                )
                tool_calls = 0

        event = _UsageEvent(
            provider_id=self._provider_id,
            model_name=self.model,
            prompt_tokens=pt,
            completion_tokens=ct,
            date_str=date.today().isoformat(),
            now_iso=datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds",
            ),
            agent_id=_usage_agent_id(),
            tool_calls=tool_calls,
        )
        # Fire-and-forget: synchronous put_nowait, ~100 ns, no await needed.
        get_token_usage_manager().enqueue(event)

        usage_data = {
            "provider_id": self._provider_id,
            "model_name": self.model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            # Context window of the wrapped model, so the UI can show how full
            # the *current* context is (prompt_tokens / context_size), distinct
            # from the cumulative session totals. 0 = unknown.
            "context_size": int(getattr(self._model, "context_size", 0) or 0),
            # Auto-compaction threshold (fraction of the window) so the UI can
            # mark where context gets evicted. None = disabled/unknown.
            "compact_threshold": self._compact_threshold,
        }
        self._store_usage(usage_data)

    @classmethod
    def pop_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        return cls._usage_by_session.pop(session_id, None)

    def _store_usage(self, usage: dict[str, Any] | None) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        if session_id and usage:
            TokenRecordingModelWrapper._usage_by_session[session_id] = usage

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        result = await self._model.generate_structured_output(*args, **kwargs)
        self._record_usage(safe_attr(result, "usage"), result)
        return result

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        # agentscope 2.0 routes structured output through
        # ``generate_structured_output`` instead of a ``__call__`` kwarg, and
        # provider SDKs (anthropic, openai) reject unknown kwargs. Drop the
        # 1.x ``structured_model`` if a caller still passes it.
        kwargs.pop("structured_model", None)

        # Fix: Omit tool_choice="auto" for vLLM compatibility
        # vLLM without --enable-auto-tool-choice will reject requests when
        # tool_choice="auto" is present, even if tools are provided.
        # By omitting tool_choice when it's "auto", we bypass the check
        # while keeping tools available for correct tool calling behavior.
        if tool_choice == "auto":
            tool_choice = None

        result = await self._model(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        if isinstance(result, AsyncGenerator):
            return self._wrap_stream(result)
        self._record_usage(safe_attr(result, "usage"), result)
        return result

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
    ) -> AsyncGenerator[ChatResponse, None]:
        last_usage: ChatUsage | None = None
        last_complete_calls: int | None = None
        seen: set[str] = set()
        anon = 0
        count_warned = False
        async for chunk in stream:
            usage = safe_attr(chunk, "usage")
            if usage is not None:
                last_usage = usage
            try:
                ids = _tool_ids(chunk)
                if ids is not None:
                    named, n_anon = ids
                    if named or n_anon:
                        # Last frame with tools: AgentScope snapshot.
                        # 0-tool last unions deltas (last-is-delta compat).
                        if safe_attr(chunk, "is_last"):
                            last_complete_calls = len(named) + n_anon
                        else:
                            seen |= named
                            anon += n_anon
            except Exception:
                if not count_warned:
                    count_warned = True
                    logger.debug(
                        "token_usage: failed to count stream tool calls",
                        exc_info=True,
                    )
            yield chunk
        if last_complete_calls is not None:
            self._record_usage(last_usage, tool_calls=last_complete_calls)
        else:
            self._record_usage(last_usage, tool_calls=len(seen) + anon)
