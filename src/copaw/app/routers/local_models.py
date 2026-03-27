# -*- coding: utf-8 -*-
"""API endpoints for local model management."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from ...local_models.model_manager import LocalModelInfo
from ...local_models.manager import LocalModelManager
from ...providers.provider import ModelInfo
from ...providers.models import ModelSlotConfig
from ...providers.provider_manager import ProviderManager

router = APIRouter(prefix="/local-models", tags=["local-models"])


def get_local_model_manager(request: Request) -> LocalModelManager:
    """Helper to get the LocalModelManager instance from app state."""
    return request.app.state.local_model_manager


def get_provider_manager(request: Request) -> ProviderManager:
    """Helper to get the ProviderManager instance from app state."""
    return request.app.state.provider_manager


class ServerStatus(BaseModel):
    available: bool = Field(
        ...,
        description="Whether llama.cpp is running and responding",
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
    model_path: str = Field(
        ...,
        description="Path to a local GGUF file or repo directory",
    )
    model_name: str = Field(
        ...,
        description="Alias exposed by the llama.cpp server",
    )


class StartServerResponse(BaseModel):
    port: int = Field(..., description="Port bound by the llama.cpp server")
    model_name: str = Field(
        ...,
        description="Alias exposed by the llama.cpp server",
    )


class StartModelDownloadRequest(BaseModel):
    model_name: str = Field(
        ...,
        description="Recommended local model name to download",
    )


class ActionResponse(BaseModel):
    status: str = Field(..., description="Operation result status")
    message: str = Field(..., description="Human-readable operation result")


# =========================================================================
# llama.cpp server related endpoints
# ========================================================================


@router.get(
    "/server",
    response_model=ServerStatus,
    summary="Check if local server is available",
)
async def server_available(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ServerStatus:
    """Check if the local model server is properly installed and ready."""
    installed = manager.check_llamacpp_installation()
    ready = False
    message = ""

    if not installed:
        return ServerStatus(
            available=False,
            installed=False,
            port=None,
            model_name=None,
            message="llama.cpp is not installed",
        )

    server_state = manager.get_llamacpp_server_status()

    if server_state["running"]:
        try:
            ready = await manager.check_llamacpp_server_ready()
        except RuntimeError as exc:
            message = str(exc)
    else:
        message = "llama.cpp server is not running"

    if server_state["running"] and not ready and not message:
        message = "llama.cpp server is not responding"

    return ServerStatus(
        available=installed and ready,
        installed=installed,
        port=server_state["port"],
        model_name=server_state["model_name"],
        message=message,
    )


@router.post(
    "/server/download",
    response_model=ActionResponse,
    summary="Start llama.cpp download",
)
async def start_llamacpp_download(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Start downloading the llama.cpp binary package."""
    try:
        manager.start_llamacpp_download()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        port = await model_manager.setup_server(
            model_name=payload.model_name,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    local_provider = provider_manager.get_provider("copaw-local")

    if local_provider is None:
        raise HTTPException(
            status_code=500,
            detail="Local provider not found in provider manager",
        )

    local_provider.models = [
        ModelInfo(id=payload.model_name, name=payload.model_name),
    ]
    local_provider.base_url = f"http://localhost:{port}/v1"

    # update the active model slot to point to the new local model
    provider_manager.save_active_model(
        ModelSlotConfig(
            provider_id=local_provider.id,
            model=payload.model_name,
        ),
    )

    return StartServerResponse(
        port=port,
        model_name=payload.model_name,
    )


@router.delete(
    "/server",
    response_model=ActionResponse,
    summary="Stop llama.cpp server",
)
async def stop_llamacpp_server(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> ActionResponse:
    """Stop the active llama.cpp server."""
    await manager.shutdown_server()
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
    summary="List recommended local models",
)
async def list_local(
    manager: LocalModelManager = Depends(get_local_model_manager),
) -> List[LocalModelInfo]:
    """List all recommended local models."""
    return manager.get_recommended_models()


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
        manager.start_model_download(payload.model_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

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
