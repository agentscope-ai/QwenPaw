# -*- coding: utf-8 -*-
"""Cross-model fallback wrapper for transient pre-output failures."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any, AsyncGenerator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from .model_cooldown import (
    CooldownPolicy,
    cooldown_remaining,
    is_on_cooldown,
    model_cooldown_key,
    record_model_failure,
    record_model_success,
)
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
    """Try configured models in order before any response becomes visible.

    A candidate that fails a hop is put on cooldown, so the next request
    starts from a healthy candidate instead of paying the failing model's
    retry cost again.  Cooldown never turns a slow request into a failed
    one: when every candidate is cooling down the configured order is
    used unchanged.
    """

    def __init__(
        self,
        models: list[ChatModelBase],
        cooldown: CooldownPolicy | None = None,
    ) -> None:
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
        self._cooldown = cooldown or CooldownPolicy()
        self._cooldown_keys = tuple(self._key_for(model) for model in models)
        self._thinking_omit_ids: set[str] = set()
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
        self._apply_thinking_omit_ids(model)

    @staticmethod
    def _set_model_thinking_omit_ids(
        model: ChatModelBase,
        block_ids: set[str],
    ) -> bool:
        """Apply omission state to one candidate's concrete formatter."""
        formatter = getattr(model, "formatter", None)
        if formatter is None:
            return False
        setter = getattr(formatter, "set_thinking_omit_ids", None)
        if callable(setter):
            return bool(setter(set(block_ids)))
        setattr(formatter, "_qwenpaw_omit_thinking_ids", set(block_ids))
        return True

    def _apply_thinking_omit_ids(self, model: ChatModelBase) -> bool:
        """Apply the current request-time omission state to one candidate."""
        return self._set_model_thinking_omit_ids(
            model,
            self._thinking_omit_ids,
        )

    def set_thinking_omit_ids(self, block_ids: set[str]) -> bool:
        """Persist omissions and apply them to the currently visible model."""
        self._thinking_omit_ids = {str(item) for item in block_ids}
        return self._apply_thinking_omit_ids(self._active_model)

    def _key_for(self, model: ChatModelBase) -> str:
        """Return the cooldown-registry key of one candidate."""
        return model_cooldown_key(*self._model_identity(model))

    def _request_plan(self) -> tuple[int, ...]:
        """Return the candidate indexes to try for one request, in order.

        Candidates that are cooling down are left out, so a model that
        just failed is not paid for again.  When every candidate is
        cooling down the full configured order is returned: cooldown must
        never turn a slow request into a hard failure.
        """
        if not self._cooldown.enabled:
            return tuple(range(len(self._models)))
        eligible = tuple(
            index
            for index, key in enumerate(self._cooldown_keys)
            if not is_on_cooldown(key)
        )
        if eligible:
            return eligible
        return tuple(range(len(self._models)))

    def _record_failure(self, model: ChatModelBase, exc: Exception) -> None:
        """Cool down a candidate the chain already decided to skip."""
        record_model_failure(self._key_for(model), exc, self._cooldown)

    def _record_success(self, model: ChatModelBase) -> None:
        """Clear the cooldown of a candidate that just served."""
        if not self._cooldown.enabled:
            return
        record_model_success(self._key_for(model))

    def _begin_request(self) -> tuple[Token, tuple[int, ...]]:
        """Activate the request's start model and snapshot prior state.

        The returned token MUST be passed to :meth:`_end_request` once the
        request settles (response returned, stream exhausted, or error
        raised).  The returned plan is the ordered tuple of candidate
        indexes this request may use; the start model is ``plan[0]``,
        which is the primary unless the primary is cooling down.
        """
        plan = self._request_plan()
        start = self._models[plan[0]]
        token = self._active_model_var.set(start)
        self._apply_thinking_omit_ids(start)
        return token, plan

    def _end_request(self, token: Token) -> None:
        """Restore the start model the next request will use.

        Ends by enforcing the invariant directly: between requests the
        context must expose the model the next request starts with, which
        is the primary unless the primary is cooling down.  Compaction
        sizes the context budget from it and capability learning reads
        ``model_key``, so both must see the model that will actually
        serve.  Token reset alone is not enough -- an abandoned stream
        closed late resets out of order, and CPython then silently
        restores the token's stale snapshot instead of raising.
        """
        try:
            self._active_model_var.reset(token)
        except ValueError:
            # The stream was consumed in a different context than the
            # one that started the request; fall through and repair the
            # consumer's context below.
            pass
        start = self._models[self._request_plan()[0]]
        if self._active_model_var.get() is not start:
            self._active_model_var.set(start)

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
        token: Token | None
        token, plan = self._begin_request()
        try:
            self._seed_cooldown_event(plan, fallback_events)
            for position, index in enumerate(plan):
                model = self._models[index]
                self._activate_model(model)
                try:
                    response = await model(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if not self._can_try_next(position, plan, exc):
                        raise
                    following = self._models[plan[position + 1]]
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
                        position,
                        plan,
                        args,
                        kwargs,
                        fallback_events,
                        stream_token,
                    )
                self._record_success(model)
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
        position: int,
        plan: tuple[int, ...],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        fallback_events: list[dict[str, str]],
        reset_token: Token,
    ) -> AsyncGenerator[ChatResponse, None]:
        try:
            current = stream
            current_position = position
            current_index = plan[position]
            current_model = self._models[current_index]
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
                    self._record_success(current_model)
                    return
                except Exception as exc:
                    if emitted or not self._can_try_next(
                        current_position,
                        plan,
                        exc,
                    ):
                        raise
                    fallback_error = exc
                finally:
                    await current.aclose()
                assert fallback_error is not None
                response, current_position = await self._start_fallback(
                    current_position,
                    plan,
                    fallback_error,
                    args,
                    kwargs,
                    fallback_events,
                )
                current_index = plan[current_position]
                current_model = self._models[current_index]
                if not isinstance(response, AsyncGenerator):
                    self._record_success(current_model)
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
        current_position: int,
        plan: tuple[int, ...],
        error: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        fallback_events: list[dict[str, str]],
    ) -> tuple[ChatResponse | AsyncGenerator[ChatResponse, None], int]:
        """Start the next usable fallback, skipping pre-stream failures."""
        last_error = error
        for next_position in range(current_position + 1, len(plan)):
            current_model = self._models[plan[next_position - 1]]
            next_model = self._models[plan[next_position]]
            fallback_events.append(
                self._record_fallback(current_model, next_model, last_error),
            )
            self._activate_model(next_model)
            try:
                return await next_model(*args, **kwargs), next_position
            except Exception as exc:
                last_error = exc
                if not self._can_try_next(next_position, plan, exc):
                    raise
        raise last_error

    def _can_try_next(
        self,
        position: int,
        plan: tuple[int, ...],
        exc: Exception,
    ) -> bool:
        if position + 1 >= len(plan):
            return False
        # Only the configured primary model's error class decides whether
        # fallback engages at all.  Once the chain is running, a broken
        # candidate (revoked key, deleted model, ...) must not mask the
        # healthy candidates behind it, so its own error never stops the
        # walk.
        #
        # Consequence while the primary is cooling down: it is not
        # attempted, so no candidate carries the primary's gate and a
        # request-level error (400, context overflow, content safety) from
        # the candidate tried first lets the walk continue.  That is the
        # same rule every secondary candidate already followed, and it is
        # deliberate: gating on the first attempt instead would let one
        # broken fallback hide the healthy models behind it.
        return plan[position] > 0 or is_fallback_eligible(exc)

    def _record_fallback(
        self,
        current: ChatModelBase,
        following: ChatModelBase,
        exc: Exception,
    ) -> dict[str, str]:
        """Log one hop, cool the skipped model, and publish the hop."""
        self._log_fallback(current, following, exc)
        self._record_failure(current, exc)
        event = self._fallback_event(current, following, exc)
        self._publish_fallback(event, following)
        return event

    def _seed_cooldown_event(
        self,
        plan: tuple[int, ...],
        fallback_events: list[dict[str, str]],
    ) -> None:
        """Publish the hop cooldown already decided before this request.

        The request starts from a fallback because the primary is cooling
        down.  That is a model choice users must be able to see, so it
        travels the same notice channel as an in-request hop.
        """
        if plan[0] == 0:
            return
        primary = self._models[0]
        following = self._models[plan[0]]
        logger.info(
            "Primary model %s is cooling down (%.1fs left); starting from "
            "%s",
            self._cooldown_keys[0],
            cooldown_remaining(self._cooldown_keys[0]),
            self._cooldown_keys[plan[0]],
        )
        event = self._event(primary, following, f"cooldown")
        self._publish_fallback(event, following)
        fallback_events.append(event)

    def _publish_fallback(
        self,
        event: dict[str, str],
        following: ChatModelBase,
    ) -> None:
        """Publish one hop to the per-request notice sink."""
        sink = _FALLBACK_NOTICE_SINK.get()
        if sink is None:
            return
        sink["events"].append(dict(event))
        sink["actual_model"] = self._actual_model_dict(following)

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
    def _event(
        cls,
        current: ChatModelBase,
        following: ChatModelBase,
        reason_kind: str,
    ) -> dict[str, str]:
        from_provider_id, from_model_id = cls._model_identity(current)
        to_provider_id, to_model_id = cls._model_identity(following)
        return {
            "type": "model_fallback",
            "from_provider_id": from_provider_id,
            "from_model_id": from_model_id,
            "to_provider_id": to_provider_id,
            "to_model_id": to_model_id,
            "reason_kind": reason_kind,
        }

    @classmethod
    def _fallback_event(
        cls,
        current: ChatModelBase,
        following: ChatModelBase,
        exc: Exception,
    ) -> dict[str, str]:
        return cls._event(
            current,
            following,
            classify_model_error(exc).kind,
        )

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
        token, plan = self._begin_request()
        try:
            self._seed_cooldown_event(plan, fallback_events)
            for position, index in enumerate(plan):
                model = self._models[index]
                self._activate_model(model)
                try:
                    response = await model.generate_structured_output(
                        *args,
                        **kwargs,
                    )
                except Exception as exc:
                    last_error = exc
                    if not self._can_try_next(position, plan, exc):
                        raise
                    following = self._models[plan[position + 1]]
                    fallback_events.append(
                        self._record_fallback(model, following, exc),
                    )
                    continue
                self._record_success(model)
                return self._annotate_response(
                    response,
                    fallback_events,
                    model,
                )
            assert last_error is not None
            raise last_error
        finally:
            self._end_request(token)
