# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Literal

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage

from ..utils.model_response import safe_attr
from .buffer import _UsageEvent
from .manager import _usage_agent_id, get_token_usage_manager

# AgentScope does not expose provider cache semantics through a public
# capability API. These prefixes therefore depend on its concrete adapter MRO
# module paths. Unknown or renamed paths intentionally fail closed so cache
# metrics disappear instead of being reported with an invalid denominator.
_CACHE_USAGE_MODEL_MODULES = (
    "agentscope.model._anthropic",
    "agentscope.model._dashscope",
    "agentscope.model._deepseek",
    "agentscope.model._gemini",
    "agentscope.model._moonshot",
    "agentscope.model._openai_chat",
    "agentscope.model._openai_response",
    "agentscope.model._xai",
)


def _cache_usage_metrics(
    model: Any,
    prompt_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> tuple[bool, int]:
    """Return whether cache usage is supported and its input denominator."""
    modules = {
        cls.__module__
        for cls in type(model).__mro__
        if isinstance(getattr(cls, "__module__", None), str)
    }
    observed = any(
        module.startswith(prefix)
        for module in modules
        for prefix in _CACHE_USAGE_MODEL_MODULES
    )
    if not observed:
        return False, 0
    if any(
        module.startswith("agentscope.model._anthropic") for module in modules
    ):
        return (
            True,
            prompt_tokens + cache_read_tokens + cache_write_tokens,
        )
    if cache_read_tokens + cache_write_tokens > prompt_tokens:
        return False, 0
    return True, prompt_tokens


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

    @property
    def formatter(self) -> Any:
        """Expose the wrapped model's formatter to AgentScope."""
        return self._model.formatter

    @formatter.setter
    def formatter(self, value: Any) -> None:
        """Keep formatter updates synchronized with the wrapped model."""
        self._model.formatter = value

    def _record_usage(self, usage: ChatUsage | None) -> None:
        """Enqueue a usage event synchronously — never blocks the caller."""
        if usage is None:
            return
        pt = max(int(getattr(usage, "input_tokens", 0) or 0), 0)
        ct = max(int(getattr(usage, "output_tokens", 0) or 0), 0)
        cache_read = max(
            int(getattr(usage, "cache_input_tokens", 0) or 0),
            0,
        )
        cache_write = max(
            int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            0,
        )
        if pt <= 0 and ct <= 0:
            return
        cache_observed, cache_eligible = _cache_usage_metrics(
            self._model,
            pt,
            cache_read,
            cache_write,
        )
        if not cache_observed:
            cache_read = 0
            cache_write = 0

        event = _UsageEvent(
            provider_id=self._provider_id,
            model_name=self.model,
            prompt_tokens=pt,
            completion_tokens=ct,
            date_str=date.today().isoformat(),
            now_iso=datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds",
            ),
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cache_eligible_input_tokens=cache_eligible,
            cache_observed=cache_observed,
            agent_id=_usage_agent_id(),
        )
        # Fire-and-forget: synchronous put_nowait, ~100 ns, no await needed.
        get_token_usage_manager().enqueue(event)

        usage_data = {
            "provider_id": self._provider_id,
            "model_name": self.model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cache_eligible_input_tokens": cache_eligible,
            "cache_observed": cache_observed,
            "cache_hit_rate": (
                cache_read / cache_eligible * 100
                if cache_eligible > 0
                else None
            ),
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
            previous = TokenRecordingModelWrapper._usage_by_session.get(
                session_id,
            )
            if previous is None:
                TokenRecordingModelWrapper._usage_by_session[
                    session_id
                ] = usage
                return
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "cache_eligible_input_tokens",
            ):
                usage[key] = int(previous.get(key, 0) or 0) + int(
                    usage.get(key, 0) or 0,
                )
            usage["total_tokens"] = (
                usage["prompt_tokens"] + usage["completion_tokens"]
            )
            usage["cache_observed"] = bool(
                previous.get("cache_observed", False)
                or usage.get("cache_observed", False),
            )
            cache_eligible = usage["cache_eligible_input_tokens"]
            usage["cache_hit_rate"] = (
                usage["cache_read_tokens"] / cache_eligible * 100
                if cache_eligible > 0
                else None
            )
            TokenRecordingModelWrapper._usage_by_session[session_id] = usage

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        result = await self._model.generate_structured_output(*args, **kwargs)
        self._record_usage(safe_attr(result, "usage"))
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
        self._record_usage(safe_attr(result, "usage"))
        return result

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
    ) -> AsyncGenerator[ChatResponse, None]:
        last_usage: ChatUsage | None = None
        try:
            async for chunk in stream:
                usage = safe_attr(chunk, "usage")
                if usage is not None:
                    last_usage = usage
                yield chunk
        finally:
            await stream.aclose()
            self._record_usage(last_usage)
