# -*- coding: utf-8 -*-
"""Node-side orchestration for authenticated Relay WSS connections."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import replace
from collections.abc import Awaitable, Callable

from websockets.exceptions import ConnectionClosed

from .node_transport import RelayNodeTransport
from .platform_client import PlatformRelayClient, RelayPlatformError
from .store import RelayNodeStore

logger = logging.getLogger(__name__)


class RelayNodeConnectionService:
    """Obtain short tickets and maintain the registered Node connection."""

    def __init__(
        self,
        store: RelayNodeStore,
        transport: RelayNodeTransport,
    ) -> None:
        self._store = store
        self._transport = transport
        self._lock = store.mutation_lock

    @property
    def connected(self) -> bool:
        """Report a completed WSS handshake rather than enrollment status."""
        return self._transport.connected

    @property
    def connected_at(self) -> float:
        """Return the last successful handshake's monotonic timestamp."""
        return self._transport.connected_at

    async def connect_once(self) -> None:
        """Connect until the WSS closes, persisting each rotated nonce."""
        async with self._lock:
            state = await asyncio.to_thread(self._store.load)
            if state is None or state.registered_node is None:
                raise ValueError(
                    "QwenPaw is not registered with Platform Relay",
                )
            client = PlatformRelayClient(state.platform_url)
            ticket = await client.create_node_connect_ticket(
                state.registered_node,
                state.key_pair,
            )
            registered = replace(
                state.registered_node,
                dpop_nonce=ticket.next_credential_dpop_nonce,
            )
            state = replace(state, registered_node=registered)
            await asyncio.to_thread(self._store.save, state)
        await self._transport.run(
            websocket_url=ticket.websocket_url,
            ticket=ticket.token,
            dpop_nonce=ticket.dpop_nonce,
            key_pair=state.key_pair,
            node_id=registered.node_id,
        )


class RelayNodeSupervisor:
    """Reconnect an enrolled Node without overlapping connection loops."""

    def __init__(
        self,
        connection: RelayNodeConnectionService,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        self._connection = connection
        self._sleep = sleep or asyncio.sleep
        self._jitter = jitter or _reconnect_jitter
        self._task: asyncio.Task[None] | None = None
        self._status = "stopped"
        self._last_error: str | None = None

    @property
    def status(self) -> str:
        """Return the current redacted transport state."""
        if self._connection.connected:
            return "online"
        return self._status

    @property
    def last_error(self) -> str | None:
        """Return only the exception class, never credentials or URLs."""
        return self._last_error

    def start(self) -> None:
        """Start one background reconnect loop if it is not running."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the reconnect loop."""
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._status = "stopped"

    async def _run(self) -> None:
        delay = 1.0
        while True:
            attempt_started = asyncio.get_running_loop().time()
            try:
                self._status = "connecting"
                self._last_error = None
                await self._connection.connect_once()
                self._status = "reconnecting"
                delay = 1.0
            except RelayPlatformError as exc:
                self._last_error = exc.code
                if exc.status_code in {401, 403, 404}:
                    self._status = "authorization_required"
                    return
                self._status = "reconnecting"
            except Exception as exc:  # noqa: BLE001 - background boundary
                if self._connection.connected_at >= attempt_started:
                    delay = 1.0
                self._status = "reconnecting"
                self._last_error = type(exc).__name__
                close_code = (
                    exc.rcvd.code
                    if isinstance(exc, ConnectionClosed) and exc.rcvd
                    else None
                )
                logger.warning(
                    "Relay connection failed: %s, close_code=%s",
                    self._last_error,
                    close_code,
                )
            await self._sleep(self._jitter(delay))
            delay = min(delay * 2, 30.0)


def _reconnect_jitter(delay: float) -> float:
    return random.uniform(delay * 0.8, delay * 1.2)
