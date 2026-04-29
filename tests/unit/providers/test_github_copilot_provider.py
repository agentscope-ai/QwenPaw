# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for GitHubCopilotProvider."""
from __future__ import annotations

from pathlib import Path

import pytest

import qwenpaw.constant as constant_module
from qwenpaw.providers.github_copilot_provider import (
    GITHUB_COPILOT_MODELS,
    GitHubCopilotProvider,
    PROVIDER_GITHUB_COPILOT,
)
from qwenpaw.providers.oauth.copilot_oauth_service import (
    reset_oauth_services_for_test,
)


@pytest.fixture(autouse=True)
def _isolated_oauth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(constant_module, "SECRET_DIR", tmp_path)
    reset_oauth_services_for_test()


def _make_provider() -> GitHubCopilotProvider:
    return GitHubCopilotProvider(
        id="github-copilot",
        name="GitHub Copilot",
        base_url="https://api.githubcopilot.com",
        chat_model="OpenAIChatModel",
        require_api_key=False,
        freeze_url=True,
        auth_type="oauth_device_code",
        models=list(GITHUB_COPILOT_MODELS),
    )


def test_default_provider_metadata() -> None:
    p = PROVIDER_GITHUB_COPILOT
    assert p.id == "github-copilot"
    assert p.auth_type == "oauth_device_code"
    assert p.require_api_key is False
    assert p.freeze_url is True
    assert p.support_model_discovery is True
    assert len(p.models) >= 5  # static catalog is non-empty


async def test_check_connection_unauthenticated_returns_false() -> None:
    provider = _make_provider()
    ok, msg = await provider.check_connection()
    assert ok is False
    assert "not authenticated" in msg.lower()


async def test_get_info_reflects_unauthenticated_state() -> None:
    provider = _make_provider()
    info = await provider.get_info()
    assert info.auth_type == "oauth_device_code"
    assert info.is_authenticated is False
    assert info.oauth_user_login == ""
    assert info.require_api_key is False


async def test_get_info_reflects_authenticated_state() -> None:
    provider = _make_provider()
    # Inject token directly into the OAuth service
    provider.oauth_access_token = "gho_x"
    provider.oauth_user_login = "alice"
    service = provider._service()  # noqa: SLF001
    service._oauth_access_token = "gho_x"  # noqa: SLF001
    service._github_login = "alice"  # noqa: SLF001

    info = await provider.get_info()
    assert info.is_authenticated is True
    assert info.oauth_user_login == "alice"


async def test_fetch_models_returns_static_catalog_when_unauth() -> None:
    provider = _make_provider()
    models = await provider.fetch_models()
    ids = [m.id for m in models]
    assert "gpt-4o" in ids
    assert "claude-sonnet-4" in ids


async def test_probe_multimodal_uses_documented_capability() -> None:
    provider = _make_provider()
    # gpt-4o is documented as image-capable in the static catalog.
    result = await provider.probe_model_multimodal("gpt-4o")
    assert result.supports_image is True
    assert result.supports_video is False
    # Unknown model → empty (not an error).
    result_unknown = await provider.probe_model_multimodal("unknown-xyz")
    assert result_unknown.supports_image is False
    assert result_unknown.supports_video is False


async def test_get_chat_model_instance_injects_copilot_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    # Authenticate so the service has a token
    provider.oauth_access_token = "gho_x"
    service = provider._service()  # noqa: SLF001
    service._oauth_access_token = "gho_x"  # noqa: SLF001

    captured: dict = {}

    class _StubChatModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "qwenpaw.providers.openai_chat_model_compat.OpenAIChatModelCompat",
        _StubChatModel,
    )
    instance = provider.get_chat_model_instance("gpt-4o")
    assert instance is not None
    client_kwargs = captured["client_kwargs"]
    assert "http_client" in client_kwargs
    http_client = client_kwargs["http_client"]
    # The httpx client must carry the Copilot-specific default headers.
    assert http_client.headers.get("editor-version") is not None
    assert http_client.headers.get("copilot-integration-id") == "vscode-chat"
    assert http_client.headers.get("openai-intent") == "conversation-panel"


async def test_service_factory_seeds_from_token_store_first() -> None:
    """``_service()`` should prefer the encrypted ``CopilotTokenStore``
    over the (legacy) provider-config ``oauth_access_token`` field so
    the token store remains the single source of truth.
    """
    from qwenpaw.providers.oauth.copilot_token_store import CopilotTokenStore

    # Plant a credential in the encrypted store before the service exists.
    CopilotTokenStore("github-copilot").save("gho_from_store", "store-user")

    provider = _make_provider()
    # Provider-config field intentionally diverges to prove precedence.
    provider.oauth_access_token = "gho_from_config"
    provider.oauth_user_login = "config-user"

    service = provider._service()  # noqa: SLF001
    assert service.is_authenticated
    assert service.oauth_access_token == "gho_from_store"
    assert service.github_login == "store-user"


async def test_service_factory_falls_back_to_provider_config() -> None:
    """When the token store is empty (e.g. installs upgraded from an
    earlier release), the factory must still rehydrate the service
    from the legacy provider-config fields for backwards compatibility.
    """
    provider = _make_provider()
    provider.oauth_access_token = "gho_legacy"
    provider.oauth_user_login = "legacy-user"

    service = provider._service()  # noqa: SLF001
    assert service.is_authenticated
    assert service.oauth_access_token == "gho_legacy"
    assert service.github_login == "legacy-user"


async def test_service_factory_runs_only_once_per_provider() -> None:
    """The process-global registry must hand back the *same* service
    instance for repeated calls so the shared httpx client and OAuth
    state are not duplicated.
    """
    provider = _make_provider()
    s1 = provider._service()  # noqa: SLF001
    s2 = provider._service()  # noqa: SLF001
    assert s1 is s2


async def test_client_reuses_shared_http_client() -> None:
    """Repeated ``_client()`` calls must reuse the OAuth service's
    shared ``httpx.AsyncClient`` so we never leak sockets across
    discovery / connection-check invocations.
    """
    provider = _make_provider()
    provider.oauth_access_token = "gho_x"
    service = provider._service()  # noqa: SLF001
    service._oauth_access_token = "gho_x"  # noqa: SLF001

    client_a = provider._client()  # noqa: SLF001
    client_b = provider._client()  # noqa: SLF001
    # AsyncOpenAI exposes its underlying httpx client as ``_client``.
    assert client_a._client is client_b._client  # noqa: SLF001
    assert (
        client_a._client is service.get_or_create_http_client()
    )  # noqa: SLF001
    await service.aclose_http_client()
