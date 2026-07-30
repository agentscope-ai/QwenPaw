# -*- coding: utf-8 -*-
"""Controlled client for the host-managed Computer Use native runtime."""

from __future__ import annotations

import asyncio
import sys
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from qwenpaw.app.computer_use import (
    HostRuntimeProvider,
    RuntimeCapability,
    get_current_computer_use_turn_id,
)
from qwenpaw.config.context import (
    get_current_session_id as get_tool_session_id,
)

from .approval import ComputerUseApprovalCoordinator
from .protocol import (
    PROTOCOL_VERSION,
    ComputerUseProtocolError,
    NativeRequest,
    parse_response,
)
from .transport import (
    ComputerUseTransport,
    UnixSocketTransport,
    WindowsPipeTransport,
)

_DEFAULT_DEADLINE_MS = 10000
# The desktop host spawns the helper process while answering acquire; the
# first spawn after an update can be slowed by antivirus scanning, and
# frozen backends still use a short per-attempt socket timeout, so retry
# the idempotent acquire a few times to cover that cold-start window.
_ACQUIRE_ATTEMPTS = 5

# The helper refuses rather than queues when another session holds the desktop,
# so the waiting is done here. Five attempts with doubling delays give a little
# over two seconds, which covers one action's worth of contention; beyond that
# the model is better told the desktop is busy than left waiting.
_DESKTOP_BUSY_ATTEMPTS = 5
_DESKTOP_BUSY_DELAY_SECONDS = 0.15
_ACQUIRE_RETRY_DELAY_SECONDS = 0.5
TransportFactory = Callable[[], ComputerUseTransport]


