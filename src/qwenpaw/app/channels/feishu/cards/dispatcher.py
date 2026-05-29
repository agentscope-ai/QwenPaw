# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Feishu interactive card dispatcher (routing-only).

Two lookup tables drive the dispatch:

* ``_by_message_type`` — outbound: ``metadata.message_type`` → ``render``.
* ``_by_action_type``  — inbound: button ``value.type``      → ``handle``.

Public entry-points (called by :class:`~..channel.FeishuChannel`):
:meth:`try_send_card_for_event` and :meth:`handle_card_action`.

Adding a new card kind: drop a module exposing ``NAME`` /
``MESSAGE_TYPE`` / ``ACTION_TYPE`` plus ``render`` / ``handle``,
then register it in :meth:`_register_kinds`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
)

from . import context

try:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTrigger,
        P2CardActionTriggerResponse,
    )
except ImportError:  # pragma: no cover - optional dependency
    P2CardActionTrigger = None  # type: ignore[assignment]
    P2CardActionTriggerResponse = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    from ..channel import FeishuChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Registry record
# ---------------------------------------------------------------------

# Outbound: given (channel, to_handle, event, send_meta, meta, **kw)
# build + send the card.  Returns True if sent.
RenderFn = Callable[..., Awaitable[bool]]

# Inbound: given (channel, event, action_value) produce the synchronous
# card response for lark_oapi.
HandleFn = Callable[
    ["FeishuChannel", Any, Dict[str, Any]],
    "P2CardActionTriggerResponse",
]


@dataclass(frozen=True)
class CardKind:
    """Describes one kind of interactive card and its handlers."""

    name: str
    message_type: str  # matches ``metadata.message_type`` (outbound)
    action_type: str  # matches button ``value.type`` (inbound)
    render: RenderFn
    handle: HandleFn


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------


class FeishuCardHandler:
    """Routing-only dispatcher for Feishu interactive cards.

    Holds a back-reference to the owning :class:`FeishuChannel` and
    piggybacks on its primitives without duplicating state.
    """

    def __init__(self, channel: "FeishuChannel") -> None:
        self._channel = channel
        self._by_message_type: Dict[str, CardKind] = {}
        self._by_action_type: Dict[str, CardKind] = {}
        self._register_kinds()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, kind: CardKind) -> None:
        """Install a card kind into both lookup tables."""
        if kind.message_type in self._by_message_type:
            logger.warning(
                "feishu card: message_type %r already registered, overriding",
                kind.message_type,
            )
        if kind.action_type in self._by_action_type:
            logger.warning(
                "feishu card: action_type %r already registered, overriding",
                kind.action_type,
            )
        self._by_message_type[kind.message_type] = kind
        self._by_action_type[kind.action_type] = kind

    def _register_kinds(self) -> None:
        """Register every built-in card kind."""
        from . import tool_guard

        self.register(
            CardKind(
                name=tool_guard.NAME,
                message_type=tool_guard.MESSAGE_TYPE,
                action_type=tool_guard.ACTION_TYPE,
                render=tool_guard.render,
                handle=tool_guard.handle,
            ),
        )

    # ==================================================================
    # Public entry-points (called by FeishuChannel)
    # ==================================================================

    async def try_send_card_for_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        *,
        compact: bool = False,
    ) -> bool:
        """Render ``event`` as an interactive card if any kind matches.

        Returns ``True`` when a card was sent (the caller should skip
        the default text/post rendering), ``False`` otherwise.

        When ``compact=True`` (streaming mode), the render function
        receives ``compact=True`` so it can produce a minimal card.
        """
        meta = context.extract_meta(event)
        if meta is None:
            return False
        kind = self._by_message_type.get(str(meta.get("message_type") or ""))
        if kind is None:
            return False
        try:
            return await kind.render(
                self._channel,
                to_handle,
                event,
                send_meta,
                meta,
                compact=compact,
            )
        except Exception:  # pragma: no cover
            logger.exception(
                "feishu card render failed: kind=%s",
                kind.name,
            )
            return False

    def handle_card_action(
        self,
        data: "P2CardActionTrigger",
    ) -> "P2CardActionTriggerResponse":
        """Sync entry for ``card.action.trigger`` (called from WS thread).

        Must return a :class:`P2CardActionTriggerResponse` synchronously.
        """
        # Guard against cross-instance dispatch.
        header = getattr(data, "header", None)
        event_app_id = getattr(header, "app_id", None)
        if event_app_id and event_app_id != self._channel.app_id:
            return P2CardActionTriggerResponse({})

        event = getattr(data, "event", None)
        action = getattr(event, "action", None) if event else None
        action_value = getattr(action, "value", None) if action else None
        if not isinstance(action_value, dict):
            return P2CardActionTriggerResponse({})

        kind = self._by_action_type.get(str(action_value.get("type") or ""))
        if kind is None:
            return P2CardActionTriggerResponse({})

        try:
            return kind.handle(self._channel, event, action_value)
        except Exception:  # pragma: no cover
            logger.exception(
                "feishu card handle failed: kind=%s",
                kind.name,
            )
            return P2CardActionTriggerResponse({})


__all__ = ["FeishuCardHandler", "CardKind"]
