# -*- coding: utf-8 -*-
"""WeCom SDK, native frames, stream state and uploads owned by one worker."""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from contextlib import asynccontextmanager
import hashlib
import logging
from pathlib import Path
import threading
import uuid

from qwenpaw.app.channels.utils import (
    file_url_to_local_path,
    materialize_data_url,
    split_text,
)

from .cards.tool_guard import (
    build_approval_card,
    build_resolved_card,
    parse_card_event,
)
from .errors import WeComDeliveryError
from .inbound import InboundDecoder
from .utils import compress_image_for_wecom, format_markdown_tables

logger = logging.getLogger(__name__)
_UPLOAD_CHUNK_SIZE = 512 * 1024
_UPLOAD_CMD_INIT = "aibot_upload_media_init"
_UPLOAD_CMD_CHUNK = "aibot_upload_media_chunk"
_UPLOAD_CMD_FINISH = "aibot_upload_media_finish"
_UPLOAD_CMDS = (_UPLOAD_CMD_INIT, _UPLOAD_CMD_CHUNK, _UPLOAD_CMD_FINISH)
_UPLOAD_ACK_TIMEOUT = 30.0
_PROCESSING_REFRESH_INTERVAL = 20.0
_PROCESSING_MAX_DURATION = 180.0
_PROCESSING_TEXT = "🤔 Thinking..."
_MAX_ROUTES = 128


class _SdkLoggerAdapter:
    def debug(self, message, *args):
        logger.debug(message, *args)

    def info(self, message, *args):
        logger.info(message, *args)

    def warn(self, message, *args):
        logger.warning(message, *args)

    def error(self, message, *args):
        logger.error(message, *args)


