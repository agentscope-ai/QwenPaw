# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-import,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for ShellEvasionGuardian quote-aware checks.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the shell-evasion
detection checks, which previously had zero unit-test coverage.
"""

from __future__ import annotations

import pytest

import qwenpaw.security.tool_guard.guardians.shell_evasion_guardian as seg
from qwenpaw.security.tool_guard.guardians.shell_evasion_guardian import (
    ShellEvasionGuardian,
)


def _guardian_with_all_checks_enabled() -> ShellEvasionGuardian:
    guardian = ShellEvasionGuardian()
    guardian._check_enabled = {name: True for name in seg._CHECK_NAMES}
    return guardian


# ---------------------------------------------------------------------------
# _QuoteState / _extract_outside_single_quotes
# ---------------------------------------------------------------------------


class TestQuoteState:
    def test_single_quote_toggle(self):
        state = seg._QuoteState()
        state.feed("'")
        assert state.in_single is True
        state.feed("'")
        assert state.in_single is False

    def test_double_quote_toggle(self):
        state = seg._QuoteState()
        state.feed('"')
        assert state.in_double is True
        state.feed('"')
        assert state.in_double is False

    def test_backslash_escape_outside_single(self):
        state = seg._QuoteState()
        state.feed("\\")
        assert state.escaped is True
        state.feed('"')  # consumed by escape
        assert state.in_double is False

    def test_backslash_literal_inside_single(self):
        state = seg._QuoteState()
        for ch in "'\\'":
            state.feed(ch)
        assert state.in_single is False

    def test_double_quote_inside_single_ignored(self):
        state = seg._QuoteState()
        for ch in "'\"'":
            state.feed(ch)
        assert state.in_single is False
        assert state.in_double is False


class TestExtractOutsideSingleQuotes:
    def test_removes_single_quoted_content(self):
        assert seg._extract_outside_single_quotes("echo 'rm -rf /'") == (
            "echo "
        )

    def test_keeps_double_quoted_content(self):
        assert seg._extract_outside_single_quotes('echo "$(whoami)"') == (
            'echo "$(whoami)"'
        )

    def test_plain_command_unchanged(self):
        assert seg._extract_outside_single_quotes("ls -la") == "ls -la"


# ---------------------------------------------------------------------------
# _check_command_substitution
# ---------------------------------------------------------------------------


class TestCheckCommandSubstitution:
    def test_backtick_detected(self):
        finding = seg._check_command_substitution(
            "echo `whoami`",
            seg._extract_outside_single_quotes("echo `whoami`"),
        )
        assert finding is not None
        assert finding.rule_id == "SHELL_EVASION_COMMAND_SUBSTITUTION"

    def test_backtick_inside_single_quotes_ignored(self):
        cmd = "echo '`whoami`'"
        finding = seg._check_command_substitution(
            cmd,
            seg._extract_outside_single_quotes(cmd),
        )
        assert finding is None

    def test_dollar_paren_detected(self):
        cmd = "echo $(whoami)"
        finding = seg._check_command_substitution(
            cmd,
            seg._extract_outside_single_quotes(cmd),
        )
        assert finding is not None

    def test_dollar_paren_inside_single_quotes_ignored(self):
        cmd = "echo '$(whoami)'"
        finding = seg._check_command_substitution(
            cmd,
            seg._extract_outside_single_quotes(cmd),
        )
        assert finding is None

    def test_clean_command(self):
        assert seg._check_command_substitution("ls", "ls") is None


# ---------------------------------------------------------------------------
# _check_obfuscated_flags
# ---------------------------------------------------------------------------


class TestCheckObfuscatedFlags:
    def test_ansi_c_quote_detected(self):
        finding = seg._check_obfuscated_flags("$'\\x2d exec'")
        assert finding is not None
        assert finding.rule_id == "SHELL_EVASION_OBFUSCATED_FLAGS"

    def test_locale_quote_detected(self):
        finding = seg._check_obfuscated_flags('$"hello"')
        assert finding is not None

    def test_quoted_flag_after_space_detected(self):
        finding = seg._check_obfuscated_flags("find . '-exec' ls")
        assert finding is not None

    def test_normal_flag_clean(self):
        assert seg._check_obfuscated_flags("find . -name '*.py'") is None

    def test_quoted_non_flag_clean(self):
        assert seg._check_obfuscated_flags("echo 'hello world'") is None


# ---------------------------------------------------------------------------
# _check_backslash_escaped_whitespace
# ---------------------------------------------------------------------------


class TestCheckBackslashWhitespace:
    def test_escaped_space_detected(self):
        finding = seg._check_backslash_escaped_whitespace("echo\\ test")
        assert finding is not None
        assert finding.rule_id == "SHELL_EVASION_BACKSLASH_WHITESPACE"

    def test_escaped_tab_detected(self):
        finding = seg._check_backslash_escaped_whitespace("echo\\\tx")
        assert finding is not None

    def test_escaped_space_inside_double_quotes_clean(self):
        assert seg._check_backslash_escaped_whitespace('echo "a\\ b"') is None

    def test_normal_command_clean(self):
        assert seg._check_backslash_escaped_whitespace("ls -la") is None


# ---------------------------------------------------------------------------
# _check_backslash_escaped_operators
# ---------------------------------------------------------------------------


class TestCheckBackslashOperators:
    def test_escaped_semicolon_detected(self):
        finding = seg._check_backslash_escaped_operators("ls \\; rm")
        assert finding is not None
        assert finding.rule_id == "SHELL_EVASION_BACKSLASH_OPERATOR"

    def test_escaped_pipe_detected(self):
        finding = seg._check_backslash_escaped_operators("ls \\| rm")
        assert finding is not None

    def test_find_exec_terminator_allowed(self):
        cmd = "find . -name x -exec ls {} \\;"
        assert seg._check_backslash_escaped_operators(cmd) is None

    def test_operator_inside_double_quotes_clean(self):
        assert seg._check_backslash_escaped_operators('echo "a\\;b"') is None

    def test_normal_command_clean(self):
        assert seg._check_backslash_escaped_operators("ls -la") is None


# ---------------------------------------------------------------------------
# _check_newlines
# ---------------------------------------------------------------------------


class TestCheckNewlines:
    def test_carriage_return_detected(self):
        finding = seg._check_newlines("ls\rx")
        assert finding is not None
        assert finding.rule_id == "SHELL_EVASION_NEWLINE"

    def test_newline_with_hidden_command_detected(self):
        finding = seg._check_newlines("ls\nrm -rf /")
        assert finding is not None

    def test_trailing_newline_clean(self):
        assert seg._check_newlines("ls\n") is None

    def test_heredoc_clean(self):
        cmd = "cat <<'EOF'\nline1\nline2\nEOF"
        assert seg._check_newlines(cmd) is None


class TestLooksLikeHeredoc:
    def test_complete_heredoc_true(self):
        cmd = "cat <<'EOF'\nbody\nEOF"
        assert seg._looks_like_heredoc(cmd) is True

    def test_no_heredoc_false(self):
        assert seg._looks_like_heredoc("ls -la") is False


# ---------------------------------------------------------------------------
# guardian entry point
# ---------------------------------------------------------------------------


class TestShellEvasionGuardian:
    def test_non_shell_tool_returns_empty(self):
        guardian = _guardian_with_all_checks_enabled()
        assert guardian.guard("read_file", {"command": "`x`"}) == []

    def test_empty_command_returns_empty(self):
        guardian = _guardian_with_all_checks_enabled()
        assert guardian.guard("execute_shell_command", {"command": ""}) == []

    def test_non_string_command_returns_empty(self):
        guardian = _guardian_with_all_checks_enabled()
        assert guardian.guard("execute_shell_command", {"command": 5}) == []

    def test_clean_command_no_findings(self):
        guardian = _guardian_with_all_checks_enabled()
        findings = guardian.guard(
            "execute_shell_command",
            {"command": "ls -la"},
        )
        assert findings == []

    def test_backtick_command_flagged(self):
        guardian = _guardian_with_all_checks_enabled()
        findings = guardian.guard(
            "execute_shell_command",
            {"command": "echo `whoami`"},
        )
        assert len(findings) >= 1
        assert any(
            f.rule_id == "SHELL_EVASION_COMMAND_SUBSTITUTION" for f in findings
        )

    def test_disabled_checks_skipped(self):
        guardian = ShellEvasionGuardian()
        guardian._check_enabled = {}  # all disabled
        findings = guardian.guard(
            "execute_shell_command",
            {"command": "echo `whoami`"},
        )
        assert findings == []

    def test_check_exception_swallowed(self, monkeypatch):
        guardian = _guardian_with_all_checks_enabled()

        def boom(command):
            raise RuntimeError("check crashed")

        # Replace one check with a crashing function via the _CHECKS tuple.
        monkeypatch.setattr(
            seg,
            "_CHECKS",
            (("newlines", boom),),
        )
        findings = guardian.guard(
            "execute_shell_command",
            {"command": "ls"},
        )
        assert findings == []

    def test_reload(self, monkeypatch):
        guardian = ShellEvasionGuardian()
        monkeypatch.setattr(
            seg,
            "_load_check_enabled_map",
            lambda: {"newlines": True},
        )
        guardian.reload()
        assert guardian._check_enabled == {"newlines": True}


class TestLoadCheckEnabledMap:
    def test_config_load_failure_returns_empty(self, monkeypatch):
        import qwenpaw.config as config_module

        def boom():
            raise RuntimeError("no config")

        monkeypatch.setattr(config_module, "load_config", boom)
        assert seg._load_check_enabled_map() == {}

    def test_non_dict_returns_empty(self, monkeypatch):
        import qwenpaw.config as config_module
        from types import SimpleNamespace

        monkeypatch.setattr(
            config_module,
            "load_config",
            lambda: SimpleNamespace(
                security=SimpleNamespace(
                    tool_guard=SimpleNamespace(
                        shell_evasion_checks="not-a-dict",
                    ),
                ),
            ),
        )
        assert seg._load_check_enabled_map() == {}

    def test_valid_config_filters_unknown_keys(self, monkeypatch):
        import qwenpaw.config as config_module
        from types import SimpleNamespace

        monkeypatch.setattr(
            config_module,
            "load_config",
            lambda: SimpleNamespace(
                security=SimpleNamespace(
                    tool_guard=SimpleNamespace(
                        shell_evasion_checks={
                            "newlines": True,
                            "unknown_check": True,
                            "quoted_newline": "yes",  # not a bool
                        },
                    ),
                ),
            ),
        )
        assert seg._load_check_enabled_map() == {"newlines": True}
