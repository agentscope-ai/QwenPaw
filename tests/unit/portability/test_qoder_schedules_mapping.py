# -*- coding: utf-8 -*-
"""Qoder schedule mapping: frequency table, interval phases, review metadata.

Every expected cron string and review reason here was measured by running
the provider against a temporary store, not derived by hand, because the
interval phase pattern depends on the start time rendered in the target
timezone rather than on the raw minute count.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from qwenpaw.portability.models import SourceScheduledTask
from qwenpaw.portability.providers import qoder_schedules
from qwenpaw.portability.providers.qoder_schedules import (
    discover_qoder_scheduled_tasks,
)

_START = "2026-08-20T00:00:00Z"
_UNSET = object()


def _discover_v2(
    tasks: list[dict[str, Any]],
) -> tuple[list[SourceScheduledTask], list[str], int]:
    """Run discovery over one throwaway v2 store."""
    base = Path(tempfile.mkdtemp())
    path = (
        base
        / "globalStorage"
        / "aicoding.aicoding-agent"
        / "schedule"
        / "tasks.v2.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 2, "tasks": tasks, "runs": []}),
        encoding="utf-8",
    )
    try:
        return discover_qoder_scheduled_tasks(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _task(
    repeat: Any = _UNSET,
    *,
    start_at: str = _START,
    zone: Any = "UTC",
    top_timezone: Any = _UNSET,
    schedule: Any = _UNSET,
    **overrides: Any,
) -> dict[str, Any]:
    """Build one v2 task; ``None`` is a real value, only ``_UNSET`` omits."""
    task: dict[str, Any] = {
        "id": "a",
        "title": "T",
        "prompt": "P",
        "lifecycle": "active",
        "enabled": True,
    }
    if schedule is _UNSET:
        task["schedule"] = {
            "startAt": start_at,
            "timezone": zone,
            "repeat": {"frequency": "none"} if repeat is _UNSET else repeat,
        }
    elif schedule is not None:
        task["schedule"] = schedule
    if top_timezone is not _UNSET:
        task["timezone"] = top_timezone
    task.update(overrides)
    return task


def _mapped(task: dict[str, Any]) -> SourceScheduledTask:
    tasks, warnings, count = _discover_v2([task])
    assert count == 1
    assert len(tasks) == 1, warnings
    return tasks[0]


def _unsupported_reason(task: dict[str, Any]) -> str:
    mapped = _mapped(task)
    assert mapped.schedule_type == "unsupported"
    assert mapped.cron == ""
    assert mapped.run_at is None
    reason = mapped.metadata["schedule_review_reason"]
    assert isinstance(reason, str)
    assert reason in mapped.metadata["review_reasons"]
    assert mapped.metadata["schedule_fidelity"] == "unsupported"
    return reason


# --------------------------------------------------------------------------
# the exact-frequency table
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("repeat", "start_at", "cron"),
    [
        ({"frequency": "every-hour", "minute": 5}, _START, "5 * * * *"),
        ({"frequency": "every-hour", "minute": 0}, _START, "0 * * * *"),
        ({"frequency": "every-hour", "minute": 59}, _START, "59 * * * *"),
        ({"frequency": "daily", "time": "09:05"}, _START, "5 9 * * *"),
        ({"frequency": "daily", "time": "00:00"}, _START, "0 0 * * *"),
        ({"frequency": "daily", "time": "23:59"}, _START, "59 23 * * *"),
        (
            {"frequency": "weekly", "time": "23:59", "weekdays": [0, 6]},
            _START,
            "59 23 * * sun,sat",
        ),
        (
            {"frequency": "weekly", "time": "08:30", "weekdays": [3, 1, 1]},
            _START,
            "30 8 * * mon,wed",
        ),
        (
            {"frequency": "weekly", "time": "08:30", "weekdays": [2]},
            _START,
            "30 8 * * tue",
        ),
    ],
    ids=[
        "hourly-5",
        "hourly-0",
        "hourly-59",
        "daily-0905",
        "daily-midnight",
        "daily-late",
        "weekly-weekend",
        "weekly-dedup-sorted",
        "weekly-single",
    ],
)
def test_exact_frequencies_map_to_cron(
    repeat: dict[str, Any],
    start_at: str,
    cron: str,
) -> None:
    mapped = _mapped(_task(repeat, start_at=start_at))

    assert mapped.schedule_type == "cron"
    assert mapped.cron == cron
    assert mapped.run_at is None
    assert mapped.metadata["schedule_fidelity"] == "exact"
    assert "schedule_review_reason" not in mapped.metadata


def test_frequency_none_maps_to_a_single_run_at() -> None:
    mapped = _mapped(_task({"frequency": "none"}))

    assert mapped.schedule_type == "once"
    assert mapped.cron == ""
    assert mapped.run_at is not None
    assert mapped.run_at.isoformat() == "2026-08-20T00:00:00+00:00"
    assert mapped.metadata["schedule_fidelity"] == "exact"


# --------------------------------------------------------------------------
# interval phase arithmetic (start time is rendered in the target zone)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "start_at", "zone_name", "cron"),
    [
        (1, _START, "UTC", "* * * * *"),
        (15, _START, "UTC", "*/15 * * * *"),
        (20, _START, "UTC", "*/20 * * * *"),
        (15, "2026-08-20T00:07:00Z", "UTC", "7,22,37,52 * * * *"),
        (30, "2026-08-20T00:45:00Z", "UTC", "15,45 * * * *"),
        (60, "2026-08-20T03:30:00Z", "UTC", "30 * * * *"),
        (120, _START, "UTC", "0 */2 * * *"),
        (
            120,
            "2026-08-20T05:30:00Z",
            "UTC",
            "30 1,3,5,7,9,11,13,15,17,19,21,23 * * *",
        ),
        (480, "2026-08-20T03:10:00Z", "UTC", "10 3,11,19 * * *"),
        (1440, "2026-08-20T05:30:00Z", "UTC", "30 5 * * *"),
        # +08:00 renders 13:30 local, so the daily phase differs from UTC.
        (1440, "2026-08-20T05:30:00Z", "Asia/Shanghai", "30 13 * * *"),
        (120, _START, "Asia/Shanghai", "0 */2 * * *"),
    ],
    ids=[
        "every-minute",
        "quarter-aligned",
        "third-aligned",
        "quarter-offset-7",
        "half-offset-45",
        "hourly-offset-30",
        "two-hours-aligned",
        "two-hours-offset",
        "eight-hours-offset",
        "daily-utc",
        "daily-shanghai",
        "two-hours-shanghai",
    ],
)
def test_exact_intervals_map_to_phased_cron(
    minutes: int,
    start_at: str,
    zone_name: str,
    cron: str,
) -> None:
    repeat = {"frequency": "interval", "minutes": minutes}

    mapped = _mapped(_task(repeat, start_at=start_at, zone=zone_name))

    assert mapped.schedule_type == "cron"
    assert mapped.cron == cron
    assert mapped.timezone == zone_name
    assert mapped.metadata["schedule_fidelity"] == "exact"


@pytest.mark.parametrize(
    ("minutes", "start_at"),
    [
        (7, _START),  # 60 % 7 != 0: no exact minute phase exists
        (90, _START),  # not a whole hour count
        (420, _START),  # 7 hours: 24 % 7 != 0
        (780, _START),  # 13 hours: 24 % 13 != 0
        (1500, _START),  # 25 hours: longer than a day
        (525_600, _START),  # a whole year: 8760 hours
        (15, "2026-08-20T00:00:30Z"),  # sub-minute start offset
        (15, "2026-08-20T00:00:00.500Z"),  # sub-microsecond offset
    ],
    ids=[
        "7-min",
        "90-min",
        "7-hours",
        "13-hours",
        "25-hours",
        "one-year",
        "seconds-in-start",
        "micros-in-start",
    ],
)
def test_inexact_intervals_are_retained_for_review(
    minutes: int,
    start_at: str,
) -> None:
    repeat = {"frequency": "interval", "minutes": minutes}

    reason = _unsupported_reason(_task(repeat, start_at=start_at))

    assert reason == "interval_not_exactly_representable"


@pytest.mark.parametrize(
    "minutes",
    [0, -15, 525_601, "15", 15.5, None, True, [15], 1e9],
    ids=[
        "zero",
        "negative",
        "above-cap",
        "string",
        "fractional",
        "missing",
        "boolean",
        "list",
        "float-1e9",
    ],
)
def test_out_of_range_interval_minutes_are_rejected(minutes: Any) -> None:
    repeat = {"frequency": "interval", "minutes": minutes}

    assert _unsupported_reason(_task(repeat)) == "invalid_interval_minutes"


@pytest.mark.parametrize(
    "minute",
    [60, -1, "5", 5.5, None, True, [5]],
    ids=[
        "above-59",
        "negative",
        "string",
        "fractional",
        "missing",
        "bool",
        "list",
    ],
)
def test_invalid_hourly_minute_is_rejected(minute: Any) -> None:
    repeat = {"frequency": "every-hour", "minute": minute}

    assert _unsupported_reason(_task(repeat)) == "invalid_hourly_minute"


@pytest.mark.parametrize(
    "wall_clock",
    ["25:00", "09:60", "9:05", "", "09:05:00", 9, None, "x" * 17, [9, 5]],
    ids=[
        "hour-25",
        "minute-60",
        "single-digit-hour",
        "empty",
        "with-seconds",
        "int",
        "missing",
        "too-long",
        "list",
    ],
)
def test_invalid_daily_time_is_rejected(wall_clock: Any) -> None:
    repeat = {"frequency": "daily", "time": wall_clock}

    assert _unsupported_reason(_task(repeat)) == "invalid_daily_time"


@pytest.mark.parametrize(
    ("wall_clock", "weekdays", "reason"),
    [
        ("xx", [1], "invalid_weekly_time"),
        ("08:30", [7], "invalid_weekdays"),
        ("08:30", [-1], "invalid_weekdays"),
        ("08:30", [], "invalid_weekdays"),
        ("08:30", [0, 1, 2, 3, 4, 5, 6, 0], "invalid_weekdays"),
        ("08:30", "mon", "invalid_weekdays"),
        ("08:30", None, "invalid_weekdays"),
        ("08:30", [1, "a"], "invalid_weekdays"),
        ("08:30", [1.5], "invalid_weekdays"),
    ],
    ids=[
        "bad-time",
        "weekday-7",
        "weekday-negative",
        "weekday-empty",
        "weekday-eight",
        "weekday-string",
        "weekday-missing",
        "weekday-non-int",
        "weekday-fractional",
    ],
)
def test_invalid_weekly_parts_are_rejected(
    wall_clock: str,
    weekdays: Any,
    reason: str,
) -> None:
    repeat = {"frequency": "weekly", "time": wall_clock, "weekdays": weekdays}

    assert _unsupported_reason(_task(repeat)) == reason


def test_weekly_time_is_checked_before_weekdays() -> None:
    repeat = {"frequency": "weekly", "time": "99:99", "weekdays": [7]}

    assert _unsupported_reason(_task(repeat)) == "invalid_weekly_time"


@pytest.mark.parametrize(
    ("repeat", "reason"),
    [
        ({"frequency": "fortnightly"}, "unsupported_repeat_frequency"),
        ({"frequency": ""}, "unsupported_repeat_frequency"),
        ({}, "unsupported_repeat_frequency"),
        ({"frequency": 5}, "unsupported_repeat_frequency"),
        ("not-a-dict", "missing_repeat_definition"),
        (None, "missing_repeat_definition"),
        ([1, 2], "missing_repeat_definition"),
    ],
    ids=[
        "unknown-frequency",
        "blank-frequency",
        "no-frequency",
        "non-string-frequency",
        "repeat-string",
        "repeat-missing",
        "repeat-list",
    ],
)
def test_unknown_or_missing_repeat_is_rejected(
    repeat: Any,
    reason: str,
) -> None:
    assert _unsupported_reason(_task(repeat)) == reason


@pytest.mark.parametrize(
    ("start_at", "reason"),
    [
        ("nope", "invalid_start_at"),
        ("2026-08-20T00:00:00", "invalid_start_at"),  # naive: no zone
        ("", "invalid_start_at"),
        (None, "invalid_start_at"),
        (12345, "invalid_start_at"),
        ("x" * 300, "invalid_start_at"),
    ],
    ids=["unparsable", "naive", "blank", "missing", "int", "too-long"],
)
def test_bad_start_at_is_rejected(start_at: Any, reason: str) -> None:
    repeat = {"frequency": "none"}

    assert _unsupported_reason(_task(repeat, start_at=start_at)) == reason


def test_missing_schedule_definition_is_rejected() -> None:
    task = _task(schedule=None, top_timezone="UTC")

    assert _unsupported_reason(task) == "missing_schedule_definition"


def test_non_dict_schedule_is_rejected() -> None:
    task = _task(schedule="every day", top_timezone="UTC")

    assert _unsupported_reason(task) == "missing_schedule_definition"


# --------------------------------------------------------------------------
# timezone resolution
# --------------------------------------------------------------------------


def test_missing_timezone_is_reported() -> None:
    assert _unsupported_reason(_task(zone="")) == "missing_timezone"


def test_unknown_timezone_is_reported() -> None:
    assert _unsupported_reason(_task(zone="Not/AZone")) == "invalid_timezone"


def test_non_string_timezone_is_treated_as_missing() -> None:
    assert _unsupported_reason(_task(zone=5)) == "missing_timezone"


def test_blank_schedule_timezone_falls_back_to_task_field() -> None:
    task = _task(
        {"frequency": "daily", "time": "09:05"},
        zone="   ",
        top_timezone="Asia/Shanghai",
    )

    mapped = _mapped(task)

    assert mapped.timezone == "Asia/Shanghai"
    assert mapped.cron == "5 9 * * *"


def test_absent_schedule_timezone_falls_back_to_task_field() -> None:
    task = _task(
        schedule={
            "startAt": _START,
            "repeat": {"frequency": "daily", "time": "09:05"},
        },
        top_timezone="Asia/Shanghai",
    )

    mapped = _mapped(task)

    assert mapped.timezone == "Asia/Shanghai"
    assert mapped.cron == "5 9 * * *"


def test_non_string_task_timezone_is_ignored() -> None:
    task = _task(
        schedule={"startAt": _START, "repeat": {"frequency": "none"}},
        top_timezone=7,
    )

    mapped = _mapped(task)

    assert mapped.timezone == ""
    assert mapped.metadata["schedule_review_reason"] == "missing_timezone"


def test_blocked_timezone_is_audited_and_emptied() -> None:
    task = _task(zone="Z" * 120)

    mapped = _mapped(task)

    assert mapped.timezone == ""
    audit = mapped.metadata["timezone_audit"]
    assert audit["disposition"] == "omitted"
    assert audit["original_chars"] == 120
    assert mapped.metadata["review_reasons"] == [
        "activation_requires_user_review",
        "missing_timezone",
        "source_timezone_blocked",
    ]


def test_named_zone_is_kept_and_applied_to_daily_time() -> None:
    task = _task(
        {"frequency": "daily", "time": "09:05"},
        zone="Asia/Shanghai",
    )

    mapped = _mapped(task)

    assert mapped.timezone == "Asia/Shanghai"
    assert mapped.cron == "5 9 * * *"


# --------------------------------------------------------------------------
# scalar parsers used by the mapping table
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("09:05", (9, 5)),
        ("  09:05  ", (9, 5)),
        ("00:00", (0, 0)),
        ("23:59", (23, 59)),
        ("9:05", None),
        ("24:00", None),
        ("09:60", None),
        ("09:05:00", None),
        ("", None),
        ("x" * 17, None),
        (5, None),
        (None, None),
        (["09:05"], None),
    ],
)
def test_wall_clock_parsing(value: Any, expected: Any) -> None:
    assert qoder_schedules._wall_clock(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([3, 1, 1], [1, 3]),
        ([0], [0]),
        ([6], [6]),
        ([6, 0, 2, 4], [0, 2, 4, 6]),
        ([1, 2.0], [1, 2]),
        ([7], None),
        ([-1], None),
        ([], None),
        ([0] * 8, None),
        ("mon", None),
        (None, None),
        ([1, "a"], None),
        ([1.5], None),
        ([True], None),
    ],
)
def test_weekday_normalization(value: Any, expected: Any) -> None:
    assert qoder_schedules._weekdays(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        (0, 0),
        (-3, -3),
        (5.0, 5),
        (5.5, None),
        (True, None),
        (False, None),
        ("5", None),
        (None, None),
        ([1], None),
        ({"a": 1}, None),
    ],
)
def test_integer_coercion_rejects_bools_and_fractions(
    value: Any,
    expected: Any,
) -> None:
    assert qoder_schedules._integer(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "Not/AZone", "Asia/Nowhere", "../etc/passwd", " " * 3],
)
def test_timezone_loading_rejects_unknown_zones(value: str) -> None:
    assert qoder_schedules._load_timezone(value) is None


def test_timezone_loading_accepts_known_zones() -> None:
    zone = qoder_schedules._load_timezone("Asia/Shanghai")

    assert isinstance(zone, ZoneInfo)
    assert zone.key == "Asia/Shanghai"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-08-20T00:00:00Z", "2026-08-20T00:00:00+00:00"),
        ("2026-08-20T00:00:00+08:00", "2026-08-20T00:00:00+08:00"),
        ("  2026-08-20T00:00:00Z  ", "2026-08-20T00:00:00+00:00"),
        ("2026-08-20T00:00:00", None),  # naive
        ("nope", None),
        ("", None),
        (None, None),
        (5, None),
        ("x" * 300, None),
    ],
)
def test_aware_datetime_parsing(value: Any, expected: str | None) -> None:
    parsed = qoder_schedules._parse_aware_datetime(value)

    if expected is None:
        assert parsed is None
    else:
        assert parsed is not None
        assert parsed.isoformat() == expected


@pytest.mark.parametrize(
    ("cycle", "step", "offset", "expected"),
    [
        (60, 1, 0, "*"),
        (24, 1, 0, "*"),
        (60, 15, 0, "*/15"),
        (24, 2, 0, "*/2"),
        (60, 15, 7, "7,22,37,52"),
        (24, 2, 1, "1,3,5,7,9,11,13,15,17,19,21,23"),
        (24, 24, 5, "5"),
        (60, 60, 3, "3"),
        (24, 8, 3, "3,11,19"),
    ],
)
def test_phase_field_renders_exact_patterns(
    cycle: int,
    step: int,
    offset: int,
    expected: str,
) -> None:
    assert qoder_schedules._phase_field(cycle, step, offset) == expected


def test_unique_keeps_first_occurrence_order() -> None:
    assert qoder_schedules._unique(["a", "b", "a", "c", "b"]) == [
        "a",
        "b",
        "c",
    ]


def test_interval_cron_refuses_sub_minute_start() -> None:
    start = datetime(2026, 8, 20, 0, 0, 30, tzinfo=timezone.utc)

    result = qoder_schedules._interval_cron(
        15,
        start_at=start,
        zone=ZoneInfo("UTC"),
    )

    assert result == ""


def test_interval_cron_renders_in_the_target_zone() -> None:
    start = datetime(2026, 8, 20, 5, 30, tzinfo=timezone.utc)

    utc = qoder_schedules._interval_cron(
        1440,
        start_at=start,
        zone=ZoneInfo("UTC"),
    )
    shanghai = qoder_schedules._interval_cron(
        1440,
        start_at=start,
        zone=ZoneInfo("Asia/Shanghai"),
    )

    assert utc == "30 5 * * *"
    assert shanghai == "30 13 * * *"


# --------------------------------------------------------------------------
# workspace classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cwd", "authority", "expected"),
    [
        ("", "", ("not_set", None, "")),
        ("", "ssh-remote+host", ("not_set", None, "")),
        (
            "/tmp",
            "ssh-remote+host",
            ("remote_unverified", None, "remote_workspace_unverified"),
        ),
        (
            "relative/dir",
            "",
            ("not_absolute", False, "workspace_path_not_absolute"),
        ),
        ("/no/such/dir/r14", "", ("missing", False, "workspace_path_missing")),
    ],
    ids=["empty", "empty-remote", "remote", "relative", "missing"],
)
def test_workspace_status_classification(
    cwd: str,
    authority: str,
    expected: tuple[str, bool | None, str],
) -> None:
    result = qoder_schedules._workspace_status(
        cwd,
        target_remote_authority=authority,
    )

    assert result == expected


def test_workspace_status_reports_existing_directory(tmp_path: Path) -> None:
    result = qoder_schedules._workspace_status(
        str(tmp_path),
        target_remote_authority="",
    )

    assert result == ("exists", True, "")


def test_workspace_status_swallows_stat_errors(tmp_path: Path) -> None:
    with patch.object(Path, "exists", side_effect=OSError(13, "denied")):
        result = qoder_schedules._workspace_status(
            str(tmp_path),
            target_remote_authority="",
        )

    assert result == ("missing", False, "workspace_path_missing")


def test_remote_workspace_never_trusts_a_local_exists_check(
    tmp_path: Path,
) -> None:
    task = _task(workspacePath=str(tmp_path), targetRemoteAuthority="ssh+h")

    mapped = _mapped(task)

    assert mapped.cwd == str(tmp_path)
    assert mapped.metadata["workspace_status"] == "remote_unverified"
    assert mapped.metadata["workspace_exists"] is None
    assert "remote_workspace_unverified" in mapped.metadata["review_reasons"]


def test_blocked_cwd_is_audited_and_never_kept() -> None:
    task = _task(workspacePath="/tmp/bad\x00path")

    mapped = _mapped(task)

    assert mapped.cwd == ""
    assert mapped.metadata["workspace_status"] == "blocked_unsafe"
    assert mapped.metadata["workspace_exists"] is None
    assert mapped.metadata["review_reasons"] == [
        "activation_requires_user_review",
        "source_cwd_blocked",
    ]
    assert mapped.metadata["cwd_audit"]["disposition"] == "omitted"
    assert "\x00" not in json.dumps(mapped.metadata)


def test_overlong_cwd_is_audited_and_never_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(qoder_schedules, "_MAX_CWD_CHARS", 40)
    task = _task(workspacePath="/" + "a" * 60)

    mapped = _mapped(task)

    assert mapped.cwd == ""
    assert mapped.metadata["workspace_status"] == "blocked_unsafe"
    assert mapped.metadata["cwd_audit"]["original_chars"] == 61


def test_missing_workspace_directory_is_reported() -> None:
    task = _task(workspacePath="/no/such/dir/r14")

    mapped = _mapped(task)

    assert mapped.metadata["workspace_status"] == "missing"
    assert mapped.metadata["workspace_exists"] is False
    assert "workspace_path_missing" in mapped.metadata["review_reasons"]


def test_relative_workspace_directory_is_reported() -> None:
    task = _task(workspacePath="relative/dir")

    mapped = _mapped(task)

    assert mapped.metadata["workspace_status"] == "not_absolute"
    assert mapped.metadata["workspace_exists"] is False
    assert "workspace_path_not_absolute" in mapped.metadata["review_reasons"]


def test_existing_workspace_directory_needs_no_extra_review(
    tmp_path: Path,
) -> None:
    task = _task(workspacePath=str(tmp_path))

    mapped = _mapped(task)

    assert mapped.metadata["workspace_status"] == "exists"
    assert mapped.metadata["workspace_exists"] is True
    assert mapped.metadata["review_reasons"] == [
        "activation_requires_user_review",
    ]
