# -*- coding: utf-8 -*-
"""Behavioural tests for the MCP OAuth router flows.

Covers the module-level helpers and the four endpoints of
``qwenpaw.app.routers.mcp_oauth`` that previously had no coverage:
metadata discovery (RFC 9728 / RFC 8414), dynamic client registration
(RFC 7591), the authorization-code exchange, token persistence into the
real per-workspace credential store, and the start / callback / status /
revoke endpoints.

Network legs are stubbed with ``httpx.MockTransport`` so every test is
deterministic and never leaves the machine; persistence legs run against
a real temporary workspace so the assertions read back what was actually
written to disk.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.app.routers import mcp_oauth as mo
from qwenpaw.app.routers.mcp_oauth import router as oauth_router
from qwenpaw.drivers.adapters.mcp_console import (
    OAUTH_CREDENTIAL_ALIAS,
    attach_mcp_oauth_credential,
    mcp_oauth_credential_ref,
)
from qwenpaw.drivers.constants import PROTOCOL_MCP
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.errors import CredentialNotFoundError
from qwenpaw.drivers.storage import dump_card, load_card

MCP_URL = "https://mcp.example.com/coop/mcp"
AS_URL = "https://as.example.com"


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class WorkspaceStub:
    """Minimal workspace: a real temp dir and no driver manager.

    ``driver_manager = None`` matters: ``DriverConfigService`` would
    otherwise take the mock's auto-created ``credential_store`` attribute
    and every persistence assertion would be vacuous.
    """

    def __init__(self, root: Path, agent_id: str = "agent-1") -> None:
        self.workspace_dir = root
        self.driver_manager = None
        self.agent_id = agent_id


def _mock_client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., httpx.AsyncClient]:
    """Return an ``httpx.AsyncClient`` stand-in bound to *handler*."""
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    return factory


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Point only the router module at a transport-stubbed AsyncClient.

    The helpers build their own clients, so the class has to be swapped;
    swapping ``mo.httpx`` (not the real ``httpx`` module) keeps the blast
    radius inside the module under test.
    """
    monkeypatch.setattr(
        mo,
        "httpx",
        SimpleNamespace(AsyncClient=_mock_client_factory(handler)),
    )


def _json_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _session(**overrides: Any) -> mo.OAuthSession:
    kwargs: dict = {
        "agent_id": "agent-1",
        "client_key": "k1",
        "code_verifier": "verifier-abc",
        "client_id": "client-1",
        "auth_endpoint": "https://as.example.com/authorize",
        "token_endpoint": "https://as.example.com/token",
        "redirect_uri": "http://testserver/api/mcp/oauth/callback",
        "scope": "read write",
    }
    kwargs.update(overrides)
    return mo.OAuthSession(**kwargs)


@pytest.fixture(autouse=True)
def _clear_state_store() -> Any:
    """Every test starts and ends with an empty OAuth state store."""
    mo._state_store.clear()
    yield
    mo._state_store.clear()


