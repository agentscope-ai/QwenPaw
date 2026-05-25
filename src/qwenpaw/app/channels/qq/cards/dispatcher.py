# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""QQ interactive card dispatcher (routing-only).

Two lookup tables drive the dispatch:

* ``_by_message_type``     — outbound: ``metadata.message_type`` → ``render``.
* ``_by_action_data_prefix`` — inbound: ``action.data`` prefix  → ``handle``.

Public entry-points (called by :class:`~..channel.QQChannel`):
:meth:`try_send_card_for_event` and :meth:`handle_interaction_event`.
"""
from __future__ import annotations

import asyncio
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
    from ..channel import QQChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Registry record
# ---------------------------------------------------------------------

RenderFn = Callable[
    ["QQChannel", str, Any, Dict[str, Any], Dict[str, Any]],
    Awaitable[bool],
]

HandleFn = Callable[["QQChannel", Dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class CardKind:
    """Describes one kind of interactive card and its handlers."""

    name: str
    message_type: str
    action_data_prefix: str
    render: RenderFn
    handle: HandleFn


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------


class QQCardHandler:
    """Routing-only dispatcher for QQ interactive keyboard cards."""

    def __init__(self, channel: "QQChannel") -> None:
        self._channel = channel
        self._by_message_type: Dict[str, CardKind] = {}
        self._by_action_data_prefix: Dict[str, CardKind] = {}
        self._register_kinds()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, kind: CardKind) -> None:
        """Install a card kind into both lookup tables."""
        self._by_message_type[kind.message_type] = kind
        self._by_action_data_prefix[kind.action_data_prefix] = kind

    def _register_kinds(self) -> None:
        """Register every built-in card kind."""
        from . import tool_guard

        self.register(
            CardKind(
                name=tool_guard.NAME,
                message_type=tool_guard.MESSAGE_TYPE,
                action_data_prefix=tool_guard.ACTION_DATA_PREFIX,
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
    ) -> bool:
        """Render ``event`` as a keyboard card if any kind matches.

        Returns ``True`` when a card was sent so the caller can skip
        the default text rendering.
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
            )
        except Exception:
            logger.exception(
                "qq card render failed: kind=%s",
                kind.name,
            )
            return False

    def handle_interaction_event(self, event_data: Dict[str, Any]) -> None:
        """Sync entry called from the WS thread; routes by action.data
        prefix and dispatches to the main loop."""
        loop = self._channel._loop
        if not loop or not loop.is_running():
            logger.warning(
                "qq card event: main loop not running, drop event",
            )
            return

        kind = self._lookup_kind_for_event(event_data)
        if kind is None:
            return

        asyncio.run_coroutine_threadsafe(
            self._safe_handle(kind, event_data),
            loop,
        )

    async def _safe_handle(
        self,
        kind: CardKind,
        event_data: Dict[str, Any],
    ) -> None:
        """Wrap the registered handler with logging."""
        try:
            await kind.handle(self._channel, event_data)
        except Exception:
            logger.exception(
                "qq card handle failed: kind=%s",
                kind.name,
            )

    def _lookup_kind_for_event(
        self,
        event_data: Dict[str, Any],
    ) -> Optional[CardKind]:
        """Find the CardKind matching the interaction event's action data."""
        import json as _json

        # Extract button_data from various possible locations
        data_str = ""
        resolved = event_data.get("data", {})
        if isinstance(resolved, dict):
            resolved_inner = resolved.get("resolved", {})
            if isinstance(resolved_inner, dict):
                data_str = str(resolved_inner.get("button_data") or "")
        if not data_str:
            data_str = str(event_data.get("button_data") or "")
        if not data_str:
            return None

        try:
            ctx = _json.loads(data_str)
        except (ValueError, TypeError):
            return None

        prefix = str(ctx.get("p") or "")
        return self._by_action_data_prefix.get(prefix)


__all__ = ["QQCardHandler", "CardKind"]
