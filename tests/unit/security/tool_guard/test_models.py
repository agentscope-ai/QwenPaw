# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.tool_guard.models."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from datetime import timezone

from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
    _safe_repr,
)


# ---------------------------------------------------------------------------
# GuardSeverity
# ---------------------------------------------------------------------------


class TestGuardSeverity:
    """Tests for the GuardSeverity enum."""

    def test_all_values_exist(self):
        """All six severity levels must be defined."""
        expected = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "SAFE"}
        actual = {s.value for s in GuardSeverity}
        assert actual == expected

    def test_string_values(self):
        """Each enum member's value equals its uppercase name."""
        assert GuardSeverity.CRITICAL.value == "CRITICAL"
        assert GuardSeverity.HIGH.value == "HIGH"
        assert GuardSeverity.MEDIUM.value == "MEDIUM"
        assert GuardSeverity.LOW.value == "LOW"
        assert GuardSeverity.INFO.value == "INFO"
        assert GuardSeverity.SAFE.value == "SAFE"

    def test_is_str_enum(self):
        """GuardSeverity is a str Enum so members
        can be compared to strings."""
        assert GuardSeverity.CRITICAL == "CRITICAL"
        assert isinstance(GuardSeverity.SAFE, str)


# ---------------------------------------------------------------------------
# GuardThreatCategory
# ---------------------------------------------------------------------------


class TestGuardThreatCategory:
    """Tests for the GuardThreatCategory enum."""

    EXPECTED_CATEGORIES = {
        "COMMAND_INJECTION",
        "DATA_EXFILTRATION",
        "PATH_TRAVERSAL",
        "SENSITIVE_FILE_ACCESS",
        "NETWORK_ABUSE",
        "CREDENTIAL_EXPOSURE",
        "RESOURCE_ABUSE",
        "PROMPT_INJECTION",
        "CODE_EXECUTION",
        "PRIVILEGE_ESCALATION",
    }

    def test_all_ten_categories_exist(self):
        """Exactly ten threat categories must be defined."""
        assert len(GuardThreatCategory) == 10
        actual = {c.name for c in GuardThreatCategory}
        assert actual == self.EXPECTED_CATEGORIES

    def test_category_values_are_lowercase_snake(self):
        """Category values use lowercase snake_case convention."""
        for cat in GuardThreatCategory:
            assert cat.value == cat.name.lower()


# ---------------------------------------------------------------------------
# GuardFinding
# ---------------------------------------------------------------------------


