# -*- coding: utf-8 -*-
"""Conserved legacy OAuth business cases through the real plugin host.

Protocol helper cases moved to plugins/mcp/test_oauth_legacy_network.py.
Legacy URLs render popup HTML while the public PawApp owns PKCE and tokens.
"""
# pylint: disable=protected-access,redefined-outer-name
import asyncio
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.app.routers import mcp_oauth as mo
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.storage import dump_card, load_card
from qwenpaw.plugins.testing import PluginTestHost
from tests.unit.plugins.mcp.fixtures import (
    PLUGIN,
    Peer,
    card,
    mock_http,
    seed_card,
)

MCP_URL = "https://mcp.example.com/coop/mcp"
AS_URL = "https://as.example.com"
START = {
    "url": MCP_URL,
    "client_id": "client-1",
    "scope": "read write",
    "auth_endpoint": f"{AS_URL}/authorize",
    "token_endpoint": f"{AS_URL}/token",
}


@pytest.fixture
async def flow(tmp_path, monkeypatch):
    peer = Peer()
    peer.install(monkeypatch)
    state = SimpleNamespace(
        calls=[],
        response={
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_in": 120,
            "scope": "granted",
        },
        token_status=200,
        token_error=None,
        registration_status=201,
        registration={"client_id": "dynamic-client"},
    )

    def network(request):
        state.calls.append(request)
        if request.url.path == "/token":
            if state.token_error:
                raise state.token_error
            return httpx.Response(state.token_status, json=state.response)
        if request.url.path == "/reg":
            return httpx.Response(
                state.registration_status,
                json=state.registration,
            )
        if (
            request.url.path
            == "/.well-known/oauth-protected-resource/coop/mcp"
        ):
            return httpx.Response(
                200,
                json={"authorization_servers": [AS_URL]},
            )
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": f"{AS_URL}/authorize",
                    "token_endpoint": f"{AS_URL}/token",
                    "registration_endpoint": f"{AS_URL}/reg",
                },
            )
        return httpx.Response(404)

    mock_http(monkeypatch, network)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(PLUGIN)
        host._http_app.state.plugin_loader = host._loader
        host._http_app.include_router(mo.router, prefix="/api")
        workspace = await host._workspace("test")
        path = seed_card(
            host.root,
            card(
                "k1",
                "sse",
                enabled=False,
                endpoint={"transport": "sse", "url": MCP_URL},
            ),
        )
        store = AsyncCredentialStore(
            workspace.workspace_dir / "credentials.yaml",
        )
        state.host, state.workspace, state.path, state.store = (
            host,
            workspace,
            path,
            store,
        )
        yield state
        assert (
            not peer.opens
        ), "OAuth/config operations established a protocol connection"


async def request(flow, method, path, **kwargs):
    return await flow.host.request(
        method,
        path,
        headers={"X-Agent-Id": "test", **kwargs.pop("headers", {})},
        user_id="alice",
        **kwargs,
    )


async def start(flow, body=None, **kwargs):
    response = await request(
        flow,
        "POST",
        "/api/mcp/oauth/start/k1",
        json=START if body is None else {"url": MCP_URL, **body},
        **kwargs,
    )
    assert response.status == 200, response.text
    return response.json()


async def callback(flow, state, **params):
    return await request(
        flow,
        "GET",
        "/api/mcp/oauth/callback?"
        + urlencode({"state": state, "code": "code-1", **params}),
    )


async def authorize(flow, body=None):
    started = await start(flow, body)
    response = await callback(flow, started["session_id"])
    assert response.status == 200, response.text
    assert "Authorization successful" in response.text
    assert "mcp-oauth" in response.text
    return await flow.store.get("mcp/k1/oauth")


async def seed_credential(flow, *, public=None, secrets=None, meta=None):
    await flow.store.put(
        CredentialRecord(
            ref="mcp/k1/oauth",
            kind="oauth2_auth_code",
            public=public or {},
            secrets=secrets or {},
            meta=meta or {},
        ),
    )


