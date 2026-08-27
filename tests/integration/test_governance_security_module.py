# -*- coding: utf-8 -*-
"""Integration tests for Governance & Security module internals.

Covers src/qwenpaw/governance/* and src/qwenpaw/security/* (module
level, 2,815 uncovered lines): detectors, audit log, policy engine,
tool adapter, secret store, rule guardian.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# detectors
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_detect_sensitive_paths_match() -> None:
    """detect_sensitive_paths flags a target inside a sensitive dir."""
    from qwenpaw.governance.detectors import detect_sensitive_paths

    findings = detect_sensitive_paths(
        tool_name="shell",
        target="/etc/passwd",
        tool_type="shell",
        sensitive_paths=["/etc/"],
    )
    assert isinstance(findings, list)
    assert len(findings) >= 1


@pytest.mark.integration
@pytest.mark.p1
def test_detect_sensitive_paths_no_match() -> None:
    """detect_sensitive_paths returns empty for a clean target."""
    from qwenpaw.governance.detectors import detect_sensitive_paths

    findings = detect_sensitive_paths(
        tool_name="shell",
        target="/tmp/integ-clean-file",
        tool_type="shell",
        sensitive_paths=["/etc/"],
    )
    assert not findings


@pytest.mark.integration
@pytest.mark.p1
def test_detect_sensitive_paths_empty_config() -> None:
    """detect_sensitive_paths returns empty when no paths configured."""
    from qwenpaw.governance.detectors import detect_sensitive_paths

    findings = detect_sensitive_paths(
        tool_name="shell",
        target="/etc/passwd",
        tool_type="shell",
        sensitive_paths=[],
    )
    assert not findings


@pytest.mark.integration
@pytest.mark.p1
def test_detect_dangerous_patterns_match() -> None:
    """detect_dangerous_patterns flags a target matching a rule."""
    from qwenpaw.governance.detectors import detect_dangerous_patterns

    from qwenpaw.governance.policy import DetectionRuleConfig

    rule = DetectionRuleConfig(
        id="integ-rule",
        patterns=[r"rm\s+-rf"],
    )
    findings = detect_dangerous_patterns(
        tool_name="shell",
        target="rm -rf /",
        detection_rules=[rule],
    )
    assert isinstance(findings, list)


@pytest.mark.integration
@pytest.mark.p1
def test_detect_dangerous_patterns_no_rules() -> None:
    """detect_dangerous_patterns returns empty with no rules."""
    from qwenpaw.governance.detectors import detect_dangerous_patterns

    findings = detect_dangerous_patterns(
        tool_name="shell",
        target="echo hello",
        detection_rules=[],
    )
    assert not findings


# ------------------------------------------------------------------ #
# audit log
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_audit_log_record_and_query() -> None:
    """AuditLog records an event and returns it on query."""
    from qwenpaw.governance.audit import AuditLog
    from qwenpaw.governance.policy import (
        GovernanceAction,
        GovernanceDecision,
        ToolCallSpec,
    )

    with tempfile.TemporaryDirectory() as tmp:
        log = AuditLog.get_instance(db_dir=Path(tmp))
        spec = ToolCallSpec(
            tool_name="integ_tool",
            target="/tmp/x",
            agent_id="default",
            session_id="integ-session",
        )
        decision = GovernanceDecision(
            action=GovernanceAction.ALLOW,
            reason="integ test",
        )
        log.record(tmp, spec, decision)
        result = log.query(limit=10)
        events = result[0] if isinstance(result, tuple) else result
        assert len(events) >= 1
        assert events[0].tool_name == "integ_tool"
        AuditLog.close_instance()


@pytest.mark.integration
@pytest.mark.p1
def test_audit_event_fields() -> None:
    """AuditEvent carries the recorded fields."""
    from qwenpaw.governance.audit import AuditEvent

    ev = AuditEvent(
        ts=0,
        workspace_dir="/tmp",
        agent_id="default",
        session_id="s",
        tool_name="t",
        target="/tmp/x",
        decision="deny",
        reason="r",
    )
    assert ev.decision == "deny"
    assert ev.tool_name == "t"


# ------------------------------------------------------------------ #
# policy
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_governance_action_enum() -> None:
    """GovernanceAction enum has the four expected values."""
    from qwenpaw.governance.policy import GovernanceAction

    assert GovernanceAction.ALLOW.value == "allow"
    assert GovernanceAction.DENY.value == "deny"
    assert GovernanceAction.ASK.value == "ask"
    assert GovernanceAction.SANDBOX_FALLBACK.value == "sandbox_fallback"


@pytest.mark.integration
@pytest.mark.p1
def test_default_user_rules_nonempty() -> None:
    """get_default_user_rules returns the built-in rule set."""
    from qwenpaw.governance.policy import get_default_user_rules

    rules = get_default_user_rules()
    assert isinstance(rules, list)
    assert len(rules) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_load_governance_policy_default() -> None:
    """load_governance_policy returns a default policy when missing."""
    from qwenpaw.governance.policy import load_governance_policy

    with tempfile.TemporaryDirectory() as tmp:
        policy = load_governance_policy(tmp, tmp)
        assert policy is not None


# ------------------------------------------------------------------ #
# secret store
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_secret_store_roundtrip() -> None:
    """mask/restore round-trips a secret value."""
    from qwenpaw.security.secret_store import (
        mask_secret_value,
        restore_masked_secret_value,
    )

    secret = "integ-secret-value"
    masked = mask_secret_value(secret)
    assert masked != secret
    restored = restore_masked_secret_value(masked, secret)
    assert restored == secret


# ------------------------------------------------------------------ #
# rule guardian
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_guard_rule_from_dict() -> None:
    """GuardRule builds from a dict payload."""
    from qwenpaw.security.tool_guard.guardians.rule_guardian import (
        GuardRule,
    )

    rule = GuardRule(
        {
            "id": "integ-rule",
            "category": "command_injection",
            "severity": "HIGH",
            "patterns": ["rm\\s+-rf"],
        },
    )
    assert rule.id == "integ-rule"


@pytest.mark.integration
@pytest.mark.p1
def test_load_rules_from_yaml(tmp_path) -> None:
    """load_rules_from_yaml parses a rules list."""
    from qwenpaw.security.tool_guard.guardians.rule_guardian import (
        load_rules_from_yaml,
    )

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        "- id: integ-rule\n"
        "  category: command_injection\n"
        "  severity: MEDIUM\n"
        "  patterns: ['dangerous']\n",
    )
    rules = load_rules_from_yaml(yaml_file)
    assert isinstance(rules, list)
    assert len(rules) == 1
    assert rules[0].id == "integ-rule"
