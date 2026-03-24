# -*- coding: utf-8 -*-
"""Project pipeline APIs split from agents router to reduce merge conflicts."""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as PathParam

from . import agents as agents_router_impl
from .agents_pipeline_core import (
    CreatePipelineRunRequest,
    PipelineRunDetail,
    PipelineRunSummary,
    PipelineTemplateInfo,
    _create_project_pipeline_run,
    _list_project_pipeline_runs,
    _list_project_pipeline_templates,
    _load_project_pipeline_run,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get(
    "/{agentId}/projects/{projectId}/pipelines/templates",
    response_model=list[PipelineTemplateInfo],
    summary="List project pipeline templates",
    description="List available pipeline templates for a project",
)
async def list_project_pipeline_templates(
    request: Request,
    agentId: str = PathParam(...),
    projectId: str = PathParam(...),
) -> list[PipelineTemplateInfo]:
    """List available pipeline templates for a project."""
    manager = agents_router_impl._get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        project_dir = agents_router_impl._resolve_project_dir(Path(workspace.workspace_dir), projectId)
        return _list_project_pipeline_templates(project_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/projects/{projectId}/pipelines/runs",
    response_model=list[PipelineRunSummary],
    summary="List project pipeline runs",
    description="List pipeline runs under a project",
)
async def list_project_pipeline_runs(
    request: Request,
    agentId: str = PathParam(...),
    projectId: str = PathParam(...),
) -> list[PipelineRunSummary]:
    """List pipeline runs under a project."""
    manager = agents_router_impl._get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        project_dir = agents_router_impl._resolve_project_dir(Path(workspace.workspace_dir), projectId)
        return _list_project_pipeline_runs(project_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/projects/{projectId}/pipelines/runs/{runId}",
    response_model=PipelineRunDetail,
    summary="Get project pipeline run",
    description="Get one pipeline run detail under a project",
)
async def get_project_pipeline_run(
    request: Request,
    agentId: str = PathParam(...),
    projectId: str = PathParam(...),
    runId: str = PathParam(...),
) -> PipelineRunDetail:
    """Get one pipeline run detail under a project."""
    manager = agents_router_impl._get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        project_dir = agents_router_impl._resolve_project_dir(Path(workspace.workspace_dir), projectId)
        return _load_project_pipeline_run(project_dir, runId)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/{agentId}/projects/{projectId}/pipelines/runs",
    response_model=PipelineRunDetail,
    summary="Create project pipeline run",
    description="Create a new pipeline run from one template",
)
async def create_project_pipeline_run(
    request: Request,
    body: CreatePipelineRunRequest,
    agentId: str = PathParam(...),
    projectId: str = PathParam(...),
) -> PipelineRunDetail:
    """Create a new pipeline run from one template."""
    manager = agents_router_impl._get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        project_dir = agents_router_impl._resolve_project_dir(Path(workspace.workspace_dir), projectId)
        return _create_project_pipeline_run(projectId, project_dir, body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