class TestLoadHelpers:
    async def test_workspace_credential_store_is_real_store(self, flow):
        store = DriverConfigService(flow.workspace).credential_store
        assert isinstance(store, AsyncCredentialStore)
        assert store is DriverConfigService(flow.workspace).credential_store

    def test_mcp_card_path_points_at_protocol_scoped_yaml(self, tmp_path):
        workspace = SimpleNamespace(workspace_dir=tmp_path)
        assert (
            DriverConfigService(workspace).card_path("k1", protocol="mcp")
            == tmp_path / "drivers/mcp/k1.yaml"
        )

    async def test_load_card_returns_saved_card(self, flow):
        saved = await DriverConfigService(flow.workspace).load_card(
            "k1",
            protocol="mcp",
        )
        assert saved.endpoint["url"] == MCP_URL

    async def test_missing_card_raises_404_with_client_key(self, flow):
        response = await request(flow, "GET", "/api/mcp/oauth/status/ghost")
        assert response.status == 404
        assert "ghost" in response.text

    async def test_optional_credential_maps_not_found_to_none(self, flow):
        assert (
            await DriverConfigService(flow.workspace).load_optional_credential(
                "mcp/k1/oauth",
            )
            is None
        )

    async def test_optional_credential_returns_record(self, flow):
        await seed_credential(flow, public={"client_id": "cid"})
        record = await DriverConfigService(
            flow.workspace,
        ).load_optional_credential("mcp/k1/oauth")
        assert record.public["client_id"] == "cid"

    async def test_optional_oauth_credential_uses_oauth_ref(self, flow):
        await seed_credential(flow, secrets={"access_token": "AT"})
        record = await DriverConfigService(
            flow.workspace,
        ).load_optional_credential("mcp/k1/oauth")
        assert record.secrets["access_token"] == "AT"

    async def test_reload_driver_best_effort_is_silent_without_manager(
        self,
        tmp_path,
    ):
        await DriverConfigService(
            SimpleNamespace(workspace_dir=tmp_path),
        ).reload_driver_best_effort("k1")


class TestPersistTokens:
    async def test_missing_access_token_raises(self, flow):
        flow.response = {"refresh_token": "RT"}
        begun = await start(flow)
        result = await callback(flow, begun["session_id"])
        assert result.status == 400
        assert "access_token" in result.text
        assert "Authorization successful" not in result.text

    async def test_writes_public_fields_secrets_and_card_binding(self, flow):
        before = time.time()
        record = await authorize(flow)
        assert record.kind == "oauth2_auth_code"
        assert record.meta["updated_at"] >= before
        assert record.secrets == {"access_token": "AT", "refresh_token": "RT"}
        assert record.public["client_id"] == "client-1"
        assert record.public["scope"] == "granted"
        assert record.public["token_endpoint"] == f"{AS_URL}/token"
        assert record.public["auth_endpoint"] == f"{AS_URL}/authorize"
        assert before + 120 <= record.public["expires_at"] <= time.time() + 120
        saved = load_card(flow.path)
        assert saved.credentials["oauth"].ref == "mcp/k1/oauth"
        assert (
            saved.endpoint["headers"]["Authorization"]["field"]
            == "access_token"
        )

    async def test_defaults_expire_in_one_hour_and_keeps_session_scope(
        self,
        flow,
    ):
        flow.response = {"access_token": "AT-1"}
        record = await authorize(flow)
        assert record.public["scope"] == "read write"
        assert record.public["expires_at"] - time.time() > 3500
        assert "refresh_token" not in record.secrets

    async def test_merges_existing_public_and_meta(self, flow):
        await seed_credential(
            flow,
            public={"client_id": "old-cid", "extra": "keep-me"},
            secrets={"access_token": "OLD"},
            meta={"created_at": 1.0},
        )
        flow.response = {"access_token": "NEW"}
        record = await authorize(flow, {**START, "client_id": ""})
        assert record.public["client_id"] == "old-cid"
        assert record.public["extra"] == "keep-me"
        assert record.public["auth_endpoint"] == f"{AS_URL}/authorize"
        assert record.secrets == {"access_token": "NEW"}
        assert record.meta["created_at"] == 1.0

    async def test_missing_card_raises_value_error(self, flow):
        begun = await start(flow)
        flow.path.unlink()
        result = await callback(flow, begun["session_id"])
        assert result.status == 400
        assert "Authorization successful" not in result.text
        assert not [item for item in flow.calls if item.url.path == "/token"]


