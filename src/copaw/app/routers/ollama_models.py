# -*- coding: utf-8 -*-
"""API endpoints for Ollama model management.

This router mirrors the local_models router but delegates lifecycle operations
(list / pull / delete) to the Ollama daemon via OllamaModelManager. Downloads
run in the background and their status can be polled by the frontend.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..download_task_store import (
    DownloadTask,
    DownloadTaskStatus,
    clear_completed,
    create_task,
    get_tasks,
    update_status,
    cancel_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ollama-models", tags=["ollama-models"])


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


@router.get(
    "",
    response_model=List[OllamaModelResponse],
    summary="List Ollama models",
)
async def list_ollama_models() -> List[OllamaModelResponse]:
    """Return the current Ollama model list via the SDK.

    If the Ollama SDK is not installed, returns HTTP 501.
    """
    try:
        from ...providers.ollama_manager import OllamaModelManager
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail=(
                "Ollama SDK not installed. Install with: pip install ollama"
            ),
        ) from exc

    try:
        models = OllamaModelManager.list_models()
    except Exception as exc:
        if _is_ollama_connection_error(exc):
            logger.warning(
                "Failed to connect to Ollama while listing models: %s",
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Failed to connect to Ollama. "
                    "Please ensure Ollama is installed and running."
                ),
            ) from exc
        logger.exception("Failed to list Ollama models")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list Ollama models: {exc}",
        ) from exc

    return [OllamaModelResponse(**m.model_dump()) for m in models]


@router.post(
    "/download",
    response_model=OllamaDownloadTaskResponse,
    summary="Start a background Ollama model pull",
)
async def download_ollama_model(
    body: OllamaDownloadRequest,
) -> OllamaDownloadTaskResponse:
    """Start a background pull via Ollama SDK.

    Returns a task_id immediately; the frontend can poll /download-status
    to track progress.
    """
    await clear_completed(backend="ollama")

    task = await create_task(
        repo_id=body.name,
        filename=None,
        backend="ollama",
        source="ollama",
    )

    loop = asyncio.get_running_loop()
    asyncio.create_task(
        _run_pull_in_background(task.task_id, body.name, loop),
        name=f"ollama-download-{task.task_id}",
    )

    return _task_to_response(task)


async def _run_pull_in_background(
    task_id: str,
    name: str,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Execute the Ollama pull in a thread and update task status."""
    from ...providers.ollama_manager import OllamaModelManager, OllamaModelInfo

    await update_status(task_id, DownloadTaskStatus.DOWNLOADING)

    try:
        info: OllamaModelInfo = await loop.run_in_executor(
            None,
            lambda: OllamaModelManager.pull_model(name),
        )
        result_dict = info.model_dump()
        await update_status(
            task_id,
            DownloadTaskStatus.COMPLETED,
            result=result_dict,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Ollama model pull failed: %s", exc)
        await update_status(
            task_id,
            DownloadTaskStatus.FAILED,
            error=str(exc),
        )


@router.get(
    "/download-status",
    response_model=List[OllamaDownloadTaskResponse],
    summary="Get Ollama download tasks",
)
async def get_ollama_download_status() -> List[OllamaDownloadTaskResponse]:
    """Return all Ollama-related download tasks."""
    tasks = await get_tasks(backend="ollama")
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
            detail=f"Task {task_id} not found or not cancellable",
        )
    return {"status": "cancelled", "task_id": task_id}


@router.delete(
    "/{name:path}",
    summary="Delete an Ollama model",
)
async def delete_ollama_model(name: str) -> dict:
    """Delete an Ollama model via the SDK."""
    try:
        from ...providers.ollama_manager import OllamaModelManager
    except ImportError as exc:  # pragma: no cover - import guard
        raise HTTPException(
            status_code=501,
            detail="Ollama SDK not installed.",
        ) from exc

    try:
        OllamaModelManager.delete_model(name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to delete Ollama model: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "deleted", "name": name}
