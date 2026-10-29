# -*- coding: utf-8 -*-
"""Worker-owned Slack Socket Mode, native callbacks and message effects."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import random
import re
import time

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from qwenpaw.channel_protocol.outbound_budget import (
    await_send,
    retry_delay_fits,
)

from .constants import (
    SLACK_RECONNECT_FACTOR,
    SLACK_RECONNECT_INITIAL_S,
    SLACK_RECONNECT_JITTER,
    SLACK_RECONNECT_MAX_ATTEMPTS,
    SLACK_RECONNECT_MAX_S,
    SLACK_SOCKET_PING_INTERVAL_S,
    SLACK_TEXT_LIMIT,
)
from .format import markdown_to_slack_mrkdwn
from .handler import SlackEventHandler
from .sender import SlackSender
from .utils import (
    SlackDeliveryError,
    _apply_slack_proxy,
    _extract_retry_after,
    _resolve_slack_proxy_url,
    build_dedup_key,
)

logger = logging.getLogger(__name__)
_NON_RECOVERABLE_SLACK_ERRORS = frozenset(
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


def _is_non_recoverable_slack_error(error):
    return any(
        keyword in str(error).lower()
        for keyword in _NON_RECOVERABLE_SLACK_ERRORS
    )


class SlackPlatform:
    channel = "slack"

    def __init__(self, config, on_event, on_state):
        self.config, self.on_event, self.on_state = config, on_event, on_state
        self.bot_token = config.get("bot_token") or ""
        self.app_token = config.get("app_token") or ""
        self.bot_prefix = config.get("bot_prefix") or ""
        self.dm_disabled = config.get("dm_disabled", False)
        self.group_disabled = config.get("group_disabled", False)
        workspace = config.get("workspace_dir")
        if config.get("media_dir"):
            self._media_dir = Path(config["media_dir"]).expanduser()
        elif workspace:
            self._media_dir = Path(workspace).expanduser() / "media"
        else:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            self._media_dir = DEFAULT_MEDIA_DIR
        self._client = self._app = self._handler = None
        self._event_handler = self._sender = None
        self._socket_mode_task = self._connection_task = self._stop_task = None
        self._background_tasks, self._event_tasks, self._effect_tasks = (
            set(),
            set(),
            set(),
        )
        self._sdk_tasks = set()
        self._event_locks = {}
        self._socket_reconnect_lock = asyncio.Lock()
        self._socket_reconnect_attempt = 0
        self._epoch = 0
        self._running = self._stopping = self.connected = False
        self._bot_user_id = ""
        self._proxy_url = None
        self._thread_context_cache = OrderedDict()
        self._thread_context_cache_ttl = 60.0
        self._thread_context_cache_max = 1024

    @property
    def media_dir(self):
        return self._media_dir

    @property
    def bot_user_id(self):
        return self._bot_user_id

    @property
    def proxy_url(self):
        return self._proxy_url

    async def _state(self, state):
        connected = state == "connected"
        if connected != self.connected:
            self._epoch += 1
        self.connected = connected
        await self.on_state(state)

    async def _build_app(self):
        self._client = AsyncWebClient(token=self.bot_token, retry_handlers=[])
        self._app = AsyncApp(
            token=self.bot_token,
            client=self._client,
            logger=logger,
            ignoring_self_events_enabled=True,
            before_authorize=self._configure_request_client,
        )

    async def _configure_request_client(self, client, next):
        _apply_slack_proxy(client, self._proxy_url)
        return await next()

    async def get_client(self):
        if self._client is None:
            await self._build_app()
        return self._client

    async def _fetch_bot_user_id(self):
        client = await self.get_client()
        last = None
        for attempt in range(3):
            try:
                self._bot_user_id = (await client.auth_test()).get(
                    "user_id",
                    "",
                )
                return
            except Exception as exc:
                last = exc
                await asyncio.sleep(2**attempt)
        raise RuntimeError(
            "[slack] Failed to fetch bot user_id after 3 attempts",
        ) from last

    async def _on_init(self):
        self._media_dir.mkdir(parents=True, exist_ok=True)
        await self._build_app()
        self._proxy_url, _reason = _resolve_slack_proxy_url(
            self.config.get("proxy"),
        )
        _apply_slack_proxy(self._client, self._proxy_url)
        await self._fetch_bot_user_id()
        self._event_handler = SlackEventHandler(
            self,
            self.on_event,
            self.bot_prefix,
            self.config.get("require_mention", True),
        )
        self._event_handler.register(self._app)

        @self._app.command(re.compile(r"^/.+"))
        async def slash(ack, command):
            name = (command.get("command") or "").lstrip("/")
            await ack(response_type="ephemeral", text=f"Running `/{name}`…")
            await self.dispatch(
                self._event_handler.handle_slash_command,
                command,
            )

        self._sender = SlackSender(self)

    async def start(self):
        if self._stopping:
            raise RuntimeError("SLACK_STOP_INCOMPLETE")
        await self._on_init()
        self._running = True
        await self._start()

    def _release_sdk_task(self, task):
        if task.cancelled() or task.exception() is None:
            self._sdk_tasks.discard(task)

    def _retain_sdk_task(self, task):
        if isinstance(task, asyncio.Future) and task not in self._sdk_tasks:
            self._sdk_tasks.add(task)
            task.add_done_callback(self._release_sdk_task)
        return task

    def _remember_sdk_tasks(self, handler):
        client = getattr(handler, "client", None)
        for name in (
            "message_processor",
            "current_session_monitor",
            "message_receiver",
        ):
            task = getattr(client, name, None)
            self._retain_sdk_task(task)

    def _own_sdk_tasks(self, handler):
        self._remember_sdk_tasks(handler)
        for name in (
            "process_messages",
            "monitor_current_session",
            "receive_messages",
        ):
            native = getattr(handler.client, name)

            def create_owned_task(native=native):
                # SDK ensure_future(Task) keeps this exact native task.
                return self._retain_sdk_task(asyncio.ensure_future(native()))

            setattr(handler.client, name, create_owned_task)

    async def _start(self):
        await self._stop_socket_mode_handler()
        self._handler = AsyncSocketModeHandler(
            self._app,
            self.app_token,
            proxy=self._proxy_url,
            ping_interval=SLACK_SOCKET_PING_INTERVAL_S,
        )
        _apply_slack_proxy(self._handler.client, self._proxy_url)
        self._own_sdk_tasks(self._handler)
        self._socket_mode_task = asyncio.create_task(
            self._handler.start_async(),
        )
        self._socket_mode_task.add_done_callback(
            self._on_socket_mode_task_done,
        )
        self._connection_task = asyncio.create_task(
            self._watch_connection(self._handler),
        )

    async def _watch_connection(self, handler):
        while self._running and handler is self._handler:
            try:
                connected = await handler.client.is_connected()
            except asyncio.CancelledError:
                raise
            except Exception:
                connected = False
            if connected != self.connected:
                await self._state("connected" if connected else "disconnected")
            await asyncio.sleep(0.05)

    def _schedule_background(self, coro):
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _on_socket_mode_task_done(self, task):
        if (
            task is not self._socket_mode_task
            or task.cancelled()
            or not self._running
        ):
            return
        error = task.exception()
        self._schedule_background(self._socket_exited(error))

    async def _socket_exited(self, error):
        if not self._running:
            return
        if error and _is_non_recoverable_slack_error(error):
            self._running = False
            await self._state("failed")
            return
        await self._state("disconnected")
        await self._restart_socket_mode(
            "task error" if error else "task exited normally",
        )

    async def _restart_socket_mode(self, reason):
        async with self._socket_reconnect_lock:
            if not self._running:
                return
            if self._socket_reconnect_attempt >= SLACK_RECONNECT_MAX_ATTEMPTS:
                self._running = False
                await self._state("failed")
                return
            delay = min(
                (self._socket_reconnect_attempt + 1)
                * SLACK_RECONNECT_FACTOR
                * SLACK_RECONNECT_INITIAL_S,
                SLACK_RECONNECT_MAX_S,
            )
            delay = max(
                0,
                delay
                + delay * SLACK_RECONNECT_JITTER * (2 * random.random() - 1),
            )
            await asyncio.sleep(delay)
            if not self._running:
                return
            self._socket_reconnect_attempt += 1
            try:
                await self._start()
                self._socket_reconnect_attempt = 0
            except Exception as exc:
                if _is_non_recoverable_slack_error(exc):
                    self._running = False
                    await self._state("failed")
                    return
                raise

    async def dispatch(self, callback, *args, **kwargs):
        if self._stopping or not self._running or not self.connected:
            return False
        task = asyncio.current_task()
        self._event_tasks.add(task)
        epoch = self._epoch
        value = args[0] if args else {}
        key = (
            build_dedup_key(value)
            if value.get("ts")
            else value.get("trigger_id")
        )
        entry = self._event_locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                if self._stopping or epoch != self._epoch:
                    return False
                return await callback(*args, **kwargs)
        finally:
            entry[1] -= 1
            if not entry[1]:
                self._event_locks.pop(key, None)
            self._event_tasks.discard(task)

    @asynccontextmanager
    async def _effect(self):
        if self._stopping or not self.connected:
            raise SlackDeliveryError("NOT_CONNECTED")
        task = asyncio.current_task()
        self._effect_tasks.add(task)
        try:
            yield
        finally:
            self._effect_tasks.discard(task)

    async def effect_call(self, function, **kwargs):
        for attempt in range(3):
            try:
                result = await await_send(function(**kwargs))
                if result.get("ok") is False:
                    raise SlackDeliveryError("SLACK_REJECTED")
                return result
            except (SlackDeliveryError, asyncio.CancelledError):
                raise
            except Exception as exc:
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                if status == 429 and attempt < 2:
                    delay = _extract_retry_after(exc)
                    delay = 1.5 * (attempt + 1) if delay is None else delay
                    if retry_delay_fits(delay):
                        await await_send(asyncio.sleep(delay))
                        continue
                rejected = isinstance(status, int) and (
                    400 <= status < 500
                    or status < 500
                    and response.get("ok") is False
                )
                code = (
                    response.get("error", "") if response is not None else ""
                )
                raise SlackDeliveryError(
                    (
                        "SLACK_FORMAT_REJECTED"
                        if rejected
                        and code
                        in {
                            "msg_too_long",
                            "invalid_blocks",
                            "invalid_attachments",
                        }
                        else (
                            "SLACK_REJECTED"
                            if rejected
                            else "SLACK_RESULT_UNKNOWN"
                        )
                    ),
                    side_effect_possible=not rejected,
                    retryable=status == 429,
                ) from exc

    def authorize_path(self, value):
        path = Path(value).expanduser().resolve()
        roots = [self._media_dir.resolve()]
        if self.config.get("workspace_dir"):
            roots.append(
                Path(self.config["workspace_dir"]).expanduser().resolve(),
            )
        if not any(path.is_relative_to(root) for root in roots):
            raise SlackDeliveryError("MEDIA_PATH_OUTSIDE_WORKSPACE")

    async def download_file(self, url, filename):
        if self._event_handler is None:
            self._event_handler = SlackEventHandler(
                self,
                self.on_event,
                self.bot_prefix,
                self.config.get("require_mention", True),
            )
        return await self._event_handler._download_slack_file(url, filename)

    async def send_parts(self, route, parts):
        async with self._effect():
            result = await self._sender.send_content_parts(
                route["channel_id"],
                list(parts),
                {
                    "slack_channel_id": route["channel_id"],
                    "slack_thread_ts": route.get("thread_ts") or "",
                },
            )
            if not result:
                raise SlackDeliveryError("SLACK_CONTENT_NOT_DELIVERED")
            return {
                "channel_id": route["channel_id"],
                "message_ts": str(result),
            }

    async def start_stream(self, route, stream_type):
        async with self._effect():
            if stream_type == "reasoning" and not self.config.get(
                "show_thinking",
                True,
            ):
                return {"message_ts": "", "channel_id": "", "final": "true"}
            channel = route.get("stream_channel_id")
            if not channel:
                raise SlackDeliveryError("STREAM_TARGET_UNAVAILABLE")
            text = ("💭 " if stream_type == "reasoning" else "") + "⏳ ..."
            response = await self.effect_call(
                self._client.chat_postMessage,
                channel=channel,
                thread_ts=route.get("thread_ts") or None,
                text=text,
                mrkdwn=True,
            )
            if not response.get("ts"):
                raise SlackDeliveryError(
                    "SLACK_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            return {
                "message_ts": str(response["ts"]),
                "channel_id": channel,
                "text": text,
            }

    async def update_stream(self, resource, text, *, final=False):
        async with self._effect():
            if not resource.get("message_ts"):
                return resource
            if not text.strip():
                return resource
            now = time.monotonic()
            last_delta = float(resource.get("last_delta_at", "0"))
            if not final and now - last_delta < 1.5:
                return resource
            display = markdown_to_slack_mrkdwn(text) if final else text
            if final and len(display) > SLACK_TEXT_LIMIT:
                await self.effect_call(
                    self._client.chat_delete,
                    channel=resource["channel_id"],
                    ts=resource["message_ts"],
                )
                try:
                    result = await self._sender.send_content_parts(
                        resource["channel_id"],
                        [{"type": "text", "text": text}],
                        {"slack_thread_ts": resource.get("thread_ts", "")},
                    )
                except SlackDeliveryError as exc:
                    raise SlackDeliveryError(
                        exc.reason_code,
                        side_effect_possible=True,
                    ) from exc
                return {
                    **resource,
                    "message_ts": str(result or resource["message_ts"]),
                }
            if len(display) > SLACK_TEXT_LIMIT:
                retained = SLACK_TEXT_LIMIT - 4
                display = "..." + display[-retained:]
            try:
                await self.effect_call(
                    self._client.chat_update,
                    channel=resource["channel_id"],
                    ts=resource["message_ts"],
                    text=display,
                    mrkdwn=True,
                )
            except SlackDeliveryError as exc:
                if not final or exc.reason_code != "SLACK_FORMAT_REJECTED":
                    raise
                result = await self._sender.send_content_parts(
                    resource["channel_id"],
                    [{"type": "text", "text": text}],
                    {"slack_thread_ts": resource.get("thread_ts", "")},
                )
                return {
                    **resource,
                    "message_ts": str(result or resource["message_ts"]),
                }
            return {**resource, "last_delta_at": str(now)}

    def get_cached_thread_context(self, channel_id, thread_ts):
        cached = self._thread_context_cache.get(f"{channel_id}:{thread_ts}")
        if (
            cached
            and time.monotonic() - cached[1] < self._thread_context_cache_ttl
        ):
            return cached[0]
        return None

    def set_cached_thread_context(self, channel_id, thread_ts, content):
        self._thread_context_cache[f"{channel_id}:{thread_ts}"] = (
            content,
            time.monotonic(),
        )
        while len(self._thread_context_cache) > self._thread_context_cache_max:
            self._thread_context_cache.popitem(last=False)

    async def _stop_socket_mode_handler(self):
        handler = self._handler
        if self._connection_task is not None:
            self._connection_task.cancel()
            await asyncio.gather(self._connection_task, return_exceptions=True)
            self._connection_task = None
        if self._socket_mode_task is not None:
            if not self._socket_mode_task.cancelling():
                self._socket_mode_task.cancel()
        failures = []
        if handler is not None:
            handler.client.auto_reconnect_enabled = False
            handler.client.default_auto_reconnect_enabled = False
        if self._socket_mode_task is not None:
            await asyncio.gather(
                self._socket_mode_task,
                return_exceptions=True,
            )
        if handler is not None:
            self._remember_sdk_tasks(handler)
        failures.extend(await self._drain_sdk_tasks())
        if handler is not None:
            try:
                await handler.close_async()
            except Exception as exc:
                failures.append(exc)
            self._remember_sdk_tasks(handler)
        failures.extend(await self._drain_sdk_tasks())
        if failures:
            raise failures[0]
        self._sdk_tasks.clear()
        self._socket_mode_task = self._handler = None

    async def _drain_sdk_tasks(self):
        settled, failures = set(), []
        while tasks := self._sdk_tasks - settled:
            for task in tasks:
                if not task.done() and (
                    not isinstance(task, asyncio.Task) or not task.cancelling()
                ):
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failures.extend(
                result
                for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)
            )
            settled.update(tasks)
        return failures

    async def stop(self):
        self._stopping, self._running = True, False
        self.connected = False
        self._epoch += 1
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self):
        tasks = self._background_tasks | self._event_tasks | self._effect_tasks
        tasks = {task for task in tasks if task is not asyncio.current_task()}
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        failures = []
        for close in (
            self._stop_socket_mode_handler,
            *(
                component.close
                for component in (self._sender, self._event_handler)
                if component
            ),
        ):
            try:
                await close()
            except Exception as exc:
                failures.append(exc)
        session = getattr(self._client, "session", None)
        if session is not None and not session.closed:
            try:
                await session.close()
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise failures[0]
        self._client = self._app = self._sender = self._event_handler = None
        await self._state("disconnected")
