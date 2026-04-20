# -*- coding: utf-8 -*-
"""API endpoints for local model management."""

from __future__ import annotations

from typing import Any, List, Optional

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from ...local_models import (
    DownloadSource,
    LocalModelConfig,
    LocalModelInfo,
    LocalModelManager,
)
from ...providers.provider import ModelInfo
from ...providers.provider_manager import ProviderManager

router = APIRouter(prefix="/local-models", tags=["local-models"])


def get_local_model_manager(request: Request) -> LocalModelManager:
    """Helper to get the LocalModelManager instance from app state."""
    return request.app.state.local_model_manager


def get_provider_manager(request: Request) -> ProviderManager:
    """Helper to get the ProviderManager instance from app state."""
    return request.app.state.provider_manager


def _clear_local_runtime_provider_state(
    provider_manager: ProviderManager,
) -> None:
    """Reset persisted provider state for the managed local runtime."""
    provider_manager.update_provider(
        "qwenpaw-local",
        {
            "base_url": "",
            "extra_models": [],
        },
    )
    provider_manager.clear_active_model("qwenpaw-local")


class ServerStatus(BaseModel):
    available: bool = Field(
        ...,
        description="Whether llama.cpp is running and responding",
    )
    installable: bool = Field(
        ...,
        description="Whether the current environment can install llama.cpp",
    )
    installed: bool = Field(..., description="Whether llama.cpp is installed")
    port: Optional[int] = Field(
        default=None,
        description="Active llama.cpp server port",
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Model alias currently served by llama.cpp",
    )
    message: Optional[str] = Field(
        default=None,
        description="Additional info if the server is not available",
    )


class DownloadProgressResponse(BaseModel):
    status: str
    model_name: Optional[str] = None
    downloaded_bytes: int
    total_bytes: Optional[int] = None
    speed_bytes_per_sec: float
    source: Optional[str] = None
    error: Optional[str] = None
    local_path: Optional[str] = None


class StartServerRequest(BaseModel):
    model_id: str = Field(
        ...,
        description="The model id of the downloaded local model to serve",
    )


class StartServerResponse(BaseModel):
    port: int = Field(..., description="Port bound by the llama.cpp server")
    model_info: ModelInfo = Field(
        ...,
        description="Metadata for the model exposed by the llama.cpp server",
    )


class StartModelDownloadRequest(BaseModel):
    model_name: str = Field(
        ...,
        description="Recommended local model name to download",
    )
    source: DownloadSource = Field(
        default=DownloadSource.AUTO,
        description="Optional source to download the model from",
    )


class ActionResponse(BaseModel):
    status: str = Field(..., description="Operation result status")
    message: str = Field(..., description="Human-readable operation result")


class ServerUpdateStatus(BaseModel):
    has_update: bool = Field(
        ...,
        description="Whether a newer llama.cpp package is available",
    )


class LocalModelConfigRequest(BaseModel):
    """Request body for configuring local model settings."""

    max_context_length: Optional[int] = Field(
        default=None,
        description="Maximum context length for local models.",
        ge=32768,
    )
    port: Optional[int] = Field(
        default=None,
        description="Optional fixed port for local llama.cpp server.",
        ge=1,
        le=65535,
    )
    generate_kwargs: Optional[dict[str, Any]] = Field(
        default=None,
        description=("Additional generation parameters for local models."),
    )


# =========================================================================
# llama.cpp server related endpoints
# ========================================================================


SERVER_STATUS_CHECK_TIMEOUT = 3.0


