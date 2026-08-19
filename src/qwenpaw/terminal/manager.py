# -*- coding: utf-8 -*-
"""Per-workspace terminal session registry and lifecycle owner."""

from __future__ import annotations

import asyncio
import logging
import secrets
import sys
import time
from dataclasses import replace
from pathlib import Path

from .backends import spawn_terminal_backend
from .models import SessionResult, SessionState
from .session import TerminalSession

logger = logging.getLogger(__name__)


class UnknownSessionError(KeyError):
    pass


class TerminalSessionManager:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        max_sessions: int = 16,
        idle_ttl_seconds: float = 1800.0,
        max_retained_bytes: int = 1024 * 1024,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.max_sessions = max_sessions
        self.idle_ttl_seconds = idle_ttl_seconds
        self.max_retained_bytes = max_retained_bytes
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = asyncio.Lock()
        self._closing = False
        self._creating = 0
        self._expiry_handles: dict[str, asyncio.TimerHandle] = {}
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    def _cancel_expiry(self, session_id: str) -> None:
        handle = self._expiry_handles.pop(session_id, None)
        if handle is not None:
            handle.cancel()
        task = self._expiry_tasks.pop(session_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _schedule_expiry(self, session: TerminalSession) -> None:
        self._cancel_expiry(session.session_id)
        if self._closing or session.state is not SessionState.IDLE:
            return
        observed_activity = session.last_activity
        self._expiry_handles[
            session.session_id
        ] = asyncio.get_running_loop().call_later(
            max(0.01, self.idle_ttl_seconds),
            self._expiry_due,
            session.session_id,
            observed_activity,
        )

    def _expiry_due(
        self,
        session_id: str,
        observed_activity: float,
    ) -> None:
        self._expiry_handles.pop(session_id, None)
        if self._closing:
            return
        task = asyncio.create_task(
            self._expire_if_idle(session_id, observed_activity),
            name=f"qwenpaw-terminal-expiry-{session_id}",
        )
        self._expiry_tasks[session_id] = task

        def expiry_finished(finished: asyncio.Task[None]) -> None:
            self._expiry_finished(session_id, finished)

        task.add_done_callback(expiry_finished)

    def _expiry_finished(
        self,
        session_id: str,
        task: asyncio.Task[None],
    ) -> None:
        if self._expiry_tasks.get(session_id) is task:
            self._expiry_tasks.pop(session_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("Terminal expiry task failed: %s", error)

    async def _expire_if_idle(
        self,
        session_id: str,
        observed_activity: float,
    ) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if (
                session is None
                or session.state is not SessionState.IDLE
                or session.last_activity != observed_activity
            ):
                return
            self._sessions.pop(session_id, None)
        await session.close()

    def _take_expired_locked(self) -> list[TerminalSession]:
        now = time.monotonic()
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if session.state is SessionState.CLOSED
            or (
                session.state is SessionState.IDLE
                and now - session.last_activity >= self.idle_ttl_seconds
            )
        ]
        for session_id in expired_ids:
            self._cancel_expiry(session_id)
        return [
            session
            for session_id in expired_ids
            if (session := self._sessions.pop(session_id, None)) is not None
        ]

    async def create(
        self,
        *,
        shell: str | None,
        cwd: Path,
        env: dict[str, str],
        tty: bool,
    ) -> TerminalSession:
        expired: list[TerminalSession]
        async with self._lock:
            if self._closing:
                raise RuntimeError("terminal manager is shutting down")
            expired = self._take_expired_locked()
            if len(self._sessions) + self._creating >= self.max_sessions:
                raise RuntimeError("terminal session limit reached")
            self._creating += 1
            session_id = f"term_{secrets.token_urlsafe(18)}"
        if expired:
            await asyncio.gather(
                *(session.close() for session in expired),
                return_exceptions=True,
            )
        executable = shell or (
            "cmd.exe" if sys.platform == "win32" else "/bin/sh"
        )
        try:
            backend = await spawn_terminal_backend(
                executable,
                cwd,
                env,
                self.max_retained_bytes,
                tty=tty,
            )
            session = TerminalSession(session_id, backend, executable)
        except BaseException:
            async with self._lock:
                self._creating -= 1
            raise
        async with self._lock:
            self._creating -= 1
            if self._closing:
                close_after_create = True
            else:
                self._sessions[session_id] = session
                close_after_create = False
        if close_after_create:
            await session.close()
            raise RuntimeError("terminal manager is shutting down")
        return session

    async def execute(
        self,
        command: str,
        *,
        session_id: str | None,
        shell: str | None,
        cwd: Path,
        env: dict[str, str],
        tty: bool,
        persistent: bool,
        timeout: float,
        yield_time: float,
        max_output_bytes: int,
    ) -> SessionResult:
        if session_id is None:
            session = await self.create(shell=shell, cwd=cwd, env=env, tty=tty)
        else:
            async with self._lock:
                session = self._sessions.get(session_id)
                if session is None:
                    raise UnknownSessionError(session_id)
                self._cancel_expiry(session_id)
        try:
            result = await session.execute(
                command,
                persistent=persistent,
                timeout=timeout,
                yield_time=yield_time,
                max_output_bytes=max_output_bytes,
            )
        except BaseException:
            if session_id is None:
                await self.remove(session.session_id)
            raise
        if not result.running and not persistent and result.output_drained:
            await self.remove(session.session_id)
            return replace(result, session_id=None)
        if not result.running:
            self._schedule_expiry(session)
        return result

    async def interact(
        self,
        session_id: str,
        chars: str,
        *,
        yield_time: float,
        max_output_bytes: int,
        terminate: bool,
    ) -> SessionResult:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise UnknownSessionError(session_id)
            self._cancel_expiry(session_id)
        if terminate:
            await self.remove(session_id)
            return SessionResult(
                session_id=None,
                chunk_id=f"{session_id}:terminated",
                running=False,
                exit_code=None,
                output="",
                original_bytes=0,
                omitted_bytes=0,
                next_cursor=session.backend.capture.end_cursor,
                wall_time_ms=0,
                tty=session.tty,
                degraded=session.degraded,
                terminated=True,
            )
        result = await session.interact(
            chars,
            yield_time=yield_time,
            max_output_bytes=max_output_bytes,
        )
        if (
            not result.running
            and not session.persistent
            and result.output_drained
        ):
            await self.remove(session_id)
            return replace(result, session_id=None)
        if not result.running:
            self._schedule_expiry(session)
        return result

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._cancel_expiry(session_id)
            session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def shutdown(self) -> None:
        async with self._lock:
            self._closing = True
            expiry_handles = list(self._expiry_handles.values())
            self._expiry_handles.clear()
            expiry_tasks = list(self._expiry_tasks.values())
            self._expiry_tasks.clear()
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for handle in expiry_handles:
            handle.cancel()
        for task in expiry_tasks:
            task.cancel()
        if expiry_tasks:
            await asyncio.gather(*expiry_tasks, return_exceptions=True)
        if sessions:
            await asyncio.gather(
                *(session.close() for session in sessions),
                return_exceptions=True,
            )
