# -*- coding: utf-8 -*-
"""Read Qoder schedules safely; an existing v2 store is authoritative."""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import SourceScheduledTask
from ..skill_transfer import read_regular_file
from .schedule_fields import (
    contains_control as _contains_control,
    metadata_text as _metadata_text,
    safe_field as _safe_field,
    safe_prompt as _shared_safe_prompt,
    safe_title as _shared_safe_title,
    text as _text,
)

_SCHEDULE_STORE = (
    Path("globalStorage") / "aicoding.aicoding-agent" / "schedule"
)
_V2_FILENAME = "tasks.v2.json"
_V1_FILENAME = "tasks.v1.json"
_MAX_STORE_BYTES = 32 * 1024 * 1024
_MAX_TASKS = 5_000
_MAX_SOURCE_ID_CHARS = 512
_MAX_TITLE_CHARS = 200
_MAX_PROMPT_CHARS = 20_000
_MAX_PROMPT_BYTES = 80_000
_MAX_CWD_CHARS = 4_000
_MAX_TIMEZONE_CHARS = 100
_MAX_METADATA_STRING_CHARS = 2_048
_MAX_SMALL_METADATA_STRING_CHARS = 256
_TERMINAL_LIFECYCLES = {"cancelled", "completed", "failed"}
_V1_TERMINAL_STATUSES = {"cancelled", "completed", "failed", "running"}
_WALL_CLOCK_RE = re.compile(r"^(?P<hour>\d{2}):(?P<minute>\d{2})$")
_QODER_WEEKDAY_NAMES = (
    "sun",
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
)


@dataclass(frozen=True)
class _ScheduleMapping:
    schedule_type: str = "unsupported"
    cron: str = ""
    run_at: datetime | None = None
    reason: str = ""


def discover_qoder_scheduled_tasks(
    qoder_user_data: Path,
) -> tuple[list[SourceScheduledTask], list[str], int]:
    """Return staged definitions, warnings, and the source task count."""
    user_data = qoder_user_data.expanduser()
    store_root = user_data / _SCHEDULE_STORE
    v2_path = store_root / _V2_FILENAME
    v1_path = store_root / _V1_FILENAME

    # Presence, not successful parsing, makes v2 authoritative.
    if _path_present(v2_path):
        raw_tasks, warning = _load_store(v2_path, version=2)
        if warning:
            return [], [f"{warning} Qoder v1 was not used."], 0
        assert raw_tasks is not None
        return _normalize_tasks(raw_tasks, v2_path, version=2)

    if not _path_present(v1_path):
        return [], [], 0
    raw_tasks, warning = _load_store(v1_path, version=1)
    if warning:
        return [], [warning], 0
    assert raw_tasks is not None
    return _normalize_tasks(raw_tasks, v1_path, version=1)


def _path_present(path: Path) -> bool:
    """Recognize broken links and wrong file types as authoritative damage."""
    try:
        return path.is_symlink() or path.exists()
    except OSError:
        return True


# pylint: disable-next=too-many-return-statements
def _load_store(
    path: Path,
    *,
    version: int,
) -> tuple[list[Any] | None, str]:
    try:
        source_stat = path.lstat()
    except OSError as exc:
        return None, f"Could not inspect Qoder schedule store {path}: {exc}."
    if stat.S_ISLNK(source_stat.st_mode):
        return None, f"Refused symbolic-link Qoder schedule store: {path}."
    if not stat.S_ISREG(source_stat.st_mode):
        return None, f"Qoder schedule store {path} is not a regular file."
    if source_stat.st_size > _MAX_STORE_BYTES:
        return (
            None,
            f"Qoder schedule store {path} exceeds the "
            f"{_MAX_STORE_BYTES}-byte safety limit.",
        )

    try:
        encoded = read_regular_file(
            path,
            expected=source_stat,
            max_bytes=_MAX_STORE_BYTES,
        )
    except ValueError:
        return None, f"Qoder schedule store {path} changed while being read."
    except OSError as exc:
        return None, f"Could not read Qoder schedule store {path}: {exc}."

    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        return None, f"Could not read Qoder schedule store {path}: {exc}."

    if not isinstance(payload, dict) or payload.get("version") != version:
        return (
            None,
            f"Qoder schedule store {path} has an unsupported or malformed "
            f"version (expected {version}).",
        )
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return None, f"Qoder schedule store {path} has no valid tasks array."
    if len(tasks) > _MAX_TASKS:
        return (
            None,
            f"Qoder schedule store {path} contains {len(tasks)} tasks, "
            f"exceeding the {_MAX_TASKS}-task safety limit.",
        )
    if version == 2 and not isinstance(payload.get("runs"), list):
        return None, f"Qoder schedule store {path} has no valid runs array."
    return tasks, ""


