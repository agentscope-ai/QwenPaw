# -*- coding: utf-8 -*-
"""ACP stdio transport with bidirectional JSON-RPC support."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ACPHarnessConfig
from .errors import ACPProtocolError, ACPTransportError

logger = logging.getLogger(__name__)


@dataclass
class JSONRPCResponse:
    """JSON-RPC response envelope."""

    id: str | int | None
    result: Any = None
    error: dict[str, Any] | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class JSONRPCRequest:
    """JSON-RPC request envelope initiated by the harness."""

    id: str | int
    method: str
    params: dict[str, Any]


@dataclass
class JSONRPCNotification:
    """JSON-RPC notification envelope initiated by the harness."""

    method: str
    params: dict[str, Any]


class ACPTransport:
    """Manage ACP harness process lifecycle and message routing."""

    STDIO_STREAM_LIMIT = 1024 * 1024

    def __init__(self, harness_name: str, harness_config: ACPHarnessConfig):
        self.harness_name = harness_name
        self.config = harness_config
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._request_id = 0
        self._pending: dict[str, asyncio.Future[JSONRPCResponse]] = {}
        self._incoming: asyncio.Queue[JSONRPCRequest | JSONRPCNotification] = (
            asyncio.Queue()
        )
        self._stderr_buffer: list[str] = []

    @property
    def incoming(self) -> asyncio.Queue[JSONRPCRequest | JSONRPCNotification]:
        return self._incoming

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_buffer[-20:])

    def is_running(self) -> bool:
        """Return whether the harness process is still alive."""
        return self._process is not None and self._process.returncode is None

    async def start(self, cwd: str | Path | None = None) -> None:
        """Spawn the harness process and start background readers."""
        if self.is_running():
            await self.close()

        working_dir = Path(cwd or Path.cwd()).expanduser().resolve()
        env = os.environ.copy()
        env.update(self.config.env)
        cmd = [self.config.command, *self.config.args]
        logger.info("Spawning ACP harness %s in %s", self.harness_name, working_dir)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.STDIO_STREAM_LIMIT,
                cwd=str(working_dir),
                env=env,
            )
        except Exception as exc:  # pylint: disable=broad-except
            raise ACPTransportError(
                f"Failed to spawn harness {self.harness_name}: {exc}",
            ) from exc

        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stdout_task.add_done_callback(
            lambda task: self._on_reader_task_done("stdout", task),
        )
        self._stderr_task = asyncio.create_task(self._read_stderr())
        self._stderr_task.add_done_callback(
            lambda task: self._on_reader_task_done("stderr", task),
        )

    async def close(self) -> None:
        """Stop reader tasks and terminate the harness process."""
        for task in (self._stdout_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        if self._process is not None:
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                    wait_closed = getattr(self._process.stdin, "wait_closed", None)
                    if callable(wait_closed):
                        await wait_closed()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug(
                        "Failed closing stdin for ACP harness %s: %s",
                        self.harness_name,
                        exc,
                    )
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except ProcessLookupError:
                logger.debug(
                    "ACP harness %s already exited before terminate",
                    self.harness_name,
                )
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        self._process = None
        self._stdout_task = None
        self._stderr_task = None

    async def send_request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> JSONRPCResponse:
        """Send a JSON-RPC request and await its response."""
        request_id = self._next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        future: asyncio.Future[JSONRPCResponse] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        try:
            await self._write_payload(payload)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ACPTransportError(
                f"Timed out waiting for {method} response from {self.harness_name}",
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification."""
        await self._write_payload(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            },
        )

    async def send_result(self, request_id: str | int, result: Any) -> None:
        """Reply to a harness-initiated request with a result."""
        await self._write_payload(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            },
        )

    async def send_error(
        self,
        request_id: str | int,
        *,
        code: int,
        message: str,
    ) -> None:
        """Reply to a harness-initiated request with an error."""
        await self._write_payload(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": code,
                    "message": message,
                },
            },
        )

    async def _write_payload(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise ACPTransportError("Harness process is not running")

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    def _on_reader_task_done(self, stream_name: str, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return

        message = (
            f"ACP harness {self.harness_name} {stream_name} reader failed: {exc}"
        )
        logger.error(message)
        self._fail_pending(message)

    def _fail_pending(self, message: str) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ACPTransportError(message))
        self._pending.clear()

    def _next_request_id(self) -> str:
        self._request_id += 1
        return f"req_{self._request_id}"

    async def _read_stdout(self) -> None:
        if self._process is None or self._process.stdout is None:
            return

        while True:
            line = await self._process.stdout.readline()
            if not line:
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            try:
                message = self._decode_message(text)
            except ACPProtocolError:
                logger.debug("Ignoring non-JSON ACP stdout line: %s", text[:200])
                continue

            if isinstance(message, JSONRPCResponse):
                pending = self._pending.get(str(message.id))
                if pending is not None and not pending.done():
                    pending.set_result(message)
                continue

            await self._incoming.put(message)

    async def _read_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return

        while True:
            line = await self._process.stderr.readline()
            if not line:
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            self._stderr_buffer.append(text)
            if len(self._stderr_buffer) > 100:
                self._stderr_buffer.pop(0)
            logger.debug("ACP harness stderr (%s): %s", self.harness_name, text)

    def _decode_message(
        self,
        raw: str,
    ) -> JSONRPCResponse | JSONRPCRequest | JSONRPCNotification:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ACPProtocolError(f"Invalid JSON-RPC payload: {raw}") from exc

        if not isinstance(data, dict):
            raise ACPProtocolError("JSON-RPC payload must be an object")

        if "method" in data and "id" in data and "result" not in data and "error" not in data:
            return JSONRPCRequest(
                id=data["id"],
                method=str(data["method"]),
                params=data.get("params") or {},
            )

        if "method" in data:
            return JSONRPCNotification(
                method=str(data["method"]),
                params=data.get("params") or {},
            )

        if "id" in data:
            return JSONRPCResponse(
                id=data.get("id"),
                result=data.get("result"),
                error=data.get("error"),
            )

        raise ACPProtocolError(f"Unknown JSON-RPC payload shape: {raw}")
