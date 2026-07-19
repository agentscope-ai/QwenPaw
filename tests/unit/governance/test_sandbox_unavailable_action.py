# -*- coding: utf-8 -*-
"""UT for the configurable sandbox-unavailable fallback action.

When a shell ``SANDBOX_FALLBACK`` decision cannot be honoured because the
sandbox is unusable (platform unsupported or the global switch is off),
``ResourceGovernor.assert_policy`` resolves it according to
``security.sandbox_unavailable_action``:

    * ``allow`` (default) → run unsandboxed (ALLOW)
    * ``ask``             → prompt for approval (ASK)
    * ``deny``            → reject (DENY)

These tests pin all three branches plus the config-reader's parsing and
fail-safe default.
"""
from __future__ import annotations

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernanceDecision,
    ToolCallSpec,
)
from qwenpaw.governance.resource_governor import ResourceGovernor


class _FallbackPolicy:
    """Minimal policy stub that always returns SANDBOX_FALLBACK."""

    def evaluate(self, tc_spec):  # noqa: ANN
        return GovernanceDecision(
            action=GovernanceAction.SANDBOX_FALLBACK,
            reason="bash, no rule hit",
            source="No rule hit",
        )


def _governor_sandbox_unusable(tmp_path) -> ResourceGovernor:
    """A governor whose sandbox is unavailable (platform unsupported)."""
    gov = ResourceGovernor(
        workspace_dir=str(tmp_path),
        governance_dir=str(tmp_path / "gov"),
    )
    gov._policy = _FallbackPolicy()
    # Simulate a platform that does not support any sandbox backend.
    gov._sandbox_available = False
    gov._sandbox_capability = SimpleNamespace(reason="no backend on platform")
    return gov


def _tc_spec() -> ToolCallSpec:
    return ToolCallSpec(
        tool_name="Bash",
        target="echo hello",
        agent_id="agent-1",
        session_id="sess-1",
    )


class TestSandboxUnavailableAction:
    def test_allow_runs_unsandboxed(self, tmp_path, monkeypatch):
        gov = _governor_sandbox_unusable(tmp_path)
        monkeypatch.setattr(
            ResourceGovernor,
            "_sandbox_unavailable_action",
            staticmethod(lambda: "allow"),
        )

        decision = gov.assert_policy(_tc_spec())

        assert decision.action is GovernanceAction.ALLOW
        assert "unsandboxed" in decision.reason

    def test_ask_prompts_for_approval(self, tmp_path, monkeypatch):
        gov = _governor_sandbox_unusable(tmp_path)
        monkeypatch.setattr(
            ResourceGovernor,
            "_sandbox_unavailable_action",
            staticmethod(lambda: "ask"),
        )

        decision = gov.assert_policy(_tc_spec())

        assert decision.action is GovernanceAction.ASK
        assert "approval required" in decision.reason

    def test_deny_rejects(self, tmp_path, monkeypatch):
        gov = _governor_sandbox_unusable(tmp_path)
        monkeypatch.setattr(
            ResourceGovernor,
            "_sandbox_unavailable_action",
            staticmethod(lambda: "deny"),
        )

        decision = gov.assert_policy(_tc_spec())

        assert decision.action is GovernanceAction.DENY
        assert "denied by config" in decision.reason

    def test_default_is_allow_when_config_unavailable(
        self,
        tmp_path,
        monkeypatch,
    ):
        """The real reader falls back to 'allow' if config can't be read,
        preserving the historical (pre-toggle) behavior.
        """
        gov = _governor_sandbox_unusable(tmp_path)

        import qwenpaw.config as config_mod

        def _boom(*_a, **_k):
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(config_mod, "load_config", _boom)

        decision = gov.assert_policy(_tc_spec())

        assert decision.action is GovernanceAction.ALLOW


class TestSandboxUnavailableActionReader:
    """The static config reader normalizes and validates the raw value."""

    @staticmethod
    def _patch_config(monkeypatch, value) -> None:
        import qwenpaw.config as config_mod

        monkeypatch.setattr(
            config_mod,
            "load_config",
            lambda *a, **k: SimpleNamespace(
                security=SimpleNamespace(
                    sandbox_unavailable_action=value,
                ),
            ),
        )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("allow", "allow"),
            ("ask", "ask"),
            ("deny", "deny"),
            ("  DENY  ", "deny"),
            ("Ask", "ask"),
            ("bogus", "allow"),
            ("", "allow"),
        ],
    )
    def test_reader_normalizes(self, monkeypatch, raw, expected):
        self._patch_config(monkeypatch, raw)
        assert ResourceGovernor._sandbox_unavailable_action() == expected

    def test_reader_defaults_on_error(self, monkeypatch):
        import qwenpaw.config as config_mod

        def _boom(*_a, **_k):
            raise RuntimeError("nope")

        monkeypatch.setattr(config_mod, "load_config", _boom)
        assert ResourceGovernor._sandbox_unavailable_action() == "allow"
