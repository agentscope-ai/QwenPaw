# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Slack outbound message sender.

Handles text, image, and file delivery through the Slack Web API.
Text messages are formatted as mrkdwn and automatically split at
the 30,000-character limit.  Image and file uploads use Slack's
``files.uploadV2`` (for simple cases) or the 3-step external upload
flow (``files_getUploadURLExternal`` → HTTP POST →
``files_completeUploadExternal``) when a local file path is provided.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import unquote, urlparse

import aiohttp

from .constants import (
    SLACK_TEXT_LIMIT,
)
from .format import chunk_slack_text, markdown_to_slack_mrkdwn
from .utils import SlackDeliveryError, is_slack_host, with_retry
from qwenpaw.app.channels.utils import materialize_data_url

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient
    from .platform import SlackPlatform

logger = logging.getLogger(__name__)


def _part_value(part, key, default=None):
    return (
        part.get(key, default)
        if isinstance(part, dict)
        else getattr(part, key, default)
    )


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

    def __init__(self, platform: "SlackPlatform"):
        self._platform = platform
        self._per_route_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._per_route_locks_max: int = 1024
        self._route_users = {}
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
        entry = self._route_users.setdefault(route_key, 0)
        self._route_users[route_key] = entry + 1
        self._per_route_locks.move_to_end(route_key)
        try:
            async with lock:
                return await self._send_content_parts_impl(
                    to_handle,
                    content_parts,
                    meta,
                )
        finally:
            self._route_users[route_key] -= 1
            for key in tuple(self._per_route_locks):
                if len(self._per_route_locks) <= self._per_route_locks_max:
                    break
                if not self._route_users[key]:
                    self._per_route_locks.pop(key)
                    self._route_users.pop(key)

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
            pt = _part_value(p, "type")
            if pt == "text":
                if _part_value(p, "text"):
                    text_parts.append(_part_value(p, "text"))
            elif pt == "refusal":
                if _part_value(p, "refusal"):
                    text_parts.append(_part_value(p, "refusal"))
            else:
                media_parts.append(p)

        client = await self._platform.get_client()
        last_ts: Optional[str] = None

        # Send text first, then media
        if text_parts:
            body = "\n".join(text_parts)
            prefix = self._platform.bot_prefix or ""
            if prefix:
                body = f"{prefix}\n{body}"
            last_ts = await self._send_text(
                client,
                channel_id,
                body,
                thread_ts=thread_ts,
            )

        for mp in media_parts:
            try:
                delivered = await self._send_media(
                    client,
                    channel_id,
                    mp,
                    thread_ts=thread_ts,
                )
            except SlackDeliveryError as exc:
                if last_ts and not exc.side_effect_possible:
                    raise SlackDeliveryError(
                        exc.reason_code,
                        side_effect_possible=True,
                    ) from exc
                raise
            last_ts = delivered or last_ts

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

        Each chunk is sent via ``chat_postMessage``. Only a definite rate
        limit rejection is retried; uncertain effects remain unknown.
        """
        if not text.strip():
            return None

        mrkdwn = markdown_to_slack_mrkdwn(text)
        chunks = chunk_slack_text(mrkdwn, SLACK_TEXT_LIMIT)
        last_ts: Optional[str] = None
        for chunk in chunks:
            try:
                resp = await self._platform.effect_call(
                    client.chat_postMessage,
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=chunk,
                    mrkdwn=True,
                )
                if not resp.get("ts"):
                    raise SlackDeliveryError(
                        "SLACK_RESULT_UNKNOWN",
                        side_effect_possible=True,
                    )
                last_ts = resp["ts"]
            except SlackDeliveryError as exc:
                if last_ts and not exc.side_effect_possible:
                    raise SlackDeliveryError(
                        exc.reason_code,
                        side_effect_possible=True,
                    ) from exc
                raise
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
        pt = _part_value(part, "type", None)

        if pt == "image":
            return await self._send_image(
                client,
                channel_id,
                part,
                thread_ts=thread_ts,
            )
        if pt in ("file", "audio", "video"):
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
        part: Any,
        *,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Upload an image via ``files.uploadV2``."""
        url: Optional[str] = _part_value(part, "image_url", None)
        default_name = (
            "image" if url and url.startswith("data:") else "image.png"
        )
        filename = _part_value(part, "filename", None) or default_name

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
            _part_value(part, "file_url", None)
            or _part_value(part, "data", None)
            or _part_value(part, "video_url", None)
        )
        filename = _part_value(part, "filename", None)
        if not filename and url and not url.startswith("data:"):
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
        if url.startswith("data:"):
            async with materialize_data_url(
                url,
                self._platform.media_dir,
                filename_hint=filename,
            ) as media:
                if media is None:
                    return None
                return await self._upload_file_external(
                    client,
                    channel_id,
                    media.path,
                    media.filename or filename,
                    title=(
                        (media.filename or filename)
                        if title == filename
                        else title
                    ),
                    thread_ts=thread_ts,
                )

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

        self._platform.authorize_path(filepath)
        upload_resp = await with_retry(
            client.files_getUploadURLExternal,
            filename=filename,
            length=file_size,
        )
        upload_url = upload_resp.get("upload_url")
        file_id = upload_resp.get("file_id")
        if not upload_resp.get("ok") or not upload_url or not file_id:
            raise SlackDeliveryError("SLACK_UPLOAD_REJECTED")
        if not is_slack_host(upload_url) or urlparse(
            upload_url,
        ).scheme not in {"http", "https"}:
            raise SlackDeliveryError("SLACK_UPLOAD_URL_REJECTED")
        session = await self._get_http_session()
        data = await asyncio.to_thread(Path(filepath).read_bytes)
        post_kwargs = {
            "data": data,
            "timeout": aiohttp.ClientTimeout(30),
            "allow_redirects": False,
            "proxy": self._platform.proxy_url or "",
        }
        try:
            async with session.post(upload_url, **post_kwargs) as response:
                if response.status >= 400:
                    raise SlackDeliveryError(
                        "SLACK_UPLOAD_REJECTED",
                        side_effect_possible=response.status >= 500,
                    )
                if response.status >= 300:
                    raise SlackDeliveryError("SLACK_UPLOAD_REDIRECT_REJECTED")
        except (SlackDeliveryError, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise SlackDeliveryError(
                "SLACK_UPLOAD_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        complete = await self._platform.effect_call(
            client.files_completeUploadExternal,
            files=[{"id": file_id, "title": title or filename}],
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        if not complete.get("ok"):
            raise SlackDeliveryError("SLACK_UPLOAD_REJECTED")
        return file_id

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
        """Download an allowed URL, then upload its file via files.uploadV2."""
        if not _is_slack_ssrf_allowed(url):
            logger.warning("slack send: SSRF blocked %s", url[:120])
            return None
        path = await self._platform.download_file(url, filename)
        if not path:
            raise SlackDeliveryError("SLACK_MEDIA_DOWNLOAD_FAILED")
        try:
            resp = await self._platform.effect_call(
                client.files_upload_v2,
                channel=channel_id,
                file=path,
                filename=filename,
                title=title or filename,
                thread_ts=thread_ts,
            )
        finally:
            Path(path).unlink(missing_ok=True)
        file_id = resp.get("file", {}).get("id")
        if not file_id:
            raise SlackDeliveryError(
                "SLACK_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        return file_id

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
