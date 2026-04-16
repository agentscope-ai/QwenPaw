# -*- coding: utf-8 -*-
"""WhatsApp channel: neonize (whatsmeow Go backend).

Features:
- Text messages (DM + group)
- Image/audio/document send and receive
- Mentions
- Reactions
- QR code / pair code authentication
- Group shared sessions
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional, Dict, List, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    AudioContent,
    FileContent,
    VideoContent,
    ContentType,
    RunStatus,
)

from ....config.config import WhatsAppConfig
from ..media_utils import resolve_media_url
from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
    OutgoingContentPart,
)

logger = logging.getLogger(__name__)

WHATSAPP_MAX_TEXT_LENGTH = 4096
from ....constant import WORKING_DIR
_MEDIA_DIR = WORKING_DIR / "media" / "whatsapp"
# Default auth_dir: WORKING_DIR/credentials/whatsapp/default. Derived from
# WORKING_DIR so QWENPAW_WORKING_DIR / legacy ~/.copaw / ~/.qwenpaw fallbacks
# all line up. Override with explicit `auth_dir` in the agent's channel config.
_DEFAULT_AUTH_DIR = WORKING_DIR / "credentials" / "whatsapp" / "default"

try:
    from neonize.aioze.client import NewAClient
    from neonize.events import (
        MessageEv,
        ConnectedEv,
        DisconnectedEv,
        ConnectFailureEv,
        KeepAliveTimeoutEv,
        QREv,
    )
    from neonize.utils import build_jid
    NEONIZE_AVAILABLE = True
except ImportError:
    NEONIZE_AVAILABLE = False
    NewAClient = None
    logger.warning(
        "neonize-qwenpaw not installed. WhatsApp channel unavailable. "
        "Install: pip install qwenpaw[whatsapp] "
        "(or explicitly: pip install neonize-qwenpaw)"
    )


def _jid_to_str(jid) -> str:
    """Convert JID protobuf to readable string."""
    if hasattr(jid, "User") and jid.User:
        return f"{jid.User}@{jid.Server}" if hasattr(jid, "Server") else jid.User
    return str(jid)


def _str_to_jid(s: str):
    """Convert string to JID. Handles phone numbers and group IDs."""
    if "@" in s:
        user, server = s.split("@", 1)
        return build_jid(user, server)
    # Phone number
    num = s.lstrip("+")
    return build_jid(num, "s.whatsapp.net")


def _is_group_jid(jid) -> bool:
    """Check if JID is a group."""
    server = getattr(jid, "Server", "")
    return server == "g.us"


class WhatsAppChannel(BaseChannel):
    """WhatsApp channel using neonize (whatsmeow)."""

    channel = "whatsapp"
    uses_manager_queue = True
    requires_sequential_restart = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool = False,
        auth_dir: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        send_read_receipts: bool = True,
        text_chunk_limit: int = WHATSAPP_MAX_TEXT_LENGTH,
        self_chat_mode: bool = False,
        ack_reaction_thinking: str = "🤔",
        ack_reaction_done: str = "👀",
        ack_reaction_error: str = "⚠️",
        **kwargs,
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
        self._auth_dir = Path(auth_dir).expanduser() if auth_dir else _DEFAULT_AUTH_DIR
        self._send_read_receipts = send_read_receipts
        self._text_chunk_limit = text_chunk_limit
        self._self_chat_mode = self_chat_mode
        self._ack_reaction_thinking = ack_reaction_thinking or ""
        self._ack_reaction_done = ack_reaction_done or ""
        self._ack_reaction_error = ack_reaction_error or ""
        self._groups: List[str] = kwargs.get("groups") or []
        self._group_allow_from: List[str] = kwargs.get("group_allow_from") or []
        self._reply_to_trigger: bool = kwargs.get("reply_to_trigger", True)
        self._pending_quote_msgs: Dict[str, Any] = {}  # chat_jid -> raw neonize message
        self._media_dir = _MEDIA_DIR
        self._client: Optional[Any] = None
        self._lid_cache: Dict[str, Dict[str, str]] = {}  # lid -> {"phone": "+852...", "name": "Joe"}
        self._connected = False
        self._connect_task = None
        self._my_jid = None
        self._bot_phone = ""
        self._bot_lid = ""
        self._group_history: Dict[str, list] = {}  # chat_jid -> [{sender, body, ts}]
        self._group_history_limit = 50

        if self.enabled and not NEONIZE_AVAILABLE:
            logger.error("whatsapp: neonize not installed, channel disabled")
            self.enabled = False

        if self.enabled:
            logger.info("whatsapp: channel initialized (auth_dir=%s)", self._auth_dir)

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[WhatsAppConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
        **kwargs,
    ) -> "WhatsAppChannel":
        if isinstance(config, dict):
            c = config
        elif hasattr(config, "model_dump"):
            c = config.model_dump()
        else:
            c = vars(config) if hasattr(config, "__dict__") else dict(config)
        return cls(
            process=process,
            enabled=bool(c.get("enabled", False)),
            auth_dir=c.get("auth_dir") or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=c.get("dm_policy") or "open",
            group_policy=c.get("group_policy") or "open",
            allow_from=c.get("allow_from") or [],
            deny_message=c.get("deny_message") or "",
            require_mention=c.get("require_mention", False),
            send_read_receipts=c.get("send_read_receipts", True),
            text_chunk_limit=c.get("text_chunk_limit", WHATSAPP_MAX_TEXT_LENGTH),
            self_chat_mode=c.get("self_chat_mode", False),
            ack_reaction_thinking=c.get("ack_reaction_thinking", "🤔"),
            ack_reaction_done=c.get("ack_reaction_done", "👀"),
            ack_reaction_error=c.get("ack_reaction_error", "⚠️"),
            groups=c.get("groups") or [],
            group_allow_from=c.get("group_allow_from") or [],
            reply_to_trigger=c.get("reply_to_trigger", True),
        )

    async def update_config(self, config) -> bool:
        """Patch config in-place without restarting neonize.

        Returns False if auth_dir or enabled changed (needs full restart).
        """
        if isinstance(config, dict):
            c = config
        elif hasattr(config, "model_dump"):
            c = config.model_dump()
        else:
            c = vars(config) if hasattr(config, "__dict__") else dict(config)

        # Fields that require full restart
        new_auth_dir = c.get("auth_dir") or ""
        new_auth_path = (
            Path(new_auth_dir).expanduser()
            if new_auth_dir
            else _DEFAULT_AUTH_DIR
        )
        if new_auth_path != self._auth_dir:
            logger.info("whatsapp: update_config: auth_dir changed, needs restart")
            return False

        new_enabled = bool(c.get("enabled", False))
        if new_enabled != self.enabled:
            logger.info("whatsapp: update_config: enabled changed, needs restart")
            return False

        # Soft-patchable fields
        self._send_read_receipts = c.get("send_read_receipts", True)
        self._text_chunk_limit = c.get("text_chunk_limit", WHATSAPP_MAX_TEXT_LENGTH)
        self._self_chat_mode = c.get("self_chat_mode", False)
        self._ack_reaction_thinking = c.get("ack_reaction_thinking", "") or ""
        self._ack_reaction_done = c.get("ack_reaction_done", "") or ""
        self._ack_reaction_error = c.get("ack_reaction_error", "") or ""
        self._groups = c.get("groups") or []
        self._group_allow_from = c.get("group_allow_from") or []
        self._reply_to_trigger = c.get("reply_to_trigger", True)

        # BaseChannel fields
        self.dm_policy = c.get("dm_policy") or "open"
        self.group_policy = c.get("group_policy") or "open"
        self.allow_from = set(c.get("allow_from") or [])
        self.deny_message = c.get("deny_message") or ""
        self.require_mention = c.get("require_mention", False)
        self._filter_tool_messages = c.get("filter_tool_messages", False)
        self._filter_thinking = c.get("filter_thinking", False)

        logger.info("whatsapp: config updated in-place (neonize preserved)")
        return True

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self.enabled:
            return

        self._auth_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(self._auth_dir / "neonize.db")

        logger.info("whatsapp: starting channel (db=%s)", db_path)
        self._client = NewAClient(name=db_path)

        # Register event handlers BEFORE connecting
        @self._client.event(MessageEv)
        async def on_message(client, message):
            logger.debug("whatsapp: MessageEv received")
            await self._on_message(client, message)

        @self._client.event(ConnectedEv)
        async def on_connected(client, evt):
            self._connected = True
            self._my_jid = client.me
            
            # Read bot JID from database (client.me may be empty at connect time)
            try:
                import sqlite3
                def _read_device_jid():
                    _db = str(self._auth_dir / "neonize.db")
                    _conn = sqlite3.connect(_db)
                    try:
                        return _conn.execute("SELECT jid, lid FROM whatsmeow_device LIMIT 1").fetchone()
                    finally:
                        _conn.close()
                row = await asyncio.to_thread(_read_device_jid)
                if row:
                    jid_str = row[0] or ""  # e.g. "817089933036:1@s.whatsapp.net"
                    lid_str = row[1] or ""  # e.g. "229661330157571:1@lid"
                    # Extract phone number and LID
                    bot_phone = jid_str.split(":")[0] if ":" in jid_str else jid_str.split("@")[0]
                    bot_lid = lid_str.split(":")[0] if ":" in lid_str else lid_str.split("@")[0]
                    self._my_jid = _str_to_jid(bot_phone)
                    self._bot_phone = bot_phone
                    self._bot_lid = bot_lid
                    if bot_lid and bot_phone:
                        self._lid_cache[f"{bot_lid}@lid"] = {"phone": bot_phone, "name": "bot", "lid": f"{bot_lid}@lid"}
                    logger.info("whatsapp: connected as phone=%s lid=%s", bot_phone, bot_lid)
            except Exception as e:
                logger.warning("whatsapp: failed to read JID from DB: %s", e)
            # Enable delivery receipts (double check marks) - gated on config
            if self._send_read_receipts:
                try:
                    await client.set_force_activate_delivery_receipts(True)
                    logger.info("whatsapp: delivery receipts activated")
                except Exception as e:
                    logger.warning("whatsapp: delivery receipts failed: %s", e)

        @self._client.event(QREv)
        async def on_qr(client, evt):
            logger.info("whatsapp: QR code event received (authentication needed)")

        @self._client.event(DisconnectedEv)
        async def on_disconnected(client, evt):
            self._connected = False
            logger.warning("whatsapp: DISCONNECTED — scheduling auto-reconnect in 10s")
            asyncio.get_event_loop().call_later(10, lambda: asyncio.ensure_future(self._auto_reconnect()))

        @self._client.event(ConnectFailureEv)
        async def on_connect_failure(client, evt):
            self._connected = False
            reason = getattr(evt, "reason", "unknown")
            logger.error("whatsapp: connection failure (reason=%s) — scheduling reconnect in 30s", reason)
            asyncio.get_event_loop().call_later(30, lambda: asyncio.ensure_future(self._auto_reconnect()))

        @self._client.event(KeepAliveTimeoutEv)
        async def on_keepalive_timeout(client, evt):
            logger.warning("whatsapp: keepalive timeout — scheduling reconnect in 15s")
            asyncio.get_event_loop().call_later(15, lambda: asyncio.ensure_future(self._auto_reconnect()))

        # Start connection - connect_task must be kept running
        try:
            self._connect_task = await self._client.connect()
            logger.info("whatsapp: channel started, waiting for authentication...")
            # Give time for connection to establish
            await asyncio.sleep(2)
            logger.info("whatsapp: channel status - connected=%s, client=%s, task=%s", 
                       self._connected, self._client is not None, self._connect_task is not None)
        except Exception:
            logger.exception("whatsapp: failed to start")

    async def stop(self) -> None:
        if not self.enabled:
            return

        if self._connect_task:
            self._connect_task.cancel()
            try:
                await self._connect_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._connected = False
        logger.info("whatsapp: channel stopped")

    # ── Inbound message handler ───────────────────────────────────────

    async def _extract_message_content(self, client, msg, msg_id) -> tuple:
        """Extract body text and content parts from a WhatsApp message.

        Returns:
            (body, content_parts) where body is the text string and
            content_parts is a list of Content objects.
        """
        body = ""
        content_parts: List[Any] = []

        # Text message
        if msg.conversation:
            body = msg.conversation
        elif msg.HasField("extendedTextMessage") and msg.extendedTextMessage.text:
            body = msg.extendedTextMessage.text

        # Resolve LID mentions in body (e.g. @229661330157571 -> @+85251159218)
        if body:
            import re as _re
            lid_mentions = _re.findall(r'@(\d{12,20})', body)
            for lid_num in lid_mentions:
                lid_key = f"{lid_num}@lid"
                if lid_key not in self._lid_cache:
                    try:
                        from neonize.utils import build_jid
                        lid_jid = build_jid(lid_num, "lid")
                        await self._resolve_lid(client, lid_key, lid_jid)
                    except Exception:
                        pass
                cached = self._lid_cache.get(lid_key, {})
                phone = cached.get("phone", "")
                if phone:
                    body = body.replace(f"@{lid_num}", f"@+{phone}")

            content_parts.append(TextContent(type=ContentType.TEXT, text=body))

        # Image
        if msg.HasField("imageMessage"):
            img_msg = msg.imageMessage
            caption = img_msg.caption or ""
            if caption and not body:
                body = caption
                content_parts.append(TextContent(type=ContentType.TEXT, text=caption))
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                path = self._media_dir / f"wa_img_{msg_id}.jpg"
                await client.download_any(msg, path=str(path))
                media_url = await resolve_media_url(str(path))
                content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=media_url))
            except Exception as e:
                logger.warning("whatsapp: image download failed: %s", e)

        # Audio/voice
        if msg.HasField("audioMessage"):
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                ext = "ogg" if msg.audioMessage.ptt else "m4a"
                path = self._media_dir / f"wa_audio_{msg_id}.{ext}"
                await client.download_any(msg, path=str(path))
                media_url = await resolve_media_url(str(path))
                content_parts.append(AudioContent(type=ContentType.AUDIO, data=media_url))
            except Exception as e:
                logger.warning("whatsapp: audio download failed: %s", e)

        # Document
        if msg.HasField("documentMessage"):
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                raw_fname = msg.documentMessage.fileName or f"wa_doc_{msg_id}"
                # Sanitize filename to prevent path traversal
                fname = Path(raw_fname).name or f"wa_doc_{msg_id}"
                path = self._media_dir / fname
                await client.download_any(msg, path=str(path))
                media_url = await resolve_media_url(str(path))
                content_parts.append(FileContent(type=ContentType.FILE, file_url=media_url))
            except Exception as e:
                logger.warning("whatsapp: document download failed: %s", e)

        return body, content_parts

    async def _extract_quote_content(self, client, msg) -> List[Any]:
        """Extract the content of a quoted/replied-to WhatsApp message.

        Returns content parts (text + media) so the agent has full context
        of what the user is responding to — not just a stanza ID.

        Note: quotedMessage is a stripped-down proto — media download keys
        are usually absent, so we extract text/captions and describe media
        types rather than attempting (and failing) to download.
        """
        # contextInfo lives on extendedTextMessage, imageMessage, etc.
        ctx = None
        for field in ("extendedTextMessage", "imageMessage", "videoMessage",
                       "audioMessage", "documentMessage", "stickerMessage"):
            if msg.HasField(field):
                sub = getattr(msg, field)
                if hasattr(sub, "contextInfo"):
                    ctx = sub.contextInfo
                    break
        if not ctx:
            return []
        if not (ctx.HasField("quotedMessage") if hasattr(ctx, "HasField") else False):
            return []

        quoted_msg = ctx.quotedMessage
        participant = getattr(ctx, "participant", "") or ""
        if isinstance(participant, str):
            sender_label = participant.split("@")[0] if "@" in participant else participant
        elif hasattr(participant, "User"):
            sender_label = participant.User
        else:
            sender_label = "unknown"

        # Resolve LID to phone/name for display
        # Only treat as LID if the participant JID server is "lid", not just because it is numeric
        is_lid = False
        if isinstance(participant, str) and "@lid" in participant:
            is_lid = True
        elif hasattr(participant, "Server") and getattr(participant, "Server", "") == "lid":
            is_lid = True
        lid_key = f"{sender_label}@lid" if is_lid and sender_label else ""
        if lid_key:
            if lid_key not in self._lid_cache:
                try:
                    from neonize.utils import build_jid
                    lid_jid = build_jid(sender_label, "lid")
                    await self._resolve_lid(client, lid_key, lid_jid)
                except Exception:
                    pass
            cached = self._lid_cache.get(lid_key, {})
            phone = cached.get("phone", "")
            name = cached.get("name", "")
            if phone and name:
                sender_label = f"+{phone} ({name})"
            elif phone:
                sender_label = f"+{phone}"

        # Extract what we can from the quoted message proto
        quote_body = ""
        media_types = []

        # Text
        if getattr(quoted_msg, "conversation", ""):
            quote_body = quoted_msg.conversation
        elif quoted_msg.HasField("extendedTextMessage") and quoted_msg.extendedTextMessage.text:
            quote_body = quoted_msg.extendedTextMessage.text

        # Detect media types present in quoted message
        if quoted_msg.HasField("imageMessage"):
            caption = getattr(quoted_msg.imageMessage, "caption", "") or ""
            if caption and not quote_body:
                quote_body = caption
            media_types.append("image")
            # Try to download quoted image (may work if media key is present)
            stanza_id = getattr(ctx, "stanzaId", "") or "quote"
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                path = self._media_dir / f"wa_quote_{stanza_id[:12]}.jpg"
                await client.download_any(quoted_msg, path=str(path))
                if path.exists() and path.stat().st_size > 0:
                    block = self._format_reply_context(
                        sender=sender_label,
                        body=quote_body,
                        media_types=["image"],
                    )
                    return [
                        TextContent(type=ContentType.TEXT, text=block),
                        ImageContent(type=ContentType.IMAGE, image_url=await resolve_media_url(str(path))),
                    ]
            except Exception:
                pass  # Download failed — describe instead
        if quoted_msg.HasField("videoMessage"):
            media_types.append("video")
        if quoted_msg.HasField("audioMessage"):
            ptt = getattr(quoted_msg.audioMessage, "ptt", False)
            media_types.append("voice note" if ptt else "audio")
        if quoted_msg.HasField("documentMessage"):
            fname = getattr(quoted_msg.documentMessage, "fileName", "") or ""
            media_types.append(f"file: {fname}" if fname else "document")
        if quoted_msg.HasField("stickerMessage"):
            media_types.append("sticker")

        if not quote_body and not media_types:
            return []

        return [TextContent(
            type=ContentType.TEXT,
            text=self._format_reply_context(
                sender=sender_label,
                body=quote_body,
                media_types=media_types,
            ),
        )]

    @staticmethod
    def _format_reply_context(sender: str, body: str, media_types: List[str]) -> str:
        """Build the OpenClaw-style bounded reply-to context block."""
        lines = ["=== UNTRUSTED reply-to (this message quotes an earlier one) ==="]
        lines.append(f"From: {sender}")
        if body:
            lines.append(f"Message: {body[:400]}")
        if media_types:
            lines.append(f"Media: {', '.join(media_types)}")
        lines.append("=== end of reply-to ===")
        return "\n".join(lines)

    def _check_access(self, is_group, chat_str, sender_str, sender_jid, client, msg, body) -> bool:
        """Check access control for incoming message.

        Returns True if message is allowed, False if blocked.
        Note: DM allowlist checks that need async LID resolution are
        handled separately in _on_message.
        Note: Mention checks are handled in _on_message (after content
        extraction) so non-mentioned messages can be recorded in group
        history for context injection.
        """
        if is_group:
            if self.group_policy == "allowlist":
                if not self._groups or chat_str not in self._groups:
                    logger.debug("whatsapp: blocked group %s (allowlist=%s)", chat_str[:20], self._groups)
                    return False
            # Enforce group_allow_from: if set and not ["*"], check sender
            if self._group_allow_from and "*" not in self._group_allow_from:
                sender_user = sender_str.split("@")[0] if "@" in sender_str else sender_str
                if (sender_str not in self._group_allow_from
                        and sender_user not in self._group_allow_from
                        and f"+{sender_user}" not in self._group_allow_from):
                    logger.debug("whatsapp: blocked sender %s in group (group_allow_from=%s)", sender_str[:20], self._group_allow_from)
                    return False
        return True

    async def _on_message(self, client, message) -> None:
        try:
            # Resolve bot's own LID on first message
            if self._my_jid and not self._lid_cache.get(_jid_to_str(self._my_jid)):
                await self._resolve_lid(client, _jid_to_str(self._my_jid), self._my_jid)

            info = message.Info
            source = info.MessageSource
            sender_jid = source.Sender
            chat_jid = source.Chat
            is_group = source.IsGroup
            is_from_me = source.IsFromMe
            msg_id = info.ID
            timestamp = info.Timestamp

            logger.info("whatsapp: [RAW] sender=%s chat=%s is_group=%s is_from_me=%s",
                       _jid_to_str(sender_jid), _jid_to_str(chat_jid), is_group, is_from_me)

            # Skip own messages unless self_chat_mode
            if is_from_me and not self._self_chat_mode:
                logger.debug("whatsapp: skipping own message (self_chat_mode=%s)", self._self_chat_mode)
                return

            sender_str = _jid_to_str(sender_jid)
            chat_str = _jid_to_str(chat_jid)

            # Extract message content via helper
            msg = message.Message
            body, content_parts = await self._extract_message_content(client, msg, msg_id)

            # Extract quoted/replied-to message content
            quote_parts = await self._extract_quote_content(client, msg)
            if quote_parts:
                content_parts = quote_parts + content_parts

            if not content_parts:
                return

            # Access control (sync checks: group allowlist)
            if not self._check_access(is_group, chat_str, sender_str, sender_jid, client, msg, body):
                return

            # Group mention gate — record non-mentioned messages for context
            # Slash commands (/new, /stop, /clear, etc.) bypass mention gate
            is_slash_command = bool(body and body.lstrip().startswith("/"))
            if is_group and self.require_mention and not is_slash_command:
                if not self._is_bot_mentioned(msg, body):
                    # Buffer for later context injection when bot IS mentioned
                    if body or content_parts:
                        # Resolve LID to phone/name for readable history
                        if sender_str.endswith("@lid"):
                            await self._resolve_lid(client, sender_str, sender_jid)
                        display = self._format_sender(sender_str)
                        # Collect media paths from the already-downloaded
                        # attachments so the agent can see them when
                        # context is injected.
                        media_paths = []
                        for part in content_parts:
                            for attr in ("image_url", "video_url", "file_url", "data"):
                                v = getattr(part, attr, None)
                                if v and os.path.isfile(str(v)):
                                    media_paths.append(str(v))
                                    break
                        history = self._group_history.setdefault(chat_str, [])
                        history.append({
                            "sender": display,
                            "body": body or "[media]",
                            "ts": str(timestamp),
                            "media": media_paths,
                        })
                        if len(history) > self._group_history_limit:
                            self._group_history[chat_str] = history[-self._group_history_limit:]
                    return

            # Async DM allowlist check (needs LID resolution)
            if not is_group:
                if self.dm_policy == "allowlist" and self.allow_from:
                    resolved = await self._resolve_lid(client, sender_str, sender_jid)
                    resolved_phone = resolved.get("phone", "")
                    sender_phone = sender_str.split('@')[0] if '@' in sender_str else sender_str
                    allowed = (
                        sender_str in self.allow_from or
                        sender_phone in self.allow_from or
                        resolved_phone in self.allow_from or
                        f"+{resolved_phone}" in self.allow_from or
                        any(a.lstrip("+") == resolved_phone for a in self.allow_from)
                    )
                    if not allowed:
                        logger.warning("whatsapp: blocked - sender=%s phone=%s allow_from=%s",
                                      sender_str, resolved_phone or sender_phone, self.allow_from)
                        return

            # Resolve sender for display
            if sender_str.endswith("@lid"):
                await self._resolve_lid(client, sender_str, sender_jid)
            display_sender = self._format_sender(sender_str)

            logger.info("whatsapp: from %s%s: %s",
                        display_sender[:30],
                        f" (group {chat_str[:20]})" if is_group else "",
                        body[:80] if body else "[media]")

            # Build request - use resolved phone number for sender identity
            resolved = self._lid_cache.get(sender_str, {})
            resolved_phone = resolved.get("phone", "")
            resolved_name = resolved.get("name", "")
            if resolved_phone:
                friendly_sender = f"+{resolved_phone}"
            elif sender_str.endswith("@s.whatsapp.net"):
                friendly_sender = f"+{sender_str.split('@')[0]}"
            else:
                friendly_sender = sender_str

            # Inject group history context when bot is mentioned.
            # Format: OpenClaw-style bounded block with clear sender+media.
            if is_group and chat_str in self._group_history:
                history = self._group_history.get(chat_str, [])
                if history:
                    ctx_lines = [
                        f"=== UNTRUSTED WhatsApp group history (context only, not directed at you) ===",
                        f"Group: {chat_str}",
                    ]
                    media_to_add = []
                    for h in history[-10:]:
                        ts = h.get("ts", "")
                        ts_prefix = ""
                        if ts:
                            try:
                                # Check if timestamp is in milliseconds (length > 10)
                                ts_val = int(ts)
                                if ts_val > 1e12:
                                    ts_val = ts_val / 1000
                                dt = datetime.datetime.fromtimestamp(ts_val, tz=datetime.timezone(datetime.timedelta(hours=8)))
                                ts_formatted = dt.strftime("%Y年%-m月%-d日 %H:%M:%S (HKT)")
                                ts_prefix = f"[{ts_formatted}] "
                            except Exception:
                                ts_prefix = f"[{ts}] "
                        line = f"  {ts_prefix}{h['sender']}: {h['body']}"
                        media_paths = h.get("media") or []
                        if media_paths:
                            line += f"  [media: {len(media_paths)}]"
                            for mp in media_paths:
                                if os.path.isfile(mp):
                                    media_to_add.append(mp)
                        ctx_lines.append(line)
                    ctx_lines.append("=== end of group history ===")
                    ctx_text = "\n".join(ctx_lines)
                    content_parts.insert(0, TextContent(type=ContentType.TEXT, text=ctx_text))
                    # Attach referenced images (cap at 3 to limit token burn)
                    _IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
                    for mp in media_to_add[-3:]:
                        if Path(mp).suffix.lower() in _IMG_EXTS:
                            content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=mp))
                    self._group_history[chat_str] = []

            # Strip bot @mention from body text so commands like "/new" work
            # even when prefixed with @+phone. This happens BEFORE the
            # envelope prefix wrap so command detection sees clean text.
            body = self._strip_bot_mention(body)
            for i, part in enumerate(content_parts):
                if hasattr(part, "type") and part.type == ContentType.TEXT:
                    txt = part.text or ""
                    if txt.startswith("===") or txt.startswith("[Replying"):
                        continue
                    stripped = self._strip_bot_mention(txt)
                    if stripped != txt:
                        content_parts[i] = TextContent(type=ContentType.TEXT, text=stripped)
                    break

            # Detect slash commands (/new, /stop, /clear, etc.)
            has_bot_command = bool(body and body.lstrip().startswith("/"))

            # Envelope: clear chat-type + sender prefix so the agent never
            # mistakes a group for a DM.
            # Group:  [WhatsApp group {chat_jid}] Joe HO (+85251159218): text
            # DM:     [WhatsApp DM] +85251159218: text
            sender_label = friendly_sender
            if resolved_name:
                sender_label = f"{resolved_name} ({friendly_sender})"
            if is_group:
                envelope = f"[WhatsApp group {chat_str}] {sender_label}"
            else:
                envelope = f"[WhatsApp DM] {sender_label}"
            for i, part in enumerate(content_parts):
                if hasattr(part, "type") and part.type == ContentType.TEXT:
                    txt = part.text or ""
                    if txt.startswith("===") or txt.startswith("[Replying"):
                        continue
                    content_parts[i] = TextContent(
                        type=ContentType.TEXT,
                        text=f"{envelope}: {txt}"
                    )
                    break

            effective_sender = f"group:{chat_str}" if is_group else friendly_sender
            # Also resolve chat LID to phone for send target
            send_chat_jid = chat_str
            if chat_str.endswith("@lid"):
                chat_resolved = self._lid_cache.get(chat_str, {})
                chat_phone = chat_resolved.get("phone", "")
                if chat_phone:
                    send_chat_jid = f"{chat_phone}@s.whatsapp.net"

            # Resolve typing JID for typing loop during response
            typing_jid = chat_jid
            if chat_str.endswith("@lid"):
                c_info = self._lid_cache.get(chat_str, {})
                c_phone = c_info.get("phone", "")
                if c_phone:
                    typing_jid = _str_to_jid(c_phone)

            channel_meta = {
                "platform": "whatsapp",
                "chat_jid": send_chat_jid,
                "sender_jid": sender_str,
                "sender_phone": friendly_sender,
                "sender_name": resolved_name,
                "is_group": is_group,
                "msg_id": msg_id,
                "timestamp": timestamp,
                "bot_phone": f"+{self._bot_phone}" if self._bot_phone else "",
                "bot_lid": self._bot_lid,
                "has_bot_command": has_bot_command,
                "bot_mentioned": True,  # We only reach here if mention check passed
            }
            session_id = self.resolve_session_id(effective_sender, channel_meta)
            request = self.build_agent_request_from_user_content(
                channel_id=self.channel,
                sender_id=effective_sender,
                session_id=session_id,
                content_parts=content_parts,
                channel_meta=channel_meta,
            )
            request.channel_meta = channel_meta
            # Store typing info on request (NOT in channel_meta — JID/client are not JSON-serializable)
            request._wa_typing_jid = typing_jid
            request._wa_typing_client = client
            # Store ack-reaction target so _stream_with_tracker can clear it
            request._wa_ack_chat_jid = chat_jid
            request._wa_ack_sender_jid = sender_jid
            request._wa_ack_msg_id = msg_id
            # Store raw neonize message for reply-to quoting
            request._wa_raw_message = message

            # Mark as read
            if self._send_read_receipts:
                try:
                    await client.mark_read(
                        [info.ID],
                        chat_jid,
                        sender_jid,
                    )
                except Exception:
                    pass

            # For slash commands (/new, /stop, /clear, etc.), strip the
            # envelope prefix ([WhatsApp group xxx] Sender: ...) so the
            # command registry sees the raw command text.
            # Also remove group history context — it prepends text that
            # breaks command detection (query must start with /command).
            if has_bot_command:
                content_parts = [
                    p for p in content_parts
                    if not (hasattr(p, "text") and isinstance(p.text, str)
                            and p.text.startswith("=== UNTRUSTED"))
                ]
                for i, part in enumerate(content_parts):
                    if hasattr(part, "text") and part.text.startswith("[WhatsApp "):
                        # Format is: [WhatsApp group xxx] Name (+phone): text
                        # Strip up to the first ": " after the closing bracket.
                        bracket_end = part.text.find("] ")
                        if bracket_end > 0:
                            after_bracket = part.text[bracket_end + 2:]
                            idx = after_bracket.find(": ")
                            if idx > 0:
                                raw_text = after_bracket[idx + 2:]
                                content_parts[i] = TextContent(type=ContentType.TEXT, text=raw_text)
                        break
                request = self.build_agent_request_from_user_content(
                    channel_id=self.channel,
                    sender_id=effective_sender,
                    session_id=session_id,
                    content_parts=content_parts,
                    channel_meta=channel_meta,
                )
                request.channel_meta = channel_meta
                request._wa_typing_jid = typing_jid
                request._wa_typing_client = client
                request._wa_ack_chat_jid = chat_jid
                request._wa_ack_sender_jid = sender_jid
                request._wa_ack_msg_id = msg_id
                request._wa_raw_message = message

            # Fire "thinking" reaction (fire-and-forget) so the user
            # knows the bot has picked up their message before the
            # agent's reply lands.
            if self._ack_reaction_thinking:
                asyncio.create_task(self._send_reaction(
                    client, chat_jid, sender_jid, msg_id,
                    self._ack_reaction_thinking,
                ))

            # Route through UnifiedQueueManager (via self._enqueue) so
            # each (whatsapp, session_id, priority) gets its own queue
            # and worker task. Messages from different chats process
            # in parallel; same-chat messages still serialize
            # (prevents races inside one conversation).
            #
            # NOTE: direct `await self.consume_one(request)` would
            # block neonize's message callback until the agent's full
            # response finishes, which serializes ALL inbound traffic
            # (DM + group messages stack up). Fall back to direct call
            # if no enqueue callback is attached (unit tests set up
            # channels without the manager).
            if self._enqueue is not None:
                self._enqueue(request)
            else:
                await self.consume_one(request)

        except Exception:
            logger.exception("whatsapp: error processing message")

    def _is_bot_mentioned(self, msg, body: str) -> bool:
        """Check if bot is mentioned in message or message is a reply to bot."""
        if not self._my_jid:
            return False
        
        my_lid = self._bot_lid or getattr(self._my_jid, "User", "") or ""
        my_phone = self._bot_phone or ""
        if not my_phone:
            bot_jid_str = _jid_to_str(self._my_jid) if self._my_jid else ""
            bot_info = self._lid_cache.get(bot_jid_str, {})
            my_phone = bot_info.get("phone", "")
        
        # 1. Check body text for @LID or @phone
        if my_lid and f"@{my_lid}" in body:
            return True
        if my_phone and (f"@{my_phone}" in body or f"@+{my_phone}" in body):
            return True
        
        # 2. Check WhatsApp native mention (contextInfo.mentionedJID)
        ctx = None
        if msg.HasField("extendedTextMessage"):
            ctx = msg.extendedTextMessage.contextInfo
        if ctx:
            # Check mentionedJID - must be EXACT match, not substring
            if ctx.mentionedJID:
                for jid in ctx.mentionedJID:
                    if hasattr(jid, "User"):
                        jid_user = jid.User
                    elif isinstance(jid, str):
                        jid_user = jid.split("@")[0] if "@" in jid else jid
                    else:
                        continue
                    # Exact match only
                    if jid_user and (jid_user == my_lid or jid_user == my_phone):
                        return True
            
            # 3. Reply-to bot message counts as mention
            if ctx.HasField("quotedMessage") or getattr(ctx, "stanzaId", ""):
                # Check if the quoted message is from bot
                quoted_participant = getattr(ctx, "participant", "") or ""
                if isinstance(quoted_participant, str):
                    qp_user = quoted_participant.split("@")[0] if "@" in quoted_participant else quoted_participant
                elif hasattr(quoted_participant, "User"):
                    qp_user = quoted_participant.User
                else:
                    qp_user = ""
                if qp_user and (qp_user == my_lid or qp_user == my_phone):
                    logger.debug("whatsapp: reply-to-bot detected")
                    return True
        
        logger.debug("whatsapp: mention check failed - my_lid=%s my_phone=%s body=%s",
                     my_lid, my_phone, body[:60])
        return False

    async def _resolve_lid(self, client, lid_str: str, lid_jid=None) -> Dict[str, str]:
        """Resolve LID to phone number + name. Caches results."""
        if lid_str in self._lid_cache:
            return self._lid_cache[lid_str]
        
        result = {"phone": "", "name": "", "lid": lid_str}
        
        if not lid_str.endswith("@lid"):
            # Already a phone number
            result["phone"] = lid_str.split("@")[0]
            return result
        
        lid_user = lid_str.split("@")[0]
        
        # Try get_pn_from_lid
        if client and lid_jid:
            try:
                pn_jid = await client.get_pn_from_lid(lid_jid)
                if pn_jid and hasattr(pn_jid, "User") and pn_jid.User:
                    result["phone"] = pn_jid.User
                    logger.info("whatsapp: LID %s -> phone %s", lid_user, result["phone"])
            except Exception as e:
                logger.debug("whatsapp: get_pn_from_lid failed for %s: %s", lid_user, e)
        
        # Try contact store for name
        if client:
            try:
                contact = client.contact
                if contact:
                    info = contact.get(lid_jid or lid_str)
                    if info and hasattr(info, "FullName"):
                        result["name"] = info.FullName or ""
            except Exception:
                pass
        
        self._lid_cache[lid_str] = result
        return result

    def _format_sender(self, lid_str: str) -> str:
        """Format sender for display: +85251159218 (Joe) or fallback to LID."""
        cached = self._lid_cache.get(lid_str, {})
        phone = cached.get("phone", "")
        name = cached.get("name", "")
        if phone and name:
            return f"+{phone} ({name})"
        if phone:
            return f"+{phone}"
        return lid_str

    def _strip_bot_mention(self, text: str) -> str:
        """Remove bot @mention (e.g. '@+817089933036') from text.

        Handles both @phone and @LID forms so that slash commands
        preceded by a mention ("@+817089933036 /new") are recognized.
        """
        if not text:
            return text
        import re as _re
        patterns = []
        if self._bot_phone:
            patterns.append(rf"^@\+?{_re.escape(self._bot_phone)}\s*")
        if self._bot_lid:
            patterns.append(rf"^@{_re.escape(self._bot_lid)}\s*")
        out = text
        for pat in patterns:
            out = _re.sub(pat, "", out).strip()
        return out

    # ── Outbound send ─────────────────────────────────────────────────

    _reconnect_lock = None  # initialized in start()

    async def _auto_reconnect(self):
        """Attempt to reconnect the WhatsApp neonize client after disconnect.

        Uses a lock to prevent concurrent reconnect attempts. Retries with
        exponential backoff indefinitely (capped at 5 minutes).
        """
        if self._reconnect_lock is None:
            self._reconnect_lock = asyncio.Lock()

        if self._reconnect_lock.locked():
            logger.debug("whatsapp: reconnect already in progress, skipping")
            return

        async with self._reconnect_lock:
            backoff = 10
            attempt = 0
            while True:  # infinite retry
                attempt += 1
                logger.info("whatsapp: reconnect attempt %d...", attempt)
                try:
                    # Stop old connection if still lingering
                    if self._connect_task and not self._connect_task.done():
                        self._connect_task.cancel()
                        try:
                            await self._connect_task
                        except (asyncio.CancelledError, Exception):
                            pass

                    # Re-connect
                    self._connect_task = await self._client.connect()
                    # Wait for ConnectedEv to set self._connected
                    await asyncio.sleep(5)
                    if self._connected:
                        logger.info("whatsapp: reconnected on attempt %d", attempt)
                        return
                except Exception as e:
                    logger.error("whatsapp: reconnect attempt %d failed: %s", attempt, e)

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)  # cap at 5 minutes

                # Log periodic status
                if attempt % 10 == 0:
                    logger.warning("whatsapp: still trying to reconnect (attempt %d, backoff=%ds)", attempt, backoff)

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        if not self.enabled or not self._client or not self._connected:
            return
        if not text:
            return

        # Replace LID mentions with phone numbers + strip + prefix for neonize mention detection
        import re as _re
        for lid_str, info in self._lid_cache.items():
            phone = info.get("phone", "")
            if phone and lid_str.endswith("@lid"):
                lid_num = lid_str.split("@")[0]
                text = text.replace(f"@{lid_num}", f"@{phone}")
                text = text.replace(f"@+{lid_num}", f"@{phone}")
        # Also convert @+phone to @phone (neonize needs digits only after @)
        text = _re.sub(r'@\+(\d{5,16})', lambda m: '@' + m.group(1), text)

        meta = meta or {}
        chat_jid_str = meta.get("chat_jid") or to_handle
        jid = _str_to_jid(chat_jid_str)

        # Extract [Image: /path] patterns — restricted to media dir to prevent
        # LLM-driven file exfiltration (e.g. /etc/passwd)
        img_re = re.compile(r'\[Image: (file:///[^\]]+|/[^\]]+)\]')
        img_matches = img_re.findall(text)
        safe_dir = str(self._media_dir.resolve())
        for m in img_matches:
            p = m.replace("file://", "") if m.startswith("file://") else m
            resolved = str(Path(p).resolve())
            if Path(resolved).is_relative_to(safe_dir) and os.path.isfile(resolved):
                try:
                    await self._client.send_image(jid, resolved)
                    logger.info("whatsapp: sent image %s", resolved)
                except Exception as e:
                    logger.warning("whatsapp: image send failed: %s", e)
            elif os.path.isfile(p):
                logger.warning("whatsapp: blocked send of %s — outside media dir %s", p, safe_dir)
            text = text.replace(f"[Image: {m}]", "").strip()

        if not text:
            return

        chunks = self._chunk_text(text)
        # Reply-to: quote the original inbound message on the first chunk
        chat_jid_key = meta.get("chat_jid") or to_handle
        quote_msg = self._pending_quote_msgs.pop(chat_jid_key, None) if self._reply_to_trigger else None
        for i, chunk in enumerate(chunks):
            try:
                logger.info("whatsapp: SENDING to %s: %s", _jid_to_str(jid), chunk[:100])
                if i == 0 and quote_msg is not None and self._client:
                    # Build reply message quoting the inbound trigger
                    reply_built = await self._client.build_reply_message(
                        message=chunk,
                        quoted=quote_msg,
                    )
                    await self._client.send_message(jid, reply_built)
                else:
                    await self._client.send_message(jid, chunk)
            except Exception as e:
                logger.error("whatsapp: send failed: %s", e)

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        """Send a single outbound media attachment (image / video / audio / file).

        This is the primary outbound media path for WhatsApp. It is
        invoked by the base channel's ``send_content_parts`` for every
        non-text content block in the agent's reply — so when the
        agent returns an ``ImageBlock`` / ``AudioBlock`` / etc.
        (including via the ``send_file_to_user`` tool), the file
        ends up here.

        Extracts the local path from the content part (``image_url``,
        ``video_url``, ``file_url``/``file_id`` or ``data``), strips the
        ``file://`` scheme if present, then dispatches through neonize
        (``send_image`` / ``send_video`` / ``send_audio`` /
        ``send_document``).

        ✅ Images, video, audio AND documents all flow through here.
        """
        t = getattr(part, "type", None)
        logger.info(
            "whatsapp: send_media called, type=%s to=%s", t, to_handle,
        )
        if not self.enabled or not self._client or not self._connected:
            logger.warning(
                "whatsapp: send_media skipped — enabled=%s client=%s connected=%s",
                self.enabled, bool(self._client), self._connected,
            )
            return
        meta = meta or {}
        chat_jid_str = meta.get("chat_jid") or to_handle
        jid = _str_to_jid(chat_jid_str)

        # Extract the local file path from the content part
        raw_path = None
        if t == ContentType.IMAGE:
            raw_path = getattr(part, "image_url", None)
        elif t == ContentType.VIDEO:
            raw_path = getattr(part, "video_url", None)
        elif t == ContentType.FILE:
            raw_path = getattr(part, "file_url", None) or getattr(part, "file_id", None)
        elif t == ContentType.AUDIO:
            raw_path = getattr(part, "data", None)

        if not raw_path:
            logger.warning("whatsapp: send_media missing path for type=%s", t)
            return
        # Strip file:// scheme (LLM tools often emit file:///path form)
        file_path = (
            raw_path.replace("file://", "")
            if isinstance(raw_path, str) and raw_path.startswith("file://")
            else raw_path
        )
        exists = os.path.isfile(file_path) if file_path else False
        logger.info(
            "whatsapp: send_media file_path=%s exists=%s", file_path, exists,
        )
        if not exists:
            logger.warning("whatsapp: media file not found: %s", file_path)
            return
        try:
            if t == ContentType.IMAGE:
                await self._client.send_image(jid, file_path)
            elif t == ContentType.VIDEO:
                await self._client.send_video(jid, file_path)
            elif t == ContentType.AUDIO:
                await self._client.send_audio(jid, file_path, ptt=True)
            else:  # FILE
                # Extract filename from path to fix the "Untitled" issue on WhatsApp
                filename = os.path.basename(file_path)
                await self._client.send_document(jid, file_path, filename=filename)
            logger.info(
                "whatsapp: sent media to %s (type=%s, size=%d bytes)",
                to_handle, t, os.path.getsize(file_path),
            )
        except Exception as e:
            logger.error(
                "whatsapp: send_media FAILED to=%s type=%s path=%s: %s",
                to_handle, t, file_path, e,
            )

    # ── Text chunking ─────────────────────────────────────────────────

    def _chunk_text(self, text: str) -> list[str]:
        if not text or len(text) <= self._text_chunk_limit:
            return [text] if text else []
        chunks: list[str] = []
        rest = text
        while rest:
            if len(rest) <= self._text_chunk_limit:
                chunks.append(rest)
                break
            chunk = rest[:self._text_chunk_limit]
            last_nl = chunk.rfind("\n")
            if last_nl > self._text_chunk_limit // 2:
                chunk = rest[:last_nl]
            chunks.append(chunk)
            rest = rest[len(chunk):]
        return chunks

    # ── Typing indicator loop ──────────────────────────────────────────

    async def _typing_loop(self, client, typing_jid, interval: float = 4.0):
        """Re-send typing indicator every `interval` seconds until cancelled.

        WhatsApp typing indicators expire after ~5s, so we need to keep
        re-sending during the entire response generation.
        """
        try:
            while True:
                try:
                    _jb = typing_jid.SerializeToString()
                    await client._NewAClient__client.SendChatPresence(
                        client.uuid, _jb, len(_jb), 0, 0
                    )
                except Exception:
                    pass
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            # Note: presence type 2 (paused) causes neonize Go panic
            # (index out of range [2] with length 2 in SendChatPresence).
            # WhatsApp auto-clears typing after ~5s, so we just let it expire.
            pass

    # ── Reactions ─────────────────────────────────────────────────────

    async def _send_reaction(
        self,
        client,
        chat_jid,
        sender_jid,
        msg_id: str,
        emoji: str,
    ) -> None:
        """Build + send a reaction to a specific message.

        neonize exposes ``build_reaction(chat, sender, message_id, emoji)``
        which returns a Message protobuf; we then push it through
        ``send_message(to=chat_jid, message=...)``. Pass emoji="" to
        remove an existing reaction.
        """
        try:
            reaction_msg = await client.build_reaction(
                chat_jid, sender_jid, msg_id, emoji or "",
            )
            await client.send_message(chat_jid, reaction_msg)
            logger.debug(
                "whatsapp: reaction %r sent on msg=%s", emoji, msg_id,
            )
        except Exception as e:
            logger.warning("whatsapp: reaction %r failed: %s", emoji, e)

    # ── Process loop override ─────────────────────────────────────────

    async def _stream_with_tracker(self, payload):
        """Override base to handle QwenPaw event format for WhatsApp."""
        import json as _json

        request = self._payload_to_request(payload)
        send_meta = getattr(request, "channel_meta", None) or {}
        to_handle = self.get_to_handle_from_request(request)
        await self._before_consume_process(request)

        text_parts = []
        message_completed = False
        process_iterator = None
        typing_task = None
        try:
            # Start persistent typing loop (re-sends every 4s until cancelled)
            # Typing info stored on request object (not channel_meta) to avoid
            # JSON serialization issues with JID/client objects.
            typing_jid = getattr(request, "_wa_typing_jid", None)
            typing_client = getattr(request, "_wa_typing_client", None)
            # Store raw message for reply-to quoting in send()
            raw_msg = getattr(request, "_wa_raw_message", None)
            if raw_msg and self._reply_to_trigger:
                chat_key = (getattr(request, "channel_meta", None) or {}).get("chat_jid", "")
                if chat_key:
                    self._pending_quote_msgs[chat_key] = raw_msg
            if typing_jid and typing_client:
                typing_task = asyncio.create_task(
                    self._typing_loop(typing_client, typing_jid)
                )

            _runner_health = getattr(self._process, "__self__", None)
            if _runner_health:
                _h = getattr(_runner_health, "_health", "unknown")
                logger.warning("whatsapp: _process runner id=%s health=%s", id(_runner_health), _h)
            process_iterator = self._process(request)
            async for event in process_iterator:
                if hasattr(event, "model_dump_json"):
                    data = event.model_dump_json()
                elif hasattr(event, "json"):
                    data = event.json()
                else:
                    data = _json.dumps({"text": str(event)})
                yield f"data: {data}\n\n"

                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)

                if obj == "message" and status == RunStatus.Completed:
                    await self.on_event_message_completed(request, to_handle, event, send_meta)
                    message_completed = True

                # Fallback text collection
                for part in getattr(event, "content", []) or []:
                    txt = getattr(part, "text", None)
                    if not txt or txt in text_parts:
                        continue
                    if self._filter_thinking:
                        from agentscope_runtime.engine.schemas.agent_schemas import MessageType
                        if getattr(event, "type", None) == MessageType.REASONING:
                            continue
                    text_parts.append(txt)

            if text_parts and not message_completed:
                reply = chr(10).join(text_parts)
                logger.info("whatsapp: sending reply (%d chars) to %s", len(reply), to_handle)
                await self.send(to_handle, reply.strip(), send_meta)

            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)

            # Pick the right closing reaction:
            # - done  when the agent actually produced some reply
            # - error when nothing was sent (agent crashed silently or
            #   produced no content) — user would otherwise see the
            #   thinking emoji stuck forever.
            produced_reply = message_completed or bool(text_parts)
            ack_emoji = (
                self._ack_reaction_done if produced_reply
                else self._ack_reaction_error
            )
            if ack_emoji:
                ack_chat = getattr(request, "_wa_ack_chat_jid", None)
                ack_sender = getattr(request, "_wa_ack_sender_jid", None)
                ack_msg_id = getattr(request, "_wa_ack_msg_id", None)
                ack_client = getattr(request, "_wa_typing_client", None)
                if ack_chat and ack_sender and ack_msg_id and ack_client:
                    await self._send_reaction(
                        ack_client, ack_chat, ack_sender, ack_msg_id,
                        ack_emoji,
                    )

        except asyncio.CancelledError:
            if process_iterator:
                await process_iterator.aclose()
            raise
        except Exception:
            logger.exception("whatsapp: _stream_with_tracker failed")
            # Flip thinking → error so user knows the request died
            if self._ack_reaction_error:
                ack_chat = getattr(request, "_wa_ack_chat_jid", None)
                ack_sender = getattr(request, "_wa_ack_sender_jid", None)
                ack_msg_id = getattr(request, "_wa_ack_msg_id", None)
                ack_client = getattr(request, "_wa_typing_client", None)
                if ack_chat and ack_sender and ack_msg_id and ack_client:
                    try:
                        await self._send_reaction(
                            ack_client, ack_chat, ack_sender, ack_msg_id,
                            self._ack_reaction_error,
                        )
                    except Exception:
                        pass
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()

    # ── Session / routing ─────────────────────────────────────────────

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from WhatsApp native dict payload.

        WhatsApp's main inbound path constructs the AgentRequest inline in
        `_dispatch_message()` with full envelope/history/quote handling,
        but this hook is required by BaseChannel so that any code routing
        through `_payload_to_request()` (e.g. re-delivery, replay, testing)
        still gets a valid AgentRequest with `user_id` + `channel_meta`
        set correctly.
        """
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        user_id = str(meta.get("user_id") or sender_id)
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

    def resolve_session_id(
        self, sender_id: str, channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = channel_meta or {}
        chat_jid = meta.get("chat_jid")
        is_group = meta.get("is_group", False)
        if is_group and chat_jid:
            return f"whatsapp:group:{chat_jid}"
        return f"whatsapp:{sender_id}"

    def get_to_handle_from_request(self, request) -> str:
        meta = getattr(request, "channel_meta", None) or {}
        return meta.get("chat_jid") or getattr(request, "user_id", "") or ""
