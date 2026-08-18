# -*- coding: utf-8 -*-
"""Route tests for provider model discovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from pydantic import ValidationError

from qwenpaw.app.routers.providers import (
    CreateCustomProviderRequest,
    DiscoverModelsRequest,
    ProviderConfigRequest,
    TestProviderRequest,
    configure_provider,
    discover_models,
    test_provider as provider_connection_endpoint,
    test_model as model_test_endpoint,
)
from qwenpaw.providers.provider import ModelInfo, ProviderInfo


@pytest.mark.parametrize(
    "provider_id",
    [
        "../escape",
        "team/provider",
        r"team\provider",
        "CON",
        "nul.json",
        "provider.",
        "provider name",
    ],
)
def test_custom_provider_request_rejects_unsafe_id(
    provider_id: str,
) -> None:
    with pytest.raises(ValidationError):
        CreateCustomProviderRequest(id=provider_id, name="Unsafe")


async def test_configure_provider_schedules_model_discovery() -> None:
    provider = SimpleNamespace(
        support_model_discovery=True,
        api_key="sk-test",
        require_api_key=True,
        models_syncing=False,
    )
    manager = MagicMock()
    manager.update_provider_async = AsyncMock(return_value=True)
    manager.get_provider.return_value = provider
    manager.get_provider_info = AsyncMock(
        return_value=ProviderInfo(id="openai", name="OpenAI"),
    )
    manager.discover_provider_models = AsyncMock()
    tasks = BackgroundTasks()

    result = await configure_provider(
        background_tasks=tasks,
        manager=manager,
        provider_id="openai",
        body=ProviderConfigRequest(api_key="sk-test"),
    )

    assert result.id == "openai"
    manager.update_provider_async.assert_awaited_once_with(
        "openai",
        {
            "api_key": "sk-test",
            "base_url": None,
            "chat_model": None,
            "generate_kwargs": {},
            "custom_headers": None,
            "auth_mode": None,
        },
    )
    assert len(tasks.tasks) == 1
    assert provider.models_syncing is False
    task = tasks.tasks[0]
    assert task.func == manager.discover_provider_models
    assert task.args == ("openai",)
    assert task.kwargs == {"save": True}


async def test_discover_route_returns_sync_status() -> None:
    manager = MagicMock()
    manager.get_provider.return_value = SimpleNamespace()
    manager.update_provider_async = AsyncMock(return_value=True)
    manager.discover_provider_models = AsyncMock(
        return_value=SimpleNamespace(
            success=False,
            models=[ModelInfo(id="cached", name="Cached")],
            discovered_count=0,
            last_synced_at="2026-07-17T00:00:00+00:00",
            used_static_fallback=True,
            error="upstream unavailable",
            error_kind="provider_unavailable",
        ),
    )

    result = await discover_models(
        manager=manager,
        provider_id="openai",
        body=None,
        save=True,
    )

    assert result.success is False
    assert result.used_static_fallback is True
    assert result.last_synced_at == "2026-07-17T00:00:00+00:00"
    assert result.message == "upstream unavailable"
    assert result.error_kind == "provider_unavailable"
    assert [model.id for model in result.models] == ["cached"]


async def test_discover_preview_does_not_persist_credentials() -> None:
    provider = MagicMock()
    provider.model_copy.return_value = provider
    manager = MagicMock()
    manager.get_provider.return_value = provider
    manager.materialize_discovery_provider.return_value = provider
    manager.discover_provider_models = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            models=[],
            discovered_count=0,
            last_synced_at=None,
            used_static_fallback=False,
            error=None,
            error_kind=None,
        ),
    )

    await discover_models(
        manager=manager,
        provider_id="openai",
        body=DiscoverModelsRequest(
            api_key="preview-key",
            chat_model="AnthropicChatModel",
        ),
        save=False,
    )

    manager.update_provider.assert_not_called()
    manager.update_provider_async.assert_not_called()
    manager.materialize_discovery_provider.assert_called_once_with(
        "openai",
        {
            "api_key": "preview-key",
            "base_url": None,
            "chat_model": "AnthropicChatModel",
        },
    )
    manager.discover_provider_models.assert_awaited_once_with(
        "openai",
        save=False,
        provider_override=provider,
    )


@pytest.mark.parametrize(
    "chat_model",
    [
        "OpenAIChatModel",
        "OpenAIResponseModel",
        "AnthropicChatModel",
        "GeminiChatModel",
    ],
)
async def test_discover_save_persists_protocol_override(
    chat_model: str,
) -> None:
    """Persist the selected protocol before saved discovery runs."""
    manager = MagicMock()
    manager.get_provider.return_value = SimpleNamespace()
    manager.update_provider_async = AsyncMock(return_value=True)
    manager.discover_provider_models = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            models=[],
            discovered_count=0,
            last_synced_at=None,
            used_static_fallback=False,
            error=None,
            error_kind=None,
        ),
    )

    await discover_models(
        manager=manager,
        provider_id="custom-provider",
        body=DiscoverModelsRequest(
            base_url="https://example.test/v1",
            chat_model=chat_model,
        ),
        save=True,
    )

    manager.update_provider_async.assert_awaited_once_with(
        "custom-provider",
        {
            "api_key": None,
            "base_url": "https://example.test/v1",
            "chat_model": chat_model,
        },
    )
    manager.discover_provider_models.assert_awaited_once_with(
        "custom-provider",
        save=True,
        provider_override=manager.materialize_discovery_provider.return_value,
    )


async def test_model_route_returns_structured_availability() -> None:
    manager = MagicMock()
    manager.get_provider.return_value = SimpleNamespace()
    manager.check_provider_model = AsyncMock(
        return_value=SimpleNamespace(
            success=False,
            status="permission_denied",
            message="status=401: unauthorized",
            http_status=401,
            retryable=False,
            checked_at="2026-07-21T00:00:00+00:00",
            verification="live",
        ),
    )

    result = await model_test_endpoint(
        manager=manager,
        provider_id="modelscope",
        body=SimpleNamespace(model_id="org/model"),
    )

    assert result.success is False
    assert result.status == "permission_denied"
    assert result.http_status == 401
    assert result.retryable is False
    assert result.verification == "live"
    manager.check_provider_model.assert_awaited_once_with(
        "modelscope",
        "org/model",
    )


@pytest.mark.parametrize(
    "chat_model",
    [
        "OpenAIChatModel",
        "OpenAIResponseModel",
        "AnthropicChatModel",
        "GeminiChatModel",
    ],
)
async def test_connection_preserves_protocol_override(
    chat_model: str,
) -> None:
    """Connection tests must use the requested protocol temporarily."""
    provider = MagicMock()
    provider.model_copy.return_value = provider
    provider.check_connection = AsyncMock(return_value=(True, ""))
    manager = MagicMock()
    manager.get_provider.return_value = provider

    result = await provider_connection_endpoint(
        manager=manager,
        provider_id="custom-provider",
        body=TestProviderRequest(chat_model=chat_model),
    )

    assert result.success is True
    provider.model_copy.assert_called_once_with(
        update={"chat_model": chat_model},
    )
