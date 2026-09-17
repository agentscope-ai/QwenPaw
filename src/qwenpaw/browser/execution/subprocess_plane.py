# -*- coding: utf-8 -*-
"""Persistent per-workspace subprocess transport for browser execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import socket
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .._proc import kill_process_sync
from ..control_link.playwright.adapter import PlaywrightControlLink
from ..errors import BrowserError, ErrorCause, ErrorCategory
from ..runtime.links import (
    link_for,
    register_local,
    registered_links,
    unregister_local,
)
from ..runtime.ports import ControlLink
from ...utils.io_utils import run_sync_io
from .adjudicator import Adjudicator
from .wire import (
    ExecRequest,
    ExecResult,
    WireProtocolError,
    encode_frame_async,
    exec_request_payload,
    exec_result_from_payload,
    read_frame,
)
from .worker import worker_main

_DEFAULT_IDLE_TTL_SECONDS = 600.0
_DEFAULT_SESSION_IDLE_TTL_SECONDS = 900.0
_DEFAULT_EXEC_TIMEOUT_SECONDS = 120.0
_HANDOFF_PIN_SECONDS = 1800.0
logger = logging.getLogger(__name__)


def _start_worker_process(
    ctx: multiprocessing.context.BaseContext,
    target: Callable[..., None],
    sink: list[tuple[socket.socket, Any]],
) -> None:
    """Create one worker synchronously and report ownership through *sink*."""
    parent_socket, child_socket = socket.socketpair()
    try:
        proc = ctx.Process(target=target, args=(child_socket,), daemon=True)
        proc.start()
    except BaseException:
        parent_socket.close()
        raise
    finally:
        child_socket.close()
    sink.append((parent_socket, proc))


@dataclass
class _Worker:
    proc: Any
    writer: asyncio.StreamWriter
    reader: asyncio.StreamReader
    link_server: "LinkServer"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = 0.0
    pinned_until: float = 0.0


@dataclass
class PageMeta:
    """Plane-owned lifecycle policy for one agent-created page."""

    scope: str = "cycle"
    carry_over: int = 0


class LinkServer:
    """Serve main-process control-link calls for one worker socket."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        link: ControlLink | None,
        adjudicator: Adjudicator | None = None,
        page_registry: dict[tuple[str, str, str, str], PageMeta] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        del link
        self._adjudicator = adjudicator or Adjudicator()
        self._pending: dict[str, asyncio.Future[ExecResult]] = {}
        self._send_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._event_unsubscribe: Callable[[], None] | None = None
        self._event_link: ControlLink | None = None
        self._event_owner: tuple[str, str] | None = None
        self._expected_owner: tuple[str, str] | None = None
        self._closed = False
        self._page_registry = (
            page_registry if page_registry is not None else {}
        )
        self._page_meta_type = PageMeta

    async def start(self) -> None:
        """Start dispatch; execution selects its event source and owner."""
        if self._reader_task is not None:
            return
        self._reader_task = asyncio.create_task(self._read_loop())

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Send a program to the worker and await its matching result."""
        if self._closed:
            raise WireProtocolError("link server is closed")
        if request.request_id in self._pending:
            raise WireProtocolError("duplicate execution request id")
        self._expected_owner = (
            request.owner_workspace_id,
            request.owner_session_id,
        )
        loop = asyncio.get_running_loop()
        result: asyncio.Future[ExecResult] = loop.create_future()
        self._pending[request.request_id] = result
        try:
            await self._send("exec_request", exec_request_payload(request))
            return await result
        finally:
            self._pending.pop(request.request_id, None)
            self._expected_owner = None

    async def _send(self, kind: str, payload: dict[str, Any]) -> None:
        frame = await encode_frame_async(kind, payload)
        async with self._send_lock:
            self._writer.write(frame)
            await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                await self._handle_frame(await read_frame(self._reader))
        except (OSError, WireProtocolError):
            self._fail_pending("browser worker transport disconnected")
            await self.close()

    async def _handle_frame(self, frame: Mapping[str, Any]) -> None:
        kind = frame["kind"]
        payload = frame["payload"]
        if kind == "exec_result":
            result = exec_result_from_payload(payload)
            pending = self._pending.get(result.request_id)
            if pending is not None and not pending.done():
                pending.set_result(result)
            return
        if kind == "ctrl_call":
            await self._handle_control_call(payload)
            return
        if kind == "approval_request":
            await self._handle_approval_request(payload)
            return
        raise WireProtocolError(f"unexpected main-side frame kind: {kind}")

    async def _handle_approval_request(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        expected = {"request_id", "origin", "method", "params"}
        if set(payload) != expected or not all(
            isinstance(payload[name], str)
            for name in ("request_id", "origin", "method")
        ):
            raise WireProtocolError("invalid approval_request fields")
        if not isinstance(payload["params"], dict):
            raise WireProtocolError("invalid approval_request params")
        verdict = self._adjudicator.adjudicate(
            origin=payload["origin"],
            method=payload["method"],
            params=payload["params"],
        )
        await self._send(
            "approval_verdict",
            {
                "request_id": payload["request_id"],
                "decision": verdict.decision.value,
                "reason": verdict.reason,
            },
        )

    # pylint: disable-next=too-many-branches,too-many-statements
    async def _handle_control_call(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        expected = {"call_id", "method", "params"}
        if set(payload) != expected or not isinstance(payload["call_id"], str):
            raise WireProtocolError("invalid ctrl_call payload")
        if not isinstance(payload["method"], str) or not isinstance(
            payload["params"],
            dict,
        ):
            raise WireProtocolError("invalid ctrl_call fields")
        try:
            if self._expected_owner is None:
                raise BrowserError(
                    category=ErrorCategory.FATAL,
                    cause=ErrorCause.API_MISUSE,
                    suggested_action="fatal",
                    reason="control call outside an active execution",
                )
            owner = (
                str(payload["params"].get("workspace_id", "")),
                str(payload["params"].get("session_id", "")),
            )
            if owner != self._expected_owner:
                raise BrowserError(
                    category=ErrorCategory.FATAL,
                    cause=ErrorCause.API_MISUSE,
                    suggested_action="fatal",
                    reason="control call owner mismatch",
                    detail=(
                        f"claimed={owner} anchored={self._expected_owner}"
                    ),
                )
            params = dict(payload["params"])
            variant = str(params.pop("variant", ""))
            if not variant:
                raise WireProtocolError(
                    "control call is missing its birth variant",
                )
            method = payload["method"]
            if method == "link_availability":
                await self._send(
                    "ctrl_result",
                    {
                        "call_id": payload["call_id"],
                        "result": {
                            candidate: bool(
                                link_for(candidate) is not None
                                and link_for(candidate).is_available(),
                            )
                            for candidate in ("chrome", "cdp", "playwright")
                        },
                    },
                )
                return
            page_id = str(params.get("page_id") or "")
            key = (owner[0], owner[1], page_id, variant)
            if method in {"keep_page", "carry_over_page"}:
                result: dict[str, Any]
                meta = self._page_registry.get(key)
                if meta is None:
                    raise BrowserError(
                        category=ErrorCategory.RETRYABLE,
                        cause=ErrorCause.STATE_STALE,
                        suggested_action=(
                            "Use await browser.open(url) to reopen."
                        ),
                        reason="page is no longer available",
                        detail=page_id,
                    )
                if method == "keep_page":
                    meta.scope = "chat"
                    result = {"page_id": page_id, "scope": "chat"}
                else:
                    meta.carry_over = int(params.get("cycles") or 0)
                    result = {
                        "page_id": page_id,
                        "carry_over": meta.carry_over,
                    }
                await self._send(
                    "ctrl_result",
                    {"call_id": payload["call_id"], "result": result},
                )
                return
            present = method == "present_page"
            if present:
                method = "new_page"
            link = self._resolve_link(variant)
            if link is None:
                raise WireProtocolError("browser control link is unavailable")
            self._subscribe_events_for_execution(link)
            result = await link.request(
                method,
                params,
            )
            key = (
                owner[0],
                owner[1],
                str(result.get("page_id") or params.get("page_id") or ""),
                variant,
            )
            if method == "new_page" and key[2]:
                self._page_registry[key] = PageMeta(
                    scope="chat"
                    if present
                    else str(params.get("scope", "cycle")),
                )
            elif method == "close_page" and key[2]:
                self._page_registry.pop(key, None)
            await self._send(
                "ctrl_result",
                {"call_id": payload["call_id"], "result": dict(result)},
            )
        except BrowserError as exc:
            await self._send(
                "ctrl_result",
                {
                    "call_id": payload["call_id"],
                    "error": {
                        "detail": str(exc),
                        "type": "BrowserError",
                        "browser_error_code": getattr(
                            exc,
                            "browser_error_code",
                            "",
                        ),
                        "browser_error": {
                            "category": exc.category.value,
                            "cause": exc.cause.value if exc.cause else None,
                            "suggested_action": exc.suggested_action,
                            "reason": exc.reason,
                            "detail": exc.detail,
                        },
                    },
                },
            )
        # intentional boundary: serialize worker errors onto the wire response.
        except Exception as exc:
            await self._send(
                "ctrl_result",
                {
                    "call_id": payload["call_id"],
                    "error": {
                        "detail": str(exc),
                        "type": type(exc).__name__,
                        "browser_error_code": getattr(
                            exc,
                            "browser_error_code",
                            "",
                        ),
                    },
                },
            )

    def _subscribe_events_for_execution(self, link: ControlLink) -> None:
        """Follow the first concrete control-link variant in this execution."""
        owner = self._expected_owner
        if owner is None:
            return
        if self._event_link is link and self._event_owner == owner:
            return
        if self._event_unsubscribe is not None:
            self._event_unsubscribe()
        subscribe = getattr(link, "on_event_for_owner", None)
        if subscribe is not None:
            self._event_unsubscribe = subscribe(
                owner[0],
                owner[1],
                self._on_event,
            )
        else:
            subscribe = getattr(link, "on_event", None)
            if not callable(subscribe):
                return
            self._event_unsubscribe = subscribe(self._on_event)
        self._event_link = link
        self._event_owner = owner

    def _resolve_link(self, variant: str | None) -> ControlLink | None:
        """Select the main-process control link for this worker request."""
        return link_for(variant or "chrome")

    def _on_event(self, event: Mapping[str, Any]) -> None:
        if not self._closed:
            asyncio.create_task(self._send("event", dict(event)))

    def _fail_pending(self, detail: str) -> None:
        for pending in list(self._pending.values()):
            if not pending.done():
                pending.set_exception(WireProtocolError(detail))

    async def close(self) -> None:
        """Stop dispatch, unsubscribe from events, and close the socket."""
        if self._closed:
            return
        self._closed = True
        if self._event_unsubscribe is not None:
            self._event_unsubscribe()
            self._event_unsubscribe = None
        self._event_link = None
        self._event_owner = None
        if (
            self._reader_task is not None
            and self._reader_task is not asyncio.current_task()
        ):
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._fail_pending("link server closed")
        self._expected_owner = None
        self._writer.close()
        with contextlib.suppress(Exception):
            await self._writer.wait_closed()


class SubprocessPlane:
    """Run serialized wire requests in reusable workspace workers."""

    def __init__(
        self,
        worker_target: Callable[..., None] = worker_main,
        idle_ttl: float = _DEFAULT_IDLE_TTL_SECONDS,
        session_idle_ttl: float = _DEFAULT_SESSION_IDLE_TTL_SECONDS,
        chrome_link: ControlLink | None = None,
        exec_timeout_seconds: float = _DEFAULT_EXEC_TIMEOUT_SECONDS,
    ) -> None:
        self._ctx = multiprocessing.get_context("spawn")
        self._target = worker_target
        self._idle_ttl = idle_ttl
        self._session_idle_ttl = session_idle_ttl
        self._exec_timeout_seconds = exec_timeout_seconds
        self._chrome_link = chrome_link
        if chrome_link is not None:
            register_local(chrome_link, priority=True)
        if link_for("playwright") is None:
            register_local(PlaywrightControlLink())
        self._workers: dict[str, _Worker] = {}
        self._page_registry: dict[tuple[str, str, str, str], PageMeta] = {}
        self._owner_last_used: dict[tuple[str, str], float] = {}
        self._spawn_lock = asyncio.Lock()

    async def _get_or_spawn(self, key: str) -> _Worker:
        worker = self._workers.get(key)
        if worker is not None and worker.proc.is_alive():
            return worker
        async with self._spawn_lock:
            worker = self._workers.get(key)
            if worker is not None and worker.proc.is_alive():
                return worker
            if worker is not None:
                self._workers.pop(key, None)
                await self._terminate(worker)
            created: list[tuple[socket.socket, Any]] = []
            try:
                await run_sync_io(
                    _start_worker_process,
                    self._ctx,
                    self._target,
                    created,
                )
            except BaseException:
                self._abandon_created(created)
                raise
            parent_socket, proc = created[0]
            try:
                parent_socket.setblocking(False)
                reader, writer = await asyncio.open_connection(
                    sock=parent_socket,
                )
                server = LinkServer(
                    reader,
                    writer,
                    self._chrome_link or link_for("chrome"),
                    page_registry=self._page_registry,
                )
                await server.start()
                worker = _Worker(
                    proc=proc,
                    writer=writer,
                    reader=reader,
                    link_server=server,
                )
                self._workers[key] = worker
                return worker
            except BaseException:
                with contextlib.suppress(OSError):
                    parent_socket.close()
                reap = asyncio.ensure_future(self._reap_process(proc))
                with contextlib.suppress(BaseException):
                    await asyncio.shield(reap)
                raise

    @staticmethod
    def _abandon_created(created: list[tuple[socket.socket, Any]]) -> None:
        """Release cancelled spawn resources without waiting in the loop."""
        for parent_socket, proc in created:
            with contextlib.suppress(OSError):
                parent_socket.close()
            terminate = getattr(proc, "terminate", None)
            if terminate is not None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    terminate()

    async def run(self, key: str, request: ExecRequest) -> ExecResult:
        """Send one request, serializing all activity for its worker."""
        worker = await self._get_or_spawn(key)
        try:
            async with worker.lock:
                worker.pinned_until = 0.0
                try:
                    result = await asyncio.wait_for(
                        worker.link_server.execute(request),
                        timeout=self._exec_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    await self._discard(key, worker)
                    return ExecResult(
                        request_id=request.request_id,
                        error={
                            "category": "TIMEOUT",
                            "reason": "browser execution exceeded deadline",
                            "detail": (
                                "browser execution exceeded "
                                f"{self._exec_timeout_seconds}s"
                            ),
                            "teaching": (
                                "Your browser program ran past the time "
                                "limit and was stopped. The session and "
                                "pages are preserved but the page may be "
                                "stuck: take a snapshot to re-assess; if it "
                                "is truly wedged, break out explicitly with "
                                "close_page() or close_session()."
                            ),
                        },
                    )
                except (OSError, WireProtocolError) as exc:
                    await self._discard(key, worker)
                    return ExecResult(
                        request_id=request.request_id,
                        error={
                            "category": "RETRYABLE",
                            "reason": "browser worker terminated unexpectedly",
                            "detail": str(exc),
                            "teaching": (
                                "The browser worker crashed mid-execution. "
                                "The session and pages are preserved; re-run "
                                "your last step against the current page "
                                "state."
                            ),
                        },
                    )
                finally:
                    now = asyncio.get_running_loop().time()
                    worker.last_used = now
                    self._owner_last_used[
                        (
                            request.owner_workspace_id,
                            request.owner_session_id,
                        )
                    ] = now
                return result
        except asyncio.CancelledError:
            await self._discard(key, worker)
            return ExecResult(
                request_id=request.request_id,
                error={
                    "category": "CANCELLED",
                    "reason": "browser execution was cancelled",
                    "detail": "the current browser worker was stopped",
                    "teaching": (
                        "Browser execution was cancelled at your request. "
                        "The session and pages are preserved; observe the "
                        "current page state before continuing."
                    ),
                },
            )

    async def _terminate(self, worker: _Worker) -> None:
        await worker.link_server.close()
        await self._reap_process(worker.proc)

    async def _reap_process(self, proc: Any) -> None:
        """Offload reaping so process waits never block agent turns."""
        await run_sync_io(kill_process_sync, proc)

    async def _discard(self, key: str, worker: _Worker) -> None:
        """Drop a dead worker so a later request can spawn a replacement."""
        if self._workers.get(key) is worker:
            self._workers.pop(key, None)
        await self._terminate(worker)

    async def discard_worker(self, key: str) -> None:
        """Drop worker execution state only; provider sessions live on."""
        worker = self._workers.pop(key, None)
        if worker is not None:
            await self._terminate(worker)

    async def discard_idle_workers(self, ttl: float | None = None) -> None:
        """Drop idle worker execution state only; provider sessions live on."""
        effective_ttl = self._idle_ttl if ttl is None else ttl
        now = asyncio.get_running_loop().time()
        for key, worker in list(self._workers.items()):
            if now < worker.pinned_until:
                continue
            if worker.lock.locked():
                continue
            # Non-strict: a ttl of 0 means "reclaim whatever is idle now", and
            # on Windows loop.time() has ~15ms resolution, so now - last_used
            # is frequently exactly 0 right after a run.
            if now - worker.last_used >= effective_ttl:
                self._workers.pop(key, None)
                await self._terminate(worker)

    def pin(self, key: str, duration: float = _HANDOFF_PIN_SECONDS) -> None:
        """Retain a handoff-pending worker for a bounded action window."""
        worker = self._workers.get(key)
        if worker is not None:
            worker.pinned_until = asyncio.get_running_loop().time() + duration

    async def discard_all_workers(self) -> None:
        """Drop all worker execution state only; provider sessions live on."""
        for key in list(self._workers):
            await self.discard_worker(key)
        if self._chrome_link is not None:
            unregister_local(self._chrome_link)

    async def on_response_cycle_end(
        self,
        workspace_id: str,
        session_id: str,
    ) -> None:
        """Reap cycle pages, broadcast the boundary, and run idle sweeps."""
        owner = (workspace_id, session_id)
        for key, meta in list(self._page_registry.items()):
            if key[:2] != owner or meta.scope == "chat":
                continue
            if meta.carry_over > 0:
                meta.carry_over -= 1
                continue
            link = link_for(key[3])
            try:
                if link is not None:
                    await link.request(
                        "close_page",
                        {
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "page_id": key[2],
                        },
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("cycle-end close_page failed", exc_info=True)
            self._page_registry.pop(key, None)
        for link in registered_links():
            cleanup = getattr(link, "on_response_cycle_end", None)
            if cleanup is None:
                continue
            try:
                await cleanup(owner)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("cycle-end hook failed", exc_info=True)
        await self.discard_idle_workers()
        await self.sweep_idle_sessions()

    async def close_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> None:
        """Reclaim one chat's browser state on every registered link."""
        params = {"workspace_id": workspace_id, "session_id": session_id}
        await self._close_session_links(params)
        for key in list(self._page_registry):
            if key[:2] == (workspace_id, session_id):
                self._page_registry.pop(key, None)
        self._owner_last_used.pop((workspace_id, session_id), None)
        await self.discard_worker(f"{workspace_id}/{session_id}")

    async def _close_session_links(
        self,
        params: dict[str, str],
        *,
        idle_sweep: bool = False,
    ) -> None:
        """Fan out reclaim requests, isolating provider failures by design."""
        for link in registered_links():
            if idle_sweep and not getattr(link, "reclaim_on_idle", True):
                continue
            try:
                await link.request("close_session", params)
            # Isolate a provider failure so it cannot block chat close.
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "close_session failed on %s",
                    getattr(link, "variant", "?"),
                    exc_info=True,
                )

    async def sweep_idle_sessions(self) -> None:
        """Reclaim idle sessions while preserving busy and pinned work."""
        now = asyncio.get_running_loop().time()
        for owner, last_used in list(self._owner_last_used.items()):
            if now - last_used <= self._session_idle_ttl:
                continue
            key = f"{owner[0]}/{owner[1]}"
            worker = self._workers.get(key)
            if worker is not None and now < worker.pinned_until:
                continue
            if worker is not None and worker.lock.locked():
                continue
            if worker is not None:
                await worker.lock.acquire()
            try:
                await self._close_session_links(
                    {"workspace_id": owner[0], "session_id": owner[1]},
                    idle_sweep=True,
                )
                await self.discard_worker(key)
                self._owner_last_used.pop(owner, None)
            finally:
                if worker is not None:
                    worker.lock.release()

    async def close_workspace(self, workspace_id: str) -> None:
        """Reclaim every provider session and worker owned by a workspace."""
        owners = {
            owner
            for owner in self._owner_last_used
            if owner[0] == workspace_id
        }
        for key in self._workers:
            if key.startswith(f"{workspace_id}/"):
                _, session_id = key.split("/", 1)
                owners.add((workspace_id, session_id))
        for owner_workspace_id, session_id in owners:
            await self.close_session(owner_workspace_id, session_id)

    def discard_all_workers_sync(self) -> None:
        """Drop worker execution state only during process exit."""
        for key in list(self._workers):
            worker = self._workers.pop(key)
            with contextlib.suppress(Exception):
                worker.writer.close()
            with contextlib.suppress(Exception):
                kill_process_sync(worker.proc, grace=2.0)
        if self._chrome_link is not None:
            unregister_local(self._chrome_link)