class TestOauthStartEndpoint:
    async def test_explicit_endpoints_skip_discovery(self, flow):
        begun = await start(flow)
        query = parse_qs(urlparse(begun["auth_url"]).query)
        assert begun["session_id"] == query["state"][0]
        assert query["client_id"] == ["client-1"]
        assert query["scope"] == ["read write"]
        assert query["code_challenge_method"] == ["S256"]
        assert "code_verifier" not in query
        assert query["redirect_uri"] == [
            "http://sdk.test/api/mcp/oauth/callback",
        ]
        assert not flow.calls

    async def test_card_url_wins_over_request_body(self, flow):
        await start(flow, {"url": "https://wrong.invalid", "client_id": "x"})
        assert flow.calls[0].url == MCP_URL
        assert all(item.url.host != "wrong.invalid" for item in flow.calls)

    async def test_missing_url_raises_400(self, flow):
        saved = load_card(flow.path)
        saved.endpoint = {"transport": "stdio", "command": "synthetic"}
        dump_card(saved, flow.path)
        response = await request(
            flow,
            "POST",
            "/api/mcp/oauth/start/k1",
            json={"url": ""},
        )
        assert response.status == 400
        assert (
            response.json()["detail"]
            == "OAuth MCP client must have a remote URL."
        )
        assert not flow.calls

    async def test_unknown_client_raises_404(self, flow):
        response = await request(
            flow,
            "POST",
            "/api/mcp/oauth/start/ghost",
            json={"url": MCP_URL},
        )
        assert response.status == 404
        assert not flow.calls

    async def test_discovery_path_with_dynamic_registration(self, flow):
        begun = await start(flow, {})
        query = parse_qs(urlparse(begun["auth_url"]).query)
        assert query["client_id"] == ["dynamic-client"]
        assert "scope" not in query
        registrations = [
            item for item in flow.calls if item.url.path == "/reg"
        ]
        assert len(registrations) == 1
        payload = json.loads(registrations[0].content)
        assert payload["redirect_uris"] == [
            "http://sdk.test/api/mcp/oauth/callback",
        ]
        assert payload["token_endpoint_auth_method"] == "none"

    async def test_failed_registration_leaves_client_id_empty(self, flow):
        flow.registration_status = 400
        begun = await start(flow, {})
        assert "client_id" not in parse_qs(urlparse(begun["auth_url"]).query)

    async def test_existing_credential_supplies_client_id(self, flow):
        await seed_credential(flow, public={"client_id": "saved-cid"})
        begun = await start(flow, {**START, "client_id": ""})
        assert parse_qs(urlparse(begun["auth_url"]).query)["client_id"] == [
            "saved-cid",
        ]
        assert not flow.calls

    async def test_managed_callback_header_wins(self, flow, monkeypatch):
        monkeypatch.setenv(
            "QWENPAW_RUNTIME_INTERNAL_TOKEN",
            "synthetic-control-token",
        )
        begun = await start(
            flow,
            headers={
                "X-QwenPaw-Hub-OAuth-Callback-Url": (
                    "https://managed.invalid/cb"
                ),
            },
        )
        assert parse_qs(urlparse(begun["auth_url"]).query)["redirect_uri"] == [
            "https://managed.invalid/cb",
        ]


