# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""OneBot v11 Channel.

Reverse WebSocket server for NapCat, go-cqhttp, Lagrange, or any
OneBot v11 implementation.  Listens on a configurable port;
the OneBot client connects as a WebSocket client.

Message flow:
  NapCat → reverse WS → parse OneBot segments → content_parts → process
  process → content_parts → OneBot segments → reverse WS → NapCat
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiohttp
from aiohttp import web

from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

from ....config.config import OneBotConfig as OneBotChannelConfig
from ....utils.http import is_loopback_host, probe_host_for_bind_host
from ..renderer import ChannelDisplayConfig
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from ..utils import file_url_to_local_path, split_text

logger = logging.getLogger(__name__)

# Hard cap on concurrently-tracked event handlers (flood protection).
_EVENT_TASK_HARD_CAP = 500
_DEFAULT_MEDIA_BASE64_MAX_MB = 10
_DEFAULT_WS_HOST = "127.0.0.1"
# OneBot v11 defines the "Bearer" scheme; "Token" is an ecosystem
# convention popularised by NoneBot.  Matching is case-insensitive per
# RFC 7235.
_AUTH_SCHEMES = frozenset({"bearer", "token"})
_CODE_FENCE_RE = re.compile(r"^[ \t]{0,3}(?P<mark>`{3,}|~{3,})")
_MARKDOWN_LINK_RE = re.compile(
    r"\[(?P<label>[^\]\n]+)\]"
    r"\((?P<url>https?://(?:[^\s()]|\([^\s()]*\))+)\)",
)
_WRAPPED_URL_RE = re.compile(
    r"(?P<mark>\*\*|__)(?P<url>https?://\S+?)(?P=mark)",
)


_CQ_UNESCAPE_REPLACEMENTS = (
    ("&#44;", ","),
    ("&#91;", "["),
    ("&#93;", "]"),
    ("&#38;", "&"),
    ("&amp;", "&"),
)


def _unescape_cq_value(value: str) -> str:
    """Decode OneBot CQ-code escaping without applying generic HTML rules."""
    for escaped, decoded in _CQ_UNESCAPE_REPLACEMENTS:
        value = value.replace(escaped, decoded)
    return value


def _clean_links(text: str) -> str:
    """Convert supported Markdown links to readable plain text."""
    text = _MARKDOWN_LINK_RE.sub(
        lambda match: f"{match.group('label')}: {match.group('url')}",
        text,
    )
    return _WRAPPED_URL_RE.sub(lambda match: match.group("url"), text)


def _clean_inline_text(text: str) -> str:
    """Clean links outside inline code spans."""
    result: list[str] = []
    cursor = 0
    while cursor < len(text):
        opening = text.find("`", cursor)
        if opening < 0:
            result.append(_clean_links(text[cursor:]))
            break

        result.append(_clean_links(text[cursor:opening]))
        run_end = opening
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        marker = text[opening:run_end]
        closing = text.find(marker, run_end)
        if closing < 0:
            result.append(text[opening:])
            break

        closing_end = closing + len(marker)
        result.append(text[opening:closing_end])
        cursor = closing_end
    return "".join(result)


def _clean_onebot_plain_text(text: str) -> str:
    """Clean link formatting for OneBot/QQ plain-text delivery.

    OneBot text segments are rendered by QQ as plain text. Keep links as bare
    URLs so the client can auto-link them without changing non-link markup.
    """
    if not text:
        return text

    result: list[str] = []
    outside_fence: list[str] = []
    fence_mark = ""

    def _flush_outside_fence() -> None:
        if outside_fence:
            result.append(_clean_inline_text("".join(outside_fence)))
            outside_fence.clear()

    for line in text.splitlines(keepends=True):
        match = _CODE_FENCE_RE.match(line)
        if fence_mark:
            result.append(line)
            if (
                match
                and match.group("mark")[0] == fence_mark[0]
                and len(
                    match.group("mark"),
                )
                >= len(fence_mark)
            ):
                fence_mark = ""
            continue
        if match:
            _flush_outside_fence()
            fence_mark = match.group("mark")
            result.append(line)
            continue
        outside_fence.append(line)

    _flush_outside_fence()
    return "".join(result)


def _local_path_from_media_ref(ref: str) -> Path | None:
    """Resolve a local filesystem path from a media reference if possible."""
    path_text = file_url_to_local_path(ref)
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        if path.is_file():
            return path
    except OSError:
        return None
    return None


def _local_media_base64_ref(
    ref: str,
    path: Path,
    media_base64_max_bytes: int,
) -> str:
    """Convert a local OneBot media file to base64 when safe."""
    try:
        size = path.stat().st_size
        if size > media_base64_max_bytes:
            logger.warning(
                "onebot: local media file %s is %s bytes, exceeds "
                "media_base64_max_bytes=%s; sending path instead",
                path,
                size,
                media_base64_max_bytes,
            )
            return ref
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        logger.warning("onebot: failed to read local media file %s", path)
        return ref
    return "base64://" + data


