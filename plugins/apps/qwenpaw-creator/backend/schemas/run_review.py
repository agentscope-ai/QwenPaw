# -*- coding: utf-8 -*-
"""Pydantic models for the in-run review bypass (backend-internal).

Both run-review switches are code-level only, so these models intentionally
do not join the frontend API contract; reports are persisted under each
Project's ``runtime/run-review/`` directory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RubricScore(RunReviewModel):
    """One Appeal rubric row scored 0-10 (advisory, never a gate)."""

    row_key: str
    name: str
    score: int = Field(ge=0, le=10)
    ok: bool
    finding: str = ""
    suggestion: str = ""


class SyncReviewAdvisory(RunReviewModel):
    """Synchronous text/motion review attached to a jq_project result."""

    transaction_id: str
    pointer_group: str
    reviewed_pointers: list[str] = Field(default_factory=list)
    round: int = Field(ge=1)
    scores: list[RubricScore] = Field(default_factory=list)
    summary: str = ""
    created_at: datetime | None = None

    def weak_scores(self) -> list[RubricScore]:
        return [item for item in self.scores if not item.ok]


class MediaReviewFinding(RunReviewModel):
    """One scene-check finding on a generated image/video artifact."""

    check_key: str
    passed: bool
    severity: Literal["minor", "major"] = "minor"
    evidence_timestamp_ms: int | None = Field(default=None, ge=0)
    suggestion: str = ""


class MediaReviewReport(RunReviewModel):
    """Async bypass review report for one artifact version."""

    artifact_ref: str
    kind: Literal["image", "element_video"]
    round: int = Field(ge=1)
    gate_block: dict[str, Any] | None = None
    stats: dict[str, Any] | None = None
    findings: list[MediaReviewFinding] = Field(default_factory=list)
    verdict: Literal["pass", "revise"]
    created_at: datetime | None = None

    def failed_findings(self) -> list[MediaReviewFinding]:
        return [item for item in self.findings if not item.passed]


__all__ = [
    "MediaReviewFinding",
    "MediaReviewReport",
    "RubricScore",
    "RunReviewModel",
    "SyncReviewAdvisory",
]
