# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.skill_scanner.models.

Covers:
- Severity and ThreatCategory enums
- SkillFile creation and methods
- Finding creation and serialization
- ScanResult properties and methods
"""
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from datetime import datetime, timezone
from pathlib import Path


from qwenpaw.security.skill_scanner.models import (
    Finding,
    ScanResult,
    Severity,
    SkillFile,
    ThreatCategory,
)


# ---------------------------------------------------------------------------
# Severity enum
# ---------------------------------------------------------------------------


class TestSeverity:
    """Tests for Severity enum."""

    def test_all_values_exist(self):
        """All severity levels should be defined."""
        expected = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "SAFE"}
        assert {s.name for s in Severity} == expected

    def test_string_values(self):
        """Enum values should match their names."""
        assert Severity.CRITICAL.value == "CRITICAL"
        assert Severity.SAFE.value == "SAFE"

    def test_ordering(self):
        """Severity is a string enum, compare by value."""
        assert Severity.CRITICAL.value == "CRITICAL"
        assert Severity.HIGH.value == "HIGH"


# ---------------------------------------------------------------------------
# ThreatCategory enum
# ---------------------------------------------------------------------------


class TestThreatCategory:
    """Tests for ThreatCategory enum."""

    def test_all_categories_exist(self):
        """All threat categories should be defined."""
        expected = {
            "PROMPT_INJECTION",
            "COMMAND_INJECTION",
            "DATA_EXFILTRATION",
            "UNAUTHORIZED_TOOL_USE",
            "OBFUSCATION",
            "HARDCODED_SECRETS",
            "SOCIAL_ENGINEERING",
            "RESOURCE_ABUSE",
            "POLICY_VIOLATION",
            "MALWARE",
            "HARMFUL_CONTENT",
            "SKILL_DISCOVERY_ABUSE",
            "TRANSITIVE_TRUST_ABUSE",
            "AUTONOMY_ABUSE",
            "TOOL_CHAINING_ABUSE",
            "UNICODE_STEGANOGRAPHY",
            "SUPPLY_CHAIN_ATTACK",
        }
        assert {c.name for c in ThreatCategory} == expected

    def test_string_values(self):
        """Category values should be lowercase snake_case."""
        assert ThreatCategory.COMMAND_INJECTION.value == "command_injection"
        assert ThreatCategory.HARDCODED_SECRETS.value == "hardcoded_secrets"


# ---------------------------------------------------------------------------
# SkillFile
# ---------------------------------------------------------------------------


class TestSkillFile:
    """Tests for SkillFile dataclass."""

    def test_creation(self, tmp_path):
        """SkillFile should store path and metadata."""
        f = tmp_path / "test.py"
        f.write_text("hello")
        sf = SkillFile(
            path=f,
            relative_path="test.py",
            file_type="python",
            size_bytes=5,
        )
        assert sf.path == f
        assert sf.relative_path == "test.py"
        assert sf.file_type == "python"
        assert sf.size_bytes == 5
        assert sf.content is None

    def test_is_hidden_dotfile(self):
        """Dotfiles should be detected as hidden."""
        sf = SkillFile(
            path=Path("/tmp/.env"),
            relative_path=".env",
            file_type="other",
        )
        assert sf.is_hidden is True

    def test_is_hidden_in_hidden_dir(self):
        """Files in hidden directories should be detected as hidden."""
        sf = SkillFile(
            path=Path("/tmp/.git/config"),
            relative_path=".git/config",
            file_type="other",
        )
        assert sf.is_hidden is True

    def test_is_not_hidden(self):
        """Normal files should not be hidden."""
        sf = SkillFile(
            path=Path("/tmp/hello.py"),
            relative_path="hello.py",
            file_type="python",
        )
        assert sf.is_hidden is False

    def test_is_hidden_current_dir_not_hidden(self):
        """The '.' directory itself should not count as hidden."""
        sf = SkillFile(
            path=Path("/tmp/./hello.py"),
            relative_path="./hello.py",
            file_type="python",
        )
        # '.' is excluded by the condition `part != "."`
        assert sf.is_hidden is False

    def test_read_content(self, tmp_path):
        """read_content should read file from disk."""
        f = tmp_path / "test.md"
        f.write_text("hello world")
        sf = SkillFile(
            path=f,
            relative_path="test.md",
            file_type="markdown",
        )
        assert sf.read_content() == "hello world"
        assert sf.content == "hello world"

    def test_read_content_cached(self, tmp_path):
        """read_content should use cached content if available."""
        sf = SkillFile(
            path=Path("/nonexistent"),
            relative_path="gone.py",
            file_type="python",
            content="cached",
        )
        assert sf.read_content() == "cached"

    def test_read_content_nonexistent_file(self):
        """read_content should return empty string for missing files."""
        sf = SkillFile(
            path=Path("/nonexistent/file.py"),
            relative_path="file.py",
            file_type="python",
        )
        assert sf.read_content() == ""

    def test_from_path(self, tmp_path):
        """from_path should create SkillFile from disk path."""
        f = tmp_path / "test.py"
        f.write_text("print('hi')")
        sf = SkillFile.from_path(f, tmp_path)
        assert sf.relative_path == "test.py"
        assert sf.file_type == "python"
        assert sf.size_bytes > 0

    def test_from_path_nested(self, tmp_path):
        """from_path should compute relative path for nested files."""
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "deep.md"
        f.write_text("# deep")
        sf = SkillFile.from_path(f, tmp_path)
        # Use forward-slash for cross-platform comparison
        assert sf.relative_path.replace("\\", "/") == "sub/deep.md"
        assert sf.file_type == "markdown"


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class TestFinding:
    """Tests for Finding dataclass."""

    def test_creation(self):
        """Finding should store all fields."""
        f = Finding(
            id="r1:f.py:1",
            rule_id="r1",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="Dangerous command",
            description="Found rm -rf",
        )
        assert f.id == "r1:f.py:1"
        assert f.rule_id == "r1"
        assert f.category == ThreatCategory.COMMAND_INJECTION
        assert f.severity == Severity.HIGH

    def test_optional_fields_default_none(self):
        """Optional fields should default to None."""
        f = Finding(
            id="r1",
            rule_id="r1",
            category=ThreatCategory.MALWARE,
            severity=Severity.LOW,
            title="t",
            description="d",
        )
        assert f.file_path is None
        assert f.line_number is None
        assert f.snippet is None
        assert f.remediation is None
        assert f.analyzer is None
        assert not f.metadata

    def test_to_dict(self):
        """to_dict should serialize all fields."""
        f = Finding(
            id="r1:f.py:1",
            rule_id="r1",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="Dangerous command",
            description="Found rm -rf",
            file_path="f.py",
            line_number=1,
            snippet="rm -rf /",
            remediation="Do not use",
            analyzer="pattern",
            metadata={"key": "val"},
        )
        d = f.to_dict()
        assert d["id"] == "r1:f.py:1"
        assert d["category"] == "command_injection"
        assert d["severity"] == "HIGH"
        assert d["file_path"] == "f.py"
        assert d["metadata"] == {"key": "val"}


# ---------------------------------------------------------------------------
# ScanResult
# ---------------------------------------------------------------------------


class TestScanResult:
    """Tests for ScanResult dataclass."""

    def test_is_safe_with_no_findings(self, safe_scan_result):
        """ScanResult with no findings should be safe."""
        assert safe_scan_result.is_safe is True

    def test_is_safe_with_low_severity(self):
        """ScanResult with only LOW/INFO findings should be safe."""
        f = Finding(
            id="r1",
            rule_id="r1",
            category=ThreatCategory.POLICY_VIOLATION,
            severity=Severity.LOW,
            title="t",
            description="d",
        )
        result = ScanResult(
            skill_name="s",
            skill_directory="/tmp",
            findings=[f],
        )
        assert result.is_safe is True

    def test_is_not_safe_with_high(self, sample_scan_result):
        """ScanResult with HIGH finding should not be safe."""
        assert sample_scan_result.is_safe is False

    def test_is_not_safe_with_critical(self):
        """ScanResult with CRITICAL finding should not be safe."""
        f = Finding(
            id="r1",
            rule_id="r1",
            category=ThreatCategory.MALWARE,
            severity=Severity.CRITICAL,
            title="t",
            description="d",
        )
        result = ScanResult(
            skill_name="s",
            skill_directory="/tmp",
            findings=[f],
        )
        assert result.is_safe is False

    def test_max_severity_empty(self, safe_scan_result):
        """max_severity with no findings should return SAFE."""
        assert safe_scan_result.max_severity == Severity.SAFE

    def test_max_severity_with_findings(self, sample_scan_result):
        """max_severity should return highest severity."""
        assert sample_scan_result.max_severity == Severity.HIGH

    def test_max_severity_ordering(self):
        """max_severity should return CRITICAL over HIGH."""
        findings = [
            Finding(
                id="r1",
                rule_id="r1",
                category=ThreatCategory.COMMAND_INJECTION,
                severity=Severity.LOW,
                title="t1",
                description="d1",
            ),
            Finding(
                id="r2",
                rule_id="r2",
                category=ThreatCategory.MALWARE,
                severity=Severity.CRITICAL,
                title="t2",
                description="d2",
            ),
        ]
        result = ScanResult(
            skill_name="s",
            skill_directory="/tmp",
            findings=findings,
        )
        assert result.max_severity == Severity.CRITICAL

    def test_findings_count_via_len(self, sample_scan_result):
        """Findings count should be accessible via len."""
        assert len(sample_scan_result.findings) == 1

    def test_get_findings_by_severity(self, sample_scan_result):
        """get_findings_by_severity should filter correctly."""
        high = sample_scan_result.get_findings_by_severity(Severity.HIGH)
        assert len(high) == 1
        low = sample_scan_result.get_findings_by_severity(Severity.LOW)
        assert len(low) == 0

    def test_get_findings_by_category(self, sample_scan_result):
        """get_findings_by_category should filter correctly."""
        ci = sample_scan_result.get_findings_by_category(
            ThreatCategory.COMMAND_INJECTION,
        )
        assert len(ci) == 1
        malware = sample_scan_result.get_findings_by_category(
            ThreatCategory.MALWARE,
        )
        assert len(malware) == 0

    def test_to_dict(self, sample_scan_result):
        """to_dict should include all key fields."""
        d = sample_scan_result.to_dict()
        assert d["skill_name"] == "test-skill"
        assert d["is_safe"] is False
        assert d["max_severity"] == "HIGH"
        assert d["findings_count"] == len(sample_scan_result.findings)
        assert len(d["findings"]) == 1

    def test_to_dict_without_analyzers_failed(self, safe_scan_result):
        """to_dict should omit analyzers_failed when empty."""
        d = safe_scan_result.to_dict()
        assert "analyzers_failed" not in d

    def test_to_dict_with_analyzers_failed(self):
        """to_dict should include analyzers_failed when present."""
        result = ScanResult(
            skill_name="s",
            skill_directory="/tmp",
            analyzers_failed=[{"analyzer": "pattern", "error": "boom"}],
        )
        d = result.to_dict()
        assert "analyzers_failed" in d
        assert len(d["analyzers_failed"]) == 1

    def test_default_timestamp(self):
        """ScanResult should auto-generate a UTC timestamp."""
        before = datetime.now(timezone.utc)
        result = ScanResult(skill_name="s", skill_directory="/tmp")
        after = datetime.now(timezone.utc)
        assert before <= result.timestamp <= after
