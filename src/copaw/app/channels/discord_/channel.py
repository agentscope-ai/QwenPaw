# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
from __future__ import annotations

import os
import logging
import asyncio
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse
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

from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

logger = logging.getLogger(__name__)

# Regex that matches a code-fence opening/closing line (``` or ~~~).
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


class DiscordChannel(BaseChannel):
    channel = "discord"
    uses_manager_queue = True
    _DISCORD_MAX_LEN: int = 2000

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
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
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

                is_bot_mentioned = False
                bot_user = self._client.user
                if getattr(message, "mention_everyone", False):
                    is_bot_mentioned = True
                if bot_user and bot_user in message.mentions:
                    is_bot_mentioned = True
                    text = re.sub(
                        rf"<@!?{bot_user.id}>",
                        "",
                        text,
                    ).strip()

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

                is_group = message.guild is not None
                meta = {
                    "user_id": str(message.author.id),
                    "channel_id": str(message.channel.id),
                    "guild_id": str(message.guild.id)
                    if message.guild
                    else None,
                    "message_id": str(message.id),
                    "is_dm": not is_group,
                    "is_group": is_group,
                }
                if is_bot_mentioned:
                    meta["bot_mentioned"] = True

                allowed, error_msg = self._check_allowlist(
                    str(message.author.id),
                    is_group,
                )
                if not allowed:
                    logger.info(
                        "discord allowlist blocked: sender=%s is_group=%s",
                        message.author.id,
                        is_group,
                    )
                    await message.channel.send(error_msg or "")
                    return

                if not self._check_group_mention(is_group, meta):
                    return

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
        allow_from_env = os.getenv("DISCORD_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
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
            dm_policy=os.getenv("DISCORD_DM_POLICY", "open"),
            group_policy=os.getenv("DISCORD_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("DISCORD_DENY_MESSAGE", ""),
            require_mention=os.getenv("DISCORD_REQUIRE_MENTION", "0") == "1",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: DiscordChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
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
            filter_thinking=filter_thinking,
            dm_policy=config.dm_policy or "open",
            group_policy=config.group_policy or "open",
            allow_from=config.allow_from or [],
            deny_message=config.deny_message or "",
            require_mention=config.require_mention,
        )

    async def _resolve_target(self, to_handle, meta):
        """Resolve a Discord Messageable from meta or to_handle."""
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
            return ch
        if user_id:
            user = self._client.get_user(int(user_id))
            if user is None:
                user = await self._client.fetch_user(
                    int(user_id),
                )
            return user.dm_channel or await user.create_dm()
        return None

    @staticmethod
    def _chunk_text(text: str, max_len: int = 2000) -> list[str]:
        """Split *text* into chunks that fit Discord's message limit.

        Splits at newline boundaries to preserve formatting.  If a single
        line exceeds *max_len* it is hard-split at *max_len*.

        Markdown code fences are tracked so that a chunk ending inside an
        open fence gets a closing fence appended and the next chunk gets
        a matching opening fence prepended.  This keeps code blocks
        rendered correctly across split messages.
        """
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        fence_open: str = ""  # e.g. "```python"

        def _flush() -> None:
            nonlocal fence_open
            body = "".join(current).rstrip("\n")
            if fence_open:
                body += "\n```"  # close dangling fence
            chunks.append(body)
            current.clear()

        for line in text.split("\n"):
            line_with_nl = line + "\n"
            stripped = line.strip()

            # Detect fence toggle.
            if _FENCE_RE.match(stripped):
                if fence_open:
                    fence_open = ""
                else:
                    fence_open = stripped

            # Flush if adding this line would exceed the limit.
            if current and current_len + len(line_with_nl) > max_len:
                saved_fence = fence_open
                _flush()
                current_len = 0
                # Re-open the fence in the next chunk.
                if saved_fence:
                    fence_open = saved_fence
                    reopener = saved_fence + "\n"
                    current.append(reopener)
                    current_len += len(reopener)

            # Single line exceeds max_len -> hard-split.
            if len(line_with_nl) > max_len:
                for i in range(0, len(line), max_len):
                    chunks.append(line[i : i + max_len])
            else:
                current.append(line_with_nl)
                current_len += len(line_with_nl)

        if current:
            chunks.append("".join(current).rstrip("\n"))

        return [c for c in chunks if c.strip()]

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
        - Messages exceeding 2000 chars are automatically split into
            multiple messages preserving markdown code fences.
        """
        if not self.enabled:
            return
        if not self._client:
            raise RuntimeError("Discord client is not initialized")
        if not self._client.is_ready():
            raise RuntimeError("Discord client is not ready yet")
        target = await self._resolve_target(to_handle, meta)
        if not target:
            raise ValueError(
                "DiscordChannel.send requires meta['channel_id']"
                " or meta['user_id']",
            )
        for chunk in self._chunk_text(text, self._DISCORD_MAX_LEN):
            await target.send(chunk)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: list[OutgoingContentPart],
        meta: Optional[dict] = None,
    ) -> None:
        media_types = {
            ContentType.IMAGE,
            ContentType.VIDEO,
            ContentType.AUDIO,
            ContentType.FILE,
        }
        text_parts = [
            p
            for p in (parts or [])
            if getattr(p, "type", None) not in media_types
        ]
        media_parts = [
            p for p in (parts or []) if getattr(p, "type", None) in media_types
        ]
        if text_parts:
            await super().send_content_parts(
                to_handle,
                text_parts,
                meta,
            )
        for m in media_parts:
            await self.send_media(to_handle, m, meta)

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        """Send a media part as a Discord file attachment."""
        if not self.enabled or not self._client:
            return
        if not self._client.is_ready():
            return
        import discord

        url = (
            getattr(part, "image_url", None)
            or getattr(part, "video_url", None)
            or getattr(part, "data", None)
            or getattr(part, "file_url", None)
        )
        if not url:
            return

        target = await self._resolve_target(to_handle, meta)
        if not target:
            logger.warning(
                "discord send_media: cannot resolve target",
            )
            return

        temp_path = None
        if url.startswith("file://"):
            file = discord.File(url[7:])
        elif url.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "discord send_media: download failed status=%d",
                            resp.status,
                        )
                        return
                    data = await resp.read()
            parsed_path = urlparse(url).path
            suffix = Path(parsed_path).suffix
            fname = Path(parsed_path).name or f"file{suffix}"
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=suffix,
            ) as tmp:
                tmp.write(data)
            temp_path = tmp.name
            file = discord.File(
                temp_path,
                filename=fname,
            )
        else:
            return

        try:
            await target.send(file=file)
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

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
        # to_handle format: discord:ch:<channel_id> or discord:dm:<user_id>
        parts = (to_handle or "").split(":")
        if len(parts) >= 3 and parts[0] == "discord":
            kind, ident = parts[1], parts[2]
            if kind == "ch":
                return {"channel_id": ident}
            if kind == "dm":
                return {"user_id": ident}
        return {}
