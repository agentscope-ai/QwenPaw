# -*- coding: utf-8 -*-
"""NocoBase password login client behavior."""
from __future__ import annotations

import httpx
import pytest

from nocobase_auth.nocobase_client import NocoBaseClient
from nocobase_auth.config import NocoBaseAuthConfig
from nocobase_auth.engine import NocoBaseEngine


@pytest.mark.p0
async def test_sign_in_posts_basic_auth_and_returns_user_identity():
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["json"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "data": {
                    "token": "nocobase-token",
                    "email": "admin@nocobase.com",
                    "id": 1,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    client = NocoBaseClient(
        "http://nocobase.local",
        api_token="admin-api-token",
        transport=transport,
    )

    try:
        user = await client.sign_in(
            "admin@nocobase.com",
            "admin123",
            authenticator="basic",
        )
    finally:
        await client.close()

    assert seen["url"] == "http://nocobase.local/api/auth:signIn"
    assert seen["headers"]["x-authenticator"] == "basic"
    assert '"account":"admin@nocobase.com"' in seen["json"]
    assert '"password":"admin123"' in seen["json"]
    assert user == {
        "token": "nocobase-token",
        "email": "admin@nocobase.com",
        "id": 1,
    }


@pytest.mark.p0
async def test_sign_in_returns_none_for_invalid_credentials():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid")

    client = NocoBaseClient(
        "http://nocobase.local",
        api_token="admin-api-token",
        transport=httpx.MockTransport(handler),
    )

    try:
        user = await client.sign_in(
            "admin@nocobase.com",
            "wrong",
            authenticator="basic",
        )
    finally:
        await client.close()

    assert user is None


@pytest.mark.p0
async def test_engine_login_only_requires_enabled_base_url(monkeypatch):
    config = NocoBaseAuthConfig(
        enabled=True,
        base_url="http://nocobase.local",
        api_token="",
        user_id_field="email",
    )

    async def fake_sign_in(
        self,  # pylint: disable=unused-argument
        username,
        password,
        *,
        authenticator="basic",  # pylint: disable=unused-argument
    ):
        assert self.base_url == "http://nocobase.local"
        assert self.api_token == ""
        assert username == "admin@nocobase.com"
        assert password == "admin123"
        assert authenticator == "basic"
        return {"email": "admin@nocobase.com"}

    monkeypatch.setattr(NocoBaseClient, "sign_in", fake_sign_in)

    engine = NocoBaseEngine(config=config)
    result = await engine.authenticate_credentials(
        "admin@nocobase.com",
        "admin123",
    )

    # No token in the sign-in payload -> identity with None token
    assert result == ("admin@nocobase.com", None)


@pytest.mark.p0
async def test_engine_login_falls_back_to_username_when_email_missing(
    monkeypatch,
):
    config = NocoBaseAuthConfig(
        enabled=True,
        base_url="http://nocobase.local",
        api_token="",
        user_id_field="email",
    )

    async def fake_sign_in(
        self,  # pylint: disable=unused-argument
        username,
        password,
        *,
        authenticator="basic",  # pylint: disable=unused-argument
    ):
        assert username == "test22"
        assert password == "test22"
        return {
            "user": {
                "id": 3,
                "username": "test22",
                "email": None,
                "phone": None,
                "nickname": None,
            },
            "token": "nocobase-token",
        }

    monkeypatch.setattr(NocoBaseClient, "sign_in", fake_sign_in)

    engine = NocoBaseEngine(config=config)
    result = await engine.authenticate_credentials("test22", "test22")

    # Identity falls back to username; the NocoBase token is passed through
    assert result == ("test22", "nocobase-token")
