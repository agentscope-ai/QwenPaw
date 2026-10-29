"""轻量调度器：可注入时钟，作业标记 source=scheduler。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from airport_sms.domain.case import CaseId
from airport_sms.domain.roles import Role
from airport_sms.tasks.jobs import Inbox, JobEvent, JobName, system_principal
from airport_sms.tasks.plan import Plan, StepStatus

Now = Callable[[], datetime]


def utcnow() -> datetime:
    """UTC 当前时间。"""
    return datetime.now(timezone.utc)


@dataclass
class Scheduler:
    """内存调度器。生产可换 APScheduler，接口保持一致。"""

    org_id: str
    site_id: str
    now: Now = utcnow
    inbox: Inbox = field(default_factory=Inbox)
    events: list[JobEvent] = field(default_factory=list)
    _overdue_keys: set[str] = field(default_factory=set)
    _running: bool = False
    ticks: int = 0

    def start(self) -> None:
        """启动调度循环标记。"""
        self._running = True

    def stop(self) -> None:
        """停止并允许 join。"""
        self._running = False

    @property
    def running(self) -> bool:
        """是否在跑。"""
        return self._running

    def tick(self) -> None:
        """空 tick，供性能探测。"""
        if not self._running:
            return
        self.ticks += 1

    def run_step(self, plan: Plan, step_id: str) -> Plan:
        """把一步标为 done。"""
        return plan.with_status(step_id, StepStatus.DONE)

    def fail_step(self, plan: Plan, step_id: str, error: str) -> Plan:
        """把一步标为 failed 并记录错误。"""
        return plan.with_status(step_id, StepStatus.FAILED, error=error)

    def fire_overdue(self, case_id: CaseId, *, idem_key: str) -> JobEvent | None:
        """逾期整改作业。同 idem_key 只产生一次事件。"""
        if idem_key in self._overdue_keys:
            return None
        self._overdue_keys.add(idem_key)
        principal = system_principal(self.org_id, self.site_id)
        event = JobEvent(
            name=JobName.OVERDUE_CORRECTIVE_ACTION,
            case_id=str(case_id),
            source="scheduler",
            principal_role=principal.role,
            at=self.now(),
            detail="overdue",
        )
        self.events.append(event)
        return event

    def fire_digest(self) -> JobEvent:
        """每日风险摘要，写入收件箱。"""
        principal = system_principal(self.org_id, self.site_id)
        self.inbox.add("daily risk digest")
        event = JobEvent(
            name=JobName.DAILY_RISK_DIGEST,
            case_id=None,
            source="scheduler",
            principal_role=principal.role,
            at=self.now(),
            detail="digest",
        )
        self.events.append(event)
        return event

    def fire_heartbeat(self) -> JobEvent:
        """心跳收件箱。"""
        principal = system_principal(self.org_id, self.site_id)
        assert principal.role is Role.SYSTEM
        self.inbox.add("heartbeat")
        event = JobEvent(
            name=JobName.HEARTBEAT_INBOX,
            case_id=None,
            source="scheduler",
            principal_role=Role.SYSTEM,
            at=self.now(),
        )
        self.events.append(event)
        return event


__all__ = ["Scheduler", "utcnow"]
