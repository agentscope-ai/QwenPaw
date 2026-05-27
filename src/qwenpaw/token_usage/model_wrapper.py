# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Literal, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel

from .buffer import _UsageEvent
from .manager import get_token_usage_manager


class TokenRecordingModelWrapper(ChatModelBase):
    """Wraps a ChatModelBase to record token usage on each call."""

    # Pending usage events for channel/UI reporting. `pop_usage_for_session`
    # intentionally consumes these so the same usage is emitted once.
    _usage_by_session: dict[str, dict[str, Any]] = {}
    # Retained latest usage for non-destructive consumers such as context
    # estimation. This survives UI pops and is keyed by session.
    _latest_usage_by_session: dict[str, dict[str, Any]] = {}
    _usage_sequence: int = 0

    def __init__(self, provider_id: str, model: ChatModelBase) -> None:
        super().__init__(
            model_name=getattr(model, "model_name", "unknown"),
            stream=getattr(model, "stream", True),
        )
        self._model = model
        self._provider_id = provider_id

    @staticmethod
    def _read_token_count(usage: Any, *keys: str) -> int:
        """Read a non-negative token count from attr- or dict-style usage."""
        for key in keys:
            value = (
                usage.get(key)
                if isinstance(usage, Mapping)
                else getattr(usage, key, None)
            )
            if value is None:
                continue
            try:
                return max(int(value), 0)
            except (TypeError, ValueError):
                continue
        return 0

    def _record_usage(
        self,
        usage: ChatUsage | Mapping[str, Any] | None,
    ) -> None:
        """Enqueue a usage event synchronously — never blocks the caller."""
        if usage is None:
            return
        pt = self._read_token_count(
            usage,
            "input_tokens",
            "prompt_tokens",
            "prompt_eval_count",
        )
        ct = self._read_token_count(
            usage,
            "output_tokens",
            "completion_tokens",
            "eval_count",
        )
        if pt <= 0 and ct <= 0:
            return

        event = _UsageEvent(
            provider_id=self._provider_id,
            model_name=self.model_name,
            prompt_tokens=pt,
            completion_tokens=ct,
            date_str=date.today().isoformat(),
            now_iso=datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds",
            ),
        )
        # Fire-and-forget: synchronous put_nowait, ~100 ns, no await needed.
        get_token_usage_manager().enqueue(event)

        usage_data = {
            "provider_id": self._provider_id,
            "model_name": self.model_name,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        }
        self._store_usage(usage_data)

    @classmethod
    def pop_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        return cls._usage_by_session.pop(session_id, None)

    @classmethod
    def peek_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        usage = cls._latest_usage_by_session.get(session_id)
        return dict(usage) if usage else None

    def _store_usage(self, usage: dict[str, Any] | None) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        if session_id and usage:
            TokenRecordingModelWrapper._usage_sequence += 1
            usage_with_sequence = {
                **usage,
                "sequence": TokenRecordingModelWrapper._usage_sequence,
            }
            TokenRecordingModelWrapper._usage_by_session[
                session_id
            ] = usage_with_sequence
            TokenRecordingModelWrapper._latest_usage_by_session[
                session_id
            ] = usage_with_sequence

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
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
            structured_model=structured_model,
            **kwargs,
        )

        if isinstance(result, AsyncGenerator):
            return self._wrap_stream(result)
        self._record_usage(getattr(result, "usage", None))
        return result

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
    ) -> AsyncGenerator[ChatResponse, None]:
        last_usage: ChatUsage | None = None
        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                last_usage = chunk.usage
            yield chunk
        self._record_usage(last_usage)
