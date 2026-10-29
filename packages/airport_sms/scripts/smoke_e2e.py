#!/usr/bin/env python3
"""全链路冒烟：草稿到关闭（fakes）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from airport_sms.channels import InboundMessage, WeComChannel  # noqa: E402
from airport_sms.config import default_config  # noqa: E402
from airport_sms.domain import CaseId, CaseState, Role, new_draft, transition  # noqa: E402
from airport_sms.obs import Metrics, load_fixtures, run_eval  # noqa: E402
from airport_sms.runtime import AgentRequest, Runtime  # noqa: E402
from airport_sms.session.principal import Principal  # noqa: E402
from airport_sms.tasks import Scheduler  # noqa: E402


def main() -> int:
    cfg = default_config()
    assert cfg.external_sms_bridge.enabled is False
    assert cfg.auth_required is True
    assert cfg.schema_version == "1.0.0"

    rt = Runtime.in_memory()
    principal = Principal("u1", "org-a", Role.REPORTER, "site-1")
    events = list(
        rt.run(AgentRequest("smoke", principal, text="draft FOD on TWY A"))
    )
    assert any(e.get("type") == "case" for e in events), events

    listed = rt.cases.list_by_site(principal)
    assert listed
    case = listed[0]

    sub_events = list(
        rt.run(AgentRequest("smoke", principal, command="submit"))
    )
    gov = [e for e in sub_events if e.get("type") == "governance"]
    assert gov and gov[0]["action"] == "ask"
    approval_id = gov[0]["approval_id"]
    rt.governor.approvals.decide(approval_id, approve=True)
    case = transition(case, CaseState.SUBMITTED, Role.REPORTER, "approved")
    rt.cases.write(principal, case, expected_version=listed[0].version)
    assert rt.cases.get(principal, case.id).state is CaseState.SUBMITTED

    # 裁判背书（fake）
    endorse = rt.gateway.judge("assess close")
    assert endorse == "endorse"

    for to, reason in [
        (CaseState.TRIAGED, "t"),
        (CaseState.ASSESSING, "a"),
        (CaseState.MITIGATING, "m"),
        (CaseState.VERIFYING, "v"),
        (CaseState.CLOSED, "c"),
    ]:
        prev = case.version
        case = transition(case, to, Role.SAFETY_OFFICE, reason)
        rt.cases.write(principal, case, expected_version=prev)
    assert case.state is CaseState.CLOSED

    sched = Scheduler(org_id="org-a", site_id="site-1")
    event = sched.fire_overdue(CaseId(str(case.id)), idem_key="smoke-od")
    assert event is not None and event.source == "scheduler"

    ch = WeComChannel(
        Runtime.in_memory(),
        allowed_groups={"g1"},
        site_map={"g1": "site-1"},
    )
    wecom_events = ch.handle(
        InboundMessage("u", "draft smoke", "g1", "site-1")
    )
    assert any(e.get("type") for e in wecom_events)

    metrics = Metrics(ask_count=1)
    assert "ask_rate" in metrics.export()
    fixtures = ROOT / "evals" / "fixtures" / "risk_band.json"
    out = ROOT / "evals" / "smoke_report.json"
    report = run_eval(load_fixtures(fixtures), out)
    print("eval_precision", report.precision)
    print("report", report.path)
    print("bridge_enabled", cfg.external_sms_bridge.enabled)
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