class TestOauthCallbackEndpoint:
    @pytest.mark.parametrize(
        "params, message",
        [
            (
                {
                    "error": "access_denied",
                    "error_description": "user declined",
                },
                "user declined",
            ),
            ({"error": "access_denied"}, "access_denied"),
            ({}, "Missing"),
            ({"state": "unknown", "code": "code"}, "expired"),
        ],
    )
    async def test_callback_error_pages(self, flow, params, message):
        response = await request(
            flow,
            "GET",
            "/api/mcp/oauth/callback?" + urlencode(params),
        )
        assert response.status == 400
        assert message.lower() in response.text.lower()
        assert '"status": "error"' in response.text
        assert "Authorization successful" not in response.text
        assert not flow.calls

    async def test_success_exchanges_persists_and_pops_state(self, flow):
        begun = await start(flow)
        response = await callback(flow, begun["session_id"])
        assert response.status == 200, response.text
        assert "mcp-oauth" in response.text
        assert '"status": "success"' in response.text
        assert '"clientKey": "k1"' in response.text
        assert '"agentId": "test"' in response.text
        assert (await flow.store.get("mcp/k1/oauth")).secrets[
            "access_token"
        ] == "AT"
        replay = await callback(flow, begun["session_id"])
        assert replay.status == 400
        assert (
            len([item for item in flow.calls if item.url.path == "/token"])
            == 1
        )

    @pytest.mark.parametrize(
        "fault",
        ["http-status", "transport", "missing-token"],
    )
    async def test_exchange_failure_renders_error_and_consumes_session(
        self,
        flow,
        fault,
    ):
        if fault == "http-status":
            flow.token_status = 400
        elif fault == "transport":
            flow.token_error = httpx.ConnectError("token network unavailable")
        else:
            flow.response = {}
        begun = await start(flow)
        first = await callback(flow, begun["session_id"])
        assert first.status == 400
        expected = {
            "http-status": "Token exchange failed",
            "transport": "token network unavailable",
            "missing-token": "access_token",
        }[fault]
        assert expected in first.text
        assert "Authorization successful" not in first.text
        replay = await callback(flow, begun["session_id"])
        assert replay.status == 400
        assert (
            len([item for item in flow.calls if item.url.path == "/token"])
            == 1
        )

    async def test_callback_ignores_untrusted_agent_query(self, flow):
        begun = await start(flow)
        response = await callback(
            flow,
            begun["session_id"],
            agent_id="attacker",
            client_key="other",
        )
        assert response.status == 200, response.text
        assert (await flow.store.get("mcp/k1/oauth")).secrets[
            "access_token"
        ] == "AT"

    async def test_source_change_rejects_before_exchange(self, flow):
        begun = await start(flow)
        saved = load_card(flow.path)
        saved.endpoint["url"] = "https://changed.invalid"
        dump_card(saved, flow.path)
        response = await callback(flow, begun["session_id"])
        assert response.status == 400
        assert "Authorization successful" not in response.text
        assert not flow.calls

    async def test_disable_rejects_old_grant_and_reenable_does_not_replay(
        self,
        flow,
    ):
        begun = await start(flow)
        await flow.host.set_enabled("qwenpaw-mcp", False)
        response = await callback(flow, begun["session_id"])
        assert response.status in (400, 503)
        await flow.host.set_enabled("qwenpaw-mcp", True)
        replay = await callback(flow, begun["session_id"])
        assert replay.status == 400
        assert not flow.calls


