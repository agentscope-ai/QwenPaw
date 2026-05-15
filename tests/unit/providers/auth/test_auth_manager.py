# -*- coding: utf-8 -*-
"""Tests for provider auth manager orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.providers.auth.adapter import ProviderAuthAdapter
from qwenpaw.providers.auth.credential_store import OAuthCredentialStore
from qwenpaw.providers.auth.manager import (
    ProviderAuthError,
    ProviderAuthManager,
)
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

pytestmark = pytest.mark.anyio


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
    def __init__(self, providers, storage_types=None):
        self.providers = providers
        self.storage_types = storage_types or {}

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)

    def get_provider_with_storage_type(self, provider_id: str):
        provider = self.providers.get(provider_id)
        if provider is None:
            return None
        return provider, self.storage_types.get(provider_id, "custom")


class FakeAuthAdapter(ProviderAuthAdapter):
    provider_id = "oauth"
    auth_type = ProviderAuthType.OAUTH_DEVICE_CODE

    def __init__(self) -> None:
        self.poll_count = 0
        self.logout_called = False

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

    async def poll(self, provider, flow_id: str) -> AuthStatusResult:
        self.poll_count += 1
        if self.poll_count == 1:
            return AuthStatusResult(status=ProviderAuthStatus.PENDING)
        return AuthStatusResult(
            status=ProviderAuthStatus.AUTHENTICATED,
            account_label="octocat",
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
            refresh_token="oauth-refresh-token",
            account_label="octocat",
            scopes=["read:user"],
            created_at=1760000000,
            updated_at=1760000001,
        )

    async def logout(
        self,
        provider,
        credential: OAuthCredential | None,
    ) -> None:
        self.logout_called = True


def _provider(
    provider_id: str,
    api_key: str = "",
    require_api_key: bool = True,
    auth_type: ProviderAuthType = ProviderAuthType.API_KEY,
) -> OpenAIProvider:
    return OpenAIProvider(
        id=provider_id,
        name=provider_id,
        api_key=api_key,
        require_api_key=require_api_key,
        auth_type=auth_type,
    )


def _manager(tmp_path: Path, providers, registry: ProviderAuthRegistry):
    return ProviderAuthManager(
        FakeProviderManager(providers),
        credential_store=OAuthCredentialStore(tmp_path / "providers"),
        registry=registry,
    )


async def test_api_key_provider_status_authenticated(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
        {"api": _provider("api", api_key="sk-test")},
        ProviderAuthRegistry(),
    )

    status = await manager.get_status("api")

    assert status.status == ProviderAuthStatus.AUTHENTICATED


async def test_api_key_provider_status_not_configured(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
        {"api": _provider("api")},
        ProviderAuthRegistry(),
    )

    status = await manager.get_status("api")

    assert status.status == ProviderAuthStatus.NOT_CONFIGURED


async def test_api_key_provider_logout_is_not_supported(
    tmp_path: Path,
) -> None:
    manager = _manager(
        tmp_path,
        {"api": _provider("api", api_key="sk-test")},
        ProviderAuthRegistry(),
    )

    with pytest.raises(ProviderAuthError) as exc_info:
        await manager.logout("api")

    assert exc_info.value.status_code == 400
    assert "does not support logout" in exc_info.value.message


async def test_provider_without_required_api_key_is_not_required(
    tmp_path: Path,
) -> None:
    provider = _provider("local", require_api_key=False)
    manager = _manager(
        tmp_path,
        {"local": provider},
        ProviderAuthRegistry(),
    )

    status = await manager.get_status("local")
    info = await provider.get_info()

    assert status.status == ProviderAuthStatus.NOT_REQUIRED
    assert info.auth_type == ProviderAuthType.API_KEY
    assert info.auth is not None
    assert info.auth.type == ProviderAuthType.NONE
    assert info.auth.status == ProviderAuthStatus.NOT_REQUIRED


async def test_oauth_provider_without_adapter_start_is_unsupported(
    tmp_path: Path,
) -> None:
    manager = _manager(
        tmp_path,
        {
            "oauth": _provider(
                "oauth",
                auth_type=ProviderAuthType.OAUTH_DEVICE_CODE,
            ),
        },
        ProviderAuthRegistry(),
    )

    with pytest.raises(ProviderAuthError) as exc_info:
        await manager.start("oauth", AuthStartRequest())

    assert exc_info.value.status_code == 400
    assert "does not support OAuth" in exc_info.value.message


async def test_oauth_provider_with_adapter_starts_and_polls(
    tmp_path: Path,
) -> None:
    registry = ProviderAuthRegistry()
    registry.register(FakeAuthAdapter())
    manager = _manager(
        tmp_path,
        {
            "oauth": _provider(
                "oauth",
                auth_type=ProviderAuthType.OAUTH_DEVICE_CODE,
            ),
        },
        registry,
    )

    started = await manager.start("oauth", AuthStartRequest())
    first = await manager.get_status("oauth", flow_id=started.flow_id)
    second = await manager.get_status("oauth", flow_id=started.flow_id)

    assert started.flow_id == "fake-flow"
    assert started.flow_type == ProviderAuthFlowType.DEVICE_CODE
    assert first.status == ProviderAuthStatus.PENDING
    assert second.status == ProviderAuthStatus.AUTHENTICATED


async def test_callback_saves_credential_and_status_exposes_no_token(
    tmp_path: Path,
) -> None:
    registry = ProviderAuthRegistry()
    registry.register(FakeAuthAdapter())
    store = OAuthCredentialStore(tmp_path / "providers")
    manager = ProviderAuthManager(
        FakeProviderManager(
            {
                "oauth": _provider(
                    "oauth",
                    auth_type=ProviderAuthType.OAUTH_DEVICE_CODE,
                ),
            },
        ),
        credential_store=store,
        registry=registry,
    )

    callback_status = await manager.handle_callback(
        "oauth",
        state="state",
        code="code",
    )
    stored = store.load("oauth", "custom")
    status = await manager.get_status("oauth")
    status_payload = status.model_dump()

    assert callback_status.status == ProviderAuthStatus.AUTHENTICATED
    assert stored is not None
    assert stored.access_token == "oauth-access-token"
    assert status.status == ProviderAuthStatus.AUTHENTICATED
    assert status.account_label == "octocat"
    assert "access_token" not in status_payload
    assert "refresh_token" not in status_payload


async def test_callback_saves_credential_in_provider_storage_bucket(
    tmp_path: Path,
) -> None:
    registry = ProviderAuthRegistry()
    registry.register(FakeAuthAdapter())
    store = OAuthCredentialStore(tmp_path / "providers")
    manager = ProviderAuthManager(
        FakeProviderManager(
            {
                "oauth": _provider(
                    "oauth",
                    auth_type=ProviderAuthType.OAUTH_DEVICE_CODE,
                ),
            },
            storage_types={"oauth": "builtin"},
        ),
        credential_store=store,
        registry=registry,
    )

    await manager.handle_callback("oauth", state="state", code="code")

    assert store.load("oauth", "builtin") is not None
    assert store.load("oauth", "custom") is None


async def test_logout_deletes_credential(tmp_path: Path) -> None:
    adapter = FakeAuthAdapter()
    registry = ProviderAuthRegistry()
    registry.register(adapter)
    store = OAuthCredentialStore(tmp_path / "providers")
    provider = _provider("oauth", auth_type=ProviderAuthType.OAUTH_DEVICE_CODE)
    store.save(
        OAuthCredential(
            provider_id="oauth",
            access_token="oauth-access-token",
            created_at=1760000000,
            updated_at=1760000001,
        ),
        "custom",
    )
    manager = ProviderAuthManager(
        FakeProviderManager({"oauth": provider}),
        credential_store=store,
        registry=registry,
    )

    status = await manager.logout("oauth")

    assert adapter.logout_called is True
    assert status.status == ProviderAuthStatus.NOT_CONFIGURED
    assert store.load("oauth", "custom") is None
