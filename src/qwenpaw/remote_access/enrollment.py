# -*- coding: utf-8 -*-
"""Local orchestration for Platform Relay PKCE enrollment."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable
from urllib.parse import urlencode

from .platform_client import PLATFORM_OAUTH_CLIENT_ID, PlatformRelayClient
from .store import RelayNodeState, RelayNodeStore


@dataclass(frozen=True, slots=True)
class RelayEnrollmentStatus:
    """Non-secret enrollment state safe to return to the local Console."""

    status: str
    platform_url: str | None = None
    qwenpaw_id: str | None = None
    name: str | None = None
    authorization_url: str | None = None
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class PendingOAuth:
    """Short-lived PKCE state kept only in the local process."""

    nonce: str
    state: str
    code_verifier: str
    redirect_uri: str
    authorization_url: str
    expires_at: float


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
        self._pending: PendingOAuth | None = None

    async def status(self) -> RelayEnrollmentStatus:
        """Return a redacted view of the current Relay enrollment."""
        state = await asyncio.to_thread(self._store.load)
        return self._public_status(state)

    async def start(
        self,
        *,
        platform_url: str,
        name: str,
        callback_port: int,
    ) -> RelayEnrollmentStatus:
        """Start Platform PKCE OAuth while reusing the local Node key."""
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
                    registered_node=None,
                )
            nonce = secrets.token_urlsafe(24)
            oauth_state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64)
            challenge = _pkce_challenge(verifier)
            redirect_uri = (
                f"http://127.0.0.1:{callback_port}/callback/{nonce}"
            )
            authorization_url = f"{client.base_url}/cli/login?{urlencode({
                'client_id': PLATFORM_OAUTH_CLIENT_ID,
                'redirect_uri': redirect_uri,
                'state': oauth_state,
                'code_challenge': challenge,
                'code_challenge_method': 'S256',
                'scope': 'platform:control',
            })}"
            self._pending = PendingOAuth(
                nonce=nonce,
                state=oauth_state,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
                authorization_url=authorization_url,
                expires_at=time.monotonic() + 600,
            )
            await asyncio.to_thread(self._store.save, state)
            return self._public_status(state)

    async def complete_oauth(
        self,
        *,
        nonce: str,
        state_value: str,
        code: str,
    ) -> RelayEnrollmentStatus:
        """Exchange one validated callback and register the Relay Node."""
        async with self._lock:
            pending = self._active_pending()
            if pending is None:
                raise ValueError("Platform authorization expired")
            if not hmac.compare_digest(pending.nonce, nonce):
                raise ValueError("Platform authorization callback is invalid")
            if not hmac.compare_digest(pending.state, state_value):
                raise ValueError("Platform authorization state is invalid")
            node_state = await asyncio.to_thread(self._store.load)
            if node_state is None:
                raise ValueError("Relay Node identity is missing")
            client = self._client_factory(node_state.platform_url)
            access_token, refresh_token = await client.exchange_oauth_code(
                code=code,
                redirect_uri=pending.redirect_uri,
                code_verifier=pending.code_verifier,
            )
            enrollment = await client.create_oauth_enrollment(
                access_token=access_token,
                qwenpaw_id=node_state.qwenpaw_id,
                name=node_state.name,
                key_pair=node_state.key_pair,
            )
            registered = await client.register_node(
                qwenpaw_id=node_state.qwenpaw_id,
                name=node_state.name,
                enrollment=enrollment,
                key_pair=node_state.key_pair,
            )
            node_state = replace(
                node_state,
                registered_node=registered,
            )
            await asyncio.to_thread(self._store.save, node_state)
            self._pending = None
            if refresh_token:
                try:
                    await client.revoke_oauth_refresh_token(refresh_token)
                except RelayPlatformError:
                    pass
            return self._public_status(node_state)

    def _active_pending(self) -> PendingOAuth | None:
        pending = self._pending
        if pending is not None and pending.expires_at <= time.monotonic():
            self._pending = None
            return None
        return pending

    def _public_status(
        self,
        state: RelayNodeState | None,
    ) -> RelayEnrollmentStatus:
        pending = self._active_pending()
        if pending is not None:
            return RelayEnrollmentStatus(
                status="authorization_pending",
                platform_url=state.platform_url if state else None,
                qwenpaw_id=state.qwenpaw_id if state else None,
                name=state.name if state else None,
                authorization_url=pending.authorization_url,
            )
        return _public_status(state)


def _public_status(state: RelayNodeState | None) -> RelayEnrollmentStatus:
    if state is None:
        return RelayEnrollmentStatus(status="not_connected")
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


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
