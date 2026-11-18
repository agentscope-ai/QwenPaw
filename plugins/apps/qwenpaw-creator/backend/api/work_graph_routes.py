# -*- coding: utf-8 -*-
"""Work-graph HTTP surface: read the production DAG, dispatch one node.

The graph is derived on demand from durable facts (never persisted), so
GET is cheap and always current. Manual dispatch is the human override:
it bypasses the scheduler's once-per-fingerprint ledger deliberately —
a person clicking retry is an explicit instruction.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from domain.errors import NotFoundError, ValidationError
from models.config import (
    get_media_call_budget,
    get_image_model_name,
    get_video_model_name,
)
from services.file_agent_runtime import manual_regeneration_hold
from services.file_agent_runtime.work_graph import derive_work_graph
from services.file_agent_runtime.work_scheduler import WorkGraphScheduler
from services.media_files.call_budget import media_call_count
from services.project_files.facade import CreatorFileServices
from services.project_files.store import ProjectNotFound
from services.runtime_files.execution_store import ProjectExecutionStore

from .dependencies import CreatorErrorRoute, project_file_services

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["work-graph"],
    route_class=CreatorErrorRoute,
)


def _graph_payload(project_id: str, services: CreatorFileServices) -> dict:
    try:
        snapshot = services.projects.read(project_id)
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc
    tasks = ProjectExecutionStore(services.root).list_tasks(project_id)
    graph = derive_work_graph(
        snapshot.project,
        tasks=tasks,
        media_models=(get_image_model_name(), get_video_model_name()),
    )
    hold = manual_regeneration_hold.ManualRegenerationHoldStore(
        services.root,
    ).read(project_id)
    return {
        "projectId": project_id,
        "manualHold": hold.payload(),
        "generation": graph.generation,
        "counts": graph.counts(),
        # Honest spend metric: billable provider calls, never estimated money.
        "mediaCalls": media_call_count(services, project_id),
        "mediaCallBudget": get_media_call_budget(),
        "nodes": [
            {
                "id": node.node_id,
                "manuallyHeld": node.node_id in hold.node_ids,
                "kind": node.kind,
                "label": node.label,
                "status": node.status.value,
                "deps": list(node.deps),
                "lane": node.lane,
                "timelineId": node.timeline_id,
                "taskId": node.task_id,
                "progress": node.progress,
                "error": node.error,
                "missing": list(node.missing),
                "locator": node.locator,
                "dispatchable": node.command is not None,
                "promptSyncRequired": node.prompt_sync_required,
                "preparationState": (
                    "waiting" if node.prompt_sync_required else None
                ),
            }
            for node in graph.nodes
        ],
    }


def _read_project(project_id: str, services: CreatorFileServices):
    try:
        return services.projects.read(project_id)
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc


@router.get("/work-graph")
async def get_work_graph(
    project_id: str,
    response: Response,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    payload = await asyncio.to_thread(_graph_payload, project_id, services)
    # Read process activity on the event loop that owns the scheduler. A
    # saved synchronization gap alone is never evidence of user action.
    from services.file_agent_runtime.registry import get_creator_agent_runtime

    runtime = get_creator_agent_runtime()
    if runtime is not None and runtime.services.root == services.root:
        for node in payload["nodes"]:
            if node["promptSyncRequired"]:
                preparation = runtime.work_scheduler.prompt_preparation_status(
                    project_id,
                    node["id"],
                )
                node["preparationState"] = preparation["state"]
                if preparation.get("error"):
                    node["error"] = preparation["error"]
    response.headers["Cache-Control"] = "no-store"
    return payload


class ResumeWorkGraphBody(BaseModel):
    revision: int = Field(ge=0, strict=True)


@router.post("/work-graph/resume")
async def resume_work_graph(
    project_id: str,
    body: ResumeWorkGraphBody,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    await asyncio.to_thread(_read_project, project_id, services)
    await asyncio.to_thread(
        manual_regeneration_hold.ManualRegenerationHoldStore(
            services.root,
        ).resume,
        project_id,
        body.revision,
    )
    from services.file_agent_runtime.registry import get_creator_agent_runtime

    runtime = get_creator_agent_runtime()
    if runtime is not None and runtime.services.root == services.root:
        runtime.work_scheduler.wake(project_id)
    return {"ok": True}


@router.post("/work-graph/nodes/{node_id:path}/dispatch")
async def dispatch_work_graph_node(
    project_id: str,
    node_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    snapshot = await asyncio.to_thread(_read_project, project_id, services)
    holds = manual_regeneration_hold.ManualRegenerationHoldStore(services.root)
    hold_state = await asyncio.to_thread(holds.read, project_id)
    if not hold_state.project_identity.endswith(
        ":" + snapshot.project.model_dump(mode="json")["created_at"],
    ):
        raise manual_regeneration_hold.ManualHoldConflict(
            "Project lifetime changed",
        )
    tasks = await asyncio.to_thread(
        ProjectExecutionStore(services.root).list_tasks,
        project_id,
    )
    graph = derive_work_graph(
        snapshot.project,
        tasks=tasks,
        media_models=(get_image_model_name(), get_video_model_name()),
    )
    node = graph.by_id.get(node_id)
    if node is None:
        raise NotFoundError(f"work-graph 节点不存在: {node_id}")
    if node.command is None:
        raise ValidationError(f"节点 {node_id} 不支持直接派发")
    if node.status.value == "running":
        # An in-flight execution is provider spend already committed; the
        # click races the run instead of authorizing a second one.
        return {
            "ok": True,
            "nodeId": node_id,
            "status": node.status.value,
            "dispatched": False,
        }
    if node.missing:
        raise ValidationError(
            f"节点 {node_id} 的依赖未就绪：" + "、".join(node.missing[:5]),
        )
    scheduler = WorkGraphScheduler(services)
    operation = await asyncio.to_thread(
        holds.begin,
        project_id,
        node,
        graph.nodes,
        expected_identity=hold_state.project_identity,
        existing_output=bool(
            node.kind == "compose"
            and (
                slot := snapshot.project.assets.artifact_slots_by_id.get(
                    f"{node.target_ref}:render",
                )
            )
            and slot.selected_version_id,
        ),
    )
    fingerprint = scheduler.manual_retry_fingerprint(node, tasks)
    admission = manual_regeneration_hold.ManualAdmission(
        holds,
        operation,
        project_id,
        # Admission must use the scheduler's exact durable request key.
        # pylint: disable-next=protected-access
        f"dag-{node.node_id}-{scheduler._dispatch_slot(fingerprint)}",
        node_id=node.node_id,
    )
    with manual_regeneration_hold.manual_admission(admission):
        try:
            await scheduler.dispatch_node(
                project_id,
                node,
                fingerprint,
                expected_object_versions=(
                    f"project:{snapshot.etag}:work-graph",
                ),
            )
        except Exception:
            try:
                await asyncio.to_thread(
                    holds.finish,
                    admission,
                    succeeded=False,
                )
            except Exception:
                # An unreadable admission ledger is not proof of rejection.
                pass
            raise
        await asyncio.to_thread(holds.finish, admission, succeeded=True)
    return {
        "ok": True,
        "nodeId": node_id,
        "status": "dispatched",
        "dispatched": True,
    }


__all__ = ["router"]
