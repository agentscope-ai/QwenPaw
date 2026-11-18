# -*- coding: utf-8 -*-
"""Owned resource scopes backed by the existing lifecycle teardown ledger."""

from __future__ import annotations

import asyncio
import inspect
import subprocess
import threading
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Any, Callable
from types import SimpleNamespace

from . import custody
from .errors import ResourceError

_storage_cleanup = ContextVar("sdk_storage_cleanup", default=None)


@dataclass(frozen=True)
class ResourceOwner:
    plugin_id: str
    generation: int
    workspace_id: str = ""
    instance_id: str = ""


class Registration:
    """Idempotent asynchronous release; failed releases remain retryable."""

    def __init__(
        self,
        release: Callable,
        *,
        owner: ResourceOwner,
        description: str,
        _bounded: bool = True,
    ):
        self.owner = owner
        self.description = description
        self._release = release
        self._storage_owner: ResourceOwner | None = None
        self._closer = (
            custody.ConnectionCloser(
                SimpleNamespace(
                    close=(
                        self._release_async
                        if inspect.iscoroutinefunction(release)
                        else self._release_sync
                    ),
                ),
                description,
            )
            if _bounded
            else None
        )
        self._lock = asyncio.Lock()
        self.closed = False

    async def _release_async(self, result=None):
        token = _storage_cleanup.set(
            (self._storage_owner, asyncio.current_task())
            if self._storage_owner is not None
            else None,
        )
        try:
            return await (self._release() if result is None else result)
        finally:
            _storage_cleanup.reset(token)

    def _release_sync(self):
        result = self._release()
        return (
            self._release_async(result)
            if inspect.isawaitable(result)
            else result
        )

    async def close(self) -> None:
        async with self._lock:
            if self.closed:
                return
            if self._closer is not None:
                await self._closer()
            else:
                await self._release_async()
            self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()


class ResourceScope:  # pylint: disable=protected-access
    """Stop resources in reverse order, retaining incomplete stops."""

    def __init__(self, owner: ResourceOwner, guard: Callable):
        self.owner = owner
        self._guard = guard
        self._handles: list[Registration] = []
        self._parent_registration: tuple[
            ResourceScope,
            Registration,
        ] | None = None
        self._errors: list[str] = []
        self._closing = False
        self.closed = False

    def _check(self):
        self._guard()
        if self._closing or self.closed:
            raise ResourceError("Resource scope is closing")

    def defer(
        self,
        callback: Callable,
        description: str = "cleanup",
    ) -> Registration:
        return self._defer(callback, description, bounded=True)

    def _defer(self, callback, description, *, bounded=False):
        self._check()
        self._handles[:] = [
            handle for handle in self._handles if not handle.closed
        ]
        handle = Registration(
            callback,
            owner=self.owner,
            description=description,
            _bounded=bounded,
        )
        handle._storage_owner = self.owner
        self._handles.append(handle)
        return handle

    def child(
        self,
        *,
        workspace_id: str = "",
        instance_id: str = "",
    ) -> ResourceScope:
        self._check()
        owner = ResourceOwner(
            self.owner.plugin_id,
            self.owner.generation,
            workspace_id or self.owner.workspace_id,
            instance_id or self.owner.instance_id,
        )
        child = ResourceScope(owner, self._check)
        handle = self._defer(
            child.close,
            f"scope:{owner.workspace_id}:{owner.instance_id}",
        )
        child._parent_registration = (self, handle)
        return child

    def task(self, coroutine, description: str = "task") -> asyncio.Task:
        try:
            self._check()
        except BaseException:
            if inspect.iscoroutine(coroutine):
                coroutine.close()
            raise
        task = asyncio.create_task(
            coroutine,
            name=f"{self.owner.plugin_id}:{description}",
        )

        async def stop():
            await custody.stop_task(task, description)

        handle = self._defer(stop, description)

        def completed(finished):
            if not finished.cancelled():
                failure = finished.exception()
                if failure is not None:
                    self._errors.append(f"{description}: {failure}")
            handle.closed = True
            if handle in self._handles:
                self._handles.remove(handle)

        task.add_done_callback(completed)
        return task

    def connection(self, client, description: str = "connection"):
        closer = custody.ConnectionCloser(client, description)

        async def close():
            await closer()

        self._defer(close, description)
        return client

    def thread(
        self,
        target: Callable,
        *,
        stop: threading.Event,
        description: str = "thread",
    ):
        self._check()
        thread = threading.Thread(
            target=target,
            name=f"{self.owner.plugin_id}:{description}",
            daemon=True,
        )

        async def close():
            if thread.ident is None:
                return
            await custody.stop_thread(thread, stop, description)

        self._defer(close, description)
        thread.start()
        return thread

    def process(self, args, *, description: str = "process", **kwargs):
        self._check()
        # ResourceScope owns deferred process exit, not this stack frame.
        # pylint: disable-next=consider-using-with
        process = subprocess.Popen(args, **kwargs)  # noqa: S603

        async def close():
            await custody.stop_subprocess(process, description)

        self._defer(close, description)
        return process

    async def close(self) -> None:
        if self.closed:
            return
        self._closing = True
        errors = []
        for handle in reversed(tuple(self._handles)):
            try:
                await handle.close()
            except Exception as exc:
                errors.append(f"{handle.description}: {exc}")
        if errors:
            raise ResourceError("; ".join(errors))
        self.closed = True
        if self._parent_registration is not None:
            parent, handle = self._parent_registration
            handle.closed = True
            if handle in parent._handles:
                parent._handles.remove(handle)
            self._parent_registration = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "closed": self.closed,
            "resources": tuple(
                h.description for h in self._handles if not h.closed
            ),
            "errors": tuple(self._errors),
        }