def _normalize_media_ref_sync(
    ref: str,
    *,
    media_base64: bool = False,
    media_base64_max_bytes: int,
) -> str:
    """Normalize media references for OneBot clients."""
    if not ref or ref.startswith("base64://"):
        return ref
    if ref.startswith("data:") and ";base64," in ref:
        return "base64://" + ref.split(";base64,", 1)[1]

    path = _local_path_from_media_ref(ref) if media_base64 else None
    if path is None:
        return ref
    return _local_media_base64_ref(ref, path, media_base64_max_bytes)


async def _normalize_media_ref(
    ref: str,
    *,
    media_base64: bool = False,
    media_base64_max_bytes: int,
) -> str:
    """Normalize a media reference without blocking the event loop."""
    if not media_base64 or ref.startswith(("base64://", "data:")):
        return _normalize_media_ref_sync(
            ref,
            media_base64=media_base64,
            media_base64_max_bytes=media_base64_max_bytes,
        )
    return await asyncio.to_thread(
        _normalize_media_ref_sync,
        ref,
        media_base64=media_base64,
        media_base64_max_bytes=media_base64_max_bytes,
    )


def _extract_auth_token(auth_header: str) -> str:
    """Extract the token from an ``Authorization`` header value.

    Returns an empty string when the scheme is unsupported or the header
    carries no token.
    """
    scheme, _, token = auth_header.strip().partition(" ")
    if scheme.lower() not in _AUTH_SCHEMES:
        return ""
    return token.strip()


def _tokens_match(provided: str, expected: str) -> bool:
    """Compare two access tokens in constant time."""
    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _log_remote(request: web.Request) -> str:
    """Render the peer address as a single-line log field.

    ``request.remote`` is the socket peer today, but aiohttp allows it to
    be overridden via ``clone(remote=...)``, which a forwarded-header
    middleware would do with client-controlled input.  Dropping newlines
    keeps one rejection from ever becoming several log records.
    """
    remote = request.remote or "unknown"
    return remote.replace("\r", "").replace("\n", "")


