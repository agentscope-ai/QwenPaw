# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.skill_scanner.analyzers.pattern_analyzer.

Covers:
- SecurityRule: init, pattern compilation, matches_file_type, scan_content
- RuleLoader: load_rules from YAML, get_rule, get_rules_for_file_type/category
- PatternAnalyzer: analyze with policy filtering,
  _is_known_test_credential, _dedupe_findings
"""
# pylint: disable=redefined-outer-name,protected-access


import pytest
import yaml

from qwenpaw.security.skill_scanner.analyzers.pattern_analyzer import (
    PatternAnalyzer,
    RuleLoader,
    SecurityRule,
)
from qwenpaw.security.skill_scanner.models import (
    Finding,
    Severity,
    SkillFile,
    ThreatCategory,
)
from qwenpaw.security.skill_scanner.scan_policy import (
    CredentialPolicy,
    ScanPolicy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_rule_data():
    """Minimal valid rule data dict."""
    return {
        "id": "TEST_001",
        "category": "command_injection",
        "severity": "HIGH",
        "patterns": [r"rm\s+-rf"],
        "description": "Dangerous rm -rf command",
        "remediation": "Avoid destructive rm commands",
    }


@pytest.fixture
def full_rule_data():
    """Full rule data with all optional fields."""
    return {
        "id": "TEST_002",
        "category": "hardcoded_secrets",
        "severity": "CRITICAL",
        "patterns": [
            r"password\s*=\s*['\"][^'\"]+['\"]",
            r"api_key\s*=\s*['\"][^'\"]+['\"]",
        ],
        "exclude_patterns": [r"password\s*=\s*['\"]test['\"]"],
        "file_types": ["python", "bash"],
        "description": "Hardcoded secret detected",
        "remediation": "Use environment variables",
    }


@pytest.fixture
def rules_yaml(tmp_path, sample_rule_data, full_rule_data):
    """Create a temporary YAML rules file."""
    rules_file = tmp_path / "test_rules.yaml"
    rules_file.write_text(
        yaml.dump([sample_rule_data, full_rule_data]),
    )
    return rules_file


@pytest.fixture
def rule(sample_rule_data):
    """Create a SecurityRule from sample data."""
    return SecurityRule(sample_rule_data)


@pytest.fixture
def full_rule(full_rule_data):
    """Create a SecurityRule from full data."""
    return SecurityRule(full_rule_data)


# ---------------------------------------------------------------------------
# SecurityRule
# ---------------------------------------------------------------------------


class TestSecurityRuleInit:
    """Tests for SecurityRule.__init__."""

    def test_minimal_rule(self, sample_rule_data):
        """Minimal rule should initialize correctly."""
        r = SecurityRule(sample_rule_data)
        assert r.id == "TEST_001"
        assert r.category == ThreatCategory.COMMAND_INJECTION
        assert r.severity == Severity.HIGH
        assert r.patterns == [r"rm\s+-rf"]
        assert not r.exclude_patterns
        assert not r.file_types
        assert r.remediation == "Avoid destructive rm commands"

    def test_full_rule(self, full_rule_data):
        """Full rule with all fields should initialize correctly."""
        r = SecurityRule(full_rule_data)
        assert r.id == "TEST_002"
        assert r.category == ThreatCategory.HARDCODED_SECRETS
        assert len(r.patterns) == 2
        assert len(r.exclude_patterns) == 1
        assert r.file_types == ["python", "bash"]

    def test_compiled_patterns(self, sample_rule_data):
        """Patterns should be compiled into regex."""
        r = SecurityRule(sample_rule_data)
        assert len(r.compiled_patterns) == 1
        assert r.compiled_patterns[0].pattern == r"rm\s+-rf"

    def test_bad_regex_skipped(self):
        """Bad regex patterns should be skipped with a warning."""
        data = {
            "id": "BAD_RE",
            "category": "command_injection",
            "severity": "LOW",
            "patterns": [r"valid\d+", r"[invalid", r"also_valid\s+"],
            "description": "test",
        }
        r = SecurityRule(data)
        assert len(r.compiled_patterns) == 2  # bad one skipped
        assert len(r.patterns) == 3  # raw patterns still stored

    def test_exclude_patterns_compiled(self, full_rule_data):
        """Exclude patterns should be compiled."""
        r = SecurityRule(full_rule_data)
        assert len(r.compiled_exclude_patterns) == 1


class TestSecurityRuleMatchesFileType:
    """Tests for SecurityRule.matches_file_type."""

    def test_matches_all_when_no_file_types(self, rule):
        """Rule with no file_types should match all."""
        assert rule.matches_file_type("python") is True
        assert rule.matches_file_type("bash") is True
        assert rule.matches_file_type("markdown") is True

    def test_matches_specific_file_types(self, full_rule):
        """Rule with file_types should only match those types."""
        assert full_rule.matches_file_type("python") is True
        assert full_rule.matches_file_type("bash") is True
        assert full_rule.matches_file_type("markdown") is False


class TestSecurityRuleScanContent:
    """Tests for SecurityRule.scan_content."""

    def test_matching_content(self, rule):
        """Should find matches in matching content."""
        matches = rule.scan_content("rm -rf /", file_path="test.sh")
        assert len(matches) >= 1
        assert matches[0]["matched_text"] == "rm -rf"
        assert matches[0]["line_number"] == 1

    def test_no_match(self, rule):
        """Should return empty list for non-matching content."""
        matches = rule.scan_content("echo hello")
        assert len(matches) == 0

    def test_multiline_content(self, sample_rule_data):
        """Should match across multiple lines."""
        r = SecurityRule(sample_rule_data)
        content = "echo hello\ndo something\nrm -rf /tmp\n"
        matches = r.scan_content(content, file_path="test.sh")
        assert len(matches) >= 1

    def test_exclude_pattern_filters(self, full_rule_data):
        """Exclude patterns should filter out matches."""
        r = SecurityRule(full_rule_data)
        # This should match the pattern but be excluded
        content = "password = 'test'"
        matches = r.scan_content(content, file_path="test.py")
        assert len(matches) == 0

    def test_exclude_pattern_does_not_filter_non_excluded(
        self,
        full_rule_data,
    ):
        """Non-excluded matches should still be found."""
        r = SecurityRule(full_rule_data)
        content = "password = 'real_secret_value'"
        matches = r.scan_content(content, file_path="test.py")
        assert len(matches) >= 1

    def test_line_number_correct(self, rule):
        """Line numbers should be 1-based."""
        content = "line1\nline2\nrm -rf /\nline4"
        matches = rule.scan_content(content)
        assert len(matches) >= 1
        assert matches[0]["line_number"] == 3


# ---------------------------------------------------------------------------
# RuleLoader
# ---------------------------------------------------------------------------


class TestRuleLoader:
    """Tests for RuleLoader."""

    def test_load_rules_from_yaml(self, rules_yaml):
        """Should load rules from a YAML file."""
        loader = RuleLoader(rules_yaml)
        rules = loader.load_rules()
        assert len(rules) == 2
        assert rules[0].id == "TEST_001"
        assert rules[1].id == "TEST_002"

    def test_load_rules_from_directory(self, tmp_path, sample_rule_data):
        """Should load rules from all YAML files in a directory."""
        (tmp_path / "rules1.yaml").write_text(yaml.dump([sample_rule_data]))
        (tmp_path / "rules2.yaml").write_text(yaml.dump([sample_rule_data]))
        loader = RuleLoader(tmp_path)
        rules = loader.load_rules()
        assert len(rules) == 2

    def test_load_rules_invalid_yaml(self, tmp_path):
        """Should raise RuntimeError for invalid YAML content."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("not a list")
        loader = RuleLoader(bad_file)
        with pytest.raises(RuntimeError, match="Expected list"):
            loader.load_rules()

    def test_get_rule(self, rules_yaml):
        """get_rule should return rule by ID."""
        loader = RuleLoader(rules_yaml)
        loader.load_rules()
        assert loader.get_rule("TEST_001") is not None
        assert loader.get_rule("NONEXISTENT") is None

    def test_get_rules_for_file_type(self, rules_yaml):
        """Should filter rules by file type."""
        loader = RuleLoader(rules_yaml)
        loader.load_rules()
        python_rules = loader.get_rules_for_file_type("python")
        # TEST_001 has no file_types (matches all), TEST_002 has python
        assert len(python_rules) == 2

        md_rules = loader.get_rules_for_file_type("markdown")
        # Only TEST_001 matches (no file_types restriction)
        assert len(md_rules) == 1

    def test_get_rules_for_category(self, rules_yaml):
        """Should filter rules by category."""
        loader = RuleLoader(rules_yaml)
        loader.load_rules()
        ci_rules = loader.get_rules_for_category(
            ThreatCategory.COMMAND_INJECTION,
        )
        assert len(ci_rules) == 1
        assert ci_rules[0].id == "TEST_001"


