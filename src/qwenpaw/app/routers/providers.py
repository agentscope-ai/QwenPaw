# -*- coding: utf-8 -*-
"""API routes for LLM providers and models."""

from __future__ import annotations

import logging
from typing import Dict, List, Literal, Optional
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)
from pydantic import BaseModel, Field, field_validator

from qwenpaw.exceptions import (
    AppBaseException,
)

from ..agent_context import get_agent_for_request
from ..utils import schedule_agent_reload
from ...config.config import (
    AgentProfileConfig,
    load_agent_config,
    update_agent_config_async,
)
from ...providers.provider import (
    ModelInfo,
    ProviderInfo,
    validate_custom_provider_id,
)
from ...config.config import ActiveModelsInfo
from ...providers.provider_manager import ProviderManager
from ...utils.io_utils import run_sync_io
from ...utils.logging import sanitize_log_value
from ...providers.openrouter_provider import OpenRouterProvider
from ...config.config import ModelSlotConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

ChatModelName = Literal[
    "OpenAIChatModel",
    "OpenAIResponseModel",
    "AnthropicChatModel",
    "GeminiChatModel",
    "DashScopeChatModel",
]

# effective: agent-specific if set, otherwise global
# global: the global model only, ignoring any agent-specific setting
# agent: a specific agent's model only, error if not set
ActiveModelReadScope = Literal["effective", "global", "agent"]
ActiveModelWriteScope = Literal["global", "agent"]
ModelAvailabilityStatus = Literal[
    "available",
    "permission_denied",
    "model_not_found",
    "incompatible_api",
    "rate_limited",
    "transient_error",
    "unverified",
]


async def get_provider_manager(request: Request) -> ProviderManager:
    """Get the provider manager from app state.

    Args:
        request: FastAPI request object
    """
    return request.app.state.provider_manager


def _active_models_info(
    manager: ProviderManager,
    active_llm: ModelSlotConfig | None,
) -> ActiveModelsInfo:
    """Build active-model metadata using the runtime context resolver."""
    effective_max_input_length = None
    if active_llm and active_llm.provider_id and active_llm.model:
        provider = manager.get_provider(active_llm.provider_id)
        if provider is not None:
            effective_max_input_length = provider.get_context_size(
                active_llm.model,
            )
    return ActiveModelsInfo(
        active_llm=active_llm,
        effective_max_input_length=effective_max_input_length,
    )


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    name: Optional[str] = Field(
        default=None,
        description=("New display name. Only applied to custom providers."),
    )
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
    custom_headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom HTTP headers to include in every API request.",
    )
    auth_mode: Optional[Literal["api_key", "auth_token"]] = Field(
        default=None,
        description=(
            "Authentication mode: 'api_key' or 'auth_token'. "
            "Only applies to Anthropic-compatible providers."
        ),
    )
    auto_discover: bool = Field(
        default=True,
        description="Discover models after saving a supported provider",
    )


def _should_auto_discover(
    body: ProviderConfigRequest,
    provider: object | None,
) -> bool:
    """Return whether a saved provider should start discovery."""
    if not body.auto_discover or provider is None:
        return False
    if not getattr(provider, "support_model_discovery", False):
        return False
    api_key = getattr(provider, "api_key", None)
    require_api_key = getattr(provider, "require_api_key", True)
    return bool(api_key or not require_api_key)


class ModelSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Provider to use")
    model: str = Field(..., description="Model identifier")
    scope: ActiveModelWriteScope = Field(
        ...,
        description="Whether to update the global model or a specific agent",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Target agent ID when scope is 'agent'",
    )


class CreateCustomProviderRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
    chat_model: ChatModelName = Field(default="OpenAIChatModel")
    models: List[ModelInfo] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        """Reject IDs that are unsafe as cross-platform file names."""
        return validate_custom_provider_id(value)


class AddModelRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    is_free: bool = Field(
        default=False,
        description="Whether this model is free to use",
    )
    supports_multimodal: Optional[bool] = Field(
        default=None,
        description="Whether the model supports multimodal input",
    )
    supports_image: Optional[bool] = Field(
        default=None,
        description="Whether the model supports image input",
    )
    supports_video: Optional[bool] = Field(
        default=None,
        description="Whether the model supports video input",
    )
    probe_source: Optional[str] = Field(
        default=None,
        description="Source of capability metadata",
    )


