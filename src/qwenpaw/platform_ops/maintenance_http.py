"""ASGI admission for operations participating in platform snapshots."""

import re
import asyncio

from starlette.responses import JSONResponse


class MaintenanceMiddleware:
    """Hold an operation lease until streaming writes and cleanup finish."""

    def __init__(self, app, *, admission=None):
        self.app = app
        self.admission = admission

    async def __call__(self, scope, receive, send):
        from .maintenance import MaintenanceBusy, operation

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        relative = re.sub(r"^/api(?:/agents/[^/]+)?", "", path)
        exclusive_route = method == "POST" and (
            path == "/api/backups/stream"
            or re.fullmatch(r"/api/backups/[^/]+/restore", path)
        )
        # These subscriptions only read events. Their initialization and DB
        # access acquire their own leases, without holding one for the listener.
        subscription = method == "GET" and (
            relative
            in {
                "/runtime-status/stream",
                "/user-input/stream",
                "/plan/stream",
                "/workspace/watch",
            }
            or re.fullmatch(r"/tool-calls/[^/]+/[^/]+/stream", relative)
        )
        if scope["type"] != "http" or exclusive_route or subscription:
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        async def dispatch():
            async with (self.admission or operation)():
                await self.app(scope, receive, tracked_send)

        task = asyncio.create_task(dispatch())
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    if task.cancelled():
                        raise
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        except MaintenanceBusy:
            if started:
                raise
            response = JSONResponse(
                {"detail": {"code": "platform_maintenance_busy"}},
                status_code=503,
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
