# -*- coding: utf-8 -*-
"""API routes for LLM providers and models."""

from __future__ import annotations

from typing import List, Literal, Optional
from copy import deepcopy

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ...providers.provider import ProviderInfo, ModelInfo
from ...providers.provider_manager import ActiveModelsInfo, ProviderManager

router = APIRouter(prefix="/models", tags=["models"])

ChatModelName = Literal["OpenAIChatModel", "AnthropicChatModel"]


def get_provider_manager(request: Request) -> ProviderManager:
    """Get the provider manager from app state.

    Args:
        request: FastAPI request object
    """
    provider_manager = getattr(request.app.state, "provider_manager", None)
    if provider_manager is None:
        provider_manager = ProviderManager.get_instance()
    return provider_manager


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Chat model class name for protocol selection",
    )
    generate_kwargs: Optional[dict] = Field(
        default_factory=dict,
        description=(
            "Configuration in json format, will be expanded "
            "and passed to generation calls "
            "(e.g., openai.chat.completions, anthropic.messages)."
        ),
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


@router.get(
    "",
    response_model=List[ProviderInfo],
    summary="List all providers",
)
async def list_all_providers(
    manager: ProviderManager = Depends(get_provider_manager),
) -> List[ProviderInfo]:
    return await manager.list_provider_info()


@router.put(
    "/{provider_id}/config",
    response_model=ProviderInfo,
    summary="Configure a provider",
)
async def configure_provider(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: ProviderConfigRequest = Body(...),
) -> ProviderInfo:
    ok = manager.update_provider(
        provider_id,
        {
            "api_key": body.api_key,
            "base_url": body.base_url,
            "chat_model": body.chat_model,
            "generate_kwargs": body.generate_kwargs,
        },
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found",
        )

    provider_info = await manager.get_provider_info(provider_id)
    if provider_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found after update",
        )
    return provider_info


@router.post(
    "/custom-providers",
    response_model=ProviderInfo,
    summary="Create a custom provider",
    status_code=201,
)
async def create_custom_provider_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    body: CreateCustomProviderRequest = Body(...),
) -> ProviderInfo:
    try:
        provider_info = await manager.add_custom_provider(
            ProviderInfo(
                id=body.id,
                name=body.name,
                base_url=body.default_base_url,
                api_key_prefix=body.api_key_prefix,
                chat_model=body.chat_model,
                extra_models=body.models,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider_info


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
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="Discovered models",
    )
    message: str = Field(
        default="",
        description="Human-readable result message",
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
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[TestProviderRequest] = Body(default=None),
) -> TestConnectionResponse:
    """Test if a provider's URL and API key are valid."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        # Ensure we don't accidentally modify provider config during test
        tmp_provider = deepcopy(provider)
        if body and body.api_key:
            tmp_provider.api_key = body.api_key
        if body and body.base_url:
            tmp_provider.base_url = body.base_url
        ok, msg = await tmp_provider.check_connection()
        return TestConnectionResponse(
            success=ok,
            message="Connection successful"
            if ok
            else f"Connection failed: {msg}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/discover",
    response_model=DiscoverModelsResponse,
    summary="Discover available models from provider",
)
async def discover_models(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
) -> DiscoverModelsResponse:
    try:
        ok = manager.update_provider(
            provider_id,
            {
                "api_key": body.api_key if body else None,
                "base_url": body.base_url if body else None,
            },
        )
        if not ok:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )
        try:
            result = await manager.fetch_provider_models(
                provider_id,
            )
            success = True
        except Exception:
            result = []
            success = False
        return DiscoverModelsResponse(success=success, models=result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/models/test",
    response_model=TestConnectionResponse,
    summary="Test a specific model",
)
async def test_model(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: TestModelRequest = Body(...),
) -> TestConnectionResponse:
    """Test if a specific model works with the configured provider."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        ok, msg = await provider.check_model_connection(model_id=body.model_id)
        return TestConnectionResponse(
            success=ok,
            message=(
                "Model connection successful"
                if ok
                else f"Model connection failed: {msg}"
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/custom-providers/{provider_id}",
    response_model=List[ProviderInfo],
    summary="Delete a custom provider",
)
async def delete_custom_provider_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
) -> List[ProviderInfo]:
    try:
        ok = manager.remove_custom_provider(provider_id)
        if not ok:
            raise ValueError(f"Custom Provider '{provider_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await manager.list_provider_info()


@router.post(
    "/{provider_id}/models",
    response_model=ProviderInfo,
    summary="Add a model to a provider",
    status_code=201,
)
async def add_model_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: AddModelRequest = Body(...),
) -> ProviderInfo:
    try:
        provider = await manager.add_model_to_provider(
            provider_id=provider_id,
            model_info=ModelInfo(id=body.id, name=body.name),
        )  # Validate provider exists and add model
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider


@router.delete(
    "/{provider_id}/models/{model_id:path}",
    response_model=ProviderInfo,
    summary="Remove a model from a provider",
)
async def remove_model_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProviderInfo:
    try:
        provider = await manager.delete_model_from_provider(
            provider_id=provider_id,
            model_id=model_id,
        )  # Validate provider and model exist and delete
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return provider


@router.get(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Get active LLM",
)
async def get_active_models(
    manager: ProviderManager = Depends(get_provider_manager),
) -> ActiveModelsInfo:
    return ActiveModelsInfo(active_llm=manager.get_active_model())


@router.put(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Set active LLM",
)
async def set_active_model(
    manager: ProviderManager = Depends(get_provider_manager),
    body: ModelSlotRequest = Body(...),
) -> ActiveModelsInfo:
    try:
        await manager.activate_model(body.provider_id, body.model)
    except ValueError as exc:
        message = str(exc)
        lower_msg = message.lower()
        if "provider" in lower_msg and "not found" in lower_msg:
            # Missing provider
            raise HTTPException(status_code=404, detail=message) from exc
        # Invalid model, unreachable provider, or other configuration error
        raise HTTPException(status_code=400, detail=message) from exc
    return ActiveModelsInfo(active_llm=manager.get_active_model())
