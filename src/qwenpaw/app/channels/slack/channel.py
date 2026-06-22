# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements,protected-access
"""Slack Channel — native streaming in threads, with automatic fallback.

Slack's streaming API (chat.startStream/appendStream/stopStream) requires
a thread_ts — streamed messages can only exist as thread replies. This
forces a three-tier strategy:

    thread_ts present → native AsyncChatStream (incremental rendering)
    thread_ts absent  → placeholder message → chat_update edits
    stream_mode="off" → buffer all deltas → single chat_postMessage

When native streaming fails (SlackStreamNotDeliveredError), the channel
falls back to chat_update automatically — the user still sees content,
just without the typewriter effect.

Socket Mode (WebSocket) is used instead of HTTP endpoints to avoid
needing a public URL. In groups the bot responds only to @mentions by
default; once it joins a thread, subsequent replies are auto-routed
for 24 hours. Events are deduplicated within a 5-minute window.

Connection resilience
---------------------
SDK handles WebSocket reconnection internally via ``start_async()``.
If the task exits unexpectedly, a callback schedules a restart with
exponential backoff.  Reconnection is serialised through a per-instance
lock to prevent thundering-herd restarts.

Proxy support
-------------
Both the WebClient (REST API calls) and the Socket Mode WebSocket
connection honour the ``proxy`` config field.  When ``NO_PROXY`` is
set in the environment and ``slack.com`` is excluded, the proxy is
bypassed transparently.

Sub-modules: handler.py (inbound parsing), sender.py (API calls),
streaming.py (session state), format.py (mrkdwn), utils.py (helpers).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    TextContent,
)

from slack_bolt.adapter.socket_mode.async_handler import (
    AsyncSocketModeHandler,
)
from slack_bolt.app.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from ....config.config import SlackConfig as SlackChannelConfig
from ..base import BaseChannel, ProcessHandler, OnReplySent
from .constants import (
    SLACK_RECONNECT_FACTOR,
    SLACK_RECONNECT_INITIAL_S,
    SLACK_RECONNECT_JITTER,
    SLACK_RECONNECT_MAX_ATTEMPTS,
    SLACK_RECONNECT_MAX_S,
    SLACK_TEXT_LIMIT,
)
from .format import (
    chunk_slack_text,
    markdown_to_slack_mrkdwn,
)
from .handler import SlackEventHandler
from .sender import SlackSender
from .streaming import SlackStreamManager, SlackStreamNotDeliveredError
from .utils import _resolve_slack_proxy_url, _apply_slack_proxy

logger = logging.getLogger(__name__)

# Streaming edit throttle interval (seconds)
_STREAM_EDIT_INTERVAL_S = 1.5

# Error messages that indicate a non-recoverable auth failure.
# When detected, reconnection is abandoned and the channel must be
# manually reconfigured.
_NON_RECOVERABLE_SLACK_ERRORS: frozenset[str] = frozenset(
    {
        "account_inactive",
        "invalid_auth",
        "token_revoked",
        "token_expired",
        "not_authed",
        "org_login_required",
        "team_access_not_granted",
        "missing_scope",
        "cannot_find_service",
        "invalid_token",
    },
)


def _is_non_recoverable_slack_error(error: Exception) -> bool:
    """Return *True* when *error* indicates a non-recoverable auth failure.

    These errors will not be resolved by reconnection — the token or
    app configuration must be updated manually.
    """
    msg = str(error).lower()
    return any(keyword in msg for keyword in _NON_RECOVERABLE_SLACK_ERRORS)


# ── Main channel class ──


class SlackChannel(BaseChannel):  # pylint: disable=too-many-public-methods
    """Slack channel with Socket Mode connection and native streaming.

    Parameters
    ----------
    name : str
        Human-readable channel instance name.
    manager :
        Owning :class:`ChannelManager`.
    config : SlackChannelConfig
        Channel-specific configuration (bot token, app token, proxy, etc.).
    """

    channel: str = "slack"
    config_cls = SlackChannelConfig

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_token: str,
        app_token: str,
        bot_prefix: str = "",
        proxy: str = "",
        streaming_enabled: bool = False,
        require_mention: bool = True,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        access_control_dm: bool = False,
        access_control_group: bool = False,
        dm_disabled: bool = False,
        group_disabled: bool = False,
        media_dir: str = "",
        workspace_dir: Path | None = None,
    ):
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            streaming_enabled=streaming_enabled,
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )
        self.enabled = enabled
        self.dm_disabled = dm_disabled
        self.group_disabled = group_disabled
        self.bot_token = bot_token
        self.app_token = app_token
        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and workspace_dir:
            self._media_dir = Path(workspace_dir).expanduser() / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            from ....constant import DEFAULT_MEDIA_DIR

            self._media_dir = DEFAULT_MEDIA_DIR
        self._media_dir.mkdir(parents=True, exist_ok=True)
        self.bot_prefix = bot_prefix
        self.proxy = proxy
        self.streaming_enabled = streaming_enabled
        self.require_mention = require_mention

        self._app: Optional[AsyncApp] = None
        self._client: Optional[AsyncWebClient] = None
        self._handler: Optional[AsyncSocketModeHandler] = None
        self._socket_mode_task: Optional[asyncio.Task] = None
        self._socket_reconnect_attempt = 0
        self._socket_reconnect_lock = asyncio.Lock()
        self._event_handler: Optional[SlackEventHandler] = None
        self._sender: Optional[SlackSender] = None
        self._stream_manager: Optional[SlackStreamManager] = None
        self._proxy_url: Optional[str] = None
        self._bot_user_id: str = ""
        self._bot_message_ts: Dict[str, float] = {}
        self._bot_message_ts_lock = asyncio.Lock()
        self._thread_context_cache: Dict[str, tuple[str, float]] = {}
        self._thread_context_cache_ttl: float = 60.0

    @property
    def media_dir(self) -> Path:
        """Directory for caching downloaded media files."""
        return self._media_dir

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "SlackChannel":
        allow_from_env = os.getenv("SLACK_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("SLACK_CHANNEL_ENABLED", "0") == "1",
            bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
            app_token=os.getenv("SLACK_APP_TOKEN", ""),
            bot_prefix=os.getenv("SLACK_BOT_PREFIX", ""),
            proxy=os.getenv("SLACK_PROXY", ""),
            streaming_enabled=os.getenv("SLACK_STREAMING_ENABLED", "0") == "1",
            require_mention=os.getenv("SLACK_REQUIRE_MENTION", "1") == "1",
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("SLACK_DM_POLICY", "open"),
            group_policy=os.getenv("SLACK_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("SLACK_DENY_MESSAGE", ""),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
        workspace_dir: Path | None = None,
    ) -> "SlackChannel":
        # Read from config if present, otherwise fall back to caller args
        show_tool_details = getattr(
            config,
            "show_tool_details",
            show_tool_details,
        )
        filter_tool_messages = getattr(
            config,
            "filter_tool_messages",
            filter_tool_messages,
        )
        filter_thinking = getattr(
            config,
            "filter_thinking",
            filter_thinking,
        )
        return cls(
            process=process,
            enabled=True,
            bot_token=getattr(config, "bot_token", "") or "",
            app_token=getattr(config, "app_token", "") or "",
            bot_prefix=getattr(config, "bot_prefix", ""),
            proxy=getattr(config, "proxy", ""),
            streaming_enabled=getattr(config, "streaming_enabled", False),
            require_mention=getattr(config, "require_mention", True),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "open"),
            group_policy=getattr(config, "group_policy", "open"),
            allow_from=getattr(config, "allow_from", None),
            deny_message=getattr(config, "deny_message", ""),
            access_control_dm=getattr(config, "access_control_dm", False),
            access_control_group=getattr(
                config,
                "access_control_group",
                False,
            ),
            dm_disabled=getattr(config, "dm_disabled", False),
            group_disabled=getattr(config, "group_disabled", False),
            media_dir=getattr(config, "media_dir", "") or "",
            workspace_dir=workspace_dir,
        )

    @property
    def proxy_url(self) -> Optional[str]:
        """The resolved Slack proxy URL, or None."""
        return self._proxy_url

    @property
    def bot_user_id(self) -> str:
        """The bot's Slack user ID (resolved from auth.test)."""
        return self._bot_user_id

    # ── Lifecycle ──

    async def start(self) -> None:
        """Start the Slack channel: init SDK, then connect Socket Mode."""
        await self._on_init()
        await self._start()

    async def stop(self) -> None:
        """Stop the Slack channel: disconnect Socket Mode."""
        await self._stop()

    async def _on_init(self) -> None:
        """Initialise Slack SDK client, register event handlers, and
        resolve the bot user ID before any messages arrive."""
        await self._build_app()

        # Resolve proxy early so it is available for both REST and WS.
        self._proxy_url, skip_reason = _resolve_slack_proxy_url(self.proxy)
        if self._proxy_url:
            _apply_slack_proxy(self._client, self._proxy_url)
            logger.info(
                "[%s] proxy configured: %s",
                self.channel,
                self._proxy_url,
            )
        elif skip_reason == "unsupported_proxy_scheme":
            logger.info("[%s] ignoring unsupported proxy scheme", self.channel)
        elif skip_reason == "no_proxy_bypass":
            logger.info("[%s] NO_PROXY bypasses Slack proxy", self.channel)

        # Fetch bot user ID immediately so @mention detection works
        # from the first inbound message.
        await self._fetch_bot_user_id()

        self._event_handler = SlackEventHandler(
            channel=self,
            enqueue_callback=self._enqueue,
            bot_prefix=self.bot_prefix,
            require_mention=self.require_mention,
        )
        if self._app is not None:
            self._event_handler.register(self._app)

        # Retrieve all command names from CommandRegistry and CommandHandler,
        # and register them with Slack
        _slash_names = set()

        # _command_registry is injected by ChannelManager.set_workspace(),
        # but may not yet be set during the _on_init() phase,
        # so precautions are needed.
        registry = getattr(self, "_command_registry", None)
        if registry is not None:
            for cmd in registry._command_to_level:
                name = cmd.lstrip("/").split()[0]
                if name:
                    _slash_names.add(name)

        from qwenpaw.agents.command_handler import CommandHandler

        for name in CommandHandler.SYSTEM_COMMANDS:
            _slash_names.add(name)

        if _slash_names:
            _slash_pattern = re.compile(
                r"^/(?:"
                + "|".join(re.escape(n) for n in sorted(_slash_names))
                + r")$",
            )

            @self._app.command(_slash_pattern)
            async def _handle_qwenpaw_slash(ack, command):
                slash_name = (command.get("command") or "").lstrip("/")
                await ack(
                    response_type="ephemeral",
                    text=f"Running `/{slash_name}`…",
                )
                await self._event_handler.handle_slash_command(command)

        self._sender = SlackSender(channel=self)
        self._stream_manager = SlackStreamManager(channel=self)

        logger.info("[%s] slack channel initialised", self.channel)

    async def _start(self) -> None:
        """Start the Socket Mode connection

        SDK handles reconnection internally.
        """
        if self._app is None:
            await self._build_app()

        # Tear down any previous handler before starting a new one.
        await self._stop_socket_mode_handler()

        self._handler = AsyncSocketModeHandler(
            self._app,
            self.app_token,
            proxy=self._proxy_url,
            ping_interval=10,
        )

        logger.info("[%s] slack socket mode connecting", self.channel)
        self._socket_mode_task = asyncio.create_task(
            self._handler.start_async(),
        )
        self._socket_mode_task.add_done_callback(
            self._on_socket_mode_task_done,
        )
        self._socket_reconnect_attempt = 0

    async def _stop(self) -> None:
        """Gracefully disconnect: close handler, cancel task."""
        await self._stop_socket_mode_handler()
        # Abandon all active streaming sessions
        if self._stream_manager is not None:
            await self._stream_manager.cleanup_all()
        if self._sender is not None:
            await self._sender.close()
        if self._event_handler is not None:
            await self._event_handler.close()
        logger.info("[%s] slack channel stopped", self.channel)

    # ── Socket Mode resilience ──

    async def _stop_socket_mode_handler(self) -> None:
        """Shut down the current Socket Mode handler and its task."""
        handler = self._handler
        task = self._socket_mode_task

        self._handler = None
        self._socket_mode_task = None

        if handler is not None:
            try:
                await handler.close_async()
            except Exception:
                logger.debug(
                    "[%s] error closing handler",
                    self.channel,
                    exc_info=True,
                )

        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug(
                    "[%s] task raised during stop",
                    self.channel,
                    exc_info=True,
                )

    def _on_socket_mode_task_done(self, task: asyncio.Task) -> None:
        """Callback: schedule a reconnect when the Socket Mode task exits
        unexpectedly."""
        if task is not self._socket_mode_task:
            return
        if task.cancelled():
            return
        if not getattr(self, "_running", False):
            return

        exc = task.exception()
        if exc is None:
            # Normal exit — SDK's start_async() should never return normally,
            # but if it does, schedule a restart.
            if getattr(self, "_running", False):
                asyncio.ensure_future(
                    self._restart_socket_mode("task exited normally"),
                )
            return

        # Recoverability is checked only when the exception
        # is an instance of `Exception`
        if isinstance(exc, Exception) and _is_non_recoverable_slack_error(exc):
            logger.error(
                "[%s] non-recoverable auth error — stopping channel: %s",
                self.channel,
                exc,
            )
            self._running = False
            return

        logger.warning(
            "[%s] socket mode task exited with error: %s",
            self.channel,
            exc,
        )
        if getattr(self, "_running", False):
            asyncio.ensure_future(self._restart_socket_mode("task error"))

    async def _restart_socket_mode(self, reason: str) -> None:
        """Reconnect Socket Mode with exponential backoff.

        Serialised through a per-instance lock to prevent concurrent
        restart attempts.  Backoff parameters are defined in
        ``constants.py``.
        """
        async with self._socket_reconnect_lock:
            if not getattr(self, "_running", False):
                return

            if self._socket_reconnect_attempt >= SLACK_RECONNECT_MAX_ATTEMPTS:
                logger.error(
                    "[%s] max reconnect attempts (%d) reached — giving up",
                    self.channel,
                    SLACK_RECONNECT_MAX_ATTEMPTS,
                )
                self._running = False
                return

            delay = min(
                self._socket_reconnect_attempt
                * SLACK_RECONNECT_FACTOR
                * SLACK_RECONNECT_INITIAL_S,
                SLACK_RECONNECT_MAX_S,
            )
            if delay > 0:
                jitter = (
                    delay * SLACK_RECONNECT_JITTER * (2 * random.random() - 1)
                )
                delay = max(0, delay + jitter)

            logger.warning(
                "[%s] restarting socket mode (attempt %d, delay %.1fs): %s",
                self.channel,
                self._socket_reconnect_attempt + 1,
                delay,
                reason,
            )

            if delay > 0:
                await asyncio.sleep(delay)

            self._socket_reconnect_attempt += 1
            try:
                await self._stop_socket_mode_handler()
                await self._start()
            except Exception as exc:
                if _is_non_recoverable_slack_error(exc):
                    logger.error(
                        "[%s] non-recoverable auth error — "
                        "stopping channel: %s",
                        self.channel,
                        exc,
                    )
                    self._running = False
                    return
                raise

    # ── Bot user ID ──

    async def _fetch_bot_user_id(self) -> None:
        """Resolve the bot's Slack user ID. Retries with backoff
        if the first attempt fails; raises if all retries are exhausted."""
        client = await self.get_client()
        last_exc = None
        for attempt in range(3):
            try:
                auth = await client.auth_test()
                self._bot_user_id = auth.get("user_id", "")
                logger.info(
                    "[%s] slack bot user_id=%s",
                    self.channel,
                    self._bot_user_id,
                )
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[%s] slack auth_test attempt %d/3 failed: %s",
                    self.channel,
                    attempt + 1,
                    exc,
                )
                await asyncio.sleep(2**attempt)

        raise RuntimeError(
            f"[{self.channel}] Failed to fetch bot user_id after 3 attempts",
        ) from last_exc

    # ── Message sending ──

    async def _send(
        self,
        to_handle: str,
        content_parts: List[Any],
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a message to Slack.

        Delegates to :class:`SlackSender`.
        """
        if self._sender is None:
            self._sender = SlackSender(channel=self)
        await self._sender.send_content_parts(to_handle, content_parts, meta)
        return {"sent": True}

    # ------------------------------------------------------------------
    # Streaming hooks — edit-in-place via Slack chat.update
    # ------------------------------------------------------------------

    @staticmethod
    def _get_stream_state(
        send_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get or create the per-request streaming state dict in send_meta."""
        stream_state = send_meta.get("_sl_stream")
        if stream_state is None:
            stream_state = {
                "message_ts": {},
                "channel_id": "",
                "last_edit_ts": {},
            }
            send_meta["_sl_stream"] = stream_state
        return stream_state  # type: ignore[return-value]

    async def on_streaming_start(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Send a placeholder message for streaming."""
        if stream_type == "reasoning" and self._filter_thinking:
            return

        channel_id = send_meta.get("slack_channel_id") or ""
        thread_ts = send_meta.get("slack_thread_ts") or None
        if not channel_id:
            return

        client = await self.get_client()
        prefix = "\U0001f4ad " if stream_type == "reasoning" else ""
        placeholder = f"{prefix}\u23f3 ..."

        try:
            resp = await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=placeholder,
                mrkdwn=True,
            )
            ts = resp.get("ts")
            if ts:
                state = self._get_stream_state(send_meta)
                state["message_ts"][stream_type] = ts
                state["channel_id"] = channel_id
                await self.record_bot_message(ts, thread_ts)
        except Exception:
            logger.debug(
                "slack on_streaming_start: placeholder failed",
                exc_info=True,
            )

    async def on_streaming_delta(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Throttled chat.update to show incremental progress."""
        if stream_type == "reasoning" and self._filter_thinking:
            return

        state = self._get_stream_state(send_meta)
        msg_ts = state["message_ts"].get(stream_type)
        channel_id = state["channel_id"]
        if not msg_ts or not channel_id:
            return

        now = time.monotonic()
        last_ts = state["last_edit_ts"].get(stream_type, 0.0)
        if now - last_ts < _STREAM_EDIT_INTERVAL_S:
            return

        client = await self.get_client()
        prefix = "\U0001f4ad " if stream_type == "reasoning" else ""
        display = f"{prefix}{accumulated_text}" if prefix else accumulated_text

        # Truncate if exceeds Slack text limit
        if len(display) > SLACK_TEXT_LIMIT:
            display = "..." + display[-(SLACK_TEXT_LIMIT - 4) :]

        try:
            await client.chat_update(
                channel=channel_id,
                ts=msg_ts,
                text=display,
                mrkdwn=True,
            )
            state["last_edit_ts"][stream_type] = now
        except Exception:
            logger.debug(
                "slack on_streaming_delta: update failed",
                exc_info=True,
            )

    async def on_streaming_end(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Final chat.update with full text; fallback to normal send."""
        state = self._get_stream_state(send_meta)
        msg_ts = state["message_ts"].pop(stream_type, None)
        state["last_edit_ts"].pop(stream_type, None)
        channel_id = state["channel_id"]

        if stream_type == "reasoning" and self._filter_thinking:
            return

        if not accumulated_text.strip():
            return

        # If placeholder was never sent, fall back to normal send
        if not msg_ts or not channel_id:
            await self._send(
                to_handle,
                [TextContent(text=accumulated_text)],
                send_meta,
            )
            return

        client = await self.get_client()
        prefix = "\U0001f4ad " if stream_type == "reasoning" else ""
        final_text = (
            f"{prefix}{accumulated_text}" if prefix else accumulated_text
        )
        mrkdwn = markdown_to_slack_mrkdwn(final_text)

        try:
            await client.chat_update(
                channel=channel_id,
                ts=msg_ts,
                text=mrkdwn,
                mrkdwn=True,
            )
        except Exception:
            logger.debug(
                "slack on_streaming_end: final update failed, "
                "falling back to normal send",
                exc_info=True,
            )
            # Fallback: send as a new message via normal path
            await self._send(
                to_handle,
                [TextContent(text=accumulated_text)],
                send_meta,
            )

    async def _send_streaming(
        self,
        to_handle: str,
        stream_generator,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Stream content to Slack.

        When streaming is disabled, buffers the response and sends as a
        single message.  When enabled, uses native Slack streaming API in
        threads, with automatic chat_update fallback for non-thread messages.
        """
        if self._stream_manager is None:
            self._stream_manager = SlackStreamManager(channel=self)

        channel_id, thread_ts = SlackSender.resolve_route(to_handle, meta)

        if not self.streaming_enabled:
            return await self._send_streaming_off(
                channel_id,
                thread_ts,
                stream_generator,
                meta,
            )
        if thread_ts:
            return await self._send_streaming_partial(
                channel_id,
                thread_ts,
                stream_generator,
                meta,
            )
        return await self._send_streaming_edit(
            channel_id,
            stream_generator,
            meta,
        )

    async def _send_streaming_off(
        self,
        channel_id: str,
        thread_ts: Optional[str],
        stream_generator,
        _meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Buffer all deltas and send as a single message."""
        chunks: List[str] = []
        async for delta in stream_generator:
            if delta:
                chunks.append(delta)
        full_text = "".join(chunks)
        if not full_text.strip():
            return {"sent": False}

        mrkdwn = markdown_to_slack_mrkdwn(full_text)
        text_chunks = chunk_slack_text(mrkdwn, SLACK_TEXT_LIMIT)

        client = await self.get_client()
        last_ts = None
        for text in text_chunks:
            if self.bot_prefix and last_ts is None:
                text = f"{self.bot_prefix}\n{text}"
            result = await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=text,
                mrkdwn=True,
            )
            last_ts = result.get("ts")
        return {"sent": True, "message_ts": last_ts}

    async def _send_streaming_partial(
        self,
        channel_id: str,
        thread_ts: str,
        stream_generator,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Native AsyncChatStream streaming.  Falls back to chat_update
        when ``SlackStreamNotDeliveredError`` is raised."""
        if self._stream_manager is None:
            self._stream_manager = SlackStreamManager(channel=self)

        stream_session = None
        full_text = ""
        try:
            stream_session = await self._stream_manager.start_native_stream(
                channel_id=channel_id,
                thread_ts=thread_ts,
                team_id=meta.get("slack_team_id", ""),
                user_id=meta.get("slack_user_id", ""),
            )
            async for delta in stream_generator:
                if not delta:
                    continue
                full_text += delta
                mrkdwn = markdown_to_slack_mrkdwn(delta)
                await self._stream_manager.append_native(
                    stream_session,
                    mrkdwn,
                )
            await self._stream_manager.stop_native(stream_session)
            return {"sent": True, "message_ts": stream_session.thread_ts}
        except SlackStreamNotDeliveredError:
            logger.warning(
                "[%s] slack native stream not delivered, falling back",
                self.channel,
            )
            if stream_session:
                await self._stream_manager.cleanup(channel_id)
            return await self._streaming_edit_fallback(
                channel_id,
                full_text,
                stream_generator,
            )

    async def _send_streaming_edit(
        self,
        channel_id: str,
        stream_generator,
        _meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """No thread_ts — stream via chat_update fallback.

        Delegates entirely to :meth:`_streaming_edit_fallback`, which
        posts a placeholder message and then edits it incrementally.
        """
        return await self._streaming_edit_fallback(
            channel_id,
            "",
            stream_generator,
        )

    async def _streaming_edit_fallback(
        self,
        channel_id: str,
        prefix_text: str,
        stream_generator,
        initial_message_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """chat_update-based streaming fallback."""
        if self._stream_manager is None:
            self._stream_manager = SlackStreamManager(channel=self)

        client = await self.get_client()
        if initial_message_ts is None:
            result = await client.chat_postMessage(
                channel=channel_id,
                text="...",
            )
            initial_message_ts = result.get("ts")

        edit_session = await self._stream_manager.start_edit_stream(
            channel_id=channel_id,
            message_ts=initial_message_ts,
        )

        if prefix_text:
            await self._stream_manager.append_edit(edit_session, prefix_text)

        async for delta in stream_generator:
            if not delta:
                continue
            mrkdwn = markdown_to_slack_mrkdwn(delta)
            await self._stream_manager.append_edit(edit_session, mrkdwn)

        await self._stream_manager.stop_edit(edit_session)
        return {"sent": True, "message_ts": initial_message_ts}

    # ── Internal helpers ──

    async def _build_app(self) -> None:
        """Build the ``slack_bolt.AsyncApp`` and ``AsyncWebClient``."""
        self._client = AsyncWebClient(token=self.bot_token)
        self._app = AsyncApp(
            token=self.bot_token,
            client=self._client,
            logger=logger,
            ignoring_self_events_enabled=True,
        )

    async def get_client(self) -> AsyncWebClient:
        """Return the ``AsyncWebClient``, creating it if necessary."""
        if self._client is None:
            await self._build_app()
        return self._client

    async def record_bot_message(
        self,
        ts: str,
        thread_ts: Optional[str] = None,
    ) -> None:
        """Record that the bot sent a message at *ts*."""
        async with self._bot_message_ts_lock:
            self._bot_message_ts[ts] = time.monotonic()
            if thread_ts:
                self._bot_message_ts[thread_ts] = time.monotonic()

    async def has_bot_replied_in_thread(self, thread_ts: str) -> bool:
        """Return True if the bot has previously replied in this thread."""
        async with self._bot_message_ts_lock:
            return thread_ts in self._bot_message_ts

    async def prune_bot_message_ts(self) -> None:
        """Trim the oldest half of entries when exceeding 5000."""
        async with self._bot_message_ts_lock:
            if len(self._bot_message_ts) > 5000:
                sorted_items = sorted(
                    self._bot_message_ts.items(),
                    key=lambda x: x[1],
                )
                self._bot_message_ts = dict(
                    sorted_items[len(sorted_items) // 2 :],
                )

    # ── Public send API (BaseChannel contract) ──

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a single text message to Slack."""
        if not self.enabled:
            logger.debug("[%s] channel disabled, skipping send", self.channel)
            return

        parts = [TextContent(type=ContentType.TEXT, text=text)]
        await self.send_content_parts(to_handle, parts, meta or {})

    async def send_content_parts(
        self,
        to_handle: str,
        parts: list,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send content parts to Slack via :class:`SlackSender`."""
        if not self.enabled:
            logger.debug(
                "[%s] channel disabled, skipping send_content_parts",
                self.channel,
            )
            return
        if self._sender is None:
            self._sender = SlackSender(channel=self)
        await self._sender.send_content_parts(to_handle, parts, meta or {})

    # ── Native payload → AgentRequest ──

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Convert Slack native dict to AgentRequest."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        user_id = str(meta.get("slack_user_id") or sender_id)
        session_id = payload.get("session_id") or self.resolve_session_id(
            user_id,
            meta,
        )
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

    def get_cached_thread_context(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[str]:
        """Return cached thread context if still valid, else None."""
        key = f"{channel_id}:{thread_ts}"
        cached = self._thread_context_cache.get(key)
        if cached and (
            time.monotonic() - cached[1]
            < self._thread_context_cache_ttl
        ):
            return cached[0]
        return None

    def set_cached_thread_context(
        self,
        channel_id: str,
        thread_ts: str,
        content: str,
    ) -> None:
        """Store thread context in cache."""
        key = f"{channel_id}:{thread_ts}"
        self._thread_context_cache[key] = (content, time.monotonic())

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Resolve session id from Slack meta (channel + thread)."""
        if channel_meta:
            channel_id = channel_meta.get("slack_channel_id", "")
            thread_ts = channel_meta.get("slack_thread_ts", "")
            if thread_ts:
                return f"{channel_id}:{thread_ts}"
            return channel_id or sender_id
        return sender_id or ""

    def get_to_handle_from_request(self, request: Any) -> str:
        """Extract Slack routing handle from AgentRequest.

        Returns ``channel_id`` or ``channel_id:thread_ts`` so that
        :meth:`SlackSender.resolve_route` can parse it.
        """
        meta = getattr(request, "channel_meta", None) or {}
        channel_id = meta.get("slack_channel_id", "")
        thread_ts = meta.get("slack_thread_ts", "")
        if channel_id and thread_ts:
            return f"{channel_id}:{thread_ts}"
        return channel_id or f"dm:{getattr(request, 'user_id', '')}"