@pytest.fixture(autouse=True)
def _no_managed_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the Hub-injected callback header out of the way by default."""
    monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", raising=False)


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceStub:
    return WorkspaceStub(tmp_path)


@pytest.fixture
def saved_card(workspace: WorkspaceStub) -> DriverCard:
    """Persist one real MCP DriverCard into the temp workspace.

    ``dump_card`` is used (not the async ``card_store.save``) because a
    sync fixture cannot await; dumping writes the same YAML the router
    later reads back through ``load_card``.
    """
    card = DriverCard(
        name="k1",
        protocol=PROTOCOL_MCP,
        endpoint={"url": MCP_URL, "transport": "sse"},
    )
    svc = DriverConfigService(workspace)
    dump_card(card, svc.card_path("k1", protocol=PROTOCOL_MCP))
    return card


def _seed_credential(
    workspace: WorkspaceStub,
    *,
    client_key: str = "k1",
    public: Optional[dict] = None,
    secrets: Optional[dict] = None,
) -> None:
    store = DriverConfigService(workspace).credential_store
    record = CredentialRecord(
        ref=mcp_oauth_credential_ref(client_key),
        kind="oauth2_auth_code",
        public=dict(public or {}),
        secrets=dict(secrets or {}),
        meta={},
    )
    store.put_sync(record)


@pytest.fixture
def app(workspace: WorkspaceStub) -> FastAPI:
    application = FastAPI()
    manager = MagicMock(name="ManagerStub")
    manager.get_agent = AsyncMock(return_value=workspace)
    application.state.multi_agent_manager = manager
    application.include_router(oauth_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def patch_agent(workspace: WorkspaceStub) -> Any:
    """Stub the agent lookup the endpoints import from agent_context."""
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=workspace),
    ) as patched:
        yield patched


# ---------------------------------------------------------------------------
# _mcp_card_path / _fetch_json
# ---------------------------------------------------------------------------


def test_mcp_card_path_points_at_protocol_scoped_yaml(
    workspace: WorkspaceStub,
) -> None:
    path = mo._mcp_card_path(workspace, "k1")
    assert path == workspace.workspace_dir / "drivers" / "mcp" / "k1.yaml"


class TestFetchJson:
    async def test_returns_payload_on_200(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"a": 1})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert await mo._fetch_json(http_client, MCP_URL) == {"a": 1}

    async def test_returns_none_on_error_status(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="nope")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert await mo._fetch_json(http_client, MCP_URL) is None

    async def test_swallows_transport_errors(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert await mo._fetch_json(http_client, MCP_URL) is None


# ---------------------------------------------------------------------------
# _probe_resource_metadata_url
# ---------------------------------------------------------------------------


class TestProbeResourceMetadata:
    async def test_ignores_non_401(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"www-authenticate": 'Bearer resource_metadata="u"'},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._probe_resource_metadata_url(http_client, MCP_URL)
                is None
            )

    async def test_extracts_url_from_401_header(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": (
                        'Bearer error="invalid_token", '
                        'Resource_Metadata="https://prm.example.com/meta"'
                    ),
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._probe_resource_metadata_url(http_client, MCP_URL)
                == "https://prm.example.com/meta"
            )

    async def test_returns_none_when_header_absent(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, headers={"www-authenticate": "Bearer"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._probe_resource_metadata_url(http_client, MCP_URL)
                is None
            )

    async def test_swallows_transport_errors(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._probe_resource_metadata_url(http_client, MCP_URL)
                is None
            )


# ---------------------------------------------------------------------------
# _resolve_auth_server_url
# ---------------------------------------------------------------------------


def _prm(as_urls: list) -> dict:
    return {"resource": MCP_URL, "authorization_servers": as_urls}


class TestResolveAuthServerUrl:
    async def test_uses_401_header_metadata(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == MCP_URL:
                return httpx.Response(
                    401,
                    headers={
                        "www-authenticate": (
                            "Bearer resource_metadata="
                            '"https://prm.example.com/m"'
                        ),
                    },
                )
            if str(request.url) == "https://prm.example.com/m":
                return _json_response(_prm([AS_URL]))
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._resolve_auth_server_url(http_client, MCP_URL)
                == AS_URL
            )

    async def test_falls_back_to_path_aware_well_known(self) -> None:
        requested: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            if request.url.path == (
                "/.well-known/oauth-protected-resource/coop/mcp"
            ):
                return _json_response(_prm([AS_URL]))
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._resolve_auth_server_url(http_client, MCP_URL)
                == AS_URL
            )
        assert MCP_URL in requested

    async def test_root_url_skips_path_candidate(self) -> None:
        requested: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            if request.url.path == "/.well-known/oauth-protected-resource":
                return _json_response(_prm([AS_URL]))
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._resolve_auth_server_url(
                    http_client,
                    "https://mcp.example.com/",
                )
                == AS_URL
            )
        # The probe hit the MCP URL verbatim first (404, so no
        # WWW-Authenticate); with an empty path suffix only the root
        # well-known is tried, never the path-aware candidate.
        assert requested == [
            "https://mcp.example.com/",
            "https://mcp.example.com/.well-known/oauth-protected-resource",
        ]

    async def test_returns_none_when_nothing_advertises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == MCP_URL:
                return httpx.Response(401)
            return _json_response({"resource": MCP_URL})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert (
                await mo._resolve_auth_server_url(http_client, MCP_URL) is None
            )


# ---------------------------------------------------------------------------
# _fetch_as_metadata
# ---------------------------------------------------------------------------


class TestFetchAsMetadata:
    async def test_root_server_tries_rfc8414_then_oidc(self) -> None:
        requested: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            if request.url.path == "/.well-known/openid-configuration":
                return _json_response(
                    {
                        "authorization_endpoint": f"{AS_URL}/authorize",
                        "token_endpoint": f"{AS_URL}/token",
                    },
                )
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            meta = await mo._fetch_as_metadata(http_client, AS_URL)

        assert meta is not None
        assert meta["token_endpoint"] == f"{AS_URL}/token"
        assert requested == [
            f"{AS_URL}/.well-known/oauth-authorization-server",
            f"{AS_URL}/.well-known/openid-configuration",
        ]

    async def test_path_server_tries_three_candidates(self) -> None:
        requested: list = []
        scoped = f"{AS_URL}/tenant"

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            if request.url.path == "/tenant/.well-known/openid-configuration":
                return _json_response({"authorization_endpoint": "https://a"})
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            meta = await mo._fetch_as_metadata(http_client, scoped)

        assert meta == {"authorization_endpoint": "https://a"}
        assert requested == [
            f"{AS_URL}/.well-known/oauth-authorization-server/tenant",
            f"{AS_URL}/.well-known/openid-configuration/tenant",
            f"{scoped}/.well-known/openid-configuration",
        ]

    async def test_metadata_without_authorization_endpoint_rejected(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"token_endpoint": f"{AS_URL}/token"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as http_client:
            assert await mo._fetch_as_metadata(http_client, AS_URL) is None


# ---------------------------------------------------------------------------
# _discover_oauth_metadata
# ---------------------------------------------------------------------------


def _full_as_metadata(**extra: Any) -> dict:
    payload = {
        "authorization_endpoint": f"{AS_URL}/authorize",
        "token_endpoint": f"{AS_URL}/token",
    }
    payload.update(extra)
    return payload


class TestDiscoverOauthMetadata:
    async def test_success_returns_all_three_endpoints(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == MCP_URL:
                return httpx.Response(
                    401,
                    headers={
                        "www-authenticate": (
                            "Bearer resource_metadata="
                            '"https://prm.example.com/m"'
                        ),
                    },
                )
            if str(request.url) == "https://prm.example.com/m":
                return _json_response(_prm([AS_URL]))
            if request.url.path == "/.well-known/oauth-authorization-server":
                return _json_response(
                    _full_as_metadata(registration_endpoint=f"{AS_URL}/reg"),
                )
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)

        assert await mo._discover_oauth_metadata(MCP_URL) == (
            f"{AS_URL}/authorize",
            f"{AS_URL}/token",
            f"{AS_URL}/reg",
        )

    async def test_missing_registration_endpoint_is_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == MCP_URL:
                return httpx.Response(
                    401,
                    headers={
                        "www-authenticate": (
                            "Bearer resource_metadata="
                            '"https://prm.example.com/m"'
                        ),
                    },
                )
            if str(request.url) == "https://prm.example.com/m":
                return _json_response(_prm([AS_URL]))
            return _json_response(_full_as_metadata())

        _patch_httpx(monkeypatch, handler)

        auth_ep, token_ep, reg = await mo._discover_oauth_metadata(MCP_URL)
        assert (auth_ep, token_ep, reg) == (
            f"{AS_URL}/authorize",
            f"{AS_URL}/token",
            None,
        )

    async def test_undiscoverable_server_raises_400(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _patch_httpx(monkeypatch, handler)

        with pytest.raises(HTTPException) as excinfo:
            await mo._discover_oauth_metadata(MCP_URL)
        assert excinfo.value.status_code == 400
        assert "RFC 9728" in str(excinfo.value.detail)

    async def test_metadata_without_endpoints_raises_400(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == MCP_URL:
                return httpx.Response(
                    401,
                    headers={
                        "www-authenticate": (
                            "Bearer resource_metadata="
                            '"https://prm.example.com/m"'
                        ),
                    },
                )
            if str(request.url) == "https://prm.example.com/m":
                return _json_response(_prm([AS_URL]))
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)

        with pytest.raises(HTTPException) as excinfo:
            await mo._discover_oauth_metadata(MCP_URL)
        assert excinfo.value.status_code == 400
        assert AS_URL in str(excinfo.value.detail)

    async def test_metadata_missing_token_endpoint_raises_400(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == MCP_URL:
                return httpx.Response(
                    401,
                    headers={
                        "www-authenticate": (
                            "Bearer resource_metadata="
                            '"https://prm.example.com/m"'
                        ),
                    },
                )
            if str(request.url) == "https://prm.example.com/m":
                return _json_response(_prm([AS_URL]))
            return _json_response(
                {"authorization_endpoint": f"{AS_URL}/authorize"},
            )

        _patch_httpx(monkeypatch, handler)

        with pytest.raises(HTTPException) as excinfo:
            await mo._discover_oauth_metadata(MCP_URL)
        assert excinfo.value.status_code == 400
        assert "token_endpoint" in str(excinfo.value.detail)


# ---------------------------------------------------------------------------
# _dynamic_register
# ---------------------------------------------------------------------------


class TestDynamicRegister:
    @pytest.mark.parametrize("status", [200, 201])
    async def test_returns_client_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
    ) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["json"] = json.loads(request.content.decode("utf-8"))
            return _json_response({"client_id": "dyn-1"}, status=status)

        _patch_httpx(monkeypatch, handler)

        assert (
            await mo._dynamic_register(f"{AS_URL}/reg", "https://cb")
            == "dyn-1"
        )
        assert seen["json"]["redirect_uris"] == ["https://cb"]
        assert seen["json"]["grant_types"] == [
            "authorization_code",
            "refresh_token",
        ]
        assert seen["json"]["token_endpoint_auth_method"] == "none"

    async def test_error_status_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad request")

        _patch_httpx(monkeypatch, handler)

        assert (
            await mo._dynamic_register(f"{AS_URL}/reg", "https://cb") is None
        )

    async def test_transport_error_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        _patch_httpx(monkeypatch, handler)

        assert (
            await mo._dynamic_register(f"{AS_URL}/reg", "https://cb") is None
        )


# ---------------------------------------------------------------------------
# _exchange_code_for_tokens
# ---------------------------------------------------------------------------


class TestExchangeCodeForTokens:
    async def test_posts_pkce_form_and_returns_tokens(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["form"] = request.content.decode("utf-8")
            return _json_response(
                {"access_token": "AT", "expires_in": 60, "scope": "read"},
            )

        _patch_httpx(monkeypatch, handler)

        tokens = await mo._exchange_code_for_tokens(_session(), "code-1")

        assert tokens["access_token"] == "AT"
        assert seen["url"] == f"{AS_URL}/token"
        assert "grant_type=authorization_code" in seen["form"]
        assert "code=code-1" in seen["form"]
        assert "code_verifier=verifier-abc" in seen["form"]
        assert "client_id=client-1" in seen["form"]

    async def test_omits_client_id_for_public_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["form"] = request.content.decode("utf-8")
            return _json_response({"access_token": "AT"})

        _patch_httpx(monkeypatch, handler)

        await mo._exchange_code_for_tokens(_session(client_id=""), "code-1")
        assert "client_id" not in seen["form"]

    async def test_error_status_raises_with_truncated_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # "z" is deliberately a character absent from the message prefix,
        # so counting it measures only the echoed body (counting "x" would
        # also hit the "x" inside the word "exchange").
        long_body = "z" * 400

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text=long_body)

        _patch_httpx(monkeypatch, handler)

        with pytest.raises(ValueError) as excinfo:
            await mo._exchange_code_for_tokens(_session(), "code-1")
        message = str(excinfo.value)
        assert message.startswith("Token exchange failed (HTTP 400): ")
        assert message.count("z") == 300

    async def test_transport_error_raises_value_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        _patch_httpx(monkeypatch, handler)

        with pytest.raises(ValueError) as excinfo:
            await mo._exchange_code_for_tokens(_session(), "code-1")
        assert "Token exchange request failed" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Credential / card loading helpers
# ---------------------------------------------------------------------------


class TestLoadHelpers:
    def test_workspace_credential_store_is_real_store(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        store = mo._workspace_credential_store(workspace)
        assert isinstance(store, AsyncCredentialStore)
        assert store is DriverConfigService(workspace).credential_store

    async def test_load_card_returns_saved_card(
        self,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
    ) -> None:
        card = await mo._load_mcp_card_for_oauth(workspace, "k1")
        assert card.endpoint["url"] == MCP_URL

    async def test_missing_card_raises_404_with_client_key(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        with pytest.raises(HTTPException) as excinfo:
            await mo._load_mcp_card_for_oauth(workspace, "ghost")
        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "MCP client 'ghost' not found"

    async def test_value_error_variant_converts_404(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        with pytest.raises(ValueError) as excinfo:
            await mo._load_mcp_card_for_oauth_value_error(workspace, "ghost")
        assert "MCP client 'ghost' not found" in str(excinfo.value)
        assert "re-authorize" in str(excinfo.value)

    async def test_value_error_variant_passes_card_through(
        self,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
    ) -> None:
        card = await mo._load_mcp_card_for_oauth_value_error(workspace, "k1")
        assert card.name == "k1"

    async def test_optional_credential_maps_not_found_to_none(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        store = AsyncCredentialStore(
            workspace.workspace_dir / "credentials.yaml",
        )
        assert (
            await mo._load_optional_credential(store, "mcp/k1/oauth") is None
        )

    async def test_optional_credential_returns_record(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        _seed_credential(workspace, public={"client_id": "cid"})
        store = mo._workspace_credential_store(workspace)
        record = await mo._load_optional_credential(store, "mcp/k1/oauth")
        assert record is not None
        assert record.public["client_id"] == "cid"

    async def test_optional_oauth_credential_uses_oauth_ref(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        assert (
            await mo._load_optional_oauth_credential(workspace, "k1") is None
        )
        _seed_credential(workspace, secrets={"access_token": "AT"})
        record = await mo._load_optional_oauth_credential(workspace, "k1")
        assert record is not None
        assert record.secrets["access_token"] == "AT"

    async def test_reload_driver_best_effort_is_silent_without_manager(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        await mo._reload_driver_best_effort(workspace, "k1")

    async def test_credential_not_found_error_carries_ref(self) -> None:
        error = CredentialNotFoundError("mcp/k1/oauth")
        assert error.ref == "mcp/k1/oauth"


# ---------------------------------------------------------------------------
# _persist_tokens
# ---------------------------------------------------------------------------


def _request_with_manager(manager: Any) -> Any:
    """A Request-like object whose ``app.state`` carries *manager*.

    ``_persist_tokens`` only reaches for ``request.app.state``, so a
    namespace is enough and avoids building a full ASGI scope.
    """
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                multi_agent_manager=manager,
            ),
        ),
    )


def _request_without_manager() -> Any:
    """A Request-like object whose ``app.state`` has no manager at all."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


