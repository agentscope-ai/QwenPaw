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
from ...config.config import ModelSlotConfig

# ---------------------------------------------------------------------------
# APScheduler v3 uses ISO 8601 weekday numbering (0=Mon … 6=Sun) for
# CronTrigger(day_of_week=...), while standard crontab uses 0=Sun … 6=Sat.
# from_crontab() does NOT convert either.  Three-letter English abbreviations
# (mon, tue, …, sun) are unambiguous in both systems, so we normalise the
# 5th cron field to abbreviations at validation time.
# ---------------------------------------------------------------------------

_CRONTAB_NUM_TO_NAME: dict[str, str] = {
    "0": "sun",
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}


def _crontab_dow_to_name(field: str) -> str:
    """Convert the day-of-week field from crontab numbers to abbreviations.

    Handles: ``*``, single values, comma-separated lists, and ranges.
    Already-named values (``mon``, ``tue``, …) are passed through unchanged.
    """
    if field == "*":
        return field

    def _convert_token(tok: str) -> str:
        if "/" in tok:
            base, step = tok.rsplit("/", 1)
            return f"{_convert_token(base)}/{step}"
        if "-" in tok:
            parts = tok.split("-", 1)
            return "-".join(_CRONTAB_NUM_TO_NAME.get(p, p) for p in parts)
        return _CRONTAB_NUM_TO_NAME.get(tok, tok)

    return ",".join(_convert_token(t) for t in field.split(","))


class ScheduleSpec(BaseModel):
    type: Literal["cron", "once"] = "cron"
    cron: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: str = "UTC"
    repeat_every_days: Optional[int] = Field(default=None, ge=1)
    repeat_end_type: Optional[Literal["never", "until", "count"]] = None
    repeat_until: Optional[datetime] = None
    repeat_count: Optional[int] = Field(default=None, ge=1)

    @classmethod
    def normalize_cron_5_fields(cls, v: str) -> str:
        parts = [p for p in v.split() if p]
        if len(parts) == 5:
            parts[4] = _crontab_dow_to_name(parts[4])
            return " ".join(parts)

        if len(parts) == 4:
            # treat as: hour dom month dow
            hour, dom, month, dow = parts
            return f"0 {hour} {dom} {month} {_crontab_dow_to_name(dow)}"

        if len(parts) == 3:
            # treat as: dom month dow
            dom, month, dow = parts
            return f"0 0 {dom} {month} {_crontab_dow_to_name(dow)}"

        # 6 fields (seconds) or too short: reject
        raise ValueError(
            "cron must have 5 fields (or 4/3 fields that can be "
            "normalized); seconds not supported",
        )

    @model_validator(mode="after")
    def _validate_schedule_type(self) -> "ScheduleSpec":
        if self.type == "cron":
            if not (self.cron and self.cron.strip()):
                raise ValueError("schedule.type is cron but cron is empty")
            self.cron = self.normalize_cron_5_fields(self.cron)
            self.run_at = None
            self.repeat_every_days = None
            self.repeat_end_type = None
            self.repeat_until = None
            self.repeat_count = None
            return self

        if self.run_at is None:
            raise ValueError("schedule.type is once but run_at is missing")
        self.cron = None
        if self.repeat_every_days is None:
            self.repeat_end_type = None
            self.repeat_until = None
            self.repeat_count = None
            return self

        if self.repeat_end_type is None:
            self.repeat_end_type = "never"

        if self.repeat_end_type == "never":
            self.repeat_until = None
            self.repeat_count = None
            return self

        if self.repeat_end_type == "until":
            if self.repeat_until is None:
                raise ValueError(
                    "repeat_end_type is until but repeat_until is missing",
                )
            if self.repeat_until <= self.run_at:
                raise ValueError(
                    "repeat_until must be later than run_at "
                    "(deadline must be after execution time)",
                )
            self.repeat_count = None
            return self

        if self.repeat_count is None:
            raise ValueError(
                "repeat_end_type is count but repeat_count is missing",
            )
        self.repeat_until = None
        return self


class DispatchTarget(BaseModel):
    user_id: str
    session_id: str


class DispatchSpec(BaseModel):
    type: Literal["channel"] = "channel"
    channel: str = Field(default=DEFAULT_CHANNEL)
    target: DispatchTarget
    mode: Literal["stream", "final"] = Field(default="stream")
    silent: bool = Field(
        default=False,
        description=(
            "Run an agent task without delivering its events to the channel."
        ),
    )
    meta: Dict[str, Any] = Field(default_factory=dict)


