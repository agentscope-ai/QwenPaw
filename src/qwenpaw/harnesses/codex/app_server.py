# -*- coding: utf-8 -*-
"""Async JSON-RPC client for the Codex app-server process."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from .discovery import (
    CodexBinaryResolution,
    resolve_codex_binary_info,
)

logger = logging.getLogger(__name__)

ServerRequestHandler = Callable[
    [dict[str, Any]],
    Awaitable[dict[str, Any]],
]


class CodexAppServerError(RuntimeError):
    """Raised when the Codex app-server cannot satisfy a request."""


class CodexAppServerClient:
    """Own one Codex app-server subprocess and correlate JSON-RPC calls."""

    def __init__(
        self,
        binary: str | None = None,
        config_overrides: tuple[str, ...] = (),
        environment: dict[str, str] | None = None,
    ) -> None:
        self._binary = binary
        self._config_overrides = config_overrides
        self._runtime_environment = dict(environment or {})
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._request_id = 0
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._server_request_handler: ServerRequestHandler | None = None

    @property
    def installed(self) -> bool:
        """Return whether the configured executable can be found."""
        return self.binary_resolution is not None

    @property
    def binary_resolution(self) -> CodexBinaryResolution | None:
        """Return the current executable resolution and source."""
        return resolve_codex_binary_info(self._binary)

    async def start(self) -> None:
        """Start and initialize the app-server once."""
        async with self._start_lock:
            if self._process is not None and self._process.returncode is None:
                return
            resolution = self.binary_resolution
            if resolution is None:
                raise CodexAppServerError("Codex CLI not found")
            self._process = await asyncio.create_subprocess_exec(
                str(resolution.path),
                "app-server",
                *[
                    item
                    for override in self._config_overrides
                    for item in ("-c", override)
                ],
                "--listen",
                "stdio://",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self._runtime_environment},
            )
            self._reader_task = asyncio.create_task(self._read_stdout())
            self._stderr_task = asyncio.create_task(self._read_stderr())
            await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "qwenpaw",
                        "title": "QwenPaw",
                        "version": "1",
                    },
                },
            )
            await self.notify("initialized", {})

    async def configure_runtime(
        self,
        config_overrides: tuple[str, ...],
        environment: dict[str, str],
    ) -> bool:
        """Apply launch configuration, restarting a running process."""
        next_environment = dict(environment)
        if (
            self._config_overrides == config_overrides
            and self._runtime_environment == next_environment
        ):
            return False
        was_running = (
            self._process is not None and self._process.returncode is None
        )
        if was_running:
            await self.stop()
        self._config_overrides = config_overrides
        self._runtime_environment = next_environment
        return was_running

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and await its correlated response."""
        if self._process is None or self._process.returncode is not None:
            if method == "initialize":
                raise CodexAppServerError("Codex app-server is not running")
            await self.start()
        self._request_id += 1
        request_id = self._request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._send(
                {
                    "method": method,
                    "id": request_id,
                    "params": params or {},
                },
            )
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a client notification."""
        await self._send({"method": method, "params": params or {}})

    async def notifications(self) -> AsyncIterator[dict[str, Any]]:
        """Yield notifications for one temporary subscriber."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register and return a bounded notification queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a notification queue."""
        self._subscribers.discard(queue)

    def set_server_request_handler(
        self,
        handler: ServerRequestHandler | None,
    ) -> None:
        """Set the callback used for app-server approval requests."""
        self._server_request_handler = handler

    async def stop(self) -> None:
        """Terminate the process and fail outstanding calls."""
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        self._fail_pending(CodexAppServerError("Codex app-server stopped"))

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise CodexAppServerError("Codex app-server stdin unavailable")
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        async with self._write_lock:
            process.stdin.write(data + b"\n")
            await process.stdin.drain()

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Codex emitted invalid JSON")
                    continue
                await self._dispatch(message)
        finally:
            error = CodexAppServerError("Codex app-server exited")
            self._fail_pending(error)

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            if line.strip():
                logger.debug("Codex app-server emitted stderr output")

    async def _dispatch(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id is not None and "method" not in message:
            future = self._pending.get(request_id)
            if future is None or future.done():
                return
            if "error" in message:
                detail = message["error"].get("message", "Unknown error")
                future.set_exception(CodexAppServerError(f"{detail}"))
            else:
                future.set_result(message.get("result"))
            return
        if request_id is not None and "method" in message:
            await self._handle_server_request(message)
            return
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Dropped Codex notification for slow client")

    async def _deny_server_request(self, request_id: Any) -> None:
        await self._send({"id": request_id, "result": {"decision": "decline"}})

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        handler = self._server_request_handler
        if handler is None:
            await self._deny_server_request(request_id)
            return
        try:
            result = await handler(message)
        except Exception:
            logger.exception("Failed to handle Codex server request")
            result = {"decision": "decline"}
        await self._send({"id": request_id, "result": result})

    def _fail_pending(self, error: Exception) -> None:
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)


__all__ = ["CodexAppServerClient", "CodexAppServerError"]