# ---------------------------------------------------------------------------
# PatternAnalyzer
# ---------------------------------------------------------------------------


class TestPatternAnalyzer:
    """Tests for PatternAnalyzer."""

    def test_init_with_default_rules(self):
        """PatternAnalyzer should load default rules."""
        analyzer = PatternAnalyzer()
        assert len(analyzer._rules) > 0

    def test_init_with_custom_rules(self, rules_yaml):
        """PatternAnalyzer should load custom rules from path."""
        analyzer = PatternAnalyzer(rules_path=rules_yaml)
        assert len(analyzer._rules) == 2

    def test_analyze_finds_match(self, rules_yaml, tmp_path):
        """analyze should return findings for matching content."""
        analyzer = PatternAnalyzer(rules_path=rules_yaml)
        (tmp_path / "test.sh").write_text("rm -rf /tmp")
        sf = SkillFile.from_path(tmp_path / "test.sh", tmp_path)
        findings = analyzer.analyze(tmp_path, [sf])
        assert len(findings) >= 1
        assert findings[0].rule_id == "TEST_001"

    def test_analyze_no_match(self, rules_yaml, tmp_path):
        """analyze should return empty list for safe content."""
        analyzer = PatternAnalyzer(rules_path=rules_yaml)
        (tmp_path / "safe.py").write_text("print('hello')")
        sf = SkillFile.from_path(tmp_path / "safe.py", tmp_path)
        findings = analyzer.analyze(tmp_path, [sf])
        assert len(findings) == 0

    def test_analyze_file_type_filtering(self, rules_yaml, tmp_path):
        """Rules with file_types should only fire on matching files."""
        analyzer = PatternAnalyzer(rules_path=rules_yaml)
        # TEST_002 has file_types: [python, bash]
        # It should NOT fire on markdown files
        (tmp_path / "doc.md").write_text("password = 'secret123'")
        sf = SkillFile.from_path(tmp_path / "doc.md", tmp_path)
        findings = analyzer.analyze(tmp_path, [sf])
        # Only TEST_001 (no file_type restriction) could match,
        # but it looks for "rm -rf" which isn't in the content
        for f in findings:
            assert f.rule_id != "TEST_002"

    def test_analyze_skips_disabled_rules(self, rules_yaml, tmp_path):
        """Disabled rules should be skipped."""
        policy = ScanPolicy(disabled_rules={"TEST_001"})
        analyzer = PatternAnalyzer(rules_path=rules_yaml, policy=policy)
        (tmp_path / "test.sh").write_text("rm -rf /tmp")
        sf = SkillFile.from_path(tmp_path / "test.sh", tmp_path)
        findings = analyzer.analyze(tmp_path, [sf])
        rule_ids = {f.rule_id for f in findings}
        assert "TEST_001" not in rule_ids

    def test_dedupe_findings(self):
        """_dedupe_findings should remove exact duplicates."""
        f1 = Finding(
            id="R1:f.py:1",
            rule_id="R1",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="t",
            description="d",
            file_path="f.py",
            line_number=1,
        )
        f2 = Finding(
            id="R1:f.py:1",
            rule_id="R1",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="t",
            description="d",
            file_path="f.py",
            line_number=1,
        )
        f3 = Finding(
            id="R2:f.py:2",
            rule_id="R2",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.LOW,
            title="t2",
            description="d2",
            file_path="f.py",
            line_number=2,
        )
        result = PatternAnalyzer._dedupe_findings([f1, f2, f3])
        assert len(result) == 2

    def test_is_known_test_credential(self, rules_yaml):
        """_is_known_test_credential should suppress known test creds."""
        policy = ScanPolicy(
            credentials=CredentialPolicy(
                known_test_values={"sk-test-123"},
                placeholder_markers={"<YOUR_API_KEY>"},
            ),
        )
        analyzer = PatternAnalyzer(rules_path=rules_yaml, policy=policy)
        finding = Finding(
            id="R1:f.py:1",
            rule_id="R1",
            category=ThreatCategory.HARDCODED_SECRETS,
            severity=Severity.HIGH,
            title="t",
            description="d",
            snippet="api_key = sk-test-123",
        )
        assert analyzer._is_known_test_credential(finding) is True

    def test_is_not_known_test_credential(self, rules_yaml):
        """Non-credential findings should not be suppressed."""
        analyzer = PatternAnalyzer(rules_path=rules_yaml)
        finding = Finding(
            id="R1:f.py:1",
            rule_id="R1",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="t",
            description="d",
            snippet="rm -rf /",
        )
        assert analyzer._is_known_test_credential(finding) is False
