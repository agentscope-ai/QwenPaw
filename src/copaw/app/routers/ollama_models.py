# -*- coding: utf-8 -*-
"""API endpoints for Ollama model management.

This router mirrors the local_models router but delegates lifecycle operations
(list / pull / delete) to the Ollama daemon via OllamaModelManager. Downloads
run in the background and their status can be polled by the frontend.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..download_task_store import (
    DownloadTask,
    DownloadTaskStatus,
    get_task,
    clear_completed,
    create_task,
    get_tasks,
    update_status,
    cancel_task,
)

from ...providers.provider import ModelInfo
from ...providers.provider_manager import PROVIDER_OLLAMA

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ollama-models", tags=["ollama-models"])

_background_tasks: Dict[str, asyncio.Task] = {}
_background_tasks_lock = asyncio.Lock()


class OllamaDownloadRequest(BaseModel):
    name: str = Field(..., description="Ollama model name, e.g. 'llama3:8b'")


class OllamaModelResponse(BaseModel):
    name: str
    size: int
    digest: Optional[str] = None
    modified_at: Optional[str] = None


class OllamaDownloadTaskResponse(BaseModel):
    task_id: str
    status: str
    name: str
    error: Optional[str] = None
    result: Optional[OllamaModelResponse] = None


def _is_ollama_connection_error(exc: Exception) -> bool:
    """Return True when the exception indicates Ollama daemon is unreachable.

    The ollama SDK may raise different exception types depending on version.
    We keep detection tolerant by checking both type and message patterns.
    """
    if isinstance(exc, ConnectionError):
        return True
    msg = str(exc).lower()
    return "failed to connect to ollama" in msg or "connection refused" in msg


def _task_to_response(task: DownloadTask) -> OllamaDownloadTaskResponse:
    result = None
    if task.result:
        result = OllamaModelResponse(**task.result)
    return OllamaDownloadTaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        name=task.repo_id,  # store model name in repo_id for reuse
        error=task.error,
        result=result,
    )


async def _register_background_task(task_id: str, task: asyncio.Task) -> None:
    async with _background_tasks_lock:
        _background_tasks[task_id] = task


async def _pop_background_task(task_id: str) -> Optional[asyncio.Task]:
    async with _background_tasks_lock:
        return _background_tasks.pop(task_id, None)


async def _run_ollama_download_in_background(
    task_id: str,
    model_name: str,
    ollama_provider,
) -> None:
    task = await get_task(task_id)
    if task and task.status == DownloadTaskStatus.CANCELLED:
        logger.info("Ollama download task %s cancelled before start", task_id)
        await _pop_background_task(task_id)
        return

    await update_status(task_id, DownloadTaskStatus.DOWNLOADING)

    try:
        await ollama_provider.add_model(
            ModelInfo(id=model_name, name=model_name),
        )

        task = await get_task(task_id)
        if task and task.status == DownloadTaskStatus.CANCELLED:
            logger.info(
                "Ollama download task %s cancelled during execution",
                task_id,
            )
            await _pop_background_task(task_id)
            return

        await update_status(
            task_id,
            DownloadTaskStatus.COMPLETED,
            result={
                "name": model_name,
                "size": 0,
                "digest": None,
                "modified_at": None,
            },
        )
    except asyncio.CancelledError:
        await update_status(task_id, DownloadTaskStatus.CANCELLED)
        logger.info("Ollama download task %s cancelled", task_id)
        raise
    except (
        ImportError,
        ValueError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as exc:
        logger.exception("Ollama background download failed: %s", exc)
        await update_status(
            task_id,
            DownloadTaskStatus.FAILED,
            error=str(exc),
        )
    finally:
        await _pop_background_task(task_id)


@router.get(
    "",
    response_model=List[OllamaModelResponse],
    summary="List Ollama models",
)
async def list_ollama_models(
    request: Request,
) -> List[OllamaModelResponse]:
    """Return the current Ollama model list via the SDK.

    If the Ollama SDK is not installed, returns HTTP 501.
    """
    p = request.app.state.provider_manager.get_provider(
        PROVIDER_OLLAMA.id,
    )
    try:
        models = await p._client().list()  # pylint: disable=protected-access
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Ollama Python SDK not installed. Install with: "
            "pip install 'copaw[ollama]'",
        ) from exc
    except (ValueError, RuntimeError, OSError, ConnectionError) as exc:
        logger.exception("Failed to list Ollama models")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list Ollama models: {exc}",
        ) from exc

    return [
        OllamaModelResponse(
            name=m.model,
            size=m.size,
            digest=m.digest,
            modified_at=str(m.modified_at),
        )
        for m in models.models
    ]


@router.post(
    "/download",
    response_model=OllamaDownloadTaskResponse,
    summary="Start a background Ollama model pull",
)
async def download_ollama_model(
    request: Request,
    body: OllamaDownloadRequest,
) -> OllamaDownloadTaskResponse:
    """Start a background pull via Ollama SDK.

    Returns a task_id immediately; the frontend can poll /download-status
    to track progress.
    """
    ollama_provider = request.app.state.provider_manager.get_provider(
        PROVIDER_OLLAMA.id,
    )

    await clear_completed(backend=PROVIDER_OLLAMA.id)
    task = await create_task(
        repo_id=body.name,
        filename=None,
        backend=PROVIDER_OLLAMA.id,
        source="ollama",
    )

    background_task = asyncio.create_task(
        _run_ollama_download_in_background(
            task_id=task.task_id,
            model_name=body.name,
            ollama_provider=ollama_provider,
        ),
        name=f"ollama-download-{task.task_id}",
    )
    await _register_background_task(task.task_id, background_task)

    return _task_to_response(task)


@router.get(
    "/download-status",
    response_model=List[OllamaDownloadTaskResponse],
    summary="Get Ollama download tasks",
)
async def get_ollama_download_status() -> List[OllamaDownloadTaskResponse]:
    """Return all Ollama-related download tasks."""
    tasks = await get_tasks(backend=PROVIDER_OLLAMA.id)
    return [_task_to_response(t) for t in tasks]


@router.delete(
    "/download/{task_id}",
    summary="Cancel an Ollama download task",
)
async def cancel_ollama_download(task_id: str) -> dict:
    """Cancel a pending or downloading Ollama model pull."""
    success = await cancel_task(task_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=(
                "Task not found or not cancellable "
                "(already completed/failed/cancelled)"
            ),
        )

    background_task = await _pop_background_task(task_id)
    if background_task and not background_task.done():
        background_task.cancel()

    return {"status": "cancelled", "task_id": task_id}


@router.delete(
    "/{name:path}",
    summary="Delete an Ollama model",
)
async def delete_ollama_model(
    request: Request,
    name: str,
) -> dict:
    """Delete an Ollama model via the SDK."""
    ollama_provider = request.app.state.provider_manager.get_provider(
        PROVIDER_OLLAMA.id,
    )

    try:
        await ollama_provider.delete_model(model_id=name)  # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Ollama SDK not installed. Install with: "
            "pip install 'copaw[ollama]'",
        ) from exc
    except (ValueError, RuntimeError, OSError, ConnectionError) as exc:
        logger.exception("Failed to delete Ollama model: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "name": name}