class TestGuardFinding:
    """Tests for the GuardFinding dataclass."""

    def test_creation_with_required_fields(self):
        """A finding can be created with only required fields."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.CRITICAL,
            title="Test",
            description="A test finding",
            tool_name="execute_shell_command",
        )
        assert finding.id == "f-1"
        assert finding.rule_id == "R-001"
        assert finding.category == GuardThreatCategory.COMMAND_INJECTION
        assert finding.severity == GuardSeverity.CRITICAL
        assert finding.title == "Test"
        assert finding.description == "A test finding"
        assert finding.tool_name == "execute_shell_command"

    def test_optional_fields_default_to_none(self):
        """Optional fields default to None when not provided."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.PATH_TRAVERSAL,
            severity=GuardSeverity.HIGH,
            title="Test",
            description="desc",
            tool_name="read_file",
        )
        assert finding.param_name is None
        assert finding.matched_value is None
        assert finding.matched_pattern is None
        assert finding.snippet is None
        assert finding.remediation is None
        assert finding.guardian is None

    def test_metadata_defaults_to_empty_dict(self):
        """The metadata field defaults to an empty dict."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.CODE_EXECUTION,
            severity=GuardSeverity.MEDIUM,
            title="T",
            description="d",
            tool_name="shell",
        )
        assert not finding.metadata

    def test_to_dict(self):
        """to_dict returns a complete, serialisable dictionary."""
        finding = GuardFinding(
            id="f-42",
            rule_id="CMD-001",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.HIGH,
            title="Shell injection",
            description="Dangerous command detected",
            tool_name="execute_shell_command",
            param_name="command",
            matched_value="rm -rf /",
        )
        d = finding.to_dict()
        assert d["id"] == "f-42"
        assert d["rule_id"] == "CMD-001"
        assert d["category"] == "command_injection"
        assert d["severity"] == "HIGH"
        assert d["param_name"] == "command"
        assert d["matched_value"] == "rm -rf /"
        # Optional fields that were not set
        assert d["matched_pattern"] is None
        assert d["snippet"] is None
        assert d["remediation"] is None
        assert d["guardian"] is None
        assert not d["metadata"]


# ---------------------------------------------------------------------------
# ToolGuardResult
# ---------------------------------------------------------------------------


class TestToolGuardResult:
    """Tests for the ToolGuardResult dataclass."""

    def test_is_safe_with_no_findings(self):
        """Result with no findings is safe."""
        result = ToolGuardResult(tool_name="read_file", params={})
        assert result.is_safe is True

    def test_is_safe_with_medium_finding(self):
        """Result with only MEDIUM-or-lower findings is safe."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.NETWORK_ABUSE,
            severity=GuardSeverity.MEDIUM,
            title="info",
            description="d",
            tool_name="sh",
        )
        result = ToolGuardResult(
            tool_name="sh",
            params={},
            findings=[finding],
        )
        assert result.is_safe is True

    def test_is_not_safe_with_critical_finding(self):
        """A CRITICAL finding makes the result unsafe."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.CRITICAL,
            title="critical",
            description="d",
            tool_name="sh",
        )
        result = ToolGuardResult(
            tool_name="sh",
            params={},
            findings=[finding],
        )
        assert result.is_safe is False

    def test_is_not_safe_with_high_finding(self):
        """A HIGH finding also makes the result unsafe."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.PATH_TRAVERSAL,
            severity=GuardSeverity.HIGH,
            title="high",
            description="d",
            tool_name="sh",
        )
        result = ToolGuardResult(
            tool_name="sh",
            params={},
            findings=[finding],
        )
        assert result.is_safe is False

    def test_max_severity_empty_findings_returns_safe(self):
        """With no findings, max_severity is SAFE."""
        result = ToolGuardResult(tool_name="t", params={})
        assert result.max_severity == GuardSeverity.SAFE

    def test_max_severity_returns_highest(self):
        """max_severity returns the highest among mixed findings."""
        findings = [
            GuardFinding(
                id="f-1",
                rule_id="R1",
                category=GuardThreatCategory.NETWORK_ABUSE,
                severity=GuardSeverity.LOW,
                title="low",
                description="d",
                tool_name="t",
            ),
            GuardFinding(
                id="f-2",
                rule_id="R2",
                category=GuardThreatCategory.COMMAND_INJECTION,
                severity=GuardSeverity.CRITICAL,
                title="critical",
                description="d",
                tool_name="t",
            ),
            GuardFinding(
                id="f-3",
                rule_id="R3",
                category=GuardThreatCategory.PATH_TRAVERSAL,
                severity=GuardSeverity.HIGH,
                title="high",
                description="d",
                tool_name="t",
            ),
        ]
        result = ToolGuardResult(
            tool_name="t",
            params={},
            findings=findings,
        )
        assert result.max_severity == GuardSeverity.CRITICAL

    def test_max_severity_info_only(self):
        """With only INFO-level findings, max_severity is INFO."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R1",
            category=GuardThreatCategory.RESOURCE_ABUSE,
            severity=GuardSeverity.INFO,
            title="info",
            description="d",
            tool_name="t",
        )
        result = ToolGuardResult(
            tool_name="t",
            params={},
            findings=[finding],
        )
        assert result.max_severity == GuardSeverity.INFO

    def test_findings_count(self):
        """findings_count returns the number of findings."""
        assert ToolGuardResult(tool_name="t", params={}).findings_count == 0

        findings = [
            GuardFinding(
                id=f"f-{i}",
                rule_id="R",
                category=GuardThreatCategory.CODE_EXECUTION,
                severity=GuardSeverity.LOW,
                title="t",
                description="d",
                tool_name="t",
            )
            for i in range(3)
        ]
        result = ToolGuardResult(
            tool_name="t",
            params={},
            findings=findings,
        )
        assert result.findings_count == 3

    def test_get_findings_by_severity(self):
        """get_findings_by_severity filters correctly."""
        f_low = GuardFinding(
            id="f-1",
            rule_id="R1",
            category=GuardThreatCategory.RESOURCE_ABUSE,
            severity=GuardSeverity.LOW,
            title="low",
            description="d",
            tool_name="t",
        )
        f_crit = GuardFinding(
            id="f-2",
            rule_id="R2",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.CRITICAL,
            title="critical",
            description="d",
            tool_name="t",
        )
        result = ToolGuardResult(
            tool_name="t",
            params={},
            findings=[f_low, f_crit],
        )
        assert result.get_findings_by_severity(GuardSeverity.CRITICAL) == [
            f_crit,
        ]
        assert result.get_findings_by_severity(GuardSeverity.LOW) == [f_low]
        assert not result.get_findings_by_severity(GuardSeverity.HIGH)

    def test_get_findings_by_category(self):
        """get_findings_by_category filters correctly."""
        f_cmd = GuardFinding(
            id="f-1",
            rule_id="R1",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.HIGH,
            title="cmd",
            description="d",
            tool_name="t",
        )
        f_path = GuardFinding(
            id="f-2",
            rule_id="R2",
            category=GuardThreatCategory.PATH_TRAVERSAL,
            severity=GuardSeverity.MEDIUM,
            title="path",
            description="d",
            tool_name="t",
        )
        result = ToolGuardResult(
            tool_name="t",
            params={},
            findings=[f_cmd, f_path],
        )
        assert result.get_findings_by_category(
            GuardThreatCategory.COMMAND_INJECTION,
        ) == [f_cmd]
        assert result.get_findings_by_category(
            GuardThreatCategory.PATH_TRAVERSAL,
        ) == [f_path]
        assert not result.get_findings_by_category(
            GuardThreatCategory.NETWORK_ABUSE,
        )

    def test_to_dict_serialization(self):
        """to_dict produces a complete dictionary with serialisable values."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.CRITICAL,
            title="Command injection",
            description="Dangerous command",
            tool_name="execute_shell_command",
            param_name="command",
            matched_value="rm -rf /",
        )
        result = ToolGuardResult(
            tool_name="execute_shell_command",
            params={"command": "rm -rf /"},
            findings=[finding],
            guard_duration_seconds=0.05,
            guardians_used=["rule_guardian"],
        )
        d = result.to_dict()
        assert d["tool_name"] == "execute_shell_command"
        assert d["is_safe"] is False
        assert d["max_severity"] == "CRITICAL"
        assert d["findings_count"] == 1
        assert len(d["findings"]) == 1
        assert d["findings"][0]["id"] == "f-1"
        assert d["guard_duration_seconds"] == 0.05
        assert d["guardians_used"] == ["rule_guardian"]
        # timestamp should be a valid ISO string
        assert isinstance(d["timestamp"], str)
        # params should be safe-repr'd strings
        assert isinstance(d["params"]["command"], str)

    def test_to_dict_omits_guardians_failed_when_empty(self):
        """to_dict does not include guardians_failed key when list is empty."""
        result = ToolGuardResult(tool_name="t", params={})
        d = result.to_dict()
        assert "guardians_failed" not in d

    def test_to_dict_includes_guardians_failed_when_present(self):
        """to_dict includes guardians_failed when there are failures."""
        result = ToolGuardResult(
            tool_name="t",
            params={},
            guardians_failed=[{"name": "file_guardian", "error": "timeout"}],
        )
        d = result.to_dict()
        assert d["guardians_failed"] == [
            {"name": "file_guardian", "error": "timeout"},
        ]

    def test_default_timestamp_is_utc(self):
        """Default timestamp is UTC-aware."""
        result = ToolGuardResult(tool_name="t", params={})
        assert result.timestamp.tzinfo is not None
        assert result.timestamp.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# _safe_repr
