# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.app.crons.models import (
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    ScheduleSpec,
    _crontab_dow_to_name,
)
from tests.unit.app.conftest import make_cron_job_spec


# ---------------------------------------------------------------------------
# _crontab_dow_to_name — crontab numeric DOW → abbreviation
# ---------------------------------------------------------------------------


def test_dow_wildcard_passthrough():
    assert _crontab_dow_to_name("*") == "*"


def test_dow_single_numeric_to_name():
    assert _crontab_dow_to_name("0") == "sun"
    assert _crontab_dow_to_name("1") == "mon"
    assert _crontab_dow_to_name("7") == "sun"  # crontab 7 = Sunday


def test_dow_named_passthrough():
    # Already-named values must not be mutated.
    assert _crontab_dow_to_name("mon") == "mon"
    assert _crontab_dow_to_name("fri") == "fri"


def test_dow_comma_list():
    assert _crontab_dow_to_name("1,3,5") == "mon,wed,fri"


def test_dow_range():
    # Expand to an explicit list so APS never sees sun-anchored name ranges.
    assert _crontab_dow_to_name("1-5") == "mon,tue,wed,thu,fri"


def test_dow_step_star_uses_crontab_sunday_origin():
    # Crontab */2 on DOW is Sun,Tue,Thu,Sat — not APS ISO Mon,Wed,Fri,Sun.
    assert _crontab_dow_to_name("*/2") == "sun,tue,thu,sat"


def test_dow_full_numeric_range_becomes_wildcard():
    assert _crontab_dow_to_name("0-6") == "*"
    assert _crontab_dow_to_name("0-6/2") == "sun,tue,thu,sat"


def test_dow_sunday_anchored_range_is_aps_safe():
    # Former naive convert emitted "sun-fri", which APScheduler rejects.
    assert _crontab_dow_to_name("0-5") == "sun,mon,tue,wed,thu,fri"


def test_dow_range_with_step():
    assert _crontab_dow_to_name("1-5/2") == "mon,wed,fri"


# ---------------------------------------------------------------------------
# ScheduleSpec — cron type
# ---------------------------------------------------------------------------


def test_schedule_cron_normalizes_5_fields():
    spec = ScheduleSpec(type="cron", cron="0 9 * * 1")
    assert spec.cron == "0 9 * * mon"


def test_schedule_cron_normalizes_4_fields():
    spec = ScheduleSpec(type="cron", cron="9 * * 1")
    assert spec.cron == "0 9 * * mon"


def test_schedule_cron_named_dow_unchanged():
    spec = ScheduleSpec(type="cron", cron="0 9 * * mon")
    assert spec.cron == "0 9 * * mon"


def test_schedule_cron_rejects_empty():
    with pytest.raises(ValidationError, match="cron is empty"):
        ScheduleSpec(type="cron", cron="")


def test_schedule_cron_rejects_6_fields():
    with pytest.raises(ValidationError):
        ScheduleSpec(type="cron", cron="0 0 9 * * mon")


def test_schedule_once_requires_run_at():
    with pytest.raises(ValidationError, match="run_at is missing"):
        ScheduleSpec(type="once")


# ---------------------------------------------------------------------------
# CronJobSpec validation
# ---------------------------------------------------------------------------


def test_cron_job_spec_agent_syncs_request_with_target():
    spec = make_cron_job_spec(user_id="alice", session_id="console:alice")
    assert spec.request is not None
    assert spec.request.user_id == "alice"
    assert spec.request.session_id == "console:alice"


def test_cron_job_spec_text_rejects_empty_text():
    with pytest.raises(ValidationError, match="text is empty"):
        CronJobSpec(
            name="Bad",
            schedule=ScheduleSpec(type="cron", cron="0 9 * * mon"),
            task_type="text",
            text="",
            dispatch=DispatchSpec(
                target=DispatchTarget(user_id="u1", session_id="console:u1"),
            ),
        )


def test_dispatch_silent_defaults_to_false():
    dispatch = DispatchSpec(
        target=DispatchTarget(user_id="u1", session_id="console:u1"),
    )

    assert dispatch.silent is False


def test_cron_job_spec_agent_accepts_silent_delivery():
    payload = make_cron_job_spec().model_dump(mode="json")
    payload["dispatch"]["silent"] = True

    spec = CronJobSpec.model_validate(payload)

    assert spec.dispatch.silent is True


def test_cron_job_spec_text_rejects_silent_delivery():
    with pytest.raises(
        ValidationError,
        match="silent delivery is only supported for agent tasks",
    ):
        CronJobSpec(
            name="Silent text",
            schedule=ScheduleSpec(type="cron", cron="0 9 * * mon"),
            task_type="text",
            text="Hello",
            dispatch=DispatchSpec(
                target=DispatchTarget(
                    user_id="u1",
                    session_id="console:u1",
                ),
                silent=True,
            ),
        )


def test_schedule_cron_star_step_dow_matches_crontab_weekdays():
    """``*/2`` must keep crontab Sunday-origin days after normalization."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from apscheduler.triggers.cron import CronTrigger

    spec = ScheduleSpec(type="cron", cron="0 9 * * */2")
    assert spec.cron == "0 9 * * sun,tue,thu,sat"
    minute, hour, day, month, dow = spec.cron.split()
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
        timezone="UTC",
    )
    tz = ZoneInfo("UTC")
    start = datetime(2026, 9, 13, 0, 0, tzinfo=tz)  # Sunday
    end = start + timedelta(days=8)
    seen: set[str] = set()
    cursor = start
    while cursor < end:
        nxt = trigger.get_next_fire_time(None, cursor)
        if nxt is None or nxt >= end:
            break
        seen.add(nxt.strftime("%a"))
        cursor = nxt + timedelta(seconds=1)
    assert seen == {"Sun", "Tue", "Thu", "Sat"}


def test_schedule_cron_sunday_range_builds_aps_trigger():
    """Numeric ranges that start on Sunday must remain schedulable."""
    from apscheduler.triggers.cron import CronTrigger

    spec = ScheduleSpec(type="cron", cron="0 9 * * 0-5")
    assert spec.cron == "0 9 * * sun,mon,tue,wed,thu,fri"
    minute, hour, day, month, dow = spec.cron.split()
    # Must not raise ValueError(min > max) from sun-fri.
    CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
        timezone="UTC",
    )
