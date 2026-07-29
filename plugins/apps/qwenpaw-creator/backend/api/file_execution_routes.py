# -*- coding: utf-8 -*-
"""File-native SpecialistRun and Task query/cancellation routes."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import Field

from domain.enums import (
    CreatorCommandType,
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from domain.errors import ConflictError, NotFoundError, StorageIntegrityError
from schemas.common import StrictModel
from services.project_files.facade import CreatorFileServices
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskRecord,
)
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ExecutionStoreError,
    ProjectExecutionStore,
)

from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
)


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["runtime-files"],
    route_class=CreatorErrorRoute,
)

_TIMELINE_RENDER_JOBS: dict[
    tuple[str, str, str],
    tuple[str, asyncio.Task[None]],
] = {}
_TIMELINE_RENDER_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


async def drain_timeline_render_jobs(timeout_seconds: float = 15.0) -> None:
    """Cancel render coroutines and wait for real completion at shutdown.

    Cancellation only interrupts the async portions; a worker inside a
    ``to_thread``/subprocess segment finishes that segment first. Entries
    whose tasks are still running after the timeout stay registered.
    """

    pending = [
        task for _, task in _TIMELINE_RENDER_JOBS.values() if not task.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=timeout_seconds)
    for identity, (_, task) in list(_TIMELINE_RENDER_JOBS.items()):
        if task.done():
            _TIMELINE_RENDER_JOBS.pop(identity, None)
    for identity, lock in list(_TIMELINE_RENDER_LOCKS.items()):
        if identity not in _TIMELINE_RENDER_JOBS and not lock.locked():
            _TIMELINE_RENDER_LOCKS.pop(identity, None)


class TaskCancelRequest(StrictModel):
    reason: str = Field(default="用户取消", min_length=1, max_length=1000)


class ExecutionAuthorizationDecisionRequest(StrictModel):
    authorization_token: str = Field(alias="authorizationToken", min_length=1)


class ExecutionAuthorizationApprovalRequest(
    ExecutionAuthorizationDecisionRequest,
):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    max_cost: float = Field(alias="maxCost", ge=0)
    max_candidates: int = Field(alias="maxCandidates", ge=1)


_ROLE_LABELS = {
    "source_intelligence_agent": "素材理解",
    "visual_development_agent": "视觉开发",
    "r2v_generation_director": "视频生成",
    "ai_editing_director": "AI 剪辑",
}


def _store(services: CreatorFileServices) -> ProjectExecutionStore:
    return ProjectExecutionStore(services.root)


def _translate(error: BaseException) -> None:
    if isinstance(error, RecordNotFoundError):
        raise NotFoundError("Runtime 记录不存在") from error
    if isinstance(error, ExecutionStateConflict):
        raise ConflictError(str(error)) from error
    if isinstance(error, ExecutionStoreError):
        raise StorageIntegrityError(str(error)) from error
    raise error


def _task_view(task: TaskRecord) -> dict[str, Any]:
    target_ref = str(task.metadata.get("targetRef") or "")
    if not target_ref and task.input_refs:
        target_ref = task.input_refs[0]
    return {
        "id": task.task_id,
        "projectId": task.project_id,
        "transactionId": task.round_id,
        "specialistRunId": task.run_id,
        "kind": task.kind.value,
        "targetRef": target_ref,
        "status": task.status.value,
        "progress": task.progress,
        "completedElements": task.metadata.get("completedElements"),
        "totalElements": task.metadata.get("totalElements"),
        "resultRefs": task.output_refs,
        "result": task.result,
        "error": task.error,
        "createdAt": task.created_at.isoformat(),
        "updatedAt": task.updated_at.isoformat(),
    }


def _active_timeline_compose_task(
    services: CreatorFileServices,
    project_id: str,
    target_ref: str,
) -> TaskRecord | None:
    return next(
        (
            task
            for task in _store(services).list_tasks(project_id)
            if task.kind is TaskKind.COMPOSE
            and task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}
            and str(task.metadata.get("targetRef") or "") == target_ref
        ),
        None,
    )


def _render_dispatch_view(
    services: CreatorFileServices,
    project_id: str,
    *,
    task_id: str,
    replayed: bool,
) -> dict[str, Any]:
    snapshot = services.projects.read(project_id)
    return {
        "ok": True,
        "taskId": task_id,
        "artifactVersionId": None,
        "generation": snapshot.generation,
        "etag": snapshot.etag,
        "replayed": replayed,
    }


def _cancel_task_sync(
    services: CreatorFileServices,
    project_id: str,
    task_id: str,
    reason: str,
) -> TaskRecord:
    store = _store(services)
    # Runtime publishers use this same outer lock and then the Runtime record
    # lock.  Cancellation therefore cannot overtake a Project publication and
    # leave a committed result carrying a CANCELLED Task head.
    with services.projects.lifecycle_lock(project_id):
        services.projects.read(project_id)
        task = store.get_task(
            project_id,
            task_id,
            _lifecycle_lock_held=True,
        )
        if task.status is TaskStatus.CANCELLED:
            return task
        return store.transition_task(
            project_id,
            task_id,
            expected_status={TaskStatus.QUEUED, TaskStatus.RUNNING},
            status=TaskStatus.CANCELLED,
            updates={
                "error": {
                    "code": "USER_CANCELLED",
                    "message": reason.strip(),
                },
            },
            _lifecycle_lock_held=True,
        )


def _run_view(
    run: SpecialistRunRecord,
    tasks: list[TaskRecord],
) -> dict[str, Any]:
    return {
        "id": run.run_id,
        "role": run.role.value,
        "displayName": _ROLE_LABELS.get(run.role.value, run.role.value),
        "status": run.status.value,
        "targetRefs": run.target_refs,
        "relatedRunId": run.related_run_id,
        "supersedesRunId": run.supersedes_run_id,
        "finalMarker": run.final_marker,
        "finalSummaryText": run.final_summary_text,
        "taskRefs": [
            item.task_id for item in tasks if item.run_id == run.run_id
        ],
        "transactionId": run.round_id,
        "createdAt": run.created_at.isoformat(),
        "updatedAt": run.updated_at.isoformat(),
        "metadata": {
            key: value
            for key, value in run.metadata.items()
            if key not in {"hiddenReasoning", "providerRawMessages"}
        },
    }


def _authorization_view(
    record: ExecutionAuthorizationRecord,
) -> dict[str, Any]:
    status_value = (
        "DECLINED"
        if record.status is ExecutionAuthorizationStatus.REJECTED
        else record.status.value
    )
    scope = dict(record.scope or {})
    scope.setdefault("operation", record.operation)
    scope.setdefault("message", record.summary)
    billing = scope.get("billing")
    currency = billing.get("currency") if isinstance(billing, dict) else None
    return {
        "id": record.authorization_id,
        "transactionId": record.round_id,
        "specialistRunId": record.run_id,
        "executionRequestId": record.execution_request_id,
        "targetRef": record.target_scope[0],
        "scope": scope,
        "status": status_value,
        "authorizationToken": record.authorization_token,
        "provider": record.requested_provider or "creator-tool",
        "model": record.requested_model or "configured",
        "estimatedCost": record.estimated_cost,
        "currency": currency,
        "maxCandidates": record.requested_candidates or 1,
        "createdAt": record.created_at.isoformat(),
    }


@router.get("/specialist-runs")
async def list_specialist_runs(
    project_id: str,
    run_status: SpecialistRunStatus | None = Query(None, alias="status"),
    role: SpecialistRole | None = Query(None),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    store = _store(services)
    try:
        runs, tasks = await asyncio.gather(
            asyncio.to_thread(store.list_specialist_runs, project_id),
            asyncio.to_thread(store.list_tasks, project_id),
        )
    except BaseException as error:
        _translate(error)
    if run_status is not None:
        runs = [item for item in runs if item.status is run_status]
    if role is not None:
        runs = [item for item in runs if item.role is role]
    return {"items": [_run_view(item, tasks) for item in runs]}


@router.get("/specialist-runs/{run_id}")
async def get_specialist_run(
    project_id: str,
    run_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    store = _store(services)
    try:
        run, tasks = await asyncio.gather(
            asyncio.to_thread(store.get_specialist_run, project_id, run_id),
            asyncio.to_thread(store.list_tasks, project_id),
        )
    except BaseException as error:
        _translate(error)
    return _run_view(run, tasks)


@router.get("/tasks")
async def list_tasks(
    project_id: str,
    task_status: TaskStatus | None = Query(None, alias="status"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    try:
        tasks = await asyncio.to_thread(
            _store(services).list_tasks,
            project_id,
        )
    except BaseException as error:
        _translate(error)
    if task_status is not None:
        tasks = [item for item in tasks if item.status is task_status]
    return {"items": [_task_view(item) for item in tasks]}


@router.get("/tasks/{task_id}")
async def get_task(
    project_id: str,
    task_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    try:
        task = await asyncio.to_thread(
            _store(services).get_task,
            project_id,
            task_id,
        )
    except BaseException as error:
        _translate(error)
    return _task_view(task)


@router.post("/tasks/{task_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_task(
    project_id: str,
    task_id: str,
    request: TaskCancelRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    resolve_idempotency_key(idempotency_key)
    try:
        task = await asyncio.to_thread(
            _cancel_task_sync,
            services,
            project_id,
            task_id,
            request.reason,
        )
    except BaseException as error:
        _translate(error)
    if task.kind is TaskKind.R2V_GENERATION:
        from services.media_files.r2v_execution import (
            file_r2v_execution_service,
        )

        file_r2v_execution_service(services).notify_terminal_task(task)
    return _task_view(task)


@router.post(
    "/timelines/{timeline_id}/render",
    status_code=status.HTTP_202_ACCEPTED,
)
async def render_timeline(
    project_id: str,
    timeline_id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    """User-initiated final video export: deterministic local composition,
    bypassing the Agent pipeline.

    Reads all ready R2V/Edit elements of the target Timeline and composes
    them in span order; the result is written to the timeline render
    ArtifactSlot, and the frontend switches to the final-video preview after
    the next snapshot poll.
    """

    key = resolve_idempotency_key(idempotency_key)
    target_ref = f"timeline:{timeline_id}"
    from services.media_files.local_execution import (
        execute_file_local_media_command,
        file_local_media_task_id,
        find_reusable_local_media_task,
        validate_local_media_execution,
    )

    identity = (str(services.root), project_id, timeline_id)
    lock = _TIMELINE_RENDER_LOCKS.setdefault(identity, asyncio.Lock())
    async with lock:
        running = _TIMELINE_RENDER_JOBS.get(identity)
        if running is not None and not running[1].done():
            return await asyncio.to_thread(
                _render_dispatch_view,
                services,
                project_id,
                task_id=running[0],
                replayed=True,
            )

        active = await asyncio.to_thread(
            _active_timeline_compose_task,
            services,
            project_id,
            target_ref,
        )
        if active is not None:
            return await asyncio.to_thread(
                _render_dispatch_view,
                services,
                project_id,
                task_id=active.task_id,
                replayed=True,
            )

        reusable = await asyncio.to_thread(
            find_reusable_local_media_task,
            services,
            project_id=project_id,
            command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
            target_ref=target_ref,
        )
        if reusable is not None:
            # Render content is unchanged since the last successful
            # composition and the artifact is still fresh: replay the
            # succeeded Task; the frontend keeps using the existing video
            # once it observes the terminal state.
            return await asyncio.to_thread(
                _render_dispatch_view,
                services,
                project_id,
                task_id=reusable.task_id,
                replayed=True,
            )

        task_id = file_local_media_task_id(project_id, key)

        # When the background drive() fails before the Task is created there
        # is nowhere to persist the error, and the frontend would wait for a
        # Task that never exists. Pre-validate the execution plan
        # synchronously so structural problems (e.g. Overlay stacking the
        # local runner cannot handle) return 400 to the caller directly.
        await asyncio.to_thread(
            validate_local_media_execution,
            services,
            project_id=project_id,
            command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
            target_ref=target_ref,
        )

        async def drive() -> None:
            try:
                await execute_file_local_media_command(
                    services,
                    project_id=project_id,
                    command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
                    target_ref=target_ref,
                    arguments={},
                    idempotency_key=key,
                )
            except asyncio.CancelledError:
                raise
            except BaseException:
                # The execution service persists terminal failure details on
                # the durable Task; clients observe them through task polling.
                return

        background = asyncio.create_task(
            drive(),
            name=f"timeline-render:{project_id}:{timeline_id}:{task_id}",
        )
        _TIMELINE_RENDER_JOBS[identity] = (task_id, background)

        def completed(done: asyncio.Task[None]) -> None:
            if _TIMELINE_RENDER_JOBS.get(identity) == (task_id, done):
                _TIMELINE_RENDER_JOBS.pop(identity, None)
            lock = _TIMELINE_RENDER_LOCKS.get(identity)
            if lock is not None and not lock.locked():
                _TIMELINE_RENDER_LOCKS.pop(identity, None)
            if not done.cancelled():
                done.exception()

        background.add_done_callback(completed)
        return await asyncio.to_thread(
            _render_dispatch_view,
            services,
            project_id,
            task_id=task_id,
            replayed=False,
        )


@router.get("/execution-authorizations")
async def list_execution_authorizations(
    project_id: str,
    authorization_status: str | None = Query(None, alias="status"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    try:
        records = await asyncio.to_thread(
            _store(services).list_execution_authorizations,
            project_id,
        )
    except BaseException as error:
        _translate(error)
    if authorization_status:
        requested = (
            "REJECTED"
            if authorization_status == "DECLINED"
            else authorization_status
        )
        records = [item for item in records if item.status.value == requested]
    return {"items": [_authorization_view(item) for item in records]}


@router.get("/execution-authorizations/{authorization_id}")
async def get_execution_authorization(
    project_id: str,
    authorization_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    try:
        record = await asyncio.to_thread(
            _store(services).get_execution_authorization,
            project_id,
            authorization_id,
        )
    except BaseException as error:
        _translate(error)
    return _authorization_view(record)


async def _decide_authorization(
    *,
    project_id: str,
    authorization_id: str,
    authorization_token: str,
    target_status: ExecutionAuthorizationStatus,
    decision: dict[str, Any] | None,
    services: CreatorFileServices,
) -> dict[str, Any]:
    store = _store(services)
    try:
        current = await asyncio.to_thread(
            store.get_execution_authorization,
            project_id,
            authorization_id,
        )
        if not secrets.compare_digest(
            current.authorization_token,
            authorization_token,
        ):
            raise ConflictError("execution authorization token 不匹配")
        if current.status is target_status:
            return _authorization_view(current)
        if target_status is ExecutionAuthorizationStatus.APPROVED:
            assert decision is not None
            if (
                decision.get("provider") != current.requested_provider
                or decision.get("model") != current.requested_model
            ):
                raise ConflictError("批准的 provider/model 必须与原执行请求一致")
            requested_candidates = current.requested_candidates or 1
            if int(decision.get("maxCandidates") or 0) > requested_candidates:
                raise ConflictError("批准的候选数量不能超过原执行请求")
        record = await asyncio.to_thread(
            store.decide_execution_authorization,
            project_id,
            authorization_id,
            authorization_token=authorization_token,
            status=target_status,
            decision=decision,
        )
    except BaseException as error:
        _translate(error)
    return _authorization_view(record)


@router.post("/execution-authorizations/{authorization_id}/approve")
async def approve_execution_authorization(
    project_id: str,
    authorization_id: str,
    request: ExecutionAuthorizationApprovalRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    resolve_idempotency_key(idempotency_key)
    return await _decide_authorization(
        project_id=project_id,
        authorization_id=authorization_id,
        authorization_token=request.authorization_token,
        target_status=ExecutionAuthorizationStatus.APPROVED,
        decision={
            "provider": request.provider,
            "model": request.model,
            "maxCost": request.max_cost,
            "maxCandidates": request.max_candidates,
        },
        services=services,
    )


@router.post("/execution-authorizations/{authorization_id}/decline")
async def decline_execution_authorization(
    project_id: str,
    authorization_id: str,
    request: ExecutionAuthorizationDecisionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    resolve_idempotency_key(idempotency_key)
    return await _decide_authorization(
        project_id=project_id,
        authorization_id=authorization_id,
        authorization_token=request.authorization_token,
        target_status=ExecutionAuthorizationStatus.REJECTED,
        decision=None,
        services=services,
    )


__all__ = ["router"]
