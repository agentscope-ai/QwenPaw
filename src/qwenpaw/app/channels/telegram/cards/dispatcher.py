# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Telegram interactive card dispatcher (routing-only).

Two lookup tables drive the dispatch:

* ``_by_message_type``  — outbound: message_type → render.
* ``_by_callback_data_prefix`` — inbound: prefix → handle.

Public entry-points (called by :class:`~..channel.TelegramChannel`):
:meth:`try_send_card_for_event` and :meth:`handle_callback_query`.
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
    Optional,
)

from . import context

if TYPE_CHECKING:
    from ..channel import TelegramChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Registry record
# ---------------------------------------------------------------------

RenderFn = Callable[
    ...,
    Awaitable[bool],
]

HandleFn = Callable[["TelegramChannel", Any], Awaitable[None]]


@dataclass(frozen=True)
class CardKind:
    """Describes one kind of interactive card and its handlers."""

    name: str
    message_type: str
    callback_data_prefix: str
    render: RenderFn
    handle: HandleFn


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------


class TelegramCardHandler:
    """Routing-only dispatcher for Telegram inline keyboard cards."""

    def __init__(self, channel: "TelegramChannel") -> None:
        self._channel = channel
        self._by_message_type: Dict[str, CardKind] = {}
        self._by_callback_data_prefix: Dict[str, CardKind] = {}
        self._register_kinds()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, kind: CardKind) -> None:
        """Install a card kind into both lookup tables."""
        self._by_message_type[kind.message_type] = kind
        self._by_callback_data_prefix[kind.callback_data_prefix] = kind

    def _register_kinds(self) -> None:
        """Register every built-in card kind."""
        from . import tool_guard

        self.register(
            CardKind(
                name=tool_guard.NAME,
                message_type=tool_guard.MESSAGE_TYPE,
                callback_data_prefix=tool_guard.CALLBACK_DATA_PREFIX,
                render=tool_guard.render,
                handle=tool_guard.handle,
            ),
        )

    # ==================================================================
    # Public entry-points
    # ==================================================================

    async def try_send_card_for_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        *,
        compact: bool = False,
    ) -> bool:
        """Render ``event`` as an inline keyboard card if any kind matches.

        Returns ``True`` when a card was sent so the caller can skip
        the default text rendering.

        When ``compact=True`` (streaming mode), the render function
        produces a minimal card (buttons only, no body text).
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
        except Exception:
            logger.exception(
                "telegram card render failed: kind=%s",
                kind.name,
            )
            return False

    async def handle_callback_query(self, query: Any) -> None:
        """Route a CallbackQuery to the matching card kind's handler.

        Called from the CallbackQueryHandler registered in the
        Application builder.
        """
        data = getattr(query, "data", None) or ""
        kind = self._lookup_kind_for_callback(data)
        if kind is None:
            return

        try:
            await kind.handle(self._channel, query)
        except Exception:
            logger.exception(
                "telegram card handle failed: kind=%s",
                kind.name,
            )

    def is_card_event(self, event: Any) -> bool:
        """Check if the event matches a registered interactive card kind."""
        meta = context.extract_meta(event)
        if meta is None:
            return False
        message_type = str(meta.get("message_type") or "")
        return message_type in self._by_message_type

    def _lookup_kind_for_callback(
        self,
        callback_data: str,
    ) -> Optional[CardKind]:
        """Find the CardKind matching the callback_data prefix."""
        if not callback_data:
            return None
        for prefix, kind in self._by_callback_data_prefix.items():
            if callback_data.startswith(prefix):
                return kind
        return None


__all__ = ["TelegramCardHandler", "CardKind"]