class TestOauthStatusEndpoint:
    @pytest.mark.parametrize(
        "public, secrets, authorized, expiry",
        [
            ({}, {}, False, 0),
            ({"scope": "read"}, {}, False, 0),
            (
                {"expires_at": 4102444800, "scope": "read"},
                {"access_token": "AT"},
                True,
                4102444800,
            ),
            ({"expires_at": 1}, {"access_token": "AT"}, False, 1),
            ({"expires_at": 0}, {"access_token": "AT"}, True, 0),
        ],
    )
    async def test_status_retains_authorization_scope_and_expiry(
        self,
        flow,
        public,
        secrets,
        authorized,
        expiry,
    ):
        await seed_credential(flow, public=public, secrets=secrets)
        response = await request(flow, "GET", "/api/mcp/oauth/status/k1")
        assert response.status == 200, response.text
        assert response.json() == {
            "authorized": authorized,
            "expires_at": expiry,
            "scope": public.get("scope", "")
            if secrets.get("access_token")
            else "",
        }

    async def test_without_credential_reports_unauthorized(self, flow):
        response = await request(flow, "GET", "/api/mcp/oauth/status/k1")
        assert response.status == 200, response.text
        assert response.json() == {
            "authorized": False,
            "expires_at": 0.0,
            "scope": "",
        }

    async def test_unknown_client_raises_404(self, flow):
        assert (
            await request(flow, "GET", "/api/mcp/oauth/status/ghost")
        ).status == 404


class TestOauthRevokeEndpoint:
    async def test_clears_access_and_refresh_tokens_preserving_declared_alias(
        self,
        flow,
    ):
        await authorize(flow)
        response = await request(flow, "DELETE", "/api/mcp/oauth/k1")
        assert response.status == 200, response.text
        assert response.json() == {"message": "OAuth tokens cleared"}
        record = await flow.store.get("mcp/k1/oauth")
        assert "access_token" not in record.secrets
        assert "refresh_token" not in record.secrets
        status = await request(flow, "GET", "/api/mcp/oauth/status/k1")
        assert status.json()["authorized"] is False
        assert load_card(flow.path).credentials["oauth"].ref == "mcp/k1/oauth"

    async def test_revoking_without_credential_still_succeeds(self, flow):
        response = await request(flow, "DELETE", "/api/mcp/oauth/k1")
        assert response.status == 200, response.text
        assert response.json() == {"message": "OAuth tokens cleared"}

    async def test_unknown_client_raises_404(self, flow):
        assert (
            await request(flow, "DELETE", "/api/mcp/oauth/ghost")
        ).status == 404


