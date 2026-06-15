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
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

from .constants import (
    SLACK_DEDUP_MAX_ENTRIES,
    SLACK_DEDUP_WINDOW_SECONDS,
    SLACK_THREAD_CACHE_MAX,
    SLACK_THREAD_CACHE_TTL_SECONDS,
)
from .utils import build_dedup_key, generate_session_id, with_retry

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

# Commands that are known to the QwenPaw pipeline and can be rewritten
# from ``!`` prefix to ``/`` prefix.  Populated dynamically from the
# channel's :class:`CommandRegistry` when available.
_KNOWN_COMMAND_WORDS: frozenset[str] = frozenset(
    {
        "stop",
        "status",
        "restart",
        "reload-config",
        "reload_config",
        "version",
        "help",
        "reset",
        "clear",
        "dream",
        "daemon",
    },
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
        self._bot_user_id: Optional[str] = None

        self._dedup_lock = asyncio.Lock()
        self._dedup_map: OrderedDict[str, float] = OrderedDict()
        self._thread_participation: Dict[str, float] = {}
        self._http_session: Optional[aiohttp.ClientSession] = None

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
        if subtype == "message_changed":
            await self._handle_message_changed(event, client)
            return
        # 2. Skip bot messages
        if event.get("bot_id"):
            return

        # 3. Deduplicate
        dedup_key = build_dedup_key(event)
        if await self._is_duplicate(dedup_key):
            return

        # 4. Extract identifiers
        channel_id: str = event.get("channel") or ""
        user_id: str = event.get("user") or ""
        event_ts: str = event.get("ts") or ""
        thread_ts: str = event.get("thread_ts") or ""
        is_dm = channel_id.startswith("D")
        is_group = not is_dm

        # 5. @mention gate (group channels only)
        if is_group and self._require_mention and not was_mentioned:
            if not self._is_bot_mentioned(event):
                return

        # 6. Thread participation gate.
        # A thread reply is accepted when:
        #   (a) the bot has previously joined the thread (recorded in
        #       _thread_participation, 24h TTL), OR
        #   (b) the bot has sent a message in this thread (tracked in
        #       _bot_message_ts — covers the "bot replied, then user
        #       replied again after restart" scenario).
        if thread_ts and not was_mentioned:
            if not self._has_thread_participation(channel_id, thread_ts):
                if thread_ts not in self._channel._bot_message_ts:
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

        # 8. Rewrite "!command" → "/command" for thread compatibility
        text = _rewrite_bang_command(text)

        # 9. Append link unfurl previews from attachments
        text = _append_unfurl_text(text, event.get("attachments") or [])

        # 10. Extract file attachments
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

        # 11. Build & enqueue native dict
        session_id = generate_session_id(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            is_dm=is_dm,
        )
        native: Dict[str, Any] = {
            "channel_id": self._channel.channel,
            "sender_id": user_id,
            "user_id": user_id,
            "session_id": session_id,
            "content_parts": content_parts,
            "meta": {
                "slack_channel_id": channel_id,
                "slack_thread_ts": thread_ts,
                "slack_message_ts": event_ts,
                "slack_user_id": user_id,
                "is_dm": is_dm,
                "is_group": is_group,
                "bot_mentioned": was_mentioned,
            },
        }
        if file_extraction_failed:
            native["file_extraction_error"] = True

        if self._enqueue:
            self._enqueue(native)

        # 12. Record thread participation
        if thread_ts:
            self._record_thread_participation(channel_id, thread_ts)

        # 13. Prune _bot_message_ts when it grows too large.
        # The set tracks every message ts the bot has ever sent;
        # without bounds it would grow unboundedly.  We trim the
        # oldest half when exceeding 5000 entries.
        if len(self._channel._bot_message_ts) > 5000:
            sorted_items = sorted(
                self._channel._bot_message_ts.items(),
                key=lambda x: x[1],
            )
            keep = sorted_items[len(sorted_items) // 2 :]
            self._channel._bot_message_ts = dict(keep)

    async def _handle_message_changed(
        self,
        event: dict,
        _client: Any,
    ) -> None:
        """Handle ``message_changed`` events.

        Only processes messages that belong to a Slack assistant thread
        (``assistant_thread`` metadata).  Other edit events are ignored
        to avoid double-processing user edits.

        The bot's own message edits are also skipped to prevent
        self-triggered loops.
        """
        message = event.get("message", {})
        if not isinstance(message, dict):
            return

        # Only process assistant-thread messages.
        metadata = message.get("metadata", {})
        if not isinstance(metadata, dict):
            return
        if not metadata.get("event_type") == "assistant_thread":
            return

        # Skip the bot's own message edits.
        bot_id = self._resolve_bot_user_id()
        if bot_id and message.get("bot_id"):
            if message.get("user") == bot_id:
                return

        # Use the message's own user field (the original author).
        user_id = message.get("user") or event.get("user") or ""
        if not user_id:
            return

        # Extract text from the edited message.
        text = _extract_message_text(message, self._bot_prefix)
        if not text.strip():
            return

        channel_id = event.get("channel") or ""
        thread_ts = message.get("thread_ts") or event.get("thread_ts") or ""
        event_ts = message.get("ts") or event.get("ts") or ""
        is_dm = channel_id.startswith("D")

        # Build native payload and enqueue.
        session_id = generate_session_id(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            is_dm=is_dm,
        )
        native: Dict[str, Any] = {
            "channel_id": self._channel.channel,
            "sender_id": user_id,
            "user_id": user_id,
            "session_id": session_id,
            "content_parts": [TextContent(text=text)],
            "meta": {
                "slack_channel_id": channel_id,
                "slack_thread_ts": thread_ts,
                "slack_message_ts": event_ts,
                "slack_user_id": user_id,
                "is_dm": is_dm,
                "is_group": not is_dm,
                "bot_mentioned": False,
                "edited": True,  # 标记为编辑事件
            },
        }

        if self._enqueue:
            self._enqueue(native)

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
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
        url = await self._resolve_download_url(url)

        if mime_type.startswith("image/"):
            return ImageContent(image_url=url, filename=filename)
        if mime_type.startswith("audio/"):
            return AudioContent(audio_url=url, filename=filename)
        if mime_type.startswith("video/"):
            return VideoContent(video_url=url, filename=filename)
        return FileContent(file_url=url, filename=filename)

    # ── Download URL resolution ──

    async def _resolve_download_url(self, url: str) -> str:
        """Follow up to 3 HTTP redirects with retry to
        get the real download URL.

        Slack private file URLs (``url_private`` / ``url_private_download``)
        are temporary and may redirect through multiple hosts.  This helper
        follows each redirect, checks the content type to avoid caching
        HTML error pages, and returns the final URL.

        Falls back to the original *url* when resolution fails.
        """
        current = url
        for _ in range(3):
            try:
                session = await self._get_http_session()
                async with session.head(
                    current,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(10),
                ) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if location:
                            current = location
                            continue
                    # Check content type — Slack may return HTML error
                    # pages instead of binary on auth failures.
                    ct = resp.headers.get("content-type", "")
                    if "text/html" in ct and resp.status != 200:
                        logger.debug(
                            "slack handler: HTML response for %s (status=%s)",
                            current[:80],
                            resp.status,
                        )
                        return url
                    return current
            except Exception:
                logger.debug(
                    "slack handler: redirect resolution failed for %s",
                    current[:80],
                )
                return url
        return current

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
        bot_id = self._resolve_bot_user_id()
        if not bot_id:
            return False
        text = event.get("text") or ""
        return f"<@{bot_id}>" in text

    def _resolve_bot_user_id(self) -> Optional[str]:
        if self._bot_user_id is None:
            self._bot_user_id = (
                getattr(
                    self._channel,
                    "_bot_user_id",
                    None,
                )
                or ""
            )
        return self._bot_user_id or None

    # ── Thread participation ──

    def _record_thread_participation(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        key = f"{channel_id}:{thread_ts}"
        now = time.time()
        self._thread_participation[key] = now
        if len(self._thread_participation) > SLACK_THREAD_CACHE_MAX:
            expired = [
                k
                for k, v in self._thread_participation.items()
                if now - v > SLACK_THREAD_CACHE_TTL_SECONDS
            ]
            for k in expired:
                self._thread_participation.pop(k, None)

    def _has_thread_participation(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        key = f"{channel_id}:{thread_ts}"
        last = self._thread_participation.get(key)
        if last is None:
            return False
        if time.time() - last > SLACK_THREAD_CACHE_TTL_SECONDS:
            self._thread_participation.pop(key, None)
            return False
        return True

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
        cache_key = f"{channel_id}:{thread_ts}"
        now = time.monotonic()
        cached = self._channel.thread_context_cache.get(cache_key)
        if cached and (now - cached[1]) < self._channel.THREAD_CACHE_TTL:
            return cached[0]

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
        bot_id = self._resolve_bot_user_id()

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
            name = await self._resolve_user_name(user, client)
            context_parts.append(f"{name}: {msg_text}")

        content = "\n".join(context_parts) if context_parts else ""
        self._channel.thread_context_cache[cache_key] = (content, now)
        return content

    async def _resolve_user_name(
        self,
        user_id: str,
        client: Any,
    ) -> str:
        """Look up a Slack user's display name via ``users.info``.

        Falls back to the user ID when the API call fails or the user
        is not found.
        """
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
                        return display
                    real = profile.get("real_name")
                    if real:
                        return real
                name = info.get("real_name") or info.get("name")
                if name:
                    return name
        except Exception:
            logger.debug(
                "slack handler: users_info failed for %s",
                user_id,
            )
        return user_id


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


# ── "!" command rewriting ──


def _rewrite_bang_command(text: str) -> str:
    """Rewrite ``!command`` to ``/command`` for Slack threads.

    Slack blocks ``/``-prefixed messages in threads but allows ``!``.
    QwenPaw's :class:`CommandRegistry` expects ``/``-prefixed commands,
    so we transparently rewrite the prefix before the message enters
    the pipeline.
    """
    if not text or not text.startswith("!"):
        return text
    stripped = text[1:].lstrip()
    if not stripped:
        return text
    # Extract the first word (the command name).
    first_word = stripped.split(maxsplit=1)[0].lower()
    # Strip any trailing @bot mention (e.g. "!help @MyBot").
    if "@" in first_word:
        first_word = first_word.split("@")[0]
    if first_word in _KNOWN_COMMAND_WORDS:
        return "/" + stripped
    return text


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


async def _download_slack_file(url: str, token: str) -> bytes:
    """Download a Slack file with retry and content-type validation.

    Slack private URLs may return HTML error pages instead of binary
    content when authentication fails or the file has expired.  This
    helper checks the ``content-type`` header and raises ``ValueError``
    when HTML is received instead of the expected binary content.

    Parameters
    ----------
    url:
        The private download URL (``url_private_download``).
    token:
        Bot token for the ``Authorization: Bearer`` header.
    """

    last_exc = None
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(30),
                ) as resp:
                    if resp.status == 200:
                        ct = resp.headers.get("content-type", "")
                        if "text/html" in ct:
                            raise ValueError(
                                "Slack returned HTML instead of "
                                "binary content",
                            )
                        return await resp.read()
                    if resp.status in (429, 500, 502, 503):
                        await asyncio.sleep(1.5**attempt)
                        continue
                    resp.raise_for_status()
        except ValueError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(1.5**attempt)
    raise last_exc or Exception("Max retries exceeded")
