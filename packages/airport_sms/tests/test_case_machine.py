"""案件状态机行为测试。"""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError, replace

import pytest

from airport_sms.domain import (
    CaseId,
    CaseState,
    ClosedCaseError,
    IllegalTransitionError,
    InvalidScoreError,
    RiskLevel,
    Role,
    TRANSITIONS,
    change_risk,
    compute_risk_level,
    new_draft,
    transition,
)


def _draft(**kwargs: object):
    """构造默认草稿。"""
    params = {
        "case_id": CaseId("C-1"),
        "hazard": "FOD on taxiway",
        "location": "TWY A",
    }
    params.update(kwargs)
    return new_draft(**params)


def _walk(case, steps):
    """按 (目标态, 原因, 可选标志) 连续迁移。"""
    current = case
    for step in steps:
        to_state, reason, flags = step[0], step[1], step[2] if len(step) > 2 else {}
        current = transition(
            current, to_state, Role.SAFETY_OFFICE, reason, **flags
        )
    return current


LEGAL_EDGES = [
    (CaseState.DRAFT, CaseState.SUBMITTED, {}),
    (CaseState.SUBMITTED, CaseState.TRIAGED, {}),
    (CaseState.SUBMITTED, CaseState.REJECTED, {}),
    (CaseState.SUBMITTED, CaseState.ESCALATED, {}),
    (CaseState.TRIAGED, CaseState.ASSESSING, {}),
    (CaseState.TRIAGED, CaseState.REJECTED, {}),
    (CaseState.TRIAGED, CaseState.ESCALATED, {}),
    (CaseState.ASSESSING, CaseState.MITIGATING, {}),
    (CaseState.ASSESSING, CaseState.VERIFYING, {"alarp": True}),
    (CaseState.ASSESSING, CaseState.CLOSED, {"alarp": True}),
    (CaseState.ASSESSING, CaseState.ESCALATED, {}),
    (CaseState.MITIGATING, CaseState.VERIFYING, {}),
    (CaseState.MITIGATING, CaseState.ESCALATED, {}),
    (CaseState.VERIFYING, CaseState.CLOSED, {}),
    (CaseState.VERIFYING, CaseState.MITIGATING, {}),
    (CaseState.VERIFYING, CaseState.ESCALATED, {}),
    (CaseState.CLOSED, CaseState.ASSESSING, {"new_evidence": True}),
]


def _case_in(state: CaseState):
    """走到指定状态（不含 escalated 终点）。"""
    case = _draft()
    if state is CaseState.DRAFT:
        return case
    path = {
        CaseState.SUBMITTED: [(CaseState.SUBMITTED, "submit")],
        CaseState.TRIAGED: [
            (CaseState.SUBMITTED, "submit"),
            (CaseState.TRIAGED, "triage"),
        ],
        CaseState.REJECTED: [
            (CaseState.SUBMITTED, "submit"),
            (CaseState.REJECTED, "reject"),
        ],
        CaseState.ASSESSING: [
            (CaseState.SUBMITTED, "submit"),
            (CaseState.TRIAGED, "triage"),
            (CaseState.ASSESSING, "assess"),
        ],
        CaseState.MITIGATING: [
            (CaseState.SUBMITTED, "submit"),
            (CaseState.TRIAGED, "triage"),
            (CaseState.ASSESSING, "assess"),
            (CaseState.MITIGATING, "capa"),
        ],
        CaseState.VERIFYING: [
            (CaseState.SUBMITTED, "submit"),
            (CaseState.TRIAGED, "triage"),
            (CaseState.ASSESSING, "assess"),
            (CaseState.MITIGATING, "capa"),
            (CaseState.VERIFYING, "verify"),
        ],
        CaseState.CLOSED: [
            (CaseState.SUBMITTED, "submit"),
            (CaseState.TRIAGED, "triage"),
            (CaseState.ASSESSING, "assess"),
            (CaseState.MITIGATING, "capa"),
            (CaseState.VERIFYING, "verify"),
            (CaseState.CLOSED, "close"),
        ],
    }[state]
    return _walk(case, path)


