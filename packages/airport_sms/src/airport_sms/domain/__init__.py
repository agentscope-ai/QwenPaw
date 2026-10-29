"""SMS 案件领域：角色、案件、状态机。"""

from airport_sms.domain.case import (
    AuditEntry,
    Case,
    CaseId,
    CaseState,
    ClosedCaseError,
    InvalidScoreError,
    RiskLevel,
    change_risk,
    compute_risk_level,
    new_draft,
)
from airport_sms.domain.roles import Role
from airport_sms.domain.transitions import (
    ALARP_TARGETS,
    OPEN_STATES,
    TRANSITIONS,
    IllegalTransitionError,
    transition,
)

__all__ = [
    "ALARP_TARGETS",
    "AuditEntry",
    "Case",
    "CaseId",
    "CaseState",
    "ClosedCaseError",
    "IllegalTransitionError",
    "InvalidScoreError",
    "OPEN_STATES",
    "RiskLevel",
    "Role",
    "TRANSITIONS",
    "change_risk",
    "compute_risk_level",
    "new_draft",
    "transition",
]
