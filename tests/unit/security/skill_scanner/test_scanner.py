# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.skill_scanner.scanner.

Covers:
- SkillScanner initialization and defaults
- scan_skill with valid/invalid directories
- _discover_files (symlink skip, extension skip, size limit, file count limit)
- register_analyzer
- Analyzer failure handling
- Deduplication of findings
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from unittest.mock import MagicMock

import pytest

from qwenpaw.security.skill_scanner.models import (
    Finding,
    ScanResult,
    Severity,
    ThreatCategory,
)
from qwenpaw.security.skill_scanner.scanner import SkillScanner


@pytest.fixture
def scanner(default_policy):
    """Create a SkillScanner with no analyzers for unit testing."""
    return SkillScanner(analyzers=[], policy=default_policy)


@pytest.fixture
def scanner_with_mock_analyzer(default_policy, mock_analyzer):
    """Create a SkillScanner with a mock analyzer."""
    return SkillScanner(
        analyzers=[mock_analyzer],
        policy=default_policy,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestSkillScannerInit:
    """Tests for SkillScanner initialization."""

    def test_init_with_defaults(self):
        """Default scanner should have PatternAnalyzer and default policy."""
        scanner = SkillScanner()
        assert scanner.policy is not None
        assert len(scanner._analyzers) >= 1

    def test_init_with_empty_analyzers(self, default_policy):
        """Scanner with empty analyzers list should have no analyzers."""
        scanner = SkillScanner(analyzers=[], policy=default_policy)
        assert not scanner._analyzers

    def test_init_with_custom_analyzers(self, default_policy, mock_analyzer):
        """Scanner with custom analyzers should use them."""
        scanner = SkillScanner(
            analyzers=[mock_analyzer],
            policy=default_policy,
        )
        assert len(scanner._analyzers) == 1
        assert scanner._analyzers[0] is mock_analyzer

    def test_init_max_files_from_policy(self, default_policy):
        """max_files should come from policy when not explicitly set."""
        scanner = SkillScanner(analyzers=[], policy=default_policy)
        assert scanner._max_files == default_policy.file_limits.max_file_count

    def test_init_max_files_explicit(self, default_policy):
        """Explicit max_files should override policy."""
        scanner = SkillScanner(
            analyzers=[],
            policy=default_policy,
            max_files=42,
        )
        assert scanner._max_files == 42

    def test_init_skip_extensions_merged(self, default_policy):
        """Custom skip_extensions should be merged with policy defaults."""
        scanner = SkillScanner(
            analyzers=[],
            policy=default_policy,
            skip_extensions={".custom"},
        )
        assert ".custom" in scanner._skip_ext

    def test_policy_property(self, default_policy):
        """policy property should return the active policy."""
        scanner = SkillScanner(analyzers=[], policy=default_policy)
        assert scanner.policy is default_policy


# ---------------------------------------------------------------------------
# scan_skill
# ---------------------------------------------------------------------------


class TestSkillScannerScanSkill:
    """Tests for SkillScanner.scan_skill."""

    def test_scan_nonexistent_directory(self, scanner):
        """Scanning a nonexistent directory should return empty result."""
        result = scanner.scan_skill("/nonexistent/path")
        assert isinstance(result, ScanResult)
        assert not result.findings
        assert result.skill_name == "path"

    def test_scan_empty_directory(self, scanner, tmp_path):
        """Scanning an empty directory should return empty findings."""
        result = scanner.scan_skill(str(tmp_path))
        assert not result.findings
        assert result.is_safe is True

    def test_scan_with_analyzer_findings(
        self,
        scanner_with_mock_analyzer,
        mock_analyzer,
        tmp_path,
    ):
        """Scanner should aggregate findings from analyzers."""
        (tmp_path / "test.py").write_text("print('hi')")
        finding = Finding(
            id="R001:test.py:1",
            rule_id="R001",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="Test finding",
            description="test",
            file_path="test.py",
            line_number=1,
            snippet="print",
            analyzer="mock",
        )
        mock_analyzer.analyze.return_value = [finding]
        result = scanner_with_mock_analyzer.scan_skill(str(tmp_path))
        assert len(result.findings) == 1
        assert result.is_safe is False
        assert "mock_analyzer" in result.analyzers_used

    def test_scan_analyzer_failure(self, default_policy, tmp_path):
        """Analyzer exceptions should be caught and recorded."""
        failing = MagicMock()
        failing.get_name.return_value = "failing_analyzer"
        failing.analyze.side_effect = RuntimeError("boom")
        scanner = SkillScanner(
            analyzers=[failing],
            policy=default_policy,
        )
        (tmp_path / "test.py").write_text("x")
        result = scanner.scan_skill(str(tmp_path))
        assert not result.findings
        assert len(result.analyzers_failed) == 1
        assert result.analyzers_failed[0]["analyzer"] == "failing_analyzer"

    def test_scan_skill_name_from_directory(self, scanner, tmp_path):
        """skill_name should default to directory name."""
        result = scanner.scan_skill(str(tmp_path))
        assert result.skill_name == tmp_path.name

    def test_scan_skill_name_explicit(self, scanner, tmp_path):
        """Explicit skill_name should be used."""
        result = scanner.scan_skill(str(tmp_path), skill_name="my-skill")
        assert result.skill_name == "my-skill"

    def test_scan_duration_recorded(
        self,
        scanner_with_mock_analyzer,
        tmp_path,
    ):
        """scan_duration_seconds should be recorded."""
        (tmp_path / "test.py").write_text("x")
        result = scanner_with_mock_analyzer.scan_skill(str(tmp_path))
        assert result.scan_duration_seconds >= 0


# ---------------------------------------------------------------------------
# register_analyzer
# ---------------------------------------------------------------------------


class TestSkillScannerRegisterAnalyzer:
    """Tests for register_analyzer."""

    def test_register_adds_analyzer(self, scanner, mock_analyzer):
        """register_analyzer should add to the analyzer list."""
        scanner.register_analyzer(mock_analyzer)
        assert mock_analyzer in scanner._analyzers


# ---------------------------------------------------------------------------
# _discover_files
# ---------------------------------------------------------------------------


class TestSkillScannerDiscoverFiles:
    """Tests for _discover_files."""

    def test_discovers_python_files(self, scanner, tmp_path):
        """Should discover .py files."""
        (tmp_path / "hello.py").write_text("print('hi')")
        files = scanner._discover_files(tmp_path)
        assert len(files) == 1
        assert files[0].file_type == "python"

    def test_skips_skip_extensions(self, scanner, tmp_path):
        """Should skip files with extensions in skip set."""
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "code.py").write_text("x")
        files = scanner._discover_files(tmp_path)
        assert len(files) == 1
        assert files[0].relative_path == "code.py"

    def test_skips_symlinks(self, scanner, tmp_path):
        """Should skip symlinks to prevent path traversal."""
        target = tmp_path / "real.txt"
        target.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        files = scanner._discover_files(tmp_path)
        # Only the real file should appear
        names = [f.relative_path for f in files]
        assert "real.txt" in names
        assert "link.txt" not in names

    def test_respects_max_file_size(self, default_policy, tmp_path):
        """Should skip files exceeding max_file_size."""
        scanner = SkillScanner(
            analyzers=[],
            policy=default_policy,
            max_file_size=10,
        )
        big = tmp_path / "big.py"
        big.write_text("x" * 100)
        small = tmp_path / "small.py"
        small.write_text("x")
        files = scanner._discover_files(tmp_path)
        assert len(files) == 1
        assert files[0].relative_path == "small.py"

    def test_respects_max_files(self, default_policy, tmp_path):
        """Should stop after max_files files."""
        scanner = SkillScanner(
            analyzers=[],
            policy=default_policy,
            max_files=2,
        )
        for i in range(5):
            (tmp_path / f"file{i}.py").write_text(f"x{i}")
        files = scanner._discover_files(tmp_path)
        assert len(files) <= 2

    def test_skips_directories(self, scanner, tmp_path):
        """Should skip directories, only return files."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "code.py").write_text("x")
        files = scanner._discover_files(tmp_path)
        assert len(files) == 1

    def test_nested_files_discovered(self, scanner, tmp_path):
        """Should discover files in subdirectories."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("x")
        (tmp_path / "top.py").write_text("x")
        files = scanner._discover_files(tmp_path)
        assert len(files) == 2
        paths = {f.relative_path.replace("\\", "/") for f in files}
        assert "top.py" in paths
        assert "sub/nested.py" in paths
