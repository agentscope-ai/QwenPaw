# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for qwenpaw.security.tool_guard.engine."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.security.tool_guard.engine import (
    ToolGuardEngine,
    _guard_enabled,
    get_guard_engine,
)
from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_guardian(
    name: str = "test_guardian",
    always_run: bool = False,
    findings: list[GuardFinding] | None = None,
    side_effect=None,
) -> MagicMock:
    """Build a lightweight MagicMock that quacks like a BaseToolGuardian."""
    g = MagicMock()
    g.name = name
    g.always_run = always_run
    if side_effect is not None:
        g.guard.side_effect = side_effect
    else:
        g.guard.return_value = findings or []
    return g


def _make_finding(
    severity: GuardSeverity = GuardSeverity.HIGH,
    rule_id: str = "R001",
) -> GuardFinding:
    return GuardFinding(
        id="f-1",
        rule_id=rule_id,
        category=GuardThreatCategory.PATH_TRAVERSAL,
        severity=severity,
        title="Test finding",
        description="desc",
        tool_name="some_tool",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton before and after each test."""
    import qwenpaw.security.tool_guard.engine as eng_mod

    eng_mod._engine_instance = None
    yield
    eng_mod._engine_instance = None


@pytest.fixture()
def engine_with_defaults():
    """Return an engine with mocked defaults (no filesystem/config access)."""
    g1 = _make_guardian("alpha", always_run=False)
    g2 = _make_guardian("beta", always_run=True)
    with patch.object(
        ToolGuardEngine,
        "_default_guardians",
        return_value=[g1, g2],
    ), patch.object(ToolGuardEngine, "_reload_tool_sets"):
        eng = ToolGuardEngine(enabled=True)
    eng._guardians = [g1, g2]
    eng._guarded_tools = None
    eng._denied_tools = set()
    eng._auto_denied_rules = set()
    return eng


# ===================================================================
# TestGuardEnabled
# ===================================================================


class TestGuardEnabled:
    """Tests for the _guard_enabled() free function."""

    @patch("qwenpaw.security.tool_guard.engine.EnvVarLoader")
    def test_enabled_when_env_var_is_true_string(self, mock_loader):
        mock_loader.get_str.return_value = "true"
        assert _guard_enabled() is True

    @patch("qwenpaw.security.tool_guard.engine.EnvVarLoader")
    def test_enabled_when_env_var_is_false_string(self, mock_loader):
        mock_loader.get_str.return_value = "false"
        assert _guard_enabled() is False

    @patch("qwenpaw.security.tool_guard.engine.EnvVarLoader")
    def test_enabled_defaults_to_true_when_no_env_no_config(self, mock_loader):
        mock_loader.get_str.return_value = ""
        with patch(
            "qwenpaw.config.load_config",
            side_effect=Exception("no config"),
        ):
            assert _guard_enabled() is True

    @patch("qwenpaw.security.tool_guard.engine.EnvVarLoader")
    def test_enabled_reads_from_config_when_no_env(self, mock_loader):
        mock_loader.get_str.return_value = ""
        mock_cfg = MagicMock()
        mock_cfg.security.tool_guard.enabled = False
        with patch(
            "qwenpaw.config.load_config",
            return_value=mock_cfg,
        ):
            assert _guard_enabled() is False


# ===================================================================
# TestToolGuardEngineInit
# ===================================================================


class TestToolGuardEngineInit:
    @patch.object(ToolGuardEngine, "_reload_tool_sets")
    @patch.object(ToolGuardEngine, "_default_guardians")
    def test_init_with_no_guardians_creates_defaults(
        self,
        mock_defaults,
        mock_reload,  # pylint: disable=unused-argument
    ):
        default_g = _make_guardian("default_g")
        mock_defaults.return_value = [default_g]
        # Patch the guardian imports inside _default_guardians to be safe
        eng = ToolGuardEngine(enabled=True)
        mock_defaults.assert_called_once()
        assert eng._guardians == [default_g]

    @patch.object(ToolGuardEngine, "_reload_tool_sets")
    def test_init_with_custom_guardians(
        self,
        mock_reload,  # pylint: disable=unused-argument
    ):
        g1 = _make_guardian("custom1")
        g2 = _make_guardian("custom2")
        eng = ToolGuardEngine(guardians=[g1, g2], enabled=True)
        assert eng._guardians == [g1, g2]

    @patch.object(ToolGuardEngine, "_reload_tool_sets")
    def test_init_with_enabled_false(
        self,
        mock_reload,  # pylint: disable=unused-argument
    ):
        eng = ToolGuardEngine(enabled=False)
        assert eng.enabled is False

    @patch.object(ToolGuardEngine, "_reload_tool_sets")
    @patch.object(ToolGuardEngine, "_default_guardians")
    def test_init_calls_reload_tool_sets(self, mock_defaults, mock_reload):
        mock_defaults.return_value = []
        ToolGuardEngine(enabled=True)
        mock_reload.assert_called_once()


# ===================================================================
# TestToolGuardEngineProperties
# ===================================================================


class TestToolGuardEngineProperties:
    def test_guardian_names_returns_list_of_names(self, engine_with_defaults):
        assert engine_with_defaults.guardian_names == ["alpha", "beta"]

    def test_enabled_getter_setter(self, engine_with_defaults):
        assert engine_with_defaults.enabled is True
        engine_with_defaults.enabled = False
        assert engine_with_defaults.enabled is False
        engine_with_defaults.enabled = True
        assert engine_with_defaults.enabled is True

    def test_guarded_tools_returns_set_or_none(self, engine_with_defaults):
        # Default: None (guard all)
        assert engine_with_defaults.guarded_tools is None

        engine_with_defaults._guarded_tools = {"read_file", "write_file"}
        assert engine_with_defaults.guarded_tools == {
            "read_file",
            "write_file",
        }

    def test_denied_tools_returns_set(self, engine_with_defaults):
        assert engine_with_defaults.denied_tools == set()
        engine_with_defaults._denied_tools = {"dangerous_tool"}
        assert engine_with_defaults.denied_tools == {"dangerous_tool"}


# ===================================================================
# TestToolGuardEngineRegister
# ===================================================================


class TestToolGuardEngineRegister:
    def test_register_guardian_adds_guardian(self, engine_with_defaults):
        g = _make_guardian("gamma")
        engine_with_defaults.register_guardian(g)
        assert "gamma" in engine_with_defaults.guardian_names
        assert g in engine_with_defaults._guardians

    def test_unregister_guardian_removes_by_name(self, engine_with_defaults):
        assert "alpha" in engine_with_defaults.guardian_names
        result = engine_with_defaults.unregister_guardian("alpha")
        assert result is True
        assert "alpha" not in engine_with_defaults.guardian_names

    def test_unregister_guardian_returns_false_when_not_found(
        self,
        engine_with_defaults,
    ):
        result = engine_with_defaults.unregister_guardian("nonexistent")
        assert result is False


# ===================================================================
# TestToolGuardEngineIsDenied
# ===================================================================


class TestToolGuardEngineIsDenied:
    def test_is_denied_true_when_in_denied_set(self, engine_with_defaults):
        engine_with_defaults._denied_tools = {"rm_rf", "drop_db"}
        assert engine_with_defaults.is_denied("rm_rf") is True

    def test_is_denied_false_when_not_in_denied_set(
        self,
        engine_with_defaults,
    ):
        engine_with_defaults._denied_tools = {"rm_rf"}
        assert engine_with_defaults.is_denied("read_file") is False


# ===================================================================
# TestToolGuardEngineShouldAutoDenyResult
# ===================================================================


class TestToolGuardEngineShouldAutoDenyResult:
    """Tests for ToolGuardEngine.should_auto_deny_result.

    The method returns True only when at least one finding's rule_id is
    listed in the engine's auto-deny rule set; otherwise False. None /
    empty results / empty rule set all short-circuit to False.
    """

    def _make_result(self, findings):
        return ToolGuardResult(
            tool_name="execute_shell_command",
            params={"command": "x"},
            findings=findings,
            guard_duration_seconds=0.0,
        )

    def test_returns_false_when_result_is_none(self, engine_with_defaults):
        engine_with_defaults._auto_denied_rules = {"R1"}
        assert engine_with_defaults.should_auto_deny_result(None) is False

    def test_returns_false_when_findings_empty(self, engine_with_defaults):
        engine_with_defaults._auto_denied_rules = {"R1"}
        result = self._make_result([])
        assert engine_with_defaults.should_auto_deny_result(result) is False

    def test_returns_false_when_auto_deny_rules_empty(
        self,
        engine_with_defaults,
    ):
        """No auto-deny rules → never auto-deny regardless of findings."""
        engine_with_defaults._auto_denied_rules = set()
        result = self._make_result([_make_finding(rule_id="R1")])
        assert engine_with_defaults.should_auto_deny_result(result) is False

    def test_returns_true_when_finding_matches_rule(
        self,
        engine_with_defaults,
    ):
        engine_with_defaults._auto_denied_rules = {"R1"}
        result = self._make_result([_make_finding(rule_id="R1")])
        assert engine_with_defaults.should_auto_deny_result(result) is True

    def test_returns_false_when_findings_dont_match(
        self,
        engine_with_defaults,
    ):
        engine_with_defaults._auto_denied_rules = {"DANGEROUS_RULE"}
        result = self._make_result(
            [
                _make_finding(rule_id="OTHER_1"),
                _make_finding(rule_id="OTHER_2"),
            ],
        )
        assert engine_with_defaults.should_auto_deny_result(result) is False

    def test_returns_true_when_any_finding_matches(
        self,
        engine_with_defaults,
    ):
        """Among multiple findings, a single matching rule_id triggers."""
        engine_with_defaults._auto_denied_rules = {"DANGEROUS"}
        result = self._make_result(
            [
                _make_finding(rule_id="HARMLESS"),
                _make_finding(rule_id="DANGEROUS"),
                _make_finding(rule_id="OTHER"),
            ],
        )
        assert engine_with_defaults.should_auto_deny_result(result) is True

    def test_auto_denied_rules_property_reflects_state(
        self,
        engine_with_defaults,
    ):
        """Public ``auto_denied_rules`` property exposes the configured set."""
        engine_with_defaults._auto_denied_rules = {"R1", "R2"}
        assert engine_with_defaults.auto_denied_rules == {"R1", "R2"}


# ===================================================================
# TestToolGuardEngineIsGuarded
# ===================================================================


class TestToolGuardEngineIsGuarded:
    def test_is_guarded_true_when_in_guarded_set(self, engine_with_defaults):
        engine_with_defaults._guarded_tools = {"read_file", "write_file"}
        assert engine_with_defaults.is_guarded("read_file") is True

    def test_is_guarded_true_when_guarded_tools_is_none(
        self,
        engine_with_defaults,
    ):
        engine_with_defaults._guarded_tools = None
        # None means guard all tools
        assert engine_with_defaults.is_guarded("any_tool") is True

    def test_is_guarded_false_when_not_in_set(self, engine_with_defaults):
        engine_with_defaults._guarded_tools = {"read_file"}
        assert engine_with_defaults.is_guarded("execute_shell") is False


# ===================================================================
# TestToolGuardEngineGuard
# ===================================================================


class TestToolGuardEngineGuard:
    def test_guard_returns_none_when_disabled(self, engine_with_defaults):
        engine_with_defaults.enabled = False
        result = engine_with_defaults.guard("some_tool", {})
        assert result is None

    def test_guard_runs_all_guardians_when_tool_is_guarded(
        self,
        engine_with_defaults,
    ):
        finding = _make_finding()
        engine_with_defaults._guardians[0].guard.return_value = [finding]
        engine_with_defaults._guardians[1].guard.return_value = []

        result = engine_with_defaults.guard(
            "some_tool",
            {"path": "/etc/passwd"},
        )

        assert isinstance(result, ToolGuardResult)
        assert "alpha" in result.guardians_used
        assert "beta" in result.guardians_used
        assert finding in result.findings
        engine_with_defaults._guardians[0].guard.assert_called_once_with(
            "some_tool",
            {"path": "/etc/passwd"},
        )
        engine_with_defaults._guardians[1].guard.assert_called_once_with(
            "some_tool",
            {"path": "/etc/passwd"},
        )

    def test_guard_skips_non_always_run_guardians_when_only_always_run(
        self,
        engine_with_defaults,
    ):
        # alpha has always_run=False, beta has always_run=True
        engine_with_defaults.guard(
            "some_tool",
            {},
            only_always_run=True,
        )

        # Only beta should be called
        engine_with_defaults._guardians[0].guard.assert_not_called()
        engine_with_defaults._guardians[1].guard.assert_called_once()

    def test_guard_aggregates_findings_from_all_guardians(
        self,
        engine_with_defaults,
    ):
        f1 = _make_finding(severity=GuardSeverity.HIGH, rule_id="R001")
        f2 = _make_finding(severity=GuardSeverity.MEDIUM, rule_id="R002")
        engine_with_defaults._guardians[0].guard.return_value = [f1]
        engine_with_defaults._guardians[1].guard.return_value = [f2]

        result = engine_with_defaults.guard("tool", {})

        assert result.findings == [f1, f2]
        assert result.findings_count == 2

    def test_guard_returns_result_with_guardians_used(
        self,
        engine_with_defaults,
    ):
        engine_with_defaults._guardians[0].guard.return_value = []
        engine_with_defaults._guardians[1].guard.return_value = []

        result = engine_with_defaults.guard("tool", {})

        assert result.guardians_used == ["alpha", "beta"]
        assert not result.guardians_failed
        assert result.tool_name == "tool"
        assert not result.params

    def test_guard_handles_guardian_exception_gracefully(
        self,
        engine_with_defaults,
    ):
        engine_with_defaults._guardians[0].guard.side_effect = RuntimeError(
            "boom",
        )
        engine_with_defaults._guardians[1].guard.return_value = []

        result = engine_with_defaults.guard("tool", {})

        # Failing guardian should appear in
        # guardians_failed, not guardians_used
        assert "alpha" not in result.guardians_used
        assert len(result.guardians_failed) == 1
        assert result.guardians_failed[0]["name"] == "alpha"
        assert "boom" in result.guardians_failed[0]["error"]
        # Non-failing guardian still runs fine
        assert "beta" in result.guardians_used

    def test_guard_sets_duration(self, engine_with_defaults):
        engine_with_defaults._guardians[0].guard.return_value = []
        engine_with_defaults._guardians[1].guard.return_value = []

        result = engine_with_defaults.guard("tool", {})

        assert result.guard_duration_seconds >= 0.0


# ===================================================================
# TestGetGuardEngine
# ===================================================================


class TestGetGuardEngine:
    @patch(
        "qwenpaw.security.tool_guard.engine.ToolGuardEngine",
        autospec=True,
    )
    def test_returns_singleton_instance(self, MockEngine):
        MockEngine.return_value = MagicMock(spec=ToolGuardEngine)
        result = get_guard_engine()
        MockEngine.assert_called_once()
        assert result is MockEngine.return_value

    @patch(
        "qwenpaw.security.tool_guard.engine.ToolGuardEngine",
        autospec=True,
    )
    def test_returns_same_instance_on_multiple_calls(self, MockEngine):
        instance = MagicMock(spec=ToolGuardEngine)
        MockEngine.return_value = instance
        r1 = get_guard_engine()
        r2 = get_guard_engine()
        # ToolGuardEngine() should only have been called once
        MockEngine.assert_called_once()
        assert r1 is r2


# ===================================================================
# TestReloadRules
# ===================================================================


class TestToolGuardEngineReloadRules:
    def test_reload_rules_calls_reload_on_guardians_and_reloads_tool_sets(
        self,
        engine_with_defaults,
    ):
        g_with_reload = _make_guardian("reloadable")
        g_with_reload.reload = MagicMock()
        engine_with_defaults._guardians = [g_with_reload]

        with patch.object(
            engine_with_defaults,
            "_reload_tool_sets",
        ) as mock_reload_ts:
            engine_with_defaults.reload_rules()

        g_with_reload.reload.assert_called_once()
        mock_reload_ts.assert_called_once()

    def test_reload_rules_skips_guardians_without_reload(
        self,
        engine_with_defaults,
    ):
        # Default MagicMock has 'reload' attribute, so delete it explicitly
        g_no_reload = _make_guardian("no_reload")
        del g_no_reload.reload
        engine_with_defaults._guardians = [g_no_reload]

        with patch.object(
            engine_with_defaults,
            "_reload_tool_sets",
        ):
            # Should not raise
            engine_with_defaults.reload_rules()
