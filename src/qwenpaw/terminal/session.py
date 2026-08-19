# -*- coding: utf-8 -*-
"""One persistent shell session and its single-command state machine."""

from __future__ import annotations

import asyncio
import locale
import re
import secrets
import shlex
import sys
import time

from .backends.base import TerminalBackend
from .models import SessionResult, SessionState

_ANSI_RE = re.compile(
    rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))",
)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(
            locale.getpreferredencoding(False) or "utf-8",
            errors="replace",
        )


class TerminalSession:
    def __init__(
        self,
        session_id: str,
        backend: TerminalBackend,
        shell: str,
    ) -> None:
        self.session_id = session_id
        self.backend = backend
        self.shell = shell
        self.state = SessionState.IDLE
        self.interaction_lock = asyncio.Lock()
        self.last_activity = time.monotonic()
        self.persistent = False
        self._command_started = 0
        self._public_cursor = 0
        self._marker = b""
        self._marker_re: re.Pattern[bytes] | None = None
        self._marker_span: tuple[int, int] | None = None
        self._exit_code: int | None = None
        self._command_started_at = 0.0
        self._timeout_task: asyncio.Task[None] | None = None
        self._timed_out = False

    @property
    def tty(self) -> bool:
        return self.backend.tty

    @property
    def degraded(self) -> bool:
        return self.backend.degraded

    def _shell_kind(self) -> str:
        name = self.shell.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in {"cmd", "cmd.exe"}:
            return "cmd"
        if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            return "powershell"
        return "posix"

    def _wrap_command(self, command: str, token: str) -> bytes:
        marker = f"QWENPAW_DONE_{token}"
        kind = self._shell_kind()
        if kind == "cmd":
            script = f"{command}\r\necho \x1e{marker}:%errorlevel%\x1f\r\n"
        elif kind == "powershell":
            script = (
                f"& {{ {command} }}; $__qwenpaw_ec=$LASTEXITCODE; "
                f"if ($null -eq $__qwenpaw_ec) {{$__qwenpaw_ec=0}}; "
                f'[Console]::Out.WriteLine("`u001e{marker}:'
                '$__qwenpaw_ec`u001f")\r\n'
            )
        else:
            # Keep the command and completion protocol in one parsed shell
            # construct.  If they are sent as separate input lines, an
            # interactive child can consume the queued protocol lines from
            # the shared PTY before write_stdin gets a chance to respond.
            quoted_command = shlex.quote(command)
            script = (
                f"eval {quoted_command}; __qwenpaw_ec=$?; "
                f"printf '\\036{marker}:%s\\037\\n' \"$__qwenpaw_ec\"\n"
            )
        self._marker = marker.encode("ascii")
        self._marker_re = re.compile(
            rb"\x1e" + re.escape(self._marker) + rb":(-?\d+)\x1f(?:\r?\n)?",
        )
        return script.encode("utf-8")

    async def execute(
        self,
        command: str,
        *,
        persistent: bool,
        timeout: float,
        yield_time: float,
        max_output_bytes: int,
    ) -> SessionResult:
        async with self.interaction_lock:
            self._refresh_state()
            if self.state is not SessionState.IDLE:
                raise RuntimeError(f"session is {self.state.value}, not idle")
            token = secrets.token_hex(12)
            self.persistent = persistent
            self._command_started = self.backend.capture.end_cursor
            self._public_cursor = self._command_started
            self._exit_code = None
            self._marker_span = None
            self._timed_out = False
            self._command_started_at = time.monotonic()
            self.state = SessionState.RUNNING
            await self.backend.write(self._wrap_command(command, token))
            self._timeout_task = asyncio.create_task(
                self._enforce_timeout(max(0.1, timeout)),
                name=f"qwenpaw-terminal-timeout-{self.session_id}",
            )
            return await self._wait_and_poll(yield_time, max_output_bytes)

    def _refresh_state(self) -> None:
        if self.state not in {SessionState.RUNNING, SessionState.INTERRUPTING}:
            return
        retained, retained_start, _ = self.backend.capture.retained_since(
            self._command_started,
        )
        match = self._marker_re.search(retained) if self._marker_re else None
        if match:
            self._exit_code = int(match.group(1))
            self._marker_span = (
                retained_start + match.start(),
                retained_start + match.end(),
            )
            self.state = SessionState.IDLE
            if self._timeout_task is not None:
                self._timeout_task.cancel()
                self._timeout_task = None
        elif self.backend.supervisor.returncode is not None:
            self._exit_code = self.backend.supervisor.returncode
            self.state = SessionState.CLOSED

    async def _enforce_timeout(self, timeout: float) -> None:
        try:
            await asyncio.sleep(timeout)
            if self.state is not SessionState.RUNNING:
                return
            self._timed_out = True
            self.state = SessionState.INTERRUPTING
            await self._send_interrupt_probe()
            await asyncio.sleep(1.0)
            self._refresh_state()
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}:
                await self.close()
        except asyncio.CancelledError:
            pass

    def _completion_probe(self, exit_code: int = 130) -> bytes:
        marker = self._marker.decode("ascii")
        kind = self._shell_kind()
        if kind == "cmd":
            return f"\r\necho \x1e{marker}:{exit_code}\x1f\r\n".encode()
        if kind == "powershell":
            return (
                f'\r\n[Console]::Out.WriteLine("`u001e{marker}:'
                f'{exit_code}`u001f")\r\n'
            ).encode()
        return (f"\nprintf '\\036{marker}:{exit_code}\\037\\n'\n").encode()

    async def _send_interrupt_probe(self) -> None:
        try:
            if self.backend.tty and sys.platform != "win32":
                await self.backend.write(b"\x03")
            else:
                await self.backend.supervisor.interrupt()
            # Give the shell-owned completion marker a chance to arrive.  The
            # fallback probe is only needed when line discipline or process
            # termination prevented that marker from being emitted.
            await asyncio.sleep(0.1)
            self._refresh_state()
            if (
                self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}
                and self.backend.supervisor.returncode is None
            ):
                await self.backend.write(self._completion_probe())
        except Exception:  # noqa: BLE001
            await self.backend.supervisor.interrupt()

    async def _wait_and_poll(
        self,
        yield_time: float,
        max_output_bytes: int,
    ) -> SessionResult:
        deadline = time.monotonic() + max(0.0, yield_time)
        observed = self.backend.capture.end_cursor
        while self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}:
            self._refresh_state()
            if self.state not in {
                SessionState.RUNNING,
                SessionState.INTERRUPTING,
            }:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await self.backend.capture.wait_for_change(observed, remaining)
            observed = self.backend.capture.end_cursor
        return self._make_result(max_output_bytes)

    def _make_result(self, max_output_bytes: int) -> SessionResult:
        chunk = self.backend.capture.poll(
            self._public_cursor,
            max_output_bytes,
        )
        chunk_start = chunk.cursor - len(chunk.data)
        next_cursor = chunk.cursor
        data = chunk.data
        if self._marker_span is not None:
            marker_start, marker_end = self._marker_span
            left_end = max(0, min(len(data), marker_start - chunk_start))
            right_start = max(0, min(len(data), marker_end - chunk_start))
            if marker_start < chunk.cursor and marker_end > chunk_start:
                data = data[:left_end] + data[right_start:]
            if next_cursor == marker_start:
                # The user-output chunk ended exactly before the protocol
                # marker. Consume the marker without requiring an extra empty
                # poll whose only purpose would be protocol housekeeping.
                next_cursor = marker_end
        else:
            protocol_prefix = b"\x1eQWENPAW_DONE_"
            prefix_at = data.find(protocol_prefix)
            if prefix_at >= 0:
                # Do not expose or consume a partial protocol marker. Once the
                # suffix arrives, refresh_state records its exact span.
                data = data[:prefix_at]
                next_cursor = chunk_start + prefix_at
        self._public_cursor = next_cursor
        data = _ANSI_RE.sub(b"", data)
        output = _decode(data).strip("\r\n")
        running = self.state in {
            SessionState.RUNNING,
            SessionState.INTERRUPTING,
        }
        marker_bytes = 0
        if self._marker_span is not None:
            marker_bytes = self._marker_span[1] - self._marker_span[0]
        original_bytes = max(
            0,
            chunk.original_bytes - self._command_started - marker_bytes,
        )
        pending_bytes = max(0, self.backend.capture.end_cursor - next_cursor)
        elapsed = int((time.monotonic() - self._command_started_at) * 1000)
        self.last_activity = time.monotonic()
        return SessionResult(
            session_id=self.session_id,
            chunk_id=f"{self.session_id}:{chunk.cursor}",
            running=running,
            exit_code=None if running else self._exit_code,
            output=output,
            original_bytes=original_bytes,
            omitted_bytes=chunk.omitted_bytes,
            next_cursor=next_cursor,
            wall_time_ms=elapsed,
            tty=self.tty,
            degraded=self.degraded,
            timed_out=self._timed_out,
            output_bytes=len(output.encode("utf-8")),
            pending_bytes=pending_bytes,
            output_drained=not running and pending_bytes == 0,
        )

    async def interact(
        self,
        chars: str,
        *,
        yield_time: float,
        max_output_bytes: int,
    ) -> SessionResult:
        async with self.interaction_lock:
            self._refresh_state()
            if self.state is SessionState.CLOSED:
                return self._make_result(max_output_bytes)
            if chars == "\x03" and self.state is SessionState.IDLE:
                # Ctrl-C is idempotent at the tool boundary. A provider may
                # retry an interrupt after the shell has already emitted the
                # completion marker; never queue that retry for the next
                # command.
                return self._make_result(max_output_bytes)
            if chars and self.state is SessionState.IDLE:
                raise RuntimeError(
                    "session is idle; run the next command with "
                    "execute_shell_command and its session_id",
                )
            if chars == "\x03" and self.state is SessionState.RUNNING:
                self.state = SessionState.INTERRUPTING
                await self._send_interrupt_probe()
            elif chars:
                await self.backend.write(chars.encode("utf-8"))
            return await self._wait_and_poll(yield_time, max_output_bytes)

    async def interrupt(self) -> None:
        async with self.interaction_lock:
            if self.state is SessionState.RUNNING:
                self.state = SessionState.INTERRUPTING
                await self._send_interrupt_probe()

    async def close(self) -> None:
        if self.state is SessionState.CLOSED:
            return
        self.state = SessionState.TERMINATING
        current = asyncio.current_task()
        if (
            self._timeout_task is not None
            and self._timeout_task is not current
        ):
            self._timeout_task.cancel()
        self._timeout_task = None
        await self.backend.close()
        self.state = SessionState.CLOSED
