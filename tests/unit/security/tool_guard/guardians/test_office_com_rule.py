# -*- coding: utf-8 -*-
"""Guard coverage for the bundled inline Office COM automation rule.

Regression for #8002: an inline Office COM object (PowerPoint / Excel /
Word / Outlook ``.Application``) built in a shell command attaches to the
user's already-running single-instance app, so ``Quit()`` closes it. The
bundled CRITICAL rule must surface that command so it is held for approval
before the unsandboxed ``SANDBOX_FALLBACK`` -> ``ALLOW`` downgrade.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from unittest.mock import patch

import pytest

from qwenpaw.security.tool_guard.guardians.rule_guardian import (
    RuleBasedToolGuardian,
    _DEFAULT_RULES_DIR,
    load_rules_from_yaml,
)
from qwenpaw.security.tool_guard.models import GuardSeverity

RULE_ID = "TOOL_CMD_OFFICE_COM_AUTOMATION"

POSITIVE_COMMANDS = [
    "New-Object -ComObject PowerPoint.Application",
    "$ppt = New-Object -ComObject Excel.Application; $ppt.Quit()",
    "New-Object -ComObject 'Word.Application'",
    'New-Object -ComObject "Outlook.Application"',
    "[activator]::CreateInstance([type]::GetTypeFromProgID("
    '"Outlook.Application"))',
    'GetActiveObject("PowerPoint.Application")',
    'CreateObject("Excel.Application")',
    'python -c "import win32com.client; '
    "win32com.client.Dispatch('PowerPoint.Application').Quit()\"",
    'win32com.client.DispatchEx("Word.Application")',
    "[Runtime.InteropServices.Marshal]::GetActiveObject("
    "'PowerPoint.Application')",
    "New-Object -ComObject Excel.Application | % { $_.Quit() }",
]

NEGATIVE_COMMANDS = [
    "echo hello",
    "ls -la",
    "New-Object -ComObject WScript.Shell",
    "New-Object -ComObject Scripting.FileSystemObject",
    'python -c "import win32com.client; '
    "win32com.client.Dispatch('SomeOther.Application')\"",
    'GetActiveObject("Foo.Bar")',
    'CreateObject("Scripting.Dictionary")',
    'git commit -m "document PowerPoint.Application usage"',
    "pip install pywin32",
]


@pytest.fixture(scope="module")
def office_rule():
    """Load the shipped rule from the bundled rules file."""
    rules = load_rules_from_yaml(
        _DEFAULT_RULES_DIR / "dangerous_shell_commands.yaml",
    )
    matches = [r for r in rules if r.id == RULE_ID]
    assert matches, f"{RULE_ID} missing from dangerous_shell_commands.yaml"
    return matches[0]


class TestOfficeComRule:
    """The bundled rule itself matches the right commands."""

    def test_rule_is_critical(self, office_rule):
        assert office_rule.severity == GuardSeverity.CRITICAL

    @pytest.mark.parametrize("command", POSITIVE_COMMANDS)
    def test_positive(self, office_rule, command):
        match, _ = office_rule.match(command)
        assert match is not None

    @pytest.mark.parametrize("command", NEGATIVE_COMMANDS)
    def test_negative(self, office_rule, command):
        match, _ = office_rule.match(command)
        assert match is None


class TestOfficeComGuardian:
    """The guardian surfaces the CRITICAL finding for shell commands."""

    @pytest.fixture
    def guardian(self, office_rule, tmp_path):
        with patch(
            "qwenpaw.security.tool_guard.guardians.rule_guardian"
            "._load_config_rules",
            return_value=([], set()),
        ):
            return RuleBasedToolGuardian(
                rules_dir=tmp_path,
                extra_rules=[office_rule],
            )

    @pytest.mark.parametrize("command", POSITIVE_COMMANDS)
    def test_guard_flags_inline_office_com(self, guardian, command):
        findings = guardian.guard(
            "execute_shell_command",
            {"command": command},
        )
        assert any(
            f.rule_id == RULE_ID and f.severity == GuardSeverity.CRITICAL
            for f in findings
        )

    @pytest.mark.parametrize("command", NEGATIVE_COMMANDS)
    def test_guard_allows_ordinary_shell(self, guardian, command):
        findings = guardian.guard(
            "execute_shell_command",
            {"command": command},
        )
        assert not any(f.rule_id == RULE_ID for f in findings)
