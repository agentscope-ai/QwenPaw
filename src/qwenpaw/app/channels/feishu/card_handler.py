# -*- coding: utf-8 -*-
"""Feishu interactive-card handler.

Dispatches all interactive-card work (both outbound rendering and
inbound ``card.action.trigger`` callbacks) for :class:`FeishuChannel`.

The lark_oapi SDK only allows **one** ``p2.card.action.trigger``
callback per dispatcher (see ``EventDispatcherHandlerBuilder``), so we
need a single entry-point on the Feishu side. Instead of growing
``if/elif`` chains inside that entry-point, each card kind is described
as a :class:`CardKind` record and registered into two lookup tables:

* ``_by_message_type`` — for outbound: matches an outgoing event's
  ``metadata.message_type`` to a ``render`` coroutine.
* ``_by_action_type``  — for inbound: matches the ``type`` field in a
  button's ``value`` to a ``handle`` callable.

Adding a new card kind only needs:

1. Build/parse helpers in :mod:`card_templates`.
2. A private ``_send_*`` / ``_handle_*`` pair on this class.
3. One ``self._register(CardKind(...))`` line in :meth:`_register_kinds`.

The two public entry-points (:meth:`try_send_card_for_event`,
:meth:`handle_card_action`) stay untouched.
"""
from __future__ import annotations

import asyncio
import json
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

from .card_templates import (
    TOOL_GUARD_ACTION_TYPE,
    build_tool_guard_approval_card,
    build_tool_guard_resolved_card,
    build_tool_guard_toast,
    parse_tool_guard_action_value,
)

try:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTrigger,
        P2CardActionTriggerResponse,
    )
except ImportError:  # pragma: no cover - optional dependency
    P2CardActionTrigger = None  # type: ignore[assignment]
    P2CardActionTriggerResponse = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance
    from .channel import FeishuChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Registry record
# ---------------------------------------------------------------------

# Outbound: given (to_handle, event, send_meta, meta) build + send the
# card. Returns True if the card was sent so the caller can skip the
# default text rendering.
RenderFn = Callable[
    [str, Any, Dict[str, Any], Dict[str, Any]],
    Awaitable[bool],
]

# Inbound: given (event, action_value) produce the synchronous card
# response for lark_oapi.
HandleFn = Callable[[Any, Dict[str, Any]], "P2CardActionTriggerResponse"]


@dataclass(frozen=True)
class CardKind:
    """Describes one kind of interactive card and its handlers."""

    name: str  # human-readable tag for logs
    message_type: str  # matches ``metadata.message_type`` (outbound)
    action_type: str  # matches button ``value.type`` (inbound)
    render: RenderFn
    handle: HandleFn


# ---------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------


