# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,redefined-outer-name
"""Route tests for provider auth endpoints."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.providers.auth.adapter import ProviderAuthAdapter
from qwenpaw.providers.auth.credential_store import OAuthCredentialStore
from qwenpaw.providers.auth.manager import ProviderAuthManager
from qwenpaw.providers.auth.models import (
    AuthStartRequest,
    AuthStartResult,
    AuthStatusResult,
    OAuthCredential,
    ProviderAuthFlowType,
    ProviderAuthStatus,
    ProviderAuthType,
)
from qwenpaw.providers.auth.registry import ProviderAuthRegistry
from qwenpaw.providers.openai_provider import OpenAIProvider


class _MockModule(types.ModuleType):
    def __getattr__(self, name: str):
        value = MagicMock(name=name)
        setattr(self, name, value)
        return value


_ROUTER_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "qwenpaw"
    / "app"
    / "routers"
    / "providers.py"
)

pytestmark = pytest.mark.anyio


def _load_providers_router(monkeypatch):
    agent_context_module = _MockModule("qwenpaw.app.agent_context")
    agent_context_module.get_agent_for_request = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.app.agent_context",
        agent_context_module,
    )

    app_utils_module = _MockModule("qwenpaw.app.utils")
    app_utils_module.schedule_agent_reload = MagicMock()
    monkeypatch.setitem(sys.modules, "qwenpaw.app.utils", app_utils_module)

    routers_pkg = types.ModuleType("qwenpaw.app.routers")
    routers_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "qwenpaw.app.routers", routers_pkg)

    spec = importlib.util.spec_from_file_location(
        "qwenpaw.app.routers.providers_auth_test",
        _ROUTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    providers_router = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, providers_router)
    spec.loader.exec_module(providers_router)
    return providers_router


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_master_key(tmp_path: Path, monkeypatch):
    import qwenpaw.security.secret_store as mod

    test_key = bytes.fromhex(
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    )
    monkeypatch.setattr(mod, "_cached_master_key", test_key)
    monkeypatch.setattr(mod, "_cached_fernet", None)
    monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path)


class FakeProviderManager:
    def __init__(self, providers):
        self.providers = providers

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)


class FakeAuthAdapter(ProviderAuthAdapter):
    provider_id = "oauth"
    auth_type = ProviderAuthType.OAUTH_DEVICE_CODE

    async def start(
        self,
        provider,
        request: AuthStartRequest,
    ) -> AuthStartResult:
        return AuthStartResult(
            flow_id="fake-flow",
            flow_type=ProviderAuthFlowType.DEVICE_CODE,
            user_code="ABCD-EFGH",
            verification_uri="https://example.test/device",
        )

    async def handle_callback(
        self,
        provider,
        state: str,
        code: str,
    ) -> OAuthCredential:
        return OAuthCredential(
            provider_id=provider.id,
            access_token="oauth-access-token",
            account_label="octocat",
            created_at=1760000000,
            updated_at=1760000001,
        )

    async def get_status(self, provider, credential) -> AuthStatusResult:
        if credential:
            return AuthStatusResult(
                status=ProviderAuthStatus.AUTHENTICATED,
                account_label=credential.account_label,
            )
        return AuthStatusResult(status=ProviderAuthStatus.NOT_CONFIGURED)


def _provider(
    provider_id: str,
    auth_type: ProviderAuthType = ProviderAuthType.API_KEY,
) -> OpenAIProvider:
    return OpenAIProvider(
        id=provider_id,
        name=provider_id,
        auth_type=auth_type,
    )


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch):
    providers_router = _load_providers_router(monkeypatch)
    registry = ProviderAuthRegistry()
    registry.register(FakeAuthAdapter())
    fake_manager = FakeProviderManager(
        {
            "api": _provider("api"),
            "oauth": _provider(
                "oauth",
                auth_type=ProviderAuthType.OAUTH_DEVICE_CODE,
            ),
        },
    )

    app = FastAPI()
    app.state.provider_manager = fake_manager
    app.state.provider_auth_manager = ProviderAuthManager(
        fake_manager,
        credential_store=OAuthCredentialStore(tmp_path / "providers"),
        registry=registry,
    )
    app.include_router(providers_router.router, prefix="/api")
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_missing_provider_returns_404(api_client) -> None:
    async with api_client:
        response = await api_client.get("/api/models/missing/auth/status")

    assert response.status_code == 404


async def test_api_key_provider_start_returns_400(api_client) -> None:
    async with api_client:
        response = await api_client.post("/api/models/api/auth/start")

    assert response.status_code == 400
    assert "API key authentication" in response.json()["detail"]


async def test_api_key_provider_logout_returns_400(api_client) -> None:
    async with api_client:
        response = await api_client.post("/api/models/api/auth/logout")

    assert response.status_code == 400
    assert "does not support logout" in response.json()["detail"]


async def test_oauth_provider_start_returns_standard_schema(
    api_client,
) -> None:
    async with api_client:
        response = await api_client.post(
            "/api/models/oauth/auth/start",
            json={
                "redirect_uri": ("http://test/api/models/oauth/auth/callback"),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "flow_id": "fake-flow",
        "flow_type": "device_code",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://example.test/device",
        "authorization_url": None,
        "expires_at": None,
        "interval": None,
        "message": "",
    }


async def test_oauth_provider_start_rejects_external_redirect_uri(
    api_client,
) -> None:
    async with api_client:
        response = await api_client.post(
            "/api/models/oauth/auth/start",
            json={"redirect_uri": "https://evil.test/callback"},
        )

    assert response.status_code == 400
    assert "redirect_uri" in response.json()["detail"]


async def test_status_and_logout_return_standard_schema(api_client) -> None:
    async with api_client:
        status_response = await api_client.get(
            "/api/models/oauth/auth/status",
        )
        logout_response = await api_client.post(
            "/api/models/oauth/auth/logout",
        )

    assert status_response.status_code == 200
    assert status_response.json() == {
        "status": "not_configured",
        "account_label": "",
        "expires_at": None,
        "scopes": [],
        "message": "",
    }
    assert logout_response.status_code == 200
    assert logout_response.json() == {
        "status": "not_configured",
        "account_label": "",
        "expires_at": None,
        "scopes": [],
        "message": "",
    }
