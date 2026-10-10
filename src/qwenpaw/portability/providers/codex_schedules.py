# -*- coding: utf-8 -*-
"""Read Codex TOML/SQLite automations without mutating or executing them."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import SourceScheduledTask
from .schedule_fields import (
    contains_control as _contains_control,
    metadata_text as _metadata_text,
    text_audit as _text_audit,
)

from .codex_schedule_reader import (
    _MAX_CWDS_JSON_CHARS,
    _MAX_METADATA_LIST_ITEMS,
    _MAX_METADATA_STRING_CHARS,
    _MAX_SMALL_METADATA_STRING_CHARS,
    _MAX_SOURCE_ID_CHARS,
    _WEEKDAYS,
    _local_timezone_name,
    _metadata_scalar,
    _read_project_roots,
    _read_sqlite_candidates,
    _read_toml_candidates,
    _safe_cwd,
    _safe_prompt,
    _safe_rrule,
    _safe_source_id,
    _safe_timezone,
    _safe_title,
    _valid_timezone,
)


def _csv_numbers(value: str, *, minimum: int, maximum: int) -> str | None:
    if not value:
        return None
    result: list[str] = []
    for item in value.split(","):
        if not re.fullmatch(r"\d+", item):
            return None
        number = int(item)
        if number < minimum or number > maximum:
            return None
        normalized = str(number)
        if normalized not in result:
            result.append(normalized)
    return ",".join(result) if result else None


# pylint: disable-next=too-many-branches,too-many-return-statements
def _parse_rrule(
    raw: str,
) -> tuple[dict[str, str] | None, str, bool, str]:
    unfolded: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line.strip()
        elif line.strip():
            unfolded.append(line.strip())
    rule_text = ""
    timezone_hint = ""
    has_dtstart = False
    for line in unfolded:
        upper = line.upper()
        if upper.startswith("DTSTART"):
            if has_dtstart:
                return None, "", True, "RRULE contains multiple DTSTART values"
            has_dtstart = True
            header = line.split(":", 1)[0]
            match = re.search(
                r"(?:^|;)TZID=([^;:]+)",
                header,
                flags=re.IGNORECASE,
            )
            if match:
                timezone_hint = match.group(1).strip()
            continue
        if upper.startswith("RRULE"):
            if rule_text or ":" not in line:
                return (
                    None,
                    timezone_hint,
                    has_dtstart,
                    "RRULE has an invalid envelope",
                )
            rule_text = line.split(":", 1)[1].strip()
            continue
        if "FREQ=" in upper and not rule_text:
            rule_text = line
            continue
        return (
            None,
            timezone_hint,
            has_dtstart,
            "RRULE contains unsupported calendar data",
        )
    if not rule_text:
        return None, timezone_hint, has_dtstart, "RRULE is empty"
    params: dict[str, str] = {}
    for part in rule_text.split(";"):
        if "=" not in part:
            return (
                None,
                timezone_hint,
                has_dtstart,
                "RRULE contains a malformed field",
            )
        key, value = part.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if not key or not value or key in params:
            return (
                None,
                timezone_hint,
                has_dtstart,
                "RRULE contains an empty or duplicate field",
            )
        params[key] = value if key == "TZID" else value.upper()
    embedded_tzid = params.pop("TZID", "")
    if embedded_tzid:
        timezone_hint = embedded_tzid
    return params, timezone_hint, has_dtstart, ""


# pylint: disable-next=too-many-branches,too-many-return-statements,too-many-locals  # noqa: E501
def _rrule_to_cron(raw: str) -> tuple[str, str, str]:
    """Return ``(cron, timezone_hint, unsupported_reason)``."""
    params, timezone_hint, has_dtstart, error = _parse_rrule(raw)
    if params is None:
        return "", timezone_hint, error
    if has_dtstart:
        return (
            "",
            timezone_hint,
            "DTSTART-anchored RRULE cannot be represented exactly by a "
            "QwenPaw recurring cron schedule",
        )
    frequency = params.get("FREQ", "")
    try:
        interval = int(params.get("INTERVAL", "1"))
    except ValueError:
        return "", timezone_hint, "RRULE INTERVAL is not an integer"
    if interval < 1:
        return "", timezone_hint, "RRULE INTERVAL must be positive"

    if frequency in {"DAILY", "WEEKLY"}:
        allowed = {"FREQ", "INTERVAL", "BYHOUR", "BYMINUTE", "BYDAY"}
        unsupported = sorted(set(params) - allowed)
        if unsupported:
            return (
                "",
                timezone_hint,
                f"RRULE field {unsupported[0]} is unsupported",
            )
        if interval != 1:
            return (
                "",
                timezone_hint,
                f"{frequency} INTERVAL={interval} is not cron-equivalent",
            )
        hour = _csv_numbers(params.get("BYHOUR", ""), minimum=0, maximum=23)
        minute = _csv_numbers(
            params.get("BYMINUTE", ""),
            minimum=0,
            maximum=59,
        )
        if hour is None or minute is None:
            return (
                "",
                timezone_hint,
                f"{frequency} RRULE needs valid BYHOUR and BYMINUTE",
            )
        raw_days = params.get("BYDAY", "")
        if frequency == "WEEKLY" and not raw_days:
            return "", timezone_hint, "WEEKLY RRULE needs BYDAY"
        day_of_week = "*"
        if raw_days:
            days: list[str] = []
            for value in raw_days.split(","):
                day = _WEEKDAYS.get(value)
                if day is None:
                    return (
                        "",
                        timezone_hint,
                        "RRULE BYDAY contains an ordinal or invalid weekday",
                    )
                if day not in days:
                    days.append(day)
            day_of_week = ",".join(days)
        return f"{minute} {hour} * * {day_of_week}", timezone_hint, ""

    if frequency == "HOURLY":
        allowed = {"FREQ", "INTERVAL", "BYMINUTE"}
        unsupported = sorted(set(params) - allowed)
        if unsupported:
            return (
                "",
                timezone_hint,
                f"RRULE field {unsupported[0]} is unsupported",
            )
        minute = _csv_numbers(
            params.get("BYMINUTE", "0"),
            minimum=0,
            maximum=59,
        )
        if minute is None:
            return "", timezone_hint, "HOURLY RRULE has an invalid BYMINUTE"
        if interval != 1:
            return (
                "",
                timezone_hint,
                f"HOURLY INTERVAL={interval} has no reliable phase anchor",
            )
        return f"{minute} * * * *", timezone_hint, ""

    if frequency == "MINUTELY":
        allowed = {"FREQ", "INTERVAL"}
        unsupported = sorted(set(params) - allowed)
        if unsupported:
            return (
                "",
                timezone_hint,
                f"RRULE field {unsupported[0]} is unsupported",
            )
        if interval != 1:
            return (
                "",
                timezone_hint,
                f"MINUTELY INTERVAL={interval} has no reliable phase anchor",
            )
        return "* * * * *", timezone_hint, ""

    return (
        "",
        timezone_hint,
        f"RRULE frequency {frequency or '<missing>'} is unsupported",
    )


def _parse_run_at(value: Any, timezone_name: str) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        if len(value) > _MAX_SMALL_METADATA_STRING_CHARS or _contains_control(
            value,
        ):
            return None
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return None
    return parsed


# pylint: disable-next=too-many-branches
def _source_cwds(
    value: Any,
) -> tuple[list[str], bool, dict[str, Any]]:
    malformed = False
    original_text = value if isinstance(value, str) else ""
    if isinstance(value, str):
        if len(value) > _MAX_CWDS_JSON_CHARS:
            return (
                [],
                True,
                _text_audit(value, disposition="omitted"),
            )
        text = value.strip()
        if not text:
            return [], False, {}
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return [], True, {}
        value = decoded
    if value is None:
        return [], False, {}
    if not isinstance(value, (list, tuple)):
        return [], True, {}
    result: list[str] = []
    omitted = 0
    for item in value[:_MAX_METADATA_LIST_ITEMS]:
        cwd, _, reason = _safe_cwd(item)
        if cwd and not reason:
            if cwd not in result:
                result.append(cwd)
        elif item is not None and item != "":
            omitted += 1
    if len(value) > _MAX_METADATA_LIST_ITEMS:
        omitted += len(value) - _MAX_METADATA_LIST_ITEMS
    if omitted or len(result) != len(value):
        malformed = True
    audit: dict[str, Any] = {}
    if malformed and original_text:
        audit = _text_audit(original_text, disposition="normalized")
    elif omitted:
        audit = {"disposition": "normalized", "omitted_items": omitted}
    return result, malformed, audit


def _source_enabled(record: dict[str, Any]) -> tuple[bool, str, str]:
    explicit = record.get("enabled")
    if isinstance(explicit, bool):
        return explicit, "ACTIVE" if explicit else "PAUSED", ""
    if isinstance(explicit, int) and explicit in {0, 1}:
        return bool(explicit), "ACTIVE" if explicit else "PAUSED", ""
    status = _metadata_text(
        record.get("status"),
        _MAX_SMALL_METADATA_STRING_CHARS,
    ).upper()
    if status == "ACTIVE":
        return True, status, ""
    if status == "PAUSED":
        return False, status, ""
    if status:
        return False, status, f"unknown source status {status!r}"
    return False, "", "source status is missing"


# pylint: disable-next=too-many-arguments,too-many-branches,too-many-locals,too-many-statements  # noqa: E501
def _normalise_task(
    record: dict[str, Any],
    *,
    source_format: str,
    source_path: Path,
    project_roots: dict[str, list[str]],
    local_timezone: tuple[str, str],
    warnings: list[str],
) -> SourceScheduledTask:
    automation_id = _safe_source_id(record.get("id"))
    fallback_name = f"Codex automation {automation_id[:8]}"
    name, title_audit, title_reason = _safe_title(
        record.get("name"),
        fallback=fallback_name,
    )
    prompt, prompt_audit, prompt_reason = _safe_prompt(record.get("prompt"))
    source_rrule = record.get("rrule")
    has_source_rrule = isinstance(source_rrule, str) and bool(
        source_rrule.strip(),
    )
    raw_rrule, rrule_audit, rrule_reason = _safe_rrule(source_rrule)
    raw_timezone, timezone_audit, timezone_reason = _safe_timezone(
        record.get("timezone"),
    )
    cron = ""
    rrule_timezone = ""
    rrule_timezone_audit: dict[str, Any] = {}
    unsupported_reason = prompt_reason or rrule_reason or timezone_reason
    if raw_rrule:
        cron, rrule_timezone, parse_reason = _rrule_to_cron(raw_rrule)
        unsupported_reason = unsupported_reason or parse_reason
        (
            rrule_timezone,
            rrule_timezone_audit,
            rrule_timezone_reason,
        ) = _safe_timezone(rrule_timezone)
        unsupported_reason = unsupported_reason or rrule_timezone_reason

    timezone_candidate = raw_timezone or rrule_timezone
    timezone_source = "source" if timezone_candidate else local_timezone[1]
    local_timezone_name, _, local_timezone_reason = _safe_timezone(
        local_timezone[0],
    )
    timezone_name = timezone_candidate or local_timezone_name or "UTC"
    timezone_inferred = not bool(timezone_candidate)
    if not _valid_timezone(timezone_name):
        invalid_timezone = "source timezone is not a valid IANA timezone"
        unsupported_reason = unsupported_reason or invalid_timezone
        timezone_name = "UTC"
        timezone_source = "invalid_source_fallback"
    elif local_timezone_reason and timezone_inferred:
        timezone_name = "UTC"
        timezone_source = "invalid_local_fallback"
        unsupported_reason = unsupported_reason or "local timezone was unsafe"
    if timezone_inferred:
        if timezone_source == "utc_fallback":
            warnings.append(
                f"Codex automation {automation_id!r} stored no timezone; "
                "UTC was used because the device IANA timezone was "
                "unavailable.",
            )
        else:
            warnings.append(
                f"Codex automation {automation_id!r} stored no timezone; "
                f"inferred local IANA timezone {timezone_name!r}.",
            )

    run_at = None
    schedule_type = "unsupported"
    raw_run_at = record.get("run_at")
    declared_type = _metadata_text(record.get("schedule_type"), 32).lower()
    if has_source_rrule:
        if cron and not unsupported_reason:
            schedule_type = "cron"
    elif raw_run_at is not None or declared_type == "once":
        run_at = _parse_run_at(raw_run_at, timezone_name)
        if run_at is None:
            unsupported_reason = unsupported_reason or (
                "one-time schedule has an invalid run_at value"
            )
        elif not unsupported_reason:
            schedule_type = "once"
    else:
        unsupported_reason = unsupported_reason or (
            "automation has no RRULE or one-time run_at"
        )

    if prompt_reason:
        schedule_type = "unsupported"
    if schedule_type == "unsupported":
        cron = ""
        run_at = None

    enabled, source_status, status_warning = _source_enabled(record)
    if status_warning:
        warnings.append(
            f"Codex automation {automation_id!r}: {status_warning}; "
            "kept disabled.",
        )

    cwds, malformed_cwds, cwds_audit = _source_cwds(record.get("cwds"))
    if malformed_cwds:
        warnings.append(
            f"Codex automation {automation_id!r} has malformed cwds metadata.",
        )
    explicit_cwd, cwd_audit, cwd_reason = _safe_cwd(record.get("cwd"))
    if explicit_cwd:
        cwds.insert(0, explicit_cwd)
    if cwd_reason:
        warnings.append(
            f"Codex automation {automation_id!r} has an unsafe cwd; "
            "the value was omitted.",
        )
    project_id = _safe_source_id(record.get("project_id"))
    project_cwds = project_roots.get(project_id, []) if project_id else []
    if not cwds:
        cwds.extend(project_cwds)
    deduplicated_cwds: list[str] = []
    for cwd in cwds[:_MAX_METADATA_LIST_ITEMS]:
        if cwd not in deduplicated_cwds:
            deduplicated_cwds.append(cwd)
    if len(deduplicated_cwds) > 1:
        warnings.append(
            f"Codex automation {automation_id!r} targets multiple workspaces; "
            "the first path was selected and all paths were retained in "
            "metadata.",
        )
    cwd = deduplicated_cwds[0] if deduplicated_cwds else ""

    metadata: dict[str, Any] = {
        "source_format": source_format,
        "source_path": _metadata_text(
            str(source_path),
            _MAX_METADATA_STRING_CHARS,
        ),
        "source_automation_id": automation_id,
        "source_status": source_status,
        "source_kind": _metadata_text(
            record.get("kind"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "source_rrule": raw_rrule,
        "source_cwds": deduplicated_cwds,
        "project_id": project_id,
        "target_type": _metadata_text(
            record.get("target_type"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "target_thread_id": _metadata_text(
            record.get("target_thread_id"),
            _MAX_SOURCE_ID_CHARS,
        ),
        "model": _metadata_text(
            record.get("model"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "reasoning_effort": _metadata_text(
            record.get("reasoning_effort"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "notification_policy": _metadata_text(
            record.get("notification_policy"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "destination": _metadata_text(
            record.get("destination"),
            _MAX_METADATA_STRING_CHARS,
        ),
        "execution_environment": _metadata_text(
            record.get("execution_environment"),
            _MAX_SMALL_METADATA_STRING_CHARS,
        ),
        "local_environment_config_path": _metadata_text(
            record.get("local_environment_config_path"),
            _MAX_METADATA_STRING_CHARS,
        ),
        "timezone_source": timezone_source,
        "timezone_inferred": timezone_inferred,
        "source_created_at": _metadata_scalar(record.get("created_at")),
        "source_updated_at": _metadata_scalar(record.get("updated_at")),
        "source_next_run_at": _metadata_scalar(record.get("next_run_at")),
        "source_last_run_at": _metadata_scalar(record.get("last_run_at")),
        "fidelity": (
            "manual_review"
            if schedule_type != "unsupported"
            else "unsupported"
        ),
    }
    if unsupported_reason:
        safe_unsupported_reason = _metadata_text(
            unsupported_reason,
            _MAX_SMALL_METADATA_STRING_CHARS,
        )
        metadata["unsupported_reason"] = safe_unsupported_reason
        warnings.append(
            f"Codex automation {automation_id!r} schedule was preserved for "
            f"review but not converted: {safe_unsupported_reason}.",
        )
    if prompt_audit:
        metadata["prompt_audit"] = prompt_audit
    if title_audit:
        metadata["title_audit"] = title_audit
    if cwd_audit:
        metadata["cwd_audit"] = cwd_audit
    if cwds_audit:
        metadata["source_cwds_audit"] = cwds_audit
    if timezone_audit:
        metadata["timezone_audit"] = timezone_audit
    if rrule_audit:
        metadata["rrule_audit"] = rrule_audit
    if rrule_timezone_audit:
        metadata["rrule_timezone_audit"] = rrule_timezone_audit
    review_reasons = [
        reason
        for reason in (
            title_reason,
            cwd_reason,
            timezone_reason,
            rrule_reason,
            prompt_reason,
        )
        if reason
    ]
    if review_reasons:
        metadata["field_review_reasons"] = review_reasons
    if not prompt:
        warnings.append(
            f"Codex automation {automation_id!r} has no prompt and cannot be "
            "promoted.",
        )
    return SourceScheduledTask(
        source_id=automation_id,
        name=name,
        schedule_type=schedule_type,
        cron=cron,
        run_at=run_at,
        timezone=timezone_name,
        prompt=prompt,
        cwd=cwd,
        enabled=enabled,
        metadata=metadata,
    )


def discover_codex_scheduled_tasks(
    codex_home: Path,
) -> tuple[list[SourceScheduledTask], list[str], int, set[str]]:
    """Return tasks, warnings, source count, and run thread IDs."""
    warnings: list[str] = []
    codex_home = codex_home.expanduser()
    project_roots = _read_project_roots(codex_home, warnings)
    local_timezone = _local_timezone_name()
    toml_records, toml_discovered = _read_toml_candidates(codex_home, warnings)
    (
        sqlite_records,
        sqlite_discovered,
        run_thread_ids,
    ) = _read_sqlite_candidates(
        codex_home,
        warnings,
    )
    discovered_ids = toml_discovered | sqlite_discovered
    tasks: list[SourceScheduledTask] = []
    for automation_id in sorted(toml_records):
        record, path = toml_records[automation_id]
        tasks.append(
            _normalise_task(
                record,
                source_format="toml",
                source_path=path,
                project_roots=project_roots,
                local_timezone=local_timezone,
                warnings=warnings,
            ),
        )
    for automation_id in sorted(sqlite_records):
        if automation_id in toml_records:
            continue
        record, path = sqlite_records[automation_id]
        tasks.append(
            _normalise_task(
                record,
                source_format="sqlite",
                source_path=path,
                project_roots=project_roots,
                local_timezone=local_timezone,
                warnings=warnings,
            ),
        )
    tasks.sort(key=lambda task: task.source_id)
    return tasks, warnings, len(discovered_ids), run_thread_ids


__all__ = ["discover_codex_scheduled_tasks"]
