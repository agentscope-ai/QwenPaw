# -*- coding: utf-8 -*-

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.app.routers.providers import (
    ProviderConfigRequest,
    configure_provider,
)
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import ProviderManager


@pytest.fixture
def provider_manager(monkeypatch, tmp_path) -> ProviderManager:
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return ProviderManager()


def test_provider_config_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        ProviderConfigRequest(name="   ")


async def test_configure_provider_renames_custom_provider(
    provider_manager: ProviderManager,
) -> None:
    await provider_manager.add_custom_provider(
        OpenAIProvider(
            id="custom-openai",
            name="Custom OpenAI",
        ),
    )

    updated = await configure_provider(
        manager=provider_manager,
        provider_id="custom-openai",
        body=ProviderConfigRequest(name="Renamed Provider"),
    )

    assert updated.id == "custom-openai"
    assert updated.name == "Renamed Provider"
    reloaded = ProviderManager()
    provider = reloaded.get_provider("custom-openai")
    assert provider is not None
    assert provider.name == "Renamed Provider"


async def test_configure_provider_rejects_builtin_rename(
    provider_manager: ProviderManager,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await configure_provider(
            manager=provider_manager,
            provider_id="openai",
            body=ProviderConfigRequest(name="Renamed OpenAI"),
        )

    assert exc_info.value.status_code == 400
    provider = provider_manager.get_provider("openai")
    assert provider is not None
    assert provider.name == "OpenAI"
