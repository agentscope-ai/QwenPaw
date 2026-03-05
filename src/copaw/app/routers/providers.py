# -*- coding: utf-8 -*-
"""API routes for LLM providers and models."""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

from ...providers import (
    ActiveModelsInfo,
    ModelInfo,
    ProviderDefinition,
    ProviderInfo,
    ProvidersData,
    add_model,
    create_custom_provider,
    delete_custom_provider,
    discover_provider_models,
    get_provider,
    list_providers,
    load_providers_json,
    mask_api_key,
    remove_model,
    set_active_llm,
    test_model_connection,
    test_provider_connection,
    update_provider_settings,
)

router = APIRouter(prefix="/models", tags=["models"])

ChatModelName = Literal["OpenAIChatModel", "AnthropicChatModel"]


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Chat model class name for protocol selection",
    )


class ModelSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Provider to use")
    model: str = Field(..., description="Model identifier")


class CreateCustomProviderRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
    chat_model: ChatModelName = Field(default="OpenAIChatModel")
    models: List[ModelInfo] = Field(default_factory=list)


class AddModelRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)


def _build_provider_info(
    provider: ProviderDefinition,
    data: ProvidersData,
) -> ProviderInfo:
    if provider.is_local:
        return ProviderInfo(
            id=provider.id,
            name=provider.name,
            api_key_prefix="",
            models=list(provider.models),
            extra_models=[],
            is_custom=False,
            is_local=True,
            current_api_key="",
            current_base_url="",
            chat_model="OpenAIChatModel",
        )

    cur_base_url, cur_api_key = data.get_credentials(provider.id)

    settings = data.providers.get(provider.id)
    extra = (
        list(settings.extra_models)
        if settings and not provider.is_custom
        else []
    )

    return ProviderInfo(
        id=provider.id,
        name=provider.name,
        api_key_prefix=provider.api_key_prefix,
        models=list(provider.models) + extra,
        extra_models=extra,
        is_custom=provider.is_custom,
        is_local=provider.is_local,
        needs_base_url=provider.is_custom or not provider.default_base_url,
        current_api_key=mask_api_key(cur_api_key),
        current_base_url=cur_base_url,
        chat_model=provider.chat_model,
    )


@router.get(
    "",
    response_model=List[ProviderInfo],
    summary="List all providers",
)
async def list_all_providers() -> List[ProviderInfo]:
    data = load_providers_json()
    return [_build_provider_info(p, data) for p in list_providers()]


@router.put(
    "/{provider_id}/config",
    response_model=ProviderInfo,
    summary="Configure a provider",
)
async def configure_provider(
    provider_id: str = Path(...),
    body: ProviderConfigRequest = Body(...),
) -> ProviderInfo:
    provider = get_provider(provider_id)
    if provider is None:
        raise HTTPException(404, detail=f"Provider '{provider_id}' not found")

    # Allow base_url for custom providers, providers without a default
    # base URL (e.g. Azure OpenAI), and Ollama (user may override).
    allow_base_url = (
        provider.is_custom
        or not provider.default_base_url
        or provider.id == "ollama"
    )
    base_url = body.base_url if allow_base_url else None
    try:
        data = update_provider_settings(
            provider_id,
            api_key=body.api_key,
            base_url=base_url,
            chat_model=body.chat_model if provider.is_custom else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated_provider = get_provider(provider_id)
    assert updated_provider is not None
    return _build_provider_info(updated_provider, data)


@router.post(
    "/custom-providers",
    response_model=ProviderInfo,
    summary="Create a custom provider",
    status_code=201,
)
async def create_custom_provider_endpoint(
    body: CreateCustomProviderRequest = Body(...),
) -> ProviderInfo:
    try:
        data = create_custom_provider(
            provider_id=body.id,
            name=body.name,
            default_base_url=body.default_base_url,
            api_key_prefix=body.api_key_prefix,
            chat_model=body.chat_model,
            models=body.models,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    provider = get_provider(body.id)
    assert provider is not None
    return _build_provider_info(provider, data)


class TestConnectionResponse(BaseModel):
    success: bool = Field(..., description="Whether the test passed")
    message: str = Field(..., description="Human-readable result message")


class TestProviderRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to test",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to test",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to test protocol behavior",
    )


class TestModelRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to test")


class DiscoverModelsRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to use for discovery",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to use for discovery",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to use for discovery",
    )


