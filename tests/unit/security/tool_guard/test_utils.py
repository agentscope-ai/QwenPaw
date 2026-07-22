# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.tool_guard.utils."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from unittest.mock import patch

from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)
from qwenpaw.security.tool_guard.utils import (
    _DEFAULT_GUARDED_TOOLS,
    _parse_guarded_tokens,
    log_findings,
    logger,
    resolve_auto_denied_rules,
    resolve_denied_tools,
    resolve_guarded_tools,
)


# ---------------------------------------------------------------------------
# _parse_guarded_tokens
# ---------------------------------------------------------------------------


class TestParseGuardedTokens:
    """Tests for the _parse_guarded_tokens helper."""

    def test_all_returns_none(self):
        """The token 'all' signals guard-everything (returns None)."""
        assert _parse_guarded_tokens(["all"]) is None

    def test_star_returns_none(self):
        """The token '*' also signals guard-everything."""
        assert _parse_guarded_tokens(["*"]) is None

    def test_none_returns_empty_set(self):
        """The token 'none' disables guarding (returns empty set)."""
        assert _parse_guarded_tokens(["none"]) == set()

    def test_off_returns_empty_set(self):
        """'off' disables guarding."""
        assert _parse_guarded_tokens(["off"]) == set()

    def test_false_returns_empty_set(self):
        """'false' disables guarding."""
        assert _parse_guarded_tokens(["false"]) == set()

    def test_zero_returns_empty_set(self):
        """'0' disables guarding."""
        assert _parse_guarded_tokens(["0"]) == set()

    def test_comma_separated_tool_names(self):
        """Comma-separated tool names produce the expected set."""
        tokens = ["execute_shell_command", "read_file", "write_file"]
        result = _parse_guarded_tokens(tokens)
        assert result == {"execute_shell_command", "read_file", "write_file"}

    def test_whitespace_handling(self):
        """Leading/trailing whitespace is stripped from tokens."""
        tokens = ["  execute_shell_command  ", " read_file ", "write_file"]
        result = _parse_guarded_tokens(tokens)
        assert result == {"execute_shell_command", "read_file", "write_file"}

    def test_empty_tokens_ignored(self):
        """Empty strings and whitespace-only tokens are dropped."""
        tokens = ["execute_shell_command", "", "  ", "read_file"]
        result = _parse_guarded_tokens(tokens)
        assert result == {"execute_shell_command", "read_file"}

    def test_all_empty_returns_empty_set(self):
        """If all tokens are empty/whitespace, return empty set."""
        assert _parse_guarded_tokens(["", "  "]) == set()

    def test_mixed_disable_tokens_only(self):
        """A mix of only disable-tokens returns empty set."""
        assert _parse_guarded_tokens(["none", "off", "false", "0"]) == set()

    def test_mixed_case_all(self):
        """ALL in uppercase is recognised as the 'all' sentinel."""
        assert _parse_guarded_tokens(["ALL"]) is None

    def test_tool_names_preserved_case(self):
        """Real tool names keep their original casing."""
        tokens = ["Execute_Shell_Command"]
        result = _parse_guarded_tokens(tokens)
        assert "Execute_Shell_Command" in result


# ---------------------------------------------------------------------------
# resolve_guarded_tools
# ---------------------------------------------------------------------------


