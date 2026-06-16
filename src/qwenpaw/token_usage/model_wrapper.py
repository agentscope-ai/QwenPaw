# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

from collections import OrderedDict
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

    _USAGE_BY_SESSION_MAX = 256
    _usage_by_session: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    def __init__(self, provider_id: str, model: ChatModelBase) -> None:
        super().__init__(
            model_name=getattr(model, "model_name", "unknown"),
            stream=getattr(model, "stream", True),
        )
        self._model = model
        self._provider_id = provider_id

    def _record_usage(self, usage: ChatUsage | None) -> None:
        """Enqueue a usage event synchronously — never blocks the caller."""
        if usage is None:
            return
        pt = getattr(usage, "input_tokens", 0) or 0
        ct = getattr(usage, "output_tokens", 0) or 0
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
        get_token_usage_manager().enqueue(event)
        self._store_usage(pt, ct)

    @classmethod
    def peek_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        v = cls._usage_by_session.get(session_id)
        return dict(v) if v else None

    @classmethod
    def pop_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        return cls._usage_by_session.pop(session_id, None)

    def _store_usage(self, pt: int, ct: int) -> None:
        """Accumulate live usage for the current session (LRU-bounded)."""
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        if not session_id or (pt <= 0 and ct <= 0):
            return
        store = self._usage_by_session
        prev = store.get(session_id) or {}
        new_pt = int(prev.get("prompt_tokens", 0) or 0) + int(pt or 0)
        new_ct = int(prev.get("completion_tokens", 0) or 0) + int(ct or 0)
        store[session_id] = {
            "provider_id": self._provider_id,
            "model_name": self.model_name,
            "prompt_tokens": new_pt,
            "completion_tokens": new_ct,
            "total_tokens": new_pt + new_ct,
        }
        store.move_to_end(session_id)
        while len(store) > self._USAGE_BY_SESSION_MAX:
            store.popitem(last=False)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
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