class DiscoverModelsResponse(BaseModel):
    success: bool = Field(..., description="Whether discovery succeeded")
    message: str = Field(..., description="Human-readable result message")
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="Discovered models",
    )
    added_count: int = Field(
        default=0,
        description="How many new models were added into provider config",
    )


@router.post(
    "/{provider_id}/test",
    response_model=TestConnectionResponse,
    summary="Test provider connection",
)
async def test_provider(
    provider_id: str = Path(...),
    body: Optional[TestProviderRequest] = Body(default=None),
) -> TestConnectionResponse:
    """Test if a provider's URL and API key are valid."""
    try:
        api_key = body.api_key if body else None
        base_url = body.base_url if body else None
        result = await test_provider_connection(
            provider_id,
            api_key=api_key,
            base_url=base_url,
            chat_model=body.chat_model if body else None,
        )
        return TestConnectionResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/discover",
    response_model=DiscoverModelsResponse,
    summary="Discover available models from provider",
)
async def discover_models(
    provider_id: str = Path(...),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
) -> DiscoverModelsResponse:
    try:
        result = await discover_provider_models(
            provider_id,
            api_key=body.api_key if body else None,
            base_url=body.base_url if body else None,
            chat_model=body.chat_model if body else None,
        )
        return DiscoverModelsResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/models/test",
    response_model=TestConnectionResponse,
    summary="Test a specific model",
)
async def test_model(
    provider_id: str = Path(...),
    body: TestModelRequest = Body(...),
) -> TestConnectionResponse:
    """Test if a specific model works with the configured provider."""
    try:
        result = await test_model_connection(provider_id, body.model_id)
        return TestConnectionResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/custom-providers/{provider_id}",
    response_model=List[ProviderInfo],
    summary="Delete a custom provider",
)
async def delete_custom_provider_endpoint(
    provider_id: str = Path(...),
) -> List[ProviderInfo]:
    try:
        data = delete_custom_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_build_provider_info(p, data) for p in list_providers()]


@router.post(
    "/{provider_id}/models",
    response_model=ProviderInfo,
    summary="Add a model to a provider",
    status_code=201,
)
async def add_model_endpoint(
    provider_id: str = Path(...),
    body: AddModelRequest = Body(...),
) -> ProviderInfo:
    try:
        data = add_model(provider_id, ModelInfo(id=body.id, name=body.name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider = get_provider(provider_id)
    assert provider is not None
    return _build_provider_info(provider, data)


@router.delete(
    "/{provider_id}/models/{model_id:path}",
    response_model=ProviderInfo,
    summary="Remove a model from a provider",
)
async def remove_model_endpoint(
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProviderInfo:
    try:
        data = remove_model(provider_id, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider = get_provider(provider_id)
    assert provider is not None
    return _build_provider_info(provider, data)


@router.get(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Get active LLM",
)
async def get_active_models() -> ActiveModelsInfo:
    data = load_providers_json()
    return ActiveModelsInfo(active_llm=data.active_llm)


@router.put(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Set active LLM",
)
async def set_active_model(
    body: ModelSlotRequest = Body(...),
) -> ActiveModelsInfo:
    provider = get_provider(body.provider_id)
    if provider is None:
        raise HTTPException(
            404,
            detail=f"Provider '{body.provider_id}' not found",
        )

    data = load_providers_json()
    base_url, api_key = data.get_credentials(provider.id)

    # Validation based on provider type
    if provider.is_custom:
        # Custom providers need base_url
        if not base_url:
            msg = (
                f"Provider '{provider.name}' has no base_url configured. "
                "Please configure the base URL first."
            )
            raise HTTPException(status_code=400, detail=msg)
    elif provider.id == "ollama":
        # Ollama needs base_url to connect to daemon
        if not base_url:
            msg = (
                f"Provider '{provider.name}' has no base_url configured. "
                "Please configure the base URL first."
            )
            raise HTTPException(status_code=400, detail=msg)
    elif not provider.is_local:
        # Built-in remote providers (modelscope, dashscope, etc.) need API key
        if not api_key:
            msg = (
                f"Provider '{provider.name}' has no API key configured. "
                "Please configure the API key first."
            )
            raise HTTPException(status_code=400, detail=msg)
    # Local providers (llama.cpp, mlx) don't need validation

    if not body.model:
        raise HTTPException(status_code=400, detail="Model is required.")

    data = set_active_llm(body.provider_id, body.model)
    return ActiveModelsInfo(active_llm=data.active_llm)
