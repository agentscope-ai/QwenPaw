# -*- coding: utf-8 -*-
"""API endpoints for local model management."""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import BaseModel, Field

from qwenpaw.exceptions import (
    AppBaseException,
)

from ...local_models import (
    DownloadSource,
    LocalModelConfig,
    LocalModelInfo,
    LocalModelManager,
)
from ...local_models.manager import (
    DEFAULT_LOCAL_ENGINE,
    normalize_engine,
)
from ...providers.provider import ModelInfo
from ...providers.provider_manager import ProviderManager

router = APIRouter(prefix="/local-models", tags=["local-models"])


async def get_local_model_manager(request: Request) -> LocalModelManager:
    """Helper to get the LocalModelManager instance from app state."""
    return request.app.state.local_model_manager


async def get_provider_manager(request: Request) -> ProviderManager:
    """Helper to get the ProviderManager instance from app state."""
    return request.app.state.provider_manager


async def get_engine(
    engine: str = Query(
        default=DEFAULT_LOCAL_ENGINE,
        description="Local inference engine id",
    ),
) -> str:
    """Validate the optional engine selector query parameter."""
    try:
        return normalize_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def get_optional_engine(
    engine: str
    | None = Query(
        default=None,
        description="Local inference engine id; omit to stop all engines",
    ),
) -> str | None:
    """Return a validated engine id, or None when the caller omitted it."""
    if engine is None:
        return None
    try:
        return normalize_engine(engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _clear_local_runtime_provider_state(
    provider_manager: ProviderManager,
) -> None:
    """Reset persisted provider state for the managed local runtime."""
    await provider_manager.update_provider_async(
        "qwenpaw-local",
        {
            "base_url": "",
            "extra_models": [],
        },
    )
    await provider_manager.clear_active_model_async("qwenpaw-local")
    await provider_manager.clear_active_model_async(
        "qwenpaw-local",
        model_type="decision",
    )


class EngineInfo(BaseModel):
    """Availability summary for one local inference engine."""

    id: str
    name: str
    installable: bool
    installed: bool
    running: bool
    available: bool
    port: Optional[int] = None
    model_name: Optional[str] = None
    message: Optional[str] = None
    accelerator: Optional[str] = None
    device_name: Optional[str] = None
    version: Optional[str] = None


class ServerStatus(BaseModel):
    available: bool = Field(
        ...,
        description="Whether the local engine is running and responding",
    )
    installable: bool = Field(
        ...,
        description="Whether the current environment can install the engine",
    )
    installed: bool = Field(..., description="Whether the engine is installed")
    engine: str = Field(
        default=DEFAULT_LOCAL_ENGINE,
        description="Local inference engine id",
    )
    port: Optional[int] = Field(
        default=None,
        description="Active local server port",
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Model alias currently served by the engine",
    )
    message: Optional[str] = Field(
        default=None,
        description="Additional info if the server is not available",
    )
    accelerator: Optional[str] = Field(
        default=None,
        description="Active accelerator: metal, cuda, or cpu",
    )
    device_name: Optional[str] = Field(
        default=None,
        description="Human-readable accelerator device name",
    )
    version: Optional[str] = Field(
        default=None,
        description="Installed engine runtime version",
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
    engine: str = Field(
        default=DEFAULT_LOCAL_ENGINE,
        description="Local inference engine id",
    )


class StartServerResponse(BaseModel):
    port: int = Field(..., description="Port bound by the local server")
    model_info: ModelInfo = Field(
        ...,
        description="Metadata for the model exposed by the local server",
    )
    engine: str = Field(
        default=DEFAULT_LOCAL_ENGINE,
        description="Local inference engine id",
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
    engine: str = Field(
        default=DEFAULT_LOCAL_ENGINE,
        description="Local inference engine id",
    )


class ActionResponse(BaseModel):
    status: str = Field(..., description="Operation result status")
    message: str = Field(..., description="Human-readable operation result")


class ServerUpdateStatus(BaseModel):
    has_update: bool = Field(
        ...,
        description="Whether a newer runtime package is available",
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
        description="Optional fixed port for local server startup.",
        ge=1,
        le=65535,
    )
    generate_kwargs: Optional[dict[str, Any]] = Field(
        default=None,
        description=("Additional generation parameters for local models."),
    )
    gpu_acceleration: Optional[bool] = Field(
        default=None,
        description="Whether llama.cpp may offload layers to the GPU.",
    )
    auto_update: Optional[bool] = Field(
        default=None,
        description="Whether to install local engine updates automatically.",
    )


# =========================================================================
# Local engine server related endpoints
# ========================================================================


SERVER_STATUS_CHECK_TIMEOUT = 3.0


@router.get(
    "/engines",
    response_model=List[EngineInfo],
    summary="List local inference engines",
)
async def list_local_engines(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> List[EngineInfo]:
    """Return install and runtime state for every local engine."""
    engines = []
    for engine_id in manager.list_engines():
        engines.append(
            EngineInfo(**await manager.get_engine_status(engine_id)),
        )
    return engines


@router.get(
    "/server",
    response_model=ServerStatus,
    summary="Check if local server is available",
)
async def server_available(
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ServerStatus:
    """Check if the selected local engine is installed and ready."""
    installable, install_message = manager.check_installability(engine)
    accelerator = await manager.get_engine_accelerator(engine)
    version = await manager.get_engine_version(engine)

    if not installable:
        return ServerStatus(
            available=False,
            installable=False,
            installed=False,
            engine=engine,
            port=None,
            model_name=None,
            message=(
                install_message
                or f"Current environment does not support {engine}"
            ),
            accelerator=accelerator["accelerator"],
            device_name=accelerator["device_name"],
            version=version,
        )

    installed, message = manager.check_installation(engine)
    ready = False

    if not installed:
        return ServerStatus(
            available=False,
            installable=installable,
            installed=False,
            engine=engine,
            port=None,
            model_name=None,
            message=message or install_message,
            accelerator=accelerator["accelerator"],
            device_name=accelerator["device_name"],
            version=version,
        )

    server_state = manager.get_engine_server_status(engine)

    if server_state["running"] and manager.is_engine_transitioning(engine):
        message = f"{engine} server is starting"
    elif server_state["running"]:
        try:
            ready = await manager.check_server_ready(
                engine,
                timeout=SERVER_STATUS_CHECK_TIMEOUT,
            )
        except RuntimeError as exc:
            message = str(exc)
        except ValueError:
            message = f"{engine} server status is temporarily unavailable"
    else:
        message = (
            f"{engine} server is not running, please start the server first"
        )

    if server_state["running"] and not ready and not message:
        message = f"{engine} server is not responding"

    return ServerStatus(
        available=installed and ready,
        installable=installable,
        installed=installed,
        engine=engine,
        port=server_state["port"],
        model_name=server_state["model_name"],
        message=message,
        accelerator=accelerator["accelerator"],
        device_name=accelerator["device_name"],
        version=version,
    )


@router.get(
    "/server/update",
    response_model=ServerUpdateStatus,
    summary="Check if a local engine update is available",
)
async def get_local_engine_update_status(
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ServerUpdateStatus:
    """Check whether an installed local engine runtime has an update."""
    installable, _ = manager.check_installability(engine)
    if not installable:
        return ServerUpdateStatus(has_update=False)

    installed, _ = manager.check_installation(engine)
    if not installed:
        return ServerUpdateStatus(has_update=False)

    return ServerUpdateStatus(
        has_update=await manager.has_engine_update(engine),
    )


@router.post(
    "/server/download",
    response_model=ActionResponse,
    summary="Install a local engine runtime",
)
async def start_local_engine_download(
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> ActionResponse:
    """Start installing the selected engine runtime."""
    try:
        server_stopped = await manager.start_engine_download(engine)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if server_stopped:
        await _clear_local_runtime_provider_state(provider_manager)
    return ActionResponse(
        status="accepted",
        message=f"{engine} runtime install started",
    )


@router.get(
    "/server/download",
    response_model=DownloadProgressResponse,
    summary="Get local engine runtime install progress",
)
async def get_local_engine_download_progress(
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> dict[str, Any]:
    """Return the selected engine's runtime install progress snapshot."""
    return manager.get_engine_download_progress(engine)


@router.delete(
    "/server/download",
    response_model=ActionResponse,
    summary="Cancel a local engine runtime install",
)
async def cancel_local_engine_download(
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Cancel the selected engine's runtime install."""
    manager.cancel_engine_download(engine)
    return ActionResponse(
        status="ok",
        message=f"{engine} runtime install cancellation requested",
    )


@router.post(
    "/server",
    response_model=StartServerResponse,
    summary="Start a local engine server",
)
async def start_local_engine_server(
    payload: StartServerRequest,
    model_manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> StartServerResponse:
    """Start a local engine server for a downloaded model."""
    try:
        engine = normalize_engine(payload.engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        setup_result = await model_manager.setup_server(
            model_id=payload.model_id,
            engine=engine,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        await provider_manager.update_provider_async(
            "qwenpaw-local",
            {
                "base_url": f"http://127.0.0.1:{setup_result.port}/v1",
                "extra_models": [setup_result.model_info],
            },
        )
        await provider_manager.activate_model(
            provider_id="qwenpaw-local",
            model_id=setup_result.model_info.id,
            model_type=setup_result.model_info.model_type,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StartServerResponse(
        port=setup_result.port,
        model_info=setup_result.model_info,
        engine=engine,
    )


@router.delete(
    "/server",
    response_model=ActionResponse,
    summary="Stop a local engine server",
)
async def stop_local_engine_server(
    engine: str | None = Depends(get_optional_engine),
    model_manager: LocalModelManager = Depends(get_local_model_manager),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> ActionResponse:
    """Stop the selected local engine server, or every engine if omitted."""
    await model_manager.shutdown_server(engine)
    await _clear_local_runtime_provider_state(provider_manager)

    return ActionResponse(
        status="ok",
        message=f"{engine or 'local'} server stopped",
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
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> List[LocalModelInfo]:
    """List recommended models plus downloaded local models."""
    models_by_id = {
        model.id: model for model in manager.get_recommended_models(engine)
    }
    for model in manager.list_downloaded_models(engine):
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
        engine = normalize_engine(payload.engine)
        manager.start_model_download(
            payload.model_name,
            source=payload.source,
            engine=engine,
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
    engine: str = Depends(get_engine),
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Delete a downloaded local model by repo id."""
    if manager.is_model_serving(model_id, engine):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a model while it is running",
        )

    try:
        manager.remove_downloaded_model(model_id, engine=engine)
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

    if payload.gpu_acceleration is not None:
        await local_manager.set_gpu_acceleration(payload.gpu_acceleration)

    if payload.auto_update is not None:
        await local_manager.set_auto_update(payload.auto_update)

    if payload.generate_kwargs is not None:
        await provider_manager.update_provider_async(
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


# Backwards-compatible names for callers that still use the llama.cpp API.
start_llamacpp_server = start_local_engine_server
stop_llamacpp_server = stop_local_engine_server
start_llamacpp_download = start_local_engine_download
get_llamacpp_update_status = get_local_engine_update_status
get_llamacpp_download_progress = get_local_engine_download_progress
cancel_llamacpp_download = cancel_local_engine_download
