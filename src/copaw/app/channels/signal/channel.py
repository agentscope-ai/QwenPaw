# -*- coding: utf-8 -*-
"""Signal channel: HTTP JSON-RPC + SSE with signal-cli daemon.

Features:
- Text messages (DM + group)
- Quote/reply-to (inbound parse + outbound send)
- Attachments/images (inbound download + outbound send)
- Reactions (inbound + outbound)
- Mention detection for groups
- Access control (DM allowlist, group allowlist)
"""

from __future__ import annotations

import asyncio
import aiohttp
import base64
import json
import logging
import os
import time
import tempfile
from pathlib import Path
from typing import Any, Optional, Dict, List, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
    RunStatus,
)

from ....config.config import BaseChannelConfig as SignalConfig
from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
    OutgoingContentPart,
)


import re as _re

_UUID_LIKE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    _re.IGNORECASE,
)


def _looks_like_uuid(s: str) -> bool:
    """True if the string is a Signal/UUID identifier (used to ignore
    'display names' that Signal sends as the raw UUID when the user has
    no real profile name)."""
    return bool(s) and bool(_UUID_LIKE.match(s))

# ── File type detection by magic bytes ───────────────────────────
_MAGIC_MAP = [
    (b"\xff\xd8\xff",             "image/jpeg",  "jpg"),
    (b"\x89PNG\r\n\x1a\n",       "image/png",   "png"),
    (b"GIF87a",                   "image/gif",   "gif"),
    (b"GIF89a",                   "image/gif",   "gif"),
    (b"RIFF",                     "image/webp",  "webp"),  # RIFF....WEBP
    (b"\x1a\x45\xdf\xa3",        "video/webm",  "webm"),
    (b"OggS",                     "audio/ogg",   "ogg"),
    (b"fLaC",                     "audio/flac",  "flac"),
    (b"ID3",                      "audio/mpeg",  "mp3"),
    (b"\xff\xfb",                 "audio/mpeg",  "mp3"),
    (b"%PDF",                     "application/pdf", "pdf"),
]


def _detect_mime(data: bytes) -> str:
    """Detect MIME type from file header bytes."""
    for magic, mime, _ in _MAGIC_MAP:
        if data[:len(magic)] == magic:
            if magic == b"RIFF" and data[8:12] != b"WEBP":
                continue
            return mime
    # MP4/M4A: check for ftyp box (byte 4-7 = "ftyp")
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "video/mp4"
    return ""


def _detect_ext(data: bytes, declared_ct: str) -> str:
    """Pick file extension: trust magic bytes over declared content-type."""
    for magic, mime, ext in _MAGIC_MAP:
        if data[:len(magic)] == magic:
            if magic == b"RIFF" and data[8:12] != b"WEBP":
                continue
            return ext
    # MP4/M4A: check for ftyp box
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "mp4"
    # Fallback to declared content-type
    if "/" in declared_ct and declared_ct != "application/octet-stream":
        return declared_ct.split("/")[-1].split(";")[0]
    return "bin"


def _markdown_to_signal(text):
    """Convert markdown to plain text + Signal text-style ranges.

    Signal supports: BOLD, ITALIC, MONOSPACE, STRIKETHROUGH, SPOILER.
    Markdown headers (# / ## / ###) are converted to BOLD lines since
    Signal has no native header support.
    """
    # ── Phase 1: Convert headers to bold markers ──────────────────
    # "## Heading" → "**Heading**"  (then handled by inline patterns)
    text = _re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", text, flags=_re.MULTILINE)

    # ── Phase 2: Collect inline style matches ─────────────────────
    # Order matters: code blocks first (protect contents), then longer
    # markers before shorter to avoid **bold** eating *italic*.
    patterns = [
        (_re.compile(r"```(?:\w*\n)?(.*?)```", _re.DOTALL), "MONOSPACE"),
        (_re.compile(r"`([^`]+)`"), "MONOSPACE"),
        (_re.compile(r"\*\*(.+?)\*\*"), "BOLD"),
        (_re.compile(r"__(.+?)__"), "BOLD"),
        (_re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), "ITALIC"),
        (_re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"), "ITALIC"),
        (_re.compile(r"~~(.+?)~~"), "STRIKETHROUGH"),
    ]
    all_matches = []
    for pat, style in patterns:
        for m in pat.finditer(text):
            all_matches.append((m.start(), m.end(), m.group(1), style))
    all_matches.sort(key=lambda x: x[0])

    # Remove overlaps (keep earlier / longer match)
    filtered = []
    for s, e, inner, style in all_matches:
        if filtered and s < filtered[-1][1]:
            continue
        filtered.append((s, e, inner, style))

    # ── Phase 3: Build plain text + style ranges ──────────────────
    parts = []
    styles = []
    cursor = 0
    offset = 0
    for s, e, inner, style in filtered:
        before = text[cursor:s]
        parts.append(before)
        offset += len(before)
        styles.append({"start": offset, "length": len(inner), "style": style})
        parts.append(inner)
        offset += len(inner)
        cursor = e
    parts.append(text[cursor:])
    return "".join(parts), styles