class OneBotChannel(BaseChannel):
    """OneBot v11 channel via reverse WebSocket.

    Acts as a WebSocket server; NapCat (or compatible) connects
    as a client to ``ws://<host>:<port>/ws``.

    The server binds loopback by default.  When bound to a
    network-reachable address, ``access_token`` becomes mandatory and
    every connection is rejected until it is set.
    """

    channel = "onebot"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        ws_host: str = _DEFAULT_WS_HOST,
        ws_port: int = 6199,
        access_token: str = "",
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        no_text_debounce: bool = True,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        share_session_in_group: bool = False,
        access_control_dm: bool = False,
        access_control_group: bool = False,
        media_base64: bool = False,
        media_base64_max_mb: int = _DEFAULT_MEDIA_BASE64_MAX_MB,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            display_config=display_config,
            no_text_debounce=no_text_debounce,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        # An empty host would make aiohttp bind every interface, so treat
        # it as "unset" and fall back to the loopback default.  Brackets
        # are URL notation for IPv6 literals and make getaddrinfo fail,
        # so drop them the way ``is_loopback_host`` does.
        self._ws_host = ws_host.strip().strip("[]") or _DEFAULT_WS_HOST
        self._ws_port = ws_port
        # A request token is stripped before comparison, so a token made
        # only of whitespace could never match.  Treat it as unset to get
        # the actionable "access_token is empty" rejection instead.
        self._access_token = access_token.strip()
        # A network-reachable listener must authenticate its clients.
        self._auth_required = not is_loopback_host(self._ws_host)
        self._share_session_in_group = share_session_in_group
        self._media_base64 = media_base64
        max_mb = (
            media_base64_max_mb
            if media_base64_max_mb > 0
            else _DEFAULT_MEDIA_BASE64_MAX_MB
        )
        self._media_base64_max_bytes = max_mb * 1_000_000

        # WebSocket server state
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._connections: Set[web.WebSocketResponse] = set()

        # Echo-based API call tracking
        self._pending_calls: Dict[str, asyncio.Future] = {}

        # Fire-and-forget event handlers, tracked so stop() can cancel them.
        self._event_tasks: Set[asyncio.Task] = set()

        # Bot self ID (populated on first meta_event/lifecycle)
        self._self_id: Optional[int] = None

        # Watchdog for auto-restart
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_interval: float = 10.0  # seconds
        self._stopping: bool = False

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "OneBotChannel":
        return cls(
            process=process,
            enabled=os.getenv("ONEBOT_CHANNEL_ENABLED", "0") == "1",
            ws_host=os.getenv("ONEBOT_WS_HOST", _DEFAULT_WS_HOST),
            ws_port=int(os.getenv("ONEBOT_WS_PORT", "6199")),
            access_token=os.getenv("ONEBOT_ACCESS_TOKEN", ""),
            bot_prefix=os.getenv("ONEBOT_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("ONEBOT_DM_POLICY", "open"),
            group_policy=os.getenv("ONEBOT_GROUP_POLICY", "open"),
            allow_from=(
                os.getenv("ONEBOT_ALLOW_FROM", "").split(",")
                if os.getenv("ONEBOT_ALLOW_FROM")
                else []
            ),
            deny_message=os.getenv("ONEBOT_DENY_MESSAGE", ""),
            require_mention=(os.getenv("ONEBOT_REQUIRE_MENTION", "0") == "1"),
            share_session_in_group=(
                os.getenv("ONEBOT_SHARE_SESSION_IN_GROUP", "0") == "1"
            ),
            media_base64=(os.getenv("ONEBOT_MEDIA_BASE64", "0") == "1"),
            media_base64_max_mb=int(
                os.getenv(
                    "ONEBOT_MEDIA_BASE64_MAX_MB",
                    str(_DEFAULT_MEDIA_BASE64_MAX_MB),
                ),
            ),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: OneBotChannelConfig,
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        no_text_debounce: bool = True,
    ) -> "OneBotChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            ws_host=config.ws_host or _DEFAULT_WS_HOST,
            ws_port=config.ws_port or 6199,
            access_token=config.access_token or "",
            bot_prefix=config.bot_prefix or "",
            on_reply_sent=on_reply_sent,
            display_config=display_config
            or ChannelDisplayConfig.from_config(config),
            no_text_debounce=no_text_debounce,
            dm_policy=config.dm_policy,
            group_policy=config.group_policy,
            allow_from=config.allow_from,
            deny_message=config.deny_message,
            require_mention=config.require_mention,
            share_session_in_group=getattr(
                config,
                "share_session_in_group",
                False,
            ),
            access_control_dm=bool(
                getattr(config, "access_control_dm", False),
            ),
            access_control_group=bool(
                getattr(config, "access_control_group", False),
            ),
            media_base64=config.media_base64,
            media_base64_max_mb=config.media_base64_max_mb,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def health_check(self) -> Dict[str, Any]:
        """Check OneBot reverse WebSocket server status."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "OneBot channel is disabled.",
            }
        if self._site is None:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "WebSocket server is not running.",
            }
        connection_count = len(self._connections)
        if connection_count == 0:
            return {
                "channel": self.channel,
                "status": "healthy",
                "detail": (
                    f"WebSocket server listening on "
                    f"{self._ws_host}:{self._ws_port}, "
                    f"no active connections."
                ),
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": (
                f"WebSocket server listening on "
                f"{self._ws_host}:{self._ws_port}, "
                f"{connection_count} active connection(s)."
            ),
        }

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("onebot channel disabled")
            return
        self._stopping = False
        await self._start_ws_server()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stopping = True
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        await self._stop_ws_server()
        # Cancel any in-flight event handlers.
        for task in list(self._event_tasks):
            task.cancel()
        if self._event_tasks:
            await asyncio.gather(*self._event_tasks, return_exceptions=True)
            self._event_tasks.clear()

    async def _start_ws_server(self) -> None:
        """Create and start the aiohttp WebSocket server.

        On port conflict (e.g. during reload), defers to watchdog
        for automatic recovery instead of blocking.
        """
        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_ws_connection)
        self._app.router.add_get("/ws/", self._handle_ws_connection)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._ws_host,
            self._ws_port,
        )
        try:
            await self._site.start()
            logger.info(
                "onebot: reverse WS server listening on %s:%s",
                self._ws_host,
                self._ws_port,
            )
        except OSError:
            logger.warning(
                "onebot: port %s:%s in use, watchdog will retry "
                "once the old instance releases it",
                self._ws_host,
                self._ws_port,
            )
            # Clean up the failed attempt so watchdog sees
            # _site as None and triggers a restart.
            self._site = None
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
            self._app = None

    async def _stop_ws_server(self) -> None:
        """Tear down the WebSocket server and clean up connections."""
        for ws in list(self._connections):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()
        if self._site:
            try:
                await self._site.stop()
            except Exception:
                pass
            self._site = None
        if self._runner:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
        self._app = None
        # Cancel pending API futures
        for fut in self._pending_calls.values():
            if not fut.done():
                fut.cancel()
        self._pending_calls.clear()

    async def _watchdog_loop(self) -> None:
        """Periodically check server health; restart if not listening."""
        while not self._stopping:
            await asyncio.sleep(self._watchdog_interval)
            if self._stopping:
                break
            if not await self._is_server_healthy():
                logger.warning(
                    "onebot: watchdog detected server not healthy, "
                    "restarting...",
                )
                try:
                    await self._stop_ws_server()
                    await self._start_ws_server()
                    logger.info("onebot: watchdog restarted server OK")
                except Exception:
                    logger.exception(
                        "onebot: watchdog failed to restart server, "
                        "will retry in %ss",
                        self._watchdog_interval,
                    )

    def _get_listen_port(self) -> int:
        """Return the actual port the server is listening on.

        When ``ws_port=0`` the OS assigns a random port; we read it
        from the site's underlying sockets.
        """
        if self._site is None:
            return self._ws_port
        server = getattr(self._site, "_server", None)
        if server is not None:
            for sock in server.sockets or []:
                return sock.getsockname()[1]
        return self._ws_port

    async def _is_server_healthy(self) -> bool:
        """Check if the WS server is actually accepting connections.

        Returns True if the TCP port is reachable, False otherwise.
        This catches cases where ``_site`` is not None but the
        underlying socket has stopped accepting connections.
        """
        if self._site is None:
            return False
        probe_host = probe_host_for_bind_host(self._ws_host)
        probe_port = self._get_listen_port()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(probe_host, probe_port),
                timeout=3.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    # ------------------------------------------------------------------
    # WebSocket connection handling
    # ------------------------------------------------------------------

    def _token_authorized(self, request: web.Request) -> bool:
        """Check the ``Authorization`` header against the access token.

        Only the header is accepted: the OneBot v11 reverse WebSocket
        spec defines no query-parameter fallback, and a token placed in a
        query string leaks into proxy and container access logs.
        """
        provided = _extract_auth_token(
            request.headers.get("Authorization", ""),
        )
        if not provided:
            return False
        return _tokens_match(provided, self._access_token)

    async def _handle_ws_connection(
        self,
        request: web.Request,
    ) -> web.WebSocketResponse:
        """Handle incoming WebSocket connection from NapCat."""
        # A network-reachable listener without a token would accept
        # events from anyone, so refuse every connection instead.
        if self._auth_required and not self._access_token:
            logger.error(
                "onebot: rejected connection from %s: ws_host=%s is not a "
                "loopback address and access_token is empty. Set "
                "access_token, or bind ws_host to 127.0.0.1.",
                _log_remote(request),
                self._ws_host,
            )
            return web.Response(status=401, text="Unauthorized")

        if self._access_token and not self._token_authorized(request):
            logger.warning(
                "onebot: rejected connection from %s (bad token)",
                _log_remote(request),
            )
            if "access_token" in request.query:
                logger.warning(
                    "onebot: access_token was supplied as a query "
                    "parameter; OneBot v11 reverse WebSocket expects the "
                    "Authorization header instead (e.g. 'Bearer <token>'). "
                    "Configure the token field of the OneBot client.",
                )
            return web.Response(status=401, text="Unauthorized")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._connections.add(ws)
        logger.info(
            "onebot: client connected from %s",
            _log_remote(request),
        )

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        logger.warning(
                            "onebot: invalid JSON: %s",
                            msg.data[:200],
                        )
                        continue
                    if "echo" in data:
                        self._handle_api_response(data)
                    else:
                        # Dispatch as background task so the WS read
                        # loop stays unblocked — handlers can freely
                        # await _call_api (e.g. resolve file URLs).
                        self._spawn_event_task(self._handle_event(data))
                elif msg.type in (
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    break
        except Exception:
            logger.exception("onebot: WS connection error")
        finally:
            self._connections.discard(ws)
            logger.info(
                "onebot: client disconnected from %s",
                _log_remote(request),
            )

        return ws

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    def _spawn_event_task(self, coro) -> None:
        """Schedule a tracked background event handler with a hard cap.

        Under a message flood the cap prevents unbounded task accumulation;
        excess events are dropped with a warning. Tracked tasks are cancelled
        on stop().

        Note: we must not block the WS read loop here — ``_call_api`` awaits
        echo responses that arrive through the same loop, so a blocking
        semaphore would deadlock. A drop-on-cap valve is used instead.
        """
        if len(self._event_tasks) >= _EVENT_TASK_HARD_CAP:
            logger.warning(
                "onebot: event task cap (%d) reached — dropping event",
                _EVENT_TASK_HARD_CAP,
            )
            coro.close()
            return
        task = asyncio.create_task(coro)
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

    async def _handle_event(self, data: Dict[str, Any]) -> None:
        """Dispatch an OneBot v11 event."""
        post_type = data.get("post_type")
        if post_type == "meta_event":
            self._handle_meta_event(data)
        elif post_type == "message":
            await self._handle_message_event(data)
        # notice / request events: ignored for now

    def _handle_meta_event(self, data: Dict[str, Any]) -> None:
        """Handle lifecycle and heartbeat meta events."""
        meta_type = data.get("meta_event_type")
        if meta_type == "lifecycle":
            self._self_id = data.get("self_id")
            sub = data.get("sub_type", "")
            logger.info(
                "onebot: lifecycle %s, self_id=%s",
                sub,
                self._self_id,
            )
        elif meta_type == "heartbeat":
            logger.debug("onebot: heartbeat from self_id=%s", self._self_id)

    async def _handle_message_event(self, data: Dict[str, Any]) -> None:
        """Handle a message event from OneBot v11."""
        message_type = str(data.get("message_type") or "private")
        user_id = str(data.get("user_id", ""))
        group_id = str(data.get("group_id", ""))
        message_id = str(data.get("message_id", ""))
        event_self_id = data.get("self_id")
        if event_self_id is not None:
            self._self_id = event_self_id
        segments = self._normalize_onebot_segments(data.get("message", []))

        # Track bot mention and quoted message before any remote I/O.
        content_parts, bot_mentioned = self._parse_message_segments(segments)
        reply_message_id = self._reply_message_id(segments)
        if not content_parts and not reply_message_id:
            return

        sender = data.get("sender", {})
        sender_name = sender.get("card") or sender.get("nickname") or user_id

        is_group = message_type == "group"
        meta: Dict[str, Any] = {
            "message_type": message_type,
            "message_id": message_id,
            "sender_id": user_id,
            "user_name": sender_name,
            "group_id": group_id if is_group else "",
            "is_group": is_group,
            "bot_mentioned": bot_mentioned,
        }

        # Mention check (group messages may require @bot). Keep all
        # OneBot API calls after this gate to avoid I/O for ignored messages.
        if not self._check_group_mention(is_group, meta):
            return

        if reply_message_id:
            quoted_segments = await self._get_quoted_message_segments(
                reply_message_id,
            )
            quoted_parts, _ = self._parse_message_segments(quoted_segments)
            quoted_parts = await self._resolve_file_urls(
                quoted_parts,
                message_type,
                self._event_with_segments(data, quoted_segments),
            )
            content_parts = await self._resolve_file_urls(
                content_parts,
                message_type,
                self._event_with_segments(data, segments),
            )
            content_parts = self._with_quoted_context(
                quoted_parts,
                content_parts,
            )
            logger.info(
                "onebot: quoted message id=%s segments=%s parts=%s preview=%r",
                reply_message_id,
                [segment.get("type") for segment in quoted_segments],
                [getattr(part, "type", None) for part in quoted_parts],
                self._content_part_preview(quoted_parts),
            )
        else:
            content_parts = await self._resolve_file_urls(
                content_parts,
                message_type,
                self._event_with_segments(data, segments),
            )
        if not content_parts:
            return

        native = {
            "channel_id": self.channel,
            "sender_id": user_id,
            "content_parts": content_parts,
            "meta": meta,
        }

        request = self.build_agent_request_from_native(native)
        request.channel_meta = meta
        request.acl_sender_id = user_id

        logger.info(
            "onebot recv %s from=%s%s text=%r",
            message_type,
            sender_name,
            f" group={group_id}" if is_group else "",
            self._preview_text(content_parts),
        )

        if self._enqueue is not None:
            self._enqueue(request)

    # ------------------------------------------------------------------
    # Message segment parsing
    # ------------------------------------------------------------------

    def _parse_message_segments(
        self,
        segments: List[Dict[str, Any]],
    ) -> tuple[list, bool]:
        """Parse OneBot v11 message segments to content_parts.

        Returns:
            (content_parts, bot_mentioned)
        """
        parts: list = []
        bot_mentioned = False

        for seg in segments:
            seg_type = seg.get("type", "")
            seg_data = seg.get("data", {})

            if seg_type == "text":
                text = (seg_data.get("text") or "").strip()
                if text:
                    parts.append(
                        TextContent(type=ContentType.TEXT, text=text),
                    )

            elif seg_type == "image":
                url = seg_data.get("url") or seg_data.get("file", "")
                if url:
                    parts.append(
                        ImageContent(
                            type=ContentType.IMAGE,
                            image_url=url,
                        ),
                    )

            elif seg_type == "record":
                url = seg_data.get("url") or seg_data.get("file", "")
                if url:
                    parts.append(
                        AudioContent(type=ContentType.AUDIO, data=url),
                    )

            elif seg_type == "video":
                url = seg_data.get("url") or seg_data.get("file", "")
                if url:
                    parts.append(
                        VideoContent(
                            type=ContentType.VIDEO,
                            video_url=url,
                        ),
                    )

            elif seg_type == "file":
                url = seg_data.get("url") or seg_data.get("file", "")
                name = seg_data.get("name") or seg_data.get("file", "file")
                if url or seg_data.get("file_id"):
                    parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            file_url=url or name,
                            filename=name,
                        ),
                    )

            elif seg_type == "at":
                qq = str(seg_data.get("qq", ""))
                if self._self_id and qq == str(self._self_id):
                    bot_mentioned = True

            # reply, face, forward, etc. — ignored for now

        return parts, bot_mentioned

    @staticmethod
    def _normalize_onebot_segments(raw_message: Any) -> list[dict]:
        """Normalize OneBot array or CQ-code message into segment dicts."""
        if isinstance(raw_message, list):
            return [seg for seg in raw_message if isinstance(seg, dict)]
        if not isinstance(raw_message, str):
            return []

        segments: list[dict] = []
        pos = 0
        for match in re.finditer(
            r"\[CQ:(?P<type>\w+),(?P<data>[^\]]*)\]",
            raw_message,
        ):
            if match.start() > pos:
                text = raw_message[pos : match.start()].strip()
                if text:
                    segments.append({"type": "text", "data": {"text": text}})
            seg_data: dict[str, str] = {}
            for item in match.group("data").split(","):
                key, sep, value = item.partition("=")
                if sep and key:
                    seg_data[key] = _unescape_cq_value(value)
            segments.append({"type": match.group("type"), "data": seg_data})
            pos = match.end()
        if pos < len(raw_message):
            text = raw_message[pos:].strip()
            if text:
                segments.append({"type": "text", "data": {"text": text}})
        if not segments and raw_message.strip():
            segments.append(
                {"type": "text", "data": {"text": raw_message.strip()}},
            )
        return segments

    @staticmethod
    def _segment_types(segments: list[dict]) -> list[str]:
        return [str(seg.get("type", "")) for seg in segments]

    @staticmethod
    def _message_preview(value: Any) -> str:
        if isinstance(value, str):
            return value[:200]
        if not isinstance(value, list):
            return ""

        bounded: list[dict[str, Any]] = []
        for segment in value[:3]:
            if not isinstance(segment, dict):
                bounded.append({"value_type": type(segment).__name__})
                continue
            preview_segment: dict[str, Any] = {
                "type": str(segment.get("type", ""))[:40],
            }
            data = segment.get("data")
            if isinstance(data, dict):
                preview_segment["data"] = {
                    str(key)[:40]: (
                        item[:80]
                        if isinstance(item, str)
                        else item
                        if isinstance(item, (bool, int, float, type(None)))
                        else f"<{type(item).__name__}>"
                    )
                    for key, item in list(data.items())[:6]
                }
            bounded.append(preview_segment)
        return json.dumps(bounded, ensure_ascii=False)[:200]

    @staticmethod
    def _text_content_parts(parts: list) -> list[str] | None:
        texts: list[str] = []
        for part in parts:
            if getattr(part, "type", None) != ContentType.TEXT:
                return None
            text = str(getattr(part, "text", "") or "").strip()
            if text:
                texts.append(text)
        return texts

    @staticmethod
    def _content_part_preview(parts: list) -> str:
        previews: list[str] = []
        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT:
                previews.append(str(getattr(part, "text", "") or "")[:120])
            else:
                previews.append(str(part_type))
        return " | ".join(previews)[:240]

    @staticmethod
    def _quoted_part_annotation(part: Any) -> str | None:
        part_type = getattr(part, "type", None)
        if part_type == ContentType.IMAGE:
            return "[Quoted image message]"
        if part_type == ContentType.AUDIO:
            return "[Quoted voice message]"
        if part_type == ContentType.VIDEO:
            return "[Quoted video message]"
        if part_type == ContentType.FILE:
            filename = getattr(part, "filename", "") or "file"
            return f"[Quoted file message: {filename}]"
        return None

    @staticmethod
    def _annotated_quoted_parts(quoted_parts: list) -> list:
        annotated: list = []
        for part in quoted_parts:
            annotation = OneBotChannel._quoted_part_annotation(part)
            if annotation:
                annotated.append(
                    TextContent(type=ContentType.TEXT, text=annotation),
                )
            annotated.append(part)
        return annotated

    @staticmethod
    def _with_quoted_context(
        quoted_parts: list,
        current_parts: list,
    ) -> list:
        """Expose quoted content with the shared simple marker format."""
        if not quoted_parts:
            return current_parts

        quoted_texts = OneBotChannel._text_content_parts(quoted_parts)
        current_texts = OneBotChannel._text_content_parts(current_parts)
        if quoted_texts is not None and current_texts is not None:
            text = "[Quoted message]\n" + "\n".join(quoted_texts)
            if current_texts:
                text += "\n\n[Current message]\n" + "\n".join(current_texts)
            return [TextContent(type=ContentType.TEXT, text=text)]

        merged: list = [
            TextContent(type=ContentType.TEXT, text="[Quoted message]"),
            *OneBotChannel._annotated_quoted_parts(quoted_parts),
        ]
        if current_parts:
            merged.append(
                TextContent(type=ContentType.TEXT, text="[Current message]"),
            )
            merged.extend(current_parts)
        return merged

    @staticmethod
    def _event_with_segments(
        event_data: Dict[str, Any],
        segments: list[dict],
    ) -> Dict[str, Any]:
        scoped_data = dict(event_data)
        scoped_data["message"] = segments
        return scoped_data

    @staticmethod
    def _reply_message_id(segments: list) -> str | None:
        """Return the directly quoted OneBot message ID, if present."""
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("type") != "reply":
                continue
            data = segment.get("data", {})
            message_id = data.get("id") if isinstance(data, dict) else None
            if message_id is not None and str(message_id):
                return str(message_id)
        return None

    async def _get_quoted_message_segments(
        self,
        message_id: str,
    ) -> list[dict]:
        """Fetch one quoted message after the current message passes gates."""
        api_message_id: str | int = message_id
        try:
            api_message_id = int(message_id)
        except ValueError:
            pass

        try:
            result = await self._call_api(
                "get_msg",
                {"message_id": api_message_id},
            )
        except Exception:
            logger.warning(
                "onebot: failed to fetch quoted message %s",
                message_id,
                exc_info=True,
            )
            return []

        data = result.get("data") if isinstance(result, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        raw_message = (
            data.get("raw_message") if isinstance(data, dict) else None
        )
        segments = self._normalize_onebot_segments(message)
        raw_segments = self._normalize_onebot_segments(raw_message)
        if (
            raw_segments
            and self._segment_types(segments) == ["text"]
            and self._segment_types(raw_segments) != ["text"]
        ):
            segments = raw_segments
        logger.info(
            "onebot: get_msg id=%s keys=%s message_type=%s "
            "raw_type=%s message_preview=%r raw_preview=%r",
            message_id,
            sorted(data.keys()) if isinstance(data, dict) else [],
            type(message).__name__,
            type(raw_message).__name__,
            self._message_preview(message),
            self._message_preview(raw_message),
        )
        if not segments:
            logger.warning(
                "onebot: quoted message %s has no segment list",
                message_id,
            )
            return []
        return segments

    async def _resolve_file_urls(
        self,
        content_parts: list,
        message_type: str,
        event_data: Dict[str, Any],
    ) -> list:
        """Resolve real download URLs for file content parts.

        NapCat's file segments only contain the filename in the ``file``
        field, not a download URL.  We call ``get_group_file_url`` or
        ``get_private_file_url`` to obtain the real URL.
        """
        resolved = []
        file_segments = [
            segment
            for segment in event_data.get("message", [])
            if isinstance(segment, dict) and segment.get("type") == "file"
        ]
        file_segment_index = 0
        for part in content_parts:
            if getattr(part, "type", None) != ContentType.FILE:
                resolved.append(part)
                continue

            source_segment = (
                file_segments[file_segment_index]
                if file_segment_index < len(file_segments)
                else {}
            )
            file_segment_index += 1
            source_data = source_segment.get("data", {})
            file_id = (
                source_data.get("file_id", "")
                if isinstance(source_data, dict)
                else ""
            )
            file_url = getattr(part, "file_url", "") or ""
            # Already a valid URL — keep as-is
            if file_url.startswith(("http://", "https://", "file://")):
                resolved.append(part)
                continue

            if not file_id:
                # No file_id available — keep original (will likely fail
                # downstream but at least the filename is preserved)
                resolved.append(part)
                continue

            # Call OneBot API to resolve the real download URL
            if message_type == "group":
                group_id = event_data.get("group_id", "")
                result = await self._call_api(
                    "get_group_file_url",
                    {"group_id": int(group_id), "file_id": file_id},
                )
            else:
                result = await self._call_api(
                    "get_private_file_url",
                    {"file_id": file_id},
                )

            real_url = (result.get("data") or {}).get("url", "")
            if real_url:
                resolved.append(
                    FileContent(
                        type=ContentType.FILE,
                        file_url=real_url,
                        filename=getattr(part, "filename", "file"),
                    ),
                )
                logger.info(
                    "onebot: resolved file URL for %s",
                    getattr(part, "filename", "file"),
                )
            else:
                logger.warning(
                    "onebot: failed to resolve file URL for file_id=%s",
                    file_id,
                )
                resolved.append(part)

        return resolved

    # ------------------------------------------------------------------
    # Build AgentRequest
    # ------------------------------------------------------------------

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        return self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )

    # ------------------------------------------------------------------
    # Session / routing
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = channel_meta or {}
        is_group = meta.get("is_group", False)
        group_id = meta.get("group_id", "")
        if is_group:
            if self._share_session_in_group:
                return f"onebot:g:{group_id}"
            return f"onebot:{group_id}:{sender_id}"
        return f"onebot:{sender_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        meta = getattr(request, "channel_meta", {}) or {}
        if meta.get("is_group"):
            return f"group:{meta.get('group_id', '')}"
        return str(
            meta.get("sender_id") or getattr(request, "user_id", "") or "",
        )

    # ------------------------------------------------------------------
    # Sending messages (To NapCat)
    # ------------------------------------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled or not text.strip():
            return

        text = await asyncio.to_thread(_clean_onebot_plain_text, text)
        if not text.strip():
            return

        for chunk in split_text(text):
            segments = [{"type": "text", "data": {"text": chunk}}]
            await self._send_segments(to_handle, segments, meta)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text and media in their original order."""
        if not self.enabled:
            return

        text_parts: List[str] = []
        prefix = (meta or {}).get("bot_prefix", "") or ""
        prefix_pending = bool(prefix)

        async def _flush_text() -> None:
            nonlocal prefix_pending
            if not text_parts:
                return
            body = "\n".join(text_parts).strip()
            text_parts.clear()
            if not body:
                return
            if prefix_pending:
                body = f"{prefix}  {body}"
                prefix_pending = False
            await self.send(to_handle, body, meta)

        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT and getattr(part, "text", None):
                text_parts.append(part.text or "")
            elif part_type == ContentType.REFUSAL and getattr(
                part,
                "refusal",
                None,
            ):
                text_parts.append(part.refusal or "")
            elif part_type in (
                ContentType.IMAGE,
                ContentType.VIDEO,
                ContentType.AUDIO,
                ContentType.FILE,
            ):
                await _flush_text()
                await self.send_media(to_handle, part, meta)

        await _flush_text()

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a media part via OneBot API.

        Supports image, audio (record), and video segments.
        """
        t = getattr(part, "type", None)

        if t == ContentType.IMAGE:
            url = getattr(part, "image_url", "")
            if not url:
                return
            url = await self._apply_media_ref_policy(str(url))
            segments = [{"type": "image", "data": {"file": url}}]
        elif t == ContentType.AUDIO:
            url = getattr(part, "data", "")
            if not url:
                return
            url = await self._apply_media_ref_policy(str(url))
            segments = [{"type": "record", "data": {"file": url}}]
        elif t == ContentType.VIDEO:
            url = getattr(part, "video_url", "")
            if not url:
                return
            url = await self._apply_media_ref_policy(str(url))
            segments = [{"type": "video", "data": {"file": url}}]
        elif t == ContentType.FILE:
            url = getattr(part, "file_url", "") or getattr(
                part,
                "file_id",
                "",
            )
            name = getattr(part, "filename", "") or "file"
            if not url:
                return
            url = await self._apply_media_ref_policy(str(url))
            await self._send_file(to_handle, url, name, meta)
            return
        else:
            return

        await self._send_segments(to_handle, segments, meta)

    async def _apply_media_ref_policy(self, ref: str) -> str:
        """Apply the configured OneBot media reference policy."""
        return await _normalize_media_ref(
            ref,
            media_base64=self._media_base64,
            media_base64_max_bytes=self._media_base64_max_bytes,
        )

    @staticmethod
    def _resolve_target(
        to_handle: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[int]]:
        """Resolve a OneBot group/private target."""
        meta = meta or {}
        is_group = meta.get("is_group", False) or to_handle.startswith(
            "group:",
        )
        if is_group:
            target = meta.get("group_id") or to_handle.removeprefix("group:")
        else:
            target = meta.get("sender_id") or to_handle
        try:
            target_id = int(target)
        except (TypeError, ValueError):
            logger.warning(
                "onebot: invalid target %r (to_handle=%r), "
                "dropping message",
                target,
                to_handle,
            )
            return is_group, None
        return is_group, target_id

    async def _send_segments(
        self,
        to_handle: str,
        segments: List[Dict[str, Any]],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send OneBot message segments to a private or group target."""
        is_group, target = self._resolve_target(to_handle, meta)
        if target is None:
            return
        if is_group:
            await self._call_api(
                "send_group_msg",
                {"group_id": target, "message": segments},
            )
            return
        await self._call_api(
            "send_private_msg",
            {"user_id": target, "message": segments},
        )

    async def _send_file(
        self,
        to_handle: str,
        file: str,
        name: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a file via NapCat upload_group_file / upload_private_file."""
        is_group, target = self._resolve_target(to_handle, meta)
        if target is None:
            return
        if is_group:
            await self._call_api(
                "upload_group_file",
                {"group_id": target, "file": file, "name": name},
            )
            return
        await self._call_api(
            "upload_private_file",
            {"user_id": target, "file": file, "name": name},
        )

    # ------------------------------------------------------------------
    # OneBot v11 API calls (echo-based RPC)
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call an OneBot v11 API action via WebSocket echo pattern."""
        if not self._connections:
            logger.warning(
                "onebot: no active connection for API call %s",
                action,
            )
            return {}

        echo = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_calls[echo] = future

        payload = json.dumps(
            {"action": action, "params": params, "echo": echo},
            ensure_ascii=False,
        )

        # Try each connection until one succeeds (handles stale connections
        # during reconnection windows).
        sent = False
        for ws in list(self._connections):
            try:
                await ws.send_str(payload)
                sent = True
                break
            except Exception:
                logger.debug(
                    "onebot: send failed on one connection, trying next",
                )
                continue
        if not sent:
            self._pending_calls.pop(echo, None)
            logger.warning("onebot: all connections failed for %s", action)
            return {}

        try:
            result = await asyncio.wait_for(future, timeout=15.0)
            retcode = result.get("retcode", -1)
            if retcode != 0:
                logger.warning(
                    "onebot API %s retcode=%s: %s",
                    action,
                    retcode,
                    result.get("msg", ""),
                )
            return result
        except asyncio.TimeoutError:
            logger.warning("onebot: API %s timeout (15s)", action)
            return {}
        finally:
            self._pending_calls.pop(echo, None)

    def _handle_api_response(self, data: Dict[str, Any]) -> None:
        """Route an API response to its pending future."""
        echo = data.get("echo")
        if echo and echo in self._pending_calls:
            fut = self._pending_calls[echo]
            if not fut.done():
                fut.set_result(data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _preview_text(content_parts: list) -> str:
        """Return a short text preview for logging."""
        for p in content_parts:
            if getattr(p, "type", None) == ContentType.TEXT:
                text = getattr(p, "text", "")
                return text[:100] if text else ""
        return "<non-text>"