@pytest.mark.parametrize("from_state,to_state,flags", LEGAL_EDGES)
def test_legal_edge_returns_new_case_with_one_audit(
    from_state: CaseState, to_state: CaseState, flags: dict
) -> None:
    """每条合法边产生新案件且审计加一条。"""
    case = _case_in(from_state)
    before = len(case.audit)
    nxt = transition(case, to_state, Role.DEPT_OWNER, "ok", **flags)
    assert nxt is not case
    assert nxt.state is to_state
    assert len(nxt.audit) == before + 1
    assert nxt.audit[-1].from_state is from_state
    assert nxt.audit[-1].to_state is to_state
    assert nxt.audit[-1].actor is Role.DEPT_OWNER
    assert case.state is from_state
    assert len(case.audit) == before
    assert nxt.version == case.version + 1


def test_escalate_stores_resume_from_and_resume_returns() -> None:
    """升级记下原状态，恢复走回 resume_from。"""
    assessing = _case_in(CaseState.ASSESSING)
    escalated = transition(
        assessing, CaseState.ESCALATED, Role.DEPT_OWNER, "need judge"
    )
    assert escalated.state is CaseState.ESCALATED
    assert escalated.resume_from is CaseState.ASSESSING
    resumed = transition(
        escalated, CaseState.ASSESSING, Role.SAFETY_OFFICE, "resume"
    )
    assert resumed.state is CaseState.ASSESSING
    assert resumed.resume_from is None


def test_resume_to_wrong_state_is_illegal() -> None:
    """升级后只能回到 resume_from。"""
    escalated = transition(
        _case_in(CaseState.ASSESSING),
        CaseState.ESCALATED,
        Role.SYSTEM,
        "esc",
    )
    with pytest.raises(IllegalTransitionError) as exc:
        transition(escalated, CaseState.CLOSED, Role.SYSTEM, "nope")
    assert exc.value.from_state is CaseState.ESCALATED
    assert exc.value.to_state is CaseState.CLOSED


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (CaseState.CLOSED, CaseState.SUBMITTED),
        (CaseState.DRAFT, CaseState.TRIAGED),
        (CaseState.DRAFT, CaseState.ESCALATED),
        (CaseState.REJECTED, CaseState.ASSESSING),
        (CaseState.CLOSED, CaseState.ESCALATED),
        (CaseState.MITIGATING, CaseState.CLOSED),
    ],
)
def test_illegal_edges_raise_and_name_both_states(
    from_state: CaseState, to_state: CaseState
) -> None:
    """非法边抛错且错误点名 from 与 to，原案件不变。"""
    case = _case_in(from_state)
    with pytest.raises(IllegalTransitionError) as exc:
        transition(case, to_state, Role.REPORTER, "bad")
    assert exc.value.from_state is from_state
    assert exc.value.to_state is to_state
    assert from_state.value in str(exc.value)
    assert to_state.value in str(exc.value)
    assert case.state is from_state


def test_assessing_to_closed_without_alarp_is_illegal() -> None:
    """评估直关必须 ALARP。"""
    case = _case_in(CaseState.ASSESSING)
    with pytest.raises(IllegalTransitionError) as exc:
        transition(case, CaseState.CLOSED, Role.SAFETY_OFFICE, "skip capa")
    assert exc.value.from_state is CaseState.ASSESSING
    assert exc.value.to_state is CaseState.CLOSED


def test_assessing_to_verifying_without_alarp_is_illegal() -> None:
    """评估直达验证必须 ALARP。"""
    case = _case_in(CaseState.ASSESSING)
    with pytest.raises(IllegalTransitionError):
        transition(case, CaseState.VERIFYING, Role.SAFETY_OFFICE, "skip capa")


