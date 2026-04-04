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
import logging
import os
import re
import tempfile
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

from ....config.config import BaseChannelConfig as WhatsAppConfig
from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
    OutgoingContentPart,
)

logger = logging.getLogger(__name__)

WHATSAPP_MAX_TEXT_LENGTH = 4096
_MEDIA_DIR = Path(tempfile.gettempdir()) / "copaw_whatsapp_media"

try:
    from neonize.aioze.client import NewAClient
    from neonize.events import (
        MessageEv,
        ConnectedEv,
        QREv,
        PairStatusEv,
    )
    NEONIZE_AVAILABLE = True
    from neonize.utils import build_jid
    from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
        Message as WAMessage,
        ExtendedTextMessage,
        ContextInfo,
        ImageMessage,
    )
    NEONIZE_AVAILABLE = True
except ImportError:
    NEONIZE_AVAILABLE = False
    NewAClient = None
    logger.warning("neonize not installed. WhatsApp channel unavailable. Install: pip install neonize")


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
        self._auth_dir = Path(auth_dir).expanduser() if auth_dir else Path.home() / ".copaw" / "credentials" / "whatsapp"
        self._send_read_receipts = send_read_receipts
        self._text_chunk_limit = text_chunk_limit
        self._self_chat_mode = self_chat_mode
        self._groups: List[str] = kwargs.get("groups") or []
        self._group_allow_from: List[str] = kwargs.get("group_allow_from") or []
        self._media_dir = _MEDIA_DIR
        self._client: Optional[Any] = None
        self._lid_cache: Dict[str, Dict[str, str]] = {}  # lid -> {"phone": "+852...", "name": "Joe"}
        self._connected = False
        self._connect_task = None
        self._my_jid = None
        self._bot_phone = ""
        self._bot_lid = ""

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
            groups=c.get("groups") or [],
            group_allow_from=c.get("group_allow_from") or [],
        )

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
                db_path = str(self._auth_dir / "neonize.db")
                conn = sqlite3.connect(db_path)
                row = conn.execute("SELECT jid, lid FROM whatsmeow_device LIMIT 1").fetchone()
                conn.close()
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
            # Enable delivery receipts (double check marks)
            try:
                await client.set_force_activate_delivery_receipts(True)
                logger.info("whatsapp: delivery receipts activated")
            except Exception as e:
                logger.warning("whatsapp: delivery receipts failed: %s", e)

        @self._client.event(QREv)
        async def on_qr(client, evt):
            logger.info("whatsapp: QR code event received (authentication needed)")

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
                content_parts.append(TextContent(type=ContentType.TEXT, text=caption))
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                path = self._media_dir / f"wa_img_{msg_id}.jpg"
                await client.download_media_with_path(msg, str(path))
                content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=str(path)))
            except Exception as e:
                logger.warning("whatsapp: image download failed: %s", e)

        # Audio/voice
        if msg.HasField("audioMessage"):
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                ext = "ogg" if msg.audioMessage.ptt else "m4a"
                path = self._media_dir / f"wa_audio_{msg_id}.{ext}"
                await client.download_media_with_path(msg, str(path))
                content_parts.append(AudioContent(type=ContentType.AUDIO, data=str(path)))
            except Exception as e:
                logger.warning("whatsapp: audio download failed: %s", e)

        # Document
        if msg.HasField("documentMessage"):
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                fname = msg.documentMessage.fileName or f"wa_doc_{msg_id}"
                path = self._media_dir / fname
                await client.download_media_with_path(msg, str(path))
                content_parts.append(VideoContent(type=ContentType.VIDEO, video_url=str(path)))
            except Exception as e:
                logger.warning("whatsapp: document download failed: %s", e)

        return body, content_parts

    def _check_access(self, is_group, chat_str, sender_str, sender_jid, client, msg, body) -> bool:
        """Check access control for incoming message.

        Returns True if message is allowed, False if blocked.
        Note: DM allowlist checks that need async LID resolution are
        handled separately in _on_message.
        """
        if is_group:
            if self.group_policy == "allowlist" and self._groups:
                if chat_str not in self._groups:
                    logger.debug("whatsapp: blocked by group allowlist")
                    return False
            if self.require_mention:
                if not self._is_bot_mentioned(msg, body):
                    logger.warning("whatsapp: BLOCKED - mention required but not mentioned")
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

            if not content_parts:
                return

            # Access control (sync checks: group allowlist, mention)
            if not self._check_access(is_group, chat_str, sender_str, sender_jid, client, msg, body):
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
            friendly_sender = f"+{resolved_phone}" if resolved_phone else sender_str

            # For group messages, prepend sender identity to the actual message
            # (skip history context blocks that start with "---")
            if is_group and content_parts:
                sender_label = friendly_sender
                if resolved_name:
                    sender_label = f"{resolved_name} ({friendly_sender})"
                for i, part in enumerate(content_parts):
                    if hasattr(part, "type") and part.type == ContentType.TEXT:
                        txt = part.text or ""
                        # Don't prepend [From] to history context blocks
                        if txt.startswith("---"):
                            continue
                        content_parts[i] = TextContent(
                            type=ContentType.TEXT,
                            text=f"[From {sender_label}]: {txt}"
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

            channel_meta = {
                "platform": "whatsapp",
                "chat_jid": send_chat_jid,
                "sender_jid": sender_str,
                "sender_phone": friendly_sender,
                "sender_name": resolved_name,
                "is_group": is_group,
                "msg_id": msg_id,
                "timestamp": timestamp,
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

            # Send typing indicator
            try:
                typing_jid = chat_jid
                if chat_str.endswith("@lid"):
                    c_info = self._lid_cache.get(chat_str, {})
                    c_phone = c_info.get("phone", "")
                    if c_phone:
                        typing_jid = _str_to_jid(c_phone)
                _jb = typing_jid.SerializeToString()
                # WORKAROUND: access private __client to call SendChatPresence directly.
                # neonize wraps this method but its Go binding has an off-by-one enum
                # index bug for the presence type, so we bypass the wrapper.
                # TODO: Remove once neonize exposes a public API for chat presence.
                await client._NewAClient__client.SendChatPresence(
                    client.uuid, _jb, len(_jb), 0, 0
                )
                logger.info("whatsapp: typing sent to %s", _jid_to_str(typing_jid))
            except Exception as e:
                logger.warning("whatsapp: typing FAILED: %s", e)

            # For commands like /stop, pass raw body for detection
            if body and body.strip().startswith("/"):
                for i, part in enumerate(content_parts):
                    if hasattr(part, "text") and part.text.startswith("[From "):
                        idx = part.text.find("]: ")
                        if idx > 0:
                            raw_text = part.text[idx + 3:]
                            content_parts[i] = TextContent(type=ContentType.TEXT, text=raw_text)
                request = self.build_agent_request_from_user_content(
                    channel_id=self.channel,
                    sender_id=effective_sender,
                    session_id=session_id,
                    content_parts=content_parts,
                    channel_meta=channel_meta,
                )
                request.channel_meta = channel_meta

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
                    logger.warning("whatsapp: reply-to-bot DETECTED")
                    return True
        
        logger.warning("whatsapp: mention check FAILED - my_lid=%s my_phone=%s body=%s",
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

    # ── Outbound send ─────────────────────────────────────────────────

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

        # Extract [Image: /path] patterns
        img_re = re.compile(r'\[Image: (file:///[^\]]+|/[^\]]+)\]')
        img_matches = img_re.findall(text)
        for m in img_matches:
            p = m.replace("file://", "") if m.startswith("file://") else m
            if os.path.isfile(p):
                try:
                    await self._client.send_image(jid, p)
                    logger.info("whatsapp: sent image %s", p)
                except Exception as e:
                    logger.warning("whatsapp: image send failed: %s", e)
            text = text.replace(f"[Image: {m}]", "").strip()

        if not text:
            return

        chunks = self._chunk_text(text)
        for chunk in chunks:
            try:
                logger.info("whatsapp: SENDING to %s: %s", _jid_to_str(jid), chunk[:100])
                await self._client.send_message(jid, chunk)
            except Exception as e:
                logger.error("whatsapp: send failed: %s", e)

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        if not self.enabled or not self._client or not self._connected:
            return
        meta = meta or {}
        chat_jid_str = meta.get("chat_jid") or to_handle
        jid = _str_to_jid(chat_jid_str)

        t = getattr(part, "type", None)
        file_path = None
        if t == ContentType.IMAGE:
            file_path = getattr(part, "image_url", None)
        elif t == ContentType.FILE:
            file_path = getattr(part, "file_url", None)
        elif t == ContentType.AUDIO:
            file_path = getattr(part, "data", None)

        if file_path and os.path.isfile(file_path):
            try:
                if t == ContentType.IMAGE:
                    await self._client.send_image(jid, file_path)
                elif t == ContentType.AUDIO:
                    await self._client.send_audio(jid, file_path, ptt=True)
                else:
                    await self._client.send_document(jid, file_path)
                logger.info("whatsapp: sent media %s", file_path)
            except Exception as e:
                logger.warning("whatsapp: media send failed: %s", e)

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

    # ── Process loop override ─────────────────────────────────────────

    async def _stream_with_tracker(self, payload):
        """Override base to handle CoPaw event format for WhatsApp."""
        import json as _json

        request = self._payload_to_request(payload)
        send_meta = getattr(request, "channel_meta", None) or {}
        to_handle = self.get_to_handle_from_request(request)
        await self._before_consume_process(request)

        text_parts = []
        message_completed = False
        process_iterator = None
        try:
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

        except asyncio.CancelledError:
            if process_iterator:
                await process_iterator.aclose()
            raise
        except Exception:
            logger.exception("whatsapp: _stream_with_tracker failed")
            raise

    # ── Session / routing ─────────────────────────────────────────────

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
