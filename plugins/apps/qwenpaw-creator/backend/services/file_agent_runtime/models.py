# -*- coding: utf-8 -*-
"""Durable records owned by the file-native Creator Agent driver."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from services.runtime_files.models import (
    AwareDatetime,
    ChangeOrigin,
    NonEmptyString,
    ReviewBoundary,
    ReviewPolicy,
    StrictRuntimeModel,
    utc_now,
)


class AgentRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_AGENT_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    },
)


class CreatorAgentRunRecord(StrictRuntimeModel):
    run_id: NonEmptyString
    project_id: NonEmptyString
    session_id: NonEmptyString
    goal_id: NonEmptyString
    conversation_id: NonEmptyString
    round_id: NonEmptyString
    caused_by_message_id: NonEmptyString
    caused_by_message_seq: int = Field(ge=1)
    caused_by_request_id: str | None = None
    origin: ChangeOrigin
    review_policy: ReviewPolicy
    review_boundary: ReviewBoundary | None = None
    input_generation: int = Field(ge=0)
    input_etag: NonEmptyString
    status: AgentRunStatus = AgentRunStatus.QUEUED
    tool_call_count: int = Field(default=0, ge=0)
    review_ids: list[str] = Field(default_factory=list)
    final_summary: str | None = None
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_review_provenance(self) -> CreatorAgentRunRecord:
        if self.review_policy is ReviewPolicy.REQUIRE_REVIEW:
            if self.review_boundary is None:
                raise ValueError(
                    "review-required Agent run needs a ReviewBoundary",
                )
            if self.caused_by_request_id != self.review_boundary.request_id:
                raise ValueError(
                    "Agent run request does not match ReviewBoundary",
                )
            if (
                self.caused_by_message_seq
                != self.review_boundary.request_message_seq
            ):
                raise ValueError(
                    "Agent run message does not match ReviewBoundary",
                )
        elif self.review_boundary is not None:
            raise ValueError(
                "auto-fix Agent run cannot carry a ReviewBoundary",
            )
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if len(self.review_ids) != len(set(self.review_ids)):
            raise ValueError("review_ids cannot contain duplicates")
        return self


__all__ = [
    "AgentRunStatus",
    "CreatorAgentRunRecord",
    "TERMINAL_AGENT_RUN_STATUSES",
]
