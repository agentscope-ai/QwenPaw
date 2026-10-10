# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from ..channels.schema import DEFAULT_CHANNEL

# ---------------------------------------------------------------------------
# APScheduler v3 uses ISO 8601 weekday numbering (0=Mon … 6=Sun) for
# CronTrigger(day_of_week=...), while standard crontab uses 0=Sun … 6=Sat.
# from_crontab() does NOT convert either.  Three-letter English abbreviations
# (mon, tue, …, sun) are unambiguous in both systems, so we normalise the
# 5th cron field to abbreviations at validation time.
# ---------------------------------------------------------------------------

# Crontab DOW numbering: 0/7=Sun … 6=Sat. APScheduler CronTrigger uses
# ISO weekdays (0=Mon … 6=Sun). Named abbreviations are unambiguous in both
# systems; numeric ranges/steps must be expanded to names so we never emit
# APS-invalid forms like ``sun-sat`` or leave ``*/2`` on the ISO calendar.
_CRONTAB_DOW_NAMES: tuple[str, ...] = (
    "sun",
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
)
_CRONTAB_NUM_TO_NAME: dict[str, str] = {
    str(index): name for index, name in enumerate(_CRONTAB_DOW_NAMES)
}
_CRONTAB_NUM_TO_NAME["7"] = "sun"
_CRONTAB_NAME_TO_NUM: dict[str, int] = {
    name: index for index, name in enumerate(_CRONTAB_DOW_NAMES)
}


def _parse_crontab_dow_atom(atom: str) -> int:
    """Parse one crontab DOW atom (digit or abbreviation).

    Named days and ``0``–``6`` map to 0=Sun…6=Sat. Numeric ``7`` is kept as
    7 so range expansion can include Sunday at the end of a span like
    ``1-7``; callers map 7 → 0 afterwards.
    """
    key = atom.strip().lower()
    if key in _CRONTAB_NAME_TO_NUM:
        return _CRONTAB_NAME_TO_NUM[key]
    if key == "7":
        return 7
    if key in _CRONTAB_NUM_TO_NAME:
        return _CRONTAB_NAME_TO_NUM[_CRONTAB_NUM_TO_NAME[key]]
    raise ValueError(f"invalid cron day-of-week value: {atom}")


def _crontab_dow_token_is_named(tok: str) -> bool:
    """True when the token's DOW endpoints are weekday names, not numbers.

    The step (if any) is ignored: ``fri-sun/1`` is still a named range and
    must pass through unchanged. ``*`` / ``*/n`` are numeric expansions.
    """
    raw = tok.strip()
    if not raw:
        return False
    if "/" in raw:
        base, step_s = raw.rsplit("/", 1)
        if not step_s.isdigit() or int(step_s) < 1 or base == "":
            return False
    else:
        base = raw
    if base == "*":
        return False
    parts = base.split("-", 1) if "-" in base else [base]
    return all(part.strip().lower() in _CRONTAB_NAME_TO_NUM for part in parts)


def _map_crontab_dow_index(day: int) -> int:
    """Map a crontab DOW int (0–7) to 0=Sun…6=Sat (both 0 and 7 → Sunday)."""
    if day == 7:
        return 0
    if 0 <= day <= 6:
        return day
    raise ValueError(f"invalid cron day-of-week value: {day}")


def _expand_crontab_dow_token(tok: str) -> list[int]:
    """Expand one numeric DOW token (value / range / step) to 0=Sun…6=Sat.

    Numeric ``7`` is preserved through ``range()`` / step, then mapped to 0
    with duplicates dropped (so ``0-7`` is a full week, not a reversed
    ``1-0`` range).
    """
    raw = tok.strip()
    if not raw:
        raise ValueError("empty cron day-of-week token")

    step = 1
    base = raw
    if "/" in raw:
        base, step_s = raw.rsplit("/", 1)
        if not step_s.isdigit() or int(step_s) < 1:
            raise ValueError(f"invalid cron day-of-week step: {tok}")
        step = int(step_s)
        if base == "":
            raise ValueError(f"invalid cron day-of-week token: {tok}")

    if base == "*":
        start, end = 0, 6
    elif "-" in base:
        left, right = base.split("-", 1)
        start = _parse_crontab_dow_atom(left)
        end = _parse_crontab_dow_atom(right)
        if start > end:
            raise ValueError(f"invalid cron day-of-week range: {tok}")
    else:
        start = _parse_crontab_dow_atom(base)
        if "/" not in raw:
            return [_map_crontab_dow_index(start)]
        end = 6

    mapped: list[int] = []
    seen: set[int] = set()
    for day in range(start, end + 1, step):
        idx = _map_crontab_dow_index(day)
        if idx not in seen:
            seen.add(idx)
            mapped.append(idx)
    return mapped


def _crontab_dow_to_name(field: str) -> str:
    """Convert crontab DOW numbers to APS-safe weekday abbreviations.

    Handles ``*``, singles, comma lists, ranges, and steps. Numeric forms
    (including ``*`` / ``*/n``) are expanded to an explicit comma list
    (crontab 0=Sun) so APScheduler never sees ISO-ambiguous ``*/2`` or
    invalid ``sun-sat`` ranges. Named tokens (``mon``, ``mon-fri``,
    ``fri-sun/1``, …) pass through unchanged — a digit in the step does
    not make a named range numeric.
    """
    if field == "*":
        return field

    names: list[str] = []
    saw_named = False
    for token in field.split(","):
        raw = token.strip()
        if not raw:
            raise ValueError("empty cron day-of-week token")
        if _crontab_dow_token_is_named(raw):
            saw_named = True
            names.append(raw)
            continue
        days = _expand_crontab_dow_token(raw)
        if not days:
            raise ValueError(f"cron day-of-week matched no days: {raw}")
        names.extend(_CRONTAB_DOW_NAMES[day] for day in days)
    if not names:
        raise ValueError(f"cron day-of-week matched no days: {field}")
    # Full week in crontab Sunday-first order (``0-6``, ``0-7``, …).
    # ``1-7`` is also all days but Monday-first, so keep the explicit list.
    if not saw_named and names == list(_CRONTAB_DOW_NAMES):
        return "*"
    return ",".join(names)


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
        default=False,
        description=(
            "Whether to share session with target user. "
            "If False, executions use one dedicated visible cron-sourced "
            "chat for this job."
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
