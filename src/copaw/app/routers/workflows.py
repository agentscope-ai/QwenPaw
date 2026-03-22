# -*- coding: utf-8 -*-
"""Workflows API - User-level workflow management and execution.

Provides RESTful API for managing and executing user-level workflows
that can orchestrate multiple agents.
"""
# pylint: disable=raise-missing-from

import logging
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...constant import WORKFLOWS_DIR
from ..orchestration import (
    WorkflowEngine,
    WorkflowExecutionRequest,
    WorkflowExecutionResult,
    WorkflowDefinition,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


# ============================================================================
# Pydantic Models for API
# ============================================================================


class WorkflowInfo(BaseModel):
    """Workflow file information."""

    filename: str
    path: str
    size: int
    created_time: str
    modified_time: str


class WorkflowContent(BaseModel):
    """Workflow file content."""

    content: str = Field(..., description="Workflow content (YAML format)")


class WorkflowListResponse(BaseModel):
    """Response for listing workflows."""

    workflows: List[WorkflowInfo]


class WorkflowCreateRequest(BaseModel):
    """Request for creating a workflow."""

    filename: str = Field(
        ...,
        description="Workflow filename (must end with .yaml or .yml)",
    )
    content: str = Field(
        ...,
        description="Workflow content in YAML format",
    )


class WorkflowUpdateRequest(BaseModel):
    """Request for updating a workflow."""

    content: str = Field(
        ...,
        description="Updated workflow content in YAML format",
    )


# ============================================================================
# Dependencies
# ============================================================================


def get_workflow_engine(request) -> WorkflowEngine:
    """Get the workflow engine instance.

    The multi_agent_manager is stored in the app state and provides
    access to all agent workspaces.
    """
    from ..multi_agent_manager import MultiAgentManager

    manager: MultiAgentManager = getattr(
        request.app.state,
        "multi_agent_manager",
        None,
    )
    return WorkflowEngine(WORKFLOWS_DIR, multi_agent_manager=manager)


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_filename(filename: str) -> str:
    """Validate workflow filename.

    Args:
        filename: Filename to validate.

    Returns:
        Sanitized filename.

    Raises:
        HTTPException: If filename is invalid.
    """
    # Check extension
    if not (filename.endswith(".yaml") or filename.endswith(".yml")):
        raise HTTPException(
            status_code=400,
            detail="Filename must end with .yaml or .yml",
        )

    # Check for path traversal
    if "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail="Filename cannot contain path separators",
        )

    # Check for directory operations
    if filename in (".", ".."):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename",
        )

    return filename


def _get_workflow_info(filepath: Path) -> WorkflowInfo:
    """Get workflow file information.

    Args:
        filepath: Path to the workflow file.

    Returns:
        WorkflowInfo object.
    """
    stat = filepath.stat()
    return WorkflowInfo(
        filename=filepath.name,
        path=str(filepath),
        size=stat.st_size,
        created_time=datetime.fromtimestamp(stat.st_ctime).isoformat(),
        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )


# ============================================================================
# API Endpoints
# ============================================================================


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List all workflows",
)
async def list_workflows() -> WorkflowListResponse:
    """List all workflow files in the workflows directory.

    Returns:
        List of workflow files with metadata.
    """
    if not WORKFLOWS_DIR.exists():
        return WorkflowListResponse(workflows=[])

    workflows = []
    for filepath in WORKFLOWS_DIR.iterdir():
        if filepath.suffix in (".yaml", ".yml") and filepath.is_file():
            workflows.append(_get_workflow_info(filepath))

    # Sort by modification time (most recent first)
    workflows.sort(key=lambda w: w.modified_time, reverse=True)

    return WorkflowListResponse(workflows=workflows)


@router.get("/{filename}", summary="Get workflow content")
async def get_workflow(filename: str) -> WorkflowContent:
    """Get the content of a specific workflow file.

    Args:
        filename: Name of the workflow file.

    Returns:
        Workflow content in YAML format.

    Raises:
        HTTPException: If file not found or invalid.
    """
    filename = _validate_filename(filename)
    filepath = WORKFLOWS_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Security check: ensure path is within workflows dir
    if not filepath.resolve().is_relative_to(WORKFLOWS_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid workflow path")

    content = filepath.read_text(encoding="utf-8")
    return WorkflowContent(content=content)


@router.post("", status_code=201, summary="Create a new workflow")
async def create_workflow(request: WorkflowCreateRequest) -> WorkflowInfo:
    """Create a new workflow file.

    Args:
        request: Workflow creation request with filename and content.

    Returns:
        Created workflow info.

    Raises:
        HTTPException: If file already exists or content is invalid.
    """
    filename = _validate_filename(request.filename)
    filepath = WORKFLOWS_DIR / filename

    # Ensure directory exists
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

    # Check if file already exists
    if filepath.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Workflow '{filename}' already exists",
        )

    # Validate YAML content
    import yaml

    try:
        yaml.safe_load(request.content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML content: {e}",
        ) from e

    # Write the file
    filepath.write_text(request.content, encoding="utf-8")

    return _get_workflow_info(filepath)


