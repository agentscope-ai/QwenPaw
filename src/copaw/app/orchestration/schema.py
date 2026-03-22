# -*- coding: utf-8 -*-
"""Workflow schema definitions.

Defines the structure of workflow YAML files and execution models.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """Status of a workflow step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep(BaseModel):
    """A single step in a workflow.

    Each step specifies an agent to invoke and a prompt to send.
    The prompt can reference variables from the workflow context
    and results from previous steps using {{step_id.result}} syntax.
    """

    id: str = Field(
        ...,
        description="Unique step identifier within the workflow",
    )
    agent: str = Field(
        ...,
        description="Agent ID to invoke for this step",
    )
    prompt: str = Field(
        ...,
        description="Prompt to send to the agent. "
        "Supports {{variable}} substitution.",
    )
    condition: Optional[str] = Field(
        default=None,
        description="Optional condition to execute this step. "
        "Supports Jinja2 syntax.",
    )
    timeout: Optional[int] = Field(
        default=None,
        description="Timeout in seconds for this step",
    )
    retries: int = Field(
        default=0,
        description="Number of retries on failure",
    )


class WorkflowDefinition(BaseModel):
    """Complete workflow definition.

    A workflow consists of metadata and a list of steps to execute
    sequentially or based on conditions.
    """

    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(
        default=None,
        description="Workflow description",
    )
    version: str = Field(default="1.0", description="Workflow version")
    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Default variables for the workflow",
    )
    steps: List[WorkflowStep] = Field(
        ...,
        description="List of steps to execute",
    )


class StepResult(BaseModel):
    """Result of a single workflow step execution."""

    step_id: str
    status: StepStatus
    agent: str
    prompt: str
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None


class WorkflowExecutionRequest(BaseModel):
    """Request to execute a workflow."""

    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Variables to substitute in the workflow",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session ID for conversation continuity",
    )
    calling_agent_id: Optional[str] = Field(
        default=None,
        description="ID of the agent initiating this workflow "
        "(for permission checks)",
    )
    spawn_depth: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Current nesting depth for agent spawning",
    )


class WorkflowExecutionStatus(str, Enum):
    """Overall workflow execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowExecutionResult(BaseModel):
    """Result of a workflow execution."""

    workflow_name: str
    status: WorkflowExecutionStatus
    steps: List[StepResult] = Field(default_factory=list)
    variables: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    final_result: Optional[str] = Field(
        default=None,
        description="Result of the last completed step",
    )
