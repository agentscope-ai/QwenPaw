# -*- coding: utf-8 -*-
"""WeCom interactive template-card handler.

Dispatches outbound rendering (tool-guard approval → template card) and
inbound ``template_card_event`` callbacks (button click → /approval
command injection).

Unlike Feishu where ``card.action.trigger`` returns a replacement card
synchronously, WeCom requires an explicit ``update_template_card`` call
within 5 seconds of the callback.  The handler therefore calls update
directly on the channel's WSClient.

Architecture
------------
1. **Outbound** – ``try_send_card_for_event`` checks metadata for
   ``message_type == "tool_guard_approval"`` and sends a
   ``button_interaction`` card via ``reply_template_card``.
2. **Inbound** – ``handle_template_card_event`` parses the callback,
   updates the card to a resolved state, and injects ``/approval``
   into the message queue.
"""
from __future__ import annotations

import asyncio
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Optional,
)

from .card_templates import (
    APPROVE_KEY,
    DENY_KEY,
    build_tool_guard_approval_card,
    build_tool_guard_resolved_card,
    parse_tool_guard_card_event,
)

if TYPE_CHECKING:
    from .channel import WecomChannel

logger = logging.getLogger(__name__)


class WecomCardHandler:
    """Template-card dispatcher for WeCom tool-guard approval."""

    def __init__(self, channel: "WecomChannel") -> None:
        self._channel = channel

    # ==================================================================
    # Outbound: send approval card
    # ==================================================================

    async def try_send_card_for_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> bool:
        """Render a tool-guard event as a template card if applicable.

        Returns ``True`` when a card was sent (caller should skip default
        text rendering), ``False`` otherwise.
        """
        meta = self._extract_meta(event)
        if not meta or meta.get("message_type") != "tool_guard_approval":
            return False

        request_id = str(meta.get("approval_request_id") or "")
        if not request_id:
            return False

        channel = self._channel
        if not channel.enabled or not channel._client:
            return False

        frame = send_meta.get("wecom_frame")
        if not frame:
            logger.warning(
                "wecom approval card: no frame for to_handle=%s",
                (to_handle or "")[:40],
            )
            return False

        body_text = self._extract_body_text(
            getattr(event, "content", None),
        )

        session_ctx = self._build_session_ctx(to_handle, send_meta)

        template_card = build_tool_guard_approval_card(
            request_id=request_id,
            tool_name=str(meta.get("tool_name") or "tool"),
            severity=str(meta.get("severity") or "medium"),
            body_text=body_text,
            session_ctx=session_ctx,
        )

        # Step 1: Show full tool_guard details via stream message.
        # If a "🤔 Thinking..." processing stream is active, reuse it
        # to display the guard details (avoids leaving an empty bubble).
        # Otherwise start a fresh stream.
        processing_sid = send_meta.pop(
            "wecom_processing_stream_id", "",
        )
        if processing_sid:
            # Kill keepalive first so it doesn't race our finish.
            keepalive = channel._keepalive_tasks.pop(
                processing_sid, None,
            )
            if keepalive and not keepalive.done():
                keepalive.cancel()
                try:
                    await keepalive
                except (asyncio.CancelledError, Exception):
                    pass

        from aibot import generate_req_id

        stream_id = processing_sid or generate_req_id("stream")
        try:
            await channel._client.reply_stream(
                frame,
                stream_id=stream_id,
                content=body_text,
                finish=True,
            )
        except Exception:
            logger.debug("wecom approval: stream detail send failed")

        # Step 2: Send the button card as a separate reply.
        try:
            await channel._client.reply_template_card(frame, template_card)
            logger.info(
                "wecom approval card sent: request_id=%s tool=%s",
                request_id[:8],
                meta.get("tool_name", ""),
            )
            return True
        except Exception:
            logger.exception(
                "wecom approval card send failed: request_id=%s",
                request_id[:8],
            )
            return False

    # ==================================================================
    # Inbound: handle button click
    # ==================================================================

    def handle_template_card_event_sync(self, frame: Any) -> None:
        """Sync entry called from the WS thread on button click.

        Dispatches to the main event loop for async processing.
        """
        loop = self._channel._loop
        if not loop or not loop.is_running():
            logger.warning(
                "wecom card event: main loop not running, drop event",
            )
            return
        asyncio.run_coroutine_threadsafe(
            self._handle_template_card_event(frame),
            loop,
        )

    async def _handle_template_card_event(self, frame: Any) -> None:
        """Process a ``template_card_event`` callback."""
        body = frame.get("body") or {} if isinstance(frame, dict) else {}
        parsed = parse_tool_guard_card_event(body)
        if not parsed:
            # Not a tool-guard card event; ignore silently.
            return

        action = parsed["action"]
        request_id = parsed["request_id"]
        task_id = parsed["task_id"]
        tool_name = parsed.get("tool_name") or "tool"
        user_id = parsed.get("user_id") or ""

        logger.info(
            "wecom card event: action=%s request_id=%s user=%s",
            action,
            request_id[:8],
            user_id[:20],
        )

        # 1. Update the card to resolved state (must be within 5s).
        await self._update_card_resolved(
            frame, task_id, tool_name, action, user_id,
        )

        # 2. Inject /approval command into the message queue.
        self._enqueue_approval_command(
            action=action,
            request_id=request_id,
            session_ctx=parsed.get("session_ctx") or {},
            user_id=user_id,
        )

    async def _update_card_resolved(
        self,
        frame: Any,
        task_id: str,
        tool_name: str,
        action: str,
        operator_display: str,
    ) -> None:
        """Replace the approval card with a resolved status card."""
        channel = self._channel
        if not channel._client:
            return

        resolved_card = build_tool_guard_resolved_card(
            task_id=task_id,
            tool_name=tool_name,
            action=action,
            operator_display=operator_display,
        )

        try:
            await channel._client.update_template_card(frame, resolved_card)
            logger.info(
                "wecom approval card updated: task_id=%s action=%s",
                task_id[:20],
                action,
            )
        except Exception:
            logger.exception(
                "wecom approval card update failed: task_id=%s",
                task_id[:20],
            )

    def _enqueue_approval_command(
        self,
        *,
        action: str,
        request_id: str,
        session_ctx: Dict[str, Any],
        user_id: str,
    ) -> None:
        """Inject ``/approval {action} {request_id}`` into the queue."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            ContentType,
            TextContent,
        )

        channel = self._channel
        enqueue = getattr(channel, "_enqueue", None)
        if enqueue is None:
            logger.warning(
                "wecom card action: channel enqueue not set, "
                "dropping %s %s",
                action,
                request_id[:8],
            )
            return

        sender_id = str(session_ctx.get("sender_id") or user_id or "")
        session_id = str(session_ctx.get("session_id") or "")
        chatid = str(session_ctx.get("chatid") or "")
        chat_type = str(session_ctx.get("chat_type") or "single")
        is_group = chat_type == "group"

        command_text = f"/approval {action} {request_id}"
        content_parts = [
            TextContent(type=ContentType.TEXT, text=command_text),
        ]
        meta: Dict[str, Any] = {
            "wecom_sender_id": sender_id,
            "wecom_chatid": chatid,
            "wecom_chat_type": chat_type,
            "is_group": is_group,
            "from_card_action": True,
        }
        payload = {
            "channel_id": channel.channel,
            "sender_id": sender_id,
            "user_id": sender_id,
            "session_id": session_id,
            "content_parts": content_parts,
            "meta": meta,
        }
        try:
            enqueue(payload)
            logger.info(
                "wecom card action enqueued: cmd=%s request=%s session=%s",
                command_text,
                request_id[:8],
                session_id[:12],
            )
        except Exception:
            logger.exception(
                "wecom card action: enqueue failed: %s %s",
                action,
                request_id[:8],
            )

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _build_session_ctx(
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Collect routing info for re-injection later."""
        session_id = ""
        handle = (to_handle or "").strip()
        if handle.startswith("wecom:"):
            session_id = handle

        return {
            "session_id": session_id,
            "sender_id": str(send_meta.get("wecom_sender_id") or ""),
            "chatid": str(send_meta.get("wecom_chatid") or ""),
            "chat_type": str(send_meta.get("wecom_chat_type") or "single"),
        }

    @staticmethod
    def _extract_meta(event: Any) -> Optional[Dict[str, Any]]:
        """Return the original ``Msg.metadata`` dict or ``None``."""
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
        for item in content:
            if hasattr(item, "text") and item.text:
                parts.append(item.text)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text") or "")
        return "".join(parts)


__all__ = ["WecomCardHandler"]
