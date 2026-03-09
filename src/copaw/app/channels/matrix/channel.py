# -*- coding: utf-8 -*-
"""Matrix channel implementation using matrix-nio."""

import asyncio
import logging
from typing import Any, Dict, Optional

from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    ContentType,
    TextContent,
)
from nio import AsyncClient, MatrixRoom, RoomMessageText, RoomSendError

from ....config.config import MatrixConfig
from ..base import BaseChannel, OnReplySent, ProcessHandler

logger = logging.getLogger(__name__)


class MatrixChannel(BaseChannel):
    channel = "matrix"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        homeserver: str,
        user_id: str,
        access_token: str,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        bot_prefix: str = "",
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        **_kwargs: Any,
    ) -> None:
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )
        self.enabled = enabled
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.bot_prefix = bot_prefix
        self.dm_policy = dm_policy
        self.group_policy = group_policy
        self.allow_from = allow_from or []
        self.deny_message = deny_message
        self.client: Optional[AsyncClient] = None
        self._sync_task: Optional[asyncio.Task] = None

    def _check_allowlist(
        self,
        sender_id: str,
        is_group: bool = False,
    ) -> tuple:
        policy = self.group_policy if is_group else self.dm_policy
        if policy == "open":
            return True, ""
        if self.allow_from and sender_id in self.allow_from:
            return True, ""
        return False, self.deny_message

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "MatrixChannel":
        raise NotImplementedError(
            "Matrix channel must be configured via config file.",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: MatrixConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "MatrixChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            homeserver=config.homeserver,
            user_id=config.user_id,
            access_token=config.access_token,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            bot_prefix=config.bot_prefix,
            dm_policy=config.dm_policy,
            group_policy=config.group_policy,
            allow_from=config.allow_from,
            deny_message=config.deny_message,
        )

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> AgentRequest:
        room_id = native_payload["room_id"]
        sender = native_payload["sender"]
        body = native_payload["body"]

        content_parts = [TextContent(type=ContentType.TEXT, text=body)]
        session_id = self.resolve_session_id(room_id)

        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=sender,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta={"room_id": room_id},
        )
        return request

    def get_to_handle_from_request(self, request: AgentRequest) -> str:
        session_id = getattr(request, "session_id", "") or ""
        if session_id.startswith("matrix:"):
            return session_id[len("matrix:") :]
        meta = getattr(request, "channel_meta", {}) or {}
        return meta.get("room_id", getattr(request, "user_id", ""))

    async def _message_callback(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
    ) -> None:
        if event.sender == self.user_id:
            return  # Ignore our own messages

        logger.info(
            f"Matrix received message from {event.sender}"
            f" in {room.room_id}: {event.body}",
        )

        is_group = len(room.users) > 2
        allowed, deny_msg = self._check_allowlist(
            event.sender,
            is_group=is_group,
        )
        if not allowed:
            if deny_msg:
                await self.send(room.room_id, deny_msg)
            return

        payload = {
            "room_id": room.room_id,
            "sender": event.sender,
            "body": event.body,
            "meta": {"room_id": room.room_id},
        }

        if self._enqueue:
            self._enqueue(payload)

    async def start(self) -> None:
        if (
            not self.enabled
            or not self.homeserver
            or not self.user_id
            or not self.access_token
        ):
            logger.info(
                "Matrix channel not configured or disabled. Skipping start.",
            )
            return

        self.client = AsyncClient(self.homeserver, self.user_id)
        self.client.access_token = self.access_token

        self.client.add_event_callback(self._message_callback, RoomMessageText)

        logger.info(
            f"Starting Matrix client for {self.user_id}"
            f" on {self.homeserver}",
        )

        async def sync_loop() -> None:
            try:
                await self.client.sync_forever(timeout=30000, full_state=True)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Matrix sync loop error: {e}", exc_info=True)

        self._sync_task = asyncio.create_task(sync_loop())

    async def stop(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
        if self.client:
            await self.client.close()
        logger.info("Matrix channel stopped.")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.client:
            logger.error("Matrix client not initialized, cannot send message")
            return

        if not text:
            return

        logger.info(f"Matrix sending to room={to_handle} text_len={len(text)}")
        resp = await self.client.room_send(
            room_id=to_handle,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": text,
            },
        )
        if isinstance(resp, RoomSendError):
            logger.error(f"Matrix room_send failed: {resp}")