class TestResolveGuardedTools:
    """Tests for resolve_guarded_tools."""

    def test_user_defined_takes_priority(self):
        """When user_defined is provided, it wins over env and config."""
        result = resolve_guarded_tools(
            user_defined=["execute_shell_command", "read_file"],
        )
        assert result == {"execute_shell_command", "read_file"}

    def test_user_defined_none_means_guard_all(self):
        """user_defined=['all'] resolves to None (guard everything)."""
        result = resolve_guarded_tools(user_defined=["all"])
        assert result is None

    def test_user_defined_none_token_means_empty(self):
        """user_defined=['none'] resolves to empty set."""
        result = resolve_guarded_tools(user_defined=["none"])
        assert result == set()

    def test_env_var_qwenpaw_tool_guard_tools(self, mock_env_loader):
        """Env var QWENPAW_TOOL_GUARD_TOOLS is consulted
        when user_defined is None."""
        mock_env_loader.return_value = "execute_shell_command,write_file"
        result = resolve_guarded_tools()
        assert result == {"execute_shell_command", "write_file"}

    def test_env_var_all_means_none(self, mock_env_loader):
        """Env var value 'all' resolves to None (guard everything)."""
        mock_env_loader.return_value = "all"
        result = resolve_guarded_tools()
        assert result is None

    def test_env_var_star_means_none(self, mock_env_loader):
        """Env var value '*' resolves to None."""
        mock_env_loader.return_value = "*"
        result = resolve_guarded_tools()
        assert result is None

    def test_env_var_off_means_empty(self, mock_env_loader):
        """Env var value 'off' resolves to empty set."""
        mock_env_loader.return_value = "off"
        result = resolve_guarded_tools()
        assert result == set()

    def test_env_var_empty_string_falls_through(
        self,
        mock_env_loader,
        mock_config,  # pylint: disable=unused-argument
    ):
        """Empty env var falls through to config, then default."""
        mock_env_loader.return_value = ""
        # Config also returns None for guarded_tools by default
        result = resolve_guarded_tools()
        assert result == set(_DEFAULT_GUARDED_TOOLS)

    def test_config_guarded_tools_used(self, mock_env_loader, mock_config):
        """When env is empty, config's guarded_tools is used."""
        mock_env_loader.return_value = ""
        mock_config.return_value.security.tool_guard.guarded_tools = [
            "execute_shell_command",
        ]
        result = resolve_guarded_tools()
        assert result == {"execute_shell_command"}

    def test_default_set_returned_when_nothing_specified(
        self,
        mock_env_loader,
        mock_config,  # pylint: disable=unused-argument
    ):
        """When user, env, and config are all empty,
        default set is returned."""
        mock_env_loader.return_value = ""
        # mock_config returns guarded_tools=None by default
        result = resolve_guarded_tools()
        assert result == set(_DEFAULT_GUARDED_TOOLS)

    def test_none_user_defined_triggers_env_lookup(self, mock_env_loader):
        """None user_defined causes the env var to be checked."""
        mock_env_loader.return_value = "read_file"
        result = resolve_guarded_tools(user_defined=None)
        assert "read_file" in result

    def test_config_load_failure_falls_to_default(
        self,
        mock_env_loader,
    ):
        """If config loading fails, the default set is returned."""
        mock_env_loader.return_value = ""
        with patch(
            "qwenpaw.security.tool_guard.utils._load_config_tool_guard",
            return_value=None,
        ):
            result = resolve_guarded_tools()
        assert result == set(_DEFAULT_GUARDED_TOOLS)


# ---------------------------------------------------------------------------
# resolve_denied_tools
# ---------------------------------------------------------------------------


class TestResolveDeniedTools:
    """Tests for resolve_denied_tools."""

    def test_user_defined_takes_priority(self):
        """When user_defined is provided, it wins over env and config."""
        result = resolve_denied_tools(user_defined=["dangerous_tool"])
        assert result == {"dangerous_tool"}

    def test_user_defined_none_pass_through(self):
        """user_defined=None triggers env/config/default chain."""
        # This test just verifies the function doesn't crash with None
        with patch(
            "qwenpaw.security.tool_guard.utils.EnvVarLoader.get_str",
            return_value="",
        ):
            result = resolve_denied_tools(user_defined=None)
        # Default is empty
        assert isinstance(result, set)

    def test_env_var_qwenpaw_tool_guard_denied_tools(self, mock_env_loader):
        """Env var QWENPAW_TOOL_GUARD_DENIED_TOOLS is consulted."""
        mock_env_loader.return_value = "tool_a,tool_b"
        result = resolve_denied_tools()
        assert result == {"tool_a", "tool_b"}

    def test_env_var_whitespace_stripped(self, mock_env_loader):
        """Whitespace is stripped from env var tokens."""
        mock_env_loader.return_value = "  tool_a , tool_b  "
        result = resolve_denied_tools()
        assert result == {"tool_a", "tool_b"}

    def test_default_is_empty_set(
        self,
        mock_env_loader,
        mock_config,  # pylint: disable=unused-argument
    ):
        """When nothing is specified, the default is an empty set."""
        mock_env_loader.return_value = ""
        result = resolve_denied_tools()
        assert result == set()

    def test_config_denied_tools_used(self, mock_env_loader, mock_config):
        """Config's denied_tools is used when env is empty."""
        mock_env_loader.return_value = ""
        mock_config.return_value.security.tool_guard.denied_tools = [
            "blocked_tool",
        ]
        result = resolve_denied_tools()
        assert result == {"blocked_tool"}

    def test_config_empty_denied_tools_falls_through(
        self,
        mock_env_loader,
        mock_config,
    ):
        """If config.denied_tools is falsy, fall through
        to default empty set."""
        mock_env_loader.return_value = ""
        mock_config.return_value.security.tool_guard.denied_tools = []
        result = resolve_denied_tools()
        assert result == set()


