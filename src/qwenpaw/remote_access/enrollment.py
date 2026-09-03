# -*- coding: utf-8 -*-
"""Local orchestration for Platform Relay Device OAuth enrollment."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace
from typing import Callable

from .platform_client import PlatformRelayClient
from .store import RelayNodeState, RelayNodeStore


@dataclass(frozen=True, slots=True)
class RelayEnrollmentStatus:
    """Non-secret enrollment state safe to return to the local Console."""

    status: str
    platform_url: str | None = None
    qwenpaw_id: str | None = None
    name: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    expires_in: int | None = None
    interval: int | None = None
    node_id: str | None = None


class RelayEnrollmentService:
    """Serialize enrollment changes and keep secrets only on the Node."""

    def __init__(
        self,
        store: RelayNodeStore,
        *,
        client_factory: Callable[[str], PlatformRelayClient] | None = None,
    ) -> None:
        self._store = store
        self._client_factory = client_factory or PlatformRelayClient
        self._lock = asyncio.Lock()

    async def status(self) -> RelayEnrollmentStatus:
        """Return a redacted view of the current Relay enrollment."""
        state = await asyncio.to_thread(self._store.load)
        return _public_status(state)

    async def start(
        self,
        *,
        platform_url: str,
        name: str,
    ) -> RelayEnrollmentStatus:
        """Start Device OAuth while reusing the stable local Node key."""
        async with self._lock:
            current = await asyncio.to_thread(self._store.load)
            client = self._client_factory(platform_url)
            if current is None:
                state = self._store.create(
                    platform_url=client.base_url,
                    qwenpaw_id=str(uuid.uuid4()),
                    name=name,
                )
            else:
                state = replace(
                    current,
                    platform_url=client.base_url,
                    name=name,
                    authorization=None,
                )
            authorization = await client.start_authorization(
                qwenpaw_id=state.qwenpaw_id,
                name=state.name,
                key_pair=state.key_pair,
            )
            state = replace(state, authorization=authorization)
            await asyncio.to_thread(self._store.save, state)
            return _public_status(state)

    async def complete(self) -> RelayEnrollmentStatus:
        """Poll approval once and register the Node when approved."""
        async with self._lock:
            state = await asyncio.to_thread(self._store.load)
            if state is None or state.authorization is None:
                raise ValueError("No pending Platform Relay authorization")
            client = self._client_factory(state.platform_url)
            enrollment = await client.poll_authorization(
                state.authorization,
                state.key_pair,
            )
            registered = await client.register_node(
                qwenpaw_id=state.qwenpaw_id,
                name=state.name,
                enrollment=enrollment,
                key_pair=state.key_pair,
            )
            state = replace(
                state,
                authorization=None,
                registered_node=registered,
            )
            await asyncio.to_thread(self._store.save, state)
            return _public_status(state)


def _public_status(state: RelayNodeState | None) -> RelayEnrollmentStatus:
    if state is None:
        return RelayEnrollmentStatus(status="not_connected")
    if state.authorization is not None:
        return RelayEnrollmentStatus(
            status="authorization_pending",
            platform_url=state.platform_url,
            qwenpaw_id=state.qwenpaw_id,
            name=state.name,
            user_code=state.authorization.user_code,
            verification_uri=state.authorization.verification_uri,
            expires_in=state.authorization.expires_in,
            interval=state.authorization.interval,
        )
    if state.registered_node is not None:
        return RelayEnrollmentStatus(
            status="connected",
            platform_url=state.platform_url,
            qwenpaw_id=state.qwenpaw_id,
            name=state.name,
            node_id=state.registered_node.node_id,
        )
    return RelayEnrollmentStatus(
        status="not_connected",
        platform_url=state.platform_url,
        qwenpaw_id=state.qwenpaw_id,
        name=state.name,
    )
