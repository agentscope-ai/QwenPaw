# -*- coding: utf-8 -*-
"""Avatar routes follow the Console middleware's authentication policy."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app import auth
from qwenpaw.app.routers import avatars


@pytest.fixture(name="avatar_client")
def make_avatar_client(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        auth,
        "verify_token",
        lambda token: "alice" if token == "valid" else None,
    )
    config = SimpleNamespace(
        security=SimpleNamespace(allow_no_auth_hosts=[]),
    )
    monkeypatch.setattr(auth, "_get_config_cached", lambda: (config, []))
    monkeypatch.setattr(avatars, "WORKING_DIR", tmp_path)
    avatars.avatar_store.cache_clear()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(avatars.router, prefix="/api")
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            yield client, config
    finally:
        avatars.avatar_store.cache_clear()


@pytest.mark.parametrize(
    "headers,params,status",
    [
        ({"Authorization": "Bearer valid"}, {}, 200),
        ({}, {"token": "valid"}, 200),
        ({}, {}, 401),
        ({}, {"token": "invalid"}, 401),
        ({"Authorization": "Bearer invalid"}, {"token": "valid"}, 401),
    ],
)
def test_avatar_auth_for_reads_and_writes(
    avatar_client,
    headers,
    params,
    status,
):
    client, _ = avatar_client
    endpoint = "/api/profile/avatars"
    assert (
        client.get(endpoint, headers=headers, params=params).status_code
        == status
    )
    response = client.put(
        f"{endpoint}/selection",
        json={"image_id": None},
        headers=headers,
        params=params,
    )
    assert response.status_code == status
    if status == 200:
        assert response.json() == {"selected": None, "history": []}


@pytest.mark.parametrize("mode", ["disabled", "unregistered", "trusted-host"])
def test_avatar_auth_exemptions(avatar_client, monkeypatch, mode):
    client, config = avatar_client
    if mode == "disabled":
        monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "false")
    elif mode == "unregistered":
        monkeypatch.setattr(auth, "has_registered_users", lambda: False)
    else:
        config.security.allow_no_auth_hosts = ["127.0.0.1"]
    response = client.put(
        "/api/profile/avatars/selection",
        json={"image_id": None},
    )
    assert response.status_code == 200
