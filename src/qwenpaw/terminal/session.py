# -*- coding: utf-8 -*-
"""One persistent shell session and its single-command state machine."""

from __future__ import annotations

import asyncio
import re
import secrets
import shlex
import sys
import time

from .backends.base import TerminalBackend
from .input_policy import TerminalInputBuffer, TerminalInputMode
from .models import SessionResult, SessionState
from .shells import shell_kind
from .text_stream import TerminalTextStream


class CancellationRecovery:
    """Outcomes when cleaning up a cancelled execute call."""

    RECOVERED = "recovered"
    NOT_OWNER = "not_owner"
    FAILED = "failed"


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
        self._marker_prefix = b""
        self._marker_re: re.Pattern[bytes] | None = None
        self._marker_candidate_start: int | None = None
        self._marker_span: tuple[int, int] | None = None
        self._exit_code: int | None = None
        self._command_started_at = 0.0
        self._timeout_task: asyncio.Task[None] | None = None
        self._timed_out = False
        self._input_buffer = TerminalInputBuffer()
        self._input_guard_required = False
        self._authorized_input: tuple[str, str] | None = None
        self._text_stream = TerminalTextStream()
        self._command_owner: asyncio.Task[object] | None = None
        self.input_mode = TerminalInputMode.LINE

    @property
    def tty(self) -> bool:
        return self.backend.tty

    @property
    def degraded(self) -> bool:
        return self.backend.degraded

    def _shell_kind(self) -> str:
        return shell_kind(self.shell)

    def _wrap_command(self, command: str, token: str) -> bytes:
        marker = f"QWENPAW_DONE_{token}"
        kind = self._shell_kind()
        if kind == "cmd":
            script = f"{command}\r\necho \x1e{marker}:%errorlevel%\x1f\r\n"
        elif kind == "powershell":
            script = (
                "& {\r\n$LASTEXITCODE=$null; "
                "$__qwenpaw_ok=$true; $__qwenpaw_native=$null\r\n"
                "try {\r\n"
                f"{command}\r\n"
                "$__qwenpaw_ok=$?; $__qwenpaw_native=$LASTEXITCODE\r\n"
                "} catch {\r\n"
                "$__qwenpaw_ok=$false; "
                "$__qwenpaw_native=$LASTEXITCODE; Write-Error $_\r\n"
                "} finally {\r\n"
                "if ($__qwenpaw_ok) {$__qwenpaw_ec=0} "
                "elseif ($null -ne $__qwenpaw_native -and "
                "[int]$__qwenpaw_native -ne 0) "
                "{$__qwenpaw_ec=[int]$__qwenpaw_native} "
                "else {$__qwenpaw_ec=1}; "
                f'[Console]::Out.WriteLine("`u001e{marker}:'
                '$__qwenpaw_ec`u001f")\r\n}\r\n}\r\n'
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
        self._marker_prefix = b"\x1e" + self._marker + b":"
        self._marker_re = re.compile(
            re.escape(self._marker_prefix) + rb"(-?\d+)\x1f\r?\n",
        )
        return script.encode("utf-8")

    async def execute(
        self,
        command: str,
        *,
        persistent: bool,
        input_mode: str | TerminalInputMode = TerminalInputMode.LINE,
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
            self.input_mode = TerminalInputMode.parse(input_mode)
            self._command_started = self.backend.capture.end_cursor
            self._public_cursor = self._command_started
            self._exit_code = None
            self._marker_candidate_start = None
            self._marker_span = None
            self._timed_out = False
            self._input_buffer.clear()
            self._input_guard_required = False
            self._authorized_input = None
            self._text_stream.reset()
            self._command_owner = asyncio.current_task()
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
            self._marker_candidate_start = None
            self._marker_span = (
                retained_start + match.start(),
                retained_start + match.end(),
            )
            self.state = SessionState.IDLE
            self._command_owner = None
            if self._timeout_task is not None:
                self._timeout_task.cancel()
                self._timeout_task = None
        elif self.backend.supervisor.returncode is not None:
            # Without a complete marker, a marker-like suffix is ordinary
            # process output and must no longer be withheld.
            self._marker_candidate_start = None
            self._exit_code = self.backend.supervisor.returncode
            self.state = SessionState.CLOSED
            self._command_owner = None
        else:
            candidate = self._marker_candidate_offset(retained)
            self._marker_candidate_start = (
                None if candidate is None else retained_start + candidate
            )

    def _marker_candidate_offset(self, data: bytes) -> int | None:
        """Locate a complete or trailing partial marker prefix."""
        if not self._marker_prefix:
            return None
        complete = data.find(self._marker_prefix)
        if complete >= 0:
            return complete
        max_overlap = min(len(data), len(self._marker_prefix) - 1)
        for size in range(max_overlap, 0, -1):
            if data.endswith(self._marker_prefix[:size]):
                return len(data) - size
        return None

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

    async def _wait_for_interrupt_marker(self, timeout: float) -> bool:
        """Wait asynchronously for an interrupt to finish the command."""
        deadline = time.monotonic() + max(0.0, timeout)
        observed = self.backend.capture.end_cursor
        while self.state in {
            SessionState.RUNNING,
            SessionState.INTERRUPTING,
        }:
            self._refresh_state()
            if self.state not in {
                SessionState.RUNNING,
                SessionState.INTERRUPTING,
            }:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await self.backend.capture.wait_for_change(observed, remaining)
            observed = self.backend.capture.end_cursor
        return True

    async def _send_interrupt_probe(self) -> None:
        try:
            if self.backend.tty and sys.platform != "win32":
                await self.backend.write(b"\x03")
                if await self._wait_for_interrupt_marker(0.1):
                    return
                # A PTY fd can be inherited without becoming the controlling
                # foreground terminal of the new session.  Linux then accepts
                # ETX but does not turn it into SIGINT.  Signal the managed
                # terminal foreground group as a deterministic fallback.
                await self.backend.interrupt()
            else:
                await self.backend.interrupt()
            # Give the shell-owned completion marker a chance to arrive before
            # asking an idle shell to emit the protocol marker directly.
            if await self._wait_for_interrupt_marker(0.25):
                return
            if (
                self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}
                and self.backend.supervisor.returncode is None
            ):
                await self.backend.write(self._completion_probe())
        except Exception:  # noqa: BLE001
            await self.backend.interrupt()

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
        pending_marker_bytes = 0
        if self._marker_span is not None:
            marker_start, marker_end = self._marker_span
            left_end = max(0, min(len(data), marker_start - chunk_start))
            right_start = max(0, min(len(data), marker_end - chunk_start))
            if marker_start < chunk.cursor and marker_end > chunk_start:
                data = data[:left_end] + data[right_start:]
                next_cursor = max(next_cursor, marker_end)
            if next_cursor == marker_start:
                # The user-output chunk ended exactly before the protocol
                # marker. Consume the marker without requiring an extra empty
                # poll whose only purpose would be protocol housekeeping.
                next_cursor = marker_end
        elif self._marker_candidate_start is not None:
            marker_start = self._marker_candidate_start
            if marker_start < chunk.cursor:
                visible_end = max(
                    0,
                    min(len(data), marker_start - chunk_start),
                )
                data = data[:visible_end]
                next_cursor = marker_start
            pending_marker_bytes = max(
                0,
                self.backend.capture.end_cursor - marker_start,
            )
        self._public_cursor = next_cursor
        running = self.state in {
            SessionState.RUNNING,
            SessionState.INTERRUPTING,
        }
        marker_bytes = 0
        if self._marker_span is not None:
            marker_bytes = self._marker_span[1] - self._marker_span[0]
        original_bytes = max(
            0,
            chunk.original_bytes
            - self._command_started
            - marker_bytes
            - pending_marker_bytes,
        )
        pending_bytes = max(0, self.backend.capture.end_cursor - next_cursor)
        if chunk.omitted_bytes:
            self._text_stream.discard_pending()
        output = self._text_stream.feed(
            data,
            final=not running and pending_bytes == 0,
        )
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
                self._input_buffer.clear()
                self._authorized_input = None
                self.state = SessionState.INTERRUPTING
                await self._send_interrupt_probe()
            elif chars:
                combined = self._input_buffer.preview(chars)
                if self._input_guard_required:
                    if self._authorized_input != (chars, combined):
                        raise PermissionError(
                            "terminal input changed after its security check",
                        )
                    self._authorized_input = None
                ready = self._input_buffer.commit(chars, mode=self.input_mode)
                if not ready:
                    return self._make_result(max_output_bytes)
                await self.backend.write(ready.encode("utf-8"))
            return await self._wait_and_poll(yield_time, max_output_bytes)

    async def preview_input(self, chars: str) -> str:
        """Preview accumulated input for a pre-execution security check."""
        async with self.interaction_lock:
            self._refresh_state()
            if self.state is not SessionState.RUNNING:
                raise RuntimeError(
                    "terminal input can only be written to a running command",
                )
            self._input_guard_required = True
            return self._input_buffer.preview(chars)

    async def authorize_input(self, chars: str, combined: str) -> None:
        """Authorize one exact pending-input snapshot for delivery."""
        async with self.interaction_lock:
            if self._input_buffer.preview(chars) != combined:
                raise RuntimeError(
                    "terminal input changed while approval was pending",
                )
            self._authorized_input = (chars, combined)

    async def discard_input(self) -> None:
        """Discard buffered fragments after a denied input operation."""
        async with self.interaction_lock:
            self._input_buffer.clear()
            self._input_guard_required = False
            self._authorized_input = None

    async def interrupt(self) -> None:
        async with self.interaction_lock:
            if self.state is SessionState.RUNNING:
                self.state = SessionState.INTERRUPTING
                await self._send_interrupt_probe()

    async def recover_cancelled_execution(
        self,
        owner: asyncio.Task[object] | None,
        *,
        timeout: float = 1.5,
    ) -> str:
        """Recover a command owned by a cancelled execute task."""
        async with self.interaction_lock:
            self._refresh_state()
            if self.state is SessionState.IDLE:
                return CancellationRecovery.RECOVERED
            if self._command_owner is not owner:
                return CancellationRecovery.NOT_OWNER
            if self.state not in {
                SessionState.RUNNING,
                SessionState.INTERRUPTING,
            }:
                return CancellationRecovery.FAILED
            self.state = SessionState.INTERRUPTING
            await self._send_interrupt_probe()
            await self._wait_for_interrupt_marker(timeout)
            self._refresh_state()
            if self.state is SessionState.IDLE:
                self.last_activity = time.monotonic()
                return CancellationRecovery.RECOVERED
            return CancellationRecovery.FAILED

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
        self._input_buffer.clear()
        self._input_guard_required = False
        self._authorized_input = None
        self._command_owner = None
        await self.backend.close()
        self.state = SessionState.CLOSED
