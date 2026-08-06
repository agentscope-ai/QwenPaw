# -*- coding: utf-8 -*-
"""Cross-model fallback wrapper for transient pre-output failures."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, AsyncGenerator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from .model_error_policy import classify_model_error, is_fallback_eligible

logger = logging.getLogger(__name__)


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
        for index, model in enumerate(self._models):
            self._activate_model(model)
            try:
                response = await model(*args, **kwargs)
            except Exception as exc:
                last_error = exc
                if not self._can_try_next(index, exc):
                    raise
                following = self._models[index + 1]
                self._log_fallback(model, following, exc)
                fallback_events.append(
                    self._fallback_event(model, following, exc),
                )
                continue
            if isinstance(response, AsyncGenerator):
                return self._consume_with_fallback(
                    response,
                    index,
                    args,
                    kwargs,
                    fallback_events,
                )
            return self._annotate_response(
                response,
                fallback_events,
                model,
            )
        assert last_error is not None
        raise last_error

    async def _consume_with_fallback(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        index: int,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        fallback_events: list[dict[str, str]],
    ) -> AsyncGenerator[ChatResponse, None]:
        current = stream
        current_index = index
        current_model = self._models[index]
        emitted = False
        while True:
            fallback_error: Exception | None = None
            try:
                async for chunk in current:
                    emitted = emitted or bool(chunk.content)
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
            self._log_fallback(current_model, next_model, last_error)
            fallback_events.append(
                self._fallback_event(current_model, next_model, last_error),
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
        return index + 1 < len(self._models) and is_fallback_eligible(exc)

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
            provider_id, model_id = FallbackChatModel._model_identity(
                active_model,
            )
            metadata["qwenpaw_actual_model"] = {
                "provider_id": provider_id,
                "model_id": model_id,
                "context_size": getattr(
                    active_model,
                    "context_size",
                    32_768,
                ),
            }
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
                self._log_fallback(model, following, exc)
                fallback_events.append(
                    self._fallback_event(model, following, exc),
                )
        assert last_error is not None
        raise last_error
