"""SMS 案件实体与风险矩阵。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType

from airport_sms.domain.roles import Role

CaseId = NewType("CaseId", str)


class CaseState(str, Enum):
    """案件生命周期状态。"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    TRIAGED = "triaged"
    ASSESSING = "assessing"
    MITIGATING = "mitigating"
    VERIFYING = "verifying"
    CLOSED = "closed"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class RiskLevel(str, Enum):
    """严重度 × 可能性矩阵给出的风险带。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class ClosedCaseError(Exception):
    """案件已关闭时禁止改风险。"""


class InvalidScoreError(Exception):
    """严重度或可能性不在 1 到 5。"""


_RISK_MATRIX: tuple[tuple[RiskLevel, ...], ...] = (
    (
        RiskLevel.LOW,
        RiskLevel.LOW,
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.MEDIUM,
    ),
    (
        RiskLevel.LOW,
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
    ),
    (
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.HIGH,
    ),
    (
        RiskLevel.MEDIUM,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.HIGH,
        RiskLevel.EXTREME,
    ),
    (
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.HIGH,
        RiskLevel.EXTREME,
        RiskLevel.EXTREME,
    ),
)


@dataclass(frozen=True)
class AuditEntry:
    """一次状态迁移的审计记录。"""

    from_state: CaseState
    to_state: CaseState
    actor: Role
    reason: str


@dataclass(frozen=True)
class Case:
    """不可变案件。变更必须 replace 出新实例。"""

    id: CaseId
    state: CaseState
    hazard: str
    location: str
    severity: int
    likelihood: int
    risk_level: RiskLevel
    owner_role: Role
    evidence_refs: tuple[str, ...]
    cited_clauses: tuple[str, ...]
    audit: tuple[AuditEntry, ...]
    resume_from: CaseState | None = None
    version: int = 1


def compute_risk_level(severity: int, likelihood: int) -> RiskLevel:
    """按 5×5 矩阵返回风险带。"""
    _require_score(severity, likelihood)
    return _RISK_MATRIX[severity - 1][likelihood - 1]


def new_draft(
    *,
    case_id: CaseId,
    hazard: str,
    location: str,
    severity: int = 1,
    likelihood: int = 1,
    owner_role: Role = Role.REPORTER,
    evidence_refs: tuple[str, ...] = (),
    cited_clauses: tuple[str, ...] = (),
) -> Case:
    """创建草稿案件。"""
    return Case(
        id=case_id,
        state=CaseState.DRAFT,
        hazard=hazard,
        location=location,
        severity=severity,
        likelihood=likelihood,
        risk_level=compute_risk_level(severity, likelihood),
        owner_role=owner_role,
        evidence_refs=evidence_refs,
        cited_clauses=cited_clauses,
        audit=(),
        resume_from=None,
        version=1,
    )


def change_risk(case: Case, severity: int, likelihood: int) -> Case:
    """更新严重度与可能性。关闭态必须先重开评估。"""
    if case.state is CaseState.CLOSED:
        raise ClosedCaseError("change_risk is forbidden while state is closed")
    return replace(
        case,
        severity=severity,
        likelihood=likelihood,
        risk_level=compute_risk_level(severity, likelihood),
        version=case.version + 1,
    )


def _require_score(severity: int, likelihood: int) -> None:
    """校验 1 到 5 的整数评分。"""
    if not (1 <= severity <= 5 and 1 <= likelihood <= 5):
        raise InvalidScoreError(
            f"severity and likelihood must be 1-5, got {severity}x{likelihood}"
        )


__all__ = [
    "AuditEntry",
    "Case",
    "CaseId",
    "CaseState",
    "ClosedCaseError",
    "InvalidScoreError",
    "RiskLevel",
    "change_risk",
    "compute_risk_level",
    "new_draft",
]
