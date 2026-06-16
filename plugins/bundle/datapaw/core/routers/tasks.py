# -*- coding: utf-8 -*-
"""DataPaw task-panel REST API.

All paths below are relative to host's ``/api/tasks`` mount.

Read endpoints:

- ``GET  /{session_id}`` — current_plan + history + artifacts summary.
- ``GET  /{session_id}/sop`` — active graph SOP YAML (minimal contract).
- ``GET  /{session_id}/dag`` — active graph DAG YAML (structure + runtime).
- ``GET  /{session_id}/history/{plan_id}`` — fetch one historical graph.
- ``GET  /{session_id}/history/{plan_id}/sop`` — historical SOP YAML.
- ``GET  /{session_id}/files`` — list cumulative artifacts (filter by ids).
- ``GET  /{session_id}/files/preview`` — inline preview via ``?path=``.
- ``GET  /{session_id}/files/download`` — download one file via ``?path=``.
- ``GET  /{session_id}/files/resource`` — proxy any file under artifacts root.

Write endpoints (only run while no agent is active, else 409):

- ``PUT  /{session_id}/sop`` — replace the active graph from an SOP YAML.
- ``PUT  /{session_id}/dag`` — merge a DAG patch into the active graph.

SOP minimal contract: only structural fields are allowed (graph:
name / description / expected_outcome; node: node_id / name /
description / expected_outcome / deps). Runtime fields are rejected.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ..orchestration.dag_store import DAGBroadcaster, DAGStore, format_sse
from ..orchestration.task_graph import Sop, TaskGraph
from .tasks_utils import (
    PnContext,
    archive_current_plan_to_pn,
    build_file_urls,
    check_not_running,
    ensure_plan_notebook_keys,
    extract_artifacts,
    get_session_for_agent,
    get_workspace_for_agent,
    load_pn_for_request,
    persist_pn,
    resolve_request_api_origin,
    safe_filename,
    serve_artifact_file,
    serve_resource_file,
)

# Prefix is applied at mount time by host's ``api.register_http_router``
# (host prepends ``/api`` automatically), so this router carries no prefix
# of its own. See plugin.py for the registration call.
router = APIRouter(tags=["datapaw-tasks"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HistoricalPlanSummary(BaseModel):
    """Summary entry for an archived graph."""

    id: str
    name: str
    state: str = "done"
    finished_at: Optional[str] = None


class GetTasksResponse(BaseModel):
    """Body of ``GET /api/tasks/{session_id}``."""

    current_plan: Optional[dict] = None
    historical_plans: List[HistoricalPlanSummary] = Field(default_factory=list)
    artifacts_summary: dict = Field(default_factory=dict)


class SOPUploadBody(BaseModel):
    """Body of ``PUT /api/tasks/{session_id}/sop`` (YAML only).

    Only SOP minimal-contract YAML text is accepted (no dict). Runtime
    fields (id / state / output / trace / ...) are rejected by
    ``from_sop``.
    """

    yaml: str = Field(
        ...,
        min_length=1,
        description="SOP YAML text (minimal-contract format).",
    )


class DAGUploadBody(BaseModel):
    """Body of ``PUT /api/tasks/{session_id}/dag`` (YAML only)."""

    yaml: str = Field(..., min_length=1, description="DAG patch YAML text.")


class Ok(BaseModel):
    ok: bool = True
    detail: Optional[str] = None
    extra: Optional[dict] = None


class FileEntry(BaseModel):
    """One file-artifact entry in the ``GET /files`` listing."""

    graph_id: str
    node_id: str
    name: str
    path: str = Field(
        description=(
            "Sandbox-view relative path, identical to FileRef.path"
            " passed to finish_subtask."
        ),
    )
    mime_type: str
    size_bytes: int
    created_at: str
    preview_url: str = Field(
        description=(
            "Pre-built relative URL; the frontend can GET it"
            " directly for inline preview."
        ),
    )
    download_url: str = Field(
        description=(
            "Pre-built relative URL; the frontend can GET it"
            " directly to download."
        ),
    )


class FilesResponse(BaseModel):
    """Body of ``GET /api/tasks/{session_id}/files``."""

    files: List[FileEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared dependencies
# ---------------------------------------------------------------------------


async def acquire_pn(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> PnContext:
    """FastAPI dependency: fetch + lock-check + load DAG runtime state."""
    workspace = await get_workspace_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    await check_not_running(workspace, session_id)

    runner = getattr(workspace, "runner", None)
    session = getattr(runner, "session", None)
    if session is None:
        raise HTTPException(status_code=503, detail="Session not ready")

    dag_store = DAGStore.from_session(session, user_id=user_id)
    pn = await dag_store.read(session_id)
    if not isinstance(pn, dict):
        pn = {}
    ensure_plan_notebook_keys(pn)
    return PnContext(
        session=session,
        session_id=session_id,
        user_id=user_id,
        dag_store=dag_store,
        pn=pn,
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}
# ---------------------------------------------------------------------------


@router.get("/{session_id}", response_model=GetTasksResponse)
async def get_tasks(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> GetTasksResponse:
    """Active-graph overview + historical-graph index + artifact summary."""
    session, _ = await get_session_for_agent(
        request,
        request.state.agent_id if hasattr(request.state, "agent_id") else None,
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )

    storage_plans = (
        pn.get("storage", {}).get("plans", {}) if isinstance(pn, dict) else {}
    )
    historical: List[HistoricalPlanSummary] = []
    for p in storage_plans.values() if isinstance(storage_plans, dict) else []:
        if not isinstance(p, dict):
            continue
        historical.append(
            HistoricalPlanSummary(
                id=p.get("id", ""),
                name=p.get("name", ""),
                state=p.get("state", "done"),
                finished_at=p.get("finished_at"),
            ),
        )

    artifacts = pn.get("artifacts", []) if isinstance(pn, dict) else []
    artifacts_summary = {
        "total": len(artifacts) if isinstance(artifacts, list) else 0,
    }

    return GetTasksResponse(
        current_plan=pn.get("current_plan") if isinstance(pn, dict) else None,
        historical_plans=historical,
        artifacts_summary=artifacts_summary,
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/sop — download active graph SOP YAML
# ---------------------------------------------------------------------------


@router.get("/{session_id}/sop")
async def get_sop(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> Response:
    """Download the active graph's SOP YAML (minimal contract)."""
    session, _ = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    current = pn.get("current_plan") if isinstance(pn, dict) else None
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=409,
            detail="No active task graph in session.",
        )
    try:
        graph = TaskGraph.model_validate(current)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse current_plan: {exc}",
        ) from exc

    yaml_content = graph.to_sop_yaml()
    filename = f"{safe_filename(graph.name)}.sop.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/dag/events — stream active graph snapshots
