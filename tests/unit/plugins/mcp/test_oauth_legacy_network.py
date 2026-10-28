# -*- coding: utf-8 -*-
"""Conserved legacy OAuth network assertions against plugin-owned helpers.

Moved from app/routers/test_mcp_oauth_flows.py: metadata, discovery, DCR,
and PKCE exchange retain their synthetic HTTP requests and payload assertions.
The plugin maps HTTP transport exceptions at its callback response boundary.
"""
# pylint: disable=protected-access,unused-argument
import json
import base64
import hashlib
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from mcp_plugin_under_test import oauth, oauth_helpers as mo

MCP_URL = "https://mcp.example.com/coop/mcp"
AS_URL = "https://as.example.com"


def _patch_httpx(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(*args, **kwargs)

    substitute = SimpleNamespace(AsyncClient=factory)
    monkeypatch.setattr(mo, "httpx", substitute)
    monkeypatch.setattr(oauth, "httpx", substitute)


def _json_response(payload, status=200):
    return httpx.Response(status, json=payload)


def _session(**overrides):
    return SimpleNamespace(
        **{
            "code_verifier": "verifier-abc",
            "client_id": "client-1",
            "token_endpoint": "https://as.example.com/token",
            "redirect_uri": "http://testserver/api/mcp/oauth/callback",
            **overrides,
        },
    )


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

        with pytest.raises(mo.OAuthError) as excinfo:
            await mo._discover_oauth_metadata(MCP_URL)
        assert excinfo.value.status == 400
        assert "RFC 9728" in str(excinfo.value)

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

        with pytest.raises(mo.OAuthError) as excinfo:
            await mo._discover_oauth_metadata(MCP_URL)
        assert excinfo.value.status == 400
        assert AS_URL in str(excinfo.value)

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

        with pytest.raises(mo.OAuthError) as excinfo:
            await mo._discover_oauth_metadata(MCP_URL)
        assert excinfo.value.status == 400
        assert "token_endpoint" in str(excinfo.value)


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

        tokens = await oauth._exchange_code_for_tokens(_session(), "code-1")

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

        await oauth._exchange_code_for_tokens(_session(client_id=""), "code-1")
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
            await oauth._exchange_code_for_tokens(_session(), "code-1")
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

        with pytest.raises(httpx.ConnectError, match="boom"):
            await oauth._exchange_code_for_tokens(_session(), "code-1")


class TestPkce:
    def test_verifier_is_urlsafe_base64(self):
        verifier = mo._generate_code_verifier()
        assert verifier
        # must be valid urlsafe base64 without padding
        assert "=" not in verifier
        assert "+" not in verifier
        assert "/" not in verifier

    def test_verifier_random_each_call(self):
        assert mo._generate_code_verifier() != mo._generate_code_verifier()

    def test_code_challenge_is_s256_of_verifier(self):
        verifier = "test-verifier-abc123"
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest(),
            )
            .rstrip(b"=")
            .decode()
        )
        assert mo._code_challenge(verifier) == expected

    def test_code_challenge_urlsafe(self):
        challenge = mo._code_challenge("v" * 64)
        assert "+" not in challenge
        assert "/" not in challenge


# ---------------------------------------------------------------------------
# OAuthSession / _purge_expired
# ---------------------------------------------------------------------------


def _ttl_session(created_ago: float = 0.0):
    session = oauth.OAuthSession(
        workspace_id="a1",
        workspace_instance_id="instance-1",
        source_revision=1,
        client_key="k1",
        code_verifier="verifier",
        client_id="client",
        auth_endpoint="https://auth",
        token_endpoint="https://token",
        redirect_uri="https://cb",
        scope="read",
    )
    session.created_at = time.monotonic() - created_ago
    return session


class TestOAuthSession:
    def test_fresh_session_not_expired(self):
        assert _ttl_session().is_expired() is False

    def test_old_session_expired(self):
        assert (
            _ttl_session(created_ago=oauth._TTL_SECONDS + 1).is_expired()
            is True
        )

    def test_attributes_stored(self):
        session = _ttl_session()
        assert session.workspace_id == "a1"
        assert session.client_key == "k1"
        assert session.scope == "read"


management = oauth.OAuthManagement()


class TestPurgeExpired:
    @pytest.fixture(autouse=True)
    def _clean_store(self):
        management._states.clear()
        yield
        management._states.clear()

    def test_removes_only_expired(self):
        management._states["fresh"] = _ttl_session()
        management._states["old"] = _ttl_session(
            created_ago=oauth._TTL_SECONDS + 1,
        )
        management._purge()
        assert "fresh" in management._states
        assert "old" not in management._states

    def test_empty_store_safe(self):
        management._purge()  # must not raise
        assert management._states == {}