class ModelConfigRequest(BaseModel):
    max_tokens: Optional[int] = Field(
        default=None,
        description="Maximum output tokens per response.",
    )
    max_input_length: Optional[int] = Field(
        default=None,
        description="Maximum input context window size (tokens).",
    )
    generate_kwargs: Optional[dict] = Field(
        default_factory=dict,
        description=(
            "Per-model generation parameters in JSON format. "
            "These override provider-level generate_kwargs."
        ),
    )
    relay_reasoning: Optional[bool] = Field(
        default=None,
        description="Whether to relay reasoning_content in subsequent turns.",
    )
    thinking_enabled: Optional[bool] = Field(
        default=None,
        description="Enable/disable thinking for this model.",
    )
    thinking_budget: Optional[int] = Field(
        default=None,
        description="Token budget for thinking.",
    )
    reasoning_effort: Optional[str] = Field(
        default=None,
        description="Reasoning effort level (low/medium/high).",
    )


def _validate_model_slot(
    manager: ProviderManager,
    provider_id: str,
    model_id: str,
) -> None:
    """Validate that the provider and model exist without mutating state."""
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found.",
        )
    if not provider.has_model(model_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{model_id}' not found in provider "
                f"'{provider_id}'."
            ),
        )
    model_info = provider.get_model_info(model_id)
    if model_info and model_info.availability_status in {
        "permission_denied",
        "model_not_found",
        "incompatible_api",
    }:
        reason = (
            model_info.availability_message or model_info.availability_status
        )
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_id}' cannot be activated: {reason}",
        )


async def _load_agent_model(
    request: Request,
    agent_id: str,
) -> ModelSlotConfig | None:
    """Load the model configured for a specific agent."""
    workspace = await get_agent_for_request(request, agent_id=agent_id)
    agent_config = await run_sync_io(
        load_agent_config,
        workspace.agent_id,
    )
    return agent_config.active_model


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
    background_tasks: BackgroundTasks,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: ProviderConfigRequest = Body(...),
) -> ProviderInfo:
    config = {
        "api_key": body.api_key,
        "base_url": body.base_url,
        "chat_model": body.chat_model,
        "generate_kwargs": body.generate_kwargs,
        "custom_headers": body.custom_headers,
        "auth_mode": body.auth_mode,
    }
    # Renaming is restricted to custom providers so built-in
    # provider names stay immutable.
    name = body.name.strip() if body.name else None
    if name:
        provider = manager.get_provider(provider_id)
        if provider is not None and provider.is_custom:
            config["name"] = name
    ok = await manager.update_provider_async(provider_id, config)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found",
        )

    provider = manager.get_provider(provider_id)
    if _should_auto_discover(body, provider):
        background_tasks.add_task(
            manager.discover_provider_models,
            provider_id,
            save=True,
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
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider_info


class TestConnectionResponse(BaseModel):
    success: bool = Field(..., description="Whether the test passed")
    message: str = Field(..., description="Human-readable result message")
    status: Optional[ModelAvailabilityStatus] = Field(
        default=None,
        description="Structured model availability status",
    )
    http_status: Optional[int] = Field(default=None)
    retryable: Optional[bool] = Field(default=None)
    checked_at: Optional[str] = Field(default=None)
    verification: Optional[
        Literal["live", "provider_only", "catalog", "unverified"]
    ] = Field(default=None)


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
    custom_headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom headers to use for this test request",
    )
    auth_mode: Optional[Literal["api_key", "auth_token"]] = Field(
        default=None,
        description="Authentication mode to use for this test request",
    )


class TestModelRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to test")


