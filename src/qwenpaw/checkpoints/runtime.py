# -*- coding: utf-8 -*-
"""Workspace service lifecycle and automatic snapshot scheduling."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from ..utils.io_utils import run_sync_io
from .policy import CheckpointPolicy, DEFAULT_AUTO_DEBOUNCE_SECONDS
from .repository import CheckpointRepository
from .service import CheckpointService
from .policy import session_key

logger = logging.getLogger("qwenpaw.checkpoints")

_AUTO_GC_INTERVAL_SECONDS = 15 * 60


class Debouncer:
    """Asyncio debounce helper keyed by workspace/session."""

    def __init__(self, delay_time: float = DEFAULT_AUTO_DEBOUNCE_SECONDS):
        self.delay = delay_time
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._tasks_by_key: dict[str, set[asyncio.Task[None]]] = {}

    def schedule(
        self,
        key: str,
        coro_factory: Callable[[], Coroutine[Any, Any, None]],
        delay: float | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        handle = self._pending.pop(key, None)
        if handle is not None:
            handle.cancel()

        def _run() -> None:
            self._pending.pop(key, None)
            task = asyncio.create_task(coro_factory())
            self._tasks.add(task)
            self._tasks_by_key.setdefault(key, set()).add(task)

            def _done(completed: asyncio.Task[None]) -> None:
                self._tasks.discard(completed)
                keyed_tasks = self._tasks_by_key.get(key)
                if keyed_tasks is None:
                    return
                keyed_tasks.discard(completed)
                if not keyed_tasks:
                    self._tasks_by_key.pop(key, None)

            task.add_done_callback(_done)

        self._pending[key] = loop.call_later(
            self.delay if delay is None else delay,
            _run,
        )

    def cancel_pending(self, key: str) -> tuple[asyncio.Task[None], ...]:
        """Cancel a pending timer and return snapshots already running."""
        handle = self._pending.pop(key, None)
        if handle is not None:
            handle.cancel()
        return tuple(self._tasks_by_key.get(key, ()))

    def cancel_all(self) -> None:
        for handle in self._pending.values():
            handle.cancel()
        self._pending.clear()

    async def wait_all(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


class CheckpointRuntime:
    """Own workspace-scoped services and automatic snapshot scheduling."""

    def __init__(self) -> None:
        self._services: dict[str, CheckpointService] = {}
        self._initializing: dict[
            str,
            asyncio.Task[CheckpointService],
        ] = {}
        self._lock = threading.Lock()
        self._generation = 0
        self._last_auto_gc: dict[str, float] = {}
        self.debouncer = Debouncer()

    def get_for_workspace(self, workspace: Any) -> CheckpointService:
        service = self.get_for_workspace_dir(workspace.workspace_dir)
        service.workspace = workspace
        return service

    async def get_for_workspace_async(
        self,
        workspace: Any,
    ) -> CheckpointService:
        """Return a service without blocking the event loop on first use."""
        service = await self.get_for_workspace_dir_async(
            workspace.workspace_dir,
        )
        service.workspace = workspace
        return service

    async def get_for_workspace_dir_async(
        self,
        workspace_dir: str | Path,
    ) -> CheckpointService:
        """Initialize one workspace service in a worker, single-flight."""
        key = await run_sync_io(self._workspace_key, workspace_dir)
        with self._lock:
            service = self._services.get(key)
            if service is not None:
                return service
            task = self._initializing.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._initialize_service(key),
                    name=f"checkpoint-init:{key}",
                )
                self._initializing[key] = task

                def _completed(
                    completed: asyncio.Task[CheckpointService],
                ) -> None:
                    self._finish_initialization(key, completed)

                task.add_done_callback(_completed)
        return await asyncio.shield(task)

    async def _initialize_service(self, key: str) -> CheckpointService:
        repository, policy = await run_sync_io(
            self._initialize_storage,
            key,
        )
        # Construct asyncio primitives on the application event loop.
        return CheckpointService(
            key,
            repository=repository,
            policy=policy,
        )

    @staticmethod
    def _initialize_storage(
        key: str,
    ) -> tuple[CheckpointRepository, CheckpointPolicy]:
        repository = CheckpointRepository(key)
        return repository, CheckpointPolicy(repository.config_file)

    @staticmethod
    def _workspace_key(workspace_dir: str | Path) -> str:
        return str(Path(workspace_dir).expanduser().resolve())

    def _finish_initialization(
        self,
        key: str,
        task: asyncio.Task[CheckpointService],
    ) -> None:
        with self._lock:
            if self._initializing.get(key) is task:
                self._initializing.pop(key, None)
            if task.cancelled():
                return
            try:
                service = task.result()
            except Exception:
                logger.exception(
                    "Checkpoint service initialization failed for %s",
                    key,
                )
                return
            self._services.setdefault(key, service)
            self._last_auto_gc.setdefault(key, time.monotonic())

    def get_for_workspace_dir(
        self,
        workspace_dir: str | Path,
    ) -> CheckpointService:
        key = str(Path(workspace_dir).expanduser().resolve())
        with self._lock:
            service = self._services.get(key)
            if service is None:
                service = CheckpointService(key)
                self._services[key] = service
                self._last_auto_gc[key] = time.monotonic()
            return service

    async def schedule_auto_snapshot(
        self,
        workspace: Any,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        query_text: str | None = None,
    ) -> None:
        if not session_id:
            return
        service = await self.get_for_workspace_async(workspace)
        auto_enabled, debounce_seconds = await service.auto_settings()
        if not auto_enabled:
            return
        key = session_key(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
        )
        debounce_key = f"{service.workspace_dir}:{key}"
        workspace_key = str(service.workspace_dir)
        with self._lock:
            generation = self._generation

        async def _snapshot() -> None:
            try:
                # The setting may have been disabled while this debounced task
                # was waiting to run.
                if not (await service.auto_settings())[0]:
                    return
                with self._lock:
                    if (
                        generation != self._generation
                        or self._services.get(workspace_key) is not service
                    ):
                        return
                await service.make_auto_checkpoint(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    query=query_text,
                )

                now = time.monotonic()
                with self._lock:
                    last_gc = self._last_auto_gc.get(workspace_key, 0.0)
                    should_gc = now - last_gc >= _AUTO_GC_INTERVAL_SECONDS
                    if should_gc:
                        self._last_auto_gc[workspace_key] = now
                if should_gc:
                    await service.gc(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                    )
            except Exception:
                logger.exception("Checkpoint auto snapshot failed")

        self.debouncer.schedule(
            debounce_key,
            _snapshot,
            delay=debounce_seconds,
        )

    async def flush_and_close_all(self) -> None:
        self.debouncer.cancel_all()
        with self._lock:
            self._generation += 1
            initializing = tuple(self._initializing.values())
        if initializing:
            await asyncio.gather(*initializing, return_exceptions=True)
        await self.debouncer.wait_all()
        with self._lock:
            self._services.clear()
            self._last_auto_gc.clear()

    async def delete_session_checkpoints(
        self,
        workspace: Any,
        sessions: list[tuple[str, str, str]],
    ) -> tuple[str, ...]:
        """Quiesce auto snapshots, then remove session checkpoint state."""
        with self._lock:
            cached = next(
                (
                    (key, candidate)
                    for key, candidate in self._services.items()
                    if candidate.workspace is workspace
                ),
                None,
            )
        if cached is not None:
            workspace_key, service = cached
            workspace_dir = service.workspace_dir
        else:
            workspace_key = await run_sync_io(
                self._workspace_key,
                workspace.workspace_dir,
            )
            workspace_dir = Path(workspace_key)
            with self._lock:
                service = self._services.get(workspace_key)
        if service is None:
            storage_exists = await run_sync_io(
                (workspace_dir / "checkpoints" / "shadow.git").is_dir,
            )
            if not storage_exists:
                return ()
            service = await self.get_for_workspace_dir_async(workspace_dir)
        service.workspace = workspace
        active_tasks: set[asyncio.Task[None]] = set()
        for session_id, user_id, channel in sessions:
            key = session_key(
                channel=channel,
                user_id=user_id,
                session_id=session_id,
            )
            debounce_key = f"{service.workspace_dir}:{key}"
            active_tasks.update(self.debouncer.cancel_pending(debounce_key))
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        return await service.delete_sessions(sessions)


RUNTIME = CheckpointRuntime()