class TestPersistTokens:
    async def test_missing_access_token_raises(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            await mo._persist_tokens(
                _request_with_manager(MagicMock()),
                _session(),
                {"refresh_token": "RT"},
            )
        assert "access_token" in str(excinfo.value)

    async def test_missing_manager_raises(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            await mo._persist_tokens(
                _request_without_manager(),
                _session(),
                {"access_token": "AT"},
            )
        assert "MultiAgentManager" in str(excinfo.value)

    async def test_writes_public_fields_secrets_and_card_binding(
        self,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
    ) -> None:
        manager = MagicMock(name="ManagerStub")
        manager.get_agent = AsyncMock(return_value=workspace)
        before = time.time()

        await mo._persist_tokens(
            _request_with_manager(manager),
            _session(scope=""),
            {
                "access_token": "AT-1",
                "refresh_token": "RT-1",
                "expires_in": 120,
                "scope": "granted",
            },
        )

        record = await mo._load_optional_oauth_credential(workspace, "k1")
        assert record is not None
        assert record.kind == "oauth2_auth_code"
        assert record.secrets == {
            "access_token": "AT-1",
            "refresh_token": "RT-1",
        }
        assert record.public["client_id"] == "client-1"
        assert record.public["scope"] == "granted"
        assert record.public["token_endpoint"] == f"{AS_URL}/token"
        assert record.public["auth_endpoint"] == f"{AS_URL}/authorize"
        assert before + 120 <= record.public["expires_at"]
        assert record.public["expires_at"] <= time.time() + 120
        assert record.meta["updated_at"] >= before

        card = await mo._load_mcp_card_for_oauth(workspace, "k1")
        assert OAUTH_CREDENTIAL_ALIAS in card.credentials
        assert card.credentials[OAUTH_CREDENTIAL_ALIAS].ref == "mcp/k1/oauth"
        assert card.endpoint["headers"]["Authorization"]["field"] == (
            "access_token"
        )

    async def test_defaults_expire_in_one_hour_and_keeps_session_scope(
        self,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
    ) -> None:
        manager = MagicMock(name="ManagerStub")
        manager.get_agent = AsyncMock(return_value=workspace)

        await mo._persist_tokens(
            _request_with_manager(manager),
            _session(scope="read write"),
            {"access_token": "AT-1"},
        )

        record = await mo._load_optional_oauth_credential(workspace, "k1")
        assert record is not None
        assert record.public["scope"] == "read write"
        assert record.public["expires_at"] - time.time() > 3500
        assert "refresh_token" not in record.secrets

    async def test_merges_existing_public_and_meta(
        self,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
    ) -> None:
        _seed_credential(
            workspace,
            public={"client_id": "old-cid", "extra": "keep-me"},
            secrets={"access_token": "OLD"},
        )
        record_before = await mo._load_optional_oauth_credential(
            workspace,
            "k1",
        )
        assert record_before is not None
        record_before.meta["created_at"] = 1.0
        await mo._workspace_credential_store(workspace).put(record_before)

        manager = MagicMock(name="ManagerStub")
        manager.get_agent = AsyncMock(return_value=workspace)
        await mo._persist_tokens(
            _request_with_manager(manager),
            _session(client_id=""),
            {"access_token": "NEW"},
        )

        record = await mo._load_optional_oauth_credential(workspace, "k1")
        assert record is not None
        assert record.public["client_id"] == "old-cid"
        assert record.public["extra"] == "keep-me"
        assert record.public["auth_endpoint"] == f"{AS_URL}/authorize"
        assert record.secrets == {"access_token": "NEW"}
        assert record.meta["created_at"] == 1.0

    async def test_blank_agent_id_falls_back_to_active_agent(
        self,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
    ) -> None:
        manager = MagicMock(name="ManagerStub")
        manager.get_agent = AsyncMock(return_value=workspace)
        config_stub = MagicMock(name="ConfigStub")
        config_stub.agents.active_agent = "active-7"

        with patch(
            "qwenpaw.config.utils.load_config",
            return_value=config_stub,
        ) as load_config:
            await mo._persist_tokens(
                _request_with_manager(manager),
                _session(agent_id=""),
                {"access_token": "AT-1"},
            )

        load_config.assert_called_once_with()
        manager.get_agent.assert_awaited_once_with("active-7")

    async def test_missing_card_raises_value_error(
        self,
        workspace: WorkspaceStub,
    ) -> None:
        manager = MagicMock(name="ManagerStub")
        manager.get_agent = AsyncMock(return_value=workspace)
        with pytest.raises(ValueError) as excinfo:
            await mo._persist_tokens(
                _request_with_manager(manager),
                _session(client_key="ghost"),
                {"access_token": "AT-1"},
            )
        assert "MCP client 'ghost' not found" in str(excinfo.value)


# ---------------------------------------------------------------------------
# POST /oauth/start/{client_key}
# ---------------------------------------------------------------------------


class TestOauthStartEndpoint:
    def test_explicit_endpoints_skip_discovery(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
    ) -> None:
        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={
                "url": MCP_URL,
                "scope": "read",
                "client_id": "cid-1",
                "auth_endpoint": f"{AS_URL}/authorize",
                "token_endpoint": f"{AS_URL}/token",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        state = payload["session_id"]
        assert state in mo._state_store
        assert payload["auth_url"].startswith(f"{AS_URL}/authorize?")
        assert "response_type=code" in payload["auth_url"]
        assert "code_challenge_method=S256" in payload["auth_url"]
        assert "client_id=cid-1" in payload["auth_url"]
        assert "scope=read" in payload["auth_url"]
        assert f"state={state}" in payload["auth_url"]
        assert (
            "redirect_uri=http%3A%2F%2Ftestserver%2Fapi%2Fmcp%2Foauth"
            "%2Fcallback" in payload["auth_url"]
        )

        session = mo._state_store[state]
        assert session.agent_id == "agent-1"
        assert session.client_key == "k1"
        assert session.client_id == "cid-1"
        assert session.token_endpoint == f"{AS_URL}/token"
        assert mo._code_challenge(session.code_verifier) in payload["auth_url"]

    def test_card_url_wins_over_request_body(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        discover = AsyncMock(
            return_value=(f"{AS_URL}/authorize", f"{AS_URL}/token", None),
        )
        monkeypatch.setattr(mo, "_discover_oauth_metadata", discover)

        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={"url": "https://other.example.com/mcp"},
        )

        assert response.status_code == 200
        discover.assert_awaited_once_with(MCP_URL)

    def test_missing_url_raises_400(
        self,
        client: TestClient,
        patch_agent: Any,
        workspace: WorkspaceStub,
    ) -> None:
        svc = DriverConfigService(workspace)
        dump_card(
            DriverCard(
                name="nourl",
                protocol=PROTOCOL_MCP,
                endpoint={"transport": "stdio"},
            ),
            svc.card_path("nourl", protocol=PROTOCOL_MCP),
        )

        response = client.post("/api/mcp/oauth/start/nourl", json={"url": ""})

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "OAuth MCP client must have a remote URL."
        )

    def test_unknown_client_raises_404(
        self,
        client: TestClient,
        patch_agent: Any,
    ) -> None:
        response = client.post(
            "/api/mcp/oauth/start/ghost",
            json={"url": MCP_URL},
        )
        assert response.status_code == 404

    def test_discovery_path_with_dynamic_registration(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            mo,
            "_discover_oauth_metadata",
            AsyncMock(
                return_value=(
                    f"{AS_URL}/authorize",
                    f"{AS_URL}/token",
                    f"{AS_URL}/register",
                ),
            ),
        )
        register = AsyncMock(return_value="dyn-9")
        monkeypatch.setattr(mo, "_dynamic_register", register)

        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={"url": MCP_URL},
        )

        assert response.status_code == 200
        payload = response.json()
        assert "client_id=dyn-9" in payload["auth_url"]
        assert "scope=" not in payload["auth_url"]
        register.assert_awaited_once_with(
            f"{AS_URL}/register",
            "http://testserver/api/mcp/oauth/callback",
        )
        assert mo._state_store[payload["session_id"]].client_id == "dyn-9"

    def test_failed_registration_leaves_client_id_empty(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            mo,
            "_discover_oauth_metadata",
            AsyncMock(
                return_value=(
                    f"{AS_URL}/authorize",
                    f"{AS_URL}/token",
                    f"{AS_URL}/register",
                ),
            ),
        )
        monkeypatch.setattr(
            mo,
            "_dynamic_register",
            AsyncMock(return_value=None),
        )

        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={"url": MCP_URL},
        )

        assert response.status_code == 200
        payload = response.json()
        assert "client_id=" not in payload["auth_url"]
        assert mo._state_store[payload["session_id"]].client_id == ""

    def test_existing_credential_supplies_client_id(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        workspace: WorkspaceStub,
    ) -> None:
        _seed_credential(workspace, public={"client_id": "stored-cid"})

        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={
                "url": MCP_URL,
                "auth_endpoint": f"{AS_URL}/authorize",
                "token_endpoint": f"{AS_URL}/token",
            },
        )

        assert response.status_code == 200
        assert "client_id=stored-cid" in response.json()["auth_url"]

    def test_expired_sessions_are_purged_on_start(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
    ) -> None:
        stale = _session()
        stale.created_at = time.monotonic() - mo._TTL_SECONDS - 1
        mo._state_store["stale"] = stale

        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={
                "url": MCP_URL,
                "auth_endpoint": f"{AS_URL}/authorize",
                "token_endpoint": f"{AS_URL}/token",
            },
        )

        assert response.status_code == 200
        assert "stale" not in mo._state_store

    def test_managed_callback_header_wins(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "tok")

        response = client.post(
            "/api/mcp/oauth/start/k1",
            json={
                "url": MCP_URL,
                "auth_endpoint": f"{AS_URL}/authorize",
                "token_endpoint": f"{AS_URL}/token",
            },
            headers={
                "x-qwenpaw-hub-oauth-callback-url": "https://hub/cb",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert "redirect_uri=https%3A%2F%2Fhub%2Fcb" in payload["auth_url"]
        state = payload["session_id"]
        assert mo._state_store[state].redirect_uri == "https://hub/cb"


# ---------------------------------------------------------------------------
# GET /oauth/callback
# ---------------------------------------------------------------------------


def _stored_session(**overrides: Any) -> str:
    session = _session(**overrides)
    mo._state_store["state-1"] = session
    return "state-1"


class TestOauthCallbackEndpoint:
    def test_error_param_renders_error_page(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/api/mcp/oauth/callback",
            params={
                "error": "access_denied",
                "error_description": "user said no",
            },
        )

        assert response.status_code == 400
        body = response.text
        assert "user said no" in body
        assert '"status": "error"' in body

    def test_error_without_description_uses_error_code(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/api/mcp/oauth/callback",
            params={"error": "access_denied"},
        )
        assert response.status_code == 400
        assert "access_denied" in response.text

    def test_missing_code_and_state_renders_error_page(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/mcp/oauth/callback", params={"code": "c"})
        assert response.status_code == 400
        assert "Missing" in response.text

    def test_unknown_state_renders_error_page(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "c", "state": "nope"},
        )
        assert response.status_code == 400
        assert "expired or not found" in response.text

    def test_expired_session_renders_error_page(
        self,
        client: TestClient,
    ) -> None:
        _stored_session()
        mo._state_store["state-1"].created_at = (
            time.monotonic() - mo._TTL_SECONDS - 1
        )

        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "c", "state": "state-1"},
        )

        assert response.status_code == 400
        assert "expired or not found" in response.text

    def test_success_exchanges_persists_and_pops_state(
        self,
        client: TestClient,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stored_session()
        tokens = {"access_token": "AT-9", "expires_in": 30}
        exchange = AsyncMock(return_value=tokens)
        persist = AsyncMock(return_value=None)
        monkeypatch.setattr(mo, "_exchange_code_for_tokens", exchange)
        monkeypatch.setattr(mo, "_persist_tokens", persist)

        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "code-9", "state": "state-1"},
        )

        assert response.status_code == 200
        body = response.text
        assert '"status": "success"' in body
        assert '"clientKey": "k1"' in body
        assert '"agentId": "agent-1"' in body
        exchange.assert_awaited_once()
        assert exchange.await_args.args[1] == "code-9"
        persist.assert_awaited_once()
        assert persist.await_args.args[2] == tokens
        assert "state-1" not in mo._state_store

    def test_exchange_failure_renders_error_and_keeps_session(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stored_session()
        monkeypatch.setattr(
            mo,
            "_exchange_code_for_tokens",
            AsyncMock(
                side_effect=ValueError("Token exchange failed (HTTP 400)"),
            ),
        )

        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "c", "state": "state-1"},
        )

        assert response.status_code == 400
        assert "Token exchange failed" in response.text
        assert "state-1" in mo._state_store

    def test_http_exception_detail_is_surfaced(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stored_session()
        monkeypatch.setattr(
            mo,
            "_exchange_code_for_tokens",
            AsyncMock(
                side_effect=HTTPException(status_code=404, detail="gone"),
            ),
        )

        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "c", "state": "state-1"},
        )

        assert response.status_code == 400
        assert "gone" in response.text

    def test_persist_failure_renders_error(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stored_session()
        monkeypatch.setattr(
            mo,
            "_exchange_code_for_tokens",
            AsyncMock(return_value={"access_token": "AT"}),
        )
        monkeypatch.setattr(
            mo,
            "_persist_tokens",
            AsyncMock(side_effect=ValueError("MultiAgentManager missing")),
        )

        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "c", "state": "state-1"},
        )

        assert response.status_code == 400
        assert "MultiAgentManager missing" in response.text

    def test_end_to_end_callback_writes_real_credential(
        self,
        client: TestClient,
        workspace: WorkspaceStub,
        saved_card: DriverCard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full leg: real exchange stub + real store, asserting disk state."""
        _stored_session()

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "access_token": "AT-e2e",
                    "refresh_token": "RT-e2e",
                    "expires_in": 90,
                },
            )

        _patch_httpx(monkeypatch, handler)

        response = client.get(
            "/api/mcp/oauth/callback",
            params={"code": "code-e2e", "state": "state-1"},
        )

        assert response.status_code == 200
        record = AsyncCredentialStore(
            workspace.workspace_dir / "credentials.yaml",
        ).get_sync("mcp/k1/oauth")
        assert record.secrets["access_token"] == "AT-e2e"
        assert record.public["expires_at"] > time.time()


# ---------------------------------------------------------------------------
# GET /oauth/status/{client_key}
# ---------------------------------------------------------------------------


class TestOauthStatusEndpoint:
    def test_without_credential_reports_unauthorized(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
    ) -> None:
        response = client.get("/api/mcp/oauth/status/k1")
        assert response.status_code == 200
        assert response.json() == {
            "authorized": False,
            "expires_at": 0.0,
            "scope": "",
        }

    def test_credential_without_token_reports_unauthorized(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        workspace: WorkspaceStub,
    ) -> None:
        _seed_credential(workspace, public={"scope": "read"})
        response = client.get("/api/mcp/oauth/status/k1")
        assert response.status_code == 200
        assert response.json()["authorized"] is False

    def test_valid_token_reports_authorized(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        workspace: WorkspaceStub,
    ) -> None:
        expiry = time.time() + 600
        _seed_credential(
            workspace,
            public={"scope": "read write", "expires_at": expiry},
            secrets={"access_token": "AT"},
        )

        payload = client.get("/api/mcp/oauth/status/k1").json()

        assert payload["authorized"] is True
        assert payload["scope"] == "read write"
        assert payload["expires_at"] == pytest.approx(expiry)

    def test_expired_token_reports_unauthorized(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        workspace: WorkspaceStub,
    ) -> None:
        expiry = time.time() - 5
        _seed_credential(
            workspace,
            public={"expires_at": expiry},
            secrets={"access_token": "AT"},
        )

        payload = client.get("/api/mcp/oauth/status/k1").json()

        assert payload["authorized"] is False
        assert payload["expires_at"] == pytest.approx(expiry)

    def test_zero_expiry_means_no_expiry(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        workspace: WorkspaceStub,
    ) -> None:
        _seed_credential(
            workspace,
            public={"expires_at": 0},
            secrets={"access_token": "AT"},
        )

        payload = client.get("/api/mcp/oauth/status/k1").json()

        assert payload["authorized"] is True
        assert payload["expires_at"] == 0.0

    def test_unknown_client_raises_404(
        self,
        client: TestClient,
        patch_agent: Any,
    ) -> None:
        assert client.get("/api/mcp/oauth/status/ghost").status_code == 404


# ---------------------------------------------------------------------------
# DELETE /oauth/{client_key}
# ---------------------------------------------------------------------------


class TestOauthRevokeEndpoint:
    def test_clears_credential_and_detaches_card(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
        workspace: WorkspaceStub,
    ) -> None:
        _seed_credential(
            workspace,
            public={"client_id": "cid"},
            secrets={"access_token": "AT"},
        )
        svc = DriverConfigService(workspace)
        dump_card(
            attach_mcp_oauth_credential(
                saved_card,
                mcp_oauth_credential_ref("k1"),
            ),
            svc.card_path("k1", protocol=PROTOCOL_MCP),
        )

        response = client.delete("/api/mcp/oauth/k1")

        assert response.status_code == 200
        assert response.json() == {"message": "OAuth tokens cleared"}
        store = AsyncCredentialStore(
            workspace.workspace_dir / "credentials.yaml",
        )
        with pytest.raises(CredentialNotFoundError):
            store.get_sync("mcp/k1/oauth")
        card = load_card(svc.card_path("k1", protocol=PROTOCOL_MCP))
        assert OAUTH_CREDENTIAL_ALIAS not in card.credentials
        assert "Authorization" not in card.endpoint.get("headers", {})

    def test_revoking_without_credential_still_succeeds(
        self,
        client: TestClient,
        patch_agent: Any,
        saved_card: DriverCard,
    ) -> None:
        response = client.delete("/api/mcp/oauth/k1")
        assert response.status_code == 200
        assert response.json() == {"message": "OAuth tokens cleared"}

    def test_unknown_client_raises_404(
        self,
        client: TestClient,
        patch_agent: Any,
    ) -> None:
        assert client.delete("/api/mcp/oauth/ghost").status_code == 404