@router.get(
    "/server",
    response_model=ServerStatus,
    summary="Check if local server is available",
)
async def server_available(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ServerStatus:
    """Check if the local model server is properly installed and ready."""
    installable, install_message = manager.check_llamacpp_installability()

    if not installable:
        return ServerStatus(
            available=False,
            installable=False,
            installed=False,
            port=None,
            model_name=None,
            message=(
                install_message
                or "Current environment does not support llama.cpp"
            ),
        )

    installed, message = manager.check_llamacpp_installation()
    ready = False

    if not installed:
        return ServerStatus(
            available=False,
            installable=installable,
            installed=False,
            port=None,
            model_name=None,
            message=message or install_message,
        )

    server_state = manager.get_llamacpp_server_status()

    if server_state["running"] and manager.is_llamacpp_server_transitioning():
        message = "llama.cpp server is starting"
    elif server_state["running"]:
        try:
            ready = await manager.check_llamacpp_server_ready(
                timeout=SERVER_STATUS_CHECK_TIMEOUT,
            )
        except RuntimeError as exc:
            message = str(exc)
        except ValueError:
            message = "llama.cpp server status is temporarily unavailable"
    else:
        message = (
            "llama.cpp server is not running, please start the server first"
        )

    if server_state["running"] and not ready and not message:
        message = "llama.cpp server is not responding"

    return ServerStatus(
        available=installed and ready,
        installable=installable,
        installed=installed,
        port=server_state["port"],
        model_name=server_state["model_name"],
        message=message,
    )


@router.get(
    "/server/update",
    response_model=ServerUpdateStatus,
    summary="Check if a llama.cpp update is available",
)
async def get_llamacpp_update_status(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ServerUpdateStatus:
    """Check whether an installed llama.cpp runtime has an update."""
    installable, _ = manager.check_llamacpp_installability()
    if not installable:
        return ServerUpdateStatus(has_update=False)

    installed, _ = manager.check_llamacpp_installation()
    if not installed:
        return ServerUpdateStatus(has_update=False)

    return ServerUpdateStatus(has_update=await manager.has_update())


@router.post(
    "/server/download",
    response_model=ActionResponse,
    summary="Start llama.cpp download",
)
async def start_llamacpp_download(
    manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> ActionResponse:
    """Start downloading the llama.cpp binary package."""
    try:
        server_stopped = await manager.start_llamacpp_download()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if server_stopped:
        _clear_local_runtime_provider_state(provider_manager)
    return ActionResponse(
        status="accepted",
        message="llama.cpp download started",
    )


@router.get(
    "/server/download",
    response_model=DownloadProgressResponse,
    summary="Get llama.cpp download progress",
)
async def get_llamacpp_download_progress(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> dict[str, Any]:
    """Return the current llama.cpp download progress snapshot."""
    return manager.get_llamacpp_download_progress()


@router.delete(
    "/server/download",
    response_model=ActionResponse,
    summary="Cancel llama.cpp download",
)
async def cancel_llamacpp_download(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Cancel the current llama.cpp download task."""
    manager.cancel_llamacpp_download()
    return ActionResponse(
        status="ok",
        message="llama.cpp download cancellation requested",
    )


@router.post(
    "/server",
    response_model=StartServerResponse,
    summary="Start llama.cpp server",
)
async def start_llamacpp_server(
    payload: StartServerRequest,
    model_manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> StartServerResponse:
    """Start a local llama.cpp server for a downloaded model."""
    try:
        setup_result = await model_manager.setup_server(
            model_id=payload.model_id,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        provider_manager.update_provider(
            "qwenpaw-local",
            {
                "base_url": f"http://127.0.0.1:{setup_result.port}/v1",
                "extra_models": [setup_result.model_info],
            },
        )
        await provider_manager.activate_model(
            provider_id="qwenpaw-local",
            model_id=setup_result.model_info.id,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StartServerResponse(
        port=setup_result.port,
        model_info=setup_result.model_info,
    )


@router.delete(
    "/server",
    response_model=ActionResponse,
    summary="Stop llama.cpp server",
)
async def stop_llamacpp_server(
    model_manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> ActionResponse:
    """Stop the active llama.cpp server."""
    await model_manager.shutdown_server()
    _clear_local_runtime_provider_state(provider_manager)

    return ActionResponse(
        status="ok",
        message="llama.cpp server stopped",
    )


# ===============================================================
# Local Model related endpoints
# ===============================================================


@router.get(
    "/models",
    response_model=List[LocalModelInfo],
    summary="List recommended and downloaded local models",
)
async def list_local(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> List[LocalModelInfo]:
    """List recommended models plus downloaded local models."""
    models_by_id = {
        model.id: model for model in manager.get_recommended_models()
    }
    for model in manager.list_downloaded_models():
        models_by_id.setdefault(model.id, model)
    return list(models_by_id.values())


@router.post(
    "/models/download",
    response_model=ActionResponse,
    summary="Start local model download",
)
async def start_local_model_download(
    payload: StartModelDownloadRequest,
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Start downloading a recommended local model."""
    try:
        manager.start_model_download(
            payload.model_name,
            source=payload.source,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ActionResponse(
        status="accepted",
        message=f"Local model download started: {payload.model_name}",
    )


@router.get(
    "/models/download",
    response_model=DownloadProgressResponse,
    summary="Get local model download progress",
)
async def get_local_model_download_progress(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> dict[str, Any]:
    """Return the current local model download progress snapshot."""
    return manager.get_model_download_progress()


@router.delete(
    "/models/download",
    response_model=ActionResponse,
    summary="Cancel local model download",
)
async def cancel_local_model_download(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Cancel the current local model download task."""
    manager.cancel_model_download()
    return ActionResponse(
        status="ok",
        message="Local model download cancellation requested",
    )


@router.delete(
    "/models/{model_id:path}",
    response_model=ActionResponse,
    summary="Delete a downloaded local model",
)
async def delete_local_model(
    model_id: str,
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Delete a downloaded local model by repo id."""
    server_state = manager.get_llamacpp_server_status()
    if (
        server_state.get("running")
        and server_state.get("model_name") == model_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a model while it is running",
        )

    try:
        manager.remove_downloaded_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AppBaseException as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ActionResponse(
        status="ok",
        message=f"Local model deleted: {model_id}",
    )


@router.put(
    "/config",
    response_model=ActionResponse,
    summary="Configure local model settings",
)
async def configure_local_model_settings(
    payload: LocalModelConfigRequest,
    local_manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> ActionResponse:
    """Configure local model settings."""
    if payload.max_context_length is not None:
        await local_manager.set_max_context_length(payload.max_context_length)

    if "port" in payload.model_fields_set:
        await local_manager.set_port(payload.port)

    if payload.generate_kwargs is not None:
        provider_manager.update_provider(
            "qwenpaw-local",
            {
                "generate_kwargs": payload.generate_kwargs,
            },
        )

    return ActionResponse(
        status="ok",
        message="Local model settings updated",
    )


@router.get(
    "/config",
    response_model=LocalModelConfig,
    summary="Get local model settings",
)
async def get_local_model_settings(
    local_manager: LocalModelManager = Depends(get_local_model_manager),
) -> LocalModelConfig:
    """Return persisted local model runtime settings."""
    return local_manager.get_config()
