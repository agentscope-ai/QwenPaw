# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
from __future__ import annotations

import os
import logging
import asyncio
import re
import tempfile
from collections import deque
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, Optional

import aiohttp
from qwenpaw.schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ....exceptions import ChannelError
from ....config.config import DiscordConfig as DiscordChannelConfig

from ..utils import file_url_to_local_path
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

logger = logging.getLogger(__name__)

# Regex that matches a code-fence opening/closing line (``` or ~~~).
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

_STREAM_PLACEHOLDER = "..."


class DiscordChannel(BaseChannel):
    channel = "discord"
    uses_manager_queue = True
    _DISCORD_MAX_LEN: int = 2000
    _MAX_CACHED_MESSAGE_IDS: int = 500
    _STREAM_DELTA_MIN_INTERVAL_S: float = 1.0

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
        accept_bot_messages: bool = False,
        streaming_enabled: bool = False,
        access_control_dm: bool = False,
        access_control_group: bool = False,
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
            streaming_enabled=streaming_enabled,
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )
        self.enabled = enabled
        self.token = token
        self.http_proxy = http_proxy
        self.http_proxy_auth = http_proxy_auth
        self.bot_prefix = bot_prefix
        self.accept_bot_messages = accept_bot_messages
        self._task: Optional[asyncio.Task] = None
        self._client = None
        self._processed_message_ids: set[str] = set()
        self._processed_message_id_queue: deque[str] = deque()
        # Maps parent_channel_msg_id -> thread_id for race-condition
        # detection when thread creation and first message arrive
        # simultaneously.
        self._recent_thread_starts: dict[str, str] = {}
        # Typing indicator tasks: channel_id (str) -> Task
        self._typing_tasks: dict[str, asyncio.Task] = {}
        # Track which to_handles are currently processing
        self._is_processing: dict[str, bool] = {}

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
                # Always ignore messages from the bot itself
                if message.author == self._client.user:
                    return
                # Filter other bot messages unless
                # accept_bot_messages is enabled
                if message.author.bot and not self.accept_bot_messages:
                    return
                msg_id = str(message.id)
                if msg_id in self._processed_message_ids:
                    logger.debug(
                        "discord: duplicate message %s skipped",
                        msg_id,
                    )
                    return
                if (
                    len(self._processed_message_ids)
                    >= self._MAX_CACHED_MESSAGE_IDS
                ):
                    oldest = self._processed_message_id_queue.popleft()
                    self._processed_message_ids.discard(oldest)
                self._processed_message_ids.add(msg_id)
                self._processed_message_id_queue.append(msg_id)
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
                # Check role mentions:
                # if any mentioned role is one the bot has
                if not is_bot_mentioned and message.guild and bot_user:
                    bot_member = message.guild.get_member(bot_user.id)
                    if bot_member:
                        mentioned_role_ids = {
                            r.id for r in getattr(message, "role_mentions", [])
                        }
                        bot_role_ids = {r.id for r in bot_member.roles}
                        matched_role_ids = mentioned_role_ids & bot_role_ids
                        if matched_role_ids:
                            is_bot_mentioned = True
                            # Remove role mention tags from text
                            for role_id in matched_role_ids:
                                text = re.sub(
                                    rf"<@&{role_id}>",
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
                _is_thread = isinstance(message.channel, discord.Thread)
                _thread_started = (
                    not _is_thread
                    and getattr(message, "thread", None) is not None
                )
                # Race-condition: thread created simultaneously
                # with the first message. on_thread_create may
                # have cached the thread_id before on_message
                # fires for the starter message.
                _race_thread_id = None
                if not _is_thread and not _thread_started and is_group:
                    flags = getattr(message, "flags", None)
                    if flags and getattr(flags, "has_thread", False):
                        _race_thread_id = self._recent_thread_starts.get(
                            str(message.id),
                        )
                # Determine effective channel_id for session routing
                if _is_thread:
                    _effective_channel_id = str(message.channel.id)
                elif _thread_started:
                    _effective_channel_id = str(message.thread.id)
                elif _race_thread_id:
                    _effective_channel_id = _race_thread_id
                else:
                    _effective_channel_id = str(message.channel.id)

                meta = {
                    "user_id": str(message.author.id),
                    "channel_id": _effective_channel_id,
                    "guild_id": (
                        str(message.guild.id) if message.guild else None
                    ),
                    "message_id": str(message.id),
                    "is_dm": not is_group,
                    "is_group": is_group,
                }
                if _is_thread:
                    meta["is_thread"] = True
                    meta["thread_id"] = str(message.channel.id)
                    meta["parent_channel_id"] = (
                        str(message.channel.parent_id)
                        if message.channel.parent_id
                        else None
                    )
                elif _thread_started or _race_thread_id:
                    meta["is_thread"] = True
                    meta["thread_id"] = _effective_channel_id
                    meta["parent_channel_id"] = str(message.channel.id)
                if is_bot_mentioned:
                    meta["bot_mentioned"] = True

                if not self._check_group_mention(is_group, meta):
                    return

                native = {
                    "channel_id": self.channel,
                    "sender_id": str(message.author),
                    "acl_sender_id": str(message.author.id),
                    "content_parts": content_parts,
                    "meta": meta,
                }
                if self._enqueue is not None:
                    self._enqueue(native)
                else:
                    logger.warning(
                        "discord: _enqueue not set, message dropped",
                    )

            @self._client.event
            async def on_thread_create(thread):
                """Cache starter_message_id -> thread_id so on_message
                can detect the race where a thread-starting message
                arrives on the parent channel before the thread exists
                in discord.py's cache."""
                starter = getattr(thread, "starter_message", None)
                if starter:
                    key = str(starter.id)
                    self._recent_thread_starts[key] = str(thread.id)
                    logger.info(
                        "discord thread_create: thread=%s "
                        "starter_msg=%s parent=%s",
                        thread.id,
                        starter.id,
                        thread.parent_id,
                    )
                    # Evict after 30s
                    await asyncio.sleep(30)
                    self._recent_thread_starts.pop(key, None)

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
            bot_prefix=os.getenv("DISCORD_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("DISCORD_DM_POLICY", "open"),
            group_policy=os.getenv("DISCORD_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("DISCORD_DENY_MESSAGE", ""),
            require_mention=os.getenv(
                "DISCORD_REQUIRE_MENTION",
                "0",
            )
            == "1",
            accept_bot_messages=os.getenv(
                "DISCORD_ACCEPT_BOT_MESSAGES",
                "0",
            )
            == "1",
            streaming_enabled=os.getenv(
                "DISCORD_STREAMING_ENABLED",
                "0",
            )
            == "1",
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
            bot_prefix=config.bot_prefix or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=config.dm_policy or "open",
            group_policy=config.group_policy or "open",
            allow_from=config.allow_from or [],
            deny_message=config.deny_message or "",
            require_mention=config.require_mention,
            accept_bot_messages=config.accept_bot_messages,
            streaming_enabled=config.streaming_enabled,
            access_control_dm=bool(
                getattr(config, "access_control_dm", False),
            ),
            access_control_group=bool(
                getattr(config, "access_control_group", False),
            ),
        )

    async def _resolve_target(self, to_handle, _meta):
        """Resolve a Discord Messageable from meta or to_handle."""
        route = self._route_from_handle(to_handle)
        channel_id = route.get("channel_id")
        user_id = route.get("user_id")
        if channel_id:
            cid = int(channel_id)
            ch = self._client.get_channel(cid)
            if ch is None:
                ch = await self._client.fetch_channel(cid)
            return ch
        if user_id:
            uid = int(user_id)
            user = self._client.get_user(uid)
            if user is None:
                user = await self._client.fetch_user(uid)
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

        # Reserve space for a closing fence suffix ("\n```") that _flush()
        # may append when a code block spans chunk boundaries.
        fence_close_len = len("\n```")

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
            # When inside a code fence, reserve space for the closing
            # suffix that _flush() appends.
            reserved = fence_close_len if fence_open else 0
            if (
                current
                and current_len + len(line_with_nl) + reserved > max_len
            ):
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
            raise ChannelError(
                channel_name="discord",
                message="Discord client is not initialized",
            )
        if not self._client.is_ready():
            raise ChannelError(
                channel_name="discord",
                message="Discord client is not ready yet",
            )
        target = await self._resolve_target(to_handle, meta)
        if not target:
            raise ChannelError(
                channel_name="discord",
                message=(
                    "DiscordChannel.send requires "
                    "meta['channel_id'] or meta['user_id']"
                ),
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
        if not self.enabled or not self._client or not self._client.is_ready():
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
            local_path = file_url_to_local_path(url)
            if not local_path:
                logger.warning(
                    "discord send_media: invalid file URL %s",
                    url,
                )
                return
            file = discord.File(local_path)
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

    async def health_check(self) -> Dict[str, Any]:
        """Check Discord gateway connection status."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "Discord channel is disabled.",
            }
        if not self._client:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Discord client not initialized.",
            }
        if not self._client.is_ready():
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": (
                    "Discord client is not ready" " (gateway not connected)."
                ),
            }
        task_alive = self._task is not None and not self._task.done()
        if not task_alive:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Discord gateway task is not running.",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "Discord gateway is connected and ready.",
        }

    async def start(self) -> None:
        if not self.enabled:
            return
        self._task = asyncio.create_task(self._run(), name="discord_gateway")

    async def stop(self) -> None:
        if not self.enabled:
            return
        # Cancel all typing indicator tasks
        for task in self._typing_tasks.values():
            if task and not task.done():
                task.cancel()
        self._typing_tasks.clear()
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

    # ------------------------------------------------------------------
    # Typing indicator (discord.py context manager + hook lifecycle)
    # ------------------------------------------------------------------

    async def _typing_keepalive(self, channel_id: int) -> None:
        """Keep typing indicator alive via async with ch.typing().

        discord.py auto-refreshes typing inside the context manager.
        Cancelling this task exits the context, stopping typing.
        """
        try:
            ch = self._client.get_channel(channel_id)
            if not ch:
                return
            async with ch.typing():
                while self._client and self._client.is_ready():
                    await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    def _start_typing(self, channel_id: int) -> None:
        """Start typing indicator (idempotent)."""
        key = str(channel_id)
        existing = self._typing_tasks.get(key)
        if existing and not existing.done():
            return
        self._typing_tasks[key] = asyncio.create_task(
            self._typing_keepalive(channel_id),
        )

    def _stop_typing(self, channel_id: int) -> None:
        """Stop typing by cancelling the keepalive task."""
        key = str(channel_id)
        task = self._typing_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # Lifecycle hooks (align with yuanbao pattern)
    # ------------------------------------------------------------------

    async def _before_consume_process(
        self,
        request: Any,
    ) -> None:
        """Start typing before agent processes the request."""
        meta = getattr(request, "channel_meta", None) or {}
        channel_id = meta.get("channel_id", "")
        if channel_id:
            to_handle = self.get_to_handle_from_request(request)
            self._is_processing[to_handle] = True
            try:
                self._start_typing(int(channel_id))
            except (ValueError, TypeError):
                pass

    async def _on_process_completed(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Stop typing after all processing completes."""
        self._is_processing.pop(to_handle, None)
        channel_id = (send_meta or {}).get("channel_id", "")
        if channel_id:
            try:
                self._stop_typing(int(channel_id))
            except (ValueError, TypeError):
                pass
        await super()._on_process_completed(
            request,
            to_handle,
            send_meta,
        )

    async def _on_consume_error(
        self,
        request: Any,
        to_handle: str,
        err_text: str,
    ) -> None:
        """Stop typing on error."""
        self._is_processing.pop(to_handle, None)
        meta = getattr(request, "channel_meta", None) or {}
        channel_id = meta.get("channel_id", "")
        if channel_id:
            try:
                self._stop_typing(int(channel_id))
            except (ValueError, TypeError):
                pass
        await super()._on_consume_error(
            request,
            to_handle,
            err_text,
        )

    # ------------------------------------------------------------------
    # Streaming hooks (Post + Edit, aligned with Telegram)
    # ------------------------------------------------------------------

    def _get_discord_stream_state(
        self,
        send_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get or create per-request Discord streaming state."""
        state = send_meta.get("_discord_stream")
        if state is None:
            state = {"message": None}
            send_meta["_discord_stream"] = state
        return state

    def _build_stream_display_text(
        self,
        stream_type: str,
        text: str,
        send_meta: Dict[str, Any],
    ) -> str:
        """Build display text with bot_prefix and thinking emoji."""
        prefix = send_meta.get("bot_prefix") or self.bot_prefix or ""
        if stream_type == "reasoning" and text:
            if prefix:
                return f"{prefix}  💭 {text}"
            return f"💭 {text}"
        if prefix and text:
            return f"{prefix}  {text}"
        return text

    def _resolve_discord_channel(
        self,
        send_meta: Dict[str, Any],
    ) -> Any:
        """Resolve Discord channel from send_meta['channel_id']."""
        channel_id = send_meta.get("channel_id", "")
        if not channel_id or not self._client:
            return None
        try:
            return self._client.get_channel(int(channel_id))
        except (ValueError, TypeError):
            return None

    async def on_streaming_start(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Send placeholder message and cache for streaming."""
        if not self.streaming_enabled:
            return
        ch = self._resolve_discord_channel(send_meta)
        if not ch:
            return
        state = self._get_discord_stream_state(send_meta)
        placeholder = self._build_stream_display_text(
            stream_type,
            "...",
            send_meta,
        )
        try:
            msg = await ch.send(placeholder)
            state["message"] = msg
        except Exception:
            logger.debug(
                "discord: failed to send streaming placeholder",
            )

    async def on_streaming_delta(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Edit placeholder with accumulated text."""
        state = send_meta.get("_discord_stream")
        if not state:
            return
        msg = state.get("message")
        if not msg:
            return
        display = self._build_stream_display_text(
            stream_type,
            accumulated_text,
            send_meta,
        )
        # Show tail portion when exceeding Discord's message limit
        if len(display) > self._DISCORD_MAX_LEN:
            display = "..." + display[-(self._DISCORD_MAX_LEN - 4) :]
        try:
            await msg.edit(content=display)
        except Exception:
            logger.debug(
                "discord: streaming delta edit failed",
            )

    async def on_streaming_end(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Final edit or fallback to chunked send."""
        state = send_meta.pop("_discord_stream", None)
        msg = state.get("message") if state else None
        final_text = self._build_stream_display_text(
            stream_type,
            accumulated_text,
            send_meta,
        )

        if not msg:
            # Placeholder was never sent; fall back to normal send
            if final_text:
                await self.send(to_handle, final_text, send_meta)
            return

        if len(final_text) <= self._DISCORD_MAX_LEN:
            try:
                await msg.edit(content=final_text)
            except Exception:
                logger.debug(
                    "discord: streaming end edit failed",
                )
        else:
            # Text too long: delete placeholder, use chunked send
            try:
                await msg.delete()
            except Exception:
                pass
            await self.send(to_handle, final_text, send_meta)

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
