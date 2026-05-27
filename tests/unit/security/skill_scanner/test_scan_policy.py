# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.skill_scanner.scan_policy.

Covers:
- _safe_compile regex helper
- Data class defaults and construction
- ScanPolicy._from_dict / _to_dict roundtrip
- ScanPolicy._deep_merge
- ScanPolicy.is_doc_path
- ScanPolicy.get_severity_override / is_rule_disabled
- ScanPolicy.from_yaml / to_yaml
- ScanPolicy.preset_names
"""
# pylint: disable=redefined-outer-name,unused-argument,protected-access
import re

import pytest

from qwenpaw.security.skill_scanner.scan_policy import (
    AnalysisThresholdsPolicy,
    CredentialPolicy,
    FileClassificationPolicy,
    FileLimitsPolicy,
    HiddenFilePolicy,
    RuleScopingPolicy,
    ScanPolicy,
    SeverityOverride,
    _safe_compile,
)


# ---------------------------------------------------------------------------
# _safe_compile
# ---------------------------------------------------------------------------


class TestSafeCompile:
    """Tests for _safe_compile helper."""

    def test_valid_pattern(self):
        """Valid regex should compile successfully."""
        result = _safe_compile(r"\d+")
        assert result is not None
        assert result.search("123")

    def test_invalid_pattern_returns_none(self):
        """Invalid regex should return None, not raise."""
        result = _safe_compile(r"[invalid")
        assert result is None

    def test_too_long_pattern_returns_none(self):
        """Pattern exceeding max_length should return None."""
        long_pattern = "a" * 1001
        result = _safe_compile(long_pattern, max_length=1000)
        assert result is None

    def test_custom_max_length(self):
        """Custom max_length should be respected."""
        pattern = "a" * 50
        result = _safe_compile(pattern, max_length=49)
        assert result is None
        result = _safe_compile(pattern, max_length=50)
        assert result is not None

    def test_with_flags(self):
        """Flags should be passed through."""
        result = _safe_compile(r"hello", re.IGNORECASE)
        assert result is not None
        assert result.search("HELLO")


# ---------------------------------------------------------------------------
# Data class defaults
# ---------------------------------------------------------------------------


class TestHiddenFilePolicy:
    """Tests for HiddenFilePolicy defaults."""

    def test_defaults(self):
        p = HiddenFilePolicy()
        assert p.benign_dotfiles == set()
        assert p.benign_dotdirs == set()

    def test_custom(self):
        p = HiddenFilePolicy(
            benign_dotfiles={".gitignore"},
            benign_dotdirs={".github"},
        )
        assert ".gitignore" in p.benign_dotfiles
        assert ".github" in p.benign_dotdirs


class TestRuleScopingPolicy:
    """Tests for RuleScopingPolicy defaults."""

    def test_defaults(self):
        p = RuleScopingPolicy()
        assert p.skillmd_and_scripts_only == set()
        assert p.skip_in_docs == set()
        assert p.code_only == set()
        assert p.doc_path_indicators == set()
        assert not p.doc_filename_patterns
        assert p.dedupe_duplicate_findings is True


class TestCredentialPolicy:
    """Tests for CredentialPolicy defaults."""

    def test_defaults(self):
        p = CredentialPolicy()
        assert p.known_test_values == set()
        assert p.placeholder_markers == set()


class TestFileLimitsPolicy:
    """Tests for FileLimitsPolicy defaults."""

    def test_defaults(self):
        p = FileLimitsPolicy()
        assert p.max_file_count == 100
        assert p.max_file_size_bytes == 5_242_880
        assert p.max_reference_depth == 5


class TestAnalysisThresholdsPolicy:
    """Tests for AnalysisThresholdsPolicy defaults."""

    def test_defaults(self):
        p = AnalysisThresholdsPolicy()
        assert p.min_confidence_pct == 80
        assert p.max_regex_pattern_length == 1000


class TestSeverityOverride:
    """Tests for SeverityOverride dataclass."""

    def test_creation(self):
        o = SeverityOverride(rule_id="R001", severity="LOW", reason="test")
        assert o.rule_id == "R001"
        assert o.severity == "LOW"
        assert o.reason == "test"

    def test_default_reason(self):
        o = SeverityOverride(rule_id="R002", severity="INFO")
        assert o.reason == ""


# ---------------------------------------------------------------------------
# ScanPolicy construction and helpers
# ---------------------------------------------------------------------------


class TestScanPolicyConstruction:
    """Tests for ScanPolicy default construction."""

    def test_default_policy(self):
        p = ScanPolicy()
        assert p.policy_name == "default"
        assert p.policy_version == "1.0"
        assert p.preset_base == "balanced"
        assert isinstance(p.hidden_files, HiddenFilePolicy)
        assert isinstance(p.rule_scoping, RuleScopingPolicy)
        assert isinstance(p.credentials, CredentialPolicy)
        assert isinstance(p.file_classification, FileClassificationPolicy)
        assert isinstance(p.file_limits, FileLimitsPolicy)
        assert isinstance(p.analysis_thresholds, AnalysisThresholdsPolicy)
        assert not p.severity_overrides
        assert p.disabled_rules == set()


class TestScanPolicySeverityOverride:
    """Tests for get_severity_override."""

    def test_returns_override_when_present(self):
        p = ScanPolicy(
            severity_overrides=[
                SeverityOverride(rule_id="R001", severity="LOW"),
            ],
        )
        assert p.get_severity_override("R001") == "LOW"

    def test_returns_none_when_absent(self):
        p = ScanPolicy()
        assert p.get_severity_override("R001") is None

    def test_returns_first_match(self):
        p = ScanPolicy(
            severity_overrides=[
                SeverityOverride(rule_id="R001", severity="LOW"),
                SeverityOverride(rule_id="R001", severity="INFO"),
            ],
        )
        assert p.get_severity_override("R001") == "LOW"


class TestScanPolicyIsRuleDisabled:
    """Tests for is_rule_disabled."""

    def test_disabled_rule(self):
        p = ScanPolicy(disabled_rules={"R001", "R002"})
        assert p.is_rule_disabled("R001") is True

    def test_enabled_rule(self):
        p = ScanPolicy(disabled_rules={"R001"})
        assert p.is_rule_disabled("R003") is False


class TestScanPolicyIsDocPath:
    """Tests for is_doc_path."""

    def test_doc_path_by_indicator(self):
        p = ScanPolicy(
            rule_scoping=RuleScopingPolicy(
                doc_path_indicators={"docs", "examples"},
            ),
        )
        assert p.is_doc_path("docs/guide.md") is True
        assert p.is_doc_path("examples/demo.py") is True
        assert p.is_doc_path("src/main.py") is False

    def test_doc_path_by_filename_pattern(self):
        p = ScanPolicy(
            rule_scoping=RuleScopingPolicy(
                doc_filename_patterns=["readme", "tutorial"],
            ),
        )
        assert p.is_doc_path("readme.md") is True
        assert p.is_doc_path("TUTORIAL.md") is True  # case insensitive
        assert p.is_doc_path("main.py") is False

    def test_doc_path_no_match(self):
        p = ScanPolicy()
        assert p.is_doc_path("src/app.py") is False


# ---------------------------------------------------------------------------
# _from_dict / _to_dict roundtrip
# ---------------------------------------------------------------------------


class TestScanPolicyFromDict:
    """Tests for _from_dict parsing."""

    def test_minimal_dict(self):
        d = {}
        p = ScanPolicy._from_dict(d)
        assert p.policy_name == "default"
        assert p.policy_version == "1.0"

    def test_full_dict(self):
        d = {
            "policy_name": "custom",
            "policy_version": "2.0",
            "hidden_files": {
                "benign_dotfiles": [".gitignore"],
                "benign_dotdirs": [".github"],
            },
            "rule_scoping": {
                "skillmd_and_scripts_only": ["R001"],
                "skip_in_docs": ["R002"],
                "code_only": ["R003"],
                "doc_path_indicators": ["docs"],
                "doc_filename_patterns": ["readme"],
                "dedupe_duplicate_findings": False,
            },
            "credentials": {
                "known_test_values": ["sk-test"],
                "placeholder_markers": ["<YOUR_KEY>"],
            },
            "file_classification": {
                "inert_extensions": [".png"],
                "structured_extensions": [".svg"],
                "archive_extensions": [".zip"],
                "code_extensions": [".py"],
            },
            "file_limits": {
                "max_file_count": 200,
                "max_file_size_bytes": 10_485_760,
            },
            "severity_overrides": [
                {"rule_id": "R001", "severity": "LOW", "reason": "safe"},
            ],
            "disabled_rules": ["R004"],
        }
        p = ScanPolicy._from_dict(d)
        assert p.policy_name == "custom"
        assert p.hidden_files.benign_dotfiles == {".gitignore"}
        assert p.rule_scoping.dedupe_duplicate_findings is False
        assert p.credentials.known_test_values == {"sk-test"}
        assert p.file_limits.max_file_count == 200
        assert len(p.severity_overrides) == 1
        assert p.severity_overrides[0].rule_id == "R001"
        assert "R004" in p.disabled_rules


class TestScanPolicyToDict:
    """Tests for _to_dict serialization."""

    def test_roundtrip(self):
        p = ScanPolicy(
            policy_name="test",
            hidden_files=HiddenFilePolicy(
                benign_dotfiles={".env"},
            ),
            severity_overrides=[
                SeverityOverride(rule_id="R1", severity="LOW"),
            ],
            disabled_rules={"R2"},
        )
        d = p._to_dict()
        assert d["policy_name"] == "test"
        assert ".env" in d["hidden_files"]["benign_dotfiles"]
        assert len(d["severity_overrides"]) == 1
        assert "R2" in d["disabled_rules"]

    def test_from_dict_to_dict_roundtrip(self):
        """_from_dict -> _to_dict should preserve key data."""
        original = {
            "policy_name": "roundtrip",
            "hidden_files": {"benign_dotfiles": [".a"]},
            "disabled_rules": ["R99"],
        }
        p = ScanPolicy._from_dict(original)
        result = p._to_dict()
        assert result["policy_name"] == "roundtrip"
        assert ".a" in result["hidden_files"]["benign_dotfiles"]
        assert "R99" in result["disabled_rules"]


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Tests for _deep_merge static method."""

    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = ScanPolicy._deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        result = ScanPolicy._deep_merge(base, override)
        assert result["a"] == {"x": 1, "y": 3, "z": 4}

    def test_list_replaced_not_merged(self):
        """Lists in override should replace, not extend, base lists."""
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = ScanPolicy._deep_merge(base, override)
        assert result["items"] == [4, 5]

    def test_base_unchanged(self):
        """_deep_merge should not mutate the base dict."""
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        ScanPolicy._deep_merge(base, override)
        assert base == {"a": {"x": 1}}


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------


