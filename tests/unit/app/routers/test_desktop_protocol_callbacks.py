# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Dedicated Desktop callbacks must authenticate before changing state."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from qwenpaw.app.auth import AuthMiddleware, RuntimeBoundaryMiddleware
from qwenpaw.app.routers import mcp_oauth, provider_oauth, voice
from qwenpaw.browser.control_link.chrome import ws_handler
from qwenpaw.providers.oauth import OAuthSessionStore, OAuthTokenResult
from qwenpaw.tauri import env as desktop_env


@pytest.fixture(name="provider_client")
def provider_client_fixture(monkeypatch):
    monkeypatch.setenv("QWENPAW_DESKTOP_APP", "1")
    monkeypatch.setenv("QWENPAW_DESKTOP_AUTH", "1")
    monkeypatch.setattr(provider_oauth, "_session_store", OAuthSessionStore())
    monkeypatch.setattr(provider_oauth, "_callback_states", {})
    flow = provider_oauth.OpenRouterOAuthFlow()
    flow.exchange = AsyncMock(
        return_value=OAuthTokenResult(api_key="test-key"),
    )
    monkeypatch.setattr(provider_oauth, "_OAUTH_FLOWS", {"openrouter": flow})
    manager = SimpleNamespace(
        update_provider_async=AsyncMock(return_value=True),
        fetch_provider_models=AsyncMock(),
    )
    app = FastAPI()
    app.state.provider_manager = manager
    app.include_router(provider_oauth.router, prefix="/api")
    return TestClient(app), flow, manager


def _start_provider(client):
    response = client.post("/api/providers/openrouter/oauth/start")
    assert response.status_code == 200
    result = response.json()
    callback = parse_qs(urlsplit(result["authorize_url"]).query)[
        "callback_url"
    ][0]
    return callback, result["state"]


