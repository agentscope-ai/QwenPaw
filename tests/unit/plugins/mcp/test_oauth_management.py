# -*- coding: utf-8 -*-
# Test-only service/auth observations; plugin fixtures import public SDK only.
# pylint: disable=protected-access
"""Real PawApp routes with synthetic, declared source credential aliases."""

import asyncio
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from qwenpaw.plugins.testing import PluginTestHost

from .fixtures import PLUGIN, Peer, card, mock_http, seed_card, seed_record

PREFIX = "/api/qwenpaw-mcp"
START = {
    "url": "https://peer.invalid/mcp",
    "client_id": "client",
    "scope": "read",
    "auth_endpoint": "https://auth.invalid/authorize",
    "token_endpoint": "https://auth.invalid/token",
    "redirect_uri": "http://127.0.0.1:8088/api/mcp/oauth/callback",
}


async def setup_source(root, workspace="test", **overrides):
    source = card(
        transport="sse",
        enabled=False,
        credentials={
            "oauth": {
                "kind": "oauth2_auth_code",
                "ref": "synthetic-oauth",
            },
        },
        **overrides,
    )
    seed_card(root, source, workspace)
    store = await seed_record(
        root,
        workspace=workspace,
        public={"client_id": "client", "scope": "old", "keep": "public"},
        secrets={"keep": "secret"},
    )
    return source, store


async def start(host, *, workspace="test", body=None):
    result = await host.request(
        "POST",
        PREFIX + "/oauth/start/same",
        workspace_id=workspace,
        user_id="alice",
        json=body or START,
    )
    assert result.status == 200, result.text
    return result.json()


async def callback(host, state, *, workspace="test"):
    return await host.request(
        "POST",
        PREFIX + "/oauth/callback",
        workspace_id=workspace,
        user_id="alice",
        json={"state": state, "code": "code"},
    )


# One flow verifies persisted state before and after token revocation.
# pylint: disable-next=too-many-statements
async def test_pkce_callback_status_and_revoke_preserve_declared_config(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    payloads = []

    def token(request):
        assert request.url == "https://auth.invalid/token"
        payloads.append(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-refresh",
                "expires_in": 3600,
                "scope": "read",
            },
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        source, store = await setup_source(root)
        first, second = await start(host), await start(host)
        assert first["session_id"] != second["session_id"]
        query = parse_qs(urlparse(first["auth_url"]).query)
        assert query["state"] == [first["session_id"]]
        assert query["redirect_uri"] == [START["redirect_uri"]]
        assert query["client_id"] == ["client"]
        assert query["scope"] == ["read"]
        assert query["code_challenge_method"] == ["S256"]
        assert "code_verifier" not in query
        result = await callback(host, first["session_id"])
        assert result.status == 200, result.text
        assert result.json()
        assert len(payloads) == 1
        verifier = payloads[0]["code_verifier"][0]
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest(),
            )
            .rstrip(b"=")
            .decode()
        )
        assert query["code_challenge"] == [challenge]
        assert payloads[0]["grant_type"] == ["authorization_code"]
        assert payloads[0]["redirect_uri"] == [START["redirect_uri"]]
        status = await host.request(
            "GET",
            PREFIX + "/oauth/status/same",
            user_id="alice",
        )
        assert status.status == 200, status.text
        assert status.json()["authorized"] is True
        assert status.json()["scope"] == "read"
        assert status.json()["expires_at"] > time.time() + 300
        record = await store.get("synthetic-oauth")
        assert record.public["keep"] == "public"
        assert record.secrets["keep"] == "secret"
        assert record.secrets["refresh_token"] == "synthetic-refresh"
        replay = await callback(host, first["session_id"])
        assert 400 <= replay.status < 500
        assert len(payloads) == 1
        revoked = await host.request(
            "DELETE",
            PREFIX + "/oauth/same",
            user_id="alice",
        )
        assert revoked.status == 200, revoked.text
        assert "message" in revoked.json()
        record = await store.get("synthetic-oauth")
        assert not record.secrets.get("access_token")
        assert not record.secrets.get("refresh_token")
        assert record.secrets["keep"] == "secret"
        assert record.public["keep"] == "public"
        assert (
            await host.request("GET", PREFIX + "/oauth/status/same")
        ).json()["authorized"] is False
        assert not peer.opens
        import yaml

        path = root / "workspaces/test/drivers/mcp/same.yaml"
        assert yaml.safe_load(path.read_text()) == source
        assert all(
            "driver_manager" not in workspace._service_manager.services
            for workspace in host._workspaces.values()
        )


