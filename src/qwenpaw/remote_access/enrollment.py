# -*- coding: utf-8 -*-
"""Console account login and explicit, account-owned Node enrollment."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
import uuid
import base64
from dataclasses import dataclass, replace
from urllib.parse import urlencode, urlsplit

from .platform_client import (
    PLATFORM_OAUTH_CLIENT_ID,
    PlatformRelayClient,
    PlatformSession,
    RelayPlatformError,
)
from .store import RelayNodeState, RelayNodeStore


@dataclass(frozen=True, slots=True)
class RelayEnrollmentStatus:
    """Redacted account and binding metadata for the local Console."""

    status: str
    platform_url: str | None = None
    qwenpaw_id: str | None = None
    name: str | None = None
    authorization_url: str | None = None
    node_id: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    logged_in: bool = False


@dataclass(frozen=True, slots=True)
class PendingOAuth:
    """One expiring PKCE authorization bound to this local process."""

    nonce: str
    state: str
    verifier: str
    redirect_uri: str
    authorization_url: str
    expires_at: float


class RelayEnrollmentService:
    """Keep user-level OAuth credentials separate from Node credentials."""

    def __init__(
        self,
        store: RelayNodeStore,
        *,
        client_factory=PlatformRelayClient,
    ) -> None:
        self.store = store
        self._client_factory = client_factory
        self._lock = store.mutation_lock
        self._pending: PendingOAuth | None = None

    async def status(self) -> RelayEnrollmentStatus:
        """Return current identity without exposing any credentials."""
        state = await asyncio.to_thread(self.store.load)
        pending = self._pending
        if pending and pending.expires_at <= time.monotonic():
            self._pending = None
            pending = None
        registered = state.registered_node if state else None
        return RelayEnrollmentStatus(
            status=(
                "authorization_pending"
                if pending
                else "connected"
                if registered
                else "not_connected"
            ),
            platform_url=state.platform_url if state else None,
            qwenpaw_id=state.qwenpaw_id if state else None,
            name=state.name if state else None,
            authorization_url=pending.authorization_url if pending else None,
            node_id=registered.node_id if registered else None,
            account_id=state.account_id if state else None,
            account_name=state.account_name if state else None,
            logged_in=bool(state and state.session),
        )

    async def start(
        self,
        *,
        platform_url: str,
        name: str,
        callback_origin: str,
    ) -> RelayEnrollmentStatus:
        """Start login without overwriting an existing binding."""
        async with self._lock:
            client = self._client_factory(platform_url)
            state = await asyncio.to_thread(self.store.load)
            if state and state.platform_url != client.base_url:
                raise ValueError("Disconnect the current Platform first")
            if state is None:
                state = self.store.create(
                    platform_url=client.base_url,
                    qwenpaw_id=str(uuid.uuid4()),
                    name=name,
                )
                await asyncio.to_thread(self.store.save, state)
            nonce = secrets.token_urlsafe(24)
            oauth_state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64)
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode("ascii")).digest(),
                )
                .rstrip(b"=")
                .decode("ascii")
            )
            origin = urlsplit(callback_origin)
            if origin.scheme != "https" and not (
                origin.scheme == "http"
                and origin.hostname in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError("Remote Hub Platform login requires HTTPS")
            if (
                not origin.hostname
                or origin.username
                or origin.password
                or origin.query
                or origin.fragment
                or origin.path not in {"", "/"}
            ):
                raise ValueError("Invalid Console callback origin")
            redirect_uri = (
                f"{origin.scheme}://{origin.netloc}/callback/{nonce}"
            )
            query = urlencode(
                {
                    "client_id": PLATFORM_OAUTH_CLIENT_ID,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "state": oauth_state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "scope": "platform:control",
                },
            )
            self._pending = PendingOAuth(
                nonce,
                oauth_state,
                verifier,
                redirect_uri,
                f"{client.base_url}/cli/login?{query}",
                time.monotonic() + 600,
            )
        return await self.status()

    def accepts_callback(self, nonce: str) -> bool:
        """Locate this user's pending callback without a browser cookie."""
        return bool(
            self._pending
            and self._pending.expires_at > time.monotonic()
            and hmac.compare_digest(self._pending.nonce, nonce),
        )

    async def complete_oauth(
        self,
        *,
        nonce: str,
        state_value: str,
        code: str,
    ) -> RelayEnrollmentStatus:
        """Validate PKCE state, keep the user login, and enroll if needed."""
        async with self._lock:
            pending = self._pending
            if (
                not self.accepts_callback(nonce)
                or pending is None
                or not hmac.compare_digest(pending.state, state_value)
            ):
                raise ValueError("Invalid or expired Platform authorization")
            current = await asyncio.to_thread(self.store.load)
            if current is None:
                raise ValueError("Platform login state is missing")
            client = self._client_factory(current.platform_url)
            session = await client.exchange_oauth_code(
                code=code,
                redirect_uri=pending.redirect_uri,
                code_verifier=pending.verifier,
            )
            self._pending = None
            if current.account_id and current.account_id != session.user_id:
                await client.revoke_oauth_refresh_token(session.refresh_token)
                raise ValueError(
                    "Disconnect before switching Platform accounts",
                )
            current = replace(
                current,
                account_id=session.user_id,
                account_name=session.display_name,
                session=session,
            )
            await asyncio.to_thread(self.store.save, current)
            if current.registered_node is None:
                await self._enroll(current, session.access_token)
        return await self.status()

    async def _enroll(self, state: RelayNodeState, access_token: str) -> None:
        client = self._client_factory(state.platform_url)
        enrollment = await client.create_oauth_enrollment(
            access_token=access_token,
            qwenpaw_id=state.qwenpaw_id,
            name=state.name,
            key_pair=state.key_pair,
        )
        registered = await client.register_node(
            qwenpaw_id=state.qwenpaw_id,
            name=state.name,
            enrollment=enrollment,
            key_pair=state.key_pair,
        )
        await asyncio.to_thread(
            self.store.save,
            replace(state, registered_node=registered),
        )

    async def bind(self) -> RelayEnrollmentStatus:
        """Retry enrollment after login without another OAuth exchange."""
        session = await self.active_session()
        async with self._lock:
            current = await asyncio.to_thread(self.store.load)
            if current is None or current.session != session:
                raise ValueError("Platform login changed; retry binding")
            if current.registered_node is None:
                await self._enroll(current, session.access_token)
        return await self.status()

    def cancel_login(self) -> None:
        """Discard an unfinished local authorization."""
        self._pending = None

    async def active_session(self) -> PlatformSession:
        """Refresh a user login without exposing it over the Console API."""
        async with self._lock:
            state = await asyncio.to_thread(self.store.load)
            if state is None or state.session is None:
                raise ValueError("Sign in to Platform first")
            client = self._client_factory(state.platform_url)
            session = state.session
            if session.expires_at <= time.time() + 30:
                try:
                    session = await client.refresh_session(
                        session,
                    )
                except RelayPlatformError as exc:
                    if exc.status_code in {401, 403}:
                        await asyncio.to_thread(
                            self.store.save,
                            replace(state, session=None),
                        )
                    raise
                if session.user_id != state.account_id:
                    raise ValueError("Platform returned a different account")
                state = replace(state, session=session)
                await asyncio.to_thread(self.store.save, state)
            return session

    async def account_request(self, method: str, path: str, body=None):
        """Call a fixed account endpoint using the protected user login."""
        session = await self.active_session()
        state = await asyncio.to_thread(self.store.load)
        if state is None:
            raise ValueError("Sign in to Platform first")
        client = self._client_factory(state.platform_url)
        try:
            return await client.account_request(
                method,
                path,
                session.access_token,
                body,
            )
        except RelayPlatformError as exc:
            if exc.status_code == 401:
                async with self._lock:
                    current = await asyncio.to_thread(self.store.load)
                    if current and current.session == session:
                        await asyncio.to_thread(
                            self.store.save,
                            replace(current, session=None),
                        )
            raise

    async def revoke_binding(self, state: RelayNodeState | None) -> bool:
        """Revoke a detached binding using only its captured credentials."""
        if state is None or state.session is None:
            return state is None or state.registered_node is None
        client = self._client_factory(state.platform_url)
        session = state.session
        try:
            if session.expires_at <= time.time() + 30:
                session = await client.refresh_session(session)
            if session.user_id != state.account_id:
                return False
            try:
                if state.registered_node:
                    node_id = state.registered_node.node_id
                    await client.account_request(
                        "DELETE",
                        f"/api/v1/qwenpaw-relay/nodes/{node_id}",
                        session.access_token,
                    )
            except RelayPlatformError as exc:
                if exc.status_code != 404:
                    raise
            finally:
                await _logout_session(client, session)
        except RelayPlatformError:
            return False
        return True

    async def logout(self) -> None:
        """End this Console login without revoking the Node binding."""
        async with self._lock:
            self._pending = None
            state = await asyncio.to_thread(self.store.load)
            if state and state.session:
                client = self._client_factory(state.platform_url)
                try:
                    await _logout_session(client, state.session)
                finally:
                    await asyncio.to_thread(
                        self.store.save,
                        replace(state, session=None),
                    )


async def _logout_session(
    client: PlatformRelayClient,
    session: PlatformSession,
) -> None:
    await client.revoke_oauth_refresh_token(session.refresh_token)
    await client.account_request(
        "POST",
        "/api/v1/auth/logout",
        session.access_token,
        {},
    )
