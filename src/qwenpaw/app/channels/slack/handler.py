# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Slack Socket Mode inbound event handler.

Registers callbacks on a ``slack_bolt.AsyncApp`` for ``message`` and
``app_mention`` events, converts Slack's native payload into a
unified ``native`` dict, and enqueues it for the processing pipeline.

Responsibilities
----------------
* Filter bot messages, subtypes, and duplicates (based on ``event_id``).
* Detect ``@mention`` in group channels (honouring ``require_mention``).
* Track thread participation so the bot automatically replies in
  threads it has previously joined (24-hour TTL).
* Extract full text from ``rich_text`` blocks (including quotes,
  lists, and preformatted sections).
* Download file attachments (images, audio, video, generic files) via
  ``files.info`` and private URL discovery.
* Build a ``native`` dict suitable for ``BaseChannel._consume_one_request``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

import aiofiles
import aiohttp

from qwenpaw.schemas import (
    AudioContent,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

from .constants import (
    SLACK_DEDUP_MAX_ENTRIES,
    SLACK_DEDUP_WINDOW_SECONDS,
)
from .utils import (
    build_dedup_key,
    generate_session_id,
    with_retry,
)

if TYPE_CHECKING:
    from .channel import SlackChannel

logger = logging.getLogger(__name__)

# Slack message subtypes we silently ignore.
_SKIP_SUBTYPES: frozenset[str] = frozenset(
    {
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "group_join",
        "group_leave",
        "group_topic",
        "group_purpose",
        "group_name",
        "message_deleted",
        "ekm_access_denied",
        "bot_message",
    },
)

# Subtypes that may carry user content.
_ALLOWED_SUBTYPES: frozenset[str] = frozenset(
    {"file_share", "thread_broadcast"},
)


class SlackEventHandler:
    """Convert Slack events to native dicts and enqueue for processing."""

    def __init__(
        self,
        channel: "SlackChannel",
        enqueue_callback: Optional[Callable[[Dict[str, Any]], None]],
        bot_prefix: str,
        require_mention: bool,
    ):
        self._channel = channel
        self._enqueue = enqueue_callback
        self._bot_prefix = bot_prefix
        self._require_mention = require_mention

        self._dedup_lock = asyncio.Lock()
        self._dedup_map: OrderedDict[str, float] = OrderedDict()
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._user_name_cache: Dict[str, str] = {}

    # ── Registration ──

    def register(self, app: Any) -> None:
        """Register Bolt event handlers."""
        app.event("message")(self._on_message_event)
        app.event("app_mention")(self._on_app_mention)

    # ── Bolt callbacks ──

    async def _on_message_event(
        self,
        event: dict,
        client: Any,
        body: dict,
        ack: Any,
    ) -> None:
        await ack()
        await self._handle_event(event, client, was_mentioned=False)

    async def _on_app_mention(
        self,
        event: dict,
        client: Any,
        body: dict,
        ack: Any,
    ) -> None:
        await ack()
        await self._handle_event(event, client, was_mentioned=True)

    # ── Core processing ──
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches,too-many-statements
    async def _handle_event(
        self,
        event: dict,
        client: Any,
        *,
        was_mentioned: bool = False,
    ) -> None:
        """Validate, extract, and enqueue a single inbound event."""
        # 1. Skip blacklisted subtypes
        subtype = event.get("subtype") or ""
        if subtype in _SKIP_SUBTYPES:
            return
        if subtype and subtype not in _ALLOWED_SUBTYPES:
            return
        # 2. Skip bot messages
        if event.get("bot_id"):
            return

        # 3. Extract identifiers
        channel_id: str = event.get("channel") or ""
        user_id: str = event.get("user") or ""
        event_ts: str = event.get("ts") or ""
        thread_ts: str = event.get("thread_ts") or ""
        is_dm = channel_id.startswith("D")
        is_group = not is_dm

        # 4a. Channel-level mute: honour dm_disabled / group_disabled
        if is_dm and getattr(self._channel, "dm_disabled", False):
            logger.debug(
                "slack handler: dropping DM message (dm_disabled) "
                "channel=%s user=%s",
                channel_id,
                user_id,
            )
            return
        if is_group and getattr(self._channel, "group_disabled", False):
            logger.debug(
                "slack handler: dropping group message (group_disabled) "
                "channel=%s user=%s",
                channel_id,
                user_id,
            )
            return

        # 5. @mention gate (group channels only)
        # - Thread replies: always require @mention (no auto-tracking)
        # - Top-level messages: honour require_mention config
        if is_group and not was_mentioned:
            if thread_ts or self._require_mention:
                if not self._is_bot_mentioned(event):
                    return

        # 6. Deduplicate (after all gates so dropped messages
        # don't block the paired app_mention event).
        dedup_key = build_dedup_key(event)
        if await self._is_duplicate(dedup_key):
            return

        # 7. Extract text
        text = _extract_message_text(event, self._bot_prefix)

        # 7a. Fetch thread context (cached, TTL 60 s).
        # Prepend recent thread history so the Agent has full context
        # for multi-turn conversations inside a thread.
        if thread_ts:
            thread_context = await self._fetch_thread_context(
                channel_id,
                thread_ts,
                event_ts,
                client,
            )
            if thread_context:
                text = (
                    f"[Thread context]\n{thread_context}\n\n"
                    f"[Latest message]\n{text}"
                )

        # 8. Append link unfurl previews from attachments
        text = _append_unfurl_text(text, event.get("attachments") or [])

        # 9. Extract file attachments
        content_parts: list = [TextContent(text=text)] if text else []
        file_extraction_failed = False
        try:
            file_parts = await self._extract_file_parts(event, client)
            content_parts.extend(file_parts)
        except Exception:
            logger.exception(
                "slack handler: failed to extract file attachments",
            )
            file_extraction_failed = True

        if not content_parts:
            return

        # 10. Resolve display name (cached) and build native dict
        user_name = await self._resolve_user_name(user_id, client)
        session_id = generate_session_id(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            is_dm=is_dm,
        )
        native: Dict[str, Any] = {
            "channel_id": self._channel.channel,
            "sender_id": user_id,
            "acl_sender_id": user_id,
            "user_id": user_id,
            "session_id": session_id,
            "content_parts": content_parts,
            "meta": {
                "slack_channel_id": channel_id,
                "slack_thread_ts": thread_ts,
                "slack_message_ts": event_ts,
                "slack_user_id": user_id,
                "is_group": is_group,
                "bot_mentioned": was_mentioned,
                "user_name": user_name,
            },
        }
        if file_extraction_failed:
            native["file_extraction_error"] = True

        if self._enqueue:
            self._enqueue(native)

    async def close(self) -> None:
        """Close the internal aiohttp session if open."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                trust_env=True,
            )
        return self._http_session

    # ── File extraction ──

    async def _extract_file_parts(
        self,
        event: dict,
        client: Any,
    ) -> list:
        parts: list = []
        for f in event.get("files") or []:
            part = await self._build_content_from_file(f, client)
            if part is not None:
                parts.append(part)
        return parts

    async def _build_content_from_file(
        self,
        f: dict,
        _client: Any,
    ) -> Optional[Any]:
        mime_type: str = f.get("mimetype") or ""
        filename: str = f.get("name") or "file"
        url: str = f.get("url_private_download") or f.get("url_private") or ""
        if not url:
            return None
        local_path = await self._download_slack_file(url, filename)
        if local_path is None:
            return None

        if mime_type.startswith("image/"):
            return ImageContent(image_url=local_path, filename=filename)
        if mime_type.startswith("audio/"):
            ext = os.path.splitext(filename)[1].lstrip(".") or "mp3"
            return AudioContent(data=local_path, format=ext)
        if mime_type.startswith("video/"):
            return VideoContent(video_url=local_path, filename=filename)
        return FileContent(file_url=local_path, filename=filename)

    # ── Download URL resolution ──

    async def _download_slack_file(
        self,
        url: str,
        filename: str,
    ) -> Optional[str]:
        """Download a Slack private file with bot auth and cache locally.

        Slack ``url_private_download`` URLs require the bot token as an
        ``Authorization`` header.  aiohttp handles redirects automatically
        (``follow_redirects=True`` by default), so no manual redirect
        resolution loop is needed.

        On auth failure Slack returns an HTML sign-in page — we detect the
        ``text/html`` content-type and bail early instead of caching junk.

        Retries up to 3 times with exponential backoff on transient errors
        (timeouts, 429, 5xx).  Returns the absolute path to the cached
        temp file, or *None* on failure.
        """
        headers = {"Authorization": f"Bearer {self._channel.bot_token}"}
        last_exc = None

        for attempt in range(3):
            try:
                session = await self._get_http_session()
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(60),
                    proxy=self._channel.proxy_url or None,
                ) as resp:
                    if resp.status != 200:
                        if (
                            resp.status
                            in (
                                429,
                                500,
                                502,
                                503,
                                504,
                            )
                            and attempt < 2
                        ):
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        logger.warning(
                            "slack handler: download status=%s for %s",
                            resp.status,
                            filename,
                        )
                        return None

                    ct = resp.headers.get("content-type", "")
                    if "text/html" in ct:
                        logger.warning(
                            "slack handler: HTML response for %s "
                            "(auth issue?)",
                            filename,
                        )
                        return None

                    data = await resp.read()
                    break
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                last_exc = exc
                if attempt < 2:
                    logger.debug(
                        "slack handler: retry %d/2 for %s",
                        attempt + 1,
                        filename,
                    )
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                logger.exception(
                    "slack handler: download failed for %s",
                    filename,
                )
                return None
        else:
            logger.error(
                "slack handler: exhausted retries for %s: %s",
                filename,
                last_exc,
            )
            return None

        # Cache locally
        suffix = os.path.splitext(filename)[1] or ""
        path = str(
            self._channel.media_dir / f"slack_{os.urandom(8).hex()}{suffix}",
        )
        async with aiofiles.open(path, "wb") as fh:
            await fh.write(data)

        logger.debug(
            "slack handler: cached %s → %s (%d bytes)",
            filename,
            path,
            len(data),
        )
        return path

    # ── Deduplication ──

    async def _is_duplicate(self, dedup_key: str) -> bool:
        now = time.monotonic()
        async with self._dedup_lock:
            expired = [
                k
                for k, v in self._dedup_map.items()
                if now - v > SLACK_DEDUP_WINDOW_SECONDS
            ]
            for k in expired:
                self._dedup_map.pop(k, None)
            if dedup_key in self._dedup_map:
                return True
            self._dedup_map[dedup_key] = now
            if len(self._dedup_map) > SLACK_DEDUP_MAX_ENTRIES:
                self._dedup_map.popitem(last=False)
            return False

    # ── @mention detection ──

    def _is_bot_mentioned(self, event: dict) -> bool:
        bot_id = self._channel.bot_user_id or None
        if not bot_id:
            return False
        text = event.get("text") or ""
        return f"<@{bot_id}>" in text

    # ── Thread context fetching ──

    async def _fetch_thread_context(
        self,
        channel_id: str,
        thread_ts: str,
        current_ts: str,
        client: Any,
    ) -> str:
        """Fetch recent thread history via ``conversations_replies``.

        Results are cached in ``_thread_context_cache`` with a TTL
        (default 60 s) to avoid repeated API calls during rapid
        multi-turn exchanges.  The bot's own messages are excluded from
        the returned context.

        Returns a string like ``user: message\nuser2: message2``, or
        an empty string when the thread is empty or the cache is still
        warm.
        """
        cached = self._channel.get_cached_thread_context(
            channel_id,
            thread_ts,
        )
        if cached:
            return cached

        try:
            result = await with_retry(
                client.conversations_replies,
                channel=channel_id,
                ts=thread_ts,
                limit=30,
                inclusive=True,
            )
        except Exception:
            logger.debug(
                "slack handler: conversations_replies failed "
                "channel=%s thread=%s",
                channel_id,
                thread_ts,
            )
            return ""

        messages = result.get("messages", [])
        context_parts: list[str] = []
        bot_id = self._channel.bot_user_id or None

        for msg in messages:
            if msg.get("ts") == current_ts:
                continue
            # Skip bot's own messages so the Agent doesn't see
            # its own replies as "context".
            if msg.get("bot_id") and msg.get("user") == bot_id:
                continue
            msg_text = (msg.get("text") or "").strip()
            if not msg_text:
                continue
            user = msg.get("user") or "unknown"
            name = await self._resolve_user_name(user, client) or user
            context_parts.append(f"{name}: {msg_text}")

        content = "\n".join(context_parts) if context_parts else ""
        self._channel.set_cached_thread_context(
            channel_id,
            thread_ts,
            content,
        )
        return content

    async def _resolve_user_name(
        self,
        user_id: str,
        client: Any,
    ) -> str:
        """Look up a Slack user's display name via ``users.info``.

        Falls back to the user ID when the API call fails or the user
        is not found.  Results are cached per user_id.
        """
        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]
        try:
            resp = await with_retry(
                client.users_info,
                user=user_id,
            )
            info = resp.get("user", {})
            if isinstance(info, dict):
                profile = info.get("profile", {})
                if isinstance(profile, dict):
                    display = profile.get("display_name")
                    if display:
                        self._user_name_cache[user_id] = display
                        return display
                    real = profile.get("real_name")
                    if real:
                        self._user_name_cache[user_id] = real
                        return real
                name = info.get("real_name") or info.get("name")
                if name:
                    self._user_name_cache[user_id] = name
                    return name
        except Exception:
            logger.debug(
                "slack handler: users_info failed for %s",
                user_id,
            )
        self._user_name_cache[user_id] = ""
        return ""

    async def handle_slash_command(self, command: dict) -> None:
        slash_name = (command.get("command") or "").lstrip("/")
        text = (command.get("text") or "").strip()
        channel_id = command.get("channel_id") or ""
        user_id = command.get("user_id") or ""
        is_dm = channel_id.startswith("D")

        full_text = f"/{slash_name} {text}".strip()

        session_id = generate_session_id(
            channel_id=channel_id,
            thread_ts="",
            user_id=user_id,
            is_dm=is_dm,
        )

        user_name = command.get("user_name") or ""

        native = {
            "channel_id": self._channel.channel,
            "sender_id": user_id,
            "acl_sender_id": user_id,
            "user_id": user_id,
            "session_id": session_id,
            "content_parts": [TextContent(text=full_text)],
            "meta": {
                "slack_channel_id": channel_id,
                "slack_thread_ts": "",
                "slack_message_ts": "",
                "slack_user_id": user_id,
                "is_group": not is_dm,
                "slack_response_url": command.get("response_url", ""),
                "slack_is_slash_command": True,
                "user_name": user_name,
            },
        }
        if self._enqueue:
            self._enqueue(native)


# ── Text extraction helpers ──


def _extract_message_text(event: dict, bot_prefix: str) -> str:
    """Extract the best text representation from an event.

    Prefers ``rich_text`` blocks over the plain ``text`` field.
    Strips *bot_prefix* from the beginning.
    """
    text = event.get("text") or ""
    blocks = event.get("blocks") or []
    if blocks:
        extracted = _extract_text_from_blocks(blocks)
        if extracted:
            text = extracted
    if bot_prefix and text.startswith(bot_prefix):
        text = text[len(bot_prefix) :].strip()
    # Strip leading Slack @mention only when it wraps a slash command,
    # so magic commands like "@bot /stop" are correctly detected.
    # Similar to WeCom's handling of @prefix before commands.
    text = re.sub(r"^<@\w+>\s+(?=/)", "", text).strip()
    return text


def _extract_text_from_blocks(blocks: list) -> str:
    """Walk a Slack Block Kit ``blocks`` array and return plain text."""
    if not blocks:
        return ""
    parts: list[str] = []
    _walk_blocks(blocks, parts, quote_depth=0, bullet="")
    return "\n".join(parts)


def _walk_blocks(
    blocks: list,
    parts: list[str],
    quote_depth: int = 0,
    bullet: str = "",
) -> None:
    for block in blocks:
        bt = block.get("type", "")
        if bt == "rich_text":
            _walk_elements(
                block.get("elements", []),
                parts,
                quote_depth,
                bullet,
            )
        elif bt == "section":
            text_obj = block.get("text", {})
            if isinstance(text_obj, dict) and text_obj.get("text"):
                _append_line(parts, text_obj["text"], quote_depth, bullet)


def _walk_elements(
    elements: list,
    parts: list[str],
    quote_depth: int,
    bullet: str,
) -> None:
    for elem in elements:
        et = elem.get("type", "")

        if et == "rich_text_section":
            _append_line(
                parts,
                _render_inline_elements(elem.get("elements", [])),
                quote_depth,
                bullet,
            )
        elif et == "rich_text_quote":
            _walk_elements(
                elem.get("elements", []),
                parts,
                quote_depth + 1,
                bullet,
            )
        elif et == "rich_text_list":
            style = elem.get("style", "bullet")
            for idx, item in enumerate(elem.get("elements", [])):
                item_bullet = f"{idx + 1}. " if style == "ordered" else "• "
                _walk_elements(
                    item.get("elements", []),
                    parts,
                    quote_depth,
                    item_bullet,
                )
        elif et == "rich_text_preformatted":
            lang = elem.get("language", "")
            pre_parts: list[str] = []
            for sub in elem.get("elements", []):
                if sub.get("type") == "text":
                    pre_parts.append(sub.get("text", ""))
            code = "\n".join(pre_parts)
            if code.strip():
                fence = f"```{lang}"
                _append_line(parts, fence, quote_depth, "")
                for line in code.split("\n"):
                    _append_line(parts, line, quote_depth, "")
                _append_line(parts, "```", quote_depth, "")
        elif et == "text":
            # Raw text element (e.g. inside rich_text_quote or
            # rich_text_list when the item is a bare text node).
            _append_line(
                parts,
                _render_inline_elements([elem]),
                quote_depth,
                bullet,
            )


def _render_inline_elements(elements: list) -> str:
    pieces: list[str] = []
    for el in elements:
        et = el.get("type", "")
        if et == "text":
            pieces.append(el.get("text", ""))
        elif et == "link":
            url = el.get("url", "")
            text = el.get("text") or url
            pieces.append(f"{text} ({url})")
        elif et == "channel":
            pieces.append(f"<#{el.get('channel_id', '')}>")
        elif et == "user":
            pieces.append(f"<@{el.get('user_id', '')}>")
        elif et == "usergroup":
            pieces.append(f"<!subteam^{el.get('usergroup_id', '')}>")
        elif et == "emoji":
            pieces.append(f":{el.get('name', '')}:")
        elif et == "broadcast":
            pieces.append(f"<!{el.get('range', 'here')}>")
        elif et == "date":
            pieces.append(el.get("fallback", ""))
    return "".join(pieces)


def _append_line(
    parts: list[str],
    text: str,
    quote_depth: int,
    bullet: str,
) -> None:
    if not text or not text.strip():
        return
    prefix = (">" * quote_depth + " ") if quote_depth else ""
    parts.append(f"{prefix}{bullet}{text}".rstrip())


# ── Link unfurl extraction ──


def _append_unfurl_text(text: str, attachments: list) -> str:
    """Append link-preview text from Slack *attachments*.

    When a user shares a URL, Slack enriches the message with
    ``attachments`` containing title, description, and image URL.
    We extract the human-readable parts and append them to the
    message text so the Agent can see the preview content.
    """
    if not attachments:
        return text

    unfurl_parts: list[str] = []
    for att in attachments:
        # Skip message-unfurl attachments (internal Slack links).
        if att.get("is_msg_unfurl"):
            continue

        title = att.get("title", "").strip()
        title_link = att.get("title_link", "").strip()
        from_url = att.get("from_url", "").strip()
        att_text = (
            att.get("text", "").strip() or att.get("fallback", "").strip()
        )

        if title:
            if title_link:
                unfurl_parts.append(f"📎 [{title}]({title_link})")
            elif from_url:
                unfurl_parts.append(f"📎 [{title}]({from_url})")
            else:
                unfurl_parts.append(f"📎 {title}")
        elif from_url:
            unfurl_parts.append(f"📎 {from_url}")

        if att_text:
            # Truncate long descriptions.
            truncated = att_text[:500] + ("…" if len(att_text) > 500 else "")
            unfurl_parts.append(f"   {truncated}")

    if not unfurl_parts:
        return text

    suffix = "\n\n" + "\n".join(unfurl_parts)
    return text + suffix
