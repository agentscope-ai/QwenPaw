# -*- coding: utf-8 -*-
"""WebSocket helpers for the WeCom custom channel plugin."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from contextlib import suppress
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

import aiohttp

from .constants import DEFAULT_HEARTBEAT_INTERVAL_SECONDS
from .constants import DEFAULT_RECONNECT_MAX_SECONDS
from .constants import DEFAULT_RECONNECT_MIN_SECONDS
from .constants import DEFAULT_WS_URL

logger = logging.getLogger(__name__)


def build_subscribe_payload(
    req_id: str,
    bot_id: str,
    secret: str,
) -> Dict[str, Any]:
    """Build the minimal aibot_subscribe payload."""

    return {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": req_id},
        "body": {
            "bot_id": bot_id,
            "secret": secret,
        },
    }


def build_ping_payload(req_id: str) -> Dict[str, Any]:
    """Build the minimal ping payload required by the long connection."""

    return {
        "cmd": "ping",
        "headers": {"req_id": req_id},
    }


def next_backoff_seconds(
    attempt: int,
    min_seconds: int,
    max_seconds: int,
) -> int:
    """Return a bounded exponential backoff in seconds."""

    floor = max(1, int(min_seconds))
    ceiling = max(floor, int(max_seconds))
    step = max(1, int(attempt))
    return min(ceiling, floor * (2 ** (step - 1)))


class WeComWebSocketTransport(Protocol):
    """Minimal transport abstraction used by the channel for ws commands."""

    async def send_json(self, payload: Dict[str, Any]) -> None:
        """Send one JSON payload through an established transport."""


PayloadCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]


class WeComRuntimeClient:
    """Minimal aiohttp-based runtime client for WeCom long connections."""

    def __init__(
        self,
        *,
        bot_id: str,
        secret: str,
        ws_url: str = DEFAULT_WS_URL,
        ping_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        reconnect_min_seconds: int = DEFAULT_RECONNECT_MIN_SECONDS,
        reconnect_max_seconds: int = DEFAULT_RECONNECT_MAX_SECONDS,
        on_payload: Optional[PayloadCallback] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        sleep_func: Optional[Callable[[float], Awaitable[None]]] = None,
        request_id_factory: Optional[Callable[[], str]] = None,
    ):
        self.bot_id = bot_id
        self.secret = secret
        self.ws_url = ws_url or DEFAULT_WS_URL
        self.ping_interval_seconds = max(0.0, float(ping_interval_seconds))
        self.reconnect_min_seconds = int(reconnect_min_seconds)
        self.reconnect_max_seconds = int(reconnect_max_seconds)
        self.on_payload = on_payload
        self._session_factory = session_factory or aiohttp.ClientSession
        self._sleep = sleep_func or asyncio.sleep
        self._request_id_factory = request_id_factory or self._default_request_id
        self._session = None
        self._owns_session = False
        self._ws = None
        self._run_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._stopped = True
        self._send_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background runtime loop once."""

        if self._run_task is not None and not self._run_task.done():
            return
        self._stopped = False
        self._run_task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        """Stop background tasks and close transport resources."""

        self._stopped = True
        await self._cancel_task(self._heartbeat_task)
        self._heartbeat_task = None
        if self._run_task is not None:
            self._run_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._run_task
        self._run_task = None
        await self._close_ws()
        await self._close_session()

    async def send_json(self, payload: Dict[str, Any]) -> None:
        """Send one JSON payload over the currently connected socket."""

        ws = self._ws
        if ws is None:
            raise RuntimeError("WeCom websocket is not connected")
        async with self._send_lock:
            logger.info(
                "wecom ws send: cmd=%s req_id=%s",
                payload.get("cmd") or "",
                ((payload.get("headers") or {}).get("req_id") or ""),
            )
            await ws.send_json(payload)

    async def _run_forever(self) -> None:
        attempt = 1
        while not self._stopped:
            try:
                await self._connect_once()
                attempt = 1
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stopped:
                    break
                backoff = next_backoff_seconds(
                    attempt,
                    self.reconnect_min_seconds,
                    self.reconnect_max_seconds,
                )
                attempt += 1
                await self._sleep(backoff)

    async def _connect_once(self) -> None:
        session = await self._ensure_session()
        ws = await session.ws_connect(self.ws_url)
        self._ws = ws
        try:
            await self.send_json(
                build_subscribe_payload(
                    self._request_id_factory(),
                    self.bot_id,
                    self.secret,
                )
            )
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            await self._reader_loop(ws)
        finally:
            await self._cancel_task(self._heartbeat_task)
            self._heartbeat_task = None
            await self._close_ws()

    async def _reader_loop(self, ws: Any) -> None:
        async for message in ws:
            msg_type = getattr(message, "type", None)
            if msg_type not in (
                getattr(aiohttp, "WSMsgType", None).TEXT
                if hasattr(aiohttp, "WSMsgType")
                else 1,
                1,
            ):
                continue
            payload = json.loads(getattr(message, "data", "") or "{}")
            cmd = str(payload.get("cmd") or "").strip()
            if cmd in {"aibot_msg_callback", "aibot_event_callback"}:
                await self._dispatch_payload(payload)
                continue
            logger.info(
                "wecom ws recv: cmd=%s req_id=%s payload=%s",
                cmd,
                ((payload.get("headers") or {}).get("req_id") or ""),
                payload,
            )

    async def _heartbeat_loop(self) -> None:
        if self.ping_interval_seconds <= 0:
            return
        while not self._stopped and self._ws is not None:
            await self._sleep(self.ping_interval_seconds)
            if self._stopped or self._ws is None:
                return
            await self.send_json(build_ping_payload(self._request_id_factory()))

    async def _dispatch_payload(self, payload: Dict[str, Any]) -> None:
        if self.on_payload is None:
            return
        result = self.on_payload(payload)
        if inspect.isawaitable(result):
            await result

    async def _ensure_session(self) -> Any:
        if self._session is None:
            self._session = self._session_factory()
            self._owns_session = True
        return self._session

    async def _close_ws(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        with suppress(Exception):
            await ws.close()

    async def _close_session(self) -> None:
        session = self._session
        self._session = None
        owns_session = self._owns_session
        self._owns_session = False
        if session is None or not owns_session:
            return
        with suppress(Exception):
            await session.close()

    async def _cancel_task(self, task: Optional[asyncio.Task[None]]) -> None:
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def _default_request_id(self) -> str:
        return uuid.uuid4().hex