def test_desktop_provider_callback_requires_ticket_and_is_one_use(
    provider_client,
):
    client, flow, manager = provider_client
    callback, state = _start_provider(client)
    assert "/oauth/callback/desktop/" in callback
    assert len(callback.rsplit("/", 1)[1]) >= 40

    old_route = "/api/providers/openrouter/oauth/callback"
    assert (
        client.get(
            old_route,
            params={"code": "code", "state": state},
        ).status_code
        == 400
    )
    wrong = callback.rsplit("/", 1)[0] + "/wrong"
    assert client.get(wrong, params={"code": "code"}).status_code == 400
    assert (
        client.get(
            callback,
            params={"code": "code", "state": "wrong"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            callback.replace("/openrouter/", "/other/"),
            params={"code": "code"},
        ).status_code
        == 400
    )
    flow.exchange.assert_not_awaited()
    manager.update_provider_async.assert_not_awaited()

    response = client.get(callback, params={"code": "code"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert client.get(callback, params={"code": "code"}).status_code == 400
    flow.exchange.assert_awaited_once()
    manager.update_provider_async.assert_awaited_once_with(
        "openrouter",
        {"api_key": "test-key"},
    )
    assert (
        client.get(
            "/api/providers/openrouter/oauth/status",
            params={"state": state},
        ).json()["status"]
        == "completed"
    )


def test_expired_desktop_provider_ticket_cannot_exchange(provider_client):
    client, flow, _ = provider_client
    callback, state = _start_provider(client)
    provider_oauth._session_store.get(state).created_at -= 601
    assert client.get(callback, params={"code": "code"}).status_code == 400
    flow.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_ticket_is_consumed_before_exchange(provider_client):
    client, flow, manager = provider_client
    callback, state = _start_provider(client)
    started, release = asyncio.Event(), asyncio.Event()

    async def exchange(**_kwargs):
        started.set()
        await release.wait()
        return OAuthTokenResult(api_key="test-key")

    flow.exchange.side_effect = exchange
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(client.app),
    ) as http:
        first = asyncio.create_task(
            http.get(callback, params={"code": "code"}),
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        try:
            replay = await asyncio.wait_for(
                http.get(callback, params={"code": "code"}),
                timeout=2,
            )
            assert replay.status_code == 400
        finally:
            release.set()
            response = await first
    assert response.status_code == 200
    flow.exchange.assert_awaited_once()
    manager.update_provider_async.assert_awaited_once()
    assert provider_oauth._session_store.get(state).status == "completed"


def test_failed_provider_exchange_does_not_reenable_ticket(provider_client):
    client, flow, manager = provider_client
    callback, state = _start_provider(client)
    flow.exchange.side_effect = ValueError("exchange failed")
    assert client.get(callback, params={"code": "code"}).status_code == 500
    assert client.get(callback, params={"code": "code"}).status_code == 400
    flow.exchange.assert_awaited_once()
    manager.update_provider_async.assert_not_awaited()
    assert provider_oauth._session_store.get(state).status == "failed"


def test_provider_callback_without_code_consumes_ticket(provider_client):
    client, flow, _ = provider_client
    callback, state = _start_provider(client)
    assert client.get(callback).status_code == 400
    assert client.get(callback, params={"code": "code"}).status_code == 400
    flow.exchange.assert_not_awaited()
    assert provider_oauth._session_store.get(state).status == "failed"


def test_web_provider_callback_keeps_state_less_flow(
    provider_client,
    monkeypatch,
):
    client, flow, _ = provider_client
    monkeypatch.delenv("QWENPAW_DESKTOP_APP")
    callback, _ = _start_provider(client)
    assert (
        callback == "http://testserver/api/providers/openrouter/oauth/callback"
    )
    assert (
        client.get(
            callback,
            params={"code": "code", "state": "wrong"},
        ).status_code
        == 400
    )
    flow.exchange.assert_not_awaited()
    assert client.get(callback, params={"code": "code"}).status_code == 200
    flow.exchange.assert_awaited_once()


def test_provider_ticket_is_bound_to_exact_callback_path(provider_client):
    client, flow, _ = provider_client
    callback, state = _start_provider(client)
    session = provider_oauth._session_store.get(state)
    session.callback_url = callback + "/different-path"
    assert client.get(callback, params={"code": "code"}).status_code == 400
    flow.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_state_is_consumed_before_exchange(monkeypatch):
    session = mcp_oauth.OAuthSession(
        "agent",
        "client",
        "verifier",
        "client-id",
        "https://auth.example",
        "https://auth.example/token",
        "http://testserver/api/mcp/oauth/callback",
        "read",
    )
    monkeypatch.setattr(mcp_oauth, "_state_store", {"state": session})
    started, release = asyncio.Event(), asyncio.Event()

    async def exchange(actual_session, code):
        assert actual_session is session
        assert code == "code"
        started.set()
        await release.wait()
        return {"access_token": "test-token"}

    monkeypatch.setattr(mcp_oauth, "_exchange_code_for_tokens", exchange)
    persist = AsyncMock()
    monkeypatch.setattr(mcp_oauth, "_persist_tokens", persist)
    app = FastAPI()
    app.include_router(mcp_oauth.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://testserver",
    ) as client:
        first = asyncio.create_task(
            client.get("/api/mcp/oauth/callback?code=code&state=state"),
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        # Release even on a regression; duplicate requests must not hang.
        replay = asyncio.create_task(
            client.get("/api/mcp/oauth/callback?code=code&state=state"),
        )
        await asyncio.sleep(0)
        release.set()
        first_response, replay_response = await asyncio.gather(first, replay)
    assert first_response.status_code == 200
    assert replay_response.status_code == 400
    persist.assert_awaited_once()


@pytest.mark.parametrize("state", [None, "wrong", "expired"])
def test_mcp_invalid_state_never_exchanges(monkeypatch, state):
    session = mcp_oauth.OAuthSession(
        "agent",
        "client",
        "verifier",
        "id",
        "auth",
        "token",
        "callback",
        "",
    )
    session.created_at -= 601
    monkeypatch.setattr(mcp_oauth, "_state_store", {"expired": session})
    exchange = AsyncMock()
    monkeypatch.setattr(mcp_oauth, "_exchange_code_for_tokens", exchange)
    app = FastAPI()
    app.include_router(mcp_oauth.router, prefix="/api")
    response = TestClient(app).get(
        "/api/mcp/oauth/callback",
        params={"code": "code", **({"state": state} if state else {})},
    )
    assert response.status_code == 400
    exchange.assert_not_awaited()


@pytest.fixture(name="voice_client")
def voice_client_fixture(monkeypatch):
    monkeypatch.setenv("QWENPAW_DESKTOP_APP", "1")
    monkeypatch.setenv("QWENPAW_DESKTOP_AUTH", "1")
    channel = SimpleNamespace(
        channel="voice",
        config=SimpleNamespace(twilio_auth_token="test-twilio-secret"),
        get_tunnel_url=lambda: "https://voice.example",
        get_tunnel_wss_url=lambda: "wss://voice.example",
        create_ws_token=Mock(return_value="single-use-token"),
        session_mgr=SimpleNamespace(end_session=Mock()),
    )
    app = FastAPI()
    app.state.channel_manager = SimpleNamespace(channels=[channel])
    app.include_router(voice.voice_router)
    return TestClient(app), channel, app


def _twilio_signature(url, params, secret="test-twilio-secret"):
    text = url + "".join(key + params[key] for key in sorted(params))
    return base64.b64encode(
        hmac.new(secret.encode(), text.encode(), hashlib.sha1).digest(),
    ).decode()


@pytest.mark.parametrize("path", ["/voice/incoming", "/voice/status-callback"])
@pytest.mark.parametrize("missing", ["channel", "token", "signature"])
def test_desktop_twilio_callbacks_fail_closed(voice_client, path, missing):
    client, channel, app = voice_client
    if missing == "channel":
        app.state.channel_manager.channels = []
    elif missing == "token":
        channel.config.twilio_auth_token = ""
    response = client.post(
        path,
        data={"CallSid": "call", "CallStatus": "completed"},
    )
    assert response.status_code == 403
    channel.session_mgr.end_session.assert_not_called()
    channel.create_ws_token.assert_not_called()


def test_desktop_twilio_uses_configured_tunnel_not_forwarded_host(
    voice_client,
):
    client, channel, _ = voice_client
    params = {"CallSid": "call", "CallStatus": "completed"}
    path = "/voice/status-callback"
    headers = {
        "X-Forwarded-Host": "untrusted.example",
        "X-Forwarded-Proto": "https",
    }
    headers["X-Twilio-Signature"] = _twilio_signature(
        "https://untrusted.example" + path,
        params,
    )
    assert client.post(path, data=params, headers=headers).status_code == 403
    channel.session_mgr.end_session.assert_not_called()
    headers["X-Twilio-Signature"] = _twilio_signature(
        "https://voice.example" + path,
        params,
    )
    assert client.post(path, data=params, headers=headers).status_code == 204
    channel.session_mgr.end_session.assert_called_once_with("call")


def test_desktop_twilio_missing_tunnel_rejects_valid_signature(voice_client):
    client, channel, _ = voice_client
    channel.get_tunnel_url = lambda: None
    params = {"CallSid": "call", "CallStatus": "completed"}
    signature = _twilio_signature(
        "https://voice.example/voice/status-callback",
        params,
    )
    assert (
        client.post(
            "/voice/status-callback",
            data=params,
            headers={"X-Twilio-Signature": signature},
        ).status_code
        == 403
    )
    channel.session_mgr.end_session.assert_not_called()


def _add_desktop_boundary(app, monkeypatch):
    monkeypatch.setenv("QWENPAW_DESKTOP_APP", "1")
    monkeypatch.setenv("QWENPAW_DESKTOP_AUTH", "1")
    monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(
        desktop_env,
        "get_desktop_session",
        lambda: ("http://testserver", "desktop-token"),
    )
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RuntimeBoundaryMiddleware)


def test_signed_twilio_callback_crosses_desktop_gate(
    voice_client,
    monkeypatch,
):
    client, channel, app = voice_client
    _add_desktop_boundary(app, monkeypatch)
    params = {"CallSid": "call", "CallStatus": "completed"}
    signature = _twilio_signature(
        "https://voice.example/voice/status-callback",
        params,
    )
    response = client.post(
        "/voice/status-callback",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )
    assert response.status_code == 204
    channel.session_mgr.end_session.assert_called_once_with("call")
    assert (
        client.post("/voice/status-callback", data=params).status_code == 403
    )


def test_provider_ticket_crosses_desktop_gate(provider_client, monkeypatch):
    client, flow, _ = provider_client
    # Create the pending flow through its ordinary protected start route first.
    callback, _ = _start_provider(client)
    client.app.middleware_stack = None
    _add_desktop_boundary(client.app, monkeypatch)
    assert (
        client.post("/api/providers/openrouter/oauth/start").status_code == 401
    )
    assert client.get(callback, params={"code": "code"}).status_code == 200
    assert client.get(callback, params={"code": "code"}).status_code == 400
    flow.exchange.assert_awaited_once()


def test_mcp_callback_crosses_desktop_gate_once(monkeypatch):
    session = mcp_oauth.OAuthSession(
        "agent",
        "client",
        "verifier",
        "id",
        "auth",
        "token",
        "callback",
        "",
    )
    monkeypatch.setattr(mcp_oauth, "_state_store", {"state": session})
    exchange = AsyncMock(return_value={"access_token": "test-token"})
    monkeypatch.setattr(mcp_oauth, "_exchange_code_for_tokens", exchange)
    monkeypatch.setattr(mcp_oauth, "_persist_tokens", AsyncMock())
    app = FastAPI()
    app.include_router(mcp_oauth.router, prefix="/api")
    _add_desktop_boundary(app, monkeypatch)
    client = TestClient(app)
    callback = "/api/mcp/oauth/callback?code=code&state=state"
    assert client.get(callback).status_code == 200
    assert client.get(callback).status_code == 400
    assert client.post("/api/mcp/oauth/start/client").status_code == 401
    exchange.assert_awaited_once_with(session, "code")


def test_chrome_bridge_keeps_dedicated_auth_under_desktop_gate(monkeypatch):
    app = FastAPI()
    app.include_router(ws_handler.ws_router, prefix="/api")
    monkeypatch.setattr(ws_handler, "_expected_token", lambda: "nm-token")
    monkeypatch.setattr(ws_handler, "_resolve_bridge", lambda _ws: None)
    _add_desktop_boundary(app, monkeypatch)
    client = TestClient(app)
    for query in ("", "?token=wrong"):
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect("/api/ws/chrome" + query):
                pass
        assert denied.value.status_code == 401
    with client.websocket_connect("/api/ws/chrome?token=nm-token"):
        pass


def test_voice_ws_consumes_token_before_accept_under_desktop_gate(monkeypatch):
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig
    from qwenpaw.app.channels.voice.channel import VoiceChannel
    from qwenpaw.app.channels.voice import conversation_relay

    channel = VoiceChannel(
        process=AsyncMock(),
        display_config=ChannelDisplayConfig(),
    )
    handler = SimpleNamespace(handle=AsyncMock(), call_sid=None)
    monkeypatch.setattr(
        conversation_relay,
        "ConversationRelayHandler",
        Mock(return_value=handler),
    )
    app = FastAPI()
    app.state.channel_manager = SimpleNamespace(channels=[channel])
    app.include_router(voice.voice_router)
    _add_desktop_boundary(app, monkeypatch)
    client = TestClient(app)
    for query in ("", "?token=wrong"):
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/voice/ws" + query):
                pass
        assert denied.value.code == 1008
    token = channel.create_ws_token()
    with client.websocket_connect("/voice/ws?token=" + token):
        pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/voice/ws?token=" + token):
            pass
    handler.handle.assert_awaited_once()
