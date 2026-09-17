# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .common import StrictModel


class ExecutionProviderModelScope(StrictModel):
    """One exact provider/model pair covered by project preauthorization."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)

    @field_validator("provider", "model")
    @classmethod
    def _strip_identity(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider/model 不能为空")
        return stripped


class ExecutionPreauthorizationPolicy(StrictModel):
    """Durable project budget for automatic high-cost execution admission.

    ``maxCost`` is the cumulative estimated-cost budget reserved by approved
    execution requests in this Project.  Candidate count is a per-request cap;
    provider/model membership is exact and intentionally has no wildcard.
    """

    max_cost: float = Field(alias="maxCost", ge=0)
    max_candidates: int = Field(alias="maxCandidates", ge=1)
    provider_models: list[ExecutionProviderModelScope] = Field(
        alias="providerModels",
        min_length=1,
    )

    @field_validator("provider_models")
    @classmethod
    def _unique_provider_models(
        cls,
        value: list[ExecutionProviderModelScope],
    ) -> list[ExecutionProviderModelScope]:
        identities = [(item.provider, item.model) for item in value]
        if len(identities) != len(set(identities)):
            raise ValueError("providerModels 不能重复")
        return value


class ProjectCreateRequest(StrictModel):
    client_request_id: str = Field(alias="clientRequestId")
    name: str = Field(min_length=1)
    description: str = ""
    scenario: Literal["short_drama", "video_edit", "general"] = "general"
    aspect_ratio: str = Field("16:9", alias="aspectRatio")
    resolution: str = "720P"
    content_type: str | None = Field(None, alias="contentType")
    execution_preauthorization: ExecutionPreauthorizationPolicy | None = Field(
        None,
        alias="executionPreauthorization",
    )
    initial_goal: str | None = Field(None, alias="initialGoal", min_length=1)

    @field_validator("initial_goal")
    @classmethod
    def _strip_initial_goal(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("initialGoal 不能为空")
        return stripped


class ProjectCreateResponse(StrictModel):
    project_id: str = Field(alias="projectId")
    creator_session_id: str = Field(alias="creatorSessionId")
    conversation_id: str = Field(alias="conversationId")
    project_snapshot_id: str = Field(alias="projectSnapshotId")
    header: dict = Field(default_factory=dict)