@router.put("/{filename}", summary="Update a workflow")
async def update_workflow(
    filename: str,
    request: WorkflowUpdateRequest,
) -> WorkflowInfo:
    """Update an existing workflow file.

    Args:
        filename: Name of the workflow file to update.
        request: Update request with new content.

    Returns:
        Updated workflow info.

    Raises:
        HTTPException: If file not found or content is invalid.
    """
    filename = _validate_filename(filename)
    filepath = WORKFLOWS_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Validate YAML content
    import yaml

    try:
        yaml.safe_load(request.content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML content: {e}",
        ) from e

    # Write the updated content
    filepath.write_text(request.content, encoding="utf-8")

    return _get_workflow_info(filepath)


@router.delete("/{filename}", status_code=204, summary="Delete a workflow")
async def delete_workflow(filename: str) -> None:
    """Delete a workflow file.

    Args:
        filename: Name of the workflow file to delete.

    Raises:
        HTTPException: If file not found.
    """
    filename = _validate_filename(filename)
    filepath = WORKFLOWS_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")

    filepath.unlink()


@router.post(
    "/{filename}/execute",
    response_model=WorkflowExecutionResult,
    summary="Execute a workflow",
)
async def execute_workflow(
    filename: str,
    request: Request,
    exec_request: WorkflowExecutionRequest = WorkflowExecutionRequest(),
) -> WorkflowExecutionResult:
    """Execute a workflow with the given variables.

    This endpoint loads the workflow definition and executes it step by step,
    invoking the specified agents and passing results between steps.

    Args:
        filename: Name of the workflow file to execute.
        request: Execution request with optional variables.
        engine: Injected workflow engine.

    Returns:
        Execution result with all step outputs.

    Raises:
        HTTPException: If workflow not found or execution fails.
    """
    # Validate filename (don't require yaml extension for execute)
    if not (filename.endswith(".yaml") or filename.endswith(".yml")):
        # Try adding .yaml extension
        if not (WORKFLOWS_DIR / f"{filename}.yaml").exists():
            if not (WORKFLOWS_DIR / f"{filename}.yml").exists():
                raise HTTPException(
                    status_code=400,
                    detail="Filename must end with .yaml or .yml",
                )
            filename = f"{filename}.yml"
        else:
            filename = f"{filename}.yaml"

    filename = _validate_filename(filename)

    # Get workflow engine with access to multi-agent manager
    engine = get_workflow_engine(request)

    # Get calling agent ID if not explicitly provided
    calling_agent_id = exec_request.calling_agent_id
    if calling_agent_id is None:
        # Try to get the active agent from the request context
        from ...config import load_config

        try:
            config = load_config()
            calling_agent_id = config.agents.active_agent
        except Exception:
            pass  # Keep None if we can't determine the active agent

    try:
        # Load the workflow definition
        workflow = engine.load_workflow(filename)

        # Execute the workflow
        result = await engine.execute_workflow(
            workflow=workflow,
            variables=exec_request.variables,
            calling_agent_id=calling_agent_id,
            spawn_depth=exec_request.spawn_depth,
        )

        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Workflow execution failed: {e}",
        )


@router.post(
    "/validate",
    summary="Validate workflow YAML content",
)
async def validate_workflow(content: WorkflowContent) -> dict:
    """Validate workflow YAML content without executing it.

    Args:
        content: Workflow content to validate.

    Returns:
        Validation result with any errors or warnings.

    Raises:
        HTTPException: If content is invalid.
    """
    import yaml

    try:
        data = yaml.safe_load(content.content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML: {e}",
        )

    if not data:
        raise HTTPException(
            status_code=400,
            detail="Empty workflow content",
        )

    try:
        workflow = WorkflowDefinition(**data)
        return {
            "valid": True,
            "workflow_name": workflow.name,
            "steps_count": len(workflow.steps),
            "variables": list(workflow.variables.keys()),
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid workflow definition: {e}",
        )