class TestRoutingGrantSafety:
    async def test_expired_session_renders_error_page_without_network(
        self,
        flow,
        monkeypatch,
    ):
        from qwenpaw.app.mcp import oauth_bridge

        begun = await start(flow)
        future = time.monotonic() + 601
        monkeypatch.setattr(
            oauth_bridge,
            "time",
            SimpleNamespace(monotonic=lambda: future),
        )
        result = await callback(flow, begun["session_id"])
        assert result.status == 400
        assert "expired" in result.text.lower()
        assert not flow.calls
        assert (
            begun["session_id"]
            not in flow.host._http_app.state.mcp_oauth_grants
        )

    async def test_expired_sessions_are_purged_on_start(
        self,
        flow,
        monkeypatch,
    ):
        from qwenpaw.app.mcp import oauth_bridge

        begun = await start(flow)
        future = time.monotonic() + 601
        monkeypatch.setattr(
            oauth_bridge,
            "time",
            SimpleNamespace(monotonic=lambda: future),
        )
        new = await start(flow)
        assert (
            begun["session_id"]
            not in flow.host._http_app.state.mcp_oauth_grants
        )
        assert new["session_id"] in flow.host._http_app.state.mcp_oauth_grants

    async def test_routing_grant_keeps_only_bounded_trusted_metadata(
        self,
        flow,
    ):
        begun = await start(flow)
        grant = flow.host._http_app.state.mcp_oauth_grants[begun["session_id"]]
        assert set(vars(grant)) == {
            "agent_id",
            "workspace_instance_id",
            "client_key",
            "source_revision",
            "generation",
            "user_id",
            "expires_at",
        }
        assert grant.agent_id == "test"
        assert grant.client_key == "k1"
        assert grant.user_id == "alice"
        assert time.monotonic() < grant.expires_at <= time.monotonic() + 600
        assert all(
            isinstance(value, (str, int, float))
            for value in vars(grant).values()
        )

    async def test_concurrent_callbacks_claim_once_before_token_request(
        self,
        flow,
        monkeypatch,
    ):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def token(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"access_token": "AT"})

        mock_http(monkeypatch, token)
        begun = await start(flow)
        pending = asyncio.create_task(callback(flow, begun["session_id"]))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            replay = await asyncio.wait_for(
                callback(flow, begun["session_id"]),
                2,
            )
            assert replay.status == 400
            assert len(calls) == 1
            assert (
                begun["session_id"]
                not in flow.host._http_app.state.mcp_oauth_grants
            )
            release.set()
            assert (await asyncio.wait_for(pending, 2)).status == 200
        finally:
            release.set()
            await asyncio.wait_for(
                asyncio.gather(pending, return_exceptions=True),
                2,
            )

    async def test_provider_failure_consumes_state_and_never_exchanges(
        self,
        flow,
    ):
        begun = await start(flow)
        response = await callback(
            flow,
            begun["session_id"],
            error="access_denied",
            error_description="declined",
        )
        assert response.status == 400
        assert "declined" in response.text
        assert (await callback(flow, begun["session_id"])).status == 400
        assert not flow.calls

    async def test_blank_header_uses_active_workspace(self, flow):
        from qwenpaw.config.utils import load_config, save_config

        config = load_config()
        config.agents.active_agent = "test"
        save_config(config)
        response = await flow.host.request(
            "POST",
            "/api/mcp/oauth/start/k1",
            user_id="alice",
            json=START,
        )
        assert response.status == 200, response.text
        assert (
            await callback(flow, response.json()["session_id"])
        ).status == 200

    async def test_replaced_workspace_instance_is_rejected(self, flow):
        begun = await start(flow)
        original = flow.host._workspaces.pop("test")
        try:
            await flow.host._workspace("test")
            response = await callback(flow, begun["session_id"])
            assert response.status == 400
            assert not flow.calls
        finally:
            # Restore ownership so PluginTestHost shuts down the original too.
            flow.host._workspaces["original-for-cleanup"] = original


async def test_missing_manager_fails_without_attempting_token_persistence(
    flow,
):
    del flow.host._http_app.state.multi_agent_manager
    response = await request(
        flow,
        "POST",
        "/api/mcp/oauth/start/k1",
        json=START,
    )
    assert response.status == 500
    assert "MultiAgentManager" in response.text
    assert not flow.calls


@pytest.mark.parametrize(
    "failure",
    ["credential write failed", "mcp/k1/oauth synthetic-secret-access-token"],
)
async def test_persist_failure_renders_error_and_preserves_old_credential(
    flow,
    monkeypatch,
    failure,
):
    from unittest.mock import AsyncMock

    await seed_credential(flow, secrets={"access_token": "OLD"})
    begun = await start(flow)
    monkeypatch.setattr(
        AsyncCredentialStore,
        "compare_and_put",
        AsyncMock(side_effect=RuntimeError(failure)),
    )
    response = await callback(flow, begun["session_id"])
    assert response.status == 400
    assert "Could not update credential alias" in response.text
    assert failure not in response.text
    assert "mcp/k1/oauth" not in response.text
    assert "synthetic-secret-access-token" not in response.text
    assert (
        begun["session_id"] not in flow.host._http_app.state.mcp_oauth_grants
    )
    assert "Authorization successful" not in response.text
    assert (await flow.store.get("mcp/k1/oauth")).secrets[
        "access_token"
    ] == "OLD"


def test_credential_not_found_error_carries_ref():
    from qwenpaw.drivers.errors import CredentialNotFoundError

    assert CredentialNotFoundError("mcp/k1/oauth").ref == "mcp/k1/oauth"