async def _settle(task):
    """A second cancellation must not abandon a thread or file owner."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    try:
        return task.result()
    finally:
        if cancelled:
            raise asyncio.CancelledError


class WeComPlatform(InboundDecoder):
    def __init__(self, config, on_event, on_state):
        self.config = dict(config)
        self.on_event, self.on_state = on_event, on_state
        self.share_session_in_group = bool(
            config.get("share_session_in_group", True),
        )
        workspace = config.get("workspace_dir")
        media = config.get("media_dir")
        if not media and not workspace:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            media = str(DEFAULT_MEDIA_DIR)
        self._media_dir = Path(media or Path(workspace) / "media").expanduser()
        self._roots = [self._media_dir.resolve()]
        if workspace:
            self._roots.append(Path(workspace).expanduser().resolve())
        self._client = self._ws_loop = self._ws_thread = None
        self._loop = None
        self._connected = self._stopping = False
        self._epoch = 0
        self._ready = None
        self._ws_stop_event = None
        self._thread_error = None
        self._sdk_initialized = threading.Event()
        self._stop_lock = asyncio.Lock()
        self._sdk_tasks = set()
        self._callbacks = set()
        self._operations = set()
        self._file_tasks = set()
        self._bridges = set()
        self._bridge_lock = threading.Lock()
        self._native_queue = asyncio.Queue(maxsize=_MAX_ROUTES)
        self._native_worker = None
        self._upload_lock = asyncio.Lock()
        self._upload_ack_futures = {}
        self._processed_message_ids = OrderedDict()
        self._frames = {}
        self._processing = {}
        self._keepalive_tasks = {}
        self._cards = OrderedDict()
        self._staged_cards = {}
        self._identity = None
        self._delivery_tasks = set()

    def _check_epoch(self, epoch):
        if self._stopping or not self._connected or epoch != self._epoch:
            raise WeComDeliveryError("STALE_CONNECTION_CALLBACK")

    def register_frame(self, handle, frame):
        current = self._frames.get(handle)
        if current is not None:
            return {"frame_token": handle, "connection_epoch": str(current[0])}
        if len(self._frames) >= _MAX_ROUTES:
            raise WeComDeliveryError("RESPONSE_CAPACITY")
        self._frames[handle] = (self._epoch, frame)
        return {"frame_token": handle, "connection_epoch": str(self._epoch)}

    def _frame(self, route):
        self._check_epoch(int(route.get("connection_epoch", self._epoch)))
        token = route.get("frame_token")
        if not token:
            return None
        value = self._frames.get(token)
        if value is None or value[0] != self._epoch:
            raise WeComDeliveryError("NATIVE_ROUTE_EXPIRED")
        return value[1]

    def native_route_expiry(self, route):
        """Identify native reply targets that this worker cannot ever reuse."""
        token, epoch = route.get("frame_token"), route.get("connection_epoch")
        if not token or token != route.get("response_handle"):
            return None
        try:
            recorded_epoch = int(epoch)
        except (TypeError, ValueError):
            return None
        if recorded_epoch < 0 or str(recorded_epoch) != epoch:
            return None
        if recorded_epoch != self._epoch:
            return "CONNECTION_EPOCH_EXPIRED"
        frame = self._frames.get(token)
        if frame is None or frame[0] != recorded_epoch:
            return "NATIVE_ROUTE_EXPIRED"
        return None

    async def start(self):
        if self._ws_thread is not None:
            raise RuntimeError("PLATFORM_ALREADY_STARTED")
        if not self.config.get("bot_id") or not self.config.get("secret"):
            raise WeComDeliveryError("CREDENTIALS_REQUIRED")
        self._loop = asyncio.get_running_loop()
        self._ready = self._loop.create_future()
        self._native_worker = asyncio.create_task(self._consume_native())
        self._ws_thread = threading.Thread(
            target=self._run_ws,
            daemon=True,
            name="wecom-ws",
        )
        self._ws_thread.start()
        try:
            async with asyncio.timeout(30):
                await asyncio.shield(self._ready)
        except BaseException:
            await self.stop()
            raise

    def _post(self, callback, *args):
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(callback, *args)

    def _schedule_state(self, state, epoch):
        if len(self._callbacks) >= _MAX_ROUTES:
            self._connected = False
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(
                    WeComDeliveryError("CALLBACK_CAPACITY"),
                )
            return
        task = asyncio.create_task(self._state_changed(state, epoch))
        self._callbacks.add(task)
        task.add_done_callback(self._callback_done)

    def _callback_done(self, task):
        self._callbacks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "WeCom callback failed: %s",
                type(task.exception()).__name__,
            )

    async def _state_changed(self, state, epoch):
        if self._stopping or epoch != self._epoch:
            return
        self._connected = state == "connected"
        if not self._connected:
            for task in tuple(self._keepalive_tasks.values()):
                task.cancel()
            for _, future in tuple(self._upload_ack_futures.values()):
                if not future.done():
                    future.set_exception(
                        WeComDeliveryError(
                            "PLATFORM_RESULT_UNKNOWN",
                            side_effect_possible=True,
                        ),
                    )
        await self.on_state(state)
        if self._stopping or epoch != self._epoch:
            return
        if state == "connected" and not self._ready.done():
            self._ready.set_result(None)
        elif state == "failed" and not self._ready.done():
            self._ready.set_exception(WeComDeliveryError("CONNECTION_FAILED"))

    def _native(self, kind, frame, epoch):
        if self._stopping or epoch != self._epoch:
            return
        try:
            self._native_queue.put_nowait((kind, frame, epoch))
        except asyncio.QueueFull:
            self._connected = False
            self._schedule_state("failed", epoch)
            # Stop admission rather than silently claiming a dropped event was accepted.
            if self._ws_loop and self._client:
                self._ws_loop.call_soon_threadsafe(self._client.disconnect)

    async def _consume_native(self):
        while True:
            kind, frame, epoch = await self._native_queue.get()
            try:
                self._check_epoch(epoch)
                if kind == "message":
                    await self._on_message(frame)
                elif kind == "card":
                    await self._handle_card(frame)
                elif self.config.get("welcome_text"):
                    await self._call(
                        "reply_welcome",
                        frame,
                        {
                            "msgtype": "text",
                            "text": {"content": self.config["welcome_text"]},
                        },
                    )
                self._check_epoch(epoch)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "WeCom native callback failed: %s",
                    type(exc).__name__,
                )
            finally:
                self._native_queue.task_done()

    def _track_sdk(self, method):
        async def tracked(*args, **kwargs):
            task = asyncio.current_task()
            self._sdk_tasks.add(task)
            try:
                return await method(*args, **kwargs)
            finally:
                self._sdk_tasks.discard(task)

        return tracked

    async def _sdk_main(self):
        # Construct the emitter, client and asyncio primitives on their owning loop.
        from aibot import WSClient, WSClientOptions

        self._ws_stop_event = asyncio.Event()
        self._client = WSClient(
            WSClientOptions(
                bot_id=self.config["bot_id"],
                secret=self.config["secret"],
                max_reconnect_attempts=self.config.get(
                    "max_reconnect_attempts",
                    -1,
                ),
                logger=_SdkLoggerAdapter(),
                **(
                    {"ws_url": self.config["ws_url"].strip()}
                    if self.config.get("ws_url", "").strip()
                    else {}
                ),
            ),
        )
        manager = self._client._ws_manager
        original_raw = manager.on_message

        def raw(frame):
            req_id = (frame.get("headers") or {}).get("req_id", "")
            if req_id.startswith(_UPLOAD_CMDS):
                self._post(self._upload_ack, req_id, frame, self._epoch)
            elif original_raw:
                original_raw(frame)

        manager.on_message = raw
        # Preserve the historical close-only heartbeat fix: receive owns reconnect.
        heartbeat = manager._send_heartbeat

        async def send_heartbeat():
            if manager._missed_pong_count >= manager._max_missed_pong:
                if manager._ws:
                    await manager._ws.close()
                return
            await heartbeat()

        manager._send_heartbeat = send_heartbeat
        # SDK 1.0.2 reconnect runs inside receive: never cancel/await itself.
        cleanup = manager._cleanup_ws

        async def cleanup_ws():
            if manager._receive_task is asyncio.current_task():
                manager._receive_task = None
            await cleanup()

        manager._cleanup_ws = cleanup_ws
        for name in (
            "_receive_loop",
            "_heartbeat_loop",
            "_process_reply_queue",
            "_async_disconnect",
        ):
            setattr(manager, name, self._track_sdk(getattr(manager, name)))

        def authenticated():
            if not self._stopping:
                self._epoch += 1
                self._post(self._schedule_state, "connected", self._epoch)

        def disconnected(*_):
            self._epoch += 1
            self._post(self._schedule_state, "disconnected", self._epoch)

        self._client.on("authenticated", authenticated)
        self._client.on("disconnected", disconnected)
        self._client.on(
            "reconnecting",
            lambda *_: self._post(
                self._schedule_state,
                "connecting",
                self._epoch,
            ),
        )
        self._client.on(
            "error",
            lambda *_: self._post(self._schedule_state, "failed", self._epoch),
        )
        for event, kind in (
            ("message", "message"),
            ("event.enter_chat", "welcome"),
            ("event.template_card_event", "card"),
        ):
            self._client.on(
                event,
                lambda frame, kind=kind: self._post(
                    self._native,
                    kind,
                    frame,
                    self._epoch,
                ),
            )
        self._sdk_initialized.set()
        connect = asyncio.create_task(self._track_sdk(self._client.connect)())
        self._sdk_tasks.add(connect)
        connect.add_done_callback(self._sdk_tasks.discard)
        await self._ws_stop_event.wait()

    def _run_ws(self):
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        self._ws_loop = ws_loop
        try:
            ws_loop.run_until_complete(self._sdk_main())
            ws_loop.run_until_complete(ws_loop.shutdown_asyncgens())
        except BaseException as exc:
            self._thread_error = exc
            self._post(self._schedule_state, "failed", self._epoch)
        finally:
            self._sdk_initialized.set()
            # The loop remains available as evidence if a live task could not settle.
            if not asyncio.all_tasks(ws_loop):
                ws_loop.close()

    async def _shutdown_sdk(self):
        if self._client is not None:
            manager = self._client._ws_manager
            manager._is_manual_close = True
            self._client._started = False
            tasks = set(self._sdk_tasks)
            tasks.update(
                t
                for t in (manager._receive_task, manager._heartbeat_task)
                if t
            )
            tasks.discard(asyncio.current_task())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            manager._clear_pending_messages("Channel stopped")
            ws = manager._ws
            if ws is not None:
                await ws.close()
                await ws.wait_closed()
                manager._ws = None
            if self._sdk_tasks:
                raise RuntimeError("SDK_TASKS_NOT_SETTLED")
        self._ws_stop_event.set()

    async def stop(self):
        async with self._stop_lock:
            await self._stop_owned()

    async def _stop_owned(self):
        self._stopping = True
        self._connected = False
        self._epoch += 1
        current = asyncio.current_task()
        tasks = {
            self._native_worker,
            *self._callbacks,
            *self._keepalive_tasks.values(),
            *self._operations,
            *self._delivery_tasks,
        }
        tasks.discard(None)
        tasks.discard(current)
        for task in tasks:
            task.cancel()
        if tasks:
            await _settle(
                asyncio.ensure_future(
                    asyncio.gather(*tasks, return_exceptions=True),
                ),
            )
        # File workers retain paths until the real OS operation has returned.
        if self._file_tasks:
            await _settle(
                asyncio.ensure_future(
                    asyncio.gather(*self._file_tasks, return_exceptions=True),
                ),
            )
        for _, future in tuple(self._upload_ack_futures.values()):
            if not future.done():
                future.cancel()
        thread = self._ws_thread
        if (
            thread is not None
            and thread.is_alive()
            and not self._sdk_initialized.is_set()
        ):
            if not await self._file_work(self._sdk_initialized.wait, 10):
                raise RuntimeError("SDK_STOP_NOT_READY")
        ws_loop = self._ws_loop
        if thread is not None and thread.is_alive():
            if (
                ws_loop is None
                or not ws_loop.is_running()
                or self._ws_stop_event is None
            ):
                raise RuntimeError("SDK_STOP_NOT_READY")
            bridge = asyncio.run_coroutine_threadsafe(
                self._shutdown_sdk(),
                ws_loop,
            )
            await _settle(asyncio.wrap_future(bridge))
            await _settle(
                asyncio.create_task(asyncio.to_thread(thread.join, 10)),
            )
            if thread.is_alive():
                raise RuntimeError("SDK_THREAD_NOT_SETTLED")
        if ws_loop is not None and not ws_loop.is_closed():
            raise RuntimeError("SDK_LOOP_NOT_SETTLED")
        with self._bridge_lock:
            if self._bridges:
                raise RuntimeError("SDK_OPERATIONS_NOT_SETTLED")
        self._client = self._ws_thread = self._ws_loop = None
        self._frames.clear()
        self._cards.clear()
        self._staged_cards.clear()
        self._processing.clear()
        self._keepalive_tasks.clear()
        while not self._native_queue.empty():
            self._native_queue.get_nowait()
            self._native_queue.task_done()

    @asynccontextmanager
    async def delivery(self):
        task = asyncio.current_task()
        owned = task not in self._delivery_tasks
        self._delivery_tasks.add(task)
        try:
            yield
        finally:
            if owned:
                self._delivery_tasks.discard(task)

    async def _call(self, method, *args, effect=True, **kwargs):
        epoch = self._epoch
        self._check_epoch(epoch)
        ws_loop, client = self._ws_loop, self._client
        if client is None or ws_loop is None or not ws_loop.is_running():
            raise WeComDeliveryError("NOT_CONNECTED")
        task = asyncio.current_task()
        self._operations.add(task)

        async def perform():
            self._check_epoch(epoch)
            return await getattr(client, method)(*args, **kwargs)

        bridge = asyncio.run_coroutine_threadsafe(perform(), ws_loop)
        with self._bridge_lock:
            self._bridges.add(bridge)
        wrapped = asyncio.wrap_future(bridge)
        completed = False
        try:
            # A cancelled RPC waits for the platform effect instead of abandoning it.
            result = await _settle(wrapped)
            completed = True
            self._check_epoch(epoch)
            if effect and (
                not isinstance(result, dict) or result.get("errcode") != 0
            ):
                raise WeComDeliveryError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            return result
        except asyncio.CancelledError:
            raise
        except WeComDeliveryError as exc:
            if completed and effect and not exc.side_effect_possible:
                raise WeComDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        except Exception as exc:
            rejected = str(exc).startswith("Reply ack error: errcode=")
            raise WeComDeliveryError(
                "PLATFORM_REJECTED" if rejected else "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=effect and not rejected,
            ) from exc
        finally:
            self._operations.discard(task)
            with self._bridge_lock:
                self._bridges.discard(bridge)

    async def _file_work(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._file_tasks.add(task)
        try:
            return await _settle(task)
        finally:
            self._file_tasks.discard(task)

    def _upload_ack(self, req_id, frame, epoch):
        pending = self._upload_ack_futures.get(req_id)
        if pending is not None and pending[0] == epoch:
            future = pending[1]
            if not future.done():
                future.set_result(frame)

    async def _send_ws_cmd(self, cmd, body):
        from aibot import generate_req_id

        epoch = self._epoch
        self._check_epoch(epoch)
        req_id = generate_req_id(cmd)
        future = asyncio.get_running_loop().create_future()
        self._upload_ack_futures[req_id] = (epoch, future)

        async def send():
            self._check_epoch(epoch)
            await self._client._ws_manager.send(
                {"cmd": cmd, "headers": {"req_id": req_id}, "body": body},
            )

        bridge = asyncio.run_coroutine_threadsafe(send(), self._ws_loop)
        with self._bridge_lock:
            self._bridges.add(bridge)
        try:
            await _settle(asyncio.wrap_future(bridge))
            ack = await asyncio.wait_for(
                asyncio.shield(future),
                _UPLOAD_ACK_TIMEOUT,
            )
            self._check_epoch(epoch)
            if ack.get("errcode") != 0:
                raise WeComDeliveryError("PLATFORM_REJECTED")
            body = ack.get("body")
            if not isinstance(body, dict):
                raise WeComDeliveryError(
                    "UPLOAD_ACK_INVALID",
                    side_effect_possible=True,
                )
            return body
        except asyncio.CancelledError:
            raise
        except WeComDeliveryError:
            raise
        except Exception as exc:
            raise WeComDeliveryError(
                "UPLOAD_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        finally:
            self._upload_ack_futures.pop(req_id, None)
            if not future.done():
                future.cancel()
            with self._bridge_lock:
                self._bridges.discard(bridge)

    @asynccontextmanager
    async def _materialize(self, path, filename_hint):
        manager = materialize_data_url(
            path,
            self._media_dir,
            filename_hint=filename_hint,
        )
        enter = asyncio.create_task(manager.__aenter__())
        try:
            value = await _settle(enter)
        except asyncio.CancelledError:
            if (
                enter.done()
                and not enter.cancelled()
                and enter.exception() is None
            ):
                await _settle(
                    asyncio.create_task(manager.__aexit__(None, None, None)),
                )
            raise
        try:
            yield value
        finally:
            await _settle(
                asyncio.create_task(manager.__aexit__(None, None, None)),
            )

    async def _upload_media(self, path, media_type, filename_hint=None):
        async with self.delivery():
            return await self._upload_media_owned(
                path,
                media_type,
                filename_hint,
            )

    async def _upload_media_owned(self, path, media_type, filename_hint=None):
        if not path.startswith("data:"):
            local = (
                Path(file_url_to_local_path(path) or path)
                .expanduser()
                .resolve()
            )
            if not any(local.is_relative_to(root) for root in self._roots):
                raise WeComDeliveryError("MEDIA_PATH_UNAUTHORIZED")
            if not local.is_file():
                raise WeComDeliveryError("MEDIA_FILE_UNAVAILABLE")
        async with self._materialize(path, filename_hint) as materialized:
            if materialized is None:
                raise WeComDeliveryError("MEDIA_FILE_UNAVAILABLE")
            local = Path(
                file_url_to_local_path(materialized.path) or materialized.path,
            )
            if media_type == "image":
                data, filename = await self._file_work(
                    compress_image_for_wecom,
                    str(local),
                )
            else:
                data, filename = await self._file_work(
                    lambda: (local.read_bytes(), local.name),
                )
            if materialized.filename:
                filename = (
                    str(
                        Path(materialized.filename).with_suffix(
                            Path(filename).suffix,
                        ),
                    )
                    if media_type == "image"
                    else materialized.filename
                )
            async with self._upload_lock:
                total_chunks = (
                    len(data) + _UPLOAD_CHUNK_SIZE - 1
                ) // _UPLOAD_CHUNK_SIZE
                value = await self._send_ws_cmd(
                    _UPLOAD_CMD_INIT,
                    {
                        "type": media_type,
                        "filename": filename,
                        "total_size": len(data),
                        "total_chunks": total_chunks,
                        "md5": hashlib.md5(data).hexdigest(),
                    },
                )
                upload_id = value.get("upload_id")
                if not isinstance(upload_id, str) or not upload_id:
                    raise WeComDeliveryError(
                        "UPLOAD_ACK_INVALID",
                        side_effect_possible=True,
                    )
                for index in range(total_chunks):
                    chunk = data[
                        index
                        * _UPLOAD_CHUNK_SIZE : (index + 1)
                        * _UPLOAD_CHUNK_SIZE
                    ]
                    await self._send_ws_cmd(
                        _UPLOAD_CMD_CHUNK,
                        {
                            "upload_id": upload_id,
                            "chunk_index": index,
                            "base64_data": base64.b64encode(chunk).decode(),
                        },
                    )
                value = await self._send_ws_cmd(
                    _UPLOAD_CMD_FINISH,
                    {"upload_id": upload_id},
                )
                media_id = value.get("media_id")
                if not isinstance(media_id, str) or not media_id:
                    raise WeComDeliveryError(
                        "UPLOAD_ACK_INVALID",
                        side_effect_possible=True,
                    )
                return media_id

    async def _cancel_processing(self, handle, *, local_only=False):
        state = self._processing.get(handle)
        if state is None:
            return ""
        task = self._keepalive_tasks.get(state["stream_id"])
        if task is None or task.done():
            if (
                task is not None
                and self._keepalive_tasks.get(state["stream_id"]) is task
            ):
                self._keepalive_tasks.pop(state["stream_id"])
            if state.get("unknown") and not local_only:
                raise WeComDeliveryError(
                    "STREAM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            return ""
        if local_only or not state.get("finishing"):
            task.cancel()
        try:
            await _settle(
                asyncio.ensure_future(
                    asyncio.gather(task, return_exceptions=True),
                ),
            )
        finally:
            if (
                task.done()
                and self._keepalive_tasks.get(state["stream_id"]) is task
            ):
                self._keepalive_tasks.pop(state["stream_id"])
        if state.get("unknown") and not local_only:
            raise WeComDeliveryError(
                "STREAM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        return state["stream_id"] if not state.get("final") else ""

    async def _processing_effect(self, route, state, final):
        try:
            await self._call(
                "reply_stream",
                self._frame(route),
                stream_id=state["stream_id"],
                content=_PROCESSING_TEXT,
                finish=final,
            )
            if final:
                state["final"] = True
        except BaseException:
            state["unknown"] = True
            raise

    async def _keepalive_processing(
        self,
        handle,
        route,
        state,
        interval=_PROCESSING_REFRESH_INTERVAL,
        max_duration=_PROCESSING_MAX_DURATION,
    ):
        elapsed = 0.0
        try:
            while elapsed + interval <= max_duration:
                await asyncio.sleep(interval)
                elapsed += interval
                await _settle(
                    asyncio.create_task(
                        self._processing_effect(route, state, False),
                    ),
                )
            state["finishing"] = True
            await _settle(
                asyncio.create_task(
                    self._processing_effect(route, state, True),
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            state["unknown"] = True
        finally:
            if (
                self._keepalive_tasks.get(state["stream_id"])
                is asyncio.current_task()
            ):
                self._keepalive_tasks.pop(state["stream_id"])

    async def prepare(self, route, sid=None):
        frame = self._frame(route)
        if frame is None:
            return {"final": "true"}
        sid = sid or uuid.uuid4().hex
        state = {"stream_id": sid, "final": False, "unknown": False}
        handle = route["response_handle"]
        self._processing[handle] = state
        await self._call(
            "reply_stream",
            frame,
            stream_id=sid,
            content=_PROCESSING_TEXT,
            finish=False,
        )
        self._keepalive_tasks[sid] = asyncio.create_task(
            self._keepalive_processing(handle, route, state),
        )
        return {
            **route,
            "stream_id": sid,
            "text": _PROCESSING_TEXT,
            "final": "false",
            "role": "processing",
        }

    async def start_stream(self, route, stream_type, text):
        if self._frame(route) is None:
            raise WeComDeliveryError("STREAMING_TARGET_UNSUPPORTED")
        sid = (
            await self._cancel_processing(route["response_handle"])
            or uuid.uuid4().hex
        )
        resource = {
            **route,
            "stream_id": sid,
            "stream_type": stream_type,
            "text": text or "",
            "final": "false",
            "sequence": "0",
        }
        return resource

    async def update_stream(self, resource, text, *, final):
        frame = self._frame(resource)
        prefix = (
            resource.get("bot_prefix") or self.config.get("bot_prefix") or ""
        )
        display = (
            text
            if resource.get("stream_type") == "reasoning"
            or resource.get("role") == "processing"
            else (prefix + "  " + text if prefix and text else text)
        )
        await self._call(
            "reply_stream",
            frame,
            stream_id=resource["stream_id"],
            content=display,
            finish=final,
        )

    async def send_parts(self, route, parts, source=None):
        source = getattr(source, "value", source) or "content_parts"
        text = "\n".join(
            p.get("text") or p.get("refusal") or ""
            for p in parts
            if p["type"] in {"text", "refusal"}
        )
        prefix = route.get("bot_prefix") or self.config.get("bot_prefix") or ""
        if source == "direct":
            text = prefix + text if text else prefix
        else:
            text = text.strip()
            if prefix and text:
                text = prefix + "  " + text
            text = format_markdown_tables(text)
        frame = self._frame(route)
        handle = route["response_handle"]
        sid = await self._cancel_processing(handle)
        sent = False
        try:
            for chunk in split_text(text) if text else ():
                if frame:
                    await self._call(
                        "reply_stream",
                        frame,
                        stream_id=sid or uuid.uuid4().hex,
                        content=chunk,
                        finish=True,
                    )
                    sid = ""
                else:
                    await self._call(
                        "send_message",
                        route["wecom_chatid"],
                        {
                            "msgtype": "markdown",
                            "markdown": {"content": chunk},
                        },
                    )
                sent = True
            if sid and frame:
                await self._call(
                    "reply_stream",
                    frame,
                    stream_id=sid,
                    content="✅ Done",
                    finish=True,
                )
                sent = True
            for part in parts:
                kind = part["type"]
                if kind in {"text", "refusal"}:
                    continue
                if kind not in {"image", "audio", "file", "video"}:
                    raise WeComDeliveryError("CONTENT_TYPE_UNSUPPORTED")
                path = part.get(
                    "data" if kind == "audio" else kind + "_url",
                ) or part.get("file_url")
                if not path:
                    raise WeComDeliveryError("MEDIA_FILE_UNAVAILABLE")
                media_type = (
                    (
                        "voice"
                        if Path(
                            file_url_to_local_path(path) or path,
                        ).suffix.lower()
                        == ".amr"
                        else "file"
                    )
                    if kind == "audio"
                    else kind
                )
                media_id = await self._upload_media(
                    path,
                    media_type,
                    part.get("filename") if path.startswith("data:") else None,
                )
                body = {
                    "msgtype": media_type,
                    media_type: {"media_id": media_id},
                }
                if frame:
                    await self._call("reply", frame, body)
                else:
                    await self._call(
                        "send_message",
                        route["wecom_chatid"],
                        body,
                    )
                sent = True
        except WeComDeliveryError as exc:
            if sent:
                raise WeComDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        state = self._processing.get(handle)
        if state is not None:
            state["final"] = True
        return {"final": "true"}

    async def cleanup_resource(self, resource, *, local_only=False):
        handle = resource["response_handle"]
        if local_only:
            await self._cancel_processing(handle, local_only=True)
            return
        state = self._processing.get(handle)
        if resource.get("role") == "processing":
            sid = await self._cancel_processing(handle)
            if not sid:
                if state and state.get("final"):
                    return
                if state and state.get("unknown"):
                    raise WeComDeliveryError(
                        "STREAM_RESULT_UNKNOWN",
                        side_effect_possible=True,
                    )
        await self.update_stream(
            resource,
            resource.get("text") or "✅ Done",
            final=True,
        )

    async def release_route(self, handle, *, local_only=False):
        state = self._processing.get(handle)
        if state is not None:
            await self._cancel_processing(handle, local_only=local_only)
        self._frames.pop(handle, None)
        self._processing.pop(handle, None)

    async def send_stream_detail(self, route, body_text):
        sid = (
            await self._cancel_processing(route["response_handle"])
            or uuid.uuid4().hex
        )
        await self._call(
            "reply_stream",
            self._frame(route),
            stream_id=sid,
            content=body_text,
            finish=True,
        )
        state = self._processing.get(route["response_handle"])
        if state is not None:
            state["final"] = True

    async def send_approval(self, route, params, identity):
        for key, binding in tuple(self._cards.items()):
            if binding.get("resolved"):
                self._cards.pop(key)
        if len(self._cards) + len(self._staged_cards) >= _MAX_ROUTES:
            raise WeComDeliveryError("APPROVAL_CAPACITY")
        self._identity = identity
        nonce = uuid.uuid4().hex
        approval = params.approval
        try:
            card = build_approval_card(
                request_id=approval.request_id,
                tool_name=approval.tool_name,
                severity=approval.severity.value,
                session_ctx={"bid": nonce},
            )
        except ValueError:
            # Preserve the old oversized-key text path before any native card effect.
            return await self.send_parts(
                route,
                params.content_parts,
                params.content_source,
            )
        frame = self._frame(route)
        if frame is None:
            raise WeComDeliveryError("APPROVAL_TARGET_UNSUPPORTED")
        self._staged_cards[params.delivery_id] = {
            "nonce": nonce,
            "request_id": approval.request_id,
            "tool_name": approval.tool_name,
            "task_id": card["task_id"],
            "route": dict(route),
            "instance_id": identity.instance_id,
            "generation": identity.generation,
        }
        body_text = "".join(
            p.get("text", "")
            for p in params.content_parts
            if p.get("type") == "text"
        )
        detail_sent = False
        try:
            await self.send_stream_detail(route, body_text)
            detail_sent = True
        except WeComDeliveryError as exc:
            if exc.side_effect_possible:
                raise
        try:
            await self._call("reply_template_card", frame, card)
        except WeComDeliveryError as exc:
            if detail_sent:
                raise WeComDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        return {"final": "true"}

    def complete_card_delivery(self, delivery_id, acknowledged):
        binding = self._staged_cards.pop(delivery_id, None)
        if binding is not None and acknowledged:
            self._cards[binding["nonce"]] = binding

    async def _handle_card(self, frame):
        if not isinstance(frame, dict):
            return False
        body = frame.get("body") or {}
        parsed = parse_card_event(body)
        if parsed is None:
            return False
        actor = parsed["user_id"]
        nonce = str(parsed["session_ctx"].get("bid") or "")
        binding = self._cards.get(nonce)
        if not actor or binding is None or self._identity is None:
            return False
        route = binding["route"]
        if (
            binding["task_id"] != parsed["task_id"]
            or binding["request_id"] != parsed["request_id"]
            or binding["instance_id"] != self._identity.instance_id
            or binding["generation"] != self._identity.generation
        ):
            return False
        if any(
            body.get(k) and str(body[k]) != route.get(v)
            for k, v in (
                ("chatid", "wecom_chatid"),
                ("chattype", "wecom_chat_type"),
            )
        ):
            return False
        if route.get("wecom_chat_type") != "group" and actor != route.get(
            "wecom_sender_id",
        ):
            return False
        if binding.get("resolved"):
            return True
        req_id = str(
            (frame.get("headers") or {}).get("req_id") or uuid.uuid4().hex,
        )
        value = {
            "event_id": "wecom:card:" + req_id,
            "event_kind": "callback",
            "frame": frame,
            "sender_id": actor,
            "acl_sender_id": actor,
            "user_id": actor,
            "session_id": route["session_id"],
            "approval_binding_id": nonce,
            "approval_actor_id": actor,
            "meta": {
                **{k: v for k, v in route.items() if k.startswith("wecom_")},
                "is_group": route["wecom_chat_type"] == "group",
                "bot_mentioned": True,
                "has_bot_command": True,
                "operator_display": actor,
            },
            "content_parts": [
                {
                    "type": "text",
                    "text": f"/approval {parsed['action']} {parsed['request_id']}",
                },
            ],
        }
        return await self.on_event(value)

    async def resolve_approval(self, route, params):
        result = params.approval_resolution
        binding = self._cards.get(route.get("approval_binding_id"))
        valid = (
            binding is not None
            and result.outcome.value in {"approved", "denied"}
            and binding["request_id"] == result.request_id
            and route.get("approval_actor_id") == result.actor_user_id
            and binding["instance_id"] == params.instance_id
            and binding["generation"] == params.generation
        )
        if valid:
            source = binding["route"]
            valid = all(
                source.get(k) == route.get(k)
                for k in ("wecom_chatid", "wecom_chat_type", "session_id")
            )
        if not valid:
            if result.outcome.value in {"approved", "denied"}:
                raise WeComDeliveryError("APPROVAL_BINDING_INVALID")
            return await self.send_parts(
                route,
                params.content_parts,
                params.content_source,
            )
        if binding.get("resolved"):
            if not binding.get("resolution_acknowledged"):
                raise WeComDeliveryError(
                    "APPROVAL_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            return {"final": "true"}
        action = "approve" if result.outcome.value == "approved" else "deny"
        card = build_resolved_card(
            task_id=binding["task_id"],
            tool_name=result.tool_name,
            action=action,
            operator_display=result.actor_user_id,
        )
        # This is reached solely from the typed, source/actor-bound host outcome.
        binding["resolved"] = True
        await self._call("update_template_card", self._frame(route), card)
        binding["resolution_acknowledged"] = True
        return {"final": "true"}
