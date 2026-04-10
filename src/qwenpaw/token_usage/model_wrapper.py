# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

from datetime import date
from typing import Any, AsyncGenerator, Literal, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel

from .manager import get_token_usage_manager


class TokenRecordingModelWrapper(ChatModelBase):
    """Wraps a ChatModelBase to record token usage on each call."""

    _usage_by_session: dict[str, dict[str, Any]] = {}

    def __init__(self, provider_id: str, model: ChatModelBase) -> None:
        super().__init__(
            model_name=getattr(model, "model_name", "unknown"),
            stream=getattr(model, "stream", True),
        )
        self._model = model
        self._provider_id = provider_id

    async def _record_usage(self, usage: ChatUsage | None) -> None:
        if usage is None:
            return
        pt = getattr(usage, "input_tokens", 0) or 0
        ct = getattr(usage, "output_tokens", 0) or 0
        if pt > 0 or ct > 0:
            await get_token_usage_manager().record(
                provider_id=self._provider_id,
                model_name=self.model_name,
                prompt_tokens=pt,
                completion_tokens=ct,
                at_date=date.today(),
            )
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

    def _store_usage(self, usage: dict[str, Any] | None) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        if session_id and usage:
            TokenRecordingModelWrapper._usage_by_session[session_id] = usage

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        result = await self._model(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            structured_model=structured_model,
            **kwargs,
        )

        if isinstance(result, AsyncGenerator):
            return self._wrap_stream(result)
        await self._record_usage(getattr(result, "usage", None))
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
        await self._record_usage(last_usage)
