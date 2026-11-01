# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches,protected-access
"""Instance-owned DingTalk connections and platform requests.

This module is SDK-free; start imports sdk and the SDK-derived handler.
The adapter keeps host orchestration and durable routing in channel.py.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import mimetypes
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp
import certifi

from qwenpaw.exceptions import ChannelError
from qwenpaw.app.channels.utils import file_url_to_local_path
from .ai_card import ActiveAICard, FAILED, FINISHED, PROCESSING, INPUTING
from .constants import (
    AI_CARD_RECOVERY_FINAL_TEXT,
    AI_CARD_TOKEN_PREEMPTIVE_REFRESH_SECONDS,
    DINGTALK_TOKEN_TTL_SECONDS,
)
from .content_utils import session_param_from_webhook_url
from .utils import guess_suffix_from_file_content

logger = logging.getLogger(__name__)
_STREAM_HEALTH_PING_TIMEOUT_SECONDS = 3
_STREAM_WATCHDOG_INTERVAL_SECONDS = 30
_STREAM_WATCHDOG_STALE_SECONDS = 90
_STOP_TIMEOUT_SECONDS = 3.0


def owned_io(method):
    """Retain an in-flight platform operation after its caller is cancelled."""

    @functools.wraps(method)
    async def call(self, *args, **kwargs):
        current = asyncio.current_task()
        if current in self._pending_io or current is self._cleanup_task:
            return await method(self, *args, **kwargs)
        if not self._active and self._state != "starting":
            raise RuntimeError("DingTalk channel is not running")
        task = asyncio.create_task(method(self, *args, **kwargs))
        self._pending_io.add(task)

        def finished(done):
            self._pending_io.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    return call


class DingTalkPlatform:
    """Platform half of the channel; all resources belong to this instance."""

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if not self.enabled or self._active:
                return
            if (
                self._client is not None
                or self._http is not None
                or self._state == "stop_failed"
                or (
                    self._cleanup_task is not None
                    and not self._cleanup_task.done()
                )
            ):
                raise RuntimeError(
                    "DingTalk cleanup is incomplete; retry stop",
                )
            self._state = "starting"
            self._last_error = None
            if not self.client_id or not self.client_secret:
                self._state = "start_failed"
                raise ChannelError(
                    channel_name="dingtalk",
                    message="DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET "
                    "are required when channel is enabled",
                )
            try:
                from . import sdk
                from .handler import DingTalkChannelHandler
            except ModuleNotFoundError as exc:
                self._state = "start_failed"
                self._last_error = f"Missing package: {exc.name}"
                raise RuntimeError(
                    f"DingTalk requires missing package: {exc.name}",
                ) from exc
            self._sdk = sdk
            self._cleanup_task = None
            self._loop = asyncio.get_running_loop()
            self._generation += 1
            generation = self._generation
            try:
                self._media_dir.mkdir(parents=True, exist_ok=True)
                self._load_session_webhook_store_from_disk()
                ssl_context = ssl.create_default_context(
                    cafile=certifi.where(),
                )
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                self._http = aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=40, connect=10),
                )
                config = sdk.open_api_models.Config(
                    protocol="https",
                    region_id="central",
                    connect_timeout=10000,
                    read_timeout=30000,
                )
                if self.endpoint:
                    endpoint = urlparse(self.endpoint)
                    config.protocol = endpoint.scheme or "https"
                    config.endpoint = endpoint.netloc or endpoint.path
                self._oauth_sdk = sdk.dingtalk_oauth_client.Client(config)
                self._robot_sdk = sdk.dingtalk_robot_client.Client(config)
                self._card_sdk = sdk.dingtalk_card_client.Client(config)
                self._client = sdk.StreamClient(
                    sdk.dingtalk_stream.Credential(
                        self.client_id,
                        self.client_secret,
                    ),
                    self.endpoint,
                )

                def enqueue(payload):
                    if self._active and self._generation == generation:
                        callback = getattr(self, "_enqueue", None)
                        if callable(callback):
                            callback(payload)  # pylint: disable=not-callable

                handler = DingTalkChannelHandler(
                    main_loop=self._loop,
                    enqueue_callback=enqueue,
                    bot_prefix=self.bot_prefix,
                    download_url_fetcher=self._fetch_and_download_media,
                    try_accept_message=self._try_accept_message,
                    require_mention=self.require_mention,
                    admit_callback=getattr(self, "_admit_callback", None),
                    is_active=lambda: self._active
                    and self._generation == generation,
                )
                self._client.register_callback_handler(
                    sdk.dingtalk_stream.ChatbotMessage.TOPIC,
                    handler,
                )
                if not getattr(self, "_journal_owner", False):
                    await self._recover_active_cards()
                self._stop_event.clear()
                self._stream_thread = threading.Thread(
                    target=self._run_stream_forever,
                    daemon=True,
                    name="dingtalk-stream",
                )
                self._active = True
                self._state = "connecting"
                self._stream_thread.start()
            except BaseException:
                self._active = False
                self._generation += 1
                self._begin_cleanup()
                await asyncio.shield(self._cleanup_task)
                self._state = "start_failed"
                raise

    def _begin_cleanup(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup())
            self._cleanup_task.add_done_callback(
                lambda task: (
                    task.exception() if not task.cancelled() else None
                ),
            )

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            self._active = False
            self._generation += 1
            self._state = "stopping"
            self._begin_cleanup()
            await asyncio.shield(self._cleanup_task)

    async def _cleanup(self) -> None:
        try:
            self._stop_event.set()
            stream_loop = self._stream_event_loop
            signal = getattr(self, "_stream_stop_signal", None)
            if stream_loop is not None and signal is not None:
                stream_loop.call_soon_threadsafe(signal.set)
            # join runs off the host loop; timeout never proves worker exit.
            thread = self._stream_thread
            if thread is not None and thread.ident is not None:
                await asyncio.to_thread(thread.join, _STOP_TIMEOUT_SECONDS)
                if thread.is_alive():
                    raise RuntimeError("DingTalk stream thread did not stop")
            timers = set(self._debounce_timers.values())
            for task in timers:
                task.cancel()
            if timers:
                _, pending = await asyncio.wait(
                    timers,
                    timeout=_STOP_TIMEOUT_SECONDS,
                )
                if pending:
                    raise RuntimeError("DingTalk debounce cleanup incomplete")
            self._debounce_timers.clear()
            self._debounce_pending.clear()
            if self._pending_io:
                _, pending = await asyncio.wait(
                    set(self._pending_io),
                    timeout=_STOP_TIMEOUT_SECONDS,
                )
                if pending:
                    raise RuntimeError(
                        "DingTalk platform requests still running",
                    )
            # Keep failed finalizations pending on disk for the next start.
            for card in (
                []
                if getattr(self, "_journal_owner", False)
                else list(self._active_cards.values())
            ):
                if card.state not in (FINISHED, FAILED):
                    try:
                        await self._stream_ai_card(
                            card,
                            card.last_streamed_content
                            or AI_CARD_RECOVERY_FINAL_TEXT,
                            finalize=True,
                        )
                    except Exception:
                        logger.warning(
                            "DingTalk card finalization deferred",
                            exc_info=True,
                        )
            if self._http is not None:
                await self._http.close()
                if not self._http.closed:
                    raise RuntimeError("DingTalk HTTP session did not close")
            self._http = None
            self._client = None
            self._oauth_sdk = self._robot_sdk = self._card_sdk = None
            self._stream_thread = None
            self._stream_event_loop = None
            self._loop = None
            self._processing_message_ids.clear()
            self._token_value = None
            self._token_expires_at = 0
            self._state = "stopped"
            self._last_error = None
        except BaseException as exc:
            self._state = "stop_failed"
            self._last_error = type(exc).__name__
            raise

    @owned_io
    async def _send_payload_via_session_webhook(
        self,
        session_webhook: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Send one message via DingTalk sessionWebhook with given JSON
        payload (e.g. msgtype text, markdown, image, file). Returns True
        on success.
        """
        msgtype = payload.get("msgtype", "?")
        session_in_url = session_param_from_webhook_url(session_webhook)
        logger.debug("DingTalk webhook send: msgtype=%s", msgtype)
        try:
            async with self._http.post(
                session_webhook,
                json=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            ) as resp:
                body_text = await resp.text()
                body_json = json.loads(body_text)
                if (
                    not isinstance(body_json, dict)
                    or type(
                        body_json.get("errcode"),
                    )
                    is not int
                ):
                    raise ValueError("DingTalk response has no valid errcode")
                errcode = body_json["errcode"]
                errmsg = body_json.get("errmsg", "")
                if errcode != 0:
                    logger.warning(
                        "dingtalk sessionWebhook POST API error: msgtype=%s "
                        "session_from_url=%s errcode=%s errmsg=%s body=%s",
                        msgtype,
                        session_in_url,
                        errcode,
                        errmsg,
                        body_text[:300],
                    )
                    return False
                if not 200 <= resp.status < 300:
                    raise ValueError(
                        "DingTalk response status is inconsistent",
                    )
                logger.info(
                    "dingtalk sessionWebhook POST ok: msgtype=%s status=%s "
                    "errcode=%s",
                    msgtype,
                    resp.status,
                    errcode,
                )
                return True
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            # Once POST begins, absent or unreadable acknowledgement cannot
            # establish rejection. Never let it trigger another delivery.
            raise TimeoutError("DingTalk delivery outcome is unknown") from exc

    @owned_io
    async def _send_robot_message(
        self,
        *,
        msg_key: str,
        msg_param: str,
        conversation_id: str,
        is_group: bool,
        sender_staff_id: str,
        caller: str = "",
    ) -> bool:
        """Unified robot message sender using robot_1_0 SDK."""
        token = await self._get_access_token()
        sdk_headers_kwargs = {
            "x_acs_dingtalk_access_token": token,
        }
        runtime = self._sdk.tea_util_models.RuntimeOptions()
        try:
            if is_group:
                request = self._sdk.dingtalk_robot_models.OrgGroupSendRequest(
                    robot_code=self.robot_code,
                    open_conversation_id=conversation_id,
                    msg_key=msg_key,
                    msg_param=msg_param,
                )
                headers = self._sdk.dingtalk_robot_models.OrgGroupSendHeaders(
                    **sdk_headers_kwargs,
                )
                await self._robot_sdk.org_group_send_with_options_async(
                    request,
                    headers,
                    runtime,
                )
            else:
                if not sender_staff_id:
                    logger.warning(
                        "dingtalk %s: no sender_staff_id for DM, "
                        "cannot send",
                        caller,
                    )
                    return False
                request = self._sdk.dingtalk_robot_models.BatchSendOTORequest(
                    robot_code=self.robot_code,
                    user_ids=[sender_staff_id],
                    msg_key=msg_key,
                    msg_param=msg_param,
                )
                headers = self._sdk.dingtalk_robot_models.BatchSendOTOHeaders(
                    **sdk_headers_kwargs,
                )
                await self._robot_sdk.batch_send_otowith_options_async(
                    request,
                    headers,
                    runtime,
                )
            logger.info(
                "dingtalk %s ok: is_group=%s msg_key=%s",
                caller,
                is_group,
                msg_key,
            )
            return True
        except (TimeoutError, aiohttp.ClientConnectionError):
            raise
        except Exception as exc:
            self._sdk.raise_uncertain(exc)
            logger.exception(
                "dingtalk %s failed: is_group=%s msg_key=%s",
                caller,
                is_group,
                msg_key,
            )
            return False

    @owned_io
    async def _upload_media(
        self,
        data: bytes,
        media_type: str,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Upload media via DingTalk Open API and return media_id."""
        logger.info(
            "dingtalk upload_media: type=%s size=%s filename=%s",
            media_type,
            len(data),
            filename or "(none)",
        )
        token = await self._get_access_token()
        # Use oapi media upload (api.dingtalk.com upload returns 404).
        # Doc:
        # https://open.dingtalk.com/document/development/upload-media-files
        oapi_base = self.endpoint or "https://oapi.dingtalk.com"
        url = (
            f"{oapi_base}/media/upload"
            f"?access_token={token}&type={media_type}"
        )
        ext = "jpg" if media_type == "image" else "bin"
        name = filename or f"upload.{ext}"
        logger.info(f"dingtalk upload_media: name={name}")
        form = aiohttp.FormData()
        form.add_field(
            "media",
            data,
            filename=name,
            content_type=content_type
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream",
        )
        try:
            async with self._http.post(url, data=form) as resp:
                result = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk upload_media failed: type=%s status=%s "
                        "body=%s",
                        media_type,
                        resp.status,
                        result,
                    )
                    return None
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    logger.warning(
                        "dingtalk upload_media oapi err: type=%s errcode=%s",
                        media_type,
                        errcode,
                    )
                    return None
                media_id = (
                    result.get("media_id")
                    or result.get("mediaId")
                    or (result.get("result") or {}).get("media_id")
                    or (result.get("result") or {}).get("mediaId")
                )
                if media_id:
                    mid_preview = (
                        media_id[:32] + "..."
                        if len(media_id) > 32
                        else media_id
                    )
                    logger.info(
                        "dingtalk upload_media ok: type=%s media_id=%s",
                        media_type,
                        mid_preview,
                    )
                else:
                    logger.warning(
                        "dingtalk upload_media: no media_id in response",
                    )
                return media_id
        except Exception:
            logger.exception(
                "dingtalk upload_media failed: type=%s filename=%s",
                media_type,
                filename,
            )
            return None

    @owned_io
    async def _fetch_bytes_from_url(self, url: str) -> Optional[bytes]:
        """Download binary content from URL. Returns None on failure.

        Supports http(s):// and file:// URLs. file:// is read from local disk.
        """
        logger.info(
            "dingtalk fetch_bytes_from_url: url=%s",
            url[:80] + "..." if len(url) > 80 else url,
        )
        try:
            path = file_url_to_local_path(url)
            if path is not None:
                data = await asyncio.to_thread(Path(path).read_bytes)
                logger.info(
                    "dingtalk fetch_bytes_from_url ok: size=%s (file)",
                    len(data),
                )
                return data
            if url.strip().lower().startswith("file:"):
                logger.warning(
                    f"dingtalk fetch_bytes_from_url: empty file path for "
                    f"url={url[:80]}",
                )
                return None
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk fetch_bytes_from_url failed: status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                logger.info(
                    "dingtalk fetch_bytes_from_url ok: size=%s",
                    len(data),
                )
                return data
        except Exception:
            logger.exception(
                "dingtalk fetch_bytes_from_url failed: url=%s",
                url[:80],
            )
            return None

    def _run_stream_forever(self) -> None:
        """Run stream loop; on _stop_event close websocket and exit cleanly."""
        logger.info(
            "dingtalk stream thread started (client_id=%s)",
            self.client_id,
        )
        try:
            if self._client:
                asyncio.run(self._stream_loop())
        except Exception:
            logger.exception("dingtalk stream thread failed")
        finally:
            self._stream_event_loop = None
            self._stop_event.set()
            logger.info("dingtalk stream thread stopped")

    async def _stream_loop(self) -> None:
        """
        Drive DingTalkStreamClient.start() and stop when _stop_event is set.
        Closes client.websocket and cancels tasks to avoid "Task was destroyed
        but it is pending" on process exit.

        Includes a liveness watchdog that detects system sleep/wake by
        comparing wall-clock time elapsed vs expected interval.  On macOS,
        asyncio timers freeze during sleep, so the SDK's built-in keepalive
        may fail to detect a stale connection.  The watchdog forces a
        reconnect when a time jump is detected.
        """
        client = self._client
        if not client:
            return
        stream_loop = asyncio.get_running_loop()
        self._stream_event_loop = stream_loop
        self._stream_stop_signal = asyncio.Event()
        main_task = asyncio.create_task(client.start())

        async def stop_watcher() -> None:
            while not self._stop_event.is_set():
                self._update_connection_state()
                try:
                    await asyncio.wait_for(
                        self._stream_stop_signal.wait(),
                        0.5,
                    )
                except asyncio.TimeoutError:
                    pass
            if client.websocket is not None:
                try:
                    await client.websocket.close()
                except Exception:
                    pass
            while not main_task.done():
                main_task.cancel()
                await asyncio.sleep(0.1)

        async def liveness_watchdog() -> None:
            """Detect system sleep/wake via wall-clock time jump.

            If asyncio.sleep(30) actually takes >90s of real time, the
            system likely just woke from sleep.  Force-close the websocket
            so the SDK's while-True reconnect loop can trigger.

            Does NOT break after detection — keeps monitoring so repeated
            sleep/wake cycles are also covered (SDK reconnects internally
            via its while-True loop without exiting main_task).
            """
            last_wall = time.time()
            while not self._stop_event.is_set():
                await asyncio.sleep(_STREAM_WATCHDOG_INTERVAL_SECONDS)
                if self._stop_event.is_set():
                    break
                now = time.time()
                elapsed = now - last_wall
                last_wall = now
                if elapsed > _STREAM_WATCHDOG_STALE_SECONDS:
                    logger.warning(
                        "dingtalk: liveness watchdog detected "
                        "wake-from-sleep (elapsed=%.0fs, "
                        "expected~%ds); forcing reconnect...",
                        elapsed,
                        _STREAM_WATCHDOG_INTERVAL_SECONDS,
                    )
                    ws = client.websocket
                    if ws is not None:
                        try:
                            await asyncio.wait_for(
                                ws.close(),
                                timeout=15,
                            )
                        except (asyncio.TimeoutError, Exception):
                            pass

        watcher_task = asyncio.create_task(stop_watcher())
        watchdog_task = asyncio.create_task(liveness_watchdog())
        try:
            await main_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("dingtalk stream start() failed")
        watcher_task.cancel()
        watchdog_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        # Cancel remaining tasks (e.g. background_task) so loop exits cleanly
        loop = asyncio.get_running_loop()
        pending = [
            t
            for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.done()
        ]
        for t in pending:
            t.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=4.0,
                )
            except asyncio.TimeoutError:
                pass
        if self._stream_event_loop is stream_loop:
            self._stream_event_loop = None

    @staticmethod
    def _is_websocket_open(websocket: Any) -> bool:
        """Return whether an SDK websocket reports an open state."""
        if websocket is None:
            return False
        state = getattr(websocket, "state", None)
        if state is not None:
            return getattr(state, "name", None) == "OPEN"
        return not bool(getattr(websocket, "closed", True))

    @staticmethod
    async def _ping_websocket(websocket: Any) -> None:
        """Send a WebSocket Ping and wait for its matching Pong."""
        pong_waiter = await websocket.ping()
        await pong_waiter

    def _update_connection_state(self) -> None:
        if not self._active or self._client is None:
            return
        if self._is_websocket_open(self._client.websocket):
            self._state = "running"
            self._last_error = None
        else:
            error = self._client.connection_error
            if self._state == "running" or error:
                self._state = "reconnecting"
            self._last_error = error

    async def health_check(self) -> Dict[str, Any]:
        """Actively verify the DingTalk Stream WebSocket connection."""
        self._update_connection_state()
        if not self.enabled:
            return {
                "channel": self.channel,
                "state": self._state,
                "error": self._last_error,
                "status": "disabled",
                "detail": "DingTalk channel is disabled.",
            }
        issues = []
        if self._last_error:
            issues.append(self._last_error)
        websocket = None
        if self._client is None:
            issues.append("Stream client not initialized")
        else:
            websocket = getattr(self._client, "websocket", None)
            if not self._is_websocket_open(websocket):
                issues.append("WebSocket connection is not open")
        stream_thread_alive = (
            self._stream_thread is not None and self._stream_thread.is_alive()
        )
        if not stream_thread_alive:
            issues.append("Stream thread is not running")
        stream_loop = self._stream_event_loop
        if stream_thread_alive and (
            stream_loop is None or not stream_loop.is_running()
        ):
            issues.append("Stream event loop is not running")
        if self._http is None or self._http.closed:
            issues.append("HTTP session not available")
        if not issues and websocket is not None and stream_loop is not None:
            ping_coro = self._ping_websocket(websocket)
            try:
                ping_future = asyncio.run_coroutine_threadsafe(
                    ping_coro,
                    stream_loop,
                )
            except RuntimeError:
                ping_coro.close()
                issues.append("Stream event loop is not available")
            else:
                try:
                    await asyncio.wait_for(
                        asyncio.wrap_future(ping_future),
                        timeout=_STREAM_HEALTH_PING_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    ping_future.cancel()
                    issues.append("WebSocket Ping timed out")
                except asyncio.CancelledError:
                    ping_future.cancel()
                    current_task = asyncio.current_task()
                    if current_task is not None and current_task.cancelling():
                        raise
                    issues.append("WebSocket Ping was cancelled")
                except Exception as exc:
                    issues.append(
                        f"WebSocket Ping failed: {type(exc).__name__}",
                    )
        if issues:
            return {
                "channel": self.channel,
                "state": self._state,
                "error": self._last_error,
                "status": "unhealthy",
                "detail": "; ".join(issues),
            }
        return {
            "channel": self.channel,
            "state": self._state,
            "error": self._last_error,
            "status": "healthy",
            "detail": "DingTalk Stream WebSocket responded to Ping.",
        }

    @owned_io
    async def _send_emotion(
        self,
        open_msg_id: str,
        open_conversation_id: str,
        emoji_name: str,
        *,
        recall: bool = False,
        strict: bool = False,
    ) -> None:
        """Add or recall an emoji reaction on a message.

        Args:
            open_msg_id: Target message ID.
            open_conversation_id: Conversation ID.
            emoji_name: Display name (e.g. "🤔Thinking", "🥳Done").
            recall: If True, recall the reaction instead of adding it.
        """
        if not self._robot_sdk or not open_msg_id or not open_conversation_id:
            return
        action = "recall" if recall else "reply"
        models = self._sdk.dingtalk_robot_models
        try:
            token = await self._get_access_token()
            emotion_kwargs = {
                "robot_code": self.robot_code,
                "open_msg_id": open_msg_id,
                "open_conversation_id": open_conversation_id,
                "emotion_type": 2,
                "emotion_name": emoji_name,
            }
            runtime = self._sdk.tea_util_models.RuntimeOptions()
            if recall:
                emotion_kwargs[
                    "text_emotion"
                ] = models.RobotRecallEmotionRequestTextEmotion(
                    emotion_id="2659900",
                    emotion_name=emoji_name,
                    text=emoji_name,
                    background_id="im_bg_1",
                )
                request = models.RobotRecallEmotionRequest(
                    **emotion_kwargs,
                )
                sdk_headers = models.RobotRecallEmotionHeaders(
                    x_acs_dingtalk_access_token=token,
                )
                await self._robot_sdk.robot_recall_emotion_with_options_async(
                    request,
                    sdk_headers,
                    runtime,
                )
            else:
                emotion_kwargs[
                    "text_emotion"
                ] = models.RobotReplyEmotionRequestTextEmotion(
                    emotion_id="2659900",
                    emotion_name=emoji_name,
                    text=emoji_name,
                    background_id="im_bg_1",
                )
                request = models.RobotReplyEmotionRequest(
                    **emotion_kwargs,
                )
                sdk_headers = models.RobotReplyEmotionHeaders(
                    x_acs_dingtalk_access_token=token,
                )
                await self._robot_sdk.robot_reply_emotion_with_options_async(
                    request,
                    sdk_headers,
                    runtime,
                )
            logger.info(
                "dingtalk _send_emotion: %s %s on msg=%s",
                action,
                emoji_name,
                open_msg_id[:24] if open_msg_id else "",
            )
        except Exception:
            if strict:
                raise
            logger.debug(
                "dingtalk _send_emotion %s failed",
                action,
                exc_info=True,
            )

    @owned_io
    async def _create_ai_card(
        self,
        conversation_id: str,
        meta: Optional[Dict[str, Any]] = None,
        inbound: bool = True,
        force: bool = False,
        on_created=None,
    ) -> Optional[ActiveAICard]:
        if self._card_sdk is None or (
            not force and not self._ai_card_enabled()
        ):
            logger.warning(
                "dingtalk create ai card skipped: enabled=%s sdk_ready=%s "
                "message_type=%s has_template=%s has_robot=%s force=%s",
                self._ai_card_enabled(),
                self._card_sdk is not None,
                self.message_type,
                bool(self.card_template_id),
                bool(self.robot_code),
                force,
            )
            return None
        models = self._sdk.dingtalk_card_models
        token = await self._get_access_token()
        card_instance_id = f"card_{uuid4()}"
        meta = meta or {}
        sender_staff_id = meta.get("sender_staff_id") or ""
        is_group = bool(meta.get("is_group"))
        card_param_map: Dict[str, str] = {self.card_template_key: ""}
        if self.card_auto_layout:
            card_param_map["config"] = json.dumps({"autoLayout": True})

        sdk_headers = models.CreateCardHeaders(
            x_acs_dingtalk_access_token=token,
        )
        runtime = self._sdk.tea_util_models.RuntimeOptions()

        # Resolve @mention for AI card in group chat.
        # card_at_user_ids on CreateCardRequest accepts List[str] of
        # enterprise userId (senderStaffId).  Only set when available.
        card_at_user_ids: Optional[List[str]] = None
        card_user_id_type: Optional[int] = None
        if self.at_sender_on_reply and is_group and sender_staff_id:
            card_at_user_ids = [sender_staff_id]
            card_user_id_type = 1

        create_request = models.CreateCardRequest(
            card_template_id=self.card_template_id,
            out_track_id=card_instance_id,
            card_data=models.CreateCardRequestCardData(
                card_param_map=card_param_map,
            ),
            callback_type="STREAM",
            im_group_open_space_model=(
                models.CreateCardRequestImGroupOpenSpaceModel(
                    support_forward=True,
                )
            ),
            im_robot_open_space_model=(
                models.CreateCardRequestImRobotOpenSpaceModel(
                    support_forward=True,
                )
            ),
            card_at_user_ids=card_at_user_ids,
            user_id_type=card_user_id_type,
        )

        logger.info(
            "dingtalk create ai card: conversation_id=%s is_group=%s "
            "sender_staff_id=%s template_id=%s inbound=%s",
            conversation_id,
            is_group,
            sender_staff_id,
            self.card_template_id,
            inbound,
        )
        try:
            await self._card_sdk.create_card_with_options_async(
                create_request,
                sdk_headers,
                runtime,
            )
        except (TimeoutError, aiohttp.ClientConnectionError):
            raise
        except Exception as exc:
            self._sdk.raise_uncertain(exc)
            raise ChannelError(
                channel_name="dingtalk",
                message=f"create ai card failed: {exc}",
            ) from exc

        if on_created is not None:
            await on_created(
                {
                    "card_id": card_instance_id,
                    "conversation_id": conversation_id,
                    "unsettled": "true",
                },
            )

        if is_group:
            open_space_id = f"dtv1.card//IM_GROUP.{conversation_id}"
            deliver_request = models.DeliverCardRequest(
                out_track_id=card_instance_id,
                user_id_type=1,
                open_space_id=open_space_id,
                im_group_open_deliver_model=(
                    self._sdk._GroupDeliverModel(
                        robot_code=self.robot_code,
                    )
                ),
            )
        else:
            if not sender_staff_id:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=(
                        "create ai card failed: "
                        "missing sender_staff_id for IM_ROBOT"
                    ),
                )
            open_space_id = f"dtv1.card//IM_ROBOT.{sender_staff_id}"
            deliver_request = models.DeliverCardRequest(
                out_track_id=card_instance_id,
                user_id_type=1,
                open_space_id=open_space_id,
                im_robot_open_deliver_model=(
                    self._sdk._RobotDeliverModel(
                        space_type="IM_ROBOT",
                    )
                ),
            )

        deliver_headers = models.DeliverCardHeaders(
            x_acs_dingtalk_access_token=token,
        )
        logger.info(
            "dingtalk deliver ai card: conversation_id=%s open_space_id=%s",
            conversation_id,
            open_space_id,
        )
        try:
            deliver_response = (
                await self._card_sdk.deliver_card_with_options_async(
                    deliver_request,
                    deliver_headers,
                    runtime,
                )
            )
        except (TimeoutError, aiohttp.ClientConnectionError):
            raise
        except Exception as exc:
            self._sdk.raise_uncertain(exc)
            raise ChannelError(
                channel_name="dingtalk",
                message=f"deliver ai card failed: {exc}",
            ) from exc

        deliver_body = deliver_response.body if deliver_response else None
        if deliver_body:
            result = getattr(
                deliver_body,
                "result",
                None,
            )
            deliver_results = (
                getattr(result, "deliver_results", None) if result else None
            )
            if isinstance(deliver_results, list):
                failed = [
                    item
                    for item in deliver_results
                    if not getattr(
                        item,
                        "success",
                        False,
                    )
                ]
                if failed:
                    err = failed[0]
                    raise ChannelError(
                        channel_name="dingtalk",
                        message=(
                            "deliver ai card failed:"
                            f" spaceId="
                            f"{getattr(err, 'space_id', None)}"
                            f" spaceType="
                            f"{getattr(err, 'space_type', None)}"
                            f" errorMsg="
                            f"{getattr(err, 'error_msg', None)}"
                        ),
                    )

        logger.info(
            "dingtalk create ai card ok:"
            " conversation_id=%s card_instance_id=%s",
            conversation_id,
            card_instance_id,
        )

        now_ms = int(time.time() * 1000)
        card = ActiveAICard(
            card_instance_id=card_instance_id,
            access_token=token,
            conversation_id=conversation_id,
            account_id="default",
            store_path=str(self._card_store.path),
            created_at=now_ms,
            last_updated=now_ms,
            state=PROCESSING,
            last_streamed_content="",
        )
        async with self._active_cards_lock:
            key = (
                card_instance_id
                if getattr(self, "_journal_owner", False)
                else conversation_id
            )
            self._active_cards[key] = card
            if inbound:
                self._card_store.save(self._active_cards)
        return card

    @owned_io
    async def _stream_ai_card(
        self,
        card: ActiveAICard,
        content: str,
        finalize: bool = False,
    ) -> bool:
        if self._card_sdk is None or card.state in (FINISHED, FAILED):
            return False

        content = (content or "").strip()
        if not content:
            return False

        now_ms = int(time.time() * 1000)
        if not finalize:
            if content == (card.last_streamed_content or "").strip():
                return False

        if (
            now_ms - card.created_at
        ) > AI_CARD_TOKEN_PREEMPTIVE_REFRESH_SECONDS * 1000:
            card.access_token = await self._get_access_token()

        request = self._sdk.dingtalk_card_models.StreamingUpdateRequest(
            out_track_id=card.card_instance_id,
            guid=str(uuid4()),
            key=self.card_template_key,
            content=content,
            is_full=True,
            is_finalize=finalize,
            is_error=False,
        )

        async def _do_stream(token: str):
            sdk_headers = (
                self._sdk.dingtalk_card_models.StreamingUpdateHeaders(
                    x_acs_dingtalk_access_token=token,
                )
            )
            runtime = self._sdk.tea_util_models.RuntimeOptions()
            logger.debug(
                "dingtalk stream ai card: conversation_id=%s finalize=%s "
                "content_len=%s",
                card.conversation_id,
                finalize,
                len(content),
            )
            await self._card_sdk.streaming_update_with_options_async(
                request,
                sdk_headers,
                runtime,
            )

        try:
            await _do_stream(card.access_token)
        except (TimeoutError, aiohttp.ClientConnectionError):
            raise
        except Exception as first_exc:
            self._sdk.raise_uncertain(first_exc)
            is_unauthorized = (
                isinstance(first_exc, self._sdk.TeaException)
                and getattr(first_exc, "statusCode", None) == 401
            )
            error_msg = str(first_exc)
            if is_unauthorized:
                card.access_token = await self._get_access_token()
                try:
                    await _do_stream(card.access_token)
                except Exception as retry_exc:
                    self._sdk.raise_uncertain(retry_exc)
                    retry_msg = str(retry_exc)
                    if "unknownError" in retry_msg:
                        raise ChannelError(
                            channel_name="dingtalk",
                            message=(
                                "dingtalk ai card unknownError: "
                                "card_template_key mismatch?"
                            ),
                        ) from retry_exc
                    raise ChannelError(
                        channel_name="dingtalk",
                        message=f"stream ai card failed: {retry_exc}",
                    ) from retry_exc
            elif "unknownError" in error_msg:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=(
                        "dingtalk ai card unknownError: "
                        "card_template_key mismatch?"
                    ),
                ) from first_exc
            else:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=f"stream ai card failed: {first_exc}",
                ) from first_exc

        logger.debug(
            "dingtalk stream ai card ok: conversation_id=%s finalize=%s",
            card.conversation_id,
            finalize,
        )

        card.last_streamed_content = content
        card.last_updated = int(time.time() * 1000)
        if finalize:
            card.state = FINISHED
            async with self._active_cards_lock:
                key = (
                    card.card_instance_id
                    if getattr(self, "_journal_owner", False)
                    else card.conversation_id
                )
                self._active_cards.pop(key, None)
                self._card_store.save(self._active_cards)
        elif card.state == PROCESSING:
            card.state = INPUTING
            await self._save_active_cards()
        return True

    @owned_io
    async def _get_access_token(self) -> str:
        """Get and cache DingTalk accessToken for 1 hour (instance-level)."""
        if not self.client_id or not self.client_secret:
            raise ChannelError(
                channel_name="dingtalk",
                message="DingTalk client_id/client_secret missing",
            )

        now = asyncio.get_running_loop().time()
        if self._token_value and now < self._token_expires_at:
            return self._token_value

        async with self._token_lock:
            now = asyncio.get_running_loop().time()
            if self._token_value and now < self._token_expires_at:
                return self._token_value

            request = self._sdk.dingtalk_oauth_models.GetAccessTokenRequest(
                app_key=self.client_id,
                app_secret=self.client_secret,
            )
            try:
                response = await self._oauth_sdk.get_access_token_async(
                    request,
                )
            except Exception as exc:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=f"get accessToken failed: {exc}",
                ) from exc

            token = (
                response.body.access_token
                if response and response.body
                else None
            )
            if not token:
                raise ChannelError(
                    channel_name="dingtalk",
                    message="accessToken not found in SDK response",
                )

            self._token_value = token
            self._token_expires_at = (
                asyncio.get_running_loop().time() + DINGTALK_TOKEN_TTL_SECONDS
            )
            return token

    @owned_io
    async def _get_message_file_download_url(
        self,
        *,
        download_code: str,
        robot_code: str,
    ) -> Optional[str]:
        """Call DingTalk messageFiles/download to get a downloadable URL."""
        if not download_code or not robot_code:
            return None
        if self._robot_sdk is None:
            return None

        token = await self._get_access_token()
        request = (
            self._sdk.dingtalk_robot_models.RobotMessageFileDownloadRequest(
                download_code=download_code,
                robot_code=robot_code,
            )
        )
        sdk_headers = (
            self._sdk.dingtalk_robot_models.RobotMessageFileDownloadHeaders(
                x_acs_dingtalk_access_token=token,
            )
        )
        runtime = self._sdk.tea_util_models.RuntimeOptions()
        try:
            _download = (
                self._robot_sdk.robot_message_file_download_with_options_async
            )
            response = await _download(
                request,
                sdk_headers,
                runtime,
            )
        except Exception:
            logger.exception("messageFiles/download SDK call failed")
            return None

        body = response.body if response else None
        if not body:
            logger.warning("messageFiles/download: empty response body")
            return None
        logger.debug("messageFiles/download response body=%s", body)
        return getattr(body, "download_url", None)

    @owned_io
    async def _download_media_to_local(
        self,
        url: str,
        safe_key: str,
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Download media to media_dir; return local path or None.
        Suffix from Content-Type then magic bytes.
        """
        if not url or not url.strip().startswith(("http://", "https://")):
            return None
        if self._http is None:
            return None
        try:
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk media download failed status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )
                disposition = resp.headers.get(
                    "Content-Disposition",
                    "",
                )
            filename = filename_hint
            if "filename=" in disposition:
                part = (
                    disposition.split("filename=", 1)[-1].strip().strip("'\"")
                )
                if part:
                    filename = part
            suffix = ".file"
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].lower().strip()
                if ext:
                    suffix = "." + ext
            elif content_type:
                suffix = mimetypes.guess_extension(content_type) or ".file"
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{safe_key}{suffix}"
            path.write_bytes(data)
            # Fix .file/.bin with magic bytes so images get .png/.jpg etc.
            if path.suffix in (".file", ".bin"):
                real_suffix = guess_suffix_from_file_content(path)
                if real_suffix:
                    new_path = path.with_suffix(real_suffix)
                    path.rename(new_path)
                    path = new_path
                    logger.debug(
                        "dingtalk replaced suffix with %s for %s",
                        real_suffix,
                        path,
                    )
            return str(path)
        except Exception:
            logger.exception("dingtalk _download_media_to_local failed")
            return None
