# -*- coding: utf-8 -*-
"""Minimal ACP stdio JSON-RPC transport."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .core import ACPProtocolError, ACPTransportError

if TYPE_CHECKING:
    from ...config.config import ACPAgentConfig


@dataclass
class JSONRPCResponse:
    id: str | int | None
    result: Any = None
    error: dict[str, Any] | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class JSONRPCRequest:
    id: str | int
    method: str
    params: dict[str, Any]


@dataclass
class JSONRPCNotification:
    method: str
    params: dict[str, Any]


class ACPTransport:
    STDIO_STREAM_LIMIT = 1024 * 1024

    def __init__(self, agent_name: str, agent_config: ACPAgentConfig):
        self.agent_name = agent_name
        self.config = agent_config
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._request_id = 0
        self._pending: dict[str, asyncio.Future[JSONRPCResponse]] = {}
        self._incoming: asyncio.Queue[
            JSONRPCRequest | JSONRPCNotification
        ] = asyncio.Queue()
        self._owns_process_group = False

    @property
    def incoming(self) -> asyncio.Queue[JSONRPCRequest | JSONRPCNotification]:
        return self._incoming

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self, cwd: str | Path | None = None) -> None:
        if self.is_running():
            await self.close()

        working_dir = Path(cwd or Path.cwd()).expanduser().resolve()
        env = os.environ.copy()
        env.update(self.config.env)

        process_kwargs = self._process_kwargs()
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.STDIO_STREAM_LIMIT,
                cwd=str(working_dir),
                env=env,
                **process_kwargs,
            )
        except Exception as exc:
            raise ACPTransportError(
                f"Failed to delegate external agent {self.agent_name}: {exc}",
                agent=self.agent_name,
            ) from exc

        self._owns_process_group = bool(process_kwargs)
        self._stdout_task = asyncio.create_task(self._read_stream("stdout"))
        self._stdout_task.add_done_callback(self._on_reader_task_done)
        self._stderr_task = asyncio.create_task(self._read_stream("stderr"))
        self._stderr_task.add_done_callback(self._on_reader_task_done)

    async def close(self) -> None:
        process = self._process
        tasks = [self._stdout_task, self._stderr_task]
        owns_process_group = self._owns_process_group

        self._process = None
        self._stdout_task = None
        self._stderr_task = None
        self._owns_process_group = False

        try:
            await self._cancel_tasks(tasks)
        finally:
            self._cancel_pending_requests()
            await self._shutdown_process(
                process,
                owns_process_group=owns_process_group,
            )

    async def send_request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> JSONRPCResponse:
        request_id = self._next_request_id()
        future: asyncio.Future[
            JSONRPCResponse
        ] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write_payload(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
            )
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            message = (
                f"Timed out waiting for {method} response "
                f"from {self.agent_name}"
            )
            raise ACPTransportError(
                message,
                agent=self.agent_name,
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def send_result(self, request_id: str | int, result: Any) -> None:
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
        await self._write_payload(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            },
        )

    def _process_kwargs(self) -> dict[str, Any]:
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    async def _write_payload(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise ACPTransportError(
                "Agent process is not running",
                agent=self.agent_name,
            )
        self._process.stdin.write(
            json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n",
        )
        await self._process.stdin.drain()

    async def _cancel_tasks(
        self,
        tasks: list[asyncio.Task[None] | None],
    ) -> None:
        for task in tasks:
            if task is None or task.done():
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def _cancel_pending_requests(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def _shutdown_process(
        self,
        process: asyncio.subprocess.Process | None,
        *,
        owns_process_group: bool,
    ) -> None:
        if process is None:
            return
        if process.returncode is not None:
            try:
                await process.wait()
            except Exception:
                pass
            return

        await self._close_stdin(process)
        try:
            self._terminate_process(
                process,
                owns_process_group=owns_process_group,
            )
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except ProcessLookupError:
            return
        except asyncio.TimeoutError:
            try:
                self._kill_process(
                    process,
                    owns_process_group=owns_process_group,
                )
                await process.wait()
            except (ProcessLookupError, Exception):
                pass

    async def _close_stdin(self, process: asyncio.subprocess.Process) -> None:
        if process.stdin is None:
            return
        try:
            process.stdin.close()
            wait_closed = getattr(process.stdin, "wait_closed", None)
            if callable(wait_closed):
                await wait_closed()
        except Exception:
            pass

    def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        *,
        owns_process_group: bool,
    ) -> None:
        if owns_process_group and os.name != "nt":
            self._signal_process_group(process, signal.SIGTERM)
            return
        process.terminate()

    def _kill_process(
        self,
        process: asyncio.subprocess.Process,
        *,
        owns_process_group: bool,
    ) -> None:
        if owns_process_group and os.name != "nt":
            self._signal_process_group(process, signal.SIGKILL)
        elif os.name == "nt":
            self._kill_process_tree_win32(process.pid)
        else:
            process.kill()

    def _signal_process_group(
        self,
        process: asyncio.subprocess.Process,
        sig: int,
    ) -> None:
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except Exception:
            try:
                if sig == signal.SIGKILL:
                    process.kill()
                else:
                    process.terminate()
            except Exception:
                pass

    def _kill_process_tree_win32(self, pid: int) -> None:
        try:
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass

    def _on_reader_task_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        self._fail_pending(f"ACP agent {self.agent_name} reader failed: {exc}")

    def _fail_pending(self, message: str) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(
                    ACPTransportError(message, agent=self.agent_name),
                )
        self._pending.clear()

    def _next_request_id(self) -> str:
        self._request_id += 1
        return f"req_{self._request_id}"

    async def _read_stream(self, stream_name: str) -> None:
        if self._process is None:
            return
        stream = getattr(self._process, stream_name, None)
        if stream is None:
            return

        while True:
            line = await stream.readline()
            if not line:
                break
            if stream_name != "stdout":
                continue
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = self._decode_message(text)
            except ACPProtocolError:
                continue
            if isinstance(message, JSONRPCResponse):
                pending = self._pending.get(str(message.id))
                if pending is not None and not pending.done():
                    pending.set_result(message)
                continue
            await self._incoming.put(message)

    def _decode_message(
        self,
        raw: str,
    ) -> JSONRPCResponse | JSONRPCRequest | JSONRPCNotification:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ACPProtocolError(
                f"Invalid JSON-RPC payload: {raw}",
                agent=self.agent_name,
            ) from exc

        if not isinstance(data, dict):
            raise ACPProtocolError(
                "JSON-RPC payload must be an object",
                agent=self.agent_name,
            )

        if "method" in data:
            if "id" in data and "result" not in data and "error" not in data:
                return JSONRPCRequest(
                    id=data["id"],
                    method=str(data["method"]),
                    params=data.get("params") or {},
                )
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

        raise ACPProtocolError(
            f"Unknown JSON-RPC payload shape: {raw}",
            agent=self.agent_name,
        )