async def test_concurrent_callback_claims_state_before_exchange(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def token(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"access_token": "synthetic"})

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await setup_source(root)
        state = (await start(host))["session_id"]
        pending = asyncio.create_task(callback(host, state))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            replay = await asyncio.wait_for(callback(host, state), 2)
            assert 400 <= replay.status < 500
            assert len(calls) == 1
            release.set()
            result = await asyncio.wait_for(pending, 2)
            assert result.status == 200, result.text
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.wait_for(
                asyncio.gather(pending, return_exceptions=True),
                2,
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign-workspace",
        "workspace-instance",
        "source-revision",
        "expired",
        "reload",
    ],
)
async def test_callback_rejects_stale_or_foreign_binding_before_network(
    tmp_path,
    monkeypatch,
    mutation,
):
    root = tmp_path / "host"
    requests = []

    def forbidden(request):
        requests.append(request)
        return httpx.Response(200, json={"access_token": "must-not-save"})

    mock_http(monkeypatch, forbidden)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        source, store = await setup_source(root)
        await setup_source(root, workspace="other")
        state = (await start(host))["session_id"]
        workspace = "test"
        if mutation == "foreign-workspace":
            workspace = "other"
        elif mutation == "workspace-instance":
            previous = host._workspaces.pop("test")
            replacement = await host._workspace("test")
            assert replacement is not previous
        elif mutation == "source-revision":
            source["config"] = {"display_name": "changed"}
            seed_card(root, source)
        elif mutation == "reload":
            assert (await host.reload("qwenpaw-mcp")).ok
        with monkeypatch.context() as clock:
            if mutation == "expired":
                monotonic = time.monotonic
                clock.setattr(time, "monotonic", lambda: monotonic() + 601)
            result = await callback(host, state, workspace=workspace)
        assert 400 <= result.status < 500, result.text
        assert not requests
        assert not (await store.get("synthetic-oauth")).secrets.get(
            "access_token",
        )


async def test_oauth_requires_declared_alias_and_authenticated_identity(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    requests = []
    mock_http(monkeypatch, requests.append)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        seed_card(root, card(transport="sse", enabled=False))
        response = await host.request(
            "POST",
            PREFIX + "/oauth/start/same",
            json=START,
        )
        assert 400 <= response.status < 500
        await setup_source(root)
        unknown = await callback(host, "unknown-random-state")
        assert 400 <= unknown.status < 500
        assert not requests


async def test_discovery_and_dynamic_registration_through_public_start(
    tmp_path,
    monkeypatch,
):
    import json

    root = tmp_path / "host"
    requests = []

    def endpoint(request):
        requests.append(request)
        url = str(request.url)
        if url == "https://peer.invalid/mcp":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="'
                        'https://peer.invalid/protected"'
                    ),
                },
            )
        if url == "https://peer.invalid/protected":
            return httpx.Response(
                200,
                json={
                    "authorization_servers": ["https://auth.invalid/tenant"],
                },
            )
        if url == (
            "https://auth.invalid/.well-known/"
            "oauth-authorization-server/tenant"
        ):
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": "https://auth.invalid/authorize",
                    "token_endpoint": "https://auth.invalid/token",
                    "registration_endpoint": "https://auth.invalid/register",
                },
            )
        if url == "https://auth.invalid/register":
            assert request.method == "POST"
            data = json.loads(request.content)
            assert data["redirect_uris"] == [START["redirect_uri"]]
            assert data["grant_types"] == [
                "authorization_code",
                "refresh_token",
            ]
            assert data["token_endpoint_auth_method"] == "none"
            return httpx.Response(201, json={"client_id": "dynamic-client"})
        raise AssertionError(
            f"Unexpected offline endpoint {request.method} {url}",
        )

    mock_http(monkeypatch, endpoint)
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await setup_source(root)
        # DCR is used only when neither request nor existing credential has ID.
        from qwenpaw.drivers.credentials.types import CredentialRecord
        from qwenpaw.drivers.credentials.store import AsyncCredentialStore

        store = AsyncCredentialStore(root / "workspaces/test/credentials.yaml")
        await store.put(
            CredentialRecord(ref="synthetic-oauth", kind="oauth2_auth_code"),
        )
        body = {
            "url": START["url"],
            "scope": "read",
            "redirect_uri": START["redirect_uri"],
        }
        response = await start(host, body=body)
        query = parse_qs(urlparse(response["auth_url"]).query)
        assert query["client_id"] == ["dynamic-client"]
        assert len(requests) == 4


async def test_management_requires_authenticated_context_when_auth_enabled(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app import auth
    from qwenpaw.config import load_config, save_config

    root = tmp_path / "host"
    peer = Peer()
    peer.install(monkeypatch)
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    async with PluginTestHost(root) as host:
        await host.load(PLUGIN)
        await setup_source(root)
        config = load_config()
        config.security.allow_no_auth_hosts = []
        save_config(config)
        assert auth.register_user("alice", "synthetic-test-password")
        host._http_app.add_middleware(auth.AuthMiddleware)
        response = await host.request(
            "POST",
            PREFIX + "/oauth/start/same",
            user_id=None,
            json=START,
        )
        assert response.status in (401, 403), response.text
        assert not peer.opens
