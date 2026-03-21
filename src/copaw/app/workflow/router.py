# -*- coding: utf-8 -*-
"""Workflows API - User-level workflow management.

Provides RESTful API for managing user-level workflows that can
orchestrate multiple agents.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...constant import WORKFLOWS_DIR
from .md_meta import extract_meta_fields, split_frontmatter
from .run_store import WorkflowRunStore, delete_runs_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowMetaInfo(BaseModel):
    """Metadata from YAML frontmatter."""

    name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    status: Optional[str] = None
    version: Optional[str] = None


class WorkflowInfo(BaseModel):
    """Workflow file information."""

    filename: str
    path: str
    size: int
    created_time: str
    modified_time: str
    name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    status: Optional[str] = None
    version: Optional[str] = None


class WorkflowContent(BaseModel):
    """Request body: full file content as stored."""

    content: str = Field(
        ...,
        description="Full Markdown file (may include frontmatter)",
    )


class WorkflowReadResponse(BaseModel):
    """Workflow file: rendered body, raw file, and parsed frontmatter meta."""

    content: str = Field(
        ...,
        description="Markdown body after frontmatter (or full file if none)",
    )
    raw: str = Field(..., description="Exact file contents as on disk")
    meta: WorkflowMetaInfo


class WorkflowListResponse(BaseModel):
    """Response for listing workflows."""

    workflows: List[WorkflowInfo]


class WorkflowCreateRequest(BaseModel):
    """Request for creating a workflow."""

    filename: str = Field(
        ...,
        description="Workflow filename (e.g., daily_report.md)",
    )
    content: str = Field(
        ...,
        description="Workflow content in Markdown format",
    )


class WorkflowRunCreate(BaseModel):
    """Append one execution record for a workflow."""

    user_id: str = Field(default="", max_length=512)
    session_id: str = Field(default="", max_length=512)
    trigger: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="How the run was started (e.g. api, cron, manual)",
    )
    status: Optional[str] = Field(
        None,
        max_length=64,
        description="Optional outcome hint (e.g. success, error)",
    )
    executed_at: Optional[datetime] = Field(
        None,
        description="Defaults to current UTC if omitted",
    )


class WorkflowRunOut(BaseModel):
    """One persisted workflow run row."""

    run_id: str
    workflow_id: str
    user_id: str = ""
    session_id: str = ""
    trigger: str
    executed_at: str
    status: Optional[str] = None


class WorkflowRunListResponse(BaseModel):
    """List of run records for one workflow (newest first)."""

    runs: List[WorkflowRunOut]


def _reject_invalid_basename(filename: str) -> None:
    if "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail="Filename cannot contain path separators",
        )
    if not filename.endswith((".md", ".markdown")):
        raise HTTPException(
            status_code=400,
            detail="Workflow filename must end with .md or .markdown",
        )


def _workflow_file_or_404(filename: str) -> Path:
    _reject_invalid_basename(filename)
    file_path = WORKFLOWS_DIR / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{filename}' not found",
        )
    if not file_path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"'{filename}' is not a file",
        )
    return file_path


def _read_workflow_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


def _meta_for_raw(raw: str) -> WorkflowMetaInfo:
    _had, meta_dict, _body, _full = split_frontmatter(raw)
    name, description, tags, category, status, version = extract_meta_fields(
        meta_dict,
    )
    return WorkflowMetaInfo(
        name=name,
        description=description,
        tags=tags,
        category=category,
        status=status,
        version=version,
    )


def _info_from_path(file_path: Path) -> WorkflowInfo:
    stat = file_path.stat()
    try:
        raw = _read_workflow_text(file_path)
        wmeta = _meta_for_raw(raw)
    except OSError as e:
        logger.warning("Failed to read workflow %s: %s", file_path, e)
        wmeta = WorkflowMetaInfo()

    return WorkflowInfo(
        filename=file_path.name,
        path=str(file_path),
        size=stat.st_size,
        created_time=str(stat.st_ctime),
        modified_time=str(stat.st_mtime),
        name=wmeta.name,
        description=wmeta.description,
        tags=wmeta.tags,
        category=wmeta.category,
        status=wmeta.status,
        version=wmeta.version,
    )


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List all workflows",
    description=(
        "Get list of all workflow files in the user-level workflows directory"
    ),
)
async def list_workflows() -> WorkflowListResponse:
    """List all workflow files."""
    if not WORKFLOWS_DIR.exists():
        return WorkflowListResponse(workflows=[])

    workflows = []
    for pattern in ("*.md", "*.markdown"):
        for file_path in WORKFLOWS_DIR.glob(pattern):
            workflows.append(_info_from_path(file_path))

    return WorkflowListResponse(workflows=workflows)


@router.get(
    "/{filename}/runs/{run_id}",
    response_model=WorkflowRunOut,
    summary="Get one workflow run record",
)
async def get_workflow_run(filename: str, run_id: str) -> WorkflowRunOut:
    """Return a single run by ``run_id`` from this workflow's history file."""
    _workflow_file_or_404(filename)
    store = WorkflowRunStore.get_instance()
    row = await store.get_run(filename, run_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found for workflow '{filename}'",
        )
    return WorkflowRunOut.model_validate(row)


