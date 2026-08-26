# -*- coding: utf-8 -*-
"""Integration tests for the governance module.

Tests the governance subsystem's public API: GovernanceAction enum,
GovernanceDecision dataclass, and ResourceGovernor basic operations.
These are module-level integration tests.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_governance_action_enum_values() -> None:
    """Test purpose:
    - Verify GovernanceAction enum has all expected values. The policy
      engine returns these actions for tool call decisions.

    Test flow:
    1. Import GovernanceAction.
    2. Verify all 4 actions exist.
    """
    from qwenpaw.governance.policy import GovernanceAction

    assert GovernanceAction.ALLOW.value == "allow"
    assert GovernanceAction.DENY.value == "deny"
    assert GovernanceAction.ASK.value == "ask"
    assert GovernanceAction.SANDBOX_FALLBACK.value == "sandbox_fallback"


@pytest.mark.integration
@pytest.mark.p1
def test_governance_decision_dataclass() -> None:
    """Test purpose:
    - Verify GovernanceDecision can be created with required fields.
      This is the return type of policy evaluation.

    Test flow:
    1. Import GovernanceDecision.
    2. Create instance with ALLOW action.
    3. Verify fields.
    """
    from qwenpaw.governance.policy import GovernanceAction, GovernanceDecision

    decision = GovernanceDecision(
        action=GovernanceAction.ALLOW,
        reason="test reason",
    )
    assert decision.action == GovernanceAction.ALLOW
    assert decision.reason == "test reason"


@pytest.mark.integration
@pytest.mark.p1
def test_governance_decision_with_sandbox_config() -> None:
    """Test purpose:
    - Verify GovernanceDecision can carry sandbox_config for
      SANDBOX_FALLBACK action.

    Test flow:
    1. Create GovernanceDecision with SANDBOX_FALLBACK and sandbox_config.
    2. Verify sandbox_config is accessible.
    """
    from qwenpaw.governance.policy import GovernanceAction, GovernanceDecision
    from qwenpaw.sandbox.config import SandboxConfig, SandboxMode

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp",
    )
    decision = GovernanceDecision(
        action=GovernanceAction.SANDBOX_FALLBACK,
        reason="fallback to sandbox",
        sandbox_config=config,
    )
    assert decision.action == GovernanceAction.SANDBOX_FALLBACK
    assert decision.sandbox_config is not None
    assert decision.sandbox_config.mode == SandboxMode.NONE


@pytest.mark.integration
@pytest.mark.p1
def test_resource_governor_creation() -> None:
    """Test purpose:
    - Verify ResourceGovernor can be instantiated. This is the main
      entry point for governance policy enforcement.

    Test flow:
    1. Import ResourceGovernor.
    2. Create instance.
    3. Verify it has expected methods.
    """
    import tempfile
    from qwenpaw.governance import ResourceGovernor

    with tempfile.TemporaryDirectory() as tmpdir:
        governor = ResourceGovernor(workspace_dir=tmpdir)
        assert hasattr(governor, "assert_policy")
        assert hasattr(governor, "audit")


@pytest.mark.integration
@pytest.mark.p1
def test_governance_init_exports() -> None:
    """Test purpose:
    - Verify qwenpaw.governance package exports expected symbols.

    Test flow:
    1. Import from qwenpaw.governance.
    2. Verify all expected symbols are accessible.
    """
    from qwenpaw.governance import (
        GovernanceAction,
        GovernanceDecision,
        PolicyGuardedTool,
        ResourceGovernor,
    )

    assert GovernanceAction is not None
    assert GovernanceDecision is not None
    assert PolicyGuardedTool is not None
    assert ResourceGovernor is not None


@pytest.mark.integration
@pytest.mark.p1
def test_governance_detectors_module_exists() -> None:
    """Test purpose:
    - Verify governance.detectors module can be imported. Contains
      detection logic for sensitive operations.

    Test flow:
    1. Import qwenpaw.governance.detectors.
    2. Verify import succeeds.
    """
    from qwenpaw.governance import detectors

    assert detectors is not None


@pytest.mark.integration
@pytest.mark.p1
def test_governance_tool_registry_module_exists() -> None:
    """Test purpose:
    - Verify governance.tool_registry module can be imported. Contains
      tool registration logic for governance.

    Test flow:
    1. Import qwenpaw.governance.tool_registry.
    2. Verify import succeeds.
    """
    from qwenpaw.governance import tool_registry

    assert tool_registry is not None


@pytest.mark.integration
@pytest.mark.p1
def test_governance_tool_adapter_module_exists() -> None:
    """Test purpose:
    - Verify governance.tool_adapter module can be imported. Contains
      PolicyGuardedTool adapter.

    Test flow:
    1. Import qwenpaw.governance.tool_adapter.
    2. Verify import succeeds.
    """
    from qwenpaw.governance import tool_adapter

    assert tool_adapter is not None


@pytest.mark.integration
@pytest.mark.p1
def test_governance_generalize_module_exists() -> None:
    """Test purpose:
    - Verify governance.generalize module can be imported. Contains
      generalization logic for policy rules.

    Test flow:
    1. Import qwenpaw.governance.generalize.
    2. Verify import succeeds.
    """
    from qwenpaw.governance import generalize

    assert generalize is not None


@pytest.mark.integration
@pytest.mark.p1
def test_governance_audit_module_exists() -> None:
    """Test purpose:
    - Verify governance.audit module can be imported. Contains audit
      logging for governance decisions.

    Test flow:
    1. Import qwenpaw.governance.audit.
    2. Verify import succeeds.
    """
    from qwenpaw.governance import audit

    assert audit is not None
