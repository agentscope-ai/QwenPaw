# -*- coding: utf-8 -*-
"""Data models for skill scanning results.

"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """Severity levels for security findings."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    SAFE = "SAFE"


class ThreatCategory(str, Enum):
    """Categories of security threats.

    The full taxonomy is kept for forward-compatibility; only a subset
    is exercised by the currently-shipped pattern rules.
    """

    PROMPT_INJECTION = "prompt_injection"
    COMMAND_INJECTION = "command_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    UNAUTHORIZED_TOOL_USE = "unauthorized_tool_use"
    OBFUSCATION = "obfuscation"
    HARDCODED_SECRETS = "hardcoded_secrets"
    SOCIAL_ENGINEERING = "social_engineering"
    RESOURCE_ABUSE = "resource_abuse"
    POLICY_VIOLATION = "policy_violation"
    MALWARE = "malware"
    HARMFUL_CONTENT = "harmful_content"
    SKILL_DISCOVERY_ABUSE = "skill_discovery_abuse"
    TRANSITIVE_TRUST_ABUSE = "transitive_trust_abuse"
    AUTONOMY_ABUSE = "autonomy_abuse"
    TOOL_CHAINING_ABUSE = "tool_chaining_abuse"
    UNICODE_STEGANOGRAPHY = "unicode_steganography"
    SUPPLY_CHAIN_ATTACK = "supply_chain_attack"


# ---------------------------------------------------------------------------
# Skill file model (lightweight – no dependency on frontmatter)
# ---------------------------------------------------------------------------

_FILE_TYPE_MAP: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".py": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".js": "javascript",
    ".ts": "typescript",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}


@dataclass
class SkillFile:
    """A file within a skill package."""

    path: Path
    relative_path: str
    file_type: str  # 'markdown', 'python', 'bash', 'binary', 'other'
    content: str | None = None
    size_bytes: int = 0

    def read_content(self) -> str:
        """Read file content if not already loaded."""
        if self.content is None and self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.content = f.read()
            except (OSError, UnicodeDecodeError):
                self.content = ""
        return self.content or ""

    @property
    def is_hidden(self) -> bool:
        """Check if this file is a hidden file (dotfile) or inside a hidden directory."""
        parts = Path(self.relative_path).parts
        return any(part.startswith(".") and part != "." for part in parts)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_path(cls, path: Path, base_dir: Path) -> "SkillFile":
        """Create a SkillFile from an on-disk path relative to *base_dir*."""
        rel = str(path.relative_to(base_dir))
        suffix = path.suffix.lower()
        file_type = _FILE_TYPE_MAP.get(suffix, "other")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return cls(
            path=path,
            relative_path=rel,
            file_type=file_type,
            size_bytes=size,
        )


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A security issue discovered during a skill scan."""

    id: str
    rule_id: str
    category: ThreatCategory
    severity: Severity
    title: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    snippet: str | None = None
    remediation: str | None = None
    analyzer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "snippet": self.snippet,
            "remediation": self.remediation,
            "analyzer": self.analyzer,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Scan result
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Aggregated results from scanning a single skill."""

    skill_name: str
    skill_directory: str
    findings: list[Finding] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    analyzers_used: list[str] = field(default_factory=list)
    analyzers_failed: list[dict[str, str]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_safe(self) -> bool:
        """``True`` when there are no CRITICAL or HIGH findings."""
        return not any(
            f.severity in (Severity.CRITICAL, Severity.HIGH)
            for f in self.findings
        )

    @property
    def max_severity(self) -> Severity:
        """Return the highest severity found, or ``SAFE``."""
        if not self.findings:
            return Severity.SAFE
        order = [
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
            Severity.INFO,
        ]
        for sev in order:
            if any(f.severity == sev for f in self.findings):
                return sev
        return Severity.SAFE

    def get_findings_by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def get_findings_by_category(self, category: ThreatCategory) -> list[Finding]:
        return [f for f in self.findings if f.category == category]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "skill_name": self.skill_name,
            "skill_path": self.skill_directory,
            "is_safe": self.is_safe,
            "max_severity": self.max_severity.value,
            "findings_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "scan_duration_seconds": self.scan_duration_seconds,
            "analyzers_used": self.analyzers_used,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.analyzers_failed:
            result["analyzers_failed"] = self.analyzers_failed
        return result
