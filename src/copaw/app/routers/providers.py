# -*- coding: utf-8 -*-
"""API routes for LLM providers and models."""

from __future__ import annotations

import logging
import os
from typing import List, Optional

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
logger = logging.getLogger(__name__)


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)


class ModelSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Provider to use")
    model: str = Field(..., description="Model identifier")


class CreateCustomProviderRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
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
    )


@router.get(
    "",
    response_model=List[ProviderInfo],
    summary="List all providers",
)
async def list_all_providers() -> List[ProviderInfo]:
    # Keep startup health checks read-only: don't rewrite providers.json
    # when desktop app probes /api/models for readiness.
    is_desktop_app = os.environ.get("COPAW_DESKTOP_APP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    data = load_providers_json(
        persist=False,
        sync_runtime_models=not is_desktop_app,
    )
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
        logger.warning("Provider config update rejected: unknown provider '%s'", provider_id)
        raise HTTPException(404, detail=f"Provider '{provider_id}' not found")

    # Allow base_url for custom providers, providers without a default
    # base URL (e.g. Azure OpenAI), and Ollama (user may override).
    allow_base_url = (
        provider.is_custom
        or not provider.default_base_url
        or provider.id == "ollama"
    )
    logger.info(
        "Provider config update requested: provider=%s api_key_input=%s base_url_input=%s",
        provider_id,
        body.api_key is not None,
        body.base_url is not None,
    )
    base_url = body.base_url if allow_base_url else None
    try:
        data = update_provider_settings(
            provider_id,
            api_key=body.api_key,
            base_url=base_url,
        )
    except Exception:
        logger.exception(
            "Provider config update failed: provider=%s",
            provider_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to save provider configuration.",
        )

    info = _build_provider_info(provider, data)
    logger.info(
        "Provider config updated: provider=%s api_key_set=%s base_url_set=%s",
        provider_id,
        bool(info.current_api_key),
        bool(info.current_base_url),
    )
    return info


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


class TestModelRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to test")


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
        )
        return TestConnectionResponse(**result)
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
    logger.info(
        "Active LLM update requested: provider=%s model=%s",
        body.provider_id,
        body.model,
    )
    provider = get_provider(body.provider_id)
    if provider is None:
        logger.warning(
            "Active LLM update rejected: unknown provider '%s'",
            body.provider_id,
        )
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
            logger.warning(
                "Active LLM update rejected: provider not configured: provider=%s",
                body.provider_id,
            )
            raise HTTPException(status_code=400, detail=msg)
    # Local providers (llama.cpp, mlx) don't need validation

    if not body.model:
        logger.warning(
            "Active LLM update rejected: empty model for provider=%s",
            body.provider_id,
        )
        raise HTTPException(status_code=400, detail="Model is required.")

    try:
        data = set_active_llm(body.provider_id, body.model)
    except Exception:
        logger.exception(
            "Active LLM update failed during persistence: provider=%s model=%s",
            body.provider_id,
            body.model,
        )
        raise HTTPException(status_code=500, detail="Failed to save active LLM.")

    logger.info(
        "Active LLM updated: provider=%s model=%s",
        body.provider_id,
        body.model,
    )
    return ActiveModelsInfo(active_llm=data.active_llm)
