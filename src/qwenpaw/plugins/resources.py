# -*- coding: utf-8 -*-
"""Owned resource scopes backed by the existing lifecycle teardown ledger."""

from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import threading
from dataclasses import dataclass
from contextvars import ContextVar, copy_context
from collections.abc import Coroutine, Mapping, Sequence
from os import PathLike
from typing import Any, Callable, ParamSpec, TypeVar
from types import SimpleNamespace

from . import custody
from .errors import ResourceError

_storage_cleanup = ContextVar("sdk_storage_cleanup", default=None)
_T = TypeVar("_T")
_P = ParamSpec("_P")


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
        self._cleanup_error: dict[str, str] | None = None

    async def _release_async(self, result=None):
        token = _storage_cleanup.set(
            (
                (self._storage_owner, asyncio.current_task())
                if self._storage_owner is not None
                else None
            ),
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
            try:
                if self._closer is not None:
                    await self._closer()
                else:
                    await self._release_async()
            except (Exception, asyncio.CancelledError) as exc:
                self._cleanup_error = {
                    "description": self.description,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                raise
            self._cleanup_error = None
            self.closed = True

    async def __aenter__(self) -> Registration:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class ResourceScope:  # pylint: disable=protected-access
    """Stop resources in reverse order, retaining incomplete stops."""

    def __init__(self, owner: ResourceOwner, guard: Callable):
        self.owner = owner
        self._guard = guard
        self._handles: list[Registration] = []
        self._parent_registration: (
            tuple[
                ResourceScope,
                Registration,
            ]
            | None
        ) = None
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

    def task(
        self,
        coroutine: Coroutine[Any, Any, _T],
        description: str = "task",
    ) -> asyncio.Task[_T]:
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

    def connection(
        self,
        client: _T,
        description: str = "connection",
        timeout: float | None = None,
    ) -> _T:
        """Own a connection and bound each close attempt.

        ``timeout`` overrides the host's five-second default, in seconds.
        Composite connections derive it from their child stop budgets.
        Incomplete closes remain owned and can be retried.
        """
        closer = custody.ConnectionCloser(client, description, timeout=timeout)

        async def close():
            await closer()

        self._defer(close, description)
        return client

    def thread(
        self,
        target: Callable[[], object],
        *,
        stop: threading.Event,
        description: str = "thread",
    ) -> threading.Thread:
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

    async def run_sync(
        self,
        function: Callable[_P, _T],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T:
        """Run blocking work; cancellation never releases a live thread.

        Cancelling the waiter does not stop the function. Closing the scope
        joins the actual thread and reports incomplete cleanup on timeout.
        A callback's StopIteration is raised as the cause of a RuntimeError.
        """
        self._check()
        loop = asyncio.get_running_loop()
        result: asyncio.Future[_T] = loop.create_future()
        inherited = copy_context()

        def completed(deliver, value):
            # The result may arrive before thread-local destructors finish.
            if thread.is_alive():
                loop.call_later(0.001, completed, deliver, value)
                return
            handle.closed = True
            if handle in self._handles:
                self._handles.remove(handle)
            deliver(value)

        def run() -> None:
            try:
                value = inherited.run(function, *args, **kwargs)
            except BaseException as exc:
                if isinstance(exc, StopIteration):
                    error = RuntimeError(
                        "run_sync callback raised StopIteration",
                    )
                    error.__cause__ = exc
                    exc = error
                loop.call_soon_threadsafe(completed, result.set_exception, exc)
            else:
                loop.call_soon_threadsafe(completed, result.set_result, value)

        thread = threading.Thread(
            target=run,
            name=f"{self.owner.plugin_id}:run_sync",
            daemon=True,
        )

        async def close():
            if thread.ident is not None:
                await custody.stop_thread(thread, None, "run_sync")

        # Observe late exceptions even when the original waiter is cancelled.
        result.add_done_callback(lambda done: done.exception())
        handle = self._defer(close, "run_sync")
        thread.start()
        return await asyncio.shield(result)

    def process(
        self,
        args: (
            str
            | bytes
            | PathLike[str]
            | PathLike[bytes]
            | Sequence[str | bytes | PathLike[str] | PathLike[bytes]]
        ),
        *,
        description: str = "process",
        tree: bool = False,
        **kwargs: Any,
    ) -> subprocess.Popen[bytes] | subprocess.Popen[str]:
        self._check()
        if tree:
            self._tree_options(kwargs)
        # ResourceScope owns deferred process exit, not this stack frame.
        # pylint: disable-next=consider-using-with
        process = subprocess.Popen(args, **kwargs)  # noqa: S603
        owned_tree = None

        async def close():
            nonlocal owned_tree
            if tree and owned_tree is None:
                owned_tree = self._process_tree(process.pid)
            if owned_tree is None:
                await custody.stop_subprocess(process, description)
            else:
                await custody.stop_process_tree(
                    process,
                    owned_tree,
                    description,
                )

        self._defer(close, description)
        if tree:
            # Keep custody even if OS identity inspection fails after spawn.
            owned_tree = self._process_tree(process.pid)
        return process

    @staticmethod
    def _tree_options(options: dict) -> None:
        # Generic programs can spawn before a Windows Job is attached. Until
        # creation is suspended/assigned atomically, fail before spawning.
        if os.name == "nt":
            raise ResourceError("tree=True is not yet supported on Windows")
        from .execution.process_tree import ProcessTree

        try:
            ProcessTree.check_session_visibility()
        except OSError as exc:
            raise ResourceError(
                "tree=True requires OS process-session visibility",
            ) from exc
        if (
            options.get("start_new_session") is False
            or options.get(
                "process_group",
                -1,
            )
            != -1
        ):
            raise ResourceError("tree=True requires an owned process session")
        options["start_new_session"] = True

    @staticmethod
    def _process_tree(pid: int):
        from .execution.process_tree import ProcessTree

        return ProcessTree(pid, session=True)

    async def async_process(
        self,
        args: Sequence[str | PathLike[str]],
        *,
        description: str = "process",
        tree: bool = False,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> asyncio.subprocess.Process:
        """Start an asynchronous process; retain ownership during spawning.

        Use asyncio.subprocess.PIPE for interactive streams. tree=True owns
        a POSIX session, including job-control groups after its leader exits.
        Descendants must not detach into a new session.
        """
        self._check()
        options = {}
        if tree:
            self._tree_options(options)
        owned_tree = None
        process = None

        async def spawn():
            nonlocal owned_tree, process
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                **options,
            )
            if tree:
                owned_tree = self._process_tree(process.pid)
            return process

        async def close():
            nonlocal owned_tree
            # A cancelled caller can leave OS creation in progress. Never
            # cancel the spawn task or lose the eventual process handle.
            _, pending = await asyncio.wait(
                {starting},
                timeout=custody.PROCESS_STOP_SECONDS,
            )
            if pending:
                raise ResourceError("Process creation is still in progress")
            if process is None:
                return  # Creation failed without handing out a process.
            if tree and owned_tree is None:
                owned_tree = self._process_tree(process.pid)
            if owned_tree is not None:
                await custody.stop_process_tree(
                    process,
                    owned_tree,
                    description,
                )
            else:
                await custody.stop_async_process(process, description)

        self._defer(close, description)
        starting = asyncio.create_task(spawn())
        starting.add_done_callback(lambda done: done.exception())
        return await asyncio.shield(starting)

    async def __aenter__(self) -> ResourceScope:
        self._check()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

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
        """Describe ownership, background errors and pending cleanup failures.

        cleanup_errors contains the latest failed close attempt for each
        still-open registration. Successful retry removes that entry; it does
        not retry the business operation or imply its side effects failed.
        """
        return {
            "owner": self.owner,
            "closed": self.closed,
            "resources": tuple(
                h.description for h in self._handles if not h.closed
            ),
            "errors": tuple(self._errors),
            "cleanup_errors": tuple(
                dict(handle._cleanup_error)
                for handle in self._handles
                if not handle.closed and handle._cleanup_error is not None
            ),
        }