class ModelVisibilityRequest(BaseModel):
    hidden: bool = Field(..., description="Whether to hide the model")


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
    discovered_count: int = Field(
        default=0,
        description=(
            "How many new model candidates were discovered in the catalog"
        ),
    )
    last_synced_at: Optional[str] = Field(default=None)
    used_static_fallback: bool = Field(default=False)
    error_kind: Optional[str] = Field(default=None)


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
        # Build a lightweight Pydantic copy with only the overridden fields;
        # avoids deepcopy which fails when _strip_http_client is cached.
        overrides: dict = {}
        if body and body.api_key:
            overrides["api_key"] = body.api_key
        if body and body.base_url:
            overrides["base_url"] = body.base_url
        if body and body.chat_model:
            overrides["chat_model"] = body.chat_model
        if body and body.custom_headers is not None:
            overrides["custom_headers"] = body.custom_headers
        if body and body.auth_mode in ("api_key", "auth_token"):
            overrides["auth_mode"] = body.auth_mode
        tmp_provider = provider.model_copy(update=overrides)
        ok, msg = await tmp_provider.check_connection()
        return TestConnectionResponse(
            success=ok,
            message=(
                "Connection successful" if ok else f"Connection failed: {msg}"
            ),
        )
    except (ValueError, AppBaseException) as exc:
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
    save: bool = Query(
        default=True,
        description="Save discovered models to provider",
    ),
) -> DiscoverModelsResponse:
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )

        overrides = {
            "api_key": body.api_key if body else None,
            "base_url": body.base_url if body else None,
            "chat_model": body.chat_model if body else None,
        }
        if save:
            ok = await manager.update_provider_async(provider_id, overrides)
            if not ok:
                raise HTTPException(
                    status_code=404,
                    detail=f"Provider '{provider_id}' not found",
                )
        provider_override = manager.materialize_discovery_provider(
            provider_id,
            overrides,
        )
        result = await manager.discover_provider_models(
            provider_id,
            save=save,
            provider_override=provider_override,
        )

        return DiscoverModelsResponse(
            success=result.success,
            models=result.models,
            discovered_count=result.discovered_count,
            last_synced_at=result.last_synced_at,
            used_static_fallback=result.used_static_fallback,
            message=result.error or "",
            error_kind=result.error_kind,
        )
    except (ValueError, AppBaseException) as exc:
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
        result = await manager.check_provider_model(
            provider_id,
            body.model_id,
        )
        return TestConnectionResponse(
            success=result.success,
            message=(
                "Model connection successful"
                if result.success
                else f"Model connection failed: {result.message}"
            ),
            status=result.status,
            http_status=result.http_status,
            retryable=result.retryable,
            checked_at=result.checked_at,
            verification=result.verification,
        )
    except (ValueError, AppBaseException) as exc:
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
        ok = await manager.remove_custom_provider_async(provider_id)
        if not ok:
            raise ValueError(f"Custom Provider '{provider_id}' not found")
    except (ValueError, AppBaseException) as exc:
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
        model_payload = {"id": body.id, "name": body.name}
        for field in (
            "supports_multimodal",
            "supports_image",
            "supports_video",
            "probe_source",
            "is_free",
        ):
            if field in body.model_fields_set:
                model_payload[field] = getattr(body, field)
        provider = await manager.add_model_to_provider(
            provider_id=provider_id,
            model_info=ModelInfo(**model_payload),
        )  # Validate provider exists and add model
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider


