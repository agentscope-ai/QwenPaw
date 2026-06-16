# -*- coding: utf-8 -*-
"""Data models for built-in tool guard rule integrity."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RuleIntegrityFinding:
    """One rule integrity verification finding."""

    file: str
    reason: str
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuleIntegrityResult:
    """Latest built-in rule integrity verification result."""

    ok: bool
    status: str
    message: str
    checked_at: str | None
    findings: list[RuleIntegrityFinding]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [f.to_dict() for f in self.findings]
        return data


@dataclass(frozen=True)
class RuleIntegrityRepairResult:
    """Result of attempting to restore the built-in rule file."""

    ok: bool
    message: str
    source_url: str
    backup_path: str | None
    integrity: RuleIntegrityResult
    connection_timeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["integrity"] = self.integrity.to_dict()
        return data
