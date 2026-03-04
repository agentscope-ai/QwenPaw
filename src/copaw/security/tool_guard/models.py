# -*- coding: utf-8 -*-
"""Data models for tool-call guarding.

These models are intentionally separate from the skill-scanner models so
that the two sub-systems can evolve independently while sharing the same
conceptual vocabulary (severity, threat category, finding, result).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GuardSeverity(str, Enum):
    """Severity levels for guard findings."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    SAFE = "SAFE"


class GuardThreatCategory(str, Enum):
    """Categories of threats detectable in tool parameters.

    The full taxonomy is listed for forward-compatibility; only a subset
    is exercised by the currently-shipped rules.
    """

    COMMAND_INJECTION = "command_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    PATH_TRAVERSAL = "path_traversal"
    SENSITIVE_FILE_ACCESS = "sensitive_file_access"
    NETWORK_ABUSE = "network_abuse"
    CREDENTIAL_EXPOSURE = "credential_exposure"
    RESOURCE_ABUSE = "resource_abuse"
    PROMPT_INJECTION = "prompt_injection"
    CODE_EXECUTION = "code_execution"
    PRIVILEGE_ESCALATION = "privilege_escalation"


# ---------------------------------------------------------------------------
# AuditFinding
# ---------------------------------------------------------------------------


@dataclass
class GuardFinding:
    """A single security finding from guarding tool parameters."""

    id: str
    rule_id: str
    category: GuardThreatCategory
    severity: GuardSeverity
    title: str
    description: str
    tool_name: str
    param_name: str | None = None
    matched_value: str | None = None
    matched_pattern: str | None = None
    snippet: str | None = None
    remediation: str | None = None
    guardian: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "tool_name": self.tool_name,
            "param_name": self.param_name,
            "matched_value": self.matched_value,
            "matched_pattern": self.matched_pattern,
            "snippet": self.snippet,
            "remediation": self.remediation,
            "guardian": self.guardian,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# ToolGuardResult
# ---------------------------------------------------------------------------


@dataclass
class ToolGuardResult:
    """Aggregated results from guarding a single tool call."""

    tool_name: str
    params: dict[str, Any]
    findings: list[GuardFinding] = field(default_factory=list)
    guard_duration_seconds: float = 0.0
    guardians_used: list[str] = field(default_factory=list)
    guardians_failed: list[dict[str, str]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_safe(self) -> bool:
        """``True`` when there are no CRITICAL or HIGH findings."""
        return not any(
            f.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH)
            for f in self.findings
        )

    @property
    def max_severity(self) -> GuardSeverity:
        """Return the highest severity found, or ``SAFE``."""
        if not self.findings:
            return GuardSeverity.SAFE
        order = [
            GuardSeverity.CRITICAL,
            GuardSeverity.HIGH,
            GuardSeverity.MEDIUM,
            GuardSeverity.LOW,
            GuardSeverity.INFO,
        ]
        for sev in order:
            if any(f.severity == sev for f in self.findings):
                return sev
        return GuardSeverity.SAFE

    @property
    def findings_count(self) -> int:
        return len(self.findings)

    def get_findings_by_severity(self, severity: GuardSeverity) -> list[GuardFinding]:
        return [f for f in self.findings if f.severity == severity]

    def get_findings_by_category(self, category: GuardThreatCategory) -> list[GuardFinding]:
        return [f for f in self.findings if f.category == category]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tool_name": self.tool_name,
            "params": {k: _safe_repr(v) for k, v in self.params.items()},
            "is_safe": self.is_safe,
            "max_severity": self.max_severity.value,
            "findings_count": self.findings_count,
            "findings": [f.to_dict() for f in self.findings],
            "guard_duration_seconds": self.guard_duration_seconds,
            "guardians_used": self.guardians_used,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.guardians_failed:
            result["guardians_failed"] = self.guardians_failed
        return result


def _safe_repr(value: Any, max_len: int = 200) -> str:
    """Produce a truncated string representation for logging."""
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s