@router.get(
    "/{filename}/runs",
    response_model=WorkflowRunListResponse,
    summary="List workflow run history",
)
async def list_workflow_runs(filename: str) -> WorkflowRunListResponse:
    """Return all run records for this workflow, newest first."""
    _workflow_file_or_404(filename)
    store = WorkflowRunStore.get_instance()
    raw = await store.list_runs(filename)
    ordered = list(reversed(raw))
    runs = [WorkflowRunOut.model_validate(r) for r in ordered]
    return WorkflowRunListResponse(runs=runs)


@router.post(
    "/{filename}/runs",
    response_model=WorkflowRunOut,
    status_code=201,
    summary="Append a workflow run record",
)
async def append_workflow_run(
    filename: str,
    body: WorkflowRunCreate,
) -> WorkflowRunOut:
    """Append one JSON object to this workflow's run list file."""
    _workflow_file_or_404(filename)
    store = WorkflowRunStore.get_instance()
    row = await store.append_run(
        filename,
        user_id=body.user_id,
        session_id=body.session_id,
        trigger=body.trigger,
        status=body.status,
        executed_at=body.executed_at,
    )
    return WorkflowRunOut.model_validate(row)


@router.get(
    "/{filename}",
    response_model=WorkflowReadResponse,
    summary="Get workflow content",
    description=(
        "Read workflow: raw file, body without frontmatter, and parsed meta"
    ),
)
async def get_workflow(filename: str) -> WorkflowReadResponse:
    """Get workflow content by filename."""
    file_path = _workflow_file_or_404(filename)

    try:
        raw = _read_workflow_text(file_path)
        had_fence, meta_dict, body, _ = split_frontmatter(raw)
        (
            name,
            description,
            tags,
            category,
            status,
            version,
        ) = extract_meta_fields(
            meta_dict,
        )
        meta = WorkflowMetaInfo(
            name=name,
            description=description,
            tags=tags,
            category=category,
            status=status,
            version=version,
        )
        display_body = body if had_fence else raw
        return WorkflowReadResponse(
            content=display_body,
            raw=raw,
            meta=meta,
        )
    except Exception as e:
        logger.error(f"Failed to read workflow {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read workflow: {e}",
        ) from e


@router.post(
    "",
    status_code=201,
    summary="Create workflow",
    description="Create a new workflow file with the given content",
)
async def create_workflow(request: WorkflowCreateRequest) -> dict:
    """Create a new workflow file."""
    _reject_invalid_basename(request.filename)

    file_path = WORKFLOWS_DIR / request.filename

    if file_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Workflow '{request.filename}' already exists",
        )

    try:
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        file_path.write_text(request.content, encoding="utf-8")
        logger.info(f"Created workflow: {file_path}")
        return {
            "success": True,
            "filename": request.filename,
            "path": str(file_path),
        }
    except Exception as e:
        logger.error(f"Failed to create workflow {request.filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create workflow: {e}",
        ) from e


@router.put(
    "/{filename}",
    summary="Update workflow",
    description="Update an existing workflow file",
)
async def update_workflow(
    filename: str,
    content: WorkflowContent,
) -> dict:
    """Update an existing workflow file."""
    file_path = _workflow_file_or_404(filename)

    try:
        file_path.write_text(content.content, encoding="utf-8")
        logger.info(f"Updated workflow: {file_path}")
        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
        }
    except Exception as e:
        logger.error(f"Failed to update workflow {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update workflow: {e}",
        ) from e


@router.delete(
    "/{filename}",
    summary="Delete workflow",
    description="Delete a workflow file",
)
async def delete_workflow(filename: str) -> dict:
    """Delete a workflow file."""
    file_path = _workflow_file_or_404(filename)

    try:
        file_path.unlink()
        delete_runs_file(filename)
        logger.info(f"Deleted workflow: {file_path}")
        return {
            "success": True,
            "filename": filename,
        }
    except Exception as e:
        logger.error(f"Failed to delete workflow {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete workflow: {e}",
        ) from e
