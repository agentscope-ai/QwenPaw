# -*- coding: utf-8 -*-
"""Node-side orchestration for authenticated Relay WSS connections."""
from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from collections.abc import Awaitable, Callable

from .node_transport import RelayNodeTransport
from .platform_client import PlatformRelayClient
from .platform_client import RelayPairingTicket
from .store import RelayNodeStore


class RelayNodeConnectionService:
    """Obtain short tickets and maintain the registered Node connection."""

    def __init__(
        self,
        store: RelayNodeStore,
        transport: RelayNodeTransport,
    ) -> None:
        self._store = store
        self._transport = transport
        self._lock = asyncio.Lock()

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
        )

    async def create_pairing_ticket(self) -> RelayPairingTicket:
        """Create QR data while serializing the shared credential nonce."""
        async with self._lock:
            state = await asyncio.to_thread(self._store.load)
            if state is None or state.registered_node is None:
                raise ValueError(
                    "QwenPaw is not registered with Platform Relay",
                )
            client = PlatformRelayClient(state.platform_url)
            ticket = await client.create_node_pairing_ticket(
                state.registered_node,
                state.key_pair,
            )
            if (
                ticket.node_id != state.registered_node.node_id
                or ticket.qwenpaw_id != state.qwenpaw_id
                or ticket.node_public_key_thumbprint
                != state.key_pair.thumbprint()
            ):
                raise ValueError("Platform returned a different Node identity")
            state = replace(
                state,
                registered_node=replace(
                    state.registered_node,
                    dpop_nonce=ticket.next_credential_dpop_nonce,
                ),
            )
            await asyncio.to_thread(self._store.save, state)
            return ticket


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
            try:
                self._status = "connecting"
                self._last_error = None
                await self._connection.connect_once()
                self._status = "reconnecting"
                delay = 1.0
            except Exception as exc:  # noqa: BLE001 - background boundary
                self._status = "reconnecting"
                self._last_error = type(exc).__name__
            await self._sleep(self._jitter(delay))
            delay = min(delay * 2, 30.0)


def _reconnect_jitter(delay: float) -> float:
    return random.uniform(delay * 0.8, delay * 1.2)
