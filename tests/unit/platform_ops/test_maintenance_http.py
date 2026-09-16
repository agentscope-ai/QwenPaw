"""Maintenance admission covers response bodies and in-flight writes."""

import asyncio
from contextlib import asynccontextmanager

from qwenpaw.platform_ops.maintenance_http import MaintenanceMiddleware


def test_request_lease_covers_stream_body():
    events = []

    @asynccontextmanager
    async def admission():
        events.append("enter")
        yield
        events.append("exit")

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        events.append("write")
        await send({"type": "http.response.body", "body": b"done"})

    async def send(message):
        events.append(message["type"])

    asyncio.run(
        MaintenanceMiddleware(app, admission=admission)(
            {"type": "http", "path": "/api/workspace/files", "method": "PUT"},
            None,
            send,
        )
    )
    assert events == [
        "enter",
        "http.response.start",
        "write",
        "http.response.body",
        "exit",
    ]


def test_maintenance_routes_do_not_upgrade_request_lease():
    @asynccontextmanager
    async def admission():
        raise AssertionError("maintenance route must acquire exclusive directly")
        yield

    async def app(scope, receive, send):
        return

    async def scenario():
        middleware = MaintenanceMiddleware(app, admission=admission)
        for path in ("/api/backups/stream", "/api/backups/id/restore"):
            await middleware(
                {"type": "http", "path": path, "method": "POST"}, None, None
            )

    asyncio.run(scenario())


def test_cancelled_request_keeps_lease_until_work_finishes():
    active = []
    entered = asyncio.Event()
    release = asyncio.Event()

    @asynccontextmanager
    async def admission():
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    async def app(scope, receive, send):
        entered.set()
        await release.wait()

    async def scenario():
        task = asyncio.create_task(
            MaintenanceMiddleware(app, admission=admission)(
                {"type": "http", "path": "/api/files", "method": "PUT"},
                None,
                None,
            )
        )
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert active
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert not active


def test_busy_admission_returns_retryable_response():
    from qwenpaw.platform_ops.maintenance import MaintenanceBusy

    @asynccontextmanager
    async def admission():
        raise MaintenanceBusy("platform_maintenance_busy")
        yield

    async def app(scope, receive, send):
        raise AssertionError("busy request must not reach application")

    messages = []

    async def send(message):
        messages.append(message)

    asyncio.run(
        MaintenanceMiddleware(app, admission=admission)(
            {"type": "http", "path": "/api/files", "method": "PUT"},
            None,
            send,
        )
    )
    assert messages[0]["status"] == 503
    assert (b"retry-after", b"5") in messages[0]["headers"]
    assert b"platform_maintenance_busy" in messages[1]["body"]
