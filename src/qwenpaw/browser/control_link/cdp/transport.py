# -*- coding: utf-8 -*-
"""Minimal WebSocket JSON-RPC transport for the Chrome DevTools Protocol."""

from __future__ import annotations
import asyncio
from typing import Any, Callable, Mapping
from ...errors import BrowserError, ErrorCategory


class CdpTransport:
    def __init__(self) -> None:
        self._ws: Any = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._sinks: list[Callable[[dict[str, Any]], None]] = []
        self._reader_task: asyncio.Task[None] | None = None

    async def connect(self, ws_url: str) -> None:
        import websockets

        if ws_url.startswith(("http://", "https://")):
            ws_url = await self._discover_ws_endpoint(ws_url)
        self._ws = await websockets.connect(ws_url)
        self._reader_task = asyncio.create_task(self._reader())

    async def _discover_ws_endpoint(self, base_url: str) -> str:
        """Resolve an HTTP DevTools address to its websocket endpoint."""
        import json
        from urllib.request import urlopen

        version_url = base_url.rstrip("/") + "/json/version"

        def _fetch() -> str:
            with urlopen(version_url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return str(payload.get("webSocketDebuggerUrl") or "")

        try:
            endpoint = await asyncio.to_thread(_fetch)
        except Exception as exc:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                suggested_action=(
                    "Could not reach the DevTools HTTP endpoint. Confirm "
                    "Chrome runs with --remote-debugging-port and that "
                    "browser.cdp_url points at it."
                ),
                reason="CDP endpoint discovery failed",
                detail=f"{version_url}: {exc}",
            ) from exc
        if not endpoint:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                suggested_action=(
                    "The DevTools endpoint returned no "
                    "webSocketDebuggerUrl; use a ws:// address instead."
                ),
                reason="CDP endpoint discovery failed",
                detail=version_url,
            )
        return endpoint

    async def _reader(self) -> None:
        import json

        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                future = self._pending.pop(msg.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(msg)
                elif "id" not in msg:
                    for sink in list(self._sinks):
                        sink(msg)
        finally:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(
                        BrowserError(
                            category=ErrorCategory.RETRYABLE,
                            suggested_action="retry",
                            reason="CDP connection closed",
                        ),
                    )
            self._pending.clear()

    async def send(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        ident = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        payload = {"id": ident, "method": method, "params": dict(params)}
        if session_id:
            payload["sessionId"] = session_id
        await self._ws.send(__import__("json").dumps(payload))
        try:
            msg = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(ident, None)
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                suggested_action="retry",
                reason="CDP request timed out",
            ) from exc
        if "error" in msg:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                suggested_action="fatal",
                reason=str(msg["error"]),
            )
        return msg.get("result", {})

    def subscribe(self, sink):
        self._sinks.append(sink)
        return lambda: self._sinks.remove(sink)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._reader_task is not None:
            await self._reader_task
            self._reader_task = None
        self._ws = None
