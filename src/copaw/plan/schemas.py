# -*- coding: utf-8 -*-
"""Pydantic response models for plan API endpoints."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class SubTaskStateResponse(BaseModel):
    """Single subtask in a plan response."""

    idx: int
    name: str
    description: str
    expected_outcome: str
    state: Literal["todo", "in_progress", "done", "abandoned"]


class PlanStateResponse(BaseModel):
    """Full plan state returned by plan API endpoints."""

    plan_id: str
    name: str
    description: str
    expected_outcome: str
    state: Literal["todo", "in_progress", "done", "abandoned"]
    subtasks: list[SubTaskStateResponse]
    created_at: str
    updated_at: str


class PlanSummary(BaseModel):
    """Lightweight plan summary for history listing."""

    plan_id: str
    name: str
    state: str
    created_at: str
    subtask_count: int
    completed_count: int


class SubTaskInput(BaseModel):
    """Input for a single subtask when creating a plan."""

    name: str
    description: str
    expected_outcome: str


class CreatePlanRequest(BaseModel):
    """Request body for manually creating a plan."""

    name: str
    description: str
    expected_outcome: str
    subtasks: list[SubTaskInput]


class RevisePlanRequest(BaseModel):
    """Request body for revising the current plan."""

    subtask_idx: int
    action: Literal["add", "revise", "delete"]
    subtask: Optional[SubTaskInput] = None


class FinishPlanRequest(BaseModel):
    """Request body for finishing/abandoning the current plan."""

    state: Literal["done", "abandoned"] = "done"
    outcome: str = ""


class PlanConfigUpdateRequest(BaseModel):
    """Request body for updating plan configuration."""

    enabled: bool = Field(default=False)
    max_subtasks: Optional[int] = Field(default=None)
    storage_type: Literal["memory", "file"] = Field(default="memory")
    storage_path: Optional[str] = Field(default=None)
    agent_managed: bool = Field(default=True)


def plan_to_response(plan) -> PlanStateResponse:
    """Convert an AgentScope Plan to a PlanStateResponse."""
    return PlanStateResponse(
        plan_id=plan.id,
        name=plan.name,
        description=plan.description,
        expected_outcome=plan.expected_outcome,
        state=plan.state,
        subtasks=[
            SubTaskStateResponse(
                idx=i,
                name=st.name,
                description=st.description,
                expected_outcome=st.expected_outcome,
                state=st.state,
            )
            for i, st in enumerate(plan.subtasks)
        ],
        created_at=plan.created_at,
        updated_at=plan.finished_at or plan.created_at,
    )


def plan_to_summary(plan) -> PlanSummary:
    """Convert an AgentScope Plan to a PlanSummary."""
    return PlanSummary(
        plan_id=plan.id,
        name=plan.name,
        state=plan.state,
        created_at=plan.created_at,
        subtask_count=len(plan.subtasks),
        completed_count=sum(
            1 for st in plan.subtasks if st.state == "done"
        ),
    )
