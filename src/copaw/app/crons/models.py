# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ..channels.schema import DEFAULT_CHANNEL


class ScheduleSpec(BaseModel):
    type: Literal["cron"] = "cron"
    cron: str = Field(...)
    timezone: str = "UTC"

    @field_validator("cron")
    @classmethod
    def normalize_cron_5_fields(cls, v: str) -> str:
        parts = [p for p in v.split() if p]
        if len(parts) == 5:
            return " ".join(parts)

        if len(parts) == 4:
            # treat as: hour dom month dow
            hour, dom, month, dow = parts
            return f"0 {hour} {dom} {month} {dow}"

        if len(parts) == 3:
            # treat as: dom month dow
            dom, month, dow = parts
            return f"0 0 {dom} {month} {dow}"

        # 6 fields (seconds) or too short: reject
        raise ValueError(
            "cron must have 5 fields "
            "(or 4/3 fields that can be normalized); seconds not supported.",
        )


class DispatchTarget(BaseModel):
    user_id: str
    session_id: str


class DispatchSpec(BaseModel):
    type: Literal["channel"] = "channel"
    channel: str = Field(default=DEFAULT_CHANNEL)
    target: DispatchTarget
    mode: Literal["stream", "final"] = Field(default="stream")
    meta: Dict[str, Any] = Field(default_factory=dict)


class JobRuntimeSpec(BaseModel):
    max_concurrency: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    misfire_grace_seconds: int = Field(default=60, ge=0)


class CronJobRequest(BaseModel):
    """Passthrough payload to runner.stream_query(request=...).

    This is aligned with AgentRequest(extra="allow"). We keep it permissive.
    """

    model_config = ConfigDict(extra="allow")

    input: Any
    session_id: Optional[str] = None
    user_id: Optional[str] = None


TaskType = Literal["text", "agent"]


class CronJobSpec(BaseModel):
    id: str
    name: str
    enabled: bool = True

    schedule: ScheduleSpec
    task_type: TaskType = "agent"
    text: Optional[str] = None
    request: Optional[CronJobRequest] = None
    dispatch: DispatchSpec

    runtime: JobRuntimeSpec = Field(default_factory=JobRuntimeSpec)
    meta: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_task_type_fields(self) -> "CronJobSpec":
        if self.task_type == "text":
            if not (self.text and self.text.strip()):
                raise ValueError("task_type is text but text is empty")
        elif self.task_type == "agent":
            if self.request is None:
                raise ValueError("task_type is agent but request is missing")
        return self

    def build_agent_request(self) -> Dict[str, Any]:
        """Build the effective runner request for an agent cron job.

        Request context and dispatch target are distinct concepts:
        request.* controls the agent execution context, while dispatch.target.*
        controls where the response is delivered. For backward compatibility,
        missing request identity falls back to the dispatch target.
        """

        if self.task_type != "agent" or self.request is None:
            raise ValueError(
                "build_agent_request is only valid for agent jobs",
            )

        req = self.request.model_dump(mode="json")
        req["user_id"] = (
            self.request.user_id or self.dispatch.target.user_id or "cron"
        )
        req["session_id"] = (
            self.request.session_id
            or self.dispatch.target.session_id
            or f"cron:{self.id}"
        )
        return req


class JobsFile(BaseModel):
    version: int = 1
    jobs: list[CronJobSpec] = Field(default_factory=list)


class CronJobState(BaseModel):
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[
        Literal["success", "error", "running", "skipped"]
    ] = None
    last_error: Optional[str] = None


class CronJobView(BaseModel):
    spec: CronJobSpec
    state: CronJobState = Field(default_factory=CronJobState)
