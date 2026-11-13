# -*- coding: utf-8 -*-
"""Per-operation broker gate for raw ControlLink calls (ADR D8)."""

from __future__ import annotations
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from ..errors import BrowserError, ErrorCategory, ErrorCause
from ..runtime.side_effects import SideEffectClass, classify_side_effect
from ..sdk.execution_context import get_execution_context
from .approval import Decision

ApprovalClient = Callable[
    ...,
    Awaitable[Mapping[str, Any] | None],
]

_TIMEOUT_CODE = "bridge_request_timeout"
_UNCERTAIN_ACTION = (
    "This action may already have taken effect. Call snapshot() or "
    "current_surface() to observe the real page state first. If the page "
    "shows it did not happen, you may run it once more. If the page cannot "
    "tell you, do not repeat it - report the uncertainty instead."
)


def _typed_transport_uncertainty(
    method: str,
    exc: Exception,
) -> BaseException:
    """Type a mutating verb's transport timeout as an uncertain outcome."""
    if str(getattr(exc, "browser_error_code", "")) != _TIMEOUT_CODE:
        return exc
    if classify_side_effect(method) is SideEffectClass.READ:
        return exc
    return BrowserError(
        category=ErrorCategory.FATAL,
        cause=ErrorCause.TIMING,
        suggested_action=_UNCERTAIN_ACTION,
        reason=f"{method} was not confirmed before the deadline",
        detail=str(exc),
    )


class Broker:
    def __init__(
        self,
        approval_client: ApprovalClient | None = None,
    ) -> None:
        self._approve = approval_client

    async def authorize(
        self,
        ctx: Any,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        if ctx is not None and not ctx.owner.is_valid():
            raise BrowserError(
                category=ErrorCategory.ASK_HUMAN,
                suggested_action="ask_human",
                reason="owner is not valid",
            )
        origin = getattr(ctx, "origin", "*") if ctx is not None else "*"
        origin = origin or "*"
        category = classify_side_effect(method, params).value
        if category == "read" or self._approve is None:
            return
        verdict = await self._approve(
            origin=origin,
            method=method,
            params=dict(params or {}),
        )
        if verdict is None or verdict.get("decision") == Decision.ALLOW.value:
            return
        raise BrowserError(
            category=ErrorCategory.ASK_HUMAN,
            suggested_action="request user approval before this action",
            reason=f"approval denied ({verdict.get('decision')})",
        )


class BrokeredControlLink:
    def __init__(self, inner: Any, broker: Broker) -> None:
        self._inner = inner
        self._broker = broker

    @property
    def variant(self) -> str:
        return self._inner.variant

    @property
    def supported_contexts(self):
        return self._inner.supported_contexts

    def is_available(self) -> bool:
        return self._inner.is_available()

    async def request(self, method, params, *, timeout=None):
        await self._broker.authorize(
            get_execution_context(),
            method,
            dict(params),
        )
        try:
            return await self._inner.request(method, params, timeout=timeout)
        except Exception as exc:
            raise _typed_transport_uncertainty(method, exc) from exc

    def on_event(self, sink):
        return self._inner.on_event(sink)

    def __getattr__(self, name):
        return getattr(self._inner, name)
