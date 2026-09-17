# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from pydantic import Field

from domain.enums import CreatorProgressPhase

from .common import StrictModel


class CreatorTaskProgress(StrictModel):
    goal_id: str | None = Field(None, alias="goalId")
    phase: CreatorProgressPhase
    label: str
    latest_milestone: str | None = Field(None, alias="latestMilestone")
    completed: int | None = None
    total: int | None = None
    timeline_id: str | None = Field(None, alias="timelineId")
    element_id: str | None = Field(None, alias="elementId")
    source_event_seq: int = Field(0, alias="sourceEventSeq")
    updated_at: str = Field(alias="updatedAt")


class AgentStatusBadge(StrictModel):
    kind: str
    label: str
    count: int | None = None
    action_target: str | None = Field(None, alias="actionTarget")


class AgentStatusBarView(StrictModel):
    progress: CreatorTaskProgress
    activity: dict[str, Any] | None = None
    badges: list[AgentStatusBadge] = Field(default_factory=list)