def test_closed_to_assessing_requires_new_evidence() -> None:
    """关闭后重开评估需要新证据。"""
    closed = _case_in(CaseState.CLOSED)
    with pytest.raises(IllegalTransitionError):
        transition(closed, CaseState.ASSESSING, Role.SAFETY_OFFICE, "reopen")
    reopened = transition(
        closed,
        CaseState.ASSESSING,
        Role.SAFETY_OFFICE,
        "new photo",
        new_evidence=True,
    )
    assert reopened.state is CaseState.ASSESSING


def test_happy_path_to_closed() -> None:
    """草稿走到关闭。"""
    closed = _case_in(CaseState.CLOSED)
    assert closed.state is CaseState.CLOSED
    assert len(closed.audit) == 6


def test_audit_grows_by_one_per_transition() -> None:
    """每次迁移审计长度加一。"""
    case = _draft()
    hops = [
        CaseState.SUBMITTED,
        CaseState.TRIAGED,
        CaseState.ASSESSING,
        CaseState.MITIGATING,
        CaseState.VERIFYING,
        CaseState.CLOSED,
    ]
    for i, to_state in enumerate(hops, start=1):
        case = transition(case, to_state, Role.SYSTEM, f"step-{i}")
        assert len(case.audit) == i
    assert case.state is CaseState.CLOSED


def test_risk_matrix_extreme_band() -> None:
    """高严重度高可能性落在最高带。"""
    assert compute_risk_level(5, 5) is RiskLevel.EXTREME
    case = _draft(severity=5, likelihood=5)
    assert case.risk_level is RiskLevel.EXTREME


def test_risk_matrix_known_pairs() -> None:
    """矩阵覆盖四条风险带。"""
    assert compute_risk_level(1, 1) is RiskLevel.LOW
    assert compute_risk_level(2, 3) is RiskLevel.MEDIUM
    assert compute_risk_level(3, 4) is RiskLevel.HIGH
    assert compute_risk_level(4, 5) is RiskLevel.EXTREME


def test_invalid_score_rejected() -> None:
    """评分越界被拒绝。"""
    with pytest.raises(InvalidScoreError):
        compute_risk_level(0, 3)
    with pytest.raises(InvalidScoreError):
        _draft(severity=6, likelihood=1)


def test_change_risk_forbidden_when_closed() -> None:
    """关闭态改风险必须抛错。"""
    closed = _case_in(CaseState.CLOSED)
    with pytest.raises(ClosedCaseError):
        change_risk(closed, 5, 5)
    assessing = _case_in(CaseState.ASSESSING)
    updated = change_risk(assessing, 5, 4)
    assert updated.risk_level is RiskLevel.EXTREME
    assert assessing.severity == 1


def test_roles_are_four() -> None:
    """角色枚举正好四个。"""
    names = {role.value for role in Role}
    assert names == {"reporter", "dept_owner", "safety_office", "system"}


def test_frozen_case_requires_replace() -> None:
    """冻结案件不能原地改字段。"""
    case = _draft()
    with pytest.raises(FrozenInstanceError):
        case.state = CaseState.SUBMITTED  # type: ignore[misc]
    replaced = replace(case, hazard="updated")
    assert replaced.hazard == "updated"
    assert case.hazard == "FOD on taxiway"


def test_transitions_table_covers_every_state() -> None:
    """迁移表覆盖全部状态。"""
    assert set(TRANSITIONS) == set(CaseState)


def test_1000_legal_hops_under_200ms() -> None:
    """1000 次提交-分诊迁移必须低于 200ms。"""
    start = time.perf_counter()
    last = None
    for i in range(500):
        case = _draft(case_id=CaseId(f"C-{i}"))
        submitted = transition(case, CaseState.SUBMITTED, Role.REPORTER, "s")
        last = transition(submitted, CaseState.TRIAGED, Role.DEPT_OWNER, "t")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert last is not None and last.state is CaseState.TRIAGED
    assert elapsed_ms < 200, f"1000 hops took {elapsed_ms:.1f}ms"
