# -*- coding: utf-8 -*-
"""Contract tests for BaseToolGuardian subclasses.

Verifies the BaseToolGuardian contract:
- guard() returns list[GuardFinding]
- Unknown tool names don't cause crashes
- Empty params are handled gracefully
- Finding fields are populated correctly
"""
# pylint: disable=redefined-outer-name,unused-argument
# pylint: disable=protected-access,abstract-class-instantiated
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.security.tool_guard.guardians import BaseToolGuardian
from qwenpaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
)
from qwenpaw.security.tool_guard.guardians.rule_guardian import (
    RuleBasedToolGuardian,
)
from qwenpaw.security.tool_guard.models import GuardFinding


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_guardian():
    """Create a disabled FilePathToolGuardian for contract testing."""
    with patch(
        "qwenpaw.security.tool_guard.guardians.file_guardian"
        "._is_file_guard_enabled",
        return_value=False,
    ), patch(
        "qwenpaw.security.tool_guard.guardians.file_guardian"
        "._load_sensitive_files_from_config",
        return_value=set(),
    ), patch(
        "qwenpaw.security.tool_guard.guardians.file_guardian"
        "._workspace_root",
        return_value=Path("/tmp"),
    ):
        return FilePathToolGuardian()


@pytest.fixture
def rule_guardian():
    """Create a RuleBasedToolGuardian with no rules for contract testing."""
    with patch(
        "qwenpaw.security.tool_guard.guardians.rule_guardian"
        "._load_config_rules",
        return_value=([], set()),
    ), patch(
        "qwenpaw.security.tool_guard.guardians.rule_guardian"
        "._get_workspace_root",
        return_value=Path("/tmp"),
    ):
        return RuleBasedToolGuardian()


# ---------------------------------------------------------------------------
# Contract: guard() returns list[GuardFinding]
# ---------------------------------------------------------------------------


class TestGuardReturnsList:
    """guard() must always return a list of GuardFinding objects."""

    def test_file_guardian_returns_list(self, file_guardian):
        """FilePathToolGuardian.guard() returns list."""
        result = file_guardian.guard("read_file", {"path": "/tmp/test.txt"})
        assert isinstance(result, list)

    def test_rule_guardian_returns_list(self, rule_guardian):
        """RuleBasedToolGuardian.guard() returns list."""
        result = rule_guardian.guard(
            "execute_shell_command",
            {"command": "echo hello"},
        )
        assert isinstance(result, list)

    def test_file_guardian_findings_are_guard_finding(self, file_guardian):
        """All items in the result must be GuardFinding instances."""
        with patch(
            "qwenpaw.security.tool_guard.guardians.file_guardian"
            "._is_file_guard_enabled",
            return_value=True,
        ), patch(
            "qwenpaw.security.tool_guard.guardians.file_guardian"
            "._load_sensitive_files_from_config",
            return_value={"/etc/passwd"},
        ):
            guardian = FilePathToolGuardian()
            result = guardian.guard("read_file", {"path": "/etc/passwd"})
            for item in result:
                assert isinstance(item, GuardFinding)

    def test_rule_guardian_findings_are_guard_finding(self, rule_guardian):
        """All items in the result must be GuardFinding instances."""
        result = rule_guardian.guard(
            "execute_shell_command",
            {"command": "echo hello"},
        )
        for item in result:
            assert isinstance(item, GuardFinding)


# ---------------------------------------------------------------------------
# Contract: unknown tool names don't crash
# ---------------------------------------------------------------------------


class TestUnknownToolNoCrash:
    """guard() must not crash on unknown tool names."""

    def test_file_guardian_unknown_tool(self, file_guardian):
        """FilePathToolGuardian handles unknown tool gracefully."""
        result = file_guardian.guard(
            "nonexistent_tool_xyz",
            {"data": "test"},
        )
        assert isinstance(result, list)

    def test_rule_guardian_unknown_tool(self, rule_guardian):
        """RuleBasedToolGuardian handles unknown tool gracefully."""
        result = rule_guardian.guard(
            "nonexistent_tool_xyz",
            {"data": "test"},
        )
        assert isinstance(result, list)

    def test_file_guardian_empty_tool_name(self, file_guardian):
        """FilePathToolGuardian handles empty tool name."""
        result = file_guardian.guard("", {"path": "/tmp/test.txt"})
        assert isinstance(result, list)

    def test_rule_guardian_empty_tool_name(self, rule_guardian):
        """RuleBasedToolGuardian handles empty tool name."""
        result = rule_guardian.guard("", {"command": "echo hello"})
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Contract: empty params are handled gracefully
# ---------------------------------------------------------------------------