def _normalize_tasks(
    raw_tasks: list[Any],
    store_path: Path,
    *,
    version: int,
) -> tuple[list[SourceScheduledTask], list[str], int]:
    tasks: list[SourceScheduledTask] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            warnings.append(
                "Skipped malformed Qoder scheduled task at index "
                f"{index} in {store_path}.",
            )
            continue
        source_task_id = _text(raw.get("id"))
        if not source_task_id:
            warnings.append(
                "Skipped Qoder scheduled task without an id at index "
                f"{index} in {store_path}.",
            )
            continue
        if len(source_task_id) > _MAX_SOURCE_ID_CHARS or _contains_control(
            source_task_id,
        ):
            warnings.append(
                "Skipped Qoder scheduled task with an unsafe or oversized "
                f"id at index {index} in {store_path}.",
            )
            continue
        if source_task_id in seen_ids:
            warnings.append(
                f"Skipped duplicate Qoder scheduled task id "
                f"{source_task_id!r} in {store_path}.",
            )
            continue
        seen_ids.add(source_task_id)

        lifecycle = _source_lifecycle(raw, version=version)
        if _should_filter(raw, lifecycle=lifecycle, version=version):
            continue
        valid_lifecycles = (
            {"pending"} if version == 1 else {"active", "paused"}
        )
        if lifecycle not in valid_lifecycles:
            warnings.append(
                f"Skipped Qoder scheduled task {source_task_id!r} with an "
                f"unknown lifecycle {lifecycle!r}.",
            )
            continue

        task = _normalize_task(
            raw,
            source_task_id=source_task_id,
            lifecycle=lifecycle,
            store_path=store_path,
            version=version,
        )
        tasks.append(task)
        if task.schedule_type == "unsupported":
            task_metadata = getattr(task, "metadata", {})
            reason = (
                task_metadata.get("schedule_review_reason") or "unknown"
                if isinstance(task_metadata, dict)
                else "unknown"
            )
            warnings.append(
                f"Qoder scheduled task {source_task_id!r} has unsupported "
                f"timing semantics ({reason}); it was retained for review.",
            )

    return tasks, warnings, len(raw_tasks)


