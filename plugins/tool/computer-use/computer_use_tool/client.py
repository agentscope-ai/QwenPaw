# -*- coding: utf-8 -*-
"""Controlled client for the host-managed Computer Use native runtime."""

from __future__ import annotations

import asyncio
import sys
import threading
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from qwenpaw.app.computer_use import (
    HostRuntimeProvider,
    get_current_computer_use_turn_id,
)
from qwenpaw.app.agent_context import get_current_session_id
from qwenpaw.config.context import (
    get_current_session_id as get_tool_session_id,
)

from .approval import ComputerUseApprovalCoordinator
from .protocol import ComputerUseProtocolError, NativeRequest, parse_response
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
_ACQUIRE_RETRY_DELAY_SECONDS = 0.5
# Native methods that synthesize input and therefore pass through the native
# recency guard; only these consume a pending post-approval exemption.
_INPUT_METHODS = frozenset(
    {
        "click",
        "scroll",
        "drag",
        "press_key",
        "type_text",
        "invoke_element",
        "set_value",
        "close_window",
    },
)
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
        self._turn_id: str | None = None
        self._lock = asyncio.Lock()
        self._approvals = ComputerUseApprovalCoordinator()
        # Baseline of window ids seen from the last observation. ``None``
        # until the first observation so we seed state without flagging
        # every existing window as newly opened.
        self._known_window_ids: set[str] | None = None

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
        if (
            method in _INPUT_METHODS
            and self._approvals.intervention_bypass_pending
        ):
            # Carry the one-shot post-approval exemption to the native guard.
            params = {**params, "after_approval": True}
            self._approvals.intervention_bypass_pending = False
        async with self._lock:
            if self._turn_id and self._turn_id != turn_id:
                await self._end_turn(transport, self._turn_id)
            self._turn_id = turn_id
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
                raise

    def observe_windows(self, windows: Any) -> list[dict[str, Any]]:
        """Update the known-window baseline; return newly appeared windows.

        Returns an empty list until a baseline exists so the first
        observation only seeds state instead of reporting every open
        window as new. Used to surface a dialog or prompt that an action
        just opened.
        """
        if not isinstance(windows, list):
            return []
        current: dict[str, dict[str, Any]] = {}
        for window in windows:
            if isinstance(window, Mapping) and window.get("id") is not None:
                current[str(window["id"])] = dict(window)
        known = self._known_window_ids
        self._known_window_ids = set(current)
        if known is None:
            return []
        return [window for wid, window in current.items() if wid not in known]

    @property
    def has_active_turn(self) -> bool:
        """Whether this session currently owns a native Computer Use turn."""
        return self._transport is not None and self._turn_id is not None

    async def stop_turn(self) -> bool:
        """Tell Native to stop this session's active turn immediately."""
        transport = self._transport
        turn_id = self._turn_id
        if transport is None or not turn_id:
            return False
        async with self._lock:
            request = NativeRequest(
                request_id=uuid.uuid4().hex,
                method="stop_turn",
                params={},
                session_id=self._session_id,
                turn_id=turn_id,
                deadline_ms=2000,
            )
            try:
                parse_response(await transport.request(request.to_message()))
            finally:
                self._turn_id = None
        return True

    async def close(self) -> None:
        """End the active turn and close the client transport."""
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

    async def _ensure_transport(self) -> ComputerUseTransport:
        if self._transport is not None:
            return self._transport
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
        transport.set_reverse_request_handler(self._approvals.decide)
        await transport.connect()
        self._transport = transport
        return transport

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

# A client caches per-session state that has to outlive a single tool call --
# the active turn and the window baseline used to notice newly opened windows.
# Nothing tells the plugin when a session is gone, so the cache is bounded
# instead: on insert, idle sessions are dropped oldest-first. The backend is a
# long-lived desktop process, so an unbounded dict would keep every session
# ever seen.
_MAX_CACHED_CLIENTS = 64


def _evict_idle_clients() -> None:
    """Drop cached clients for sessions with no turn in flight.

    The caller holds ``_clients_lock``.
    """
    if len(_clients) < _MAX_CACHED_CLIENTS:
        return
    for session_id, client in list(_clients.items()):
        if len(_clients) < _MAX_CACHED_CLIENTS:
            return
        if not client.has_active_turn:
            del _clients[session_id]


def get_computer_use_client() -> ComputerUseClient:
    """Return the controlled client for the active QwenPaw session."""
    session_id = get_current_session_id() or get_tool_session_id() or ""
    if not session_id:
        raise ComputerUseProtocolError(
            "session_unavailable",
            "Computer Use requires an active session.",
        )
    with _clients_lock:
        client = _clients.get(session_id)
        if client is None:
            _evict_idle_clients()
            client = ComputerUseClient(session_id)
            _clients[session_id] = client
        return client


def is_computer_use_active(session_id: str) -> bool:
    """Return whether a session owns an active native Computer Use turn."""
    client = _clients.get(session_id)
    return client.has_active_turn if client is not None else False


async def stop_computer_use_session(session_id: str) -> bool:
    """Stop the native Computer Use turn currently owned by one session."""
    client = _clients.get(session_id)
    return await client.stop_turn() if client is not None else False


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
