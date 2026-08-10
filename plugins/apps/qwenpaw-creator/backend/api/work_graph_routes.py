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

from domain.errors import NotFoundError, ValidationError
from models.config import get_media_call_budget
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
    graph = derive_work_graph(snapshot.project, tasks=tasks)
    return {
        "projectId": project_id,
        "generation": graph.generation,
        "counts": graph.counts(),
        # Honest spend metric: billable provider calls, never estimated money.
        "mediaCalls": media_call_count(services, project_id),
        "mediaCallBudget": get_media_call_budget(),
        "nodes": [
            {
                "id": node.node_id,
                "kind": node.kind,
                "label": node.label,
                "status": node.status.value,
                "deps": list(node.deps),
                "lane": node.lane,
                "taskId": node.task_id,
                "progress": node.progress,
                "error": node.error,
                "missing": list(node.missing),
                "locator": node.locator,
                "dispatchable": node.command is not None,
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
    response.headers["Cache-Control"] = "no-store"
    return payload


@router.post("/work-graph/nodes/{node_id:path}/dispatch")
async def dispatch_work_graph_node(
    project_id: str,
    node_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    snapshot = await asyncio.to_thread(_read_project, project_id, services)
    tasks = await asyncio.to_thread(
        ProjectExecutionStore(services.root).list_tasks,
        project_id,
    )
    graph = derive_work_graph(snapshot.project, tasks=tasks)
    node = graph.by_id.get(node_id)
    if node is None:
        raise NotFoundError(f"work-graph 节点不存在: {node_id}")
    if node.command is None:
        raise ValidationError(f"节点 {node_id} 不支持直接派发")
    if node.status.value in ("running", "done"):
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
    await scheduler.dispatch_node(project_id, node)
    return {
        "ok": True,
        "nodeId": node_id,
        "status": "dispatched",
        "dispatched": True,
    }


__all__ = ["router"]
