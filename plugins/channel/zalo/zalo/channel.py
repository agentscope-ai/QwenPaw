# -*- coding: utf-8 -*-
"""Zalo Bot Channel for QwenPaw.

Custom channel that connects QwenPaw to Zalo via the Zalo Bot Platform.

Receive mode: polling only - long-polls Zalo's ``getUpdates`` in a
background task. Requires only a bot token; no public URL / HTTPS / domain
needed. Ideal for a personal bot on a single instance.

Routes inbound messages to the agent and sends replies via the Zalo Bot API.

Auto-loaded by QwenPaw from ~/.qwenpaw/custom_channels/zalo/.
"""

from __future__ import annotations

import asyncio
import re
import logging
import secrets
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from .client import ZaloClient, ZaloAPIError

from qwenpaw.app.channels.base import (
    BaseChannel,
    ProcessHandler,
    OnReplySent,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Smart text routing for outbound messages
# ----------------------------------------------------------------------
# When the LLM only emits plain TextContent (the common case), we still
# want to give it the ability to send image / sticker / voice.  We do
# that by scanning the text for URL / magic tokens:
#
#   Markdown image:    ![alt](https://example.com/pic.png)
#   Bare image URL:    https://example.com/pic.jpg
#   Magic tokens:      [IMAGE: url]   [STICKER: id]   [VOICE: url]
#
# Anything that matches gets pulled out of the text and routed to the
# right Zalo API.  The remaining text is sent via send_message.

# ----------------------------------------------------------------------
# Smart text routing / dispatch / thinking helpers (factored out)
# ----------------------------------------------------------------------
#
# The following helper modules now live alongside this file:
#
#   routing.py    - Action dataclass, URL & magic-token extraction
#   thinking.py   - strip <think> blocks and null-ish leak tokens
#   dispatch.py   - outbound helpers (local file, text+actions)
#
# They are imported once below. Helpers that used to be private methods
# of this module are still re-exported so any external consumer that
# imported them from `custom_channels.zalo.channel` keeps working.

from .routing import (  # noqa: E402
    Action as Action,                         # re-export
    _extract_actions as _extract_actions,     # internal but re-exported
)
from .thinking import (  # noqa: E402
    _strip_thinking as _strip_thinking,
    _strip_null_tokens as _strip_null_tokens,
)
from .dispatch import (  # noqa: E402
    _dispatch_local_file as _dispatch_local_file,
    _dispatch_text_actions as _dispatch_text_actions,
)
# Common channel defaults
# ----------------------------------------------------------------------

DEFAULT_ACCESS_CONTROL = dict(
    dm_policy="open",
    group_policy="open",
    allow_from=None,
    deny_message="",
    require_mention=False,
)


# ----------------------------------------------------------------------
# ZaloChannel
# ----------------------------------------------------------------------

class ZaloChannel(BaseChannel):  # type: ignore[misc]
    """Zalo Bot channel — polling only."""

    channel = "zalo"
    uses_manager_queue = True

    # ------------------------------------------------------------------
    # Construction / config
    # ------------------------------------------------------------------

    def __init__(
        self,
        process: Any,
        *,
        bot_token: str = "",
        secret_token: str = "",
        poll_interval: int = 30,
        max_retries: int = 3,
        max_message_len: int = 2000,
        on_reply_sent: Any = None,
        api_base_url: str = "",
        **kwargs,
    ):
        super().__init__(process, **kwargs)
        self._bot_token = bot_token
        self._secret_token = secret_token or self._generate_secret()
        self._poll_interval = max(1, poll_interval)
        self._max_retries = max(1, max_retries)
        self._max_message_len = max(1, max_message_len)
        self._on_reply_sent = on_reply_sent
        self._client: Optional[ZaloClient] = None
        self._client_factory = None  # injectable for tests
        self._started = False
        self._poll_task: Optional[asyncio.Task] = None
        self._seen_ids: set = set()
        self._api_base_url = api_base_url
        self._offset: int = 0
        # --- Typing indicator state ----------------------------------
        # ``show_typing`` can be passed in via kwargs (e.g. ``show_typing``)
        # and falls back to True so users see feedback by default.
        self._show_typing = bool(kwargs.get("show_typing", True))
        self._typing_tasks: Dict[str, asyncio.Task] = {}
        self._is_processing: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # from_config (required by ChannelManager)
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir=None,
    ) -> "ZaloChannel":
        """Create a ZaloChannel from a config dict."""
        if isinstance(config, dict):
            c = config
        else:
            # Manager may pass a SimpleNamespace — convert to dict
            c = vars(config) if hasattr(config, "__dict__") else {}

        # Build kwargs that our __init__ actually accepts.
        # 'enabled' is stored on the instance, not passed to BaseChannel.
        inst = cls(
            process=process,
            bot_token=(c.get("bot_token") or "").strip(),
            secret_token=(c.get("secret_token") or "").strip(),
            api_base_url=(c.get("api_base_url") or "").strip(),
            poll_interval=int(c.get("poll_interval", 30)),
            max_retries=int(c.get("max_retries", 3)),
            max_message_len=int(c.get("max_message_len", 2000)),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=c.get("dm_policy") or "open",
            group_policy=c.get("group_policy") or "open",
            allow_from=c.get("allow_from") or [],
            deny_message=c.get("deny_message") or "",
            require_mention=c.get("require_mention", False),
            access_control_dm=bool(c.get("access_control_dm", False)),
            access_control_group=bool(c.get("access_control_group", False)),
        )
        inst._enabled = bool(c.get("enabled", False))
        inst._bot_prefix = (c.get("bot_prefix") or "").strip()
        return inst


    # ------------------------------------------------------------------
    # Secret token
    # ------------------------------------------------------------------

    def _generate_secret(self) -> str:
        """Generate a cryptographically random secret token (≥8 chars)."""
        return secrets.token_hex(16)

    def _secret_path(self) -> Path:
        return Path.home() / ".qwenpaw" / "zalo_secret_token"

    def _load_secret(self) -> str:
        p = self._secret_path()
        if p.exists():
            return p.read_text().strip()
        token = self._generate_secret()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(token)
        p.chmod(0o600)
        return token

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        global _active_channel
        _active_channel = self

        if self._client_factory:
            self._client = self._client_factory(self._bot_token)
        else:
            self._client = ZaloClient(self._bot_token, base_url=self._api_base_url or None)

        await self._client.start()

        # Verify bot token
        me = await self._client.get_me()
        result = me.get("result", me)
        bot_id = result.get("id", "?")
        bot_name = result.get("display_name") or result.get("name", "?")
        print(f"[zalo] bot connected: id={bot_id} name={bot_name}", flush=True)

        # Start polling loop
        self._poll_task = asyncio.create_task(self._poll_loop())
        print(f"[zalo] polling started (interval={self._poll_interval}s)", flush=True)

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._client:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(  # type: ignore[override]
        self,
        chat_id: str,
        content: Any,
        meta: Optional[Dict[str, Any]] = None,
        *,
        parse_mode: Optional[str] = None,
    ) -> None:
        if self._client is None:
            raise RuntimeError("channel not started")

        meta_dict = meta or {}
        # Ưu tiên meta.chat_id (raw Zalo id). Fallback: strip prefix session.
        # 'zalo:group:{id}' → '{id}'; 'zalo:{id}' → '{id}' (backward-compat).
        real_chat_id = meta_dict.get("chat_id")
        if not real_chat_id:
            if chat_id.startswith("zalo:group:"):
                real_chat_id = chat_id[len("zalo:group:"):]
            elif chat_id.startswith("zalo:"):
                real_chat_id = chat_id[len("zalo:"):]
            else:
                real_chat_id = chat_id
        # Reply session phải khớp resolve_session_id (GROUP vs PRIVATE).
        is_group = meta_dict.get("chat_type") == "GROUP"

        # Always stop typing first - we are about to actually reply.
        try:
            self._stop_typing(real_chat_id)
        except Exception:
            logger.debug("zalo: _stop_typing failed (non-fatal)")
        self._is_processing[real_chat_id] = False

        from agentscope_runtime.engine.schemas.agent_schemas import (  # noqa: WPS433
            TextContent,
            ImageContent,
        )

        blocks: List[Any] = list(content) if isinstance(content, list) else [content]
        text_parts: List[str] = []
        _rich_sent: bool = False

        for block in blocks:
            if isinstance(block, str):
                if block.strip():
                    text_parts.append(block)
                continue
            if isinstance(block, TextContent):
                if block.text and block.text.strip():
                    text_parts.append(block.text)
                continue
            # Duck-typing fallback for test doubles / mocks
            if hasattr(block, "text") and not isinstance(block, ImageContent):
                txt = getattr(block, "text", None)
                if txt and str(txt).strip():
                    text_parts.append(str(txt))
                continue
            if isinstance(block, ImageContent):
                url = block.image_url or getattr(block, "url", None)
                if url:
                    try:
                        await self._client.send_photo(
                            chat_id=real_chat_id,
                            photo=url,
                            caption="\n".join(text_parts) or None,
                        )
                        text_parts = []
                        _rich_sent = True
                        self._safe_on_reply(real_chat_id, is_group=is_group)
                    except Exception:
                        logger.exception(
                            "Zalo send_photo failed chat_id=%s url=%s",
                            real_chat_id, url,
                        )
                continue
            # Sticker / voice content blocks
            sticker_id = getattr(block, "sticker_id", None) or getattr(block, "sticker", None)
            if sticker_id and isinstance(sticker_id, str):
                try:
                    await self._client.send_sticker(
                        chat_id=real_chat_id,
                        sticker=sticker_id,
                    )
                    _rich_sent = True
                    self._safe_on_reply(real_chat_id, is_group=is_group)
                except Exception:
                    logger.exception("Zalo send_sticker failed")
                continue
            voice_url = getattr(block, "voice_url", None) or getattr(block, "voice", None)
            if voice_url and isinstance(voice_url, str):
                try:
                    await self._client.send_voice(
                        chat_id=real_chat_id,
                        voice_url=voice_url,
                    )
                    _rich_sent = True
                    self._safe_on_reply(real_chat_id, is_group=is_group)
                except Exception:
                    logger.exception("Zalo send_voice failed")
                continue
            # Unknown content type → string fallback
            text_parts.append(str(block) if block is not None else "")

        text = "\n".join(p for p in text_parts if p).strip()

        # Strip thinking blocks (-style), lone "thinking"/"<think>" lines,
        # and placeholders from some LLM providers.
        text = _strip_thinking(text)
        text = _strip_null_tokens(text)

        if not text:
            # Agent returned nothing useful (only thinking/null tokens).
            # Per product decision, drop silently rather than sending a
            # placeholder — keeps the chat clean for the user.
            print(
                f"[zalo] drop silent: empty after filter (chat_id={real_chat_id})",
                flush=True,
            )
            return

        await _dispatch_text_actions(self, real_chat_id, text, is_group=is_group)

    def _safe_on_reply(self, real_chat_id: str, *, is_group: bool = False) -> None:
        """Fire ``_on_reply_sent`` callback without crashing the send loop.

        Session id phải khớp ``resolve_session_id``: GROUP → 'zalo:group:{id}',
        PRIVATE → 'zalo:{id}' (backward-compat).
        """
        if not self._on_reply_sent:
            return
        try:
            session = (
                f"zalo:group:{real_chat_id}" if is_group
                else f"zalo:{real_chat_id}"
            )
            self._on_reply_sent("zalo", real_chat_id, session)
        except Exception:
            logger.exception("on_reply_sent callback failed")

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        # GROUP: 1 session chung cho cả nhóm → 'zalo:group:{chat_id}'.
        # PRIVATE: giữ 'zalo:{sender_id}' (backward-compat session cũ).
        meta = channel_meta or {}
        if meta.get("chat_type") == "GROUP" and meta.get("chat_id"):
            return f"zalo:group:{meta.get('chat_id')}"
        return f"zalo:{sender_id}"

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Any:
        """Convert Zalo native payload to AgentRequest.

        Mirrors the Telegram channel override: pull fields out of the
        native dict, delegate to
        ``build_agent_request_from_user_content`` for the heavy lifting,
        then attach ``channel_meta`` so the reply path can route back.
        """
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        # GROUP: prepend prefix '[tên trong nhóm chat_id]: ' để LLM phân biệt
        # người gửi trong group. PRIVATE: giữ nguyên content (không đổi session cũ).
        if meta.get("chat_type") == "GROUP" and meta.get("chat_id"):
            from agentscope_runtime.engine.schemas.agent_schemas import (  # noqa: WPS433
                TextContent,
            )
            prefix = f"[{meta.get('from_name', '')} trong nhóm {meta.get('chat_id')}]: "
            content_parts = [TextContent(text=prefix)] + list(content_parts)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        # Attach channel_meta so SendChannel can pull chat_id/message_id
        # (and any future per-message metadata) when routing replies.
        try:
            request.channel_meta = dict(meta)
        except Exception:
            pass
        return request

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Background task: long-poll Zalo for new messages.

        Zalo API returns ``result`` as a single dict (one update),
        not a list like Telegram.  We normalise to a list.
        Zalo auto-acknowledges fetched updates — no offset needed.
        """
        while self._started and self._client is not None:
            try:
                updates = await self._client.get_updates(
                    offset=self._offset,
                    timeout=self._poll_interval,
                )
                if not updates.get("ok"):
                    continue
                result = updates.get("result")
                if result is None:
                    continue
                # Normalise: Zalo returns single dict, wrap in list
                if isinstance(result, dict):
                    events = [result]
                elif isinstance(result, list):
                    events = result
                else:
                    events = []
                for event in events:
                    self._dispatch_native_event(event)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Zalo poll error — retrying in %ds", self._poll_interval)
                await asyncio.sleep(self._poll_interval)

    def _dispatch_native_event(self, event: Dict[str, Any]) -> None:
        """Route a Zalo-native event into the manager queue."""
        import json as _json; logger.debug("[zalo] RAW_EVENT: %s", _json.dumps(event, ensure_ascii=False))
        message = event.get("message") or {}
        msg_id = message.get("message_id") or event.get("update_id") or ""
        if msg_id and msg_id in self._seen_ids:
            return
        if msg_id:
            self._seen_ids.add(msg_id)
        # Keep set bounded
        if len(self._seen_ids) > 10000:
            self._seen_ids = set(sorted(self._seen_ids)[-5000:])

        message = event.get("message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        msg_id = message.get("message_id", "")
        event_name = event.get("event_name", "") or ""

        # Text payload (Zalo uses different field names depending on event type)
        text = (
            message.get("text")
            or message.get("caption")   # images / attachments
            or ""
        )

        # Image / photo URL (singular HTTPS string per Zalo Bot API)
        photo_url = (
            message.get("photo_url")
            or message.get("image_url")
            or message.get("thumb_url")
        )
        # Some events carry a photo array of dicts (legacy / Telegram-style)
        photos = message.get("photo", [])
        if isinstance(photos, str):       # tolerate single string
            photo_url = photos
            photos = []

        # Extract content blocks
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ImageContent,
        )

        contents: List[Any] = []

        if text and text.strip():
            contents.append(TextContent(text=text))

        # ---- Photos / Images -----------------------------------------
        if isinstance(photo_url, str) and photo_url.strip():
            contents.append(ImageContent(image_url=photo_url.strip()))
        else:
            for photo in photos:
                if isinstance(photo, dict):
                    url = photo.get("file_id") or photo.get("url") or ""
                    if url:
                        contents.append(ImageContent(image_url=url))
                elif isinstance(photo, str) and photo.strip():
                    contents.append(ImageContent(image_url=photo.strip()))

        # ---- Sticker ------------------------------------------------
        sticker = message.get("sticker")
        sticker_id = (
            (sticker.get("file_id") if isinstance(sticker, dict) else None)
            or message.get("sticker_id")
            or message.get("sticker")
        )
        if sticker_id and isinstance(sticker_id, str) and sticker_id.strip():
            contents.append(TextContent(text=f"[sticker: {sticker_id.strip()}]"))

        # ---- Voice --------------------------------------------------
        voice_url = (
            message.get("voice_url")
            or (message.get("voice", {}) or {}).get("file_id")
        )
        if voice_url and isinstance(voice_url, str) and voice_url.strip():
            contents.append(TextContent(text=f"[voice: {voice_url.strip()}]"))

        # ---- Document / file ----------------------------------------
        doc = message.get("document") if isinstance(message.get("document"), dict) else {}
        attachment_url = (
            message.get("attachment_url")
            or doc.get("file_id")
            or doc.get("url")
        )
        attachment_name = (
            message.get("attachment_name")
            or doc.get("file_name")
            or "file"
        )
        if attachment_url and isinstance(attachment_url, str) and attachment_url.strip():
            contents.append(
                TextContent(
                    text=f"[file: {attachment_name} {attachment_url.strip()}]",
                ),
            )

        # ---- Video --------------------------------------------------
        video_url = (
            message.get("video_url")
            or (message.get("video", {}) or {}).get("file_id")
        )
        if video_url and isinstance(video_url, str) and video_url.strip():
            contents.append(TextContent(text=f"[video: {video_url.strip()}]"))

        # ---- Image-only fallback ------------------------------------
        # If we got an image (or other attachment) without user text, the
        # agent would otherwise receive a request with no human context.
        # Inject a Vietnamese marker so the agent knows what it is dealing
        # with.
        if not text and contents:
            for blk in contents:
                if isinstance(blk, ImageContent):
                    url = blk.image_url or getattr(blk, "url", None)
                    if url and url not in (text or ""):
                        contents.insert(
                            0,
                            TextContent(text=f"[Anh nhan duoc tu user. URL: {url}]"),
                        )
                        break

        if not contents:
            contents.append(TextContent(text="[event: no content]"))

        # Extract sender_id from message.from.id (per Zalo docs this == chat_id
        # for private chats). Fall back to chat_id if missing.
        msg_from = message.get("from") or {}
        sender_id = str(msg_from.get("id") or chat_id)
        sender_name = msg_from.get("display_name", "")

        # Push to manager queue via _enqueue (Telegram-style native payload).
        # The manager drains it, calls self._payload_to_request to convert to
        # AgentRequest, then streams events back through on_reply_sent /
        # self.send().
        native = {
            "channel_id": self.channel,
            "sender_id": sender_id,
            "content_parts": contents,
            "meta": {
                "chat_id": chat_id,
                "message_id": msg_id,
                "from": sender_id,
                "from_name": sender_name,
                "chat_type": chat.get("chat_type", "PRIVATE"),
            },
        }
        try:
            if self._enqueue is not None:
                # Start typing indicator - the user sees "typing..." while the
                # agent thinks, and send() will stop it on the way out.
                try:
                    self._start_typing(chat_id)
                except Exception:
                    logger.exception("zalo: failed to start typing")
                self._is_processing[chat_id] = True
                self._enqueue(native)
                logger.debug(
                    "[zalo] enqueued native payload: chat=%s msg=%s "
                    "sender=%s parts=%d",
                    chat_id, msg_id, sender_id, len(contents),
                )
            else:
                logger.warning(
                    "zalo: _enqueue not set, message dropped: "
                    "chat=%s msg=%s",
                    chat_id,
                    msg_id,
                )
        except Exception:
            logger.exception("Failed to dispatch Zalo event to agent")


    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------
    def _start_typing(self, chat_id: str) -> None:
        """Start a background loop that pings "typing" every 4s."""
        if not self._show_typing:
            print(f"[zalo] typing disabled (chat_id={chat_id})", flush=True)
            return
        # Cancel any existing loop for this chat (debounce).
        self._stop_typing(chat_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop (e.g. called from sync context) - skip.
            return
        self._typing_tasks[chat_id] = loop.create_task(
            self._typing_loop(chat_id),
        )
        print(f"[zalo] typing started (chat_id={chat_id})", flush=True)

    def _stop_typing(self, chat_id: str) -> None:
        """Cancel the typing loop for this chat (if any)."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly call sendChatAction("typing") until cancelled.

        Zalo's chat-action API is rate-limited, so we sleep 4s between
        pings - just under the typical 5s expiry window.
        """
        try:
            # Max 90s of "typing" - some agent queries can take minutes.
            deadline = asyncio.get_event_loop().time() + 90
            while self._client is not None:
                try:
                    await self._client.send_chat_action(
                        chat_id=chat_id,
                        action="typing",
                    )
                except Exception:
                    logger.debug(
                        "zalo: typing ping failed (non-fatal) "
                        "chat_id=%s", chat_id,
                    )
                await asyncio.sleep(4)
                if asyncio.get_event_loop().time() >= deadline:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            cur = self._typing_tasks.get(chat_id)
            if cur is asyncio.current_task():
                self._typing_tasks.pop(chat_id, None)

# ----------------------------------------------------------------------
# Channel registry hooks
# ----------------------------------------------------------------------

def get_channel(config: Dict[str, Any], **kwargs) -> ZaloChannel:
    """Factory called by the registry to build a ZaloChannel."""
    zalo_cfg = config.get("channels", {}).get("zalo", {})
    return ZaloChannel(
        process=kwargs.get("process"),
        bot_token=zalo_cfg.get("bot_token", ""),
        secret_token=zalo_cfg.get("secret_token", ""),
        poll_interval=int(zalo_cfg.get("poll_interval", 30)),
        max_retries=int(zalo_cfg.get("max_retries", 3)),
        max_message_len=int(zalo_cfg.get("max_message_len", 2000)),
        on_reply_sent=kwargs.get("on_reply_sent"),
        **{k: v for k, v in kwargs.items() if k not in ("process", "on_reply_sent")},
    )


def install(config: Dict[str, Any]) -> None:
    """Called when the channel is first loaded — ensures config has a zalo block."""
    channels = config.setdefault("channels", {})
    if "zalo" not in channels:
        channels["zalo"] = {
            "enabled": False,
            "bot_prefix": "",
            "filter_tool_messages": True,
            "filter_thinking": True,
            "dm_policy": "open",
            "group_policy": "open",
            "allow_from": [],
            "deny_message": "",
            "require_mention": False,
            "access_control_dm": False,
            "access_control_group": False,
            "dm_disabled": False,
            "group_disabled": False,
            "bot_token": "",
            "poll_interval": 30,
            "max_retries": 3,
            "max_message_len": 2000,
        }


