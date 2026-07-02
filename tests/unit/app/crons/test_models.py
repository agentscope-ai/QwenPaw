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
    assert _crontab_dow_to_name("1-5") == "mon-fri"


def test_dow_step():
    # */2 on DOW field: wildcard base with step
    assert _crontab_dow_to_name("*/2") == "*/2"


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
