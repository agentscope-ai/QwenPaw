"""案件计划：有序步骤与状态。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class StepStatus(str, Enum):
    """计划步骤状态。"""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PlanStep:
    """单个计划步骤。"""

    id: str
    title: str
    status: StepStatus = StepStatus.PENDING
    error: str | None = None


@dataclass(frozen=True)
class Plan:
    """挂在案件上的有序计划，不是模型隐状态。"""

    case_id: str
    steps: tuple[PlanStep, ...]

    def with_status(
        self, step_id: str, status: StepStatus, *, error: str | None = None
    ) -> Plan:
        """返回更新了指定步骤状态的新计划。"""
        updated: list[PlanStep] = []
        found = False
        for step in self.steps:
            if step.id == step_id:
                found = True
                updated.append(
                    replace(step, status=status, error=error)
                )
            else:
                updated.append(step)
        if not found:
            raise KeyError(step_id)
        return Plan(case_id=self.case_id, steps=tuple(updated))

    def cancel_pending(self) -> Plan:
        """把所有 pending 标为 cancelled。"""
        steps = tuple(
            replace(s, status=StepStatus.CANCELLED)
            if s.status is StepStatus.PENDING
            else s
            for s in self.steps
        )
        return Plan(case_id=self.case_id, steps=steps)


def new_plan(case_id: str, titles: list[str]) -> Plan:
    """创建全 pending 计划。"""
    steps = tuple(
        PlanStep(id=f"s{i}", title=title)
        for i, title in enumerate(titles, start=1)
    )
    return Plan(case_id=case_id, steps=steps)


__all__ = ["Plan", "PlanStep", "StepStatus", "new_plan"]
