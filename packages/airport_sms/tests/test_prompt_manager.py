"""提示组装行为测试。"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pytest

from airport_sms.context import (
    ManualIndex,
    ManualMissingError,
    PromptManager,
)
from airport_sms.domain import CaseId, Role, new_draft

MANUALS = Path(__file__).resolve().parents[1] / "assets" / "manuals"


def _mgr(**kwargs: object) -> PromptManager:
    index = ManualIndex(MANUALS)
    return PromptManager.from_index(index, site_id="TWY-A", **kwargs)  # type: ignore[arg-type]


def _case():
    return new_draft(
        case_id=CaseId("C-1"),
        hazard="FOD",
        location="TWY A",
        severity=3,
        likelihood=3,
    )


def test_reporter_prompt_has_duties_no_close() -> None:
    bundle = _mgr().build(role=Role.REPORTER, case=_case())
    assert "起草并提交" in bundle.system
    assert "不得关闭" in bundle.system
    assert "close_case" in bundle.system
    assert "[hint]" not in bundle.system or "user:" not in bundle.system.lower()


def test_safety_office_has_close_authority() -> None:
    bundle = _mgr().build(role=Role.SAFETY_OFFICE, case=_case())
    assert "关闭" in bundle.system
    assert "close" in bundle.system.lower()


def test_case_snapshot_present() -> None:
    case = _case()
    bundle = _mgr().build(role=Role.REPORTER, case=case)
    assert "C-1" in bundle.system
    assert "draft" in bundle.system


def test_cite_two_clauses_on_proposal() -> None:
    case = _case()
    mgr = _mgr()
    bundle, decision = mgr.propose(
        role=Role.SAFETY_OFFICE,
        case=case,
        action="assess",
        clause_ids=["SMS-1.1", "SMS-2.3"],
    )
    assert decision.cited_clauses == ("SMS-1.1", "SMS-2.3")
    assert "SMS-1.1" in bundle.system
    assert "SMS-2.3" in bundle.system


def test_overflow_drops_lowest_priority() -> None:
    mgr = PromptManager(
        {"SMS-1.1": "## SMS-1.1\n" + ("x" * 2000)},
        budget_chars=400,
        site_id="S1",
    )
    bundle = mgr.build(
        role=Role.REPORTER,
        case=_case(),
        clause_ids=["SMS-1.1"],
        hint="huge " + ("y" * 500),
    )
    assert "[role]" in bundle.system
    assert "[hint]" not in bundle.system


def test_missing_manual_fails_closed() -> None:
    with pytest.raises(ManualMissingError):
        ManualIndex(Path("/tmp/airport-sms-no-manuals-xyz")).load()
    mgr = _mgr()
    with pytest.raises(ManualMissingError):
        mgr.build(
            role=Role.REPORTER,
            case=_case(),
            clause_ids=["SMS-NOPE"],
        )


def test_site_section_loads() -> None:
    bundle = _mgr().build(role=Role.REPORTER, case=None, site_id="GATE-12")
    assert "GATE-12" in bundle.system
    assert "[site]" in bundle.system


def test_no_channel_marketing() -> None:
    bundle = _mgr().build(
        role=Role.REPORTER,
        case=_case(),
        hint="follow site rule",
    )
    lower = bundle.system.lower()
    assert "wecom" not in lower
    assert "企业微信" not in bundle.system
    assert "whatsapp" not in lower
    assert "[hint]" in bundle.system
    assert "user:" not in lower


def test_contributor_order_stable() -> None:
    mgr = _mgr()
    a = mgr.build(
        role=Role.REPORTER,
        case=_case(),
        clause_ids=["SMS-1.1"],
    )
    b = mgr.build(
        role=Role.REPORTER,
        case=_case(),
        clause_ids=["SMS-1.1"],
    )
    assert a.digest == b.digest
    assert a.system == b.system


def test_hint_is_system_not_fake_user() -> None:
    bundle = _mgr().build(
        role=Role.REPORTER,
        case=_case(),
        hint="prefer ALARP path",
    )
    assert bundle.system.startswith("[role]")
    assert "[hint]\nprefer ALARP path" in bundle.system
    assert "\nuser:" not in bundle.system.lower()


def test_prompt_build_p95_under_50ms() -> None:
    mgr = _mgr()
    case = _case()
    samples: list[float] = []
    for _ in range(100):
        start = perf_counter()
        mgr.build(
            role=Role.SAFETY_OFFICE,
            case=case,
            clause_ids=["SMS-1.1", "SMS-2.3", "SMS-4.1"],
            hint="check",
        )
        samples.append((perf_counter() - start) * 1000)
    samples.sort()
    p95 = samples[94]
    assert p95 < 50, f"p95={p95:.2f}ms"