# ---------------------------------------------------------------------------


class TestSafeRepr:
    """Tests for the _safe_repr helper."""

    def test_short_string_unchanged(self):
        """Short strings are returned as-is."""
        assert _safe_repr("hello") == "hello"

    def test_truncation_at_max_len(self):
        """Strings exceeding max_len are truncated with ellipsis."""
        long_str = "a" * 300
        result = _safe_repr(long_str, max_len=200)
        assert len(result) == 201  # 200 chars + "…"
        assert result.endswith("…")
        assert result[:200] == long_str[:200]

    def test_exact_max_len_not_truncated(self):
        """String exactly at max_len is not truncated."""
        s = "b" * 200
        assert _safe_repr(s, max_len=200) == s

    def test_custom_max_len(self):
        """Custom max_len is respected."""
        assert _safe_repr("abcdefghij", max_len=5) == "abcde…"

    def test_non_string_value(self):
        """Non-string values are str()-converted before truncation."""
        assert _safe_repr(42) == "42"
        assert _safe_repr(None) == "None"
        assert _safe_repr([1, 2, 3]) == "[1, 2, 3]"

    def test_non_string_truncation(self):
        """Non-string values longer than max_len are also truncated."""
        long_list = list(range(1000))
        result = _safe_repr(long_list, max_len=50)
        assert len(result) == 51  # 50 + "…"
        assert result.endswith("…")
