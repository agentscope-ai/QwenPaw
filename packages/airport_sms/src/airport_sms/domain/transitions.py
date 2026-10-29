"""案件状态迁移表与纯函数。"""

from __future__ import annotations

from dataclasses import replace

from airport_sms.domain.case import AuditEntry, Case, CaseState
from airport_sms.domain.roles import Role

OPEN_STATES: frozenset[CaseState] = frozenset(
    {
        CaseState.SUBMITTED,
        CaseState.TRIAGED,
        CaseState.ASSESSING,
        CaseState.MITIGATING,
        CaseState.VERIFYING,
    }
)

ALARP_TARGETS: frozenset[CaseState] = frozenset(
    {CaseState.VERIFYING, CaseState.CLOSED}
)

TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.DRAFT: frozenset({CaseState.SUBMITTED}),
    CaseState.SUBMITTED: frozenset(
        {CaseState.TRIAGED, CaseState.REJECTED, CaseState.ESCALATED}
    ),
    CaseState.TRIAGED: frozenset(
        {CaseState.ASSESSING, CaseState.REJECTED, CaseState.ESCALATED}
    ),
    CaseState.ASSESSING: frozenset(
        {
            CaseState.MITIGATING,
            CaseState.VERIFYING,
            CaseState.CLOSED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.MITIGATING: frozenset({CaseState.VERIFYING, CaseState.ESCALATED}),
    CaseState.VERIFYING: frozenset(
        {CaseState.CLOSED, CaseState.MITIGATING, CaseState.ESCALATED}
    ),
    CaseState.CLOSED: frozenset({CaseState.ASSESSING}),
    CaseState.REJECTED: frozenset(),
    CaseState.ESCALATED: frozenset(),
}


class IllegalTransitionError(Exception):
    """非法迁移。属性 from_state / to_state 标明两端。"""

    def __init__(self, from_state: CaseState, to_state: CaseState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"illegal transition from {from_state.value} to {to_state.value}"
        )


def transition(
    case: Case,
    to_state: CaseState,
    actor: Role,
    reason: str,
    *,
    alarp: bool = False,
    new_evidence: bool = False,
) -> Case:
    """返回迁移后的新案件，并追加一条审计。原案件不变。"""
    if not _is_legal(case, to_state, alarp=alarp, new_evidence=new_evidence):
        raise IllegalTransitionError(case.state, to_state)
    resume_from = case.resume_from
    if to_state is CaseState.ESCALATED:
        resume_from = case.state
    elif case.state is CaseState.ESCALATED:
        resume_from = None
    entry = AuditEntry(
        from_state=case.state,
        to_state=to_state,
        actor=actor,
        reason=reason,
    )
    return replace(
        case,
        state=to_state,
        resume_from=resume_from,
        audit=(*case.audit, entry),
        version=case.version + 1,
    )


def _is_legal(
    case: Case,
    to_state: CaseState,
    *,
    alarp: bool,
    new_evidence: bool,
) -> bool:
    """判断当前案件迁到目标态是否合法。"""
    from_state = case.state
    if from_state is CaseState.ESCALATED:
        return case.resume_from is not None and to_state is case.resume_from
    if to_state not in TRANSITIONS.get(from_state, frozenset()):
        return False
    if to_state is CaseState.ESCALATED:
        return from_state in OPEN_STATES
    if from_state is CaseState.ASSESSING and to_state in ALARP_TARGETS:
        return alarp
    if from_state is CaseState.CLOSED and to_state is CaseState.ASSESSING:
        return new_evidence
    return True


__all__ = [
    "ALARP_TARGETS",
    "IllegalTransitionError",
    "OPEN_STATES",
    "TRANSITIONS",
    "transition",
]
