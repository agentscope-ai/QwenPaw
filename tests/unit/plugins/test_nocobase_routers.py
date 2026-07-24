# -*- coding: utf-8 -*-
"""Unit tests for the NocoBase auth plugin routers (live passthrough)."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nocobase_auth.config import NocoBaseAuthConfig
from nocobase_auth.engine import NocoBaseEngine, set_engine
from nocobase_auth.routers import build_router


@pytest.fixture(autouse=True)
def _reset_engine():
    yield
    set_engine(None)


def _app(engine):
    set_engine(engine)
    app = FastAPI()
    app.include_router(build_router(), prefix="/nocobase-auth")
    return app


async def test_users_live_passthrough():
    def nb(_request):
        return httpx.Response(
            200,
            json={"data": [{"id": 1, "email": "a@x.io", "roles": []}]},
        )

    engine = NocoBaseEngine(
        config=NocoBaseAuthConfig(
            enabled=True, base_url="http://nb.local", api_token="admin"
        ),
        transport=httpx.MockTransport(nb),
    )
    app = _app(engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        resp = await c.get("/nocobase-auth/users")
    assert resp.status_code == 200
    assert resp.json()[0]["sender_id"] == "a@x.io"


async def test_users_errors_not_silent_empty_when_unconfigured():
    engine = NocoBaseEngine(
        config=NocoBaseAuthConfig(enabled=True, base_url="http://nb.local")
    )  # no api_token -> unconfigured
    app = _app(engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        resp = await c.get("/nocobase-auth/users")
    assert resp.status_code == 503  # explicit error, NOT [] with 200


async def test_sync_and_webhook_routes_removed():
    engine = NocoBaseEngine(config=NocoBaseAuthConfig())
    app = _app(engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        assert (await c.post("/nocobase-auth/sync")).status_code == 404
        assert (
            await c.post("/nocobase-auth/webhook", json={})
        ).status_code == 404