def _parse_mentions(text):
    """Parse @+number or @uuid and build Signal mention params."""
    pat = _re.compile(r"@(\+\d{7,15}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
    mentions = []
    result = text
    shift = 0
    for m in pat.finditer(text):
        target = m.group(1)
        pos = m.start() - shift
        replacement = "\ufffc"
        result = result[:pos] + replacement + result[pos + len(m.group(0)):]
        shift += len(m.group(0)) - 1
        mention = {"start": pos, "length": 1}
        if target.startswith("+"):
            mention["number"] = target
        else:
            mention["uuid"] = target
        mentions.append(mention)
    return result, mentions


logger = logging.getLogger(__name__)

SIGNAL_MAX_TEXT_LENGTH = 4000
_MEDIA_DIR = Path(tempfile.gettempdir()) / "copaw_signal_media"


class SignalDaemon:
    """Signal client using bbernhard/signal-cli-rest-api REST+WebSocket API.

    https://github.com/bbernhard/signal-cli-rest-api
    Requires the REST API service (Docker container) running with MODE=json-rpc.
    """

    def __init__(self, account: str, http_url: str):
        self.account = account
        self.http_url = http_url.rstrip("/")
        self.connected = False
        self.connecting = False
        self.ws_task: Optional[asyncio.Task] = None
        self.session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        if self.connecting or self.connected:
            return self.connected
        self.connecting = True
        try:
            self.session = aiohttp.ClientSession()
            async with self.session.get(
                f"{self.http_url}/v1/about",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    logger.info(
                        "Signal REST API connected: %s (mode=%s version=%s)",
                        self.http_url, info.get("mode"), info.get("version"),
                    )
                    self.connected = True
                    return True
                logger.error("Signal REST API check failed: %s", resp.status)
                return False
        except Exception as e:
            logger.error("Signal REST API not available at %s: %s", self.http_url, e)
            return False
        finally:
            self.connecting = False

    async def disconnect(self):
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
            self.ws_task = None
        if self.session:
            await self.session.close()
            self.session = None
        self.connected = False
        logger.info("Signal disconnected")

    @staticmethod
    def _to_recipient(target: str, is_group: bool) -> str:
        """Convert a target ID to bbernhard's recipient format.

        bbernhard uses `group.{base64(internal_id)}` for groups and the
        raw phone number for direct recipients. Signal-cli's internal
        group ID (what we store in config) is the base64 payload.

        Accepts either the raw internal_id, the bbernhard-formatted
        `group.xxx` string, or CoPaw's session-prefixed `group:xxx`
        form (from effective_sender). Returns bbernhard-compatible
        recipient.
        """
        if not is_group:
            return target
        # Strip CoPaw session prefix so we don't double-wrap.
        if target.startswith("group:"):
            target = target[len("group:"):]
        if target.startswith("group."):
            return target
        return "group." + base64.b64encode(target.encode()).decode().rstrip("=") + "="

    # ── Send ──────────────────────────────────────────────────────────

    async def send_message(
        self,
        target: str,
        text: str,
        is_group: bool = False,
        quote_timestamp: int = 0,
        quote_author: str = "",
        attachments: Optional[List[str]] = None,
        text_style: Optional[List[str]] = None,  # kept for compatibility, ignored
        mentions: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[int]:
        """Send message via POST /v2/send. Returns timestamp on success.

        `text_style` is ignored — bbernhard's `text_mode: "styled"` parses
        markdown natively.

        `mentions` is a list of dicts `{start, length, author}` where
        `author` is either "+phone" or a Signal UUID. The `text` must
        contain U+FFFC placeholders at each mention's `start` position.
        """
        if not self.session or not self.connected:
            return None
        recipient = self._to_recipient(target, is_group)
        payload: Dict[str, Any] = {
            "number": self.account,
            "recipients": [recipient],
        }
        if text:
            payload["message"] = text
            payload["text_mode"] = "styled"
        if mentions:
            payload["mentions"] = mentions
        if quote_timestamp and quote_author:
            payload["quote_timestamp"] = quote_timestamp
            payload["quote_author"] = quote_author
        if attachments:
            # bbernhard expects base64-encoded attachments inline.
            encoded = []
            for path in attachments:
                try:
                    with open(path, "rb") as f:
                        import mimetypes
                        mime, _ = mimetypes.guess_type(path)
                        mime = mime or "application/octet-stream"
                        data = base64.b64encode(f.read()).decode()
                        encoded.append(f"data:{mime};base64,{data}")
                except Exception as e:
                    logger.warning("signal: failed to encode attachment %s: %s", path, e)
            if encoded:
                payload["base64_attachments"] = encoded
        try:
            async with self.session.post(
                f"{self.http_url}/v2/send",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (200, 201):
                    result = await resp.json()
                    ts = result.get("timestamp")
                    return int(ts) if ts else None
                body = await resp.text()
                logger.error("Signal send failed to %s: %s %s", target, resp.status, body[:200])
                return None
        except Exception as e:
            logger.error("Signal send exception: %s", e)
            return None

    async def send_reaction(
        self,
        target: str,
        emoji: str,
        target_author: str,
        target_timestamp: int,
        is_group: bool = False,
        remove: bool = False,
    ) -> bool:
        """Send emoji reaction via POST/DELETE /v1/reactions/{number}."""
        if not self.session or not self.connected:
            return False
        recipient = self._to_recipient(target, is_group)
        payload = {
            "reaction": emoji,
            "recipient": recipient,
            "target_author": target_author,
            "timestamp": target_timestamp,
        }
        url = f"{self.http_url}/v1/reactions/{self.account}"
        method = "DELETE" if remove else "POST"
        try:
            async with self.session.request(
                method, url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            logger.error("Signal reaction failed: %s", e)
            return False

    async def send_typing(self, target: str, start: bool = True, is_group: bool = False):
        """Send typing indicator via PUT/DELETE /v1/typing-indicator/{number}."""
        if not self.session or not self.connected:
            return
        recipient = self._to_recipient(target, is_group)
        payload = {"recipient": recipient}
        url = f"{self.http_url}/v1/typing-indicator/{self.account}"
        method = "PUT" if start else "DELETE"
        try:
            async with self.session.request(
                method, url, json=payload,
                timeout=aiohttp.ClientTimeout(total=5),
            ):
                pass
        except Exception:
            pass

    # ── Receive (WebSocket) ───────────────────────────────────────────

    async def start_receive(self, message_callback):
        if self.ws_task:
            return
        self.ws_task = asyncio.create_task(
            self._ws_loop(message_callback), name="signal_ws",
        )

    async def _ws_loop(self, message_callback):
        """Connect to bbernhard's WebSocket receive endpoint."""
        # ws:// or wss:// based on http_url
        ws_url = self.http_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/v1/receive/{self.account}"
        backoff = 5
        while True:
            try:
                logger.info("Signal WS connecting: %s", ws_url)
                async with self.session.ws_connect(
                    ws_url, heartbeat=30,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10),
                ) as ws:
                    logger.info("Signal WS connected, listening...")
                    backoff = 5
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event = json.loads(msg.data)
                                await message_callback(event)
                            except json.JSONDecodeError:
                                pass
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                logger.info("Signal WS loop cancelled")
                break
            except Exception as e:
                logger.error("Signal WS error: %s, reconnecting in %ds...", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # ── Attachment download ───────────────────────────────────────────

    async def download_attachment(self, attachment_id: str, dest_dir: Path) -> Optional[Path]:
        """Download attachment via GET /v1/attachments/{id}.

        bbernhard stores attachments with correct file extensions already
        (derived from content-type). We stream the file bytes directly.
        """
        if not self.session or not self.connected:
            return None
        try:
            async with self.session.get(
                f"{self.http_url}/v1/attachments/{attachment_id}",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.error("Signal attachment %s: HTTP %s", attachment_id, resp.status)
                    return None
                raw = await resp.read()
                ct = resp.headers.get("Content-Type", "application/octet-stream")
                # Prefer extension from attachment_id (bbernhard names include ext)
                # but fall back to magic-byte detection.
                if "." in attachment_id:
                    ext = attachment_id.rsplit(".", 1)[-1]
                else:
                    ext = _detect_ext(raw, ct)
                dest_dir.mkdir(parents=True, exist_ok=True)
                safe_id = attachment_id.replace("/", "_").replace("..", "_")[:50]
                dest = dest_dir / f"signal_att_{safe_id}"
                if not str(dest).endswith(f".{ext}"):
                    dest = dest.with_suffix(f".{ext}")
                dest.write_bytes(raw)
                return dest
        except Exception as e:
            logger.error("Signal attachment download failed: %s", e)
            return None

    async def whoami(self) -> Optional[Dict]:
        """Check which accounts are registered."""
        if not self.session or not self.connected:
            return None
        try:
            async with self.session.get(
                f"{self.http_url}/v1/accounts",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    accounts = await resp.json()
                    return {"accounts": accounts, "account": self.account}
                return None
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
#  SignalChannel
# ══════════════════════════════════════════════════════════════════════

class SignalChannel(BaseChannel):
    """Signal channel: JSON-RPC + SSE via signal-cli daemon."""

    channel = "signal"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool = False,
        account: str = "",
        http_url: str = "",
        http_host: str = "127.0.0.1",
        http_port: int = 8080,
        auto_start: bool = False,
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
        text_chunk_limit: int = SIGNAL_MAX_TEXT_LENGTH,
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
        self._account = account
        self._send_read_receipts = send_read_receipts
        self._text_chunk_limit = text_chunk_limit
        self._ack_reaction_thinking = ack_reaction_thinking or ""
        self._ack_reaction_done = ack_reaction_done or ""
        self._ack_reaction_error = ack_reaction_error or ""
        self._groups: List[str] = kwargs.get("groups") or []
        self._group_allow_from: List[str] = kwargs.get("group_allow_from") or []
        self._account_uuid: str = kwargs.get("account_uuid") or ""
        self._media_dir = _MEDIA_DIR
        self._group_history: Dict[str, list] = {}  # group_id -> [{sender, body, ts}]
        self._group_history_limit = 50
        # Cache: sourceUuid/number → display name (learnt from envelope.sourceName)
        self._sender_names: Dict[str, str] = {}

        daemon_url = http_url or f"http://{http_host}:{http_port}"
        self.daemon = SignalDaemon(account=account, http_url=daemon_url)

        if self.enabled:
            logger.info("signal: initialized (account=%s, url=%s)", account, daemon_url)

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[SignalConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
        **kwargs,
    ) -> "SignalChannel":
        c = config if isinstance(config, dict) else (config.model_dump() if hasattr(config, "model_dump") else vars(config))
        return cls(
            process=process,
            enabled=bool(c.get("enabled", False)),
            account=c.get("account") or "",
            http_url=c.get("http_url") or "",
            http_host=c.get("http_host") or "127.0.0.1",
            http_port=c.get("http_port") or 8080,
            auto_start=c.get("auto_start", False),
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
            text_chunk_limit=c.get("text_chunk_limit", SIGNAL_MAX_TEXT_LENGTH),
            ack_reaction_thinking=c.get("ack_reaction_thinking", "🤔"),
            ack_reaction_done=c.get("ack_reaction_done", "👀"),
            ack_reaction_error=c.get("ack_reaction_error", "⚠️"),
            groups=c.get("groups") or [],
            group_allow_from=c.get("group_allow_from") or [],
            account_uuid=c.get("account_uuid") or c.get("accountUuid") or "",
        )

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self.enabled:
            return
        if not await self.daemon.connect():
            logger.error("signal: failed to connect to daemon")
            return
        await self.daemon.start_receive(self._on_sse_event)
        logger.info("signal: channel started (SSE receive active)")

    async def stop(self) -> None:
        if not self.enabled:
            return
        await self.daemon.disconnect()
        logger.info("signal: channel stopped")

    # ── Inbound SSE event handler ─────────────────────────────────────

    async def _on_sse_event(self, event: Dict) -> None:
        try:
            envelope = event.get("envelope", event)
            source = envelope.get("sourceNumber") or envelope.get("source") or ""
            source_uuid = envelope.get("sourceUuid") or ""
            source_name = envelope.get("sourceName") or ""
            timestamp = envelope.get("timestamp", 0)

            # Cache sender name for display + mention expansion
            if source_name:
                self._remember_sender(source, source_uuid, source_name)

            # Handle reactions
            reaction_msg = envelope.get("reactionMessage")
            if reaction_msg:
                await self._handle_inbound_reaction(source, source_uuid, reaction_msg, envelope)
                return

            data_message = envelope.get("dataMessage") or {}
            body = data_message.get("message") or ""

            # Cache any additional sender names referenced in mentions and
            # replace \ufffc placeholders with readable tokens.
            msg_mentions = data_message.get("mentions") or []
            for m in msg_mentions:
                self._remember_sender(
                    m.get("number") or "", m.get("uuid") or "", m.get("name") or "",
                )
            body = self._expand_mentions(body, msg_mentions)

            # Detect group
            group_info = data_message.get("groupInfo") or {}
            group_id = group_info.get("groupId") or ""

            # Need body or attachments to proceed
            attachments_raw = data_message.get("attachments") or []
            if attachments_raw:
                logger.info("signal: attachments found: %s", json.dumps(attachments_raw)[:500])
            if not body and not attachments_raw:
                return

            # ── Download attachments early (needed for history media paths) ──
            downloaded_media: List[Dict[str, str]] = []  # [{"path": ..., "type": ...}]
            for att in attachments_raw:
                att_id = att.get("id") or ""
                content_type = att.get("contentType") or ""
                if not att_id:
                    continue
                local = await self.daemon.download_attachment(att_id, self._media_dir)
                if local:
                    downloaded_media.append({"path": str(local), "type": content_type})

            # ── Access control ────────────────────────────────────────
            if group_id:
                if self.group_policy == "allowlist":
                    if not self._groups or group_id not in self._groups:
                        logger.debug("signal: blocked group %s (allowlist=%s)", group_id[:12], self._groups)
                        return
                # Enforce group_allow_from: restrict which senders can trigger in groups
                if self._group_allow_from:
                    sender_id = source or source_uuid
                    if not (
                        "*" in self._group_allow_from
                        or sender_id in self._group_allow_from
                        or source in self._group_allow_from
                        or source_uuid in self._group_allow_from
                        or f"uuid:{source_uuid}" in self._group_allow_from
                    ):
                        logger.debug("signal: blocked sender %s by group_allow_from", sender_id)
                        return
                if self.require_mention:
                    if not self._is_bot_mentioned(data_message, body):
                        # Record in group history buffer with media paths
                        if body or downloaded_media:
                            media_paths = [m["path"] for m in downloaded_media]
                            sender_label = self._format_sender_display(source, source_uuid)
                            history = self._group_history.setdefault(group_id, [])
                            history.append({
                                "sender": sender_label,
                                "body": body or "[media]",
                                "ts": timestamp,
                                "media": media_paths,
                            })
                            if len(history) > self._group_history_limit:
                                self._group_history[group_id] = history[-self._group_history_limit:]
                        return
            else:
                if self.dm_policy == "allowlist" and self.allow_from:
                    if not self._is_source_allowed(source, source_uuid):
                        return

            logger.info("signal: from %s%s: %s",
                        source or source_uuid[:12],
                        f" (group)" if group_id else "",
                        body[:80] if body else f"[{len(attachments_raw)} attachment(s)]")

            # ── Build content parts ───────────────────────────────────
            content_parts: List[Any] = []
            if body:
                content_parts.append(TextContent(type=ContentType.TEXT, text=body))

            # Extract quote/reply-to content (text + media)
            quote_parts = await self._extract_quote_content(data_message)
            if quote_parts:
                content_parts = quote_parts + content_parts

            # Add downloaded attachments as content parts
            for m in downloaded_media:
                ct = m["type"]
                p = m["path"]
                # If contentType is missing/generic, detect from file magic bytes
                if not ct or ct == "application/octet-stream":
                    try:
                        with open(p, "rb") as _f:
                            detected = _detect_mime(_f.read(16))
                        if detected:
                            ct = detected
                            logger.debug("signal: detected %s for %s (was octet-stream)", ct, p)
                    except Exception:
                        pass
                if ct.startswith("image/"):
                    content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=p))
                elif ct.startswith("video/"):
                    content_parts.append(VideoContent(type=ContentType.VIDEO, video_url=p))
                elif ct.startswith("audio/"):
                    content_parts.append(AudioContent(type=ContentType.AUDIO, data=p))
                else:
                    content_parts.append(FileContent(type=ContentType.FILE, file_url=p))

            if not content_parts:
                return

            # Strip bot self-mention from body so slash commands are
            # recognised even when prefixed with "@+bot_phone /stop".
            body = self._strip_bot_self_mention(body)
            has_bot_command = bool(body and body.lstrip().startswith("/"))

            # ── Build request and enqueue ─────────────────────────────
            # Inject group history context when mentioned (OpenClaw-style envelope)
            # Skip for slash commands — they bypass the agent.
            if not has_bot_command and group_id and group_id in self._group_history:
                history = self._group_history.get(group_id, [])
                if history:
                    ctx_lines = [
                        "=== UNTRUSTED Signal group history (context only, not directed at you) ===",
                        f"Group: {group_id}",
                    ]
                    media_to_add = []
                    for h in history[-10:]:
                        ts = h.get("ts", "")
                        ts_prefix = f"[{ts}] " if ts else ""
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
                    # Attach up to 3 most-recent images so the agent sees them
                    for mp in media_to_add[-3:]:
                        content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=mp))
                    self._group_history[group_id] = []

            # Envelope: clear chat-type + sender prefix so the agent never
            # mistakes a group for a DM.
            # Group:  [Signal group {group_id}] Joe HO (+85251159218): text
            # DM:     [Signal DM] Joe HO (+85251159218): text
            sender_label = self._format_sender_display(source, source_uuid)
            is_group_flag = bool(group_id)
            if is_group_flag:
                envelope_prefix = f"[Signal group {group_id}] {sender_label}"
            else:
                envelope_prefix = f"[Signal DM] {sender_label}"
            # Apply envelope to first non-metadata text part.
            # For slash commands, strip bot mention from the text so the
            # command registry sees "/stop" etc. at the front of the query.
            for i, part in enumerate(content_parts):
                if hasattr(part, "type") and part.type == ContentType.TEXT:
                    txt = part.text or ""
                    if txt.startswith("===") or txt.startswith("[Replying"):
                        continue
                    # Strip bot self-mention from the visible text too
                    txt = self._strip_bot_self_mention(txt)
                    if has_bot_command:
                        # Leave the command text raw so base's
                        # _extract_query_from_payload picks up "/stop"
                        # as the query. Envelope info is lost for the
                        # command turn — that's fine; commands bypass
                        # the agent anyway.
                        content_parts[i] = TextContent(
                            type=ContentType.TEXT, text=txt,
                        )
                    else:
                        content_parts[i] = TextContent(
                            type=ContentType.TEXT,
                            text=f"{envelope_prefix}: {txt}",
                        )
                    break
            else:
                # No text part existed — insert envelope-only text
                content_parts.insert(0, TextContent(
                    type=ContentType.TEXT,
                    text=f"{envelope_prefix}: [media]",
                ))

            # Trusted bot-identity hint (so the agent knows its own Signal
            # number and the mention syntax to tag other users in replies).
            # Only emit in groups — in DMs the user already knows they're
            # talking to the bot and mentions serve no purpose.
            # Skip for slash commands (they bypass the agent entirely).
            if is_group_flag and not has_bot_command:
                bot_id = self._account or (f"uuid:{self._account_uuid[:8]}" if self._account_uuid else "")
                hint_line = (
                    f"[Signal bot {bot_id}. "
                    f"To mention someone in a reply, write @+phone or @uuid:xxxxxxxx "
                    f"(e.g. @+85251159218 or @uuid:82e0393a).]"
                )
                content_parts.insert(0, TextContent(
                    type=ContentType.TEXT, text=hint_line,
                ))

            channel_meta = {
                "platform": "signal",
                "account": self._account,
                "timestamp": timestamp,
                "group_id": group_id,
                "source": source or source_uuid,
                "source_uuid": source_uuid,
                # For outbound quote-reply
                "quote_timestamp": timestamp,
                "quote_author": source or source_uuid,
                "has_bot_command": has_bot_command,
                "bot_mentioned": True,  # we only reach here past mention gate
            }
            session_id = self.resolve_session_id(source or source_uuid, channel_meta)
            # For groups: use group_id as sender_id so all members share one session
            effective_sender = f"group:{group_id}" if group_id else (source or source_uuid)
            request = self.build_agent_request_from_user_content(
                channel_id=self.channel,
                sender_id=effective_sender,
                session_id=session_id,
                content_parts=content_parts,
                channel_meta=channel_meta,
            )
            request.channel_meta = channel_meta
            # Store typing info in channel_meta for typing loop during response
            is_group = bool(group_id)
            typing_target = group_id if is_group else (source or source_uuid)
            channel_meta["_typing_target"] = typing_target
            channel_meta["_typing_is_group"] = is_group
            # Store reaction target for _stream_with_tracker to clear on done
            channel_meta["_ack_target"] = typing_target
            channel_meta["_ack_author"] = source or source_uuid
            channel_meta["_ack_timestamp"] = timestamp

            # Send thinking reaction (fire-and-forget)
            if self._ack_reaction_thinking:
                asyncio.create_task(self.daemon.send_reaction(
                    typing_target,
                    self._ack_reaction_thinking,
                    target_author=source or source_uuid,
                    target_timestamp=timestamp,
                    is_group=is_group,
                ))

            # Route through UnifiedQueueManager (via self._enqueue) so
            # each (signal, session_id, priority) gets its own queue
            # and worker task. Messages from different DMs/groups
            # process in parallel; same-session messages still
            # serialize (prevents races inside one conversation).
            #
            # NOTE: direct `await self.consume_one(request)` would
            # block the SSE receive loop until the agent's full
            # response finishes, which serializes ALL inbound traffic.
            # Fall back to direct call if no enqueue callback is
            # attached (unit tests set up channels without the manager).
            if self._enqueue is not None:
                self._enqueue(request)
            else:
                await self.consume_one(request)

        except Exception:
            logger.exception("signal: error processing SSE event")

    # ── Inbound reaction ──────────────────────────────────────────────

    async def _handle_inbound_reaction(
        self, source: str, source_uuid: str, reaction: Dict, envelope: Dict,
    ) -> None:
        emoji = reaction.get("emoji") or ""
        is_remove = reaction.get("isRemove", False)
        target_author = reaction.get("targetAuthor") or reaction.get("targetAuthorUuid") or ""
        target_ts = reaction.get("targetSentTimestamp") or 0
        group_info = reaction.get("groupInfo") or {}
        group_id = group_info.get("groupId") or ""

        logger.info("signal: reaction %s%s from %s on msg %d%s",
                     emoji, " (remove)" if is_remove else "",
                     source or source_uuid[:12], target_ts,
                     f" (group)" if group_id else "")

        # Ack reaction with same emoji (mirror) if reaction_level >= ack
        # For now just log it — extend later if needed

    # ── Access control helpers ────────────────────────────────────────

    def _is_bot_mentioned(self, data_message: Dict, body: str) -> bool:
        mentions = data_message.get("mentions") or []
        for m in mentions:
            if m.get("uuid") == self._account_uuid:
                return True
            if m.get("number") == self._account:
                return True
        # Quote-reply to bot counts as mention
        quote = data_message.get("quote")
        if quote:
            qa = quote.get("author") or quote.get("authorUuid") or ""
            if qa == self._account or qa == self._account_uuid:
                return True
        # Fallback: bot number in text
        if self._account and self._account in body:
            return True
        return False

    def _is_source_allowed(self, source: str, source_uuid: str) -> bool:
        for entry in self.allow_from:
            if entry.startswith("uuid:"):
                if source_uuid == entry[5:]:
                    return True
            elif entry.startswith("+"):
                if source == entry:
                    return True
            elif source == entry or source_uuid == entry:
                return True
        return False

    def _remember_sender(self, source: str, source_uuid: str, name: str) -> None:
        """Cache sourceName keyed by both phone and uuid.

        Signal sometimes sends the bare UUID as sourceName when the user
        hasn't set a profile name — skip those so callers don't end up
        with '@<full-uuid> (uuid:<short>)' tokens.
        """
        if not name or _looks_like_uuid(name):
            return
        if source:
            self._sender_names[source] = name
        if source_uuid:
            self._sender_names[source_uuid] = name

    def _strip_bot_self_mention(self, text: str) -> str:
        """Remove this bot's own @mention from outbound-addressed text.

        Users writing '@+85298349370 /stop' or '@uuid:447e962a /stop' should
        get '/stop' so the command registry picks it up. Handles:
          - @+85298349370 / @85298349370
          - @uuid:447e962a / @447e962a-1f09-...
          - @Name (+85298349370) / @Name (uuid:447e962a)   (round-trip form)
        """
        if not text:
            return text
        ids = []
        if self._account:
            ids.append(_re.escape(self._account.lstrip("+")))
        if self._account_uuid:
            ids.append(_re.escape(self._account_uuid))
            ids.append(_re.escape(self._account_uuid[:8]))
        if not ids:
            return text
        id_alt = "|".join(ids)
        id_core = rf"(?:\+?(?:{id_alt})|uuid:(?:{id_alt}))"
        # Try each form in sequence; stop at first match at head of string.
        patterns = [
            # @Name (+phone) / @Name (uuid:xxxxxxxx)
            _re.compile(rf"^\s*@[^\s()]+\s*\({id_core}\)\s*"),
            # @+phone / @uuid:xxx
            _re.compile(rf"^\s*@{id_core}\s*"),
        ]
        for pat in patterns:
            m = pat.match(text)
            if m:
                return text[m.end():].lstrip()
        return text

    def _format_sender_display(self, source: str, source_uuid: str) -> str:
        """Build a human-friendly sender label: 'Name (+phone)' / 'Name (uuid:xxx)' / fallback."""
        name = self._sender_names.get(source) or self._sender_names.get(source_uuid) or ""
        # Defensive: if the cache already holds a UUID-looking "name", drop it.
        if _looks_like_uuid(name):
            name = ""
        phone = source or ""
        if name and phone:
            return f"{name} ({phone})"
        if name and source_uuid:
            return f"{name} (uuid:{source_uuid[:8]})"
        if name:
            return name
        if phone:
            return phone
        if source_uuid:
            return f"uuid:{source_uuid[:8]}"
        return "unknown"

    @staticmethod
    def _compile_outbound_mentions(text: str) -> tuple:
        """Parse '@+phone' and '@uuid:xxxxxxxx' tokens in outbound text.

        Returns (cleaned_text, mentions) where cleaned_text has one U+FFFC
        per mention (as Signal expects) and mentions is the list bbernhard's
        /v2/send endpoint wants: [{start, length, author}].

        Recognised tokens (matched in order):
          @Name (+85251159218)        → author=+85251159218
          @Name (uuid:abc12345)       → author=abc12345…
          @+85251159218               → author=+85251159218
          @uuid:abc12345              → author=abc12345…

        Bare @Name without an id is ignored (Signal can't mention by name).
        """
        pat = _re.compile(
            r"@(?:[^@\s()]+\s*)?"
            r"(?:"
            r"\(\+(\d{7,15})\)"
            r"|\(uuid:([0-9a-f]{8}[0-9a-f-]*)\)"
            r"|\+(\d{7,15})"
            r"|uuid:([0-9a-f]{8}[0-9a-f-]*)"
            r")"
        )
        out = []
        mentions: List[Dict[str, Any]] = []
        cursor = 0
        for m in pat.finditer(text):
            # Everything before this token passes through unchanged
            out.append(text[cursor:m.start()])
            phone = m.group(1) or m.group(3) or ""
            uuid = m.group(2) or m.group(4) or ""
            author = f"+{phone}" if phone else uuid
            if author:
                mentions.append({
                    "start": sum(len(p) for p in out),
                    "length": 1,
                    "author": author,
                })
                out.append("\ufffc")
            else:
                out.append(m.group(0))
            cursor = m.end()
        out.append(text[cursor:])
        return "".join(out), mentions

    def _expand_mentions(self, body: str, mentions: List[Dict[str, Any]]) -> str:
        """Replace Signal's U+FFFC mention placeholders with readable references.

        Signal's bbernhard API sends the body with one U+FFFC codepoint per
        mention, plus a parallel list [{start, length, uuid, number, name}].
        We walk the sorted list and substitute each placeholder so the
        agent sees '@Joe' instead of '￼'.
        """
        if not body or not mentions:
            return body
        # Sort by start descending so replacement offsets stay valid
        sorted_mentions = sorted(mentions, key=lambda m: m.get("start", 0), reverse=True)
        result = body
        for m in sorted_mentions:
            start = m.get("start")
            length = m.get("length") or 1
            if start is None or start < 0 or start + length > len(result):
                continue
            name = m.get("name") or ""
            number = m.get("number") or ""
            uuid_v = m.get("uuid") or ""
            # Signal sends the raw UUID as "name" for users with no profile
            # name — treat that as no name at all.
            if _looks_like_uuid(name):
                name = ""
            # Fill name from cache when mention doesn't carry it
            if not name and number:
                name = self._sender_names.get(number, "")
            if not name and uuid_v:
                name = self._sender_names.get(uuid_v, "")
            if _looks_like_uuid(name):
                name = ""
            # Always show name + id. Prefer phone over uuid for the id.
            id_str = number if number else (f"uuid:{uuid_v[:8]}" if uuid_v else "")
            if name and id_str:
                token = f"@{name} ({id_str})"
            elif name:
                token = f"@{name}"
            elif id_str:
                token = f"@{id_str}"
            else:
                token = "@someone"
            result = result[:start] + token + result[start + length:]
        return result

    # ── Quote/reply-to extraction ──────────────────────────────────────

    async def _extract_quote_content(self, data_message: Dict) -> List[Any]:
        """Extract the content of a quoted/replied-to message.

        Returns a list of content parts (text + media) representing the
        original message being replied to, so the agent has full context
        of what the user is responding to — not just a message ID.
        """
        quote = data_message.get("quote")
        if not quote:
            return []

        parts: List[Any] = []
        quote_text = quote.get("text") or ""
        quote_author_number = quote.get("author") or ""
        quote_author_uuid = quote.get("authorUuid") or ""
        # If quote has its own mentions list, expand U+FFFC placeholders
        quote_mentions = quote.get("mentions") or []
        if quote_mentions:
            for m in quote_mentions:
                self._remember_sender(
                    m.get("number") or "", m.get("uuid") or "", m.get("name") or "",
                )
            quote_text = self._expand_mentions(quote_text, quote_mentions)
        quote_id = quote.get("id") or ""

        # Download quoted attachments (images, files, etc.)
        quote_attachments = quote.get("attachments") or []
        media_labels = []  # short type labels for the text block
        for att in quote_attachments:
            att_ct = att.get("contentType") or ""
            att_fname = att.get("fileName") or ""
            att_id = att.get("id") or ""
            if att_id:
                local = await self.daemon.download_attachment(att_id, self._media_dir)
                if local:
                    # Detect real type if contentType is missing/generic
                    if not att_ct or att_ct == "application/octet-stream":
                        try:
                            with open(str(local), "rb") as _qf:
                                detected = _detect_mime(_qf.read(16))
                            if detected:
                                att_ct = detected
                        except Exception:
                            pass
                    if att_ct.startswith("image/"):
                        parts.append(ImageContent(type=ContentType.IMAGE, image_url=str(local)))
                        media_labels.append("image")
                    elif att_ct.startswith("video/"):
                        parts.append(VideoContent(type=ContentType.VIDEO, video_url=str(local)))
                        media_labels.append("video")
                    elif att_ct.startswith("audio/"):
                        parts.append(AudioContent(type=ContentType.AUDIO, data=str(local)))
                        media_labels.append("audio")
                    else:
                        parts.append(FileContent(type=ContentType.FILE, file_url=str(local)))
                        media_labels.append(f"file: {att_fname}" if att_fname else "file")
                    continue
            # No downloadable attachment — describe it as text
            media_labels.append(att_fname or att_ct or "attachment")

        # Build OpenClaw-style bounded reply-to block (always emit header
        # when we have text OR attachments, so media ContentParts have context)
        if quote_text or media_labels:
            lines = ["=== UNTRUSTED reply-to (this message quotes an earlier one) ==="]
            author_str = self._format_sender_display(quote_author_number, quote_author_uuid)
            lines.append(f"From: {author_str}")
            if quote_id:
                lines.append(f"Quoted message id: {quote_id}")
            if quote_text:
                lines.append(f"Message: {quote_text[:400]}")
            if media_labels:
                lines.append(f"Media: {', '.join(media_labels)}")
            lines.append("=== end of reply-to ===")
            parts.insert(0, TextContent(type=ContentType.TEXT, text="\n".join(lines)))

        return parts

    # ── Outbound send ─────────────────────────────────────────────────

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        if not self.enabled or not self.daemon.connected:
            return
        if not text:
            return

        meta = meta or {}
        group_id = meta.get("group_id") or ""
        is_group = bool(group_id) or (to_handle.endswith("=") and not to_handle.startswith("+"))
        if is_group and group_id:
            to_handle = group_id

        # Extract [Image: ...] tags and convert to attachment paths.
        # Path is restricted to media_dir to prevent LLM exfiltration.
        img_re = __import__("re").compile(r'\[Image: (file:///[^\]]+|/[^\]]+)\]')
        safe_dir = str(self._media_dir.resolve())
        att_paths = []
        for m in img_re.findall(text):
            p = m.replace("file://", "") if m.startswith("file://") else m
            resolved = str(Path(p).resolve())
            if resolved.startswith(safe_dir) and os.path.isfile(resolved):
                att_paths.append(resolved)
                text = text.replace(f"[Image: {m}]", "").strip()
                logger.info("signal: extracted image attachment: %s", resolved)
            elif os.path.isfile(p):
                logger.warning("signal: blocked send of %s — outside media dir", p)
                text = text.replace(f"[Image: {m}]", "").strip()

        # bbernhard parses markdown natively with text_mode: styled.
        # Parse outbound @+phone / @uuid:xxx markers into bbernhard mention format
        # (U+FFFC placeholder + mentions array).
        text, mentions = self._compile_outbound_mentions(text)

        chunks = self._chunk_text(text) if text.strip() else [""]
        for i, chunk in enumerate(chunks):
            atts = att_paths if i == 0 and att_paths else None
            # Only attach mentions to chunks where ALL placeholders live.
            # For simplicity: if the message was chunked, send mentions only
            # on the first chunk that still contains U+FFFC placeholders.
            chunk_mentions = None
            if mentions and "\ufffc" in chunk:
                chunk_placeholder_positions = [
                    idx for idx, ch in enumerate(chunk) if ch == "\ufffc"
                ]
                # Map mentions onto this chunk (offsets are always aligned
                # when chunking is naive; if split would break this, skip).
                # Walk mentions and keep those whose (new) start falls in chunk.
                remapped = []
                # Rebuild offsets: count placeholders consumed by earlier chunks.
                consumed_before = sum(
                    1 for c in "".join(chunks[:i]) if c == "\ufffc"
                )
                mentions_in_chunk = mentions[
                    consumed_before:consumed_before + len(chunk_placeholder_positions)
                ]
                for pos, orig in zip(chunk_placeholder_positions, mentions_in_chunk):
                    remapped.append({
                        "start": pos, "length": 1, "author": orig["author"],
                    })
                chunk_mentions = remapped or None
            if chunk.strip() or atts:
                await self.daemon.send_message(
                    to_handle, chunk, is_group=is_group, attachments=atts,
                    mentions=chunk_mentions,
                )

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        """Send a single outbound media attachment (image / video / audio / file).

        This is the primary outbound media path for Signal. It is invoked
        by the base channel's ``send_content_parts`` for every non-text
        content block in the agent's reply — so when the agent returns
        an ``ImageBlock`` / ``AudioBlock`` / etc. (including via the
        ``send_file_to_user`` tool), the file ends up here.

        Extracts the local path from the content part (``image_url``,
        ``video_url``, ``file_url``/``file_id`` or ``data``), strips the
        ``file://`` scheme if present, and dispatches through
        ``SignalDaemon.send_message`` which base64-encodes the file
        inline for bbernhard's ``/v2/send`` endpoint.

        ✅ Images, audio, video AND documents all flow through here.
        """
        t = getattr(part, "type", None)
        logger.info(
            "signal: send_media called, type=%s to=%s", t, to_handle,
        )
        if not self.enabled or not self.daemon.connected:
            logger.warning(
                "signal: send_media skipped — channel=%s daemon=%s",
                self.enabled, self.daemon.connected,
            )
            return
        meta = meta or {}
        group_id = meta.get("group_id") or ""
        is_group = bool(group_id) or (to_handle.endswith("=") and not to_handle.startswith("+"))
        if is_group and group_id:
            to_handle = group_id

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
            logger.warning("signal: send_media missing path for type=%s", t)
            return
        file_path = (
            raw_path.replace("file://", "")
            if isinstance(raw_path, str) and raw_path.startswith("file://")
            else raw_path
        )
        exists = os.path.isfile(file_path) if file_path else False
        logger.info(
            "signal: send_media file_path=%s exists=%s", file_path, exists,
        )
        if not file_path or not exists:
            logger.warning("signal: media file not found: %s", file_path)
            return
        ts = await self.daemon.send_message(
            to_handle, "", is_group=is_group, attachments=[file_path],
        )
        if ts:
            logger.info(
                "signal: sent media to %s (timestamp=%s, size=%d bytes)",
                to_handle, ts, os.path.getsize(file_path),
            )
        else:
            logger.error(
                "signal: send_media FAILED to=%s path=%s", to_handle, file_path,
            )

    async def send_reaction_to(
        self,
        to_handle: str,
        emoji: str,
        target_author: str,
        target_timestamp: int,
        is_group: bool = False,
    ) -> bool:
        """Send outbound emoji reaction."""
        return await self.daemon.send_reaction(
            to_handle, emoji, target_author, target_timestamp, is_group=is_group,
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
            chunk = rest[: self._text_chunk_limit]
            last_nl = chunk.rfind("\n")
            if last_nl > self._text_chunk_limit // 2:
                chunk = rest[:last_nl]
            chunks.append(chunk)
            rest = rest[len(chunk):]
        return chunks

    # ── Typing indicator loop ──────────────────────────────────────────

    async def _typing_loop(self, target: str, is_group: bool, interval: float = 4.0):
        """Re-send typing indicator every `interval` seconds until cancelled.

        Signal typing indicators expire after ~5s.
        """
        try:
            while True:
                await self.daemon.send_typing(target, start=True, is_group=is_group)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            await self.daemon.send_typing(target, start=False, is_group=is_group)

    # ── Process loop override ─────────────────────────────────────────

    async def _stream_with_tracker(self, payload):
        """Override base to handle CoPaw event format for Signal."""
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
            typing_target = send_meta.get("_typing_target")
            typing_is_group = send_meta.get("_typing_is_group", False)
            if typing_target:
                typing_task = asyncio.create_task(
                    self._typing_loop(typing_target, typing_is_group)
                )

            process_iterator = self._process(request)
            async for event in process_iterator:
                # Yield SSE data for task tracker
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
                    logger.info("signal: message_completed, sending to %s", to_handle)
                    await self.on_event_message_completed(request, to_handle, event, send_meta)
                    message_completed = True

                # Fallback text collection (skips thinking when filter is on)
                for part in getattr(event, "content", []) or []:
                    txt = getattr(part, "text", None)
                    if not txt or txt in text_parts:
                        continue
                    if self._filter_thinking:
                        from agentscope_runtime.engine.schemas.agent_schemas import MessageType
                        if getattr(event, "type", None) == MessageType.REASONING:
                            continue
                        pt = str(getattr(part, "type", ""))
                        if "thinking" in pt.lower():
                            continue
                    text_parts.append(txt)

            # Fallback: send collected text if on_event_message_completed never fired
            logger.info("signal: stream done, message_completed=%s text_parts=%d to_handle=%s", message_completed, len(text_parts), to_handle)
            if text_parts and not message_completed:
                reply = chr(10).join(text_parts)
                logger.info("signal: fallback sending reply (%d chars) to %s", len(reply), to_handle)
                await self.send(to_handle, reply.strip(), send_meta)

            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)

            # Pick closing reaction:
            # - done  when agent produced a reply
            # - error when nothing was sent (silent crash / empty
            #   response) — otherwise the 🤔 would hang forever.
            produced_reply = message_completed or bool(text_parts)
            ack_emoji = (
                self._ack_reaction_done if produced_reply
                else self._ack_reaction_error
            )
            if ack_emoji:
                ack_target = send_meta.get("_ack_target")
                ack_author = send_meta.get("_ack_author")
                ack_ts = send_meta.get("_ack_timestamp")
                if ack_target and ack_author and ack_ts:
                    try:
                        await self.daemon.send_reaction(
                            ack_target,
                            ack_emoji,
                            target_author=ack_author,
                            target_timestamp=int(ack_ts),
                            is_group=bool(send_meta.get("_typing_is_group")),
                        )
                    except Exception as e:
                        logger.debug("signal: close reaction failed: %s", e)

        except asyncio.CancelledError:
            if process_iterator:
                await process_iterator.aclose()
            raise
        except Exception:
            logger.exception("signal: _stream_with_tracker failed")
            # Flip thinking → error so user sees the request died
            if self._ack_reaction_error:
                ack_target = send_meta.get("_ack_target")
                ack_author = send_meta.get("_ack_author")
                ack_ts = send_meta.get("_ack_timestamp")
                if ack_target and ack_author and ack_ts:
                    try:
                        await self.daemon.send_reaction(
                            ack_target,
                            self._ack_reaction_error,
                            target_author=ack_author,
                            target_timestamp=int(ack_ts),
                            is_group=bool(send_meta.get("_typing_is_group")),
                        )
                    except Exception:
                        pass
            raise
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()

    # ── Session / routing ─────────────────────────────────────────────

    def resolve_session_id(
        self, sender_id: str, channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = channel_meta or {}
        group_id = meta.get("group_id")
        if group_id:
            return f"signal:group:{group_id}"
        return f"signal:{sender_id}"

    def get_to_handle_from_request(self, request) -> str:
        meta = getattr(request, "channel_meta", None) or {}
        group_id = meta.get("group_id")
        if group_id:
            return group_id
        return meta.get("source") or getattr(request, "user_id", "") or ""
