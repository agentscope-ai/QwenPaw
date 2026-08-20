# -*- coding: utf-8 -*-
"""Cross-model fallback wrapper for transient pre-output failures."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any, AsyncGenerator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from .model_error_policy import classify_model_error, is_fallback_eligible
from .stream_progress import has_meaningful_stream_content

logger = logging.getLogger(__name__)

_FALLBACK_NOTICE_SINK: ContextVar[dict[str, Any] | None] = ContextVar(
    "qwenpaw_fallback_notice_sink",
    default=None,
)


def install_fallback_notice_sink() -> dict[str, Any]:
    """Install a per-request sink for model-fallback transparency data.

    The pinned agentscope release drops ``ChatResponse.metadata`` when
    converting model output into agent events, so annotating responses
    alone never reaches the Console or channel notifiers.  The reply
    loop installs this sink before iterating events (same task context
    as the model call); ``FallbackChatModel`` publishes each fallback
    into it, and the agent re-attaches the data onto outgoing events.
    """
    sink: dict[str, Any] = {"events": [], "actual_model": None}
    _FALLBACK_NOTICE_SINK.set(sink)
    return sink


class FallbackChatModel(ChatModelBase):
    """Try configured models in order before any response becomes visible."""

    def __init__(self, models: list[ChatModelBase]) -> None:
        if not models:
            raise ValueError("FallbackChatModel requires at least one model")
        primary = models[0]
        self._active_model_var: ContextVar[ChatModelBase] = ContextVar(
            f"fallback_active_model_{id(self)}",
            default=primary,
        )
        self._default_model = getattr(primary, "model", "unknown")
        self._default_context_size = getattr(
            primary,
            "context_size",
            32_768,
        )
        super().__init__(
            credential=getattr(primary, "credential", None),
            model=getattr(primary, "model", "unknown"),
            parameters=getattr(primary, "parameters", None)
            or ChatModelBase.Parameters(),
            stream=getattr(primary, "stream", True),
            context_size=getattr(primary, "context_size", 32_768),
        )
        self._models = models
        self._activate_model(primary)

    @property
    def _active_model(self) -> ChatModelBase:
        """Return the model active in the current request context."""
        return self._active_model_var.get()

    @_active_model.setter
    def _active_model(self, model: ChatModelBase) -> None:
        self._active_model_var.set(model)

    @property
    def _inner(self) -> ChatModelBase:
        """Expose the request-local active model for wrapper traversal."""
        return self._active_model

    @_inner.setter
    def _inner(self, model: ChatModelBase) -> None:
        self._active_model = model

    @property
    def formatter(self) -> Any:
        """Expose the serving model's formatter to AgentScope.

        AgentScope reads media support and formats messages off the
        outermost model, which is this class once fallbacks are
        configured.  ``ChatModelBase`` defines no formatter of its own, so
        without this forwarding the attribute lookup raises.
        """
        active = getattr(self, "_active_model_var", None)
        if active is None:
            raise AttributeError("formatter")
        return active.get().formatter

    @formatter.setter
    def formatter(self, value: Any) -> None:
        """Route formatter installs down to the serving model."""
        self._active_model.formatter = value

    @property
    def model(self) -> str:
        """Return the current request's actual model name."""
        active = getattr(self, "_active_model_var", None)
        if active is not None:
            return str(getattr(active.get(), "model", self._default_model))
        return self._default_model

    @model.setter
    def model(self, value: str) -> None:
        self._default_model = value

    @property
    def context_size(self) -> int:
        """Return the current request's actual context window."""
        active = getattr(self, "_active_model_var", None)
        if active is not None:
            return int(
                getattr(
                    active.get(),
                    "context_size",
                    self._default_context_size,
                ),
            )
        return self._default_context_size

    @context_size.setter
    def context_size(self, value: int) -> None:
        self._default_context_size = value

    def _activate_model(self, model: ChatModelBase) -> None:
        """Expose routing metadata from the model handling the request."""
        self._active_model = model

    def _begin_request(self) -> Token:
        """Activate the primary model and snapshot the pre-request state.

        The returned token MUST be passed to :meth:`_end_request` once the
        request settles (response returned, stream exhausted, or error
        raised).  Without the reset, the last-served fallback would leak
        into the between-requests window where the compaction manager
        sizes the context budget and capability learning reads
        ``model_key`` -- both must see the primary model, because the
        next request always tries the primary first.
        """
        return self._active_model_var.set(self._models[0])

    def _end_request(self, token: Token) -> None:
        """Restore the pre-request active model.

        Ends by enforcing the invariant directly: between requests the
        context must expose the primary model.  Token reset alone is not
        enough -- an abandoned stream closed late resets out of order,
        and CPython then silently restores the token's stale snapshot
        instead of raising.
        """
        try:
            self._active_model_var.reset(token)
        except ValueError:
            # The stream was consumed in a different context than the
            # one that started the request; fall through and repair the
            # consumer's context below.
            pass
        if self._active_model_var.get() is not self._models[0]:
            self._active_model_var.set(self._models[0])

    @property
    def model_key(self) -> str:
        """Return the key for the model handling the current request."""
        key = getattr(self._active_model, "model_key", None)
        name = getattr(self._active_model, "model", None)
        return str(key or name or self.model)

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        last_error: Exception | None = None
        fallback_events: list[dict[str, str]] = []
        token: Token | None = self._begin_request()
        try:
            for index, model in enumerate(self._models):
                self._activate_model(model)
                try:
                    response = await model(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if not self._can_try_next(index, exc):
                        raise
                    following = self._models[index + 1]
                    fallback_events.append(
                        self._record_fallback(model, following, exc),
                    )
                    continue
                if isinstance(response, AsyncGenerator):
                    stream_token = token
                    assert stream_token is not None
                    token = None  # the stream wrapper owns the reset now
                    return self._consume_with_fallback(
                        response,
                        index,
                        args,
                        kwargs,
                        fallback_events,
                        stream_token,
                    )
                return self._annotate_response(
                    response,
                    fallback_events,
                    model,
                )
            assert last_error is not None
            raise last_error
        finally:
            if token is not None:
                self._end_request(token)

    async def _consume_with_fallback(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        index: int,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        fallback_events: list[dict[str, str]],
        reset_token: Token,
    ) -> AsyncGenerator[ChatResponse, None]:
        try:
            current = stream
            current_index = index
            current_model = self._models[index]
            emitted = False
            while True:
                fallback_error: Exception | None = None
                try:
                    async for chunk in current:
                        emitted = emitted or has_meaningful_stream_content(
                            chunk.content,
                        )
                        yield self._annotate_response(
                            chunk,
                            fallback_events,
                            current_model,
                        )
                        fallback_events = []
                    return
                except Exception as exc:
                    if emitted or not self._can_try_next(current_index, exc):
                        raise
                    fallback_error = exc
                finally:
                    await current.aclose()
                assert fallback_error is not None
                response, current_index = await self._start_fallback(
                    current_index,
                    fallback_error,
                    args,
                    kwargs,
                    fallback_events,
                )
                current_model = self._models[current_index]
                if not isinstance(response, AsyncGenerator):
                    yield self._annotate_response(
                        response,
                        fallback_events,
                        current_model,
                    )
                    return
                current = response
        finally:
            self._end_request(reset_token)

    async def _start_fallback(
        self,
        current_index: int,
        error: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        fallback_events: list[dict[str, str]],
    ) -> tuple[ChatResponse | AsyncGenerator[ChatResponse, None], int]:
        """Start the next usable fallback, skipping pre-stream failures."""
        last_error = error
        for next_index in range(current_index + 1, len(self._models)):
            current_model = self._models[next_index - 1]
            next_model = self._models[next_index]
            fallback_events.append(
                self._record_fallback(current_model, next_model, last_error),
            )
            self._activate_model(next_model)
            try:
                return await next_model(*args, **kwargs), next_index
            except Exception as exc:
                last_error = exc
                if not self._can_try_next(next_index, exc):
                    raise
        raise last_error

    def _can_try_next(self, index: int, exc: Exception) -> bool:
        if index + 1 >= len(self._models):
            return False
        # Only the primary model's error class decides whether fallback
        # engages at all.  Once the chain is running, a broken candidate
        # (revoked key, deleted model, ...) must not mask the healthy
        # candidates behind it, so its own error never stops the walk.
        return index > 0 or is_fallback_eligible(exc)

    def _record_fallback(
        self,
        current: ChatModelBase,
        following: ChatModelBase,
        exc: Exception,
    ) -> dict[str, str]:
        """Log one fallback hop and publish it to the request sink."""
        self._log_fallback(current, following, exc)
        event = self._fallback_event(current, following, exc)
        sink = _FALLBACK_NOTICE_SINK.get()
        if sink is not None:
            sink["events"].append(dict(event))
            sink["actual_model"] = self._actual_model_dict(following)
        return event

    @staticmethod
    def _model_identity(model: ChatModelBase) -> tuple[str, str]:
        key = str(getattr(model, "model_key", "") or "")
        name = str(getattr(model, "model", "unknown") or "unknown")
        if ":" not in key:
            provider_id = str(getattr(model, "_provider_id", "") or "")
            return provider_id, key or name
        provider_id, model_id = key.split(":", maxsplit=1)
        return provider_id, model_id

    @classmethod
    def _fallback_event(
        cls,
        current: ChatModelBase,
        following: ChatModelBase,
        exc: Exception,
    ) -> dict[str, str]:
        from_provider_id, from_model_id = cls._model_identity(current)
        to_provider_id, to_model_id = cls._model_identity(following)
        return {
            "type": "model_fallback",
            "from_provider_id": from_provider_id,
            "from_model_id": from_model_id,
            "to_provider_id": to_provider_id,
            "to_model_id": to_model_id,
            "reason_kind": classify_model_error(exc).kind,
        }

    @classmethod
    def _actual_model_dict(cls, active_model: ChatModelBase) -> dict[str, Any]:
        provider_id, model_id = cls._model_identity(active_model)
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "context_size": getattr(
                active_model,
                "context_size",
                32_768,
            ),
        }

    @staticmethod
    def _annotate_response(
        response: ChatResponse,
        events: list[dict[str, str]],
        active_model: ChatModelBase | None = None,
    ) -> ChatResponse:
        if not events and active_model is None:
            return response
        metadata = dict(getattr(response, "metadata", None) or {})
        if events:
            metadata["qwenpaw_model_fallbacks"] = list(events)
        if active_model is not None:
            metadata[
                "qwenpaw_actual_model"
            ] = FallbackChatModel._actual_model_dict(active_model)
        response.metadata = metadata
        return response

    @staticmethod
    def _log_fallback(
        current: ChatModelBase,
        following: ChatModelBase,
        exc: Exception,
    ) -> None:
        logger.warning(
            "Model %s failed before output; falling back to %s: %s",
            getattr(current, "model", "unknown"),
            getattr(following, "model", "unknown"),
            exc,
        )

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        last_error: Exception | None = None
        fallback_events: list[dict[str, str]] = []
        token = self._begin_request()
        try:
            for index, model in enumerate(self._models):
                self._activate_model(model)
                try:
                    response = await model.generate_structured_output(
                        *args,
                        **kwargs,
                    )
                    return self._annotate_response(
                        response,
                        fallback_events,
                        model,
                    )
                except Exception as exc:
                    last_error = exc
                    if not self._can_try_next(index, exc):
                        raise
                    following = self._models[index + 1]
                    fallback_events.append(
                        self._record_fallback(model, following, exc),
                    )
            assert last_error is not None
            raise last_error
        finally:
            self._end_request(token)
