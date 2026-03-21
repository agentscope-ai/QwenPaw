# -*- coding: utf-8 -*-
"""API endpoints for local model management."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..download_task_store import (
    DownloadTask,
    DownloadTaskStatus,
    cancel_task,
    clear_completed,
    create_task,
    get_task,
    get_tasks,
    update_status,
)
from ...providers import ProviderManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-models", tags=["local-models"])

_background_tasks: Dict[str, asyncio.Task] = {}
_background_tasks_lock = asyncio.Lock()


class DownloadRequest(BaseModel):
    repo_id: str = Field(..., description="Hugging Face or ModelScope repo ID")
    filename: Optional[str] = Field(
        None,
        description="Specific file to download",
    )
    backend: str = Field("llamacpp", description="Backend: llamacpp or mlx")
    source: str = Field(
        "huggingface",
        description="Source: huggingface or modelscope",
    )


class LocalModelResponse(BaseModel):
    id: str
    repo_id: str
    filename: str
    backend: str
    source: str
    file_size: int
    local_path: str
    display_name: str


class DownloadTaskResponse(BaseModel):
    task_id: str
    status: str
    repo_id: str
    filename: Optional[str] = None
    backend: str
    source: str
    error: Optional[str] = None
    result: Optional[LocalModelResponse] = None


def _task_to_response(task: DownloadTask) -> DownloadTaskResponse:
    result = None
    if task.result:
        result = LocalModelResponse(**task.result)
    return DownloadTaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        repo_id=task.repo_id,
        filename=task.filename,
        backend=task.backend,
        source=task.source,
        error=task.error,
        result=result,
    )


async def _register_background_task(task_id: str, task: asyncio.Task) -> None:
    async with _background_tasks_lock:
        _background_tasks[task_id] = task


async def _pop_background_task(task_id: str) -> Optional[asyncio.Task]:
    async with _background_tasks_lock:
        return _background_tasks.pop(task_id, None)


@router.get(
    "",
    response_model=List[LocalModelResponse],
    summary="List downloaded local models",
)
async def list_local(
    backend: Optional[str] = None,
) -> List[LocalModelResponse]:
    try:
        from ...local_models import list_local_models, BackendType
    except ImportError:
        return []

    backend_type = BackendType(backend) if backend else None
    return [
        LocalModelResponse(
            id=m.id,
            repo_id=m.repo_id,
            filename=m.filename,
            backend=m.backend.value,
            source=m.source.value,
            file_size=m.file_size,
            local_path=m.local_path,
            display_name=m.display_name,
        )
        for m in list_local_models(backend=backend_type)
    ]


@router.post(
    "/download",
    response_model=DownloadTaskResponse,
    summary="Start a background model download",
)
async def download_model(
    body: DownloadRequest,
) -> DownloadTaskResponse:
    """Start a background download. Returns a task_id immediately."""
    try:
        from ...local_models import BackendType, DownloadSource
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail=(
                "Local model dependencies not installed. "
                "Install with: pip install 'copaw[local]'"
            ),
        ) from exc

    # Validate enum values early
    try:
        BackendType(body.backend)
        DownloadSource(body.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await clear_completed(backend=body.backend)
    task = await create_task(
        repo_id=body.repo_id,
        filename=body.filename,
        backend=body.backend,
        source=body.source,
    )

    background_task = asyncio.create_task(
        _run_download_in_background(
            task_id=task.task_id,
            body=body,
        ),
        name=f"model-download-{task.task_id}",
    )
    await _register_background_task(task.task_id, background_task)

    return _task_to_response(task)


async def _run_download_in_background(
    task_id: str,
    body: DownloadRequest,
) -> None:
    """Execute the download in a thread and update task status."""
    from ..console_push_store import append as push_store_append
    from ...local_models import BackendType, DownloadSource, LocalModelManager

    # Check if task was cancelled before starting
    task = await get_task(task_id)
    if task and task.status == DownloadTaskStatus.CANCELLED:
        logger.info("Task %s was cancelled before download started", task_id)
        await _pop_background_task(task_id)
        return

    await update_status(task_id, DownloadTaskStatus.DOWNLOADING)

    try:
        loop = asyncio.get_running_loop()
        # Periodically check if task was cancelled during download
        # We run the download in executor, but check cancellation status
        info = await loop.run_in_executor(
            None,
            lambda: LocalModelManager.download_model_sync(
                repo_id=body.repo_id,
                filename=body.filename,
                backend=BackendType(body.backend),
                source=DownloadSource(body.source),
            ),
        )

        # Check if cancelled after download completes but before marking
        # complete
        task = await get_task(task_id)
        if task and task.status == DownloadTaskStatus.CANCELLED:
            logger.info(
                "Task %s was cancelled after download, cleaning up",
                task_id,
            )
            # Try to delete the downloaded model
            try:
                from ...local_models import delete_local_model

                delete_local_model(info.id)
            except Exception:
                pass
            await _pop_background_task(task_id)
            return

        result_dict = {
            "id": info.id,
            "repo_id": info.repo_id,
            "filename": info.filename,
            "backend": info.backend.value,
            "source": info.source.value,
            "file_size": info.file_size,
            "local_path": info.local_path,
            "display_name": info.display_name,
        }
        await update_status(
            task_id,
            DownloadTaskStatus.COMPLETED,
            result=result_dict,
        )
        await push_store_append(
            "console",
            f"Model downloaded: {info.display_name}",
        )
        ProviderManager.get_instance().update_local_models()
    except asyncio.CancelledError:
        await update_status(task_id, DownloadTaskStatus.CANCELLED)
        logger.info("Local model download task %s cancelled", task_id)
        raise
    except Exception as exc:
        logger.exception("Background model download failed: %s", exc)
        await update_status(
            task_id,
            DownloadTaskStatus.FAILED,
            error=str(exc),
        )
        await push_store_append(
            "console",
            f"Model download failed: {body.repo_id} — {exc}",
        )
    finally:
        await _pop_background_task(task_id)


@router.get(
    "/download-status",
    response_model=List[DownloadTaskResponse],
    summary="Get active download tasks",
)
async def get_download_status(
    backend: Optional[str] = None,
) -> List[DownloadTaskResponse]:
    tasks = await get_tasks(backend=backend)
    return [_task_to_response(t) for t in tasks]


@router.delete(
    "/{model_id:path}",
    summary="Delete a downloaded local model",
)
async def delete_local(model_id: str) -> dict:
    try:
        from ...local_models import delete_local_model
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Local model dependencies not installed.",
        ) from exc

    try:
        delete_local_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ProviderManager.get_instance().update_local_models()

    return {"status": "deleted", "model_id": model_id}


async def _cancel_download_task(task_id: str) -> dict:
    """Cancel a pending or downloading task and stop its
    background coroutine."""
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


@router.post(
    "/cancel-download/{task_id}",
    summary="Cancel an active download task",
)
async def cancel_download(task_id: str) -> dict:
    """Cancel a pending or downloading task."""
    return await _cancel_download_task(task_id)
