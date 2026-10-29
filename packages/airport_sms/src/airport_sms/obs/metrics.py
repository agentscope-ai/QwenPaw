"""观测指标。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Metrics:
    """计数与比率。"""

    ask_count: int = 0
    deny_count: int = 0
    approve_count: int = 0
    overdue_count: int = 0
    citation_miss: int = 0
    approve_latency_ms: list[float] = field(default_factory=list)

    def ask_rate(self) -> float:
        """ASK 占比。"""
        total = self.ask_count + self.deny_count + self.approve_count
        return self.ask_count / total if total else 0.0

    def bump_citation_miss(self) -> None:
        """引用缺失加一。"""
        self.citation_miss += 1

    def export(self) -> dict[str, float | int]:
        """仪表盘 JSON。"""
        return {
            "ask_rate": self.ask_rate(),
            "deny_count": self.deny_count,
            "overdue_count": self.overdue_count,
            "citation_miss": self.citation_miss,
        }


__all__ = ["Metrics"]
