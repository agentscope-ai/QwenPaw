# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Slack outbound message sender.

Handles text, image, and file delivery through the Slack Web API.
Text messages are formatted as mrkdwn and automatically split at
the 40,000-character limit.  Image and file uploads use Slack's
``files.uploadV2`` (for simple cases) or the 3-step external upload
flow (``files_getUploadURLExternal`` → HTTP POST →
``files_completeUploadExternal``) when a local file path is provided.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import unquote, urlparse

import aiohttp

from qwenpaw.schemas import (
    ContentType,
    ImageContent,
)

from .constants import (
    SLACK_TEXT_LIMIT,
)
from .format import chunk_slack_text, markdown_to_slack_mrkdwn
from .utils import is_slack_host, with_retry

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient
    from .channel import SlackChannel

logger = logging.getLogger(__name__)


def _is_slack_ssrf_allowed(url: str) -> bool:
    """Return True if url resolves to a Slack-whitelisted hostname."""
    return is_slack_host(url)


def _resolve_local_file_path(url: str) -> Optional[str]:
    """Return the local filesystem path if *url* is a ``file://`` URI."""
    if os.path.isfile(url):
        return url

    parsed = urlparse(url)
    if parsed.scheme not in ("file", ""):
        return None
    path = unquote(parsed.path)
    # Windows: strip leading / for drive-letter paths
    if (
        os.name == "nt"
        and path.startswith("/")
        and len(path) > 2
        and path[2] == ":"
    ):
        path = path[1:]
    return path if os.path.isfile(path) else None


