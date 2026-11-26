# -*- coding: utf-8 -*-
"""Per-Hub-user Platform bindings and owner-checked Runtime relaying."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import replace
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request

from ..app.routers.remote_access import callback_router, router
from ..remote_access.runtime import PlatformRuntimeConnection
from ..remote_access.store import RelayNodeStore
from ..utils.http import is_loopback_host
from .auth import HubUser
from .models import RuntimeState


class HubPlatformConnections:
    """A cloud login and Node identity belong to one local Hub account."""

    def __init__(self, root: Path, auth, runtimes, credentials) -> None:
        self.root = root / "secrets" / "platform"
        self.auth = auth
        self.runtimes = runtimes
        self.credentials = credentials
        secret = credentials.get_or_create_system_secret(
            "PLATFORM_BINDING_KEY",
        )
        self._cipher = Fernet(
            base64.urlsafe_b64encode(
                hashlib.sha256(secret.encode("utf-8")).digest(),
            ),
        )
        self.connections: dict[str, PlatformRuntimeConnection] = {}

    def get(self, user: HubUser) -> PlatformRuntimeConnection:
        """Resolve by stable local user ID, including for administrators."""
        if user.user_id not in self.connections:
            directory = self.root / user.user_id
            self.connections[user.user_id] = PlatformRuntimeConnection(
                directory,
                lambda: self._base_url(user.user_id),
                lambda: self._headers(user.user_id),
                hub_managed=True,
                store=RelayNodeStore(
                    directory / "platform-node.json",
                    protect=self._protect,
                    unprotect=self._unprotect,
                ),
            )
        return self.connections[user.user_id]

    def _protect(self, value: str) -> str:
        return "ENC:" + self._cipher.encrypt(value.encode("utf-8")).decode(
            "ascii",
        )

    def _unprotect(self, value: str) -> str:
        if not value.startswith("ENC:"):
            raise ValueError("Invalid Hub Platform credential")
        return self._cipher.decrypt(value[4:].encode("ascii")).decode("utf-8")

    def _runtime(self, user_id: str):
        user = self.auth.get_user(user_id)
        if user is None or user.disabled:
            raise ValueError("Local Hub account is disabled")
        state = self.connections[user_id].store.load()
        if state is None or not state.runtime_id:
            raise ValueError("No Runtime is associated with this account")
        record = self.runtimes.get(state.runtime_id)
        if record.owner_user_id != user_id:
            raise ValueError("Runtime ownership changed")
        if record.state is not RuntimeState.RUNNING:
            raise ValueError("Personal Runtime is not running")
        if not is_loopback_host(record.host):
            raise ValueError("Runtime endpoint must be loopback-only")
        return record

    def _base_url(self, user_id: str) -> str:
        record = self._runtime(user_id)
        return str(
            httpx.URL(
                scheme="http",
                host=record.host.strip("[]"),
                port=record.port,
            ),
        )

    def _headers(self, user_id: str) -> dict[str, str]:
        record = self._runtime(user_id)
        token = self.credentials.get_runtime_secret(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        if not token:
            raise ValueError("Runtime credential is unavailable")
        return {"X-QwenPaw-Runtime-Token": token}

    async def prepare(self, user: HubUser, ensure_runtime) -> None:
        """Fix the binding to this user's personal Runtime before OAuth."""
        record = await ensure_runtime(user)
        if record.owner_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="Runtime not owned")
        connection = self.get(user)
        async with connection.store.mutation_lock:
            state = await asyncio.to_thread(connection.store.load)
            if state is None:
                raise HTTPException(
                    status_code=409,
                    detail="Start login first",
                )
            if state.runtime_id and state.runtime_id != record.runtime_id:
                raise HTTPException(status_code=409, detail="Disconnect first")
            await asyncio.to_thread(
                connection.store.save,
                replace(state, runtime_id=record.runtime_id),
            )

    async def watch(self) -> None:
        """Restore owned connections and stop disabled or moved accounts."""
        for path in self.root.glob("*/platform-node.json"):
            user = await asyncio.to_thread(
                self.auth.get_user,
                path.parent.name,
            )
            if user is not None and not user.disabled:
                self.get(user)
        try:
            while True:
                for user_id, connection in tuple(self.connections.items()):
                    try:
                        await asyncio.to_thread(self._runtime, user_id)
                    except (ValueError, KeyError):
                        await connection.close()
                    else:
                        if connection.supervisor.status != (
                            "authorization_required"
                        ):
                            await connection.start()
                await asyncio.sleep(5)
        finally:
            for connection in self.connections.values():
                await connection.close()


def mount_platform_routes(
    app,
    connections: HubPlatformConnections,
    require_user,
    ensure_runtime,
) -> None:
    """Mount the same Console surface with local-user scoped dependencies."""

    async def scope(
        request: Request,
        user: HubUser = Depends(require_user),
    ) -> None:
        request.state.platform_connection = connections.get(user)

        async def prepare() -> None:
            await connections.prepare(user, ensure_runtime)

        request.state.prepare_platform_login = prepare

    async def callback_scope(request: Request, nonce: str) -> None:
        for user_id, connection in tuple(connections.connections.items()):
            if not connection.account.accepts_callback(nonce):
                continue
            user = await asyncio.to_thread(connections.auth.get_user, user_id)
            if user is None or user.disabled:
                break
            await asyncio.to_thread(connections._runtime, user_id)
            request.state.platform_connection = connection
            return
        raise HTTPException(
            status_code=403,
            detail="Invalid Hub authorization",
        )

    app.include_router(router, prefix="/api", dependencies=[Depends(scope)])
    app.include_router(
        callback_router,
        dependencies=[Depends(callback_scope)],
    )