# ---------------------------------------------------------------------------
# resolve_auto_denied_rules
# ---------------------------------------------------------------------------


class TestResolveAutoDeniedRules:
    """Tests for resolve_auto_denied_rules.

    Mirrors the priority chain of resolve_denied_tools:
        user_defined > env var > config.json > default(empty).
    """

    def test_user_defined_takes_priority(self):
        """User-supplied set wins over env and config."""
        result = resolve_auto_denied_rules(
            user_defined=["RULE_A", "RULE_B"],
        )
        assert result == {"RULE_A", "RULE_B"}

    def test_user_defined_strips_whitespace_and_empty(self):
        """Whitespace is stripped and empty/whitespace tokens dropped."""
        result = resolve_auto_denied_rules(
            user_defined=["  RULE_A  ", "", "  ", "RULE_B"],
        )
        assert result == {"RULE_A", "RULE_B"}

    def test_user_defined_empty_iterable_yields_empty_set(self):
        """An empty user-supplied iterable short-circuits to empty set
        and does NOT fall through to env/config."""
        with patch(
            "qwenpaw.security.tool_guard.utils.EnvVarLoader.get_str",
            return_value="SHOULD_NOT_BE_READ",
        ):
            result = resolve_auto_denied_rules(user_defined=[])
        assert result == set()

    def test_env_var_consulted_when_user_defined_is_none(
        self,
        mock_env_loader,
    ):
        """Env var QWENPAW_TOOL_GUARD_AUTO_DENIED_RULES is read next."""
        mock_env_loader.return_value = "RULE_X,RULE_Y"
        result = resolve_auto_denied_rules()
        assert result == {"RULE_X", "RULE_Y"}

    def test_env_var_whitespace_stripped(self, mock_env_loader):
        """Whitespace around comma-separated env tokens is stripped."""
        mock_env_loader.return_value = "  RULE_X , RULE_Y  "
        result = resolve_auto_denied_rules()
        assert result == {"RULE_X", "RULE_Y"}

    def test_env_var_empty_string_falls_through_to_config(
        self,
        mock_env_loader,
        mock_config,
    ):
        """Empty env-var falls through to the config-derived value."""
        mock_env_loader.return_value = ""
        mock_config.return_value.security.tool_guard.auto_denied_rules = [
            "RULE_CFG",
        ]
        result = resolve_auto_denied_rules()
        assert result == {"RULE_CFG"}

    def test_config_strips_whitespace_and_drops_empty(
        self,
        mock_env_loader,
        mock_config,
    ):
        """Whitespace stripped and empty entries dropped from config list."""
        mock_env_loader.return_value = ""
        mock_config.return_value.security.tool_guard.auto_denied_rules = [
            " RULE_CFG ",
            "",
            "  ",
        ]
        result = resolve_auto_denied_rules()
        assert result == {"RULE_CFG"}

    def test_config_empty_list_falls_through_to_default(
        self,
        mock_env_loader,
        mock_config,
    ):
        """Falsy config.auto_denied_rules falls through to default empty."""
        mock_env_loader.return_value = ""
        mock_config.return_value.security.tool_guard.auto_denied_rules = []
        result = resolve_auto_denied_rules()
        assert result == set()

    def test_default_is_empty_set(
        self,
        mock_env_loader,
        mock_config,  # pylint: disable=unused-argument
    ):
        """With nothing specified anywhere the default is an empty set."""
        mock_env_loader.return_value = ""
        result = resolve_auto_denied_rules()
        assert result == set()

    def test_config_load_failure_falls_to_default(self, mock_env_loader):
        """If config loading raises, fall through to default empty set."""
        mock_env_loader.return_value = ""
        with patch(
            "qwenpaw.security.tool_guard.utils._load_config_tool_guard",
            return_value=None,
        ):
            result = resolve_auto_denied_rules()
        assert result == set()


# ---------------------------------------------------------------------------
# DEFAULT_GUARDED_TOOLS
# ---------------------------------------------------------------------------


