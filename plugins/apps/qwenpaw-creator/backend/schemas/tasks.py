# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from domain.enums import (
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)

from .common import StrictModel


class TaskView(StrictModel):
    id: str
    project_id: str = Field(alias="projectId")
    transaction_id: str | None = Field(None, alias="transactionId")
    specialist_run_id: str | None = Field(None, alias="specialistRunId")
    kind: TaskKind
    target_ref: str = Field(alias="targetRef")
    status: TaskStatus
    progress: float | None = None
    completed_elements: int | None = Field(
        None,
        alias="completedElements",
        ge=0,
    )
    total_elements: int | None = Field(None, alias="totalElements", ge=0)
    result_refs: list[str] = Field(default_factory=list, alias="resultRefs")


class SpecialistRunView(StrictModel):
    id: str
    role: SpecialistRole
    display_name: str = Field(alias="displayName")
    status: SpecialistRunStatus
    target_refs: list[str] = Field(alias="targetRefs")
    related_run_id: str | None = Field(None, alias="relatedRunId")
    supersedes_run_id: str | None = Field(None, alias="supersedesRunId")
    final_marker: str | None = Field(None, alias="finalMarker")
    final_summary_text: str | None = Field(None, alias="finalSummaryText")
    task_refs: list[str] = Field(default_factory=list, alias="taskRefs")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionAuthorizationView(StrictModel):
    id: str
    transaction_id: str = Field(alias="transactionId")
    specialist_run_id: str = Field(alias="specialistRunId")
    execution_request_id: str = Field(alias="executionRequestId")
    target_ref: str = Field(alias="targetRef")
    scope: dict[str, Any]
    status: Literal["PENDING", "APPROVED", "DECLINED", "EXPIRED"]
    authorization_token: str = Field(alias="authorizationToken")
    provider: str
    model: str
    estimated_cost: float | None = Field(None, alias="estimatedCost")
    currency: str | None = None
    max_candidates: int = Field(alias="maxCandidates", ge=1)
    created_at: str = Field(alias="createdAt")


class ExecutionAuthorizationPage(StrictModel):
    items: list[ExecutionAuthorizationView]