# ---------------------------------------------------------------------------

DAG_SSE_HEARTBEAT_SECONDS = 30.0


async def _iter_dag_sse_events(
    *,
    request: Request,
    session_id: str,
    dag_store: DAGStore,
    queue: asyncio.Queue,
) -> AsyncIterator[str]:
    try:
        snapshot = await dag_store.read(session_id)
        if snapshot is not None:
            yield format_sse(snapshot)
        while True:
            if await request.is_disconnected():
                break
            try:
                snapshot = await asyncio.wait_for(
                    queue.get(),
                    timeout=DAG_SSE_HEARTBEAT_SECONDS,
                )
                yield format_sse(snapshot)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        DAGBroadcaster.unsubscribe(session_id, queue)


@router.get("/{session_id}/dag/events")
async def stream_dag_events(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> StreamingResponse:
    """Stream DataPaw DAG snapshots over an independent SSE connection."""
    session, _ = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    dag_store = DAGStore.from_session(session, user_id=user_id)
    queue = DAGBroadcaster.subscribe(session_id)

    return StreamingResponse(
        _iter_dag_sse_events(
            request=request,
            session_id=session_id,
            dag_store=dag_store,
            queue=queue,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/dag — download active graph DAG YAML
# ---------------------------------------------------------------------------


@router.get("/{session_id}/dag")
async def get_dag(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
    include_trace: bool = Query(default=True),
) -> Response:
    """Download the active graph's DAG YAML (structure + runtime fields)."""
    session, _ = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    current = pn.get("current_plan") if isinstance(pn, dict) else None
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=409,
            detail="No active task graph in session.",
        )
    try:
        graph = TaskGraph.model_validate(current)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse current_plan: {exc}",
        ) from exc

    yaml_content = graph.to_dag_yaml(include_trace=include_trace)
    filename = f"{safe_filename(graph.name)}.dag.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/history/{plan_id}
# ---------------------------------------------------------------------------


@router.get("/{session_id}/history/{plan_id}")
async def get_historical_plan(
    session_id: str,
    plan_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> dict:
    """Return the full TaskGraph (nodes / outcome) of a historical graph."""
    session, _ = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    storage_plans = pn.get("storage", {}).get("plans", {})
    if not isinstance(storage_plans, dict) or plan_id not in storage_plans:
        raise HTTPException(
            status_code=404,
            detail=f"Historical plan '{plan_id}' not found.",
        )
    return {"plan": storage_plans[plan_id]}


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/history/{plan_id}/sop
# ---------------------------------------------------------------------------


@router.get("/{session_id}/history/{plan_id}/sop")
async def get_historical_sop(
    session_id: str,
    plan_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> Response:
    """Download a historical graph's SOP YAML (minimal contract)."""
    session, _ = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    storage_plans = pn.get("storage", {}).get("plans", {})
    if not isinstance(storage_plans, dict) or plan_id not in storage_plans:
        raise HTTPException(
            status_code=404,
            detail=f"Historical plan '{plan_id}' not found.",
        )
    try:
        graph = TaskGraph.model_validate(storage_plans[plan_id])
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse historical plan: {exc}",
        ) from exc

    yaml_content = graph.to_sop_yaml()
    filename = f"{safe_filename(graph.name)}.sop.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# PUT /api/tasks/{session_id}/sop — upload SOP (rebuild graph)
# ---------------------------------------------------------------------------


@router.put("/{session_id}/sop", response_model=Ok)
async def put_sop(
    body: SOPUploadBody = Body(...),
    ctx: PnContext = Depends(acquire_pn),
) -> Ok:
    """Upload an SOP YAML and rebuild the graph (overwrite semantics)."""
    try:
        sop = Sop.from_yaml(body.yaml)
        graph = TaskGraph.from_sop(sop)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse SOP: {exc}",
        ) from exc

    replaced_id = archive_current_plan_to_pn(
        ctx.pn,
        reason=f"Replaced by SOP '{graph.name}'.",
    )

    ctx.pn["current_plan"] = graph.model_dump(mode="json")

    edits = ctx.pn.setdefault("_pending_edits", [])
    edits.append(
        {
            "type": "sop_replaced",
            "name": graph.name,
            "graph_id": graph.id,
            "node_count": len(graph.nodes),
            "node_summary": [
                {
                    "id": n.node_id,
                    "name": n.name,
                    "deps": list(n.deps),
                }
                for n in graph.nodes.values()
            ],
            "replaced_graph_id": replaced_id,
        },
    )

    await persist_pn(ctx)

    return Ok(
        detail=f"SOP '{graph.name}' loaded as the active task graph.",
        extra={"graph_id": graph.id, "node_count": len(graph.nodes)},
    )


# ---------------------------------------------------------------------------
# PUT /api/tasks/{session_id}/dag — upload DAG patch (merge into current graph)
# ---------------------------------------------------------------------------


@router.put("/{session_id}/dag", response_model=Ok)
async def put_dag(
    body: DAGUploadBody = Body(...),
    ctx: PnContext = Depends(acquire_pn),
) -> Ok:
    """Upload a DAG patch and merge into the current graph (no archive)."""
    current = ctx.pn.get("current_plan")
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=409,
            detail="No active DAG to patch. Use PUT /sop to create one.",
        )

    try:
        existing = TaskGraph.model_validate(current)
        diff = existing.apply_dag(body.yaml)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply DAG: {exc}",
        ) from exc

    ctx.pn["current_plan"] = existing.model_dump(mode="json")
    edits = ctx.pn.setdefault("_pending_edits", [])
    edits.append(
        {
            "type": "dag_merged",
            "name": existing.name,
            "graph_id": existing.id,
            "added": diff.added,
            "removed": diff.removed,
            "modified": diff.modified,
            "state_overridden": diff.state_overridden,
            "stale_propagated": diff.stale_propagated,
        },
    )

    await persist_pn(ctx)

    return Ok(
        detail=f"DAG '{existing.name}' merged into the active task graph.",
        extra=diff.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files — session file-artifact listing
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files", response_model=FilesResponse)
async def list_files(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
    graph_id: Optional[str] = Query(
        default=None,
        description="Filter by graph_id; omitted returns all.",
    ),
    node_id: Optional[str] = Query(
        default=None,
        description="Filter by node_id; omitted returns all.",
    ),
) -> FilesResponse:
    """List every file-artifact registered via ``finish_subtask``."""
    session, _ = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    artifacts = extract_artifacts(pn)

    entries: List[FileEntry] = []
    for item in artifacts:
        if graph_id and item.graph_id != graph_id:
            continue
        if node_id and item.node_id != node_id:
            continue
        preview_url, download_url = build_file_urls(
            session_id,
            item.path,
            user_id=user_id,
        )
        entries.append(
            FileEntry(
                graph_id=item.graph_id,
                node_id=item.node_id,
                name=item.name,
                path=item.path,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                created_at=item.created_at,
                preview_url=preview_url,
                download_url=download_url,
            ),
        )

    return FilesResponse(files=entries)


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files/preview?path=... — inline preview
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files/preview")
async def preview_file(
    session_id: str,
    request: Request,
    path: str = Query(
        ...,
        min_length=1,
        description=(
            "``ArtifactItem.path``;"
            " must exist in this session's artifacts list."
        ),
    ),
    user_id: str = Query(default="default"),
) -> Response:
    """Inline-preview a file-artifact registered in this session."""
    session, agent_id = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    artifacts = extract_artifacts(pn)

    workspace = await get_workspace_for_agent(
        request,
        agent_id,
    )
    api_origin = resolve_request_api_origin(request)
    return serve_artifact_file(
        workspace,
        session_id,
        agent_id,
        artifacts,
        path,
        disposition="inline",
        rewrite_html=True,
        user_id=user_id,
        api_origin=api_origin,
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files/resource?path=... — artifact resource proxy
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files/resource")
async def resource_file(
    session_id: str,
    request: Request,
    path: str = Query(..., min_length=1),
    user_id: str = Query(default="default"),
    agent_id: str = Query(default=""),
) -> FileResponse:
    """Proxy any file under the artifacts root (no whitelist check)."""
    del user_id  # kept for parity with preview URLs and auth-aware hosts
    resolved_agent = agent_id or getattr(request.state, "agent_id", None)
    _, resolved_agent = await get_session_for_agent(request, resolved_agent)
    workspace = await get_workspace_for_agent(
        request,
        resolved_agent,
    )
    return serve_resource_file(
        workspace,
        session_id,
        resolved_agent,
        path,
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files/download?path=... — download
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files/download")
async def download_file(
    session_id: str,
    request: Request,
    path: str = Query(
        ...,
        min_length=1,
        description=(
            "``ArtifactItem.path``;"
            " must exist in this session's artifacts list."
        ),
    ),
    user_id: str = Query(default="default"),
) -> Response:
    """Download a file-artifact registered in this session."""
    session, agent_id = await get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    pn = await load_pn_for_request(
        session,
        session_id,
        user_id=user_id,
    )
    artifacts = extract_artifacts(pn)

    workspace = await get_workspace_for_agent(
        request,
        agent_id,
    )
    api_origin = resolve_request_api_origin(request)
    return serve_artifact_file(
        workspace,
        session_id,
        agent_id,
        artifacts,
        path,
        disposition="attachment",
        rewrite_html=True,
        user_id=user_id,
        api_origin=api_origin,
    )
