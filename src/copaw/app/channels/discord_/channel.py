# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
from __future__ import annotations

import os
import logging
import asyncio
from typing import Any, Optional

import aiohttp
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ....config.config import DiscordConfig as DiscordChannelConfig

from ..base import BaseChannel, OnReplySent, ProcessHandler

logger = logging.getLogger(__name__)


class DiscordChannel(BaseChannel):
    channel = "discord"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        token: str,
        http_proxy: str,
        http_proxy_auth: str,
        bot_prefix: str,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
        )
        self.enabled = enabled
        self.token = token
        self.http_proxy = http_proxy
        self.http_proxy_auth = http_proxy_auth
        self.bot_prefix = bot_prefix
        self._task: Optional[asyncio.Task] = None
        self._client = None

        if self.enabled:
            import discord  # type: ignore

            intents = discord.Intents.default()
            intents.message_content = True
            intents.dm_messages = True
            intents.messages = True
            intents.guilds = True

            proxy_auth = None
            if self.http_proxy_auth:
                u, p = self.http_proxy_auth.split(":", 1)
                proxy_auth = aiohttp.BasicAuth(u, p)

            self._client = discord.Client(
                intents=intents,
                proxy=self.http_proxy,
                proxy_auth=proxy_auth,
            )

            @self._client.event
            async def on_message(message):
                if message.author.bot:
                    return
                text = (message.content or "").strip()
                attachments = message.attachments

                # Build runtime content parts
                content_parts = []
                if text:
                    content_parts.append(
                        TextContent(type=ContentType.TEXT, text=text),
                    )
                if attachments:
                    for att in attachments:
                        file_name = (att.filename or "").lower()
                        url = att.url
                        ctype = (att.content_type or "").lower()

                        is_image = ctype.startswith(
                            "image/",
                        ) or file_name.endswith(
                            (
                                ".png",
                                ".jpg",
                                ".jpeg",
                                ".gif",
                                ".webp",
                                ".bmp",
                                ".tiff",
                            ),
                        )
                        is_video = ctype.startswith(
                            "video/",
                        ) or file_name.endswith(
                            (".mp4", ".mov", ".mkv", ".webm", ".avi"),
                        )
                        is_audio = ctype.startswith(
                            "audio/",
                        ) or file_name.endswith(
                            (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"),
                        )

                        if is_image:
                            content_parts.append(
                                ImageContent(
                                    type=ContentType.IMAGE,
                                    image_url=url,
                                ),
                            )
                        elif is_video:
                            content_parts.append(
                                VideoContent(
                                    type=ContentType.VIDEO,
                                    video_url=url,
                                ),
                            )
                        elif is_audio:
                            content_parts.append(
                                AudioContent(
                                    type=ContentType.AUDIO,
                                    data=url,
                                ),
                            )
                        else:
                            content_parts.append(
                                FileContent(
                                    type=ContentType.FILE,
                                    file_url=url,
                                ),
                            )

                meta = {
                    "user_id": str(message.author.id),
                    "channel_id": str(message.channel.id),
                    "guild_id": str(message.guild.id)
                    if message.guild
                    else None,
                    "message_id": str(message.id),
                    "is_dm": message.guild is None,
                }
                native = {
                    "channel_id": self.channel,
                    "sender_id": str(message.author),
                    "content_parts": content_parts,
                    "meta": meta,
                }
                if self._enqueue is not None:
                    self._enqueue(native)
                else:
                    logger.warning(
                        "discord: _enqueue not set, message dropped",
                    )

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "DiscordChannel":
        return cls(
            process=process,
            enabled=os.getenv("DISCORD_CHANNEL_ENABLED", "1") == "1",
            token=os.getenv("DISCORD_BOT_TOKEN", ""),
            http_proxy=os.getenv(
                "DISCORD_HTTP_PROXY",
                "",
            ),
            http_proxy_auth=os.getenv("DISCORD_HTTP_PROXY_AUTH", ""),
            bot_prefix=os.getenv("DISCORD_BOT_PREFIX", "[BOT] "),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: DiscordChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
    ) -> "DiscordChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            token=config.bot_token or "",
            http_proxy=config.http_proxy,
            http_proxy_auth=config.http_proxy_auth or "",
            bot_prefix=config.bot_prefix or "[BOT] ",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
        )

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        """
        Proactive send for Discord.

        Notes:
        - Discord cannot send to a "user handle" directly without resolving
            a User/Channel.
        - This implementation supports:
            1) meta["channel_id"]  -> send to that channel
            2) meta["user_id"]     -> DM that user (opens/uses DM channel)
        - If neither is provided, this raises ValueError.
        """
        if not self.enabled:
            return
        if not self._client:
            raise RuntimeError("Discord client is not initialized")
        if not self._client.is_ready():
            raise RuntimeError("Discord client is not ready yet")

        meta = meta or {}

        if not meta.get("channel_id") and not meta.get("user_id"):
            meta.update(self._route_from_handle(to_handle))

        channel_id = meta.get("channel_id")
        user_id = meta.get("user_id")

        if channel_id:
            ch = self._client.get_channel(int(channel_id))
            if ch is None:
                ch = await self._client.fetch_channel(
                    int(channel_id),
                )
            await ch.send(text)
            return

        if user_id:
            user = self._client.get_user(int(user_id))
            if user is None:
                user = await self._client.fetch_user(
                    int(user_id),
                )
            dm = user.dm_channel or await user.create_dm()
            await dm.send(text)
            return

        raise ValueError(
            "DiscordChannel.send requires meta['channel_id'] or meta["
            "'user_id']",
        )

    async def _run(self) -> None:
        if not self.enabled or not self.token or not self._client:
            return
        await self._client.start(self.token, reconnect=True)

    async def start(self) -> None:
        if not self.enabled:
            return
        self._task = asyncio.create_task(self._run(), name="discord_gateway")

    async def stop(self) -> None:
        if not self.enabled:
            return
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.CancelledError, Exception):
                pass
        if self._client:
            await self._client.close()

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        """Session by channel (guild) or DM user id."""
        meta = channel_meta or {}
        is_dm = bool(meta.get("is_dm"))
        channel_id = meta.get("channel_id")
        user_id = meta.get("user_id") or sender_id
        if is_dm:
            return f"discord:dm:{user_id}"
        if channel_id:
            return f"discord:ch:{channel_id}"
        return f"discord:dm:{user_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        """Discord send target is session_id (discord:ch:xxx or dm:xxx)."""
        sid = getattr(request, "session_id", "")
        uid = getattr(request, "user_id", "")
        return sid or uid or ""

    def build_agent_request_from_native(self, native_payload) -> Any:
        """Build AgentRequest from Discord dict (content_parts + meta)."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        user_id = str(meta.get("user_id") or sender_id)
        session_id = self.resolve_session_id(user_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.user_id = user_id
        request.channel_meta = meta
        return request

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        return session_id

    def _route_from_handle(self, to_handle: str) -> dict:
        # to_handle: discord:ch:<channel_id> 或 discord:dm:<user_id>
        parts = (to_handle or "").split(":")
        if len(parts) >= 3 and parts[0] == "discord":
            kind, ident = parts[1], parts[2]
            if kind == "ch":
                return {"channel_id": ident}
            if kind == "dm":
                return {"user_id": ident}
        return {}
