# -*- coding: utf-8 -*-
"""Multi-workspace management API — CRUD + activate."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...workspace import WorkspaceInfo, WorkspaceManager
from ...constant import set_workspace_dir

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    path: str
    created_at: float
    is_active: bool


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def get_workspace_manager(request: Request) -> WorkspaceManager:
    mgr = getattr(request.app.state, "workspace_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="workspace manager not initialized",
        )
    return mgr


def _to_response(ws: WorkspaceInfo) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        path=ws.path,
        created_at=ws.created_at,
        is_active=ws.is_active,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    mgr: WorkspaceManager = Depends(get_workspace_manager),
):
    return [_to_response(ws) for ws in mgr.list_workspaces()]


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    body: CreateWorkspaceRequest,
    mgr: WorkspaceManager = Depends(get_workspace_manager),
):
    ws = mgr.create(name=body.name)
    return _to_response(ws)


@router.get("/active", response_model=WorkspaceResponse)
async def get_active_workspace(
    mgr: WorkspaceManager = Depends(get_workspace_manager),
):
    ws = mgr.get_active()
    if ws is None:
        raise HTTPException(status_code=404, detail="no active workspace")
    return _to_response(ws)


@router.post("/{workspace_id}/activate", response_model=WorkspaceResponse)
async def activate_workspace(
    workspace_id: str,
    mgr: WorkspaceManager = Depends(get_workspace_manager),
):
    found = mgr.activate(workspace_id)
    if not found:
        raise HTTPException(status_code=404, detail="workspace not found")
    # Update the global workspace dir so subsequent path lookups
    # resolve to the newly activated workspace.
    set_workspace_dir(mgr.get_active_path())
    ws = mgr.get_active()
    assert ws is not None, "just activated; must exist"
    return _to_response(ws)


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    mgr: WorkspaceManager = Depends(get_workspace_manager),
):
    ok = mgr.delete(workspace_id)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="cannot delete active workspace or workspace not found",
        )
    return {"deleted": True}