class TestEmptyParamsNoCrash:
    """guard() must not crash on empty or missing params."""

    def test_file_guardian_empty_params(self, file_guardian):
        """FilePathToolGuardian handles empty params."""
        result = file_guardian.guard("read_file", {})
        assert isinstance(result, list)

    def test_rule_guardian_empty_params(self, rule_guardian):
        """RuleBasedToolGuardian handles empty params."""
        result = rule_guardian.guard("execute_shell_command", {})
        assert isinstance(result, list)

    def test_file_guardian_none_param_value(self, file_guardian):
        """FilePathToolGuardian handles None param values."""
        result = file_guardian.guard("read_file", {"path": None})
        assert isinstance(result, list)

    def test_rule_guardian_none_param_value(self, rule_guardian):
        """RuleBasedToolGuardian handles None param values."""
        result = rule_guardian.guard(
            "execute_shell_command",
            {"command": None},
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Contract: Finding fields are populated
# ---------------------------------------------------------------------------


class TestFindingFieldsPopulated:
    """GuardFindings must have required fields populated."""

    def test_file_guardian_finding_fields(self):
        """FilePathToolGuardian findings have required fields."""
        with patch(
            "qwenpaw.security.tool_guard.guardians.file_guardian"
            "._is_file_guard_enabled",
            return_value=True,
        ), patch(
            "qwenpaw.security.tool_guard.guardians.file_guardian"
            "._load_sensitive_files_from_config",
            return_value={"/etc/passwd"},
        ), patch(
            "qwenpaw.security.tool_guard.guardians.file_guardian"
            "._workspace_root",
            return_value=Path("/tmp"),
        ):
            guardian = FilePathToolGuardian()
            result = guardian.guard("read_file", {"path": "/etc/passwd"})
            if result:
                f = result[0]
                assert f.rule_id is not None
                assert f.category is not None
                assert f.severity is not None
                assert f.title is not None
                assert f.description is not None
                assert f.tool_name == "read_file"

    def test_rule_guardian_finding_fields(self, tmp_path):
        """RuleBasedToolGuardian findings have required fields."""
        import yaml

        rule_data = {
            "id": "CONTRACT_TEST",
            "category": "command_injection",
            "severity": "HIGH",
            "tool": "execute_shell_command",
            "params": ["command"],
            "patterns": [r"rm\s+-rf"],
            "description": "Dangerous rm",
        }
        (tmp_path / "rules.yaml").write_text(yaml.dump([rule_data]))
        with patch(
            "qwenpaw.security.tool_guard.guardians.rule_guardian"
            "._load_config_rules",
            return_value=([], set()),
        ), patch(
            "qwenpaw.security.tool_guard.guardians.rule_guardian"
            "._get_workspace_root",
            return_value=Path("/tmp"),
        ):
            guardian = RuleBasedToolGuardian(rules_dir=tmp_path)
            result = guardian.guard(
                "execute_shell_command",
                {"command": "rm -rf /"},
            )
            if result:
                f = result[0]
                assert f.rule_id == "CONTRACT_TEST"
                assert f.category is not None
                assert f.severity is not None
                assert f.title is not None
                assert f.description is not None
                assert f.tool_name == "execute_shell_command"
                assert f.guardian == "rule_based_tool_guardian"


# ---------------------------------------------------------------------------
# Contract: BaseToolGuardian interface
# ---------------------------------------------------------------------------


class TestBaseToolGuardianInterface:
    """Verify BaseToolGuardian abstract interface."""

    def test_cannot_instantiate_base(self):
        """BaseToolGuardian is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseToolGuardian("test")  # noqa: E0110

    def test_subclass_must_implement_guard(self):
        """Subclass without guard() cannot be instantiated."""

        class IncompleteGuardian(BaseToolGuardian):
            pass

        with pytest.raises(TypeError):
            IncompleteGuardian("test")  # noqa: E0110

    def test_repr(self, file_guardian):
        """__repr__ should include class name and guardian name."""
        r = repr(file_guardian)
        assert "FilePathToolGuardian" in r
        assert "file_path_tool_guardian" in r

    def test_name_attribute(self, file_guardian):
        """name attribute should be set."""
        assert file_guardian.name == "file_path_tool_guardian"

    def test_always_run_attribute(self, file_guardian):
        """always_run attribute should be accessible."""
        assert isinstance(file_guardian.always_run, bool)