class JobRuntimeSpec(BaseModel):
    max_concurrency: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    misfire_grace_seconds: int = Field(default=600, ge=0)
    share_session: bool = Field(
        default=True,
        description=(
            "Whether to share session with target user. "
            "If False, creates isolated context with unique run ID."
        ),
    )
    tool_safety: bool = Field(
        default=False,
        description=(
            "Tool execution safety for this cron job. "
            "When enabled (True), uses AUTO mode — risky tools require "
            "approval (may block unattended execution). "
            "When disabled (False), uses OFF mode — all tools execute "
            "without approval checks, suitable for trusted automated tasks."
        ),
    )


class CronJobRequest(BaseModel):
    """Passthrough payload to workspace.stream_query(request=...).

    This is aligned with AgentRequest(extra="allow"). We keep it permissive.
    """

    model_config = ConfigDict(extra="allow")

    input: Optional[Any] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    model_slot_override: Optional[ModelSlotConfig] = Field(
        default=None,
        description=(
            "Optional per-job model selection. It takes precedence over the "
            "agent's active model without changing persisted configuration."
        ),
    )

    @field_validator("model_slot_override", mode="before")
    @classmethod
    def _normalize_model_slot_override(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        provider_id, separator, model = value.partition(":")
        if not separator:
            raise ValueError(
                "model_slot_override requires non-empty provider_id and model",
            )
        return {
            "provider_id": provider_id.strip(),
            "model": model.strip(),
        }

    @field_validator("model_slot_override")
    @classmethod
    def _validate_model_slot_override(
        cls,
        value: Optional[ModelSlotConfig],
    ) -> Optional[ModelSlotConfig]:
        if value is None:
            return None

        provider_id = value.provider_id.strip()
        model = value.model.strip()
        if not provider_id or not model:
            raise ValueError(
                "model_slot_override requires non-empty provider_id and model",
            )
        return value.model_copy(
            update={"provider_id": provider_id, "model": model},
        )


TaskType = Literal["text", "agent"]


class CronJobSpec(BaseModel):
    id: Optional[str] = None
    name: str
    enabled: bool = True

    schedule: ScheduleSpec
    task_type: TaskType = "agent"
    text: Optional[str] = None
    request: Optional[CronJobRequest] = None
    dispatch: DispatchSpec
    save_result_to_inbox: Optional[bool] = None

    runtime: JobRuntimeSpec = Field(default_factory=JobRuntimeSpec)
    meta: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_task_type_fields(self) -> "CronJobSpec":
        if self.task_type == "text":
            if not (self.text and self.text.strip()):
                raise ValueError("task_type is text but text is empty")
            if (
                self.request is not None
                and self.request.model_slot_override is not None
            ):
                raise ValueError(
                    "model override is only supported for agent tasks",
                )
            if self.dispatch.silent:
                raise ValueError(
                    "silent delivery is only supported for agent tasks",
                )
            self.request = None
        elif self.task_type == "agent":
            if self.request is None:
                raise ValueError("task_type is agent but request is missing")
            # Keep request.user_id and request.session_id in sync with target
            target = self.dispatch.target
            self.request = self.request.model_copy(
                update={
                    "user_id": target.user_id,
                    "session_id": target.session_id,
                },
            )
        if self.save_result_to_inbox is None:
            # Product rule:
            # - text + recurring(cron) => default OFF
            # - all other combinations => default ON
            self.save_result_to_inbox = not (
                self.task_type == "text" and self.schedule.type == "cron"
            )
        return self


class JobsFile(BaseModel):
    version: int = 2
    jobs: list[CronJobSpec] = Field(default_factory=list)


class CronJobState(BaseModel):
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[
        Literal["success", "error", "running", "skipped", "cancelled"]
    ] = None
    last_error: Optional[str] = None


class CronExecutionRecord(BaseModel):
    run_at: datetime
    status: Literal["success", "error", "running", "skipped", "cancelled"]
    error: Optional[str] = None
    trigger: Literal["scheduled", "manual"] = "scheduled"


class CronJobView(BaseModel):
    spec: CronJobSpec
    state: CronJobState = Field(default_factory=CronJobState)


class CronDispatchTargetItem(BaseModel):
    channel: str
    user_id: str
    session_id: str


class CronDispatchTargetsResponse(BaseModel):
    channels: list[str] = Field(default_factory=list)
    items: list[CronDispatchTargetItem] = Field(default_factory=list)
