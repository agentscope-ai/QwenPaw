"""私人响应不得被浏览器或代理当成其他账户的可复用缓存。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import FileResponse, Response

from qwenpaw.app import auth


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["file", "metadata", "auth"])
async def test_multi_user_private_responses_disable_storage(
    tmp_path, monkeypatch, kind,
):
    source = tmp_path / "private.md"
    source.write_text("owned content", encoding="utf-8")
    app = FastAPI()
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: True)
    authenticated = SimpleNamespace(
        user=SimpleNamespace(username="synthetic"),
    )
    sessions = SimpleNamespace(
        authenticate_access=AsyncMock(return_value=authenticated),
    )
    monkeypatch.setattr(
        auth, "get_identity_runtime",
        lambda: SimpleNamespace(sessions=sessions),
    )
    monkeypatch.setattr(
        auth, "actor_from_request",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    path = "/api/auth/status" if kind == "auth" else "/api/private-cache-check"

    @app.get(path)
    async def content():
        if kind == "file":
            return FileResponse(source, headers={"Vary": "Accept-Encoding"})
        return {"content": "owned content"}

    app.add_middleware(auth.AuthMiddleware)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.get(
            path, headers={"Authorization": "Bearer synthetic-token"},
        )
    assert response.status_code == 200
    assert "no-store" in response.headers.get("cache-control", "")
    vary = {
        value.strip().lower()
        for value in response.headers.get("vary", "").split(",")
    }
    assert {"authorization", "cookie"} <= vary
    if kind == "file":
        assert "accept-encoding" in vary


@pytest.mark.asyncio
@pytest.mark.parametrize("multi_user", [True, False])
async def test_public_assets_preserve_existing_cache_policy(
    monkeypatch, multi_user,
):
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: multi_user)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: False)
    app = FastAPI()

    @app.get("/assets/cache-check.js")
    async def asset():
        return Response(
            "public asset",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    app.add_middleware(auth.AuthMiddleware)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.get("/assets/cache-check.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=3600"
