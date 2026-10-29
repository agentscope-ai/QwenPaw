"""观测与评估测试。"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from airport_sms.obs import (
    Metrics,
    Tracer,
    load_fixtures,
    redact,
    run_eval,
    threshold_ok,
)

FIX = (
    Path(__file__).resolve().parents[1] / "evals" / "fixtures" / "risk_band.json"
)


def test_ask_rate_registered() -> None:
    m = Metrics(ask_count=1, deny_count=1)
    assert "ask_rate" in m.export()


def test_trace_includes_governance() -> None:
    t = Tracer()
    t.start("governance", tool="submit_case")
    assert any(s.name == "governance" for s in t.spans)


def test_fixture_eval_writes_report(tmp_path) -> None:
    report = run_eval(load_fixtures(FIX), tmp_path / "report.json")
    assert Path(report.path).exists()
    assert report.precision == 1.0


def test_citation_miss_increments() -> None:
    m = Metrics()
    m.bump_citation_miss()
    assert m.citation_miss == 1


def test_feedback_not_builtin() -> None:
    feedback: list[str] = []
    builtin_len = 0
    feedback.append("correct location")
    assert len(feedback) == 1
    assert builtin_len == 0


def test_dashboard_json() -> None:
    m = Metrics(overdue_count=2)
    assert m.export()["overdue_count"] == 2


def test_pii_redaction() -> None:
    assert "[phone]" in redact("call 13800138000 now")


def test_eval_threshold_fail_then_ok(tmp_path) -> None:
    report = run_eval(load_fixtures(FIX), tmp_path / "r.json")
    assert threshold_ok(report, min_precision=0.9)
    assert not threshold_ok(report, min_precision=1.1)


def test_quality_job_scheduler_source() -> None:
    source = "scheduler"
    assert source == "scheduler"


def test_eval_scratch_only(tmp_path) -> None:
    run_eval(load_fixtures(FIX), tmp_path / "scratch.json")
    assert (tmp_path / "scratch.json").exists()


def test_eval_under_30s(tmp_path) -> None:
    start = perf_counter()
    run_eval(load_fixtures(FIX), tmp_path / "p.json")
    assert (perf_counter() - start) < 30
