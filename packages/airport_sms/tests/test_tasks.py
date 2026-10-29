"""计划与调度器行为测试。"""

from __future__ import annotations

from time import perf_counter

from airport_sms.domain import CaseId, Role
from airport_sms.tasks import (
    JobName,
    Scheduler,
    StepStatus,
    new_plan,
    system_principal,
)


def test_plan_three_pending() -> None:
    plan = new_plan("c1", ["a", "b", "c"])
    assert len(plan.steps) == 3
    assert all(s.status is StepStatus.PENDING for s in plan.steps)


def test_run_step_done() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    plan = new_plan("c1", ["a", "b", "c"])
    plan = sched.run_step(plan, "s1")
    assert plan.steps[0].status is StepStatus.DONE
    assert plan.steps[1].status is StepStatus.PENDING


def test_fail_step_stores_error() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    plan = new_plan("c1", ["a"])
    plan = sched.fail_step(plan, "s1", "boom")
    assert plan.steps[0].status is StepStatus.FAILED
    assert plan.steps[0].error == "boom"


def test_overdue_job_event() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    event = sched.fire_overdue(CaseId("c1"), idem_key="od-1")
    assert event is not None
    assert event.name is JobName.OVERDUE_CORRECTIVE_ACTION
    assert event.source == "scheduler"
    assert event.case_id == "c1"


def test_cancel_pending() -> None:
    plan = new_plan("c1", ["a", "b"])
    sched = Scheduler(org_id="o", site_id="s")
    plan = sched.run_step(plan, "s1")
    plan = plan.cancel_pending()
    assert plan.steps[0].status is StepStatus.DONE
    assert plan.steps[1].status is StepStatus.CANCELLED


def test_system_principal() -> None:
    p = system_principal("org", "site")
    assert p.role is Role.SYSTEM
    sched = Scheduler(org_id="org", site_id="site")
    event = sched.fire_heartbeat()
    assert event.principal_role is Role.SYSTEM


def test_overdue_idempotent() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    a = sched.fire_overdue(CaseId("c1"), idem_key="k")
    b = sched.fire_overdue(CaseId("c1"), idem_key="k")
    assert a is not None
    assert b is None
    assert len(sched.events) == 1


def test_digest_inbox() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    before = len(sched.inbox.items)
    sched.fire_digest()
    assert len(sched.inbox.items) == before + 1


def test_lifecycle_start_stop() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    sched.start()
    assert sched.running is True
    sched.tick()
    sched.stop()
    assert sched.running is False


def test_scheduler_source_tag() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    event = sched.fire_overdue(CaseId("c1"), idem_key="x")
    assert event is not None
    assert event.source == "scheduler"


def test_100_ticks_under_500ms() -> None:
    sched = Scheduler(org_id="o", site_id="s")
    sched.start()
    start = perf_counter()
    for _ in range(100):
        sched.tick()
    ms = (perf_counter() - start) * 1000
    sched.stop()
    assert ms < 500, f"{ms:.1f}ms"
