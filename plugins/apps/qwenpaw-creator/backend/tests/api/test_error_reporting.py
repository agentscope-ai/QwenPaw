# -*- coding: utf-8 -*-
"""Creator HTTP errors always include support-ready correlation fields."""

from pathlib import Path
import asyncio

from fastapi import APIRouter, FastAPI, Query
from httpx import ASGITransport, AsyncClient

from api.dependencies import CreatorErrorRoute
from services.runtime_files.errors import LockTimeoutError


def test_validation_lock_and_unexpected_errors_share_diagnostic_contract():
    app = FastAPI()
    router = APIRouter(route_class=CreatorErrorRoute)

    @router.get("/validation")
    async def validation(count: int = Query(...)) -> dict[str, int]:
        return {"count": count}

    @router.get("/lock")
    async def lock_failure() -> None:
        raise LockTimeoutError(
            Path("runtime/locks/session-runtime.lock"),
            10,
            phase="resource",
            waiter={"pid": 11},
            holder={"pid": 22},
        )

    @router.get("/unexpected")
    async def unexpected() -> None:
        raise ValueError("broken invariant")

    app.include_router(router)

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return (
                await client.get("/validation?count=bad"),
                await client.get("/lock"),
                await client.get("/unexpected"),
            )

    validation_response, lock_response, unexpected_response = asyncio.run(
        scenario(),
    )
    validation_body = validation_response.json()
    assert validation_response.status_code == 422
    assert validation_body["details"]["issues"][0]["location"][-1] == "count"

    lock_body = lock_response.json()
    assert lock_response.status_code == 503
    assert lock_body["code"] == "RUNTIME_LOCK_TIMEOUT"
    assert lock_body["details"]["holder"]["pid"] == 22

    unexpected_body = unexpected_response.json()
    assert unexpected_response.status_code == 500
    assert unexpected_body["code"] == "INTERNAL_ERROR"
    assert unexpected_body["details"]["errorType"] == "ValueError"

    for response in (
        validation_response,
        lock_response,
        unexpected_response,
    ):
        body = response.json()
        assert body["errorId"] == response.headers["X-Creator-Error-ID"]
        assert body["traceId"] == response.headers["X-Creator-Trace-ID"]
        assert body["requestId"] == response.headers["X-Request-ID"]