class ComputerUseClient:
    """Own one authenticated native connection for one QwenPaw session."""

    def __init__(
        self,
        session_id: str,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        self._session_id = session_id
        self._transport_factory = transport_factory
        self._transport: ComputerUseTransport | None = None
        # The capability this client's transport was built from, kept so a dead
        # endpoint can be reported back rather than reconnected to forever.
        self._capability: RuntimeCapability | None = None
        self._turn_id: str | None = None
        # The turn a stop applied to. Kept here rather than only in the helper
        # because a stop drops the connection, and the helper holds that fact
        # per connection -- a later action in the same turn would otherwise be
        # allowed straight through on a fresh one.
        self._stopped_turn: str | None = None
        self._lock = asyncio.Lock()
        # The loop that created the transport, its reader task and this lock.
        # They may only be touched from there, and control routes arrive on the
        # HTTP server's loop instead.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._approvals = ComputerUseApprovalCoordinator()

    async def execute(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        deadline_ms: int = _DEFAULT_DEADLINE_MS,
    ) -> dict[str, Any]:
        """Execute one native operation through the authenticated transport."""
        transport = await self._ensure_transport()
        turn_id = get_current_computer_use_turn_id()
        if not turn_id:
            raise ComputerUseProtocolError(
                "turn_unavailable",
                "Computer Use is unavailable outside an active agent turn.",
            )
        if turn_id == self._stopped_turn:
            raise ComputerUseProtocolError(
                "turn_stopped",
                "Computer Use was stopped for this turn.",
            )
        async with self._lock:
            if self._turn_id and self._turn_id != turn_id:
                await self._end_turn(transport, self._turn_id)
            self._turn_id = turn_id
            for attempt in range(_DESKTOP_BUSY_ATTEMPTS):
                request = NativeRequest(
                    request_id=uuid.uuid4().hex,
                    method=method,
                    params=params,
                    session_id=self._session_id,
                    turn_id=turn_id,
                    deadline_ms=max(100, deadline_ms),
                )
                try:
                    return parse_response(
                        await transport.request(request.to_message()),
                    )
                except asyncio.CancelledError:
                    # Release the native pipe instance so the helper's serve
                    # thread can exit and future turns can open a fresh one.
                    await self._discard_transport()
                    raise
                except ComputerUseProtocolError as error:
                    if error.code in {
                        "runtime_disconnected",
                        "runtime_unavailable",
                        "request_timeout",
                        "invalid_frame",
                    }:
                        await self._discard_transport()
                    if error.code in {"runtime_disconnected", "invalid_frame"}:
                        # The connection went away mid-request rather than the
                        # action failing, so the endpoint itself is suspect. A
                        # timeout is not: the helper may simply be working.
                        self._forget_capability()
                    if error.code != "desktop_busy":
                        raise
                    if attempt + 1 >= _DESKTOP_BUSY_ATTEMPTS:
                        raise
                    # Another session holds the desktop. The helper refuses
                    # rather than queueing, so the waiting happens here, where
                    # a stop can end it -- a thread parked inside the helper
                    # could not be reached and would act after the user said
                    # no.
                    #
                    # Retrying is safe only because the refusal comes before
                    # the helper touches anything: unlike a timeout, it carries
                    # no chance of an action already half performed.
                    await asyncio.sleep(
                        _DESKTOP_BUSY_DELAY_SECONDS * (2**attempt),
                    )
                    if turn_id == self._stopped_turn:
                        raise ComputerUseProtocolError(
                            "turn_stopped",
                            "Computer Use was stopped for this turn.",
                        ) from error
            raise ComputerUseProtocolError(
                "desktop_busy",
                "Another Computer Use session is using the desktop.",
            )

    @property
    def has_active_turn(self) -> bool:
        """Whether this session currently owns a native Computer Use turn."""
        return self._transport is not None and self._turn_id is not None

    async def stop_turn(self) -> bool:
        """Tell Native to stop this session's active turn immediately."""
        return await self._on_owner_loop(self._stop_turn_here)

    async def _stop_turn_here(self) -> bool:
        """Stop the active turn, on the loop that owns the transport.

        Deliberately takes no lock. An action holds ``_lock`` for its whole
        round trip, and that round trip may be waiting on a person answering an
        approval prompt -- so a stop that queued behind it could not arrive
        until the thing it was meant to interrupt had finished.

        Signal first, then reap. Recording the stop and dropping the connection
        ends any wait at once: closing the transport fails the request still
        in flight, and the helper reaps that turn when its own read fails.
        Asking the helper politely instead would not work -- it serves one
        request per connection, so a stop frame would sit behind the action.
        """
        turn_id = self._turn_id
        if self._transport is None or not turn_id:
            return False
        self._stopped_turn = turn_id
        await self._discard_transport()
        return True

    async def close(self) -> None:
        """End the active turn and close the client transport."""
        await self._on_owner_loop(self._close_here)

    async def end_turn(self) -> bool:
        """Release the native turn this session has finished with.

        Keeps the connection, since the next turn will want it: the helper
        drops
        the turn's screenshots and accessibility handles and carries on
        serving.
        """
        return await self._on_owner_loop(self._end_turn_here)

    async def _end_turn_here(self) -> bool:
        transport = self._transport
        turn_id = self._turn_id
        if transport is None or not turn_id:
            return False
        self._turn_id = None
        await self._end_turn(transport, turn_id)
        return True

    @property
    def owner_loop(self) -> asyncio.AbstractEventLoop | None:
        """The loop this client's transport and lock belong to, if
        connected."""
        return self._loop

    async def _close_here(self) -> None:
        transport = self._transport
        if transport is None:
            return
        try:
            if self._turn_id:
                await self._end_turn(transport, self._turn_id)
        finally:
            self._turn_id = None
            self._transport = None
            await transport.close()

    async def _on_owner_loop(
        self,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Run a client operation on the loop that owns its asyncio state.

        The host runs one event loop per workspace, each on its own thread, and
        the control routes run on the HTTP server's loop. The transport's
        streams, its reader task and this client's lock all belong to whichever
        loop built them, so a coroutine touching them is handed back there
        rather than awaited here.
        """
        loop = self._loop
        if loop is None or loop is asyncio.get_running_loop():
            return await operation()
        try:
            handle = asyncio.run_coroutine_threadsafe(operation(), loop)
        except RuntimeError:
            # The owning loop is gone, so its transport is unusable anyway.
            self._transport = None
            self._turn_id = None
            return None
        return await asyncio.wrap_future(handle)

    async def _ensure_transport(self) -> ComputerUseTransport:
        if self._transport is not None:
            return self._transport
        # Everything created below belongs to this loop, so record it before
        # anything else can be asked to touch it from elsewhere.
        self._loop = asyncio.get_running_loop()
        if self._transport_factory is not None:
            transport = self._transport_factory()
        else:
            capability = await self._acquire_capability()
            if capability is None:
                raise ComputerUseProtocolError(
                    "runtime_unavailable",
                    "Computer Use native runtime is unavailable.",
                )
            transport = (
                WindowsPipeTransport(capability)
                if sys.platform == "win32"
                else UnixSocketTransport(capability)
            )
            # Remembered so a dead endpoint can be reported back to the
            # provider; the next acquire then asks the host for a live one.
            self._capability = capability
        transport.set_reverse_request_handler(self._approvals.decide)
        try:
            await transport.connect()
        except ComputerUseProtocolError:
            # The endpoint named by this capability did not answer, which is
            # what a helper that has gone away looks like from here.
            self._forget_capability()
            raise
        self._transport = transport
        return transport

    def _forget_capability(self) -> None:
        """Report this client's endpoint as dead, so a fresh one is issued."""
        capability, self._capability = self._capability, None
        if capability is not None:
            HostRuntimeProvider.invalidate_capability(capability)

    @staticmethod
    async def _acquire_capability():
        """Acquire the host capability, retrying cold-start misses."""
        for attempt in range(_ACQUIRE_ATTEMPTS):
            # The provider call blocks on a control socket; keep it off the
            # event loop so other sessions stay responsive.
            capability = await asyncio.to_thread(
                HostRuntimeProvider.acquire_capability,
            )
            if capability is not None:
                if capability.protocol_version != PROTOCOL_VERSION:
                    raise ComputerUseProtocolError(
                        "protocol_mismatch",
                        "Computer Use plugin and desktop runtime "
                        "versions are incompatible.",
                    )
                return capability
            if attempt + 1 < _ACQUIRE_ATTEMPTS:
                await asyncio.sleep(_ACQUIRE_RETRY_DELAY_SECONDS)
        return None

    async def _end_turn(
        self,
        transport: ComputerUseTransport,
        turn_id: str,
    ) -> None:
        request = NativeRequest(
            request_id=uuid.uuid4().hex,
            method="end_turn",
            params={},
            session_id=self._session_id,
            turn_id=turn_id,
            deadline_ms=2000,
        )
        try:
            parse_response(await transport.request(request.to_message()))
        except ComputerUseProtocolError:
            pass

    async def _discard_transport(self) -> None:
        """Detach and close the current transport, ignoring shutdown errors."""
        transport = self._transport
        self._transport = None
        self._turn_id = None
        if transport is None:
            return
        try:
            await transport.close()
        except Exception:
            # Closing a broken pipe can raise transport errors; ignore them so
            # the caller can re-raise its own original failure.
            pass


_clients: dict[str, ComputerUseClient] = {}
# The cache is read and written from more than one event loop -- the host runs
# one per workspace on its own thread -- so a plain dict could be mutated while
# another thread iterates it during eviction. The lock covers the get-or-create
# and eviction paths; per-client work happens outside it, guarded by the
# client's own async lock.
_clients_lock = threading.Lock()

# A client caches the per-session native turn that outlives a single tool call.
# Nothing tells the plugin when a session is gone, so the cache is bounded
# instead: on insert, idle sessions are dropped oldest-first. The backend is a
# long-lived desktop process, so an unbounded dict would keep every session
# ever seen.
_MAX_CACHED_CLIENTS = 64


def _retire(client: ComputerUseClient) -> None:
    """Close an evicted client's connection, best effort.

    Dropping the reference alone would leave the pipe or socket open until the
    object happened to be collected. Closing needs to await, and this runs from
    synchronous code holding a threading lock, so the coroutine is handed to
    the
    loop that owns the transport and not waited on.
    """
    loop = client.owner_loop
    if loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(client.close(), loop)
    except RuntimeError:
        # That loop has stopped, so its transport is already unusable.
        pass


def _evict_idle_clients() -> list[ComputerUseClient]:
    """Drop cached clients for sessions with no turn in flight.

    The caller holds ``_clients_lock``. Returns the clients removed so the
    caller can close them outside the lock.
    """
    if len(_clients) < _MAX_CACHED_CLIENTS:
        return []
    evicted = []
    for session_id, client in list(_clients.items()):
        if len(_clients) < _MAX_CACHED_CLIENTS:
            break
        if not client.has_active_turn:
            del _clients[session_id]
            evicted.append(client)
    return evicted


def get_computer_use_client() -> ComputerUseClient:
    """Return the controlled client for the active QwenPaw session."""
    # The request-context module initializes the web workspace stack. Defer it
    # until session lookup so transport and protocol code remain lightweight.
    from qwenpaw.app.agent_context import get_current_session_id

    session_id = get_current_session_id() or get_tool_session_id() or ""
    if not session_id:
        raise ComputerUseProtocolError(
            "session_unavailable",
            "Computer Use requires an active session.",
        )
    with _clients_lock:
        client = _clients.get(session_id)
        evicted: list[ComputerUseClient] = []
        if client is None:
            evicted = _evict_idle_clients()
            if len(_clients) >= _MAX_CACHED_CLIENTS:
                # Every cached session still claims a turn. Refusing keeps the
                # bound real and makes the situation visible, where growing the
                # cache would quietly hold a connection per session forever.
                raise ComputerUseProtocolError(
                    "too_many_sessions",
                    "Too many Computer Use sessions are active; "
                    "finish or stop one before starting another.",
                )
            client = ComputerUseClient(session_id)
            _clients[session_id] = client
    for retired in evicted:
        _retire(retired)
    return client


def _cached_client(session_id: str) -> ComputerUseClient | None:
    """Look up a session's client under the cache lock.

    Control routes reach the cache from the HTTP server's thread while a
    workspace thread may be inserting or evicting, so every read takes the lock
    the rest of this module already uses.
    """
    with _clients_lock:
        return _clients.get(session_id)


def is_computer_use_active(session_id: str) -> bool:
    """Return whether a session owns an active native Computer Use turn."""
    client = _cached_client(session_id)
    return client.has_active_turn if client is not None else False


async def stop_computer_use_session(session_id: str) -> bool:
    """Stop the native Computer Use turn currently owned by one session."""
    client = _cached_client(session_id)
    return await client.stop_turn() if client is not None else False


async def end_computer_use_turn(session_id: str) -> bool:
    """Release the native turn a finished request was holding.

    The turn id is minted per request by the host, and nothing used to retire
    it: a session that used the tool once kept its turn -- and the helper's
    screenshots and accessibility handles -- until the next call happened to
    supply a new id. That also made the cache bound unreachable, since a client
    holding a turn is never evicted.
    """
    client = _cached_client(session_id)
    return await client.end_turn() if client is not None else False


def known_computer_use_sessions() -> list[str]:
    """Every session this process holds a Computer Use client for.

    A pending approval can only exist for one of these: the helper asks through
    the connection a client owns, so the request carries that client's session.
    Turning the feature off therefore has to reach all of them, not only the
    session whoever flipped the switch happened to be looking at.
    """
    with _clients_lock:
        return list(_clients)


async def stop_all_computer_use_turns() -> int:
    """Stop every active native turn across all known sessions.

    Used when the feature is switched off so no automation keeps running.
    Returns the number of turns that were actually stopped.
    """
    stopped = 0
    # Snapshot under the lock, then stop turns without holding it: stop_turn
    # awaits native I/O, and the lock is a sync primitive that must not be held
    # across an await.
    with _clients_lock:
        clients = list(_clients.values())
    for client in clients:
        if await client.stop_turn():
            stopped += 1
    return stopped
