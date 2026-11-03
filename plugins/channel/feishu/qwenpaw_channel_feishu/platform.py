# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Feishu platform implementation reused from the isolated transport."""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from email.utils import parsedate_to_datetime
from functools import wraps
import io
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
import types
from typing import Any
import uuid

import httpx

from qwenpaw.app.channels.utils import file_url_to_local_path
from .errors import FeishuDeliveryError
from .card_templates import (
    build_tool_guard_approval_card,
    parse_tool_guard_action_value,
    build_streaming_card_json,
)
from .constants import (
    FEISHU_FILE_MAX_BYTES,
    FEISHU_NICKNAME_CACHE_MAX,
    FEISHU_PROCESSED_IDS_MAX,
    FEISHU_REASONING_PANEL_ELEMENT_ID,
    FEISHU_STALE_MSG_THRESHOLD_MS,
    FEISHU_STREAM_ELEMENT_ID,
    FEISHU_WS_RECV_TIMEOUT,
)
from .utils import (
    build_interactive_content_chunks,
    detect_file_ext,
    extract_interactive_text,
    extract_json_key,
    extract_post_image_keys,
    extract_post_media_file_keys,
    extract_post_text,
    normalize_feishu_md,
)


logger = logging.getLogger(__name__)

_WS_CONNECT_TIMEOUT = 30.0
_WS_HEALTH_CHECK_INTERVAL = 30.0
_OPERATION_DRAIN_TIMEOUT = 5.0
_WS_DISCONNECT_TIMEOUT = 5.0
_WS_THREAD_JOIN_TIMEOUT = 5.0
_WS_PENDING_CANCEL_TIMEOUT = 0.5


def _declare_namespace_shim(_name: str) -> None:
    return None


_PKG_RESOURCES_MISSING = object()
_original_pkg_resources: Any = sys.modules.get(
    "pkg_resources",
    _PKG_RESOURCES_MISSING,
)
_pkg_resources_shim: types.ModuleType | None = None
_pkg_resources_module: Any = None
_declare_namespace_patched = False

try:
    import pkg_resources as _pkg_resources_module  # type: ignore
except ImportError:  # pragma: no cover - setuptools>=82
    _pkg_resources_shim = types.ModuleType("pkg_resources")
    _pkg_resources_shim.declare_namespace = (  # type: ignore[attr-defined]
        _declare_namespace_shim
    )
    sys.modules["pkg_resources"] = _pkg_resources_shim
else:
    if not hasattr(_pkg_resources_module, "declare_namespace"):
        setattr(
            _pkg_resources_module,
            "declare_namespace",
            _declare_namespace_shim,
        )
        _declare_namespace_patched = True

try:
    import lark_oapi as lark
    import lark_oapi.ws.client as lark_ws
    from lark_oapi.api.contact.v3 import GetUserRequest
    from lark_oapi.api.im.v1 import (
        CreateFileRequest,
        CreateFileRequestBody,
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
        GetMessageRequest,
        GetMessageResourceRequest,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
    )
    from lark_oapi.api.cardkit.v1 import (
        ContentCardElementRequest,
        ContentCardElementRequestBody,
        CreateCardRequest,
        CreateCardRequestBody,
        SettingsCardRequest,
        SettingsCardRequestBody,
    )
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )
    from lark_oapi.core.token import TokenManager
finally:
    if (
        _pkg_resources_shim is not None
        and sys.modules.get("pkg_resources") is _pkg_resources_shim
    ):
        if _original_pkg_resources is _PKG_RESOURCES_MISSING:
            del sys.modules["pkg_resources"]
        else:
            sys.modules["pkg_resources"] = _original_pkg_resources
    if _declare_namespace_patched and _pkg_resources_module is not None:
        if (
            getattr(_pkg_resources_module, "declare_namespace", None)
            is _declare_namespace_shim
        ):
            delattr(_pkg_resources_module, "declare_namespace")


def _owned_operation(method):
    """Keep actual transport work owned even if its caller is cancelled."""

    @wraps(method)
    async def run(self, *args, **kwargs):
        if self._closing or self._closed:
            raise RuntimeError("Feishu platform is closing")
        task = asyncio.create_task(method(self, *args, **kwargs))
        self._operations.add(task)
        task.add_done_callback(self._operation_done)
        return await asyncio.shield(task)

    return run