@router.put(
    "/{provider_id}/models/{model_id:path}/visibility",
    response_model=ProviderInfo,
    summary="Hide or restore a discovered model",
)
async def set_model_visibility(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
    body: ModelVisibilityRequest = Body(...),
) -> ProviderInfo:
    try:
        return await manager.set_model_hidden(
            provider_id,
            model_id,
            hidden=body.hidden,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ProbeMultimodalResponse(BaseModel):
    supports_image: bool = Field(
        default=False,
        description="Whether the model supports image input",
    )
    supports_video: bool = Field(
        default=False,
        description="Whether the model supports video input",
    )
    supports_multimodal: bool = Field(
        default=False,
        description="Whether the model supports any multimodal input",
    )
    image_message: str = Field(
        default="",
        description="Probe result message for image support",
    )
    video_message: str = Field(
        default="",
        description="Probe result message for video support",
    )


@router.post(
    "/{provider_id}/models/{model_id:path}/probe-multimodal",
    response_model=ProbeMultimodalResponse,
    summary="Probe model multimodal capability",
)
async def probe_model_multimodal(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProbeMultimodalResponse:
    """Probe image and video support by sending lightweight test requests."""
    result = await manager.probe_model_multimodal(provider_id, model_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return ProbeMultimodalResponse(**result)


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
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return provider


@router.put(
    "/{provider_id}/models/{model_id:path}/config",
    response_model=ProviderInfo,
    summary="Configure per-model generation parameters",
)
async def configure_model(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
    body: ModelConfigRequest = Body(...),
) -> ProviderInfo:
    """Update per-model generate_kwargs that override provider-level
    settings."""
    try:
        config = {
            field: getattr(body, field) for field in body.model_fields_set
        }
        provider_info = await manager.update_model_config(
            provider_id=provider_id,
            model_id=model_id,
            config=config,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider_info


@router.get(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Get effective active LLM",
)
async def get_active_models(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    scope: ActiveModelReadScope = Query(default="effective"),
    agent_id: Optional[str] = Query(default=None),
) -> ActiveModelsInfo:
    """Get active model by scope.

    - effective: agent-specific first, otherwise global fallback
    - global: ProviderManager global model only
    - agent: a specific agent's configured model only
    """
    if scope == "global":
        return _active_models_info(manager, manager.get_active_model())

    if scope == "agent":
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="agent_id is required when scope is 'agent'",
            )
        return _active_models_info(
            manager,
            await _load_agent_model(request, agent_id),
        )

    try:
        target_agent_id = agent_id
        if target_agent_id is None:
            workspace = await get_agent_for_request(request)
            target_agent_id = workspace.agent_id

        agent_model = await _load_agent_model(request, target_agent_id)
        if agent_model:
            logger.info(
                "Returning agent-specific model for %s: %s",
                sanitize_log_value(target_agent_id),
                agent_model,
            )
            return _active_models_info(manager, agent_model)
    except (
        HTTPException,
        OSError,
        ValueError,
        TypeError,
        AppBaseException,
    ) as exc:
        logger.warning(
            "Failed to get agent-specific model: %s",
            exc,
            exc_info=True,
        )

    global_model = manager.get_active_model()
    logger.info("Returning global model: %s", global_model)
    return _active_models_info(manager, global_model)


@router.put(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Set active LLM",
)
async def set_active_model(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    body: ModelSlotRequest = Body(...),
) -> ActiveModelsInfo:
    """Set active model by scope."""
    if body.scope == "global":
        try:
            await manager.activate_model(body.provider_id, body.model)
        except (
            FileNotFoundError,
            RuntimeError,
            ValueError,
            AppBaseException,
        ) as exc:
            message = str(exc)
            lower_msg = message.lower()
            if "provider" in lower_msg and "not found" in lower_msg:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc

        # Sync to active agent if its active_model is unset (#4937)
        try:
            workspace = await get_agent_for_request(request)
            changed = False

            def apply_global_default(
                agent_config: AgentProfileConfig,
            ) -> None:
                nonlocal changed
                if (
                    agent_config.active_model
                    and agent_config.active_model.provider_id
                ):
                    return
                agent_config.active_model = ModelSlotConfig(
                    provider_id=body.provider_id,
                    model=body.model,
                )
                changed = True

            await update_agent_config_async(
                workspace.agent_id,
                apply_global_default,
            )
            if changed:
                schedule_agent_reload(request, workspace.agent_id)
        except Exception:
            pass

        return _active_models_info(manager, manager.get_active_model())

    if not body.agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required when scope is 'agent'",
        )

    _validate_model_slot(manager, body.provider_id, body.model)

    try:
        workspace = await get_agent_for_request(
            request,
            agent_id=body.agent_id,
        )

        def apply_active_model(agent_config: AgentProfileConfig) -> None:
            agent_config.active_model = ModelSlotConfig(
                provider_id=body.provider_id,
                model=body.model,
            )

        await update_agent_config_async(
            workspace.agent_id,
            apply_active_model,
        )
        # Hot reload agent (async, non-blocking)
        schedule_agent_reload(request, workspace.agent_id)

    except (
        HTTPException,
        OSError,
        ValueError,
        TypeError,
        AppBaseException,
    ) as exc:
        logger.warning(
            "Failed to save active model to agent config: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to save active model to agent config",
        ) from exc

    manager.maybe_probe_multimodal(body.provider_id, body.model)

    return _active_models_info(
        manager,
        ModelSlotConfig(
            provider_id=body.provider_id,
            model=body.model,
        ),
    )


# =============================================================================
# OpenRouter-specific endpoints for model discovery with filtering
# =============================================================================


class FilterModelsRequest(BaseModel):
    """Request model for filtering OpenRouter models."""

    providers: List[str] = Field(
        default_factory=list,
        description="Filter by provider/series (e.g., ['openai', 'google'])",
    )
    input_modalities: List[str] = Field(
        default_factory=list,
        description="Required input modalities (e.g., ['image'])",
    )
    output_modalities: List[str] = Field(
        default_factory=list,
        description="Required output modalities (e.g., ['text'])",
    )
    max_prompt_price: Optional[float] = Field(
        default=None,
        description="Maximum prompt price per 1M tokens (e.g., 0.000001)",
    )
    is_free: Optional[bool] = Field(
        default=None,
        description="Whether to return only free models",
    )


class SeriesResponse(BaseModel):
    """Response model for available series/providers."""

    series: List[str] = Field(
        default_factory=list,
        description="Provider series (e.g., ['openai', 'google'])",
    )


class DiscoverExtendedResponse(BaseModel):
    """Response model for extended model discovery."""

    success: bool = Field(..., description="Whether discovery succeeded")
    models: List[dict] = Field(
        default_factory=list,
        description="Discovered models with extended metadata",
    )
    providers: List[str] = Field(
        default_factory=list,
        description="Available provider series",
    )
    total_count: int = Field(
        default=0,
        description="Total number of models discovered",
    )


class FilterModelsResponse(BaseModel):
    """Response model for filtered models."""

    success: bool = Field(..., description="Whether filtering succeeded")
    models: List[dict] = Field(
        default_factory=list,
        description="Filtered models with extended metadata",
    )
    total_count: int = Field(
        default=0,
        description="Total number of models matching filters",
    )


@router.get(
    "/openrouter/series",
    response_model=SeriesResponse,
    summary="Get available OpenRouter provider series",
)
async def get_openrouter_series(
    manager: ProviderManager = Depends(get_provider_manager),
) -> SeriesResponse:
    """Get list of available provider/series from OpenRouter."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    try:
        series = await provider.get_available_providers()
        return SeriesResponse(series=series)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch series: {str(exc)}",
        ) from exc


@router.post(
    "/openrouter/discover-extended",
    response_model=DiscoverExtendedResponse,
    summary="Discover OpenRouter models with extended metadata",
)
async def discover_openrouter_extended(
    manager: ProviderManager = Depends(get_provider_manager),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
) -> DiscoverExtendedResponse:
    """Discover available models from OpenRouter with full metadata."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    if body and body.api_key:
        await manager.update_provider_async(
            "openrouter",
            {"api_key": body.api_key},
        )

    try:
        models = await provider.fetch_extended_models()
        providers = await provider.get_available_providers()

        models_dict = [
            {
                "id": m.id,
                "name": m.name,
                "supports_multimodal": m.supports_multimodal,
                "supports_image": m.supports_image,
                "supports_video": m.supports_video,
                "probe_source": m.probe_source,
                "is_free": m.is_free,
                "provider": m.provider,
                "input_modalities": m.input_modalities,
                "output_modalities": m.output_modalities,
                "pricing": m.pricing,
            }
            for m in models
        ]

        return DiscoverExtendedResponse(
            success=True,
            models=models_dict,
            providers=providers,
            total_count=len(models_dict),
        )
    except Exception:
        return DiscoverExtendedResponse(
            success=False,
            models=[],
            providers=[],
            total_count=0,
        )


@router.post(
    "/openrouter/models/filter",
    response_model=FilterModelsResponse,
    summary="Filter OpenRouter models by criteria",
)
async def filter_openrouter_models(
    manager: ProviderManager = Depends(get_provider_manager),
    body: FilterModelsRequest = Body(...),
) -> FilterModelsResponse:
    """Filter OpenRouter models by provider, modalities, and price."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    try:
        models = await provider.fetch_extended_models()

        filtered_models = provider.filter_models(
            models=models,
            providers=body.providers if body.providers else None,
            input_modalities=(
                body.input_modalities if body.input_modalities else None
            ),
            output_modalities=(
                body.output_modalities if body.output_modalities else None
            ),
            max_prompt_price=body.max_prompt_price,
            is_free=body.is_free,
        )

        models_dict = [
            {
                "id": m.id,
                "name": m.name,
                "supports_multimodal": m.supports_multimodal,
                "supports_image": m.supports_image,
                "supports_video": m.supports_video,
                "probe_source": m.probe_source,
                "is_free": m.is_free,
                "provider": m.provider,
                "input_modalities": m.input_modalities,
                "output_modalities": m.output_modalities,
                "pricing": m.pricing,
            }
            for m in filtered_models
        ]

        return FilterModelsResponse(
            success=True,
            models=models_dict,
            total_count=len(models_dict),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to filter models: {str(exc)}",
        ) from exc