class SlackSender:
    """Send text, images, and files to Slack channels."""

    def __init__(self, channel: "SlackChannel"):
        self._channel = channel
        self._per_route_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._per_route_locks_max: int = 1024
        self._http_session: Optional[aiohttp.ClientSession] = None

    # ── Public API ──

    async def send_content_parts(
        self,
        to_handle: str,
        content_parts: list,
        meta: Dict[str, Any],
    ) -> Optional[str]:
        """Send a list of content parts to Slack.

        Text parts are merged, prefixed with the bot name, and sent as
        mrkdwn.  Media parts (image / file / audio / video) are uploaded
        individually.  Returns the ``ts`` of the last delivered message
        or *None*.
        """
        channel_id, thread_ts = self.resolve_route(to_handle, meta)
        route_key = f"{channel_id}:{thread_ts or ''}"

        lock = self._per_route_locks.setdefault(
            route_key,
            asyncio.Lock(),
        )
        # Move to end (LRU) and evict oldest if over capacity
        self._per_route_locks.move_to_end(route_key)
        while len(self._per_route_locks) > self._per_route_locks_max:
            self._per_route_locks.popitem(last=False)

        async with lock:
            return await self._send_content_parts_impl(
                to_handle,
                content_parts,
                meta,
            )

    async def _send_content_parts_impl(
        self,
        to_handle: str,
        content_parts: list,
        meta: Dict[str, Any],
    ) -> Optional[str]:
        """Internal implementation of send_content_parts."""
        channel_id, thread_ts = self.resolve_route(to_handle, meta)
        if not channel_id:
            logger.warning("slack send: no channel_id resolved")
            return None

        text_parts: list[str] = []
        media_parts: list = []
        for p in content_parts:
            pt = getattr(p, "type", None)
            if pt == ContentType.TEXT:
                if p.text:
                    text_parts.append(p.text)
            elif pt == ContentType.REFUSAL:
                if getattr(p, "refusal", None):
                    text_parts.append(p.refusal)
            else:
                media_parts.append(p)

        client = await self._channel.get_client()
        last_ts: Optional[str] = None

        # Send text first, then media
        if text_parts:
            body = "\n".join(text_parts)
            prefix = self._channel.bot_prefix or ""
            if prefix:
                body = f"{prefix}\n{body}"
            last_ts = await self._send_text(
                client,
                channel_id,
                body,
                thread_ts=thread_ts,
            )

        for mp in media_parts:
            last_ts = await self._send_media(
                client,
                channel_id,
                mp,
                thread_ts=thread_ts,
            )

        return last_ts

    # ── Text ──

    async def _send_text(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        text: str,
        *,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Post *text* as Slack mrkdwn, chunking if necessary.

        Each chunk is sent via ``chat_postMessage`` with automatic retry
        on transient failures.
        """
        if not text.strip():
            return None

        mrkdwn = markdown_to_slack_mrkdwn(text)
        chunks = chunk_slack_text(mrkdwn, SLACK_TEXT_LIMIT)
        last_ts: Optional[str] = None
        failed_chunks: list[int] = []

        for i, chunk in enumerate(chunks):
            try:
                resp = await with_retry(
                    client.chat_postMessage,
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=chunk,
                    mrkdwn=True,
                )
                ts = resp.get("ts")
                if ts:
                    last_ts = ts
            except Exception:
                logger.exception(
                    "slack send: chat_postMessage failed chunk=%d/%d "
                    "channel=%s",
                    i + 1,
                    len(chunks),
                    channel_id,
                )
                failed_chunks.append(i)

        # If all chunks fail, throw an explicit error
        if failed_chunks:
            raise RuntimeError(
                f"{len(failed_chunks)}/{len(chunks)} message chunks "
                f"failed to send to channel={channel_id} "
                f"(failed: {failed_chunks})",
            )

        return last_ts

    # ── Media ──

    async def _send_media(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        part: Any,
        *,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Upload a single media part (image, file, audio, video)."""
        pt = getattr(part, "type", None)

        if pt == ContentType.IMAGE:
            return await self._send_image(
                client,
                channel_id,
                part,
                thread_ts=thread_ts,
            )
        if pt in (ContentType.FILE, ContentType.AUDIO, ContentType.VIDEO):
            return await self._send_file(
                client,
                channel_id,
                part,
                thread_ts=thread_ts,
            )
        logger.debug("slack send: unsupported part type %s", pt)
        return None

    async def _send_image(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        part: ImageContent,
        *,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Upload an image via ``files.uploadV2``."""
        url: Optional[str] = getattr(part, "image_url", None)
        filename = getattr(part, "filename", None) or "image.png"

        if not url:
            logger.warning("slack send: image has no url")
            return None

        return await self._upload_media(
            client,
            channel_id,
            url,
            filename,
            title=filename,
            thread_ts=thread_ts,
        )

    async def _send_file(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        part: Any,
        *,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Upload a generic file via ``files.uploadV2``."""
        url: Optional[str] = (
            getattr(part, "file_url", None)
            or getattr(part, "data", None)
            or getattr(part, "video_url", None)
        )
        filename = getattr(part, "filename", None)
        if not filename and url:
            filename = os.path.basename(url) or "file"
        filename = filename or "file"

        if not url:
            logger.warning("slack send: file has no url")
            return None

        return await self._upload_media(
            client,
            channel_id,
            url,
            filename,
            title=filename,
            thread_ts=thread_ts,
        )

    async def _upload_media(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        url: str,
        filename: str,
        *,
        title: str = "",
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Upload media to Slack, using external upload flow for local files.

        Strategy
        --------
        * ``file://`` or local paths → 3-step external upload (SSRF-safe).
        * Remote URL on Slack's domain → ``files.uploadV2``.
        * Other remote URL → blocked (SSRF).
        """
        local_path = _resolve_local_file_path(url)
        if local_path:
            return await self._upload_file_external(
                client,
                channel_id,
                local_path,
                filename,
                title=title,
                thread_ts=thread_ts,
            )

        return await self._upload_remote_media(
            client,
            channel_id,
            url,
            filename,
            title=title,
            thread_ts=thread_ts,
        )

    # pylint: disable=too-many-return-statements
    async def _upload_file_external(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        filepath: str,
        filename: str,
        *,
        title: str = "",
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """3-step external file upload for local files.

        1. ``files_getUploadURLExternal`` → pre-signed URL
        2. HTTP POST binary content to the pre-signed URL
        3. ``files_completeUploadExternal`` → finalise and share
        """

        if not os.path.isfile(filepath):
            logger.warning("slack send: local file not found %s", filepath)
            return None

        file_size = os.path.getsize(filepath)

        # Step 1: get upload URL
        try:
            upload_resp = await with_retry(
                client.files_getUploadURLExternal,
                filename=filename,
                length=file_size,
            )
        except Exception:
            logger.exception(
                "slack send: getUploadURLExternal failed",
            )
            return None

        if not upload_resp.get("ok"):
            logger.warning(
                "slack send: getUploadURLExternal not ok: %s",
                upload_resp.get("error"),
            )
            return None

        upload_url = upload_resp.get("upload_url")
        file_id = upload_resp.get("file_id")
        if not upload_url or not file_id:
            return None

        # Step 2: PUT binary content
        try:
            session = await self._get_http_session()
            with open(filepath, "rb") as fh:
                data = fh.read()
            post_kwargs: dict = {
                "data": data,
                "timeout": aiohttp.ClientTimeout(30),
            }
            # Mirror the proxy used by the Slack REST client
            proxy_url = self._channel.proxy_url
            if proxy_url:
                post_kwargs["proxy"] = proxy_url
            async with session.post(
                upload_url,
                **post_kwargs,
            ) as up_resp:
                if up_resp.status >= 400:
                    logger.warning(
                        "slack send: upload HTTP %s",
                        up_resp.status,
                    )
                    return None
        except Exception:
            logger.exception("slack send: file upload POST failed")
            return None

        # Step 3: complete
        try:
            complete_resp = await with_retry(
                client.files_completeUploadExternal,
                files=[{"id": file_id, "title": title or filename}],
                channel_id=channel_id,
                thread_ts=thread_ts,
            )
            if complete_resp.get("ok"):
                return file_id
        except Exception:
            logger.exception(
                "slack send: completeUploadExternal failed",
            )

        return None

    async def _upload_remote_media(
        self,
        client: "AsyncWebClient",
        channel_id: str,
        url: str,
        filename: str,
        *,
        title: str = "",
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Upload a remote URL to Slack via files.uploadV2 (SSRF-safe)."""
        if not _is_slack_ssrf_allowed(url):
            logger.warning("slack send: SSRF blocked %s", url[:120])
            return None
        try:
            resp = await with_retry(
                client.files_upload_v2,
                channel=channel_id,
                file=url,
                filename=filename,
                title=title or filename,
                thread_ts=thread_ts,
            )
            ts = resp.get("file", {}).get("id")
            return ts
        except Exception:
            logger.exception("slack send: files.uploadV2 failed")
            return None

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                trust_env=True,
            )
        return self._http_session

    # ── Route resolution ──

    @staticmethod
    def resolve_route(
        to_handle: str,
        meta: Dict[str, Any],
    ) -> tuple:
        """Resolve (channel_id, thread_ts) from *to_handle* and *meta*.

        Supported *to_handle* formats:

        * ``slack:thread:<channel>:<thread_ts>`` — session_id for thread
        * ``slack:dm:<user_id>`` — DM session_id (meta channel_id preferred)
        * ``slack:ch:<channel_id>`` — session_id for channel
        * ``C12345`` / ``D12345`` / ``G12345`` — bare channel ID
        * ``C12345:1700000001.123456`` — compound channel:thread_ts

        A raw user ID (``U...``) is not a valid send target; in that case
        the routing falls back to *meta* (used by the access-control gate).
        """
        from .format import normalize_slack_thread_ts

        channel_id = ""
        thread_ts: Optional[str] = None

        if to_handle and to_handle.startswith("slack:"):
            parts = to_handle.split(":")
            kind = parts[1] if len(parts) >= 2 else ""
            if kind == "thread" and len(parts) >= 4:
                channel_id = parts[2]
                thread_ts = normalize_slack_thread_ts(
                    ":".join(parts[3:]),
                )
            elif kind == "dm" and len(parts) >= 3:
                # Prefer the DM channel ID stored in meta if available;
                # otherwise fall back to the user ID (Slack accepts it).
                channel_id = meta.get("slack_channel_id") or parts[2]
            elif kind == "ch" and len(parts) >= 3:
                channel_id = parts[2]
        elif to_handle and ":" in to_handle:
            parts = to_handle.split(":", 1)
            channel_id = parts[0]
            thread_ts = normalize_slack_thread_ts(parts[1])
        elif to_handle and to_handle[0] in ("C", "D", "G"):
            channel_id = to_handle
            thread_ts = normalize_slack_thread_ts(
                meta.get("slack_thread_ts") or "",
            )

        if not channel_id:
            channel_id = meta.get("slack_channel_id") or ""
            thread_ts = normalize_slack_thread_ts(
                meta.get("slack_thread_ts") or "",
            )

        return channel_id, thread_ts

    async def close(self) -> None:
        """Close the internal aiohttp session if open."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
