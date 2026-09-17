# -*- coding: utf-8 -*-
"""Desktop protects dynamic routes independently of account authentication."""

import secrets

import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from qwenpaw.app.auth import RuntimeBoundaryMiddleware
from qwenpaw.tauri import env


@pytest.fixture(name="desktop")
def desktop_fixture(monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv(env.DESKTOP_APP_ENV, "1")
    monkeypatch.setenv(env.DESKTOP_AUTH_ENV, "1")
    monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(env, "_desktop_token", token, raising=False)
    monkeypatch.setattr(
        env,
        "_desktop_origin",
        "http://127.0.0.1:8765",
        raising=False,
    )
    app = FastAPI()
    app.add_middleware(RuntimeBoundaryMiddleware)

    @app.api_route("/api/mcp", methods=["GET", "POST"])
    @app.get("/plugin-private/read")
    @app.get("/api/auth/status")
    def protected():
        return {"ok": True}

    @app.websocket("/plugin-private/socket")
    async def protected_socket(socket: WebSocket):
        await socket.accept()
        await socket.send_text("private")
        await socket.close()

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, token


@pytest.mark.parametrize(
    "path",
    [
        "/api/mcp",
        "/api/auth/status",
        "/plugin-private/read",
    ],
)
def test_anonymous_dynamic_routes_are_denied(desktop, path):
    client, _ = desktop
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["code"] == "desktop_session_required"


def test_write_is_denied_and_current_identity_works(desktop):
    client, token = desktop
    assert client.post("/api/mcp").status_code == 401
    assert (
        client.post(
            "/api/mcp",
            headers={"X-Desktop-Session": token},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/mcp",
            headers={"X-Desktop-Session": "wrong"},
        ).status_code
        == 401
    )


def test_token_does_not_authorize_another_host_or_origin(desktop):
    client, token = desktop
    headers = {"X-Desktop-Session": token}
    assert (
        client.get(
            "/api/mcp",
            headers={**headers, "Host": "rebind.invalid:8765"},
        ).status_code
        == 421
    )
    assert (
        client.get(
            "/api/mcp",
            headers={**headers, "Origin": "http://127.0.0.1:8766"},
        ).status_code
        == 403
    )


def test_missing_startup_identity_fails_closed(desktop, monkeypatch):
    client, token = desktop
    monkeypatch.setattr(env, "_desktop_token", "", raising=False)
    assert (
        client.get(
            "/api/mcp",
            headers={"X-Desktop-Session": token},
        ).status_code
        == 401
    )


def test_anonymous_websocket_is_rejected_before_accept(desktop):
    client, _ = desktop
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/plugin-private/socket"):
            pytest.fail("An unauthenticated socket was accepted")
    assert exc.value.code == 4401


def test_standalone_web_behavior_is_unchanged(desktop, monkeypatch):
    client, _ = desktop
    monkeypatch.delenv(env.DESKTOP_APP_ENV)
    monkeypatch.setattr(env, "_desktop_token", "", raising=False)
    assert client.get("/api/mcp").status_code == 200


def test_other_desktop_hosts_do_not_enable_windows_auth(desktop, monkeypatch):
    client, _ = desktop
    monkeypatch.delenv(env.DESKTOP_AUTH_ENV)
    assert client.get("/api/mcp").status_code == 200


def test_launch_credential_is_consumed_before_child_processes(
    desktop,
    monkeypatch,
):
    import os

    _, token = desktop
    monkeypatch.setenv(env.DESKTOP_SESSION_ENV, token)
    env.consume_desktop_session()
    assert env.DESKTOP_SESSION_ENV not in os.environ
    assert env.get_desktop_session() is None
    env.set_desktop_origin(8765)
    assert env.get_desktop_session() == ("http://127.0.0.1:8765", token)
    with pytest.raises(RuntimeError, match="missing or invalid"):
        env.consume_desktop_session()


def test_disabled_host_does_not_initialize_desktop_identity(
    desktop,
    monkeypatch,
):
    _, token = desktop
    monkeypatch.delenv(env.DESKTOP_AUTH_ENV)
    monkeypatch.setenv(env.DESKTOP_SESSION_ENV, token)
    env.consume_desktop_session()
    env.set_desktop_origin(8765)
    assert env.get_desktop_session() is None


@pytest.mark.parametrize("site", ["same-site", "cross-site"])
def test_native_header_cannot_authorize_cross_origin_requests(desktop, site):
    client, token = desktop
    response = client.get(
        "/plugin-private/read",
        headers={"X-Desktop-Session": token, "Sec-Fetch-Site": site},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("origin", [None, "http://127.0.0.1:8765"])
def test_native_and_same_origin_browser_requests_work(desktop, origin):
    client, token = desktop
    headers = {"X-Desktop-Session": token}
    if origin:
        headers.update({"Origin": origin, "Sec-Fetch-Site": "same-origin"})
    assert (
        client.get("/plugin-private/read", headers=headers).status_code == 200
    )
