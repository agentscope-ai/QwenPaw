# -*- coding: utf-8 -*-
"""Unit tests for NocoBaseEngine (mirror-free)."""
from __future__ import annotations

import httpx
import pytest

from nocobase_auth.config import NocoBaseAuthConfig
from nocobase_auth.engine import NocoBaseEngine, get_engine, set_engine


def _cfg(**kw):
    base = dict(enabled=True, base_url="http://nb.local", api_token="admin")
    base.update(kw)
    return NocoBaseAuthConfig(**base)


@pytest.fixture(autouse=True)
def _reset_engine():
    yield
    set_engine(None)


async def test_global_accessor_roundtrip():
    engine = NocoBaseEngine(config=_cfg())
    assert get_engine() is engine
    set_engine(None)
    assert get_engine() is None


async def test_list_users_live_passthrough():
    def handler(request):
        if request.url.path == "/api/users:list":
            return httpx.Response(
                200,
                json={"data": [{"id": 1, "email": "a@x.io", "roles": []}]},
            )
        return httpx.Response(404)

    engine = NocoBaseEngine(
        config=_cfg(),
        transport=httpx.MockTransport(handler),
    )
    users = await engine.list_users()
    assert users[0]["sender_id"] == "a@x.io"


async def test_list_users_raises_when_unconfigured():
    engine = NocoBaseEngine(config=_cfg(api_token=""))
    with pytest.raises(RuntimeError):
        await engine.list_users()


async def test_update_config_closes_old_client(tmp_path, monkeypatch):
    from nocobase_auth import config as nb_config_module

    # update_config() calls config.save() with no explicit path; keep it off
    # the real working directory.
    monkeypatch.setattr(nb_config_module, "WORKING_DIR", tmp_path)

    def handler(_request):
        return httpx.Response(200, json={"data": []})

    engine = NocoBaseEngine(
        config=_cfg(),
        transport=httpx.MockTransport(handler),
    )
    # force creation of the admin client
    await engine.list_users()
    old = engine._client  # pylint: disable=protected-access
    assert old is not None
    old_httpx_client = old._client  # pylint: disable=protected-access
    assert old_httpx_client is not None

    await engine.update_config(_cfg(base_url="http://other"))

    assert engine._client is None  # pylint: disable=protected-access
    assert old_httpx_client.is_closed


async def test_verify_user_token_uses_user_token_when_configured():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={"data": {"email": "u@x.io", "roles": []}},
        )

    engine = NocoBaseEngine(
        config=_cfg(),
        transport=httpx.MockTransport(handler),
    )
    user = await engine.verify_user_token("user-jwt")
    assert user["email"] == "u@x.io"
    assert seen["auth"] == "Bearer user-jwt"  # user token, not admin
    assert seen["path"] == "/api/auth:check"
