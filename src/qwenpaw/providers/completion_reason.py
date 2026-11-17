# -*- coding: utf-8 -*-
"""Keep provider termination details across AgentScope accumulation."""

from contextvars import ContextVar
from inspect import isasyncgen
from typing import Any

from agentscope.model._model_response import FinishedReason

from .adapters.usage import value

COMPLETION_METADATA_KEY = f"qwenpaw_model_completion"
_completion_state: ContextVar[dict | None] = ContextVar(
    f"model_completion_state",
    default=None,
)


def _capture_reason(raw: Any, state: dict) -> None:
    """Capture the first choice's explicit provider termination reason."""
    choices = value(raw, f"choices") or []
    if choices:
        reason = value(choices[0], f"finish_reason")
        if isinstance(reason, str) and reason:
            state[f"finish_reason"] = reason


def _attach_completion(response: Any, state: dict) -> None:
    """Annotate completion without changing interruption semantics."""
    reason = state.get(f"finish_reason")
    if not reason or response.finished_reason == FinishedReason.INTERRUPTED:
        return
    response.metadata = {
        **response.metadata,
        COMPLETION_METADATA_KEY: {
            f"finish_reason": reason,
            f"truncated": reason == f"length",
        },
    }


class _CompletionStream:
    """Observe wire chunks without changing their content or ownership."""

    def __init__(self, stream, state):
        self.stream = stream
        self.state = state
        self.active = None

    @property
    def response(self):
        """Expose the transport response used by nested SDK adapters."""
        return getattr(self.stream, f"response", None)

    async def __aenter__(self):
        self.active = await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self.active.__anext__()
        _capture_reason(chunk, self.state)
        return chunk


class CompletionReasonMixin:
    """Restore finish reasons omitted by the pinned Chat Completions SDK."""

    async def __call__(self, *args, **kwargs):
        state: dict = {}
        token = _completion_state.set(state)
        try:
            response = await super().__call__(*args, **kwargs)
        finally:
            _completion_state.reset(token)
        if not isasyncgen(response):
            _attach_completion(response, state)
            return response
        return self._relay_completion(response, state)

    async def _relay_completion(self, stream, state):
        """Scope each pull separately for task-per-event SSE consumers."""
        try:
            while True:
                token = _completion_state.set(state)
                try:
                    chunk = await anext(stream)
                except StopAsyncIteration:
                    return
                finally:
                    _completion_state.reset(token)
                if chunk.is_last:
                    _attach_completion(chunk, state)
                yield chunk
        finally:
            token = _completion_state.set(state)
            try:
                try:
                    await stream.aclose()
                finally:
                    parser = state.pop(f"parser", None)
                    if parser is not None:
                        await parser.aclose()
            finally:
                _completion_state.reset(token)

    async def _parse_stream_response(self, start_datetime, response):
        state = _completion_state.get()
        if state is None:
            state = {}
        captured = _CompletionStream(response, state)
        parser = super()._parse_stream_response(
            start_datetime,
            captured,
        )
        state[f"parser"] = parser
        try:
            async for parsed in parser:
                yield parsed
        finally:
            state.pop(f"parser", None)
            await parser.aclose()

    def _parse_completion_response(
        self,
        start_datetime,
        response,
        *args,
        **kwargs,
    ):
        state = _completion_state.get()
        if state is None:
            state = {}
        _capture_reason(response, state)
        parsed = super()._parse_completion_response(
            start_datetime,
            response,
            *args,
            **kwargs,
        )
        _attach_completion(parsed, state)
        return parsed
