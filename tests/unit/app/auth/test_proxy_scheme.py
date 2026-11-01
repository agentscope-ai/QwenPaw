# -*- coding: utf-8 -*-
"""Trusted proxy schemes preserve HTTPS URLs and the real TCP peer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from qwenpaw.app import auth
from qwenpaw.app._app import app as production_app
from qwenpaw.app.routers import mcp_oauth, provider_oauth, terminal


@pytest.fixture
def proxy_config(monkeypatch):
    """Configure middleware trust without constructing API routes."""
    networks = auth._parse_networks(["127.0.0.1/32"])
    config = SimpleNamespace(
        security=SimpleNamespace(allow_no_auth_hosts=[]),
    )
    monkeypatch.setattr(auth, "_get_config_cached", lambda: (config, networks))
    return SimpleNamespace(networks=networks, config=config)


@pytest.fixture
def proxy_app(monkeypatch, proxy_config):
    """Use production middleware registration without agent startup."""
    monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        auth,
        "verify_token",
        lambda token: "alice" if token == "valid" else None,
    )
    monkeypatch.setattr(terminal, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(terminal, "terminal_unavailable_reason", lambda: None)
    monkeypatch.setattr(terminal, "CORS_ORIGINS", "")
    monkeypatch.setattr(
        terminal,
        "get_agent_for_request",
        AsyncMock(return_value=SimpleNamespace(agent_id="agent-a")),
    )
    app = FastAPI(middleware=production_app.user_middleware)
    app.include_router(terminal.router, prefix="/api")
    app.include_router(mcp_oauth.router, prefix="/api")
    manager = MagicMock()
    manager.list.return_value = []
    app.state.terminal_manager = manager

    @app.get("/api/proxy-probe")
    async def probe(request: Request):
        return {
            "scheme": request.url.scheme,
            "peer": request.client.host,
            "resolved_ip": auth.resolve_client_ip(request),
            "trusted_proxy": auth.is_trusted_proxy(request),
            "user": request.state.user,
            "provider": provider_oauth._build_callback_url(
                request,
                "openrouter",
            ),
            "mcp": mcp_oauth._redirect_uri(request),
        }

    return SimpleNamespace(
        app=app,
        manager=manager,
        networks=proxy_config.networks,
        config=proxy_config.config,
    )


def _client(fixture, peer="127.0.0.1"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app, client=(peer, 54321)),
        base_url="http://qwenpaw.example.test",
        headers={"Authorization": "Bearer valid"},
    )


async def test_trusted_https_terminal_same_origin(proxy_app):
    async with _client(proxy_app) as client:
        response = await client.get(
            f"/api/terminals/{uuid4()}",
            headers={
                "Origin": "https://qwenpaw.example.test",
                "X-Forwarded-Proto": "https",
            },
        )
    assert response.status_code == 200
    assert response.json() == []
    assert proxy_app.manager.list.call_args.args[0][:2] == ("alice", "agent-a")


async def test_trusted_https_oauth_callback(proxy_app):
    async with _client(proxy_app) as client:
        response = await client.get(
            "/api/proxy-probe",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "127.0.0.1, 203.0.113.7",
                "X-Forwarded-Host": "attacker.test",
                "Forwarded": "proto=http;host=attacker.test",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == (
        "https://qwenpaw.example.test/api/providers/openrouter/oauth/callback"
    )
    assert payload["mcp"] == (
        "https://qwenpaw.example.test/api/mcp/oauth/callback"
    )
    assert payload["scheme"] == "https"
    assert payload["peer"] == "127.0.0.1"
    assert payload["resolved_ip"] == "203.0.113.7"
    assert payload["trusted_proxy"] is True
    assert payload["user"] == "alice"


def test_production_scheme_middleware_precedes_auth():
    classes = [item.cls for item in production_app.user_middleware]
    assert classes.index(auth.TrustedProxySchemeMiddleware) < classes.index(
        auth.AuthMiddleware,
    )


async def test_trusted_https_still_rejects_cross_site_terminal(proxy_app):
    async with _client(proxy_app) as client:
        response = await client.get(
            f"/api/terminals/{uuid4()}",
            headers={
                "Origin": "https://attacker.test",
                "X-Forwarded-Proto": "https",
            },
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site terminal request rejected"
    proxy_app.manager.list.assert_not_called()


@pytest.mark.parametrize(
    "peer,empty_trust",
    [("198.51.100.2", False), ("127.0.0.1", True)],
)
async def test_untrusted_spoofed_scheme_and_ip_are_ignored(
    proxy_app,
    peer,
    empty_trust,
):
    if empty_trust:
        proxy_app.networks.clear()
    async with _client(proxy_app, peer) as client:
        response = await client.get(
            "/api/proxy-probe",
            headers=[
                ("X-Forwarded-Proto", "https"),
                ("X-Forwarded-Proto", "invalid"),
                ("X-Forwarded-For", "127.0.0.1"),
            ],
        )
        denied = await client.get(
            "/api/proxy-probe",
            headers={"Authorization": "", "X-Forwarded-For": "127.0.0.1"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scheme"] == "http"
    assert payload["peer"] == payload["resolved_ip"] == peer
    assert payload["trusted_proxy"] is False
    assert denied.status_code == 401


async def test_direct_http_terminal_and_oauth_unchanged(proxy_app):
    async with _client(proxy_app) as client:
        terminal_response = await client.get(
            f"/api/terminals/{uuid4()}",
            headers={"Origin": "http://qwenpaw.example.test"},
        )
        response = await client.get("/api/proxy-probe")
    assert terminal_response.status_code == 200
    payload = response.json()
    assert payload["scheme"] == "http"
    assert payload["provider"] == (
        "http://qwenpaw.example.test/api/providers/openrouter/oauth/callback"
    )
    assert (
        payload["mcp"] == "http://qwenpaw.example.test/api/mcp/oauth/callback"
    )


@pytest.mark.parametrize(
    "peer,forwarded_ip",
    [("127.0.0.1", "203.0.113.7"), ("10.0.0.1", "127.0.0.1")],
)
async def test_scheme_restoration_preserves_real_auth_ip_gate(
    proxy_app,
    peer,
    forwarded_ip,
):
    proxy_app.config.security.allow_no_auth_hosts = ["127.0.0.1", "::1"]
    proxy_app.networks[:] = auth._parse_networks([peer])
    headers = {"X-Forwarded-Proto": "https", "X-Forwarded-For": forwarded_ip}
    async with _client(proxy_app, peer) as client:
        denied = await client.get(
            "/api/proxy-probe",
            headers={**headers, "Authorization": ""},
        )
        allowed = await client.get("/api/proxy-probe", headers=headers)
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["scheme"] == "https"
    assert allowed.json()["peer"] == peer
    assert allowed.json()["resolved_ip"] == forwarded_ip


def _scope(kind="http", values=(), peer="127.0.0.1"):
    return {
        "type": kind,
        "scheme": "ws" if kind == "websocket" else "http",
        "method": "POST",
        "path": "/api/probe",
        "root_path": "",
        "query_string": b"a=b",
        "headers": [(b"host", b"qwenpaw.example.test")]
        + [(b"x-forwarded-proto", value) for value in values],
        "client": (peer, 54321),
        "server": ("127.0.0.1", 8088),
        "state": {},
    }


async def _invoke(scope):
    downstream = AsyncMock()
    receive, send = AsyncMock(), AsyncMock()
    await auth.TrustedProxySchemeMiddleware(downstream)(scope, receive, send)
    receive.assert_not_awaited()
    return downstream, receive, send


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("http", b"https", "https"),
        ("http", b" \tHTTPS\t ", "https"),
        ("http", b"http", "http"),
        ("websocket", b"https", "wss"),
        ("websocket", b"http", "ws"),
        ("websocket", b"wss", "wss"),
        ("websocket", b"ws", "ws"),
    ],
)
async def test_scheme_only_changes_in_copied_scope(
    proxy_config,
    kind,
    value,
    expected,
):
    scope = _scope(kind, [value])
    original = scope.copy()
    downstream, receive, send = await _invoke(scope)
    changed, passed_receive, passed_send = downstream.call_args.args
    assert changed["scheme"] == expected
    assert {key: val for key, val in changed.items() if key != "scheme"} == {
        key: val for key, val in original.items() if key != "scheme"
    }
    assert changed["client"] is scope["client"]
    assert changed["headers"] is scope["headers"]
    assert changed["state"] is scope["state"]
    assert scope == original
    assert passed_receive is receive and passed_send is send
    send.assert_not_awaited()


@pytest.mark.parametrize(
    "values",
    [
        [b""],
        [b" "],
        [b"https", b"https"],
        [b"http", b"https"],
        [b"https,http"],
        [b"https, https"],
        [b"ftp"],
        [b"https://example.test"],
        [b"https\r\n"],
        [b"\nhttps"],
        [b"https\x00"],
        [b"https\x7f"],
        [b"https\xff"],
    ],
)
async def test_trusted_malformed_proto_rejected(proxy_config, values):
    downstream, _, send = await _invoke(_scope(values=values))
    downstream.assert_not_awaited()
    first = send.call_args_list[0].args[0]
    assert first["type"] == "http.response.start"
    assert first["status"] == 400
    assert send.call_args_list[-1].args[0]["type"] == "http.response.body"


@pytest.mark.parametrize("values", [[b"https", b"https"], [b"ftp"]])
async def test_websocket_malformed_proto_closes_connection(
    proxy_config,
    values,
):
    downstream, _, send = await _invoke(_scope("websocket", values))
    downstream.assert_not_awaited()
    assert send.call_args_list[0].args[0] == {
        "type": "websocket.close",
        "code": 1008,
    }


@pytest.mark.parametrize("value", [b"ws", b"wss"])
async def test_http_rejects_websocket_only_schemes(proxy_config, value):
    downstream, _, send = await _invoke(_scope(values=[value]))
    downstream.assert_not_awaited()
    assert send.call_args_list[0].args[0]["status"] == 400


@pytest.mark.parametrize("kind", ["http", "websocket", "lifespan"])
async def test_no_forwarded_proto_passes_scope_untouched(proxy_config, kind):
    scope = _scope(kind)
    downstream, receive, send = await _invoke(scope)
    downstream.assert_awaited_once_with(scope, receive, send)
    assert downstream.call_args.args[0] is scope
    send.assert_not_awaited()


async def test_missing_peer_does_not_trust_forwarded_proto(proxy_config):
    scope = _scope(values=[b"https"])
    scope["client"] = None
    downstream, _, send = await _invoke(scope)
    assert downstream.call_args.args[0]["scheme"] == "http"
    send.assert_not_awaited()


@pytest.mark.parametrize("kind", ["http", "websocket", "lifespan"])
async def test_untrusted_or_non_request_invalid_headers_pass_through(
    proxy_config,
    kind,
):
    scope = _scope(kind, [b"https\r\n", b"invalid"], peer="198.51.100.2")
    downstream, receive, send = await _invoke(scope)
    downstream.assert_awaited_once_with(scope, receive, send)
    assert downstream.call_args.args[0] is scope
    send.assert_not_awaited()
