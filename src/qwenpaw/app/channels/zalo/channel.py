# -*- coding: utf-8 -*-
# pylint: disable=too-many-instance-attributes,too-many-public-methods
"""Zalo Bot channel: long-polling getUpdates + REST send."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from qwenpaw.app.channels.base import (
    AudioContent,
    BaseChannel,
    ContentType,
    FileContent,
    ImageContent,
    OnReplySent,
    ProcessHandler,
    TextContent,
    VideoContent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables / defaults
# ---------------------------------------------------------------------------

ZALO_DEFAULT_API_BASE = "https://bot.zalo.me"
ZALO_DEFAULT_POLL_INTERVAL = 30.0
ZALO_DEFAULT_POLL_TIMEOUT = 25.0
ZALO_DEFAULT_MAX_RETRIES = 3
ZALO_DEFAULT_MAX_MESSAGE_LEN = 2000

# Outbound content markers an LLM may emit inside a text reply.
_IMAGE_TOKEN_RE = re.compile(
    r"\[IMAGE\s*:\s*(\S+?)\s*\]",
    flags=re.IGNORECASE,
)
_STICKER_TOKEN_RE = re.compile(
    r"\[STICKER\s*:\s*(\S+?)\s*\]",
    flags=re.IGNORECASE,
)
_VOICE_TOKEN_RE = re.compile(
    r"\[VOICE\s*:\s*(\S+?)\s*\]",
    flags=re.IGNORECASE,
)
_FILE_TOKEN_RE = re.compile(
    r"\[FILE\s*:\s*(/\S+?)\s*\]",
    flags=re.IGNORECASE,
)
_MARKDOWN_IMG_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(https?://\S+?)\s*\)",
    flags=re.IGNORECASE,
)
_URL_RE = re.compile(
    r"(https?://\S+?\.(?:png|jpg|jpeg|gif|webp|bmp)(?:\?[^\s)]*)?)",
    flags=re.IGNORECASE,
)
_THINK_BLOCK_RE = re.compile(
    r"\s*<think(?:ing)?\b[^>]*>.*?</think(?:ing)?\s*>",
    re.DOTALL | re.IGNORECASE,
)
_LEADING_NULL_RE = re.compile(
    r"^\s*(null|none|undefined|nil|nan)\s*\n\n",
    flags=re.IGNORECASE,
)
_NULL_TOKENS = frozenset(
    {"null", "none", "undefined", "nil", "nan", "n/a", "()"},
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OutboundAction:
    """A non-text action extracted from LLM text reply."""

    kind: str  # photo | sticker | voice | local_file
    payload: str
    position: int = 0  # source position in original text


# ---------------------------------------------------------------------------
# Channel class
# ---------------------------------------------------------------------------


class ZaloChannel(BaseChannel):
    """Zalo Bot channel driven by long-polling ``getUpdates``.

    Long-polling avoids the need for a public webhook URL — useful when
    QwenPaw runs behind NAT or on a developer laptop.
    """

    # Channel registry key — read by ``ChannelManager``.
    channel = "zalo"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_token: str,
        api_base_url: str = ZALO_DEFAULT_API_BASE,
        secret_token: str = "",
        show_typing: bool = True,
        poll_interval: float = ZALO_DEFAULT_POLL_INTERVAL,
        max_retries: int = ZALO_DEFAULT_MAX_RETRIES,
        max_message_len: int = ZALO_DEFAULT_MAX_MESSAGE_LEN,
        share_session_in_group: bool = True,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        streaming_enabled: bool = False,
        access_control_dm: bool = False,
        access_control_group: bool = False,
        workspace_dir: Optional[Path] = None,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
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
        self.bot_token = (bot_token or "").strip()
        self.api_base_url = (api_base_url or ZALO_DEFAULT_API_BASE).rstrip("/")
        self.secret_token = secret_token or ""
        self.show_typing = show_typing
        self.poll_interval = float(poll_interval)
        self.max_retries = int(max_retries)
        self.max_message_len = int(max_message_len)
        self.share_session_in_group = bool(share_session_in_group)
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )

        # Runtime state
        self._task: Optional[asyncio.Task] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._stopped = asyncio.Event()
        self._offset: Optional[int] = None
        # Latest update id per chat to avoid replays.
        self._last_update_ids: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, env: Any) -> "ZaloChannel":
        """Build a ZaloChannel from a runtime env/manager object.

        ``env`` is expected to expose ``process`` (ProcessHandler) and
        optionally ``on_reply_sent`` (OnReplySent).
        """
        process = env.process  # type: ignore[attr-defined]
        on_reply_sent = getattr(env, "on_reply_sent", None)
        return cls(
            process=process,
            enabled=True,
            bot_token=getattr(env, "zalo_bot_token", ""),
            api_base_url=getattr(
                env,
                "zalo_api_base_url",
                ZALO_DEFAULT_API_BASE,
            ),
            secret_token=getattr(env, "zalo_secret_token", ""),
            show_typing=getattr(env, "zalo_show_typing", True),
            poll_interval=getattr(
                env,
                "zalo_poll_interval",
                ZALO_DEFAULT_POLL_INTERVAL,
            ),
            max_retries=getattr(
                env,
                "zalo_max_retries",
                ZALO_DEFAULT_MAX_RETRIES,
            ),
            max_message_len=getattr(
                env,
                "zalo_max_message_len",
                ZALO_DEFAULT_MAX_MESSAGE_LEN,
            ),
            share_session_in_group=getattr(
                env,
                "zalo_share_session_in_group",
                True,
            ),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        cfg: Dict[str, Any],
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "ZaloChannel":
        """Build a ZaloChannel from a config section dict."""
        if not isinstance(cfg, dict):
            cfg = {}
        return cls(
            process=process,
            enabled=bool(cfg.get("enabled", True)),
            bot_token=str(cfg.get("bot_token", "")),
            api_base_url=str(
                cfg.get("api_base_url", ZALO_DEFAULT_API_BASE),
            ),
            secret_token=str(cfg.get("secret_token", "")),
            show_typing=bool(cfg.get("show_typing", True)),
            poll_interval=float(
                cfg.get("poll_interval", ZALO_DEFAULT_POLL_INTERVAL),
            ),
            max_retries=int(
                cfg.get("max_retries", ZALO_DEFAULT_MAX_RETRIES),
            ),
            max_message_len=int(
                cfg.get("max_message_len", ZALO_DEFAULT_MAX_MESSAGE_LEN),
            ),
            share_session_in_group=bool(
                cfg.get("share_session_in_group", True),
            ),
            on_reply_sent=on_reply_sent,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the long-polling worker."""
        if not self.enabled:
            logger.info("ZaloChannel disabled, skip start")
            return
        if not self.bot_token:
            logger.warning(
                "ZaloChannel: bot_token missing — channel will stay idle",
            )
            return
        if self._task and not self._task.done():
            return

        self._stopped.clear()
        self._http = httpx.AsyncClient(
            base_url=self.api_base_url,
            timeout=httpx.Timeout(ZALO_DEFAULT_POLL_TIMEOUT + 5.0),
            headers={"User-Agent": "QwenPaw-Zalo/1.0"},
        )
        self._task = asyncio.create_task(
            self._poll_loop(),
            name="zalo-poll",
        )
        logger.info("ZaloChannel started (api=%s)", self.api_base_url)

    async def stop(self) -> None:
        """Stop the long-polling worker."""
        self._stopped.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._http = None
        logger.info("ZaloChannel stopped")

    async def health_check(self) -> Dict[str, Any]:
        """Return basic channel health info for doctor checks."""
        ok = bool(self.bot_token) and self._http is not None
        return {
            "channel": self.channel,
            "enabled": self.enabled,
            "bot_token_set": bool(self.bot_token),
            "running": bool(self._task and not self._task.done()),
            "ok": ok,
        }

    # ------------------------------------------------------------------
    # Long-polling worker
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Long-poll `getUpdates` until ``stop`` is called."""
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                params: Dict[str, Any] = {
                    "timeout": int(ZALO_DEFAULT_POLL_TIMEOUT),
                }
                if self._offset is not None:
                    params["offset"] = self._offset
                resp = await self._http.get(  # type: ignore[union-attr]
                    f"/bot{self.bot_token}/getUpdates",
                    params=params,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "ZaloChannel poll: HTTP %s — backing off %.1fs",
                        resp.status_code,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                backoff = 1.0
                data = resp.json()
                if not isinstance(data, dict):
                    continue
                result = data.get("result") or []
                if isinstance(result, list):
                    for upd in result:
                        await self._handle_update(upd)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("ZaloChannel poll error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _handle_update(self, update: Dict[str, Any]) -> None:
        """Dispatch a single Telegram-style update payload."""
        if not isinstance(update, dict):
            return
        upd_id = update.get("update_id")
        if isinstance(upd_id, int):
            self._offset = upd_id + 1

        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "")
        sender_id = str(sender.get("id") or "")
        if not chat_id or not sender_id:
            return

        chat_type = str(chat.get("type") or "private").lower()
        is_group = chat_type in {"group", "supergroup", "channel"}
        from_name = (
            sender.get("username")
            or sender.get("first_name")
            or sender.get("last_name")
            or sender_id
        )

        text = message.get("text") or message.get("caption") or ""
        # Strip leading mention "@botname" in groups (Zalo uses same UX).
        if is_group:
            entities = message.get("entities") or []
            for ent in entities:
                if (
                    isinstance(ent, dict)
                    and ent.get("type") == "mention"
                    and isinstance(text, str)
                ):
                    offset = ent.get("offset")
                    length = ent.get("length")
                    if isinstance(offset, int) and isinstance(length, int):
                        text = text[:offset] + text[offset + length :]
                        break
        text = (text or "").lstrip()

        # Access control / mention gating.
        if (
            is_group
            and self.require_mention
            and not message.get(
                "mentioned_bot",
            )
        ):
            return

        session_id = self.resolve_session_id(
            sender_id,
            channel_meta={"chat_id": chat_id, "chat_type": chat_type},
        )

        native = self.build_agent_request_from_native(
            {
                "sender_id": sender_id,
                "from_name": str(from_name),
                "chat_id": chat_id,
                "chat_type": chat_type,
                "is_group": is_group,
                "text": text,
                "raw_message": message,
                "session_id": session_id,
                "update_id": upd_id,
            },
        )
        if native is None:
            return
        if self._enqueue is None:
            logger.debug("ZaloChannel enqueue not bound — drop update")
            return
        await self._enqueue(native, is_group=is_group)

    # ------------------------------------------------------------------
    # Session / addressing
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a stable session id for this update.

        - Private chat: ``zalo:<user_id>``
        - Group chat with sharing: ``zalo:group:<chat_id>``
        - Group without sharing: ``zalo:<user_id>:<chat_id>``
        """
        meta = channel_meta or {}
        chat_id = str(meta.get("chat_id") or "")
        chat_type = str(meta.get("chat_type") or "private").lower()
        is_group = chat_type in {"group", "supergroup", "channel"}
        if is_group and self.share_session_in_group and chat_id:
            return f"zalo:group:{chat_id}"
        if is_group:
            return (
                f"zalo:{sender_id}:{chat_id}"
                if chat_id
                else f"zalo:{sender_id}"
            )
        return f"zalo:{sender_id}"

    def to_handle_from_target(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> str:
        """Recover a to_handle from session id and user id (if known)."""
        if session_id.startswith("zalo:group:") and user_id == "":
            return f"zalo:group:{session_id.split(':')[-1]}"
        if user_id:
            return f"zalo:{user_id}"
        # Fallback: decode from session id when possible.
        parts = session_id.split(":")
        if len(parts) >= 2 and parts[0] == "zalo":
            tail = ":".join(parts[1:])
            return (
                f"zalo:group:{tail}" if "group" == parts[1] else f"zalo:{tail}"
            )
        return session_id

    def get_to_handle_from_request(self, request: Any) -> str:
        """Reconstruct the send-side handle from an AgentRequest."""
        chat_id = ""
        sender_id = ""
        meta = getattr(request, "meta", None) or {}
        if isinstance(meta, dict):
            chat_id = str(meta.get("chat_id") or "")
            sender_id = str(meta.get("sender_id") or "")
        session_id = getattr(request, "session_id", "") or ""
        if chat_id and meta.get("is_group"):
            return f"zalo:group:{chat_id}"
        if sender_id:
            return f"zalo:{sender_id}"
        return session_id

    def get_on_reply_sent_args(
        self,
        request: Any,
        to_handle: str,
    ) -> Dict[str, Any]:
        """Yield the kwargs ``on_reply_sent`` expects after send completes."""
        meta = getattr(request, "meta", None) or {}
        is_group = bool(meta.get("is_group"))
        return {"is_group": is_group}

    # ------------------------------------------------------------------
    # AgentRequest shaping
    # ------------------------------------------------------------------

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Optional[Any]:
        """Build an AgentRequest (or queue envelope) from a native update."""
        if not isinstance(native_payload, dict):
            return None
        text = native_payload.get("text") or ""
        if not text:
            return None
        is_group = bool(native_payload.get("is_group"))
        from_name = str(native_payload.get("from_name") or "")
        chat_id = str(native_payload.get("chat_id") or "")
        if is_group and from_name:
            # Tag the line so the LLM knows who said what.
            text = f"[{from_name} trong nhóm {chat_id}]: {text}"

        content_parts: List[Any] = []
        content_parts.append(TextContent(text=text))

        from qwenpaw.schemas import AgentRequest  # late import

        return AgentRequest(
            session_id=str(native_payload.get("session_id") or ""),
            content_parts=content_parts,
            meta={
                "channel": self.channel,
                "sender_id": str(native_payload.get("sender_id") or ""),
                "from_name": from_name,
                "chat_id": chat_id,
                "chat_type": str(native_payload.get("chat_type") or "private"),
                "is_group": is_group,
                "update_id": native_payload.get("update_id"),
            },
            raw=native_payload.get("raw_message"),
        )

    def build_agent_request_from_user_content(
        self,
        content_parts: List[Any],
        session_id: str,
    ) -> Tuple[str, List[Any], Dict[str, Any]]:
        """Render content parts into the LLM-visible prompt text.

        Mirrors the protocol used by other built-in channels so the same
        agent core can consume them. We collapse ``content_parts`` to
        plain text here (image/file content is enumerated by kind).
        """
        text_chunks: List[str] = []
        for part in content_parts or []:
            if isinstance(part, TextContent):
                text_chunks.append(part.text or "")
            elif isinstance(part, ImageContent):
                text_chunks.append(
                    f"[image url={getattr(part, 'url', '')}]",
                )
            elif isinstance(part, AudioContent):
                text_chunks.append(
                    f"[audio url={getattr(part, 'url', '')}]",
                )
            elif isinstance(part, VideoContent):
                text_chunks.append(
                    f"[video url={getattr(part, 'url', '')}]",
                )
            elif isinstance(part, FileContent):
                file_url = getattr(part, "url", "") or getattr(
                    part,
                    "path",
                    "",
                )
                text_chunks.append(f"[file url={file_url}]")
            else:
                ctype = getattr(part, "type", None) or ContentType.TEXT
                payload = getattr(part, "payload", None) or getattr(
                    part,
                    "text",
                    None,
                )
                text_chunks.append(f"[{ctype}] {payload}")
        return ("\n".join(text_chunks).strip(), content_parts, {})

    # ------------------------------------------------------------------
    # Send path
    # ------------------------------------------------------------------

    async def send(
        self,
        to_handle: str,
        content_parts: List[Any],
    ) -> None:
        """Dispatch the agent's reply for a session.

        ``to_handle`` is either ``zalo:<user_id>`` (private) or
        ``zalo:group:<chat_id>`` (group). Text parts are routed through
        ``_dispatch_text_actions`` to preserve image / sticker / voice /
        file markers emitted by the LLM.
        """
        if not content_parts:
            return
        if self._http is None:
            logger.warning("ZaloChannel: send ignored — http client not ready")
            return

        real_chat_id = self._handle_to_chat_id(to_handle)
        is_group = to_handle.startswith("zalo:group:")
        primary_text = "\n".join(
            part.text
            for part in content_parts
            if isinstance(part, TextContent)
        ).strip()

        if not primary_text:
            # No text — try media parts only.
            for part in content_parts:
                if isinstance(part, ImageContent):
                    url = getattr(part, "url", "") or ""
                    if url:
                        await self._send_photo(real_chat_id, url)
                elif isinstance(part, AudioContent):
                    url = getattr(part, "url", "") or ""
                    if url:
                        await self._send_voice(real_chat_id, url)
            return

        await self._dispatch_text_actions(
            real_chat_id,
            primary_text,
            is_group=is_group,
        )

    @staticmethod
    def _handle_to_chat_id(to_handle: str) -> str:
        """Translate ``zalo:group:<id>`` / ``zalo:<id>`` → raw chat id."""
        if to_handle.startswith("zalo:group:"):
            return to_handle[len("zalo:group:") :]
        if to_handle.startswith("zalo:"):
            return to_handle[len("zalo:") :]
        return to_handle

    # ------------------------------------------------------------------
    # Outbound dispatcher (text + media extraction)
    # ------------------------------------------------------------------

    async def _dispatch_text_actions(
        self,
        real_chat_id: str,
        text: str,
        is_group: bool,
    ) -> None:
        """Send a text reply, extracting any embedded actions on the way."""
        actions, leftover = self._extract_actions(text)
        leftover = self._strip_thinking(leftover)
        leftover = self._strip_null_tokens(leftover)
        leftover = leftover.strip()

        if leftover:
            await self._safe_send_message(real_chat_id, leftover)
            try:
                if self._on_reply_sent is not None:
                    self._on_reply_sent(
                        chat_id=real_chat_id,
                        is_group=is_group,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("on_reply_sent failed: %s", exc)

        for action in actions:
            if action.kind == "photo":
                await self._send_photo(real_chat_id, action.payload)
            elif action.kind == "sticker":
                await self._send_sticker(real_chat_id, action.payload)
            elif action.kind == "voice":
                await self._send_voice(real_chat_id, action.payload)
            elif action.kind == "local_file":
                await self._dispatch_local_file(real_chat_id, action.payload)
            try:
                if self._on_reply_sent is not None:
                    self._on_reply_sent(
                        chat_id=real_chat_id,
                        is_group=is_group,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("on_reply_sent failed: %s", exc)

    @staticmethod
    def _extract_actions(text: str) -> Tuple[List[OutboundAction], str]:
        """Pull magic tokens + bare image URLs out of a text reply."""
        if not text:
            return [], ""
        actions: List[OutboundAction] = []
        leftover = text

        # [FILE: /abs/path] (must come before other tokens because / is
        # optional in the others but required here).
        for m in _FILE_TOKEN_RE.finditer(leftover):
            actions.append(
                OutboundAction("local_file", m.group(1), m.start()),
            )
        leftover = _FILE_TOKEN_RE.sub("", leftover)

        # [STICKER: id]
        for m in _STICKER_TOKEN_RE.finditer(leftover):
            actions.append(
                OutboundAction("sticker", m.group(1), m.start()),
            )
        leftover = _STICKER_TOKEN_RE.sub("", leftover)

        # [VOICE: url]
        for m in _VOICE_TOKEN_RE.finditer(leftover):
            actions.append(
                OutboundAction("voice", m.group(1), m.start()),
            )
        leftover = _VOICE_TOKEN_RE.sub("", leftover)

        # [IMAGE: url]
        for m in _IMAGE_TOKEN_RE.finditer(leftover):
            actions.append(
                OutboundAction("photo", m.group(1), m.start()),
            )
        leftover = _IMAGE_TOKEN_RE.sub("", leftover)

        # ![caption](url)
        for m in _MARKDOWN_IMG_RE.finditer(leftover):
            actions.append(
                OutboundAction("photo", m.group(1), m.start()),
            )
        leftover = _MARKDOWN_IMG_RE.sub("", leftover)

        # Bare image URLs ending in png/jpg/jpeg/gif/webp/bmp.
        for m in _URL_RE.finditer(leftover):
            actions.append(
                OutboundAction("photo", m.group(1), m.start()),
            )
        leftover = _URL_RE.sub("", leftover)

        # Collapse runs of blank lines.
        leftover = re.sub(r"[ \t]+", " ", leftover)
        leftover = re.sub(r"\n{3,}", "\n\n", leftover)
        return actions, leftover.strip()

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove ``<think…>…</think>`` blocks and lone label lines."""
        if not text:
            return text
        text = _THINK_BLOCK_RE.sub("\n", text)
        cleaned = []
        for line in text.splitlines():
            stripped = line.strip()
            low = stripped.lower()
            if low.startswith("think") or low.startswith("reasoning"):
                # Drop "Thinking:" / "Reasoning:" labels.
                continue
            cleaned.append(line)
        text = "\n".join(cleaned)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _strip_null_tokens(text: str) -> str:
        """Drop leading ``null`` leaks and placeholder-only lines."""
        if not text:
            return text
        kept = [
            line
            for line in text.splitlines()
            if line.strip().lower() not in _NULL_TOKENS
        ]
        text = "\n".join(kept).strip()
        text = _LEADING_NULL_RE.sub("", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Low-level HTTP helpers
    # ------------------------------------------------------------------

    async def _safe_send_message(self, chat_id: str, text: str) -> None:
        """Send a text message, splitting if over ``max_message_len``."""
        chunks = self._split_text(text, self.max_message_len)
        for chunk in chunks:
            try:
                await self._api_post(
                    "sendMessage",
                    {"chat_id": chat_id, "text": chunk},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ZaloChannel sendMessage failed (chat=%s): %s",
                    chat_id,
                    exc,
                )

    async def _send_photo(self, chat_id: str, url: str) -> None:
        try:
            await self._api_post(
                "sendPhoto",
                {"chat_id": chat_id, "photo": url},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ZaloChannel sendPhoto failed (chat=%s): %s",
                chat_id,
                exc,
            )

    async def _send_sticker(self, chat_id: str, sticker_id: str) -> None:
        try:
            await self._api_post(
                "sendSticker",
                {"chat_id": chat_id, "sticker": sticker_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ZaloChannel sendSticker failed (chat=%s): %s",
                chat_id,
                exc,
            )

    async def _send_voice(self, chat_id: str, voice_url: str) -> None:
        try:
            await self._api_post(
                "sendVoice",
                {"chat_id": chat_id, "voice": voice_url},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ZaloChannel sendVoice failed (chat=%s): %s",
                chat_id,
                exc,
            )

    async def _dispatch_local_file(
        self,
        chat_id: str,
        path_str: str,
    ) -> None:
        """Send a textual fallback noting a local file reference.

        Zalo Bot API does not currently expose a raw file upload without
        a public URL, so we surface file metadata so the user knows the
        bot referenced a local file.
        """
        try:
            path = Path(path_str).expanduser().resolve()
        except Exception:  # noqa: BLE001
            await self._safe_send_message(
                chat_id,
                f"❌ Cannot resolve path: {path_str}",
            )
            return
        if not path.exists():
            await self._safe_send_message(
                chat_id,
                f"❌ File not found: {path}",
            )
            return
        size_kb = path.stat().st_size / 1024.0
        await self._safe_send_message(
            chat_id,
            f"📎 File: {path.name} ({size_kb:.1f} KB)\n📍 {path}",
        )

    async def _api_post(
        self,
        method: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """POST to Zalo Bot API with retries. Returns the parsed JSON dict."""
        if self._http is None:
            raise RuntimeError("ZaloChannel HTTP client not initialized")
        url = f"/bot{self.bot_token}/{method}"
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = await self._http.post(url, json=payload)
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"{resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                if resp.status_code != 200:
                    return {
                        "ok": False,
                        "status": resp.status_code,
                        "body": resp.text[:500],
                    }
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return {"ok": False, "body": resp.text[:500]}
            except (httpx.RequestError, asyncio.TimeoutError) as exc:
                last_exc = exc
                await asyncio.sleep(0.5 * (2**attempt))
        if last_exc is not None:
            raise last_exc
        return {"ok": False, "status": 0, "body": "exhausted retries"}

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @staticmethod
    def _split_text(text: str, max_len: int) -> List[str]:
        """Greedy split on whitespace, falling back to hard slice."""
        if max_len <= 0 or len(text) <= max_len:
            return [text]
        chunks: List[str] = []
        rest = text
        while len(rest) > max_len:
            window = rest[:max_len]
            cut = window.rfind(" ")
            if cut <= 0:
                cut = max_len
            chunks.append(rest[:cut].rstrip())
            rest = rest[cut:].lstrip()
        if rest:
            chunks.append(rest)
        return chunks
