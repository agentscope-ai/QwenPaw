"""离线评估：风险带精度。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from airport_sms.domain.case import RiskLevel, compute_risk_level


@dataclass(frozen=True)
class EvalCase:
    """标注样本。"""

    hazard: str
    severity: int
    likelihood: int
    expected: RiskLevel


@dataclass
class EvalReport:
    """评估报告。"""

    precision: float
    total: int
    correct: int
    path: str


def load_fixtures(path: Path) -> list[EvalCase]:
    """加载夹具。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            hazard=row["hazard"],
            severity=row["severity"],
            likelihood=row["likelihood"],
            expected=RiskLevel(row["expected"]),
        )
        for row in data
    ]


def run_eval(fixtures: list[EvalCase], out: Path) -> EvalReport:
    """跑评估并写报告。不碰生产库。"""
    correct = 0
    for row in fixtures:
        got = compute_risk_level(row.severity, row.likelihood)
        if got is row.expected:
            correct += 1
    total = len(fixtures)
    precision = correct / total if total else 0.0
    report = EvalReport(
        precision=precision, total=total, correct=correct, path=str(out)
    )
    out.write_text(
        json.dumps(
            {
                "precision": precision,
                "total": total,
                "correct": correct,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def threshold_ok(report: EvalReport, *, min_precision: float = 0.9) -> bool:
    """是否过阈值。"""
    return report.precision >= min_precision


__all__ = ["EvalCase", "EvalReport", "load_fixtures", "run_eval", "threshold_ok"]
