# -*- coding: utf-8 -*-
"""Shared fixtures for skill_scanner tests."""
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from unittest.mock import MagicMock

import pytest

from qwenpaw.security.skill_scanner.models import (
    Finding,
    ScanResult,
    Severity,
    ThreatCategory,
)
from qwenpaw.security.skill_scanner.scan_policy import ScanPolicy


@pytest.fixture
def default_policy():
    """Return a default ScanPolicy (no file I/O if default YAML missing)."""
    return ScanPolicy()


@pytest.fixture
def sample_finding():
    """Create a sample Finding for reuse."""
    return Finding(
        id="test-rule:file.py:1",
        rule_id="test-rule",
        category=ThreatCategory.COMMAND_INJECTION,
        severity=Severity.HIGH,
        title="Test finding",
        description="A test finding for unit tests",
        file_path="file.py",
        line_number=1,
        snippet="rm -rf /",
        remediation="Do not use dangerous commands",
        analyzer="pattern",
    )


@pytest.fixture
def sample_scan_result(sample_finding):
    """Create a sample ScanResult with one finding."""
    return ScanResult(
        skill_name="test-skill",
        skill_directory="/tmp/test-skill",
        findings=[sample_finding],
        scan_duration_seconds=0.1,
        analyzers_used=["pattern"],
    )


@pytest.fixture
def safe_scan_result():
    """Create a ScanResult with no findings (safe)."""
    return ScanResult(
        skill_name="safe-skill",
        skill_directory="/tmp/safe-skill",
        findings=[],
        scan_duration_seconds=0.05,
        analyzers_used=["pattern"],
    )


@pytest.fixture
def skill_dir(tmp_path):
    """Create a minimal skill directory with sample files."""
    skill = tmp_path / "test-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Test Skill\nA test skill.")
    (skill / "hello.py").write_text('print("hello")\n')
    return skill


@pytest.fixture
def mock_analyzer():
    """Create a mock BaseAnalyzer."""
    analyzer = MagicMock()
    analyzer.get_name.return_value = "mock_analyzer"
    analyzer.analyze.return_value = []
    return analyzer