class TestScanPolicyYamlIO:
    """Tests for from_yaml / to_yaml."""

    def test_from_yaml_file_not_found(self):
        """from_yaml should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError, match="not found"):
            ScanPolicy.from_yaml("/nonexistent/policy.yaml")

    def test_from_yaml_and_to_yaml_roundtrip(self, tmp_path):
        """Write a policy to YAML and read it back."""
        p = ScanPolicy(
            policy_name="test-policy",
            hidden_files=HiddenFilePolicy(
                benign_dotfiles={".gitignore"},
            ),
            disabled_rules={"R001"},
        )
        path = tmp_path / "policy.yaml"
        p.to_yaml(path)
        assert path.exists()

        loaded = ScanPolicy.from_yaml(path)
        assert loaded.policy_name == "test-policy"
        assert ".gitignore" in loaded.hidden_files.benign_dotfiles
        assert "R001" in loaded.disabled_rules

    def test_from_yaml_empty_file(self, tmp_path):
        """Empty YAML file should produce default policy."""
        path = tmp_path / "empty.yaml"
        path.write_text("")
        p = ScanPolicy.from_yaml(path)
        assert p.policy_name == "default"

    def test_to_yaml_includes_header(self, tmp_path):
        """to_yaml should include a header comment."""
        p = ScanPolicy()
        path = tmp_path / "out.yaml"
        p.to_yaml(path)
        content = path.read_text()
        assert "QwenPaw" in content or "Scan Policy" in content


class TestScanPolicyPresets:
    """Tests for preset_names and from_preset."""

    def test_preset_names_returns_list(self):
        names = ScanPolicy.preset_names()
        assert isinstance(names, list)

    def test_from_preset_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            ScanPolicy.from_preset("nonexistent")
