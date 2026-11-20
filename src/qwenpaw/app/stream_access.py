"""Enforce continuing device, user, agent and plugin access on authenticated SSE."""

import asyncio
import logging
from contextlib import ExitStack

import anyio
from starlette.datastructures import Headers

from ..access.agent_repository import PostgresAgentRepository
from ..access.stream_revocation import listen
from ..identity.runtime import get_identity_runtime, get_identity_schema

logger = logging.getLogger(__name__)
RECHECK_SECONDS = 5
CHECK_TIMEOUT_SECONDS = 3


async def _still_authorized(authenticated, accesses, plugin) -> bool:
    fresh = await get_identity_runtime().sessions.active_parent_session(
        authenticated.session.id,
        authenticated.user.id,
    )
    if fresh is None or fresh.user.platform_role != authenticated.user.platform_role:
        return False
    if plugin is not None:
        from ..plugins.governance import PluginAccessError
        from .routers.frontend_plugin import get_plugin_governance_service

        plugin_id, actor = plugin
        try:
            await get_plugin_governance_service().require_app_access(actor, plugin_id)
        except PluginAccessError:
            return False
    if not accesses:
        return True
    repo = PostgresAgentRepository(schema=get_identity_schema())
    records = await repo.list_accessible(
        agent_keys=[access.agent.key for access in accesses],
        user_id=fresh.user.id,
    )
    for access in accesses:
        if access.historical_read_only:
            return False
        key = access.agent.key
        current = records.get(key)
        if current is None:
            if (
                access.registration_state != "legacy_preview"
                or key in await repo.list_registered_keys([key])
                or fresh.user.id != await repo.get_first_admin_id()
            ):
                return False
        elif current.status in {"disabled", "deleted"} or current.role != access.role:
            return False
    return True


class _AccessWatch:
    """One database recheck per device and authorization scope across tabs."""

    def __init__(self, authenticated, accesses, plugin):
        self.allowed = asyncio.Event()
        self.listeners = set()
        self.revoked = False
        self.subscriptions = ExitStack()
        for key in {access.agent.key for access in accesses} or {None}:
            self.subscriptions.enter_context(
                listen(
                    authenticated.user.id,
                    authenticated.session.id,
                    key,
                    self.revoke,
                    plugin_id=plugin[0] if plugin else None,
                )
            )
        self.task = asyncio.create_task(self.monitor(authenticated, accesses, plugin))

    def revoke(self):
        self.revoked = True
        for close in tuple(self.listeners):
            close()

    async def monitor(self, authenticated, accesses, plugin):
        while True:
            self.allowed.clear()
            try:
                with anyio.fail_after(CHECK_TIMEOUT_SECONDS):
                    valid = await _still_authorized(authenticated, accesses, plugin)
            except Exception as exc:
                logger.warning("Stream access check failed (%s)", type(exc).__name__)
                valid = False
            if not valid:
                self.revoke()
                return
            self.allowed.set()
            await anyio.sleep(RECHECK_SECONDS)


class StreamAccessMiddleware:
    """Select streams by response type, including route aliases and replay."""

    def __init__(self, app):
        self.app = app
        self.watches = {}

    async def __call__(self, scope, receive, send):
        state = scope.get("state", {})
        authenticated = state.get("authenticated_session")
        if scope["type"] != "http" or authenticated is None:
            return await self.app(scope, receive, send)

        closed = finished = False
        watch = key = None
        with anyio.CancelScope() as lifetime:

            def close():
                nonlocal closed
                closed = True
                lifetime.cancel()

            async def guarded_send(message):
                nonlocal finished, watch, key
                if message["type"] == "http.response.start":
                    mime = Headers(raw=message.get("headers", [])).get("content-type", "")
                    if mime.partition(";")[0].strip().lower() == "text/event-stream":
                        accesses = tuple(
                            access
                            for name in ("agent_access", "delegation_source_access")
                            if (access := state.get(name)) is not None
                        )
                        plugin = state.get("authorized_plugin")
                        key = (
                            asyncio.get_running_loop(),
                            authenticated.session.id,
                            authenticated.user.platform_role,
                            accesses,
                            plugin[0] if plugin else None,
                        )
                        watch = self.watches.get(key)
                        if watch is None or watch.revoked:
                            watch = self.watches[key] = _AccessWatch(
                                authenticated, accesses, plugin
                            )
                        watch.listeners.add(close)
                elif watch is not None and message["type"] == "http.response.body":
                    await watch.allowed.wait()
                    if watch.revoked:
                        return
                    finished = not message.get("more_body", False)
                await send(message)

            try:
                await self.app(scope, receive, guarded_send)
            finally:
                if watch is not None:
                    watch.listeners.discard(close)
                    if not watch.listeners:
                        if self.watches.get(key) is watch:
                            del self.watches[key]
                        watch.subscriptions.close()
                        watch.task.cancel()
                        with anyio.CancelScope(shield=True):
                            await asyncio.gather(watch.task, return_exceptions=True)
        if closed and not finished:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