class TestDefaultGuardedTools:
    """Tests for the _DEFAULT_GUARDED_TOOLS frozenset."""

    def test_is_frozenset(self):
        assert isinstance(_DEFAULT_GUARDED_TOOLS, frozenset)

    def test_contains_expected_tools(self):
        """The default set includes the expected high-risk tools."""
        expected = {
            "execute_shell_command",
            "read_file",
            "write_file",
            "edit_file",
            "append_file",
            "send_file_to_user",
            "view_text_file",
            "write_text_file",
        }
        assert _DEFAULT_GUARDED_TOOLS == expected


# ---------------------------------------------------------------------------
# log_findings
# ---------------------------------------------------------------------------


def _format_call(mock_call):
    """Format a logger mock call into its rendered message string.

    The logger uses %-style formatting: ``logger.info(fmt, *args)``.
    ``mock_call`` is a ``call(fmt, arg1, arg2, ...)`` tuple.
    """
    fmt = mock_call[0][0]
    args = mock_call[0][1:]
    if args:
        return fmt % args
    return fmt


class TestLogFindings:
    """Tests for the log_findings structured logging function.

    The project's custom logging sets propagate=False on the
    ``qwenpaw`` logger, so caplog cannot capture records.  Instead we
    patch the module-level logger and inspect the mock calls directly.
    """

    def test_empty_findings_logs_summary_only(self):
        """When findings list is empty, only a summary line is logged."""
        result = ToolGuardResult(
            tool_name="read_file",
            params={},
            findings=[],
            guard_duration_seconds=0.01,
        )
        with patch.object(logger, "info") as mock_info, patch.object(
            logger,
            "warning",
        ):
            log_findings("read_file", result)
            # Summary for safe result uses info
            mock_info.assert_called()
            last_msg = _format_call(mock_info.call_args_list[-1])
            assert "Summary for tool 'read_file'" in last_msg
            assert "max_severity=SAFE" in last_msg

    def test_high_severity_uses_warning(self):
        """HIGH severity findings are logged at WARNING level."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.PATH_TRAVERSAL,
            severity=GuardSeverity.HIGH,
            title="Path traversal",
            description="Escapes workspace",
            tool_name="read_file",
            param_name="path",
            matched_value="../../etc/passwd",
        )
        result = ToolGuardResult(
            tool_name="read_file",
            params={"path": "../../etc/passwd"},
            findings=[finding],
            guard_duration_seconds=0.02,
        )
        with patch.object(logger, "warning") as mock_warn:
            log_findings("read_file", result)
            # HIGH finding uses warning, summary also uses warning
            assert mock_warn.call_count >= 2
            first_msg = _format_call(mock_warn.call_args_list[0])
            assert "HIGH" in first_msg

    def test_low_severity_uses_info(self):
        """LOW severity findings are logged at INFO level."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.RESOURCE_ABUSE,
            severity=GuardSeverity.LOW,
            title="Resource usage",
            description="High memory usage",
            tool_name="execute_shell_command",
        )
        result = ToolGuardResult(
            tool_name="execute_shell_command",
            params={},
            findings=[finding],
            guard_duration_seconds=0.01,
        )
        with patch.object(logger, "info") as mock_info:
            log_findings("execute_shell_command", result)
            first_msg = _format_call(mock_info.call_args_list[0])
            assert "LOW" in first_msg

    def test_critical_severity_uses_warning(self):
        """CRITICAL severity findings are logged at WARNING level."""
        finding = GuardFinding(
            id="f-1",
            rule_id="R-001",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.CRITICAL,
            title="Command injection",
            description="Destructive command",
            tool_name="execute_shell_command",
            matched_value="rm -rf /",
        )
        result = ToolGuardResult(
            tool_name="execute_shell_command",
            params={"command": "rm -rf /"},
            findings=[finding],
            guard_duration_seconds=0.03,
        )
        with patch.object(logger, "warning") as mock_warn:
            log_findings("execute_shell_command", result)
            first_msg = _format_call(mock_warn.call_args_list[0])
            assert "CRITICAL" in first_msg

    def test_log_includes_tool_guard_prefix(self):
        """Log messages include the [TOOL GUARD] prefix."""
        result = ToolGuardResult(
            tool_name="read_file",
            params={},
            findings=[],
            guard_duration_seconds=0.01,
        )
        with patch.object(logger, "info") as mock_info:
            log_findings("read_file", result)
            msg = _format_call(mock_info.call_args_list[0])
            assert "[TOOL GUARD]" in msg
