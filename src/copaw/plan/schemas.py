# -*- coding: utf-8 -*-
"""Pydantic response models for plan API endpoints."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


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


class SubTaskInput(BaseModel):
    """Input for a single subtask when revising a plan."""

    name: str
    description: str
    expected_outcome: str


class RevisePlanRequest(BaseModel):
    """Request body for revising the current plan."""

    subtask_idx: int
    action: Literal["add", "revise", "delete"]
    subtask: Optional[SubTaskInput] = None

    @model_validator(mode="after")
    def _check_subtask_required(self) -> "RevisePlanRequest":
        if self.action in ("add", "revise") and self.subtask is None:
            raise ValueError(
                f"'subtask' is required when action is " f"'{self.action}'",
            )
        return self


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


_STATE_LABEL = {
    "todo": "[ ]",
    "in_progress": "[WIP]",
    "done": "[x]",
    "abandoned": "[Abandoned]",
}


def plan_dict_to_overview(plan_dict: dict) -> str:
    """Build a human-readable plan overview from a raw plan dict.

    This is used to reconstruct plan context when loading
    historical chat sessions whose earlier messages have been
    compacted away by memory compaction.

    Args:
        plan_dict: The ``current_plan`` value from a serialised
            ``PlanNotebook`` state dict.

    Returns:
        A markdown-formatted overview string, or ``""`` if the
        dict is empty / invalid.
    """
    if not plan_dict or not isinstance(plan_dict, dict):
        return ""

    name = plan_dict.get("name", "Unnamed Plan")
    desc = plan_dict.get("description", "")
    expected = plan_dict.get("expected_outcome", "")
    plan_state = plan_dict.get("state", "todo")
    subtasks = plan_dict.get("subtasks", [])

    lines = [
        f"**Plan: {name}** ({plan_state})",
    ]
    if desc:
        lines.append(f"Description: {desc}")
    if expected:
        lines.append(f"Expected outcome: {expected}")
    if subtasks:
        lines.append("")
        lines.append("Subtasks:")
        for i, st in enumerate(subtasks):
            label = _STATE_LABEL.get(
                st.get("state", "todo"),
                "[ ]",
            )
            st_name = st.get("name", "")
            outcome = st.get("outcome", "")
            line = f"  {i + 1}. {label} {st_name}"
            if outcome and st.get("state") == "done":
                line += f" -> {outcome}"
            lines.append(line)

    return "\n".join(lines)
