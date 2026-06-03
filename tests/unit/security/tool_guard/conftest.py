# -*- coding: utf-8 -*-
"""Shared fixtures for tool_guard tests."""
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


# ---------------------------------------------------------------------------
# Config / env fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """Patch ``qwenpaw.config.load_config`` to return a mock
    with tool_guard config."""
    tool_guard_cfg = MagicMock()
    tool_guard_cfg.guarded_tools = None
    tool_guard_cfg.denied_tools = None
    tool_guard_cfg.auto_denied_rules = None

    security_cfg = MagicMock()
    security_cfg.tool_guard = tool_guard_cfg

    app_cfg = MagicMock()
    app_cfg.security = security_cfg

    with patch("qwenpaw.config.load_config", return_value=app_cfg) as patched:
        yield patched


@pytest.fixture
def mock_env_loader():
    """Patch ``EnvVarLoader.get_str`` so no real env vars are read."""
    with patch(
        "qwenpaw.constant.EnvVarLoader.get_str",
        return_value="",
    ) as patched:
        yield patched


@pytest.fixture
def mock_workspace(tmp_path: Path):
    """Provide a tmp_path workspace and patch ``get_current_workspace_dir``."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with patch(
        "qwenpaw.config.context.get_current_workspace_dir",
        return_value=workspace,
    ):
        yield workspace


# ---------------------------------------------------------------------------
# Model instance fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def guard_findings():
    """Create sample GuardFinding objects for reuse."""
    critical_finding = GuardFinding(
        id="f-001",
        rule_id="CMD-001",
        category=GuardThreatCategory.COMMAND_INJECTION,
        severity=GuardSeverity.CRITICAL,
        title="Dangerous shell command",
        description="Command contains destructive pattern 'rm -rf /'",
        tool_name="execute_shell_command",
        param_name="command",
        matched_value="rm -rf /",
        matched_pattern=r"rm\s+-rf\s+/",
        snippet="rm -rf /",
        remediation="Reject or sandbox destructive commands",
        guardian="rule_guardian",
    )

    high_finding = GuardFinding(
        id="f-002",
        rule_id="PATH-001",
        category=GuardThreatCategory.PATH_TRAVERSAL,
        severity=GuardSeverity.HIGH,
        title="Path traversal attempt",
        description="File path escapes workspace boundary",
        tool_name="read_file",
        param_name="path",
        matched_value="../../etc/passwd",
        matched_pattern=r"\.\.[\\/]",
        snippet="../../etc/passwd",
        remediation="Validate paths stay within workspace",
        guardian="file_guardian",
    )

    medium_finding = GuardFinding(
        id="f-003",
        rule_id="NET-001",
        category=GuardThreatCategory.NETWORK_ABUSE,
        severity=GuardSeverity.MEDIUM,
        title="Suspicious network access",
        description="Tool attempts outbound connection",
        tool_name="execute_shell_command",
        param_name="command",
        matched_value="curl http://evil.com",
        remediation=None,
        guardian="rule_guardian",
    )

    return {
        "critical": critical_finding,
        "high": high_finding,
        "medium": medium_finding,
    }


@pytest.fixture
def safe_result():
    """Return a ToolGuardResult with no findings."""
    return ToolGuardResult(
        tool_name="read_file",
        params={"path": "/tmp/safe.txt"},
        findings=[],
        guard_duration_seconds=0.01,
    )


@pytest.fixture
def unsafe_result(guard_findings):
    """Return a ToolGuardResult with a CRITICAL finding."""
    return ToolGuardResult(
        tool_name="execute_shell_command",
        params={"command": "rm -rf /"},
        findings=[guard_findings["critical"]],
        guard_duration_seconds=0.05,
    )
