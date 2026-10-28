# -*- coding: utf-8 -*-
"""Credential resolution at the actual plugin connection boundary."""

import asyncio
import time
from urllib.parse import parse_qs

import httpx
import pytest

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.testing import PluginTestHost

from .fixtures import PLUGIN, Peer, card, mock_http, seed_record


def credential(kind="oauth2_auth_code", ref="synthetic-oauth"):
    return {"kind": kind, "ref": ref}


async def test_stdio_resolves_readonly_bindings_and_configured_env_only(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.envs import save_envs

    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    monkeypatch.setenv("MCP_HOST_PRIVATE", "must-not-inherit")
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        save_envs({"MCP_CONFIGURED": "persisted", "OVERRIDE": "base"})
        await seed_record(root, kind="static", secrets={"key": "synthetic"})
        source = card(credentials={"only": credential("static")})
        source["endpoint"]["env"] = {
            "OVERRIDE": {"source": "literal", "value": "card"},
            "AUTH": {
                "source": "credential",
                "credential": "only",
                "field": "key",
                "format": "Bearer {value}",
            },
            "ABSENT": {
                "source": "credential",
                "credential": "only",
                "field": "missing",
            },
            "NULL": {"source": "literal", "value": None},
            "FLAT": "plain",
        }
        await host.open_driver(source)
        params = peer.opens[0][1]
        assert params.args == ["--offline"]
        assert params.env == {
            "MCP_CONFIGURED": "persisted",
            "OVERRIDE": "card",
            "AUTH": "Bearer synthetic",
            "NULL": "",
            "FLAT": "plain",
        }
        assert "MCP_HOST_PRIVATE" not in params.env


@pytest.mark.parametrize(
    "binding",
    [
        {"public": {"X-Literal": "fixed"}, "secret_refs": {"X-Secret": "key"}},
        {
            "X-Literal": {"source": "literal", "value": "fixed"},
            "X-Secret": {
                "source": "credential",
                "credential": "first",
                "field": "key",
            },
        },
    ],
)
async def test_sse_bindings_alias_order_and_timeout(
    tmp_path,
    monkeypatch,
    binding,
):
    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await seed_record(
            root,
            kind="static",
            secrets={"key": "first-value", "token": "first-token"},
        )
        await seed_record(
            root,
            kind="static",
            ref="second",
            secrets={"key": "second-value"},
        )
        source = card(
            transport="sse",
            credentials={
                "first": credential("static"),
                "second": credential("static", "second"),
            },
        )
        source["endpoint"].update(headers=binding, http_timeout=1200)
        await host.open_driver(source)
        kwargs = peer.opens[0][1]
        assert kwargs["headers"]["X-Literal"] == "fixed"
        assert kwargs["headers"]["X-Secret"] == "first-value"
        assert kwargs["headers"]["Authorization"] == "Bearer first-token"
        assert kwargs["timeout"] == 1200
        assert kwargs["sse_read_timeout"] >= 1200


async def test_explicit_authorization_wins_over_implicit_oauth(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await seed_record(root, secrets={"access_token": "implicit"})
        source = card(transport="sse", credentials={"oauth": credential()})
        source["endpoint"]["headers"] = {"authorization": "Explicit synthetic"}
        await host.open_driver(source)
        assert peer.opens[0][1]["headers"] == {
            "authorization": "Explicit synthetic",
        }


@pytest.mark.parametrize("expires_at", [0, None, 4102444800])
async def test_valid_and_no_expiry_tokens_do_not_refresh(
    tmp_path,
    monkeypatch,
    expires_at,
):
    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    requests = []

    def forbidden(request):
        requests.append(request)
        raise AssertionError("Valid token must not trigger token exchange")

    mock_http(monkeypatch, forbidden)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        public = {"token_endpoint": "https://auth.invalid/token"}
        if expires_at is not None:
            public["expires_at"] = expires_at
        await seed_record(
            root,
            public=public,
            secrets={"access_token": "valid"},
        )
        await host.open_driver(
            card(transport="sse", credentials={"oauth": credential()}),
        )
        assert peer.opens[0][1]["headers"]["Authorization"] == "Bearer valid"
        assert not requests


@pytest.mark.parametrize("kind", ["oauth2_auth_code", "oauth2_cc"])
async def test_refresh_retry_and_persistent_fields(
    tmp_path,
    monkeypatch,
    kind,
):
    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    payloads = []

    def token(request):
        assert request.url == "https://auth.invalid/token"
        payloads.append(parse_qs(request.content.decode()))
        if len(payloads) < 3:
            return httpx.Response([503, 429][len(payloads) - 1])
        return httpx.Response(
            200,
            json={"access_token": "fresh", "expires_in": 3600},
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        secrets = {
            "access_token": "expired",
            "client_secret": "secret",
            "keep": "unchanged",
        }
        if kind == "oauth2_auth_code":
            secrets["refresh_token"] = "refresh-original"
        store = await seed_record(
            root,
            kind=kind,
            public={
                "token_endpoint": "https://auth.invalid/token",
                "expires_at": time.time() - 1,
                "client_id": "client",
                "scope": "read",
                "issuer": "preserve",
            },
            secrets=secrets,
        )
        refresh_started = time.time()
        await host.open_driver(
            card(transport="sse", credentials={"oauth": credential(kind)}),
        )
        assert len(payloads) == 3
        expected = (
            "refresh_token"
            if kind == "oauth2_auth_code"
            else "client_credentials"
        )
        assert payloads[-1]["grant_type"] == [expected]
        assert peer.opens[0][1]["headers"]["Authorization"] == "Bearer fresh"
        current = await store.get("synthetic-oauth")
        assert current.public["issuer"] == "preserve"
        assert current.secrets["keep"] == "unchanged"
        assert current.secrets["client_secret"] == "secret"
        if kind == "oauth2_auth_code":
            assert refresh_started <= current.meta["updated_at"] <= time.time()
            assert current.meta == {
                "synthetic": True,
                "updated_at": current.meta["updated_at"],
            }
        else:
            assert current.meta == {"synthetic": True}
        if kind == "oauth2_auth_code":
            assert current.secrets["refresh_token"] == "refresh-original"
            assert current.secrets["access_token"] == "fresh"
            assert current.public["expires_at"] > time.time() + 300


async def test_expired_without_refresh_token_fails_before_transport(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await seed_record(
            root,
            public={"expires_at": 1},
            secrets={"access_token": "expired"},
        )
        with pytest.raises(SDKError):
            await host.open_driver(
                card(transport="sse", credentials={"oauth": credential()}),
            )
        assert not peer.opens


async def test_refresh_cas_conflict_never_overwrites_newer_credentials(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.drivers.credentials.types import CredentialRecord

    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def token(_request):
        entered.set()
        await release.wait()
        return httpx.Response(
            200,
            json={"access_token": "stale-network", "expires_in": 3600},
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        store = await seed_record(
            root,
            public={
                "expires_at": 1,
                "token_endpoint": "https://auth.invalid/token",
            },
            secrets={"access_token": "expired", "refresh_token": "old"},
        )
        task = asyncio.create_task(
            host.open_driver(
                card(transport="sse", credentials={"oauth": credential()}),
            ),
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await store.put(
                CredentialRecord(
                    ref="synthetic-oauth",
                    kind="oauth2_auth_code",
                    public={"expires_at": time.time() + 3600, "writer": "new"},
                    secrets={
                        "access_token": "newer",
                        "refresh_token": "new-refresh",
                    },
                ),
            )
            release.set()
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                2,
            )
            current = await store.get("synthetic-oauth")
            assert current.secrets == {
                "access_token": "newer",
                "refresh_token": "new-refresh",
            }
            assert current.public["writer"] == "new"
            assert (
                not peer.opens
                or peer.opens[0][1]["headers"]["Authorization"]
                == "Bearer newer"
            )
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                2,
            )


async def test_aksk_derived_signature_binding_uses_generic_runtime_provider(
    tmp_path,
    monkeypatch,
):
    import base64
    import hashlib
    import hmac

    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await seed_record(
            root,
            kind="ak_sk",
            secrets={
                "access_key": "synthetic-ak",
                "secret_key": "synthetic-sk",
            },
        )
        source = card(
            transport="sse",
            credentials={"signing": credential("ak_sk")},
        )
        source["endpoint"]["headers"] = {
            name: {
                "source": "credential",
                "credential": "signing",
                "field": field,
            }
            for name, field in (
                ("X-AK", "access_key"),
                ("X-Time", "timestamp"),
                ("X-Signature", "signature"),
            )
        }
        await host.open_driver(source)
        headers = peer.opens[0][1]["headers"]
        assert headers["X-AK"] == "synthetic-ak"
        expected = base64.b64encode(
            hmac.new(
                b"synthetic-sk",
                f'synthetic-ak:{headers["X-Time"]}:synthetic-oauth'.encode(),
                hashlib.sha256,
            ).digest(),
        ).decode()
        assert headers["X-Signature"] == expected
        assert "secret_key" not in headers


async def test_http_request_refreshes_authorization_without_reconnecting(
    tmp_path,
    monkeypatch,
):
    import json
    from qwenpaw.drivers.credentials.types import CredentialRecord

    root = tmp_path / "host"
    remote = []
    tokens = []

    def endpoint(request):
        if request.url.host == "auth.invalid":
            tokens.append(request)
            return httpx.Response(
                200,
                json={"access_token": "fresh-on-request", "expires_in": 3600},
            )
        payload = json.loads(request.content)
        remote.append(
            (payload["method"], request.headers.get("Authorization")),
        )
        result = {
            "server/discover": {"supportedVersions": ["2026-07-28"]},
            "tools/list": {"tools": [{"name": "echo", "inputSchema": {}}]},
            "tools/call": {"content": [{"type": "text", "text": "fresh"}]},
        }[payload["method"]]
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": result},
        )

    mock_http(monkeypatch, endpoint)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        store = await seed_record(
            root,
            public={
                "expires_at": time.time() + 3600,
                "token_endpoint": "https://auth.invalid/token",
            },
            secrets={"access_token": "initial", "refresh_token": "refresh"},
        )
        await host.open_driver(
            card(
                transport="streamable_http",
                credentials={"oauth": credential()},
            ),
        )
        await host.list_driver_capabilities("same")
        assert not tokens
        assert all(auth == "Bearer initial" for _, auth in remote)
        await store.put(
            CredentialRecord(
                ref="synthetic-oauth",
                kind="oauth2_auth_code",
                public={
                    "expires_at": 1,
                    "token_endpoint": "https://auth.invalid/token",
                },
                secrets={
                    "access_token": "expired",
                    "refresh_token": "refresh",
                },
            ),
        )
        result = await host.call_driver("same", "echo", {})
        assert result.content[0].text == "fresh"
        assert remote[-1] == ("tools/call", "Bearer fresh-on-request")
        assert len(tokens) == 1
        assert sum(method == "server/discover" for method, _ in remote) == 1