class LarkOapiPlatform:
    """Own Feishu SDK clients, callbacks, media, and platform sends."""

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._secret: dict[str, str] = {}
        self._media_work_dir: Path | None = None
        self._client: Any = None
        self._http_client: httpx.AsyncClient | None = None
        self._runner_loop: asyncio.AbstractEventLoop | None = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._ws_started = threading.Event()
        self._ws_error: BaseException | None = None
        self._ws_connect_task = None
        self._ws_disconnect_task = None
        self._disconnected = asyncio.Event()
        self._last_ws_receive_at = 0.0
        self._closed = False
        self._closing = False
        self._generation = 0
        self._callbacks: set[asyncio.Task] = set()
        self._operations: set[asyncio.Task] = set()
        self._clock_offset = 0
        self._bot_open_id = ""
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._inbound_lock = asyncio.Lock()
        self._nickname_cache: OrderedDict[str, str] = OrderedDict()

    async def prepare(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        media_work_dir: Path,
    ) -> None:
        """Build the production SDK client from validated Runner inputs."""
        app_id = str(config.get("app_id") or "")
        app_secret = str(secret.get("app_secret") or "")
        if not app_id or not app_secret:
            raise ValueError("Feishu credentials are required")
        self._config = dict(config)
        self._secret = {
            "app_secret": app_secret,
            "encrypt_key": str(secret.get("encrypt_key") or ""),
            "verification_token": str(
                secret.get("verification_token") or "",
            ),
        }
        self._media_work_dir = media_work_dir
        self._media_work_dir.mkdir(parents=True, exist_ok=True)
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(self._sdk_domain())
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        try:
            await self._probe_credentials()
        except Exception:
            await self._discard_prepared_resources()
            raise

    async def _probe_credentials(self) -> None:
        """Validate credentials through the SDK tenant-token flow."""
        if self._client is None:
            raise RuntimeError("Feishu authentication client is unavailable")
        token = await self._run_blocking(
            TokenManager.get_self_tenant_token,
            self._client._config,
        )
        if not token:
            raise RuntimeError("Feishu credentials were rejected")

    async def _discard_prepared_resources(self) -> None:
        """Release partially prepared clients after authentication failure."""
        if self._http_client is not None:
            await self._http_client.aclose()
        self._http_client = None
        self._client = None
        self._secret.clear()

    async def connect(
        self,
        on_message: Callable[[object], Awaitable[None]],
        on_card: Callable[[object], Awaitable[None]],
    ) -> None:
        """Start one SDK WebSocket connection in its dedicated thread."""
        if self._closing:
            raise RuntimeError("Feishu platform is closing")
        if self._ws_thread is not None:
            raise RuntimeError(
                "Feishu previous connection requires disconnect",
            )
        try:
            self._bot_open_id = await self._fetch_bot_open_id()
        except Exception:
            logger.warning("Feishu bot identity lookup failed", exc_info=True)
        self._closed = False
        self._generation += 1
        generation = self._generation
        self._runner_loop = asyncio.get_running_loop()
        self._disconnected = asyncio.Event()
        self._ws_error = None
        self._ws_connect_task = None
        self._ws_disconnect_task = None
        self._ws_started.clear()
        handler = (
            lark.EventDispatcherHandler.builder(
                self._secret.get("encrypt_key", ""),
                self._secret.get("verification_token", ""),
            )
            .register_p2_im_message_receive_v1(
                lambda value: self._on_message_sync(
                    value,
                    on_message,
                    generation,
                ),
            )
            .register_p2_im_message_reaction_created_v1(
                lambda _value: None,
            )
            .register_p2_im_message_reaction_deleted_v1(
                lambda _value: None,
            )
            .register_p2_card_action_trigger(
                lambda value: self._on_card_sync(value, on_card, generation),
            )
            .build()
        )
        self._ws_thread = threading.Thread(
            target=self._run_ws,
            args=(handler,),
            daemon=True,
        )
        self._ws_thread.start()
        started = await asyncio.to_thread(
            self._ws_started.wait,
            _WS_CONNECT_TIMEOUT,
        )
        if not started:
            await self.disconnect()
            raise TimeoutError("Feishu WebSocket connection timed out")
        if self._ws_error is not None:
            error = self._ws_error
            await self.disconnect()
            raise RuntimeError("Feishu WebSocket connection failed") from error

    async def wait_disconnected(self) -> None:
        """Wait until the SDK connection terminates."""
        await self._disconnected.wait()

    async def health_snapshot(self) -> dict[str, Any]:
        """Return a local, non-blocking connection health snapshot."""
        thread = self._ws_thread
        loop = self._ws_loop
        client = self._ws_client
        connection = getattr(client, "_conn", None)
        silent = (
            self._last_ws_receive_at > 0
            and time.monotonic() - self._last_ws_receive_at
            > FEISHU_WS_RECV_TIMEOUT
        )
        connected = bool(
            not self._closed
            and thread is not None
            and thread.is_alive()
            and loop is not None
            and not loop.is_closed()
            and client is not None
            and connection is not None
            and not self._disconnected.is_set()
            and not silent,
        )
        return {"connected": connected}

    async def _settle_work(self) -> None:
        # Tasks, rather than run_coroutine_threadsafe proxy futures, establish
        # quiescence: cancellation must include each coroutine's finally block.
        for task in self._callbacks:
            if not task.cancelling():
                task.cancel()
        deadline = asyncio.get_running_loop().time() + _OPERATION_DRAIN_TIMEOUT
        while pending := self._callbacks | self._operations:
            _, pending = await asyncio.wait(
                pending,
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
            )
            if pending:
                raise RuntimeError("Feishu callbacks or sends did not finish")

    async def _run_blocking(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._operations.add(task)
        task.add_done_callback(self._operation_done)
        return await asyncio.shield(task)

    def _operation_done(self, task: asyncio.Task) -> None:
        self._operations.discard(task)
        if not task.cancelled():
            task.exception()  # Observe failures after caller cancellation.

    async def disconnect(self) -> None:
        """Stop ingress, settle owned work and join before dropping handles."""
        self._closed = True
        self._generation += 1
        await self._settle_work()
        loop = self._ws_loop
        thread = self._ws_thread
        if loop is not None and not loop.is_closed() and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._disconnect_ws_client(),
                loop,
            )
            wrapped = asyncio.wrap_future(future)
            wrapped.add_done_callback(
                lambda item: None if item.cancelled() else item.exception(),
            )
            try:
                await asyncio.wait_for(
                    asyncio.shield(wrapped),
                    timeout=_WS_DISCONNECT_TIMEOUT * 1.2,
                )
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                # Thread finalization can cancel this proxy after closing the
                # socket. Join and inspect the actual resources below.
            except Exception as exc:
                raise RuntimeError(
                    "Feishu SDK disconnect did not finish",
                ) from exc
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            # Cancelling this await does not mean the thread has joined.
            await asyncio.shield(
                asyncio.to_thread(
                    thread.join,
                    _WS_THREAD_JOIN_TIMEOUT,
                ),
            )
            if thread.is_alive():
                raise RuntimeError("Feishu WebSocket thread did not stop")
        if self._ws_loop is not None and not self._ws_loop.is_closed():
            raise RuntimeError("Feishu WebSocket loop cleanup is incomplete")
        if getattr(self._ws_client, "_conn", None) is not None:
            raise RuntimeError("Feishu WebSocket socket cleanup is incomplete")
        self._ws_thread = None
        self._ws_client = None
        self._ws_loop = None
        self._disconnected.set()

    async def _disconnect_ws_client(self) -> None:
        """Share the actual close task across thread-finally and host stop."""
        if self._ws_disconnect_task is None or self._ws_disconnect_task.done():
            self._ws_disconnect_task = asyncio.create_task(
                self._close_ws_connection(),
            )
        await asyncio.shield(self._ws_disconnect_task)

    async def _close_ws_connection(self) -> None:
        connecting = self._ws_connect_task
        if connecting is not None and not connecting.done():
            connecting.cancel()
            await asyncio.gather(connecting, return_exceptions=True)
        client = self._ws_client
        if client is None or not hasattr(client, "_disconnect"):
            return
        connection = getattr(client, "_conn", None)
        try:
            await asyncio.wait_for(
                client._disconnect(),
                timeout=_WS_DISCONNECT_TIMEOUT,
            )
        except BaseException:
            # SDK clears _conn in finally even when socket.close fails.
            # Preserve the socket handle until closure succeeds.
            client._conn = connection
            raise

    async def close(self) -> None:
        """Release all platform resources."""
        self._closing = True
        await self.disconnect()
        await self._discard_prepared_resources()

    def _on_message_sync(
        self,
        value: object,
        callback: Callable[[object], Awaitable[None]],
        generation: int | None = None,
    ) -> None:
        """Fast-ACK SDK callback that schedules Runner-owned work."""
        generation = self._generation if generation is None else generation
        if (
            self._closed
            or (generation is not None and generation != self._generation)
            or not self._event_matches_instance(value)
        ):
            return
        if self._event_is_stale(value):
            return
        self._schedule_callback(
            self._dispatch_native_message(value, callback),
            "message",
            generation,
        )

    def _on_card_sync(
        self,
        value: object,
        callback: Callable[[object], Awaitable[None]],
        generation: int | None = None,
    ) -> Any:
        """Schedule card ingestion and return the SDK response promptly."""
        generation = self._generation if generation is None else generation
        if (
            self._closed
            or (generation is not None and generation != self._generation)
            or not self._event_matches_instance(value)
        ):
            return P2CardActionTriggerResponse({})
        native = self._native_card(value)
        parsed = parse_tool_guard_action_value(native.get("action_value"))
        if parsed is None:
            return P2CardActionTriggerResponse({})
        native.update(parsed)
        self._schedule_callback(callback(native), "card", generation)
        # Host ACL and approval policy have not run yet; acknowledge only.
        return P2CardActionTriggerResponse(
            {
                "toast": {
                    "type": "info",
                    "content": (
                        "Approval action received; awaiting authorization."
                    ),
                },
            },
        )

    def _schedule_callback(
        self,
        coroutine: Awaitable[None],
        event_kind: str,
        generation: int | None = None,
    ) -> None:
        loop = self._runner_loop
        generation = self._generation if generation is None else generation

        def schedule():
            if self._closed or generation != self._generation:
                coroutine.close()
                return
            task = asyncio.create_task(coroutine)
            self._callbacks.add(task)
            task.add_done_callback(finished)

        def finished(task):
            self._callbacks.discard(task)
            if not task.cancelled() and task.exception() is not None:
                logger.error(
                    "Feishu %s callback failed",
                    event_kind,
                    exc_info=task.exception(),
                )

        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(schedule)
                return
            except RuntimeError:
                pass
        coroutine.close()

    def _run_ws(self, handler: Any) -> None:
        """Run one lark-oapi connection in a private event loop."""
        runner_loop = self._runner_loop
        if runner_loop is None:
            self._ws_error = RuntimeError("Runner loop is unavailable")
            self._ws_started.set()
            return
        loop = asyncio.new_event_loop()
        self._ws_loop = loop
        try:
            asyncio.set_event_loop(loop)
            self._ws_client = lark_ws.Client(
                str(self._config.get("app_id") or ""),
                self._secret.get("app_secret", ""),
                event_handler=handler,
                log_level=lark.LogLevel.INFO,
                domain=self._sdk_domain(),
                auto_reconnect=False,
            )
            # SDK _connect schedules through a module-global `loop`. Bind only
            # this method to instance globals; leave other clients alone.
            connect = self._ws_client._connect.__func__
            self._ws_client._connect = types.FunctionType(
                connect.__code__,
                {**connect.__globals__, "loop": loop},
                connect.__name__,
                connect.__defaults__,
                connect.__closure__,
            ).__get__(self._ws_client)
            self._ws_client._receive_message_loop = (
                lambda: self._receive_ws_messages(loop, runner_loop)
            )
            self._ws_connect_task = loop.create_task(
                self._ws_client._connect(),
            )
            loop.run_until_complete(self._ws_connect_task)
            self._last_ws_receive_at = time.monotonic()
            loop.create_task(self._ws_client._ping_loop())
            loop.create_task(
                self._monitor_ws_connection(loop, runner_loop),
            )
            self._ws_started.set()
            loop.run_forever()
        except BaseException as exc:
            self._ws_error = exc
            self._ws_started.set()
        finally:
            self._closed = True
            while True:
                try:
                    loop.run_until_complete(self._disconnect_ws_client())
                    break
                except Exception:
                    logger.warning(
                        "Feishu socket cleanup needs retry",
                        exc_info=True,
                    )
                    # Retain a running loop/thread so a later stop can retry.
                    loop.run_forever()
            pending = [
                task for task in asyncio.all_tasks(loop) if not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                with suppress(Exception):
                    loop.run_until_complete(
                        asyncio.wait(
                            pending,
                            timeout=_WS_PENDING_CANCEL_TIMEOUT,
                        ),
                    )
            remaining = [task for task in pending if not task.done()]
            if remaining:
                # A cancellation-resistant SDK task still owns this loop. Keep
                # the thread alive and observable until its cleanup completes.
                loop.run_until_complete(
                    asyncio.gather(
                        *remaining,
                        return_exceptions=True,
                    ),
                )
            loop.close()
            with suppress(RuntimeError):
                runner_loop.call_soon_threadsafe(self._disconnected.set)

    async def _receive_ws_messages(
        self,
        loop: asyncio.AbstractEventLoop,
        runner_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Receive SDK frames and terminate the connection on exit."""
        try:
            while True:
                connection = getattr(self._ws_client, "_conn", None)
                if connection is None:
                    return
                message = await connection.recv()
                self._last_ws_receive_at = time.monotonic()
                loop.create_task(self._ws_client._handle_message(message))
        except Exception:
            logger.debug(
                "Feishu WebSocket receive loop ended",
                exc_info=True,
            )
        finally:
            if not self._closed:
                await self._stop_ws_loop(loop, runner_loop)

    async def _monitor_ws_connection(
        self,
        loop: asyncio.AbstractEventLoop,
        runner_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Close a missing or silent SDK connection."""
        while not self._closed:
            await asyncio.sleep(_WS_HEALTH_CHECK_INTERVAL)
            connection = getattr(self._ws_client, "_conn", None)
            silent = (
                self._last_ws_receive_at > 0
                and time.monotonic() - self._last_ws_receive_at
                > FEISHU_WS_RECV_TIMEOUT
            )
            if connection is not None and not silent:
                continue
            if silent:
                logger.warning("Feishu WebSocket was silent for too long")
            else:
                logger.warning("Feishu WebSocket connection was lost")
            await self._stop_ws_loop(loop, runner_loop)
            return

    async def _stop_ws_loop(
        self,
        loop: asyncio.AbstractEventLoop,
        runner_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Best-effort disconnect and wake the Runner connection loop."""
        with suppress(asyncio.TimeoutError, Exception):
            await self._disconnect_ws_client()
        runner_loop.call_soon_threadsafe(self._disconnected.set)
        loop.call_soon(loop.stop)

    async def _dispatch_native_message(
        self,
        value: object,
        callback: Callable[[object], Awaitable[None]],
    ) -> None:
        # Serialize admission so concurrent copies cannot bypass ACK dedup.
        async with self._inbound_lock:
            await self._dispatch_native_message_serial(value, callback)

    async def _dispatch_native_message_serial(self, value, callback) -> None:
        native = self._native_message(value)
        message_id = str(native.get("message_id") or "")
        if not message_id or message_id in self._processed_ids:
            return
        sender_id = str(native.get("sender_open_id") or "")
        if not sender_id or sender_id == self._bot_open_id:
            return
        sender_name = str(native.get("sender_name") or "")
        if not sender_name:
            sender_name = await self._fetch_sender_name(sender_id)
        native["sender_name"] = sender_name
        text_parts: list[str] = []
        content_parts: list[dict[str, Any]] = []
        message_type = str(native.get("message_type") or "text")
        main_text, hints, parts = await self._parse_message_content(
            message_type,
            str(native.get("content") or ""),
            message_id,
        )
        if message_type == "text" and main_text:
            for key in native.get("bot_mention_keys", []):
                main_text = main_text.replace(str(key), "")
            main_text = main_text.strip() or None
        if main_text:
            text_parts.append(main_text)
        text_parts.extend(hints)
        content_parts.extend(parts)
        parent_id = str(native.get("parent_id") or "")
        if parent_id:
            await self._append_quoted_message(
                parent_id,
                text_parts,
                content_parts,
            )
        if not text_parts and not content_parts:
            text_parts.append(f"[{message_type}]")
        if text_parts:
            content_parts.insert(
                0,
                {"type": "text", "text": "\n".join(text_parts)},
            )
        native["content_parts"] = content_parts
        await callback(native)
        self._processed_ids[message_id] = None
        while len(self._processed_ids) > FEISHU_PROCESSED_IDS_MAX:
            self._processed_ids.popitem(last=False)

    async def _parse_message_content(
        self,
        message_type: str,
        content: str,
        message_id: str,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        text: str | None = None
        hints: list[str] = []
        parts: list[dict[str, Any]] = []
        if message_type == "text":
            text = extract_json_key(content, "text")
        elif message_type == "post":
            text = extract_post_text(content)
            for image_key in extract_post_image_keys(content):
                try:
                    locator = await self._download_resource(
                        message_id,
                        image_key,
                        "image",
                        "image.jpg",
                    )
                    parts.append({"type": "image", "image_url": locator})
                except Exception:
                    logger.warning(
                        "Feishu image download failed",
                        exc_info=True,
                    )
                    hints.append("[image: download failed]")
            for file_key in extract_post_media_file_keys(content):
                try:
                    locator = await self._download_resource(
                        message_id,
                        file_key,
                        "file",
                        "file.bin",
                    )
                    parts.append({"type": "file", "file_url": locator})
                except Exception:
                    logger.warning(
                        "Feishu file download failed",
                        exc_info=True,
                    )
                    hints.append("[media: download failed]")
        elif message_type == "interactive":
            text = extract_interactive_text(content)
        elif message_type in {"image", "file", "media", "audio"}:
            key = extract_json_key(
                content,
                "image_key",
                "file_key",
                "imageKey",
                "fileKey",
            )
            if not key:
                return None, [f"[{message_type}: missing key]"], []
            filename = extract_json_key(
                content,
                "file_name",
                "fileName",
            ) or {
                "image": "image.jpg",
                "media": "video.mp4",
                "audio": "audio.opus",
            }.get(message_type, "file.bin")
            resource_type = "image" if message_type == "image" else "file"
            try:
                locator = await self._download_resource(
                    message_id,
                    key,
                    resource_type,
                    filename,
                )
            except Exception:
                logger.warning(
                    "Feishu %s download failed",
                    message_type,
                    exc_info=True,
                )
                label = "video" if message_type == "media" else message_type
                return None, [f"[{label}: download failed]"], []
            content_type = {
                "image": "image",
                "audio": "audio",
                "media": "video",
            }.get(message_type, "file")
            locator_name = (
                "data" if content_type == "audio" else f"{content_type}_url"
            )
            part = {
                "type": content_type,
                locator_name: locator,
                "filename": filename,
            }
            if content_type == "audio":
                part["format"] = Path(filename).suffix.lstrip(".") or "opus"
            parts.append(part)
        if text is not None:
            text = text.strip() or None
        return text, hints, parts

    async def _append_quoted_message(
        self,
        parent_id: str,
        text_parts: list[str],
        content_parts: list[dict[str, Any]],
    ) -> None:
        result = await self._fetch_quoted_message(parent_id)
        if result is None:
            return
        message_type, content = result
        text, hints, parts = await self._parse_message_content(
            message_type,
            content,
            parent_id,
        )
        label = {
            "text": "message",
            "post": "message",
            "image": "image",
            "file": "file",
            "media": "video",
            "audio": "audio",
            "interactive": "interactive card",
        }.get(message_type, message_type)
        quoted = f"[quoted {label}: {text}]" if text else f"[quoted {label}]"
        text_parts.insert(0, quoted)
        for hint in reversed(hints):
            text_parts.insert(1, f"[quoted {hint.strip('[]')}]")
        content_parts.extend(parts)

    async def _fetch_quoted_message(
        self,
        parent_id: str,
    ) -> tuple[str, str] | None:
        if self._client is None:
            return None
        try:
            request = GetMessageRequest.builder().message_id(parent_id).build()
            request.add_query("card_msg_content_type", "user_card_content")
            response = await self._client.im.v1.message.aget(request)
            if not response.success():
                return None
            items = response.data.items if response.data else []
            if not items:
                return None
            message = items[0]
            body = getattr(message, "body", None)
            return (
                str(getattr(message, "msg_type", "") or ""),
                str(getattr(body, "content", "") or ""),
            )
        except Exception:
            logger.debug("Feishu quoted message fetch failed", exc_info=True)
            return None

    async def _fetch_sender_name(self, open_id: str) -> str:
        if open_id in self._nickname_cache:
            name = self._nickname_cache.pop(open_id)
            self._nickname_cache[open_id] = name
            return name
        if self._client is None:
            return ""
        try:
            request = (
                GetUserRequest.builder()
                .user_id(open_id)
                .user_id_type("open_id")
                .build()
            )
            response = await self._run_blocking(
                self._client.contact.v3.user.get,
                request,
            )
            user = response.data.user if response.success() else None
            for field in ("name", "en_name", "nickname"):
                value = getattr(user, field, "") if user is not None else ""
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    self._nickname_cache[open_id] = name
                    while (
                        len(self._nickname_cache) > FEISHU_NICKNAME_CACHE_MAX
                    ):
                        self._nickname_cache.popitem(last=False)
                    return name
        except Exception:
            logger.debug("Feishu sender name lookup failed", exc_info=True)
        return ""

    async def _fetch_bot_open_id(self) -> str:
        """Fetch bot identity and update the server clock offset."""
        if self._client is None or self._http_client is None:
            return ""
        try:
            token = await self._run_blocking(
                TokenManager.get_self_tenant_token,
                self._client._config,
            )
            if not token:
                return ""
            response = await self._http_client.get(
                f"{self._sdk_domain()}/open-apis/bot/v3/info",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
            date_value = response.headers.get("Date")
            if date_value:
                server_ms = int(
                    parsedate_to_datetime(date_value).timestamp() * 1000,
                )
                self._clock_offset = server_ms - int(time.time() * 1000)
            data = response.json()
            if data.get("code", -1) != 0:
                return ""
            return str((data.get("bot") or {}).get("open_id") or "")
        except Exception:
            logger.debug("Feishu bot identity lookup failed", exc_info=True)
            return ""

    async def _download_resource(
        self,
        message_id: str,
        resource_key: str,
        resource_type: str,
        filename: str,
    ) -> str:
        if self._client is None or GetMessageResourceRequest is None:
            raise RuntimeError("Feishu media client is unavailable")
        media_dir = self._media_work_dir
        if media_dir is None:
            raise RuntimeError("Feishu media_work_dir is unavailable")
        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(resource_key)
            .type(resource_type)
            .build()
        )
        response = await self._client.im.v1.message_resource.aget(request)
        if not response.success() or response.file is None:
            raise RuntimeError("Feishu media download failed")
        data = response.file.read()
        if not data:
            raise RuntimeError("Feishu media download was empty")
        if resource_type == "image":
            safe_key = (
                "".join(
                    character
                    for character in resource_key
                    if character.isalnum() or character in "-_."
                )
                or "img"
            )
            extension = detect_file_ext(data, default="jpg")
            path = media_dir / f"{message_id}_{safe_key}.{extension}"
        else:
            safe_name = Path(filename).name or "file.bin"
            if safe_name in {"file.bin", "video.mp4"}:
                extension = detect_file_ext(data, default="bin")
                safe_name = f"file.{extension}"
            path = media_dir / f"{message_id}_{safe_name}"
        await self._run_blocking(path.write_bytes, data)
        return str(path)

    @_owned_operation
    async def send_message(
        self,
        receive_id_type: str,
        receive_id: str,
        content_parts: tuple[dict[str, Any], ...],
        *,
        reply_message_id: str = "",
    ) -> str:
        """Send text and media with legacy Feishu ordering and rendering."""
        text_parts: list[str] = []
        media_parts: list[Mapping[str, Any]] = []
        for part in content_parts:
            if part.get("type") == "text":
                text_parts.append(str(part.get("text") or ""))
            else:
                media_parts.append(part)
        body = "\n".join(text_parts).strip()
        prefix = str(self._config.get("bot_prefix") or "")
        if prefix and body:
            body = f"{prefix}  {body}"
        last_message_id = ""
        side_effect_possible = False
        try:
            if body:
                message_ids = await self._send_text(
                    receive_id_type,
                    receive_id,
                    body,
                    reply_message_id=reply_message_id,
                )
                if message_ids:
                    last_message_id = message_ids[-1]
                    side_effect_possible = True
            for part in media_parts:
                if part.get("type") == "image":
                    message_id = await self._send_image_part(
                        receive_id_type,
                        receive_id,
                        part,
                        reply_message_id=reply_message_id,
                    )
                else:
                    message_id = await self._send_file_part(
                        receive_id_type,
                        receive_id,
                        part,
                        reply_message_id=reply_message_id,
                    )
                last_message_id = message_id
                side_effect_possible = True
        except FeishuDeliveryError as exc:
            raise FeishuDeliveryError(
                exc.reason_code,
                side_effect_possible=(
                    side_effect_possible or exc.side_effect_possible
                ),
                retryable=exc.retryable,
            ) from exc
        if not last_message_id:
            raise FeishuDeliveryError(
                "EMPTY_OUTBOUND_CONTENT",
                side_effect_possible=False,
            )
        return last_message_id

    @_owned_operation
    async def send_approval(
        self,
        receive_id_type: str,
        receive_id: str,
        approval: Mapping[str, str],
        fallback_text: str,
        *,
        session_ctx: Mapping[str, Any] | None = None,
    ) -> str:
        content = build_tool_guard_approval_card(
            request_id=str(approval.get("request_id") or ""),
            tool_name=str(approval.get("tool_name") or "tool"),
            severity=str(approval.get("severity") or "medium"),
            body_text=fallback_text,
            session_ctx=dict(session_ctx)
            if session_ctx is not None
            else {
                "chat_id": (
                    receive_id if receive_id_type == "chat_id" else ""
                ),
                "chat_type": (
                    "group" if receive_id_type == "chat_id" else "p2p"
                ),
                "receive_id": receive_id,
                "receive_id_type": receive_id_type,
                "is_group": receive_id_type == "chat_id",
            },
        )
        return await self._create_message(
            receive_id_type,
            receive_id,
            "interactive",
            content,
        )

    async def _send_text(
        self,
        receive_id_type: str,
        receive_id: str,
        body: str,
        *,
        reply_message_id: str = "",
    ) -> list[str]:
        if not reply_message_id and re.search(
            r"^\s*\|",
            body,
            re.MULTILINE,
        ):
            message_ids = []
            try:
                for chunk in build_interactive_content_chunks(body):
                    message_ids.append(
                        await self._create_message(
                            receive_id_type,
                            receive_id,
                            "interactive",
                            chunk,
                        ),
                    )
            except FeishuDeliveryError as exc:
                raise FeishuDeliveryError(
                    exc.reason_code,
                    side_effect_possible=(
                        bool(message_ids) or exc.side_effect_possible
                    ),
                    retryable=exc.retryable,
                ) from exc
            return message_ids
        post = {
            "zh_cn": {
                "content": [
                    [{"tag": "md", "text": normalize_feishu_md(body)}],
                ],
            },
        }
        return [
            await self._create_message(
                receive_id_type,
                receive_id,
                "post",
                json.dumps(post, ensure_ascii=False),
                reply_message_id=reply_message_id,
            ),
        ]

    async def _send_image_part(
        self,
        receive_id_type: str,
        receive_id: str,
        part: Mapping[str, Any],
        *,
        reply_message_id: str = "",
    ) -> str:
        if self._client is None:
            raise FeishuDeliveryError(
                "PLATFORM_UNAVAILABLE",
                side_effect_possible=False,
            )
        data = await self._read_locator(str(part.get("image_url") or ""))
        request = (
            CreateImageRequest.builder()
            .request_body(
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(io.BytesIO(data))
                .build(),
            )
            .build()
        )
        try:
            response = await self._client.im.v1.image.acreate(request)
        except Exception as exc:
            raise FeishuDeliveryError(
                "IMAGE_UPLOAD_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        image_key = (
            getattr(response.data, "image_key", "")
            if response.success() and response.data
            else ""
        )
        if not image_key:
            raise FeishuDeliveryError(
                "IMAGE_UPLOAD_FAILED",
                side_effect_possible=False,
            )
        try:
            return await self._create_message(
                receive_id_type,
                receive_id,
                "image",
                json.dumps({"image_key": image_key}, ensure_ascii=False),
                reply_message_id=reply_message_id,
            )
        except FeishuDeliveryError as exc:
            raise FeishuDeliveryError(
                exc.reason_code,
                side_effect_possible=True,
                retryable=exc.retryable,
            ) from exc

    async def _send_file_part(
        self,
        receive_id_type: str,
        receive_id: str,
        part: Mapping[str, Any],
        *,
        reply_message_id: str = "",
    ) -> str:
        locator = str(
            part.get("file_url")
            or part.get("video_url")
            or part.get("data")
            or "",
        )
        data = await self._read_locator(locator)
        if len(data) > FEISHU_FILE_MAX_BYTES:
            raise FeishuDeliveryError(
                "FILE_TOO_LARGE",
                side_effect_possible=False,
            )
        filename = str(
            part.get("filename") or Path(locator).name or "file.bin",
        )
        suffix = Path(filename).suffix.lower().lstrip(".")
        file_type = "stream"
        if suffix in {
            "pdf",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "ppt",
            "pptx",
        }:
            file_type = {"docx": "doc", "xlsx": "xls", "pptx": "ppt"}.get(
                suffix,
                suffix,
            )
        elif suffix in {"ogg", "opus"}:
            file_type = "opus"
        request = (
            CreateFileRequest.builder()
            .request_body(
                CreateFileRequestBody.builder()
                .file_type(file_type)
                .file_name(Path(filename).name)
                .file(io.BytesIO(data))
                .build(),
            )
            .build()
        )
        try:
            response = await self._client.im.v1.file.acreate(request)
        except Exception as exc:
            raise FeishuDeliveryError(
                "FILE_UPLOAD_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        file_key = (
            getattr(response.data, "file_key", "")
            if response.success() and response.data
            else ""
        )
        if not file_key:
            raise FeishuDeliveryError(
                "FILE_UPLOAD_FAILED",
                side_effect_possible=False,
            )
        try:
            return await self._create_message(
                receive_id_type,
                receive_id,
                "audio" if file_type == "opus" else "file",
                json.dumps({"file_key": file_key}, ensure_ascii=False),
                reply_message_id=reply_message_id,
            )
        except FeishuDeliveryError as exc:
            raise FeishuDeliveryError(
                exc.reason_code,
                side_effect_possible=True,
                retryable=exc.retryable,
            ) from exc

    async def _read_locator(self, locator: str) -> bytes:
        if locator.startswith("data:") and "base64," in locator:
            try:
                return base64.b64decode(locator.split("base64,", 1)[1])
            except Exception as exc:
                raise FeishuDeliveryError(
                    "INVALID_DATA_LOCATOR",
                    side_effect_possible=False,
                ) from exc
        local_path = file_url_to_local_path(locator)
        if local_path is not None:
            path = Path(local_path)
            if not path.is_file():
                raise FeishuDeliveryError(
                    "LOCAL_FILE_UNAVAILABLE",
                    side_effect_possible=False,
                )
            return await self._run_blocking(path.read_bytes)
        if locator.startswith(("http://", "https://")):
            if self._http_client is None:
                raise FeishuDeliveryError(
                    "HTTP_CLIENT_UNAVAILABLE",
                    side_effect_possible=False,
                )
            response = await self._http_client.get(locator)
            if response.status_code >= 400:
                raise FeishuDeliveryError(
                    "REMOTE_MEDIA_UNAVAILABLE",
                    side_effect_possible=False,
                )
            return response.content
        raise FeishuDeliveryError(
            "UNSUPPORTED_MEDIA_LOCATOR",
            side_effect_possible=False,
        )

    async def _create_message(
        self,
        receive_id_type: str,
        receive_id: str,
        message_type: str,
        content: str,
        *,
        reply_message_id: str = "",
    ) -> str:
        if reply_message_id:
            request = (
                ReplyMessageRequest.builder()
                .message_id(reply_message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type(message_type)
                    .content(content)
                    .reply_in_thread(True)
                    .build(),
                )
                .build()
            )
        else:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(message_type)
                    .content(content)
                    .build(),
                )
                .build()
            )
        try:
            if reply_message_id:
                response = await self._client.im.v1.message.areply(request)
            else:
                response = await self._client.im.v1.message.acreate(request)
        except Exception as exc:
            raise FeishuDeliveryError(
                "MESSAGE_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        if not response.success():
            raise FeishuDeliveryError(
                "MESSAGE_REJECTED",
                side_effect_possible=False,
                retryable=True,
            )
        message_id = getattr(response.data, "message_id", "")
        if not message_id:
            raise FeishuDeliveryError(
                "MESSAGE_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        return str(message_id)

    @_owned_operation
    async def start_stream(
        self,
        receive_id_type: str,
        receive_id: str,
        text: str,
        *,
        collapsible: bool = False,
    ) -> dict[str, str]:
        card_json = build_streaming_card_json(text or "...", collapsible)
        request = (
            CreateCardRequest.builder()
            .request_body(
                CreateCardRequestBody.builder()
                .type("card_json")
                .data(json.dumps(card_json, ensure_ascii=False))
                .build(),
            )
            .build()
        )
        try:
            response = await self._client.cardkit.v1.card.acreate(request)
        except Exception as exc:
            raise FeishuDeliveryError(
                "STREAM_CREATE_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        card_id = (
            getattr(response.data, "card_id", "")
            if response.success() and response.data
            else ""
        )
        if not card_id:
            raise FeishuDeliveryError(
                "STREAM_CREATE_FAILED",
                side_effect_possible=False,
            )
        try:
            message_id = await self._create_message(
                receive_id_type,
                receive_id,
                "interactive",
                json.dumps(
                    {"type": "card", "data": {"card_id": card_id}},
                    ensure_ascii=False,
                ),
            )
        except FeishuDeliveryError as exc:
            raise FeishuDeliveryError(
                exc.reason_code,
                side_effect_possible=True,
                retryable=exc.retryable,
            ) from exc
        return {"card_id": str(card_id), "message_id": message_id}

    @_owned_operation
    async def update_stream(
        self,
        target: Mapping[str, str],
        text: str,
        sequence: int,
        *,
        final: bool,
    ) -> bool:
        request = (
            ContentCardElementRequest.builder()
            .card_id(target["card_id"])
            .element_id(FEISHU_STREAM_ELEMENT_ID)
            .request_body(
                ContentCardElementRequestBody.builder()
                .content(normalize_feishu_md(text) if final else text)
                .sequence(sequence)
                .uuid(str(uuid.uuid4()))
                .build(),
            )
            .build()
        )
        try:
            response = await self._client.cardkit.v1.card_element.acontent(
                request,
            )
        except Exception as exc:
            raise FeishuDeliveryError(
                "STREAM_UPDATE_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        if not response.success() or not final:
            return bool(response.success())
        preview = text.strip()
        if len(preview) > 80:
            preview = f"{preview[:77]}..."
        settings = json.dumps(
            {
                "config": {
                    "streaming_mode": False,
                    "summary": {"content": preview or "completed"},
                },
            },
            ensure_ascii=False,
        )
        finalize = (
            SettingsCardRequest.builder()
            .card_id(target["card_id"])
            .request_body(
                SettingsCardRequestBody.builder()
                .settings(settings)
                .sequence(sequence + 1)
                .uuid(str(uuid.uuid4()))
                .build(),
            )
            .build()
        )
        try:
            final_response = await self._client.cardkit.v1.card.asettings(
                finalize,
            )
        except Exception as exc:
            raise FeishuDeliveryError(
                "STREAM_FINALIZE_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        if not final_response.success():
            raise FeishuDeliveryError(
                "STREAM_FINALIZE_PARTIAL",
                side_effect_possible=True,
            )
        return True

    @_owned_operation
    async def collapse_reasoning_panel(
        self,
        card_id: str,
        sequence: int,
    ) -> bool:
        """Collapse the reasoning panel via the CardKit element PATCH API.

        The element content API (PUT) returns 404 for this endpoint, so the
        update goes through a PATCH whose ``partial_element`` is a JSON
        string. ``sequence`` must exceed the finalize sequence. A failure is
        logged only: a panel left expanded must never fail the answer.
        """
        if not self._client or not card_id:
            return False

        from lark_oapi.api.cardkit.v1 import (
            PatchCardElementRequest,
            PatchCardElementRequestBody,
        )

        partial_element = json.dumps({"expanded": False}, ensure_ascii=False)

        try:
            req = (
                PatchCardElementRequest.builder()
                .card_id(card_id)
                .element_id(FEISHU_REASONING_PANEL_ELEMENT_ID)
                .request_body(
                    PatchCardElementRequestBody.builder()
                    .partial_element(partial_element)
                    .sequence(sequence)
                    .uuid(str(uuid.uuid4()))
                    .build(),
                )
                .build()
            )
            resp = await self._client.cardkit.v1.card_element.apatch(req)
            if not resp.success():
                logger.warning(
                    "feishu collapse reasoning panel failed: code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                return False
            return True
        except Exception:
            logger.warning(
                "feishu collapse reasoning panel exception",
                exc_info=True,
            )
            return False

    @_owned_operation
    async def add_reaction(
        self,
        message_id: str,
        emoji_type: str = "DONE",
    ) -> bool:
        return await self._add_reaction(message_id, emoji_type)

    async def _add_reaction(
        self,
        message_id: str,
        emoji_type: str,
    ) -> bool:
        if not message_id or self._client is None:
            return False
        request = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(
                    Emoji.builder().emoji_type(emoji_type).build(),
                )
                .build(),
            )
            .build()
        )
        try:
            response = await self._client.im.v1.message_reaction.acreate(
                request,
            )
            return bool(response.success())
        except Exception:
            logger.debug("Feishu reaction failed", exc_info=True)
            return False

    def _native_message(self, value: object) -> dict[str, Any]:
        event = getattr(value, "event", None)
        message = getattr(event, "message", None)
        sender = getattr(event, "sender", None)
        sender_id = getattr(sender, "sender_id", None)
        mentions = getattr(message, "mentions", None) or []
        mention_keys: list[str] = []
        content = str(getattr(message, "content", "") or "")
        mentioned = "@_all" in content
        for mention in mentions:
            mention_id = getattr(mention, "id", None)
            if (
                self._bot_open_id
                and getattr(mention_id, "open_id", "") == self._bot_open_id
            ):
                mentioned = True
                key = str(getattr(mention, "key", "") or "")
                if key:
                    mention_keys.append(key)
        header = getattr(value, "header", None)
        return {
            "event_id": str(
                getattr(header, "event_id", "")
                or getattr(message, "message_id", ""),
            ),
            "message_id": str(getattr(message, "message_id", "") or ""),
            "chat_id": str(getattr(message, "chat_id", "") or ""),
            "chat_type": str(getattr(message, "chat_type", "p2p") or "p2p"),
            "message_type": str(
                getattr(message, "message_type", "text") or "text",
            ),
            "content": content,
            "sender_open_id": str(
                getattr(sender_id, "open_id", "") or "",
            ),
            "sender_name": str(
                getattr(sender, "name", "")
                or getattr(sender, "nickname", "")
                or "",
            ),
            "thread_id": str(getattr(message, "thread_id", "") or ""),
            "parent_id": str(getattr(message, "parent_id", "") or ""),
            "bot_mentioned": mentioned,
            "bot_mention_keys": mention_keys,
        }

    @staticmethod
    def _native_card(value: object) -> dict[str, Any]:
        event = getattr(value, "event", None)
        action = getattr(event, "action", None)
        operator = getattr(event, "operator", None)
        header = getattr(value, "header", None)
        action_value = getattr(action, "value", None) or {}
        action_name = str(action_value.get("action") or "")
        request_id = str(action_value.get("request_id") or "")
        operator_id = str(getattr(operator, "open_id", "") or "")
        fallback_id = f"card-{request_id}-{operator_id}-{action_name}"
        return {
            "event_id": str(
                getattr(header, "event_id", "") or fallback_id,
            ),
            "operator_open_id": operator_id,
            "action_value": action_value,
        }

    def _event_matches_instance(self, value: object) -> bool:
        app_id = str(
            getattr(getattr(value, "header", None), "app_id", "") or "",
        )
        expected = str(self._config.get("app_id") or "")
        return not app_id or app_id == expected

    def _event_is_stale(self, value: object) -> bool:
        create_time = getattr(
            getattr(value, "header", None),
            "create_time",
            None,
        )
        if not create_time:
            return False
        now_ms = int(time.time() * 1000) + self._clock_offset
        try:
            return now_ms - int(create_time) > FEISHU_STALE_MSG_THRESHOLD_MS
        except (TypeError, ValueError):
            return False

    def _sdk_domain(self) -> str:
        domain = str(self._config.get("domain") or "feishu")
        if domain.startswith("http"):
            return domain
        return lark.LARK_DOMAIN if domain == "lark" else lark.FEISHU_DOMAIN


__all__ = ["FeishuDeliveryError", "LarkOapiPlatform"]
