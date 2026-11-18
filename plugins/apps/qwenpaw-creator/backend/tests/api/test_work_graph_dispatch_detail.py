# -*- coding: utf-8 -*-
# Empty-dict assertions stay explicit for readability, same as the other
# API test modules in this package.
# pylint: disable=use-implicit-booleaness-not-comparison
"""The manual dispatch gate must tell a real render apart from a stranded one.

Field case 2026-11-06: a node whose task was admitted but never claimed reads
as "running", and the gate answered it with a silent dispatched=false, so the
user saw a queue label for 69 hours while nothing was queued at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api.work_graph_routes import _task_admission_detail
from domain.enums import TaskStatus
from services.file_agent_runtime.work_scheduler import (
    _abandoned_queued_targets,
)

pytestmark = pytest.mark.unit

TARGET = "element:elem:s8d"


def _task(
    *,
    status: TaskStatus,
    updated_at: datetime,
    last_attempt_seq: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_id="task-71c0c25dc4725316a3d843183c18612e",
        kind="r2v_generation",
        status=status,
        updated_at=updated_at,
        last_attempt_seq=last_attempt_seq,
        metadata={"targetRef": TARGET},
        input_refs=[TARGET],
        error=None,
        result=None,
    )


def test_admitted_but_unclaimed_is_recognised() -> None:
    now = datetime.now(UTC)
    stranded = _task(
        status=TaskStatus.QUEUED,
        updated_at=now - timedelta(minutes=20),
        last_attempt_seq=0,
    )
    assert _abandoned_queued_targets([stranded], now=now) == {TARGET}


def test_claimed_or_fresh_tasks_are_not_rescued() -> None:
    now = datetime.now(UTC)
    running = _task(
        status=TaskStatus.RUNNING,
        updated_at=now,
        last_attempt_seq=3,
    )
    fresh = _task(
        status=TaskStatus.QUEUED,
        updated_at=now - timedelta(minutes=2),
        last_attempt_seq=0,
    )
    assert _abandoned_queued_targets([running, fresh], now=now) == set()


def test_admission_detail_reports_the_task_behind_a_running_node() -> None:
    stranded = _task(
        status=TaskStatus.QUEUED,
        updated_at=datetime.now(UTC) - timedelta(minutes=20),
        last_attempt_seq=0,
    )
    detail = _task_admission_detail([stranded], TARGET)
    assert detail["taskId"] == stranded.task_id
    assert detail["taskStatus"] == "QUEUED"
    assert detail["lastAttemptSeq"] == 0
    assert detail["ageSeconds"] is not None
    assert detail["ageSeconds"] >= 1200


def test_admission_detail_stays_quiet_without_a_target() -> None:
    assert _task_admission_detail([], None) == {}
    assert _task_admission_detail([], "element:elem:none") == {}