def _source_lifecycle(raw: dict[str, Any], *, version: int) -> str:
    if version == 1:
        return _metadata_text(
            raw.get("status"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ).lower()

    lifecycle = _metadata_text(
        raw.get("lifecycle"),
        _MAX_SMALL_METADATA_STRING_CHARS,
    ).lower()
    if lifecycle:
        return lifecycle
    status = _metadata_text(
        raw.get("status"),
        _MAX_SMALL_METADATA_STRING_CHARS,
    ).lower()
    if status == "cancelled":
        return "cancelled"
    if status in {"completed", "failed", "running"}:
        return "completed"
    if status == "pending":
        return "paused" if raw.get("enabled") is False else "active"
    return ""


def _should_filter(
    raw: dict[str, Any],
    *,
    lifecycle: str,
    version: int,
) -> bool:
    if raw.get("deletedAt") or raw.get("cancelledAt"):
        return True
    if version == 1:
        return lifecycle in _V1_TERMINAL_STATUSES
    return lifecycle in _TERMINAL_LIFECYCLES


# pylint: disable-next=too-many-branches,too-many-statements
def _normalize_task(
    raw: dict[str, Any],
    *,
    source_task_id: str,
    lifecycle: str,
    store_path: Path,
    version: int,
) -> SourceScheduledTask:
    raw_timezone = _source_timezone(raw, version=version)
    timezone_name, timezone_audit, timezone_reason = _safe_timezone(
        raw_timezone,
    )
    mapping = _map_schedule(raw, version=version, timezone_name=timezone_name)
    source_enabled = (
        lifecycle == "active"
        if version == 2
        else bool(raw.get("enabled", lifecycle == "pending"))
    )

    prompt_value = raw.get("prompt")
    prompt = prompt_value if isinstance(prompt_value, str) else ""
    if not prompt.strip() and isinstance(raw.get("payload"), dict):
        payload_prompt = raw["payload"].get("message")
        prompt = payload_prompt if isinstance(payload_prompt, str) else ""
    prompt, prompt_audit, prompt_reason = _safe_prompt(prompt)
    if prompt_reason:
        # An omitted instruction must never become an executable target job.
        mapping = _ScheduleMapping(reason=prompt_reason)

    raw_title = raw.get("title")
    title, title_audit, title_reason = _safe_title(
        raw_title if isinstance(raw_title, str) else "",
        fallback=f"Qoder schedule {source_task_id}",
    )
    raw_cwd = raw.get("workspacePath")
    cwd, cwd_audit, cwd_reason = _safe_cwd(
        raw_cwd if isinstance(raw_cwd, str) else "",
    )
    target_remote_authority = _metadata_text(
        raw.get("targetRemoteAuthority"),
        _MAX_METADATA_STRING_CHARS,
    )
    workspace_status, workspace_exists, workspace_reason = _workspace_status(
        cwd,
        target_remote_authority=target_remote_authority,
    )
    if cwd_reason:
        workspace_status = "blocked_unsafe"
        workspace_exists = None

    review_reasons = ["activation_requires_user_review"]
    if lifecycle == "paused" or not source_enabled:
        review_reasons.append("source_task_paused")
    if version == 1:
        review_reasons.append("legacy_v1_definition")
    if mapping.reason:
        review_reasons.append(mapping.reason)
    if timezone_reason:
        review_reasons.append(timezone_reason)
    if title_reason:
        review_reasons.append(title_reason)
    if cwd_reason:
        review_reasons.append(cwd_reason)
    if workspace_reason:
        review_reasons.append(workspace_reason)
    source_model = _metadata_text(
        raw.get("model"),
        _MAX_SMALL_METADATA_STRING_CHARS,
    )
    if source_model:
        review_reasons.append("model_compatibility_review")
    if raw.get("goalEnabled") is True:
        review_reasons.append("goal_mode_compatibility_review")
    execution_target = _safe_execution_target(raw.get("executionTarget"))
    if (
        isinstance(execution_target, dict)
        and execution_target.get("kind") == "existingSession"
    ):
        review_reasons.append("legacy_existing_session_target_not_preserved")
    review_reasons = _unique(review_reasons)

    source_schedule = _source_schedule(raw, version=version)
    metadata: dict[str, Any] = {
        "provider": "qoder",
        "source_store_version": version,
        "source_store_path": _metadata_text(
            str(store_path),
            _MAX_METADATA_STRING_CHARS,
        ),
        "source_task_id": source_task_id,
        "source_lifecycle": lifecycle,
        "source_status": _metadata_text(
            raw.get("status"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "source_enabled": source_enabled,
        "target_default_enabled": False,
        "review_required": True,
        "review_reasons": review_reasons,
        "schedule_fidelity": (
            "unsupported"
            if mapping.schedule_type == "unsupported"
            else "exact"
        ),
        "source_schedule": source_schedule,
        "source_next_run_at": _metadata_text(
            raw.get("nextRunAt") or raw.get("nextFireAt"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "source_owner_authority": _metadata_text(
            raw.get("ownerAuthority"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "source_owner_account_id": _metadata_text(
            raw.get("ownerAccountId"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "source_target_remote_authority": target_remote_authority,
        "source_execution_target": execution_target,
        "source_workspace_type": _metadata_text(
            raw.get("workspaceType"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "workspace_status": workspace_status,
        "workspace_exists": workspace_exists,
        "source_model": source_model,
        "source_goal_enabled": raw.get("goalEnabled") is True,
        "source": _metadata_text(
            raw.get("source"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "source_request_id": _metadata_text(
            raw.get("sourceRequestId"),
            _MAX_METADATA_STRING_CHARS,
        ),
        "source_tool_call_id": _metadata_text(
            raw.get("sourceToolCallId"),
            _MAX_METADATA_STRING_CHARS,
        ),
        "created_at": _metadata_text(
            raw.get("createdAt"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "updated_at": _metadata_text(
            raw.get("updatedAt"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
    }
    if mapping.reason:
        metadata["schedule_review_reason"] = mapping.reason
    if version == 1:
        metadata["legacy_store"] = True
    if prompt_reason:
        metadata["unsupported_reason"] = prompt_reason
    if prompt_audit:
        metadata["prompt_audit"] = prompt_audit
    if title_audit:
        metadata["title_audit"] = title_audit
    if cwd_audit:
        metadata["cwd_audit"] = cwd_audit
    if timezone_audit:
        metadata["timezone_audit"] = timezone_audit

    return SourceScheduledTask(
        source_id=f"qoder:schedule:{source_task_id}",
        name=title,
        schedule_type=mapping.schedule_type,
        cron=mapping.cron,
        run_at=mapping.run_at,
        timezone=timezone_name,
        prompt=prompt,
        cwd=cwd,
        enabled=source_enabled,
        metadata=metadata,
    )


def _source_schedule(raw: dict[str, Any], *, version: int) -> dict[str, Any]:
    if version == 2:
        schedule = raw.get("schedule")
        if not isinstance(schedule, dict):
            return {}
        normalized: dict[str, Any] = {}
        start_at = _metadata_text(
            schedule.get("startAt"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        )
        timezone_name = _metadata_text(
            schedule.get("timezone"),
            _MAX_TIMEZONE_CHARS,
        )
        if start_at:
            normalized["startAt"] = start_at
        if timezone_name:
            normalized["timezone"] = timezone_name
        repeat = _safe_repeat(schedule.get("repeat"))
        if repeat:
            normalized["repeat"] = repeat
        return normalized
    return {
        "kind": "at",
        "at": _metadata_text(
            raw.get("fireAt"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "timezone": _metadata_text(
            raw.get("timezone"),
            _MAX_TIMEZONE_CHARS,
        ),
    }


def _safe_repeat(value: Any) -> dict[str, Any]:
    """Keep only Qoder repeat fields with bounded scalar values."""
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    frequency = _metadata_text(value.get("frequency"), 32)
    if frequency:
        normalized["frequency"] = frequency

    for field in ("minutes", "minute"):
        integer = _integer(value.get(field))
        if integer is not None and abs(integer) <= 10_000_000:
            normalized[field] = integer

    wall_clock = _metadata_text(value.get("time"), 16)
    if wall_clock:
        normalized["time"] = wall_clock

    weekdays = value.get("weekdays")
    if isinstance(weekdays, list):
        bounded_weekdays: list[int] = []
        for item in weekdays[:7]:
            integer = _integer(item)
            if integer is not None and -100 <= integer <= 100:
                bounded_weekdays.append(integer)
        normalized["weekdays"] = bounded_weekdays
    return normalized


def _safe_execution_target(value: Any) -> dict[str, str]:
    """Preserve known execution-target identity without nested payloads."""
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    kind = _metadata_text(value.get("kind"), 64)
    if kind:
        normalized["kind"] = kind
    for field in ("sessionId", "questTaskId"):
        field_value = _metadata_text(value.get(field), _MAX_SOURCE_ID_CHARS)
        if field_value:
            normalized[field] = field_value
    return normalized


def _safe_prompt(value: str) -> tuple[str, dict[str, Any], str]:
    return _shared_safe_prompt(
        value,
        max_chars=_MAX_PROMPT_CHARS,
        max_bytes=_MAX_PROMPT_BYTES,
    )


def _safe_title(
    value: str,
    *,
    fallback: str,
) -> tuple[str, dict[str, Any], str]:
    return _shared_safe_title(
        value,
        fallback=fallback or "Qoder schedule",
        max_chars=_MAX_TITLE_CHARS,
    )


def _safe_cwd(value: str) -> tuple[str, dict[str, Any], str]:
    return _safe_field(
        value,
        max_chars=_MAX_CWD_CHARS,
        max_bytes=None,
        reason="source_cwd_blocked",
    )


def _safe_timezone(value: str) -> tuple[str, dict[str, Any], str]:
    return _safe_field(
        value,
        max_chars=_MAX_TIMEZONE_CHARS,
        max_bytes=None,
        reason="source_timezone_blocked",
    )


def _source_timezone(raw: dict[str, Any], *, version: int) -> str:
    if version == 2 and isinstance(raw.get("schedule"), dict):
        value = raw["schedule"].get("timezone")
        if isinstance(value, str) and value.strip():
            return value
    value = raw.get("timezone")
    return value if isinstance(value, str) else ""


# pylint: disable-next=too-many-return-statements,too-many-branches
def _map_schedule(
    raw: dict[str, Any],
    *,
    version: int,
    timezone_name: str,
) -> _ScheduleMapping:
    zone = _load_timezone(timezone_name)
    if zone is None:
        return _ScheduleMapping(
            reason=(
                "missing_timezone" if not timezone_name else "invalid_timezone"
            ),
        )

    if version == 1:
        run_at = _parse_aware_datetime(raw.get("fireAt"))
        if run_at is None:
            return _ScheduleMapping(reason="invalid_start_at")
        return _ScheduleMapping(schedule_type="once", run_at=run_at)

    schedule = raw.get("schedule")
    if not isinstance(schedule, dict):
        return _ScheduleMapping(reason="missing_schedule_definition")
    start_at = _parse_aware_datetime(schedule.get("startAt"))
    if start_at is None:
        return _ScheduleMapping(reason="invalid_start_at")
    repeat = schedule.get("repeat")
    if not isinstance(repeat, dict):
        return _ScheduleMapping(reason="missing_repeat_definition")

    frequency = _metadata_text(repeat.get("frequency"), 32)
    if frequency == "none":
        return _ScheduleMapping(schedule_type="once", run_at=start_at)
    if frequency == "interval":
        minutes = _integer(repeat.get("minutes"))
        if minutes is None or minutes < 1 or minutes > 525_600:
            return _ScheduleMapping(reason="invalid_interval_minutes")
        cron = _interval_cron(minutes, start_at=start_at, zone=zone)
        if not cron:
            return _ScheduleMapping(
                reason="interval_not_exactly_representable",
            )
        return _ScheduleMapping(schedule_type="cron", cron=cron)
    if frequency == "every-hour":
        minute = _integer(repeat.get("minute"))
        if minute is None or not 0 <= minute <= 59:
            return _ScheduleMapping(reason="invalid_hourly_minute")
        return _ScheduleMapping(
            schedule_type="cron",
            cron=f"{minute} * * * *",
        )
    if frequency == "daily":
        wall_clock = _wall_clock(repeat.get("time"))
        if wall_clock is None:
            return _ScheduleMapping(reason="invalid_daily_time")
        hour, minute = wall_clock
        return _ScheduleMapping(
            schedule_type="cron",
            cron=f"{minute} {hour} * * *",
        )
    if frequency == "weekly":
        wall_clock = _wall_clock(repeat.get("time"))
        weekdays = _weekdays(repeat.get("weekdays"))
        if wall_clock is None:
            return _ScheduleMapping(reason="invalid_weekly_time")
        if weekdays is None:
            return _ScheduleMapping(reason="invalid_weekdays")
        hour, minute = wall_clock
        weekday_field = ",".join(
            _QODER_WEEKDAY_NAMES[item] for item in weekdays
        )
        return _ScheduleMapping(
            schedule_type="cron",
            cron=f"{minute} {hour} * * {weekday_field}",
        )
    return _ScheduleMapping(reason="unsupported_repeat_frequency")


def _interval_cron(
    minutes: int,
    *,
    start_at: datetime,
    zone: ZoneInfo,
) -> str:
    """Return an exact five-field phase pattern, or an empty string."""
    local_start = start_at.astimezone(zone)
    if local_start.second or local_start.microsecond:
        return ""

    if minutes < 60:
        if 60 % minutes:
            return ""
        offset = local_start.minute % minutes
        minute_field = _phase_field(60, minutes, offset)
        return f"{minute_field} * * * *"

    if minutes % 60:
        return ""
    hours = minutes // 60
    if hours > 24 or 24 % hours:
        return ""
    if hours == 24:
        hour_field = str(local_start.hour)
    else:
        hour_field = _phase_field(24, hours, local_start.hour % hours)
    return f"{local_start.minute} {hour_field} * * *"


def _phase_field(cycle: int, step: int, offset: int) -> str:
    if step == 1:
        return "*"
    if offset == 0:
        return f"*/{step}"
    return ",".join(str(value) for value in range(offset, cycle, step))


def _parse_aware_datetime(value: Any) -> datetime | None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_SMALL_METADATA_STRING_CHARS
    ):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _load_timezone(value: str) -> ZoneInfo | None:
    if not value:
        return None
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _wall_clock(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or len(value) > 16:
        return None
    match = _WALL_CLOCK_RE.fullmatch(value.strip())
    if match is None:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _weekdays(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not value or len(value) > 7:
        return None
    normalized: set[int] = set()
    for item in value:
        weekday = _integer(item)
        if weekday is None or not 0 <= weekday <= 6:
            return None
        normalized.add(weekday)
    return sorted(normalized)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if int(value) != value:
        return None
    return int(value)


def _workspace_status(
    cwd: str,
    *,
    target_remote_authority: Any,
) -> tuple[str, bool | None, str]:
    if not cwd:
        return "not_set", None, ""
    if _text(target_remote_authority):
        # A local existence check says nothing about an SSH/WSL/container path.
        return "remote_unverified", None, "remote_workspace_unverified"
    candidate = Path(cwd).expanduser()
    if not candidate.is_absolute():
        return "not_absolute", False, "workspace_path_not_absolute"
    try:
        exists = candidate.exists()
    except OSError:
        exists = False
    if not exists:
        return "missing", False, "workspace_path_missing"
    return "exists", True, ""


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = ["discover_qoder_scheduled_tasks"]