class FeishuCardHandler:
    """Registry-based dispatcher for Feishu interactive cards.

    Holds a back-reference to the owning :class:`FeishuChannel` and
    piggybacks on its primitives (``_send_message`` / ``_loop`` / ...)
    without duplicating state.
    """

    # Tightly coupled with the owning FeishuChannel by design.
    # pylint: disable=protected-access

    def __init__(self, channel: "FeishuChannel") -> None:
        self._channel = channel
        self._by_message_type: Dict[str, CardKind] = {}
        self._by_action_type: Dict[str, CardKind] = {}
        self._register_kinds()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register(self, kind: CardKind) -> None:
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
        """Register every built-in card kind.

        New card kinds: add one ``self._register(CardKind(...))`` line
        here and implement the render/handle pair below.
        """
        self._register(
            CardKind(
                name="tool_guard_approval",
                message_type="tool_guard_approval",
                action_type=TOOL_GUARD_ACTION_TYPE,
                render=self._send_tool_guard_approval_card,
                handle=self._handle_tool_guard_action,
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
    ) -> bool:
        """Render ``event`` as an interactive card if any kind matches.

        Returns ``True`` when a card was sent (the caller should then
        skip the default text/post rendering), ``False`` otherwise.
        """
        meta = self._extract_meta(event)
        if meta is None:
            return False
        kind = self._by_message_type.get(str(meta.get("message_type") or ""))
        if kind is None:
            return False
        try:
            return await kind.render(to_handle, event, send_meta, meta)
        except Exception:  # pragma: no cover - defensive
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

        Must return a :class:`P2CardActionTriggerResponse` synchronously
        so Feishu can use it to update the card UI.
        """
        # Guard against cross-instance dispatch: lark_oapi uses a single
        # module-level loop variable that can be overwritten when
        # multiple FeishuChannel instances coexist.
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
            return kind.handle(event, action_value)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "feishu card handle failed: kind=%s",
                kind.name,
            )
            return P2CardActionTriggerResponse({})

    # ==================================================================
    # tool-guard: outbound
    # ==================================================================

    async def _send_tool_guard_approval_card(
        self,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        meta: Dict[str, Any],
    ) -> bool:
        if not meta.get("approval_request_id"):
            return False
        ch = self._channel
        if not ch.enabled:
            return False
        recv = await ch._get_receive_for_send(to_handle, send_meta)
        if not recv:
            logger.warning(
                "feishu approval card: no receive_id for to_handle=%s",
                (to_handle or "")[:50],
            )
            return False
        receive_id_type, receive_id = recv
        body_text = self._extract_body_text(getattr(event, "content", None))
        session_ctx = self._build_session_ctx(
            to_handle=to_handle,
            send_meta=send_meta,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        content = build_tool_guard_approval_card(
            request_id=str(meta.get("approval_request_id") or ""),
            tool_name=str(meta.get("tool_name") or "tool"),
            severity=str(meta.get("severity") or "medium"),
            body_text=body_text,
            session_ctx=session_ctx,
        )
        msg_id = await ch._send_message(
            receive_id_type,
            receive_id,
            "interactive",
            content,
        )
        if msg_id:
            send_meta["_last_sent_message_id"] = msg_id
            logger.info(
                "feishu approval card sent: request_id=%s msg_id=%s",
                str(meta.get("approval_request_id") or "")[:8],
                msg_id[:24],
            )
            return True
        logger.warning(
            "feishu approval card send failed: request_id=%s",
            str(meta.get("approval_request_id") or "")[:8],
        )
        return False

    # ==================================================================
    # tool-guard: inbound
    # ==================================================================

    def _handle_tool_guard_action(
        self,
        event: Any,
        action_value: Dict[str, Any],
    ) -> "P2CardActionTriggerResponse":
        parsed = parse_tool_guard_action_value(action_value)
        if not parsed:
            return P2CardActionTriggerResponse({})

        action = parsed["action"]
        operator = getattr(event, "operator", None) if event else None
        operator_open_id = (
            getattr(operator, "open_id", None) if operator else None
        ) or ""

        ch = self._channel
        loop = ch._loop

        # Re-inject as ``/approval`` magic command so ApprovalCommandHandler
        # stays the single source of truth; card handler keeps no business
        # state of its own.
        self._enqueue_approval_command(
            action=action,
            request_id=parsed["request_id"],
            session_ctx=parsed.get("session_ctx") or {},
            operator_open_id=operator_open_id,
        )

        tool_name = parsed.get("tool_name") or "tool"

        # Resolve operator display name on the main loop; fall back to
        # the last 6 chars of open_id on lookup failure.
        operator_display = operator_open_id[-6:] if operator_open_id else ""
        if operator_open_id and loop and loop.is_running():
            try:
                name = asyncio.run_coroutine_threadsafe(
                    ch._get_user_name_by_open_id(operator_open_id),
                    loop,
                ).result(timeout=2)
                if name:
                    operator_display = name
            except Exception:
                pass  # keep fallback

        resolved_card = build_tool_guard_resolved_card(
            tool_name=tool_name,
            action=action,
            operator_display=operator_display,
            body_text=parsed.get("body") or "",
        )
        toast = build_tool_guard_toast(action, tool_name)
        try:
            return P2CardActionTriggerResponse(
                {
                    "toast": toast,
                    "card": {
                        "type": "raw",
                        "data": json.loads(resolved_card),
                    },
                },
            )
        except Exception:  # pragma: no cover
            logger.exception("feishu card action: build response failed")
            return P2CardActionTriggerResponse({"toast": toast})

    def _enqueue_approval_command(
        self,
        *,
        action: str,
        request_id: str,
        session_ctx: Dict[str, Any],
        operator_open_id: str,
    ) -> None:
        """Inject ``/approval {action} {request_id}`` into the channel queue.

        Rebuilds a native payload from ``session_ctx`` so the runner's
        command dispatcher routes it to :class:`ApprovalCommandHandler`.
        Thread-safe via the manager's enqueue callback.
        """
        from agentscope_runtime.engine.schemas.agent_schemas import (
            ContentType,
            TextContent,
        )

        ch = self._channel
        enqueue = getattr(ch, "_enqueue", None)
        if enqueue is None:
            logger.warning(
                "feishu card action: channel enqueue not set, drop %s %s",
                action,
                request_id[:8],
            )
            return

        sender_id = str(session_ctx.get("sender_id") or operator_open_id or "")
        session_id = str(session_ctx.get("session_id") or "")
        receive_id = str(session_ctx.get("receive_id") or "")
        receive_id_type = str(session_ctx.get("receive_id_type") or "open_id")
        chat_id = str(session_ctx.get("chat_id") or "")
        chat_type = str(session_ctx.get("chat_type") or "p2p")
        is_group = bool(session_ctx.get("is_group"))

        command_text = f"/approval {action} {request_id}".strip()
        content_parts = [
            TextContent(type=ContentType.TEXT, text=command_text),
        ]
        meta: Dict[str, Any] = {
            "feishu_sender_id": sender_id,
            "feishu_chat_id": chat_id,
            "feishu_chat_type": chat_type,
            "feishu_receive_id": receive_id,
            "feishu_receive_id_type": receive_id_type,
            "is_group": is_group,
            "from_card_action": True,
        }
        payload = {
            "channel_id": ch.channel,
            "sender_id": sender_id,
            "user_id": sender_id,
            "session_id": session_id,
            "content_parts": content_parts,
            "meta": meta,
        }
        try:
            enqueue(payload)
            logger.info(
                "feishu card action enqueued: cmd=%s request=%s session=%s",
                command_text,
                request_id[:8],
                session_id[:12],
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "feishu card action: enqueue command failed: %s %s",
                action,
                request_id[:8],
            )

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _build_session_ctx(
        *,
        to_handle: str,
        send_meta: Dict[str, Any],
        receive_id: str,
        receive_id_type: str,
    ) -> Dict[str, Any]:
        """Collect routing info needed to re-inject a message later.

        ``session_id`` is derived from ``to_handle``
        (``feishu:sw:<short_session_id>``) so the enqueued command
        lands in the same debounce bucket as the original conversation.
        """
        session_id = ""
        handle = (to_handle or "").strip()
        if handle.startswith("feishu:sw:"):
            session_id = handle[len("feishu:sw:") :]
        return {
            "session_id": session_id,
            "sender_id": str(send_meta.get("feishu_sender_id") or ""),
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "chat_id": str(send_meta.get("feishu_chat_id") or ""),
            "chat_type": str(send_meta.get("feishu_chat_type") or "p2p"),
            "is_group": bool(send_meta.get("is_group")),
        }

    @staticmethod
    def _extract_meta(event: Any) -> Optional[Dict[str, Any]]:
        """Return the original ``Msg.metadata`` dict or ``None``.

        ``Runner`` wraps the original ``Msg.metadata`` under a nested
        ``metadata`` key when converting to ``Message``; unwrap it.
        """
        metadata = getattr(event, "metadata", None) or {}
        if not isinstance(metadata, dict):
            return None
        inner = metadata.get("metadata")
        meta = inner if isinstance(inner, dict) else metadata
        return meta if isinstance(meta, dict) else None

    @staticmethod
    def _extract_body_text(content: Any) -> str:
        """Flatten ``Message.content`` to plain text."""
        if not content:
            return ""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts = []
        for c in content:
            # TextContent objects have a ``.text`` attribute
            if hasattr(c, "text") and c.text:
                parts.append(c.text)
            elif isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text") or "")
        return "".join(parts)


__all__ = ["CardKind", "FeishuCardHandler"]
