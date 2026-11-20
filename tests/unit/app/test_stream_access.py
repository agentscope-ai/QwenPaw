"""The stream boundary fails closed without delaying ordinary HTTP responses."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.access.stream_revocation import _listeners
from qwenpaw.app import stream_access


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "timeout"])
async def test_database_check_failure_closes_idle_and_ready_streams(monkeypatch, failure):
    async def unavailable(*_):
        if failure == "exception":
            raise ConnectionError()
        await asyncio.Event().wait()

    monkeypatch.setattr(stream_access, "_still_authorized", unavailable)
    monkeypatch.setattr(stream_access, "CHECK_TIMEOUT_SECONDS", 0.03)
    authenticated = SimpleNamespace(
        session=SimpleNamespace(id=uuid4()),
        user=SimpleNamespace(id=uuid4(), platform_role="member"),
    )
    scope = {"type": "http", "state": {"authenticated_session": authenticated}}
    entered = asyncio.Event()
    finished = asyncio.Event()

    async def route(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        try:
            entered.set()
            await send(
                {"type": "http.response.body", "body": b"data: private\n\n", "more_body": True}
            )
            await asyncio.Event().wait()
        finally:
            finished.set()

    guard = stream_access.StreamAccessMiddleware(route)
    sent = AsyncMock()
    await asyncio.wait_for(guard(scope, AsyncMock(), sent), 1)
    assert entered.is_set() and finished.is_set()
    assert [args.args[0].get("body") for args in sent.await_args_list] == [None, b""]
    assert not guard.watches
    assert not any(listener.session_id == authenticated.session.id for listener in _listeners)


@pytest.mark.asyncio
async def test_many_chunks_and_two_tabs_share_a_device_check(monkeypatch):
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(stream_access, "_still_authorized", check)
    authenticated = SimpleNamespace(
        session=SimpleNamespace(id=uuid4()),
        user=SimpleNamespace(id=uuid4(), platform_role="member"),
    )
    arrived = 0
    both_open = asyncio.Event()

    async def route(_scope, _receive, send):
        nonlocal arrived
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        arrived += 1
        if arrived == 2:
            both_open.set()
        await both_open.wait()
        for _ in range(100):
            await send({"type": "http.response.body", "body": b"data: test\n\n", "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    guard = stream_access.StreamAccessMiddleware(route)
    scope = {"type": "http", "state": {"authenticated_session": authenticated}}
    out = [AsyncMock(), AsyncMock()]
    await asyncio.wait_for(asyncio.gather(*(guard(scope, AsyncMock(), sink) for sink in out)), 2)
    assert all(sink.await_count == 102 for sink in out)
    check.assert_awaited_once()
    assert not guard.watches
