# -*- coding: utf-8 -*-
"""Extra (non-primary) project directories in governance.

Every bound root gets a system-managed ALLOW rule and a sandbox mount;
unbinding a directory drops its rule again.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.governance.policy import (
    EXTRA_PROJECT_DIR_RULE_REASON,
    GovernanceAction,
    GovernanceRule,
    ToolCallSpec,
    _sync_extra_project_dir_rules,
    load_governance_policy,
)
from qwenpaw.governance.resource_governor import ResourceGovernor

_WS = "/tmp/qp-gov-ws"
_PRIMARY = "/tmp/qp-gov-primary"
_EXTRA_A = "/tmp/qp-gov-extra-a"
_EXTRA_B = "/tmp/qp-gov-extra-b"


# ---------------------------------------------------------------------------
# Policy rule sync
# ---------------------------------------------------------------------------


def test_extra_dirs_get_allow_rules():
    rules = _sync_extra_project_dir_rules(
        [],
        _WS,
        _PRIMARY,
        [_EXTRA_A, _EXTRA_B],
    )
    matches = {rule.match for rule in rules}
    assert f"*({_EXTRA_A}/**)" in matches
    assert f"*({_EXTRA_B}/**)" in matches
    assert all(
        rule.action == GovernanceAction.ALLOW for rule in rules
    )
    assert all(
        rule.reason == EXTRA_PROJECT_DIR_RULE_REASON for rule in rules
    )


def test_primary_and_workspace_are_not_duplicated_as_extras():
    rules = _sync_extra_project_dir_rules(
        [],
        _WS,
        _PRIMARY,
        [_PRIMARY, _WS, _EXTRA_A],
    )
    assert [rule.match for rule in rules] == [f"*({_EXTRA_A}/**)"]


def test_unbinding_drops_the_rule():
    bound = _sync_extra_project_dir_rules(
        [],
        _WS,
        _PRIMARY,
        [_EXTRA_A, _EXTRA_B],
    )
    # Second sync without extra B: its rule must disappear.
    after = _sync_extra_project_dir_rules(
        bound,
        _WS,
        _PRIMARY,
        [_EXTRA_A],
    )
    matches = {rule.match for rule in after}
    assert f"*({_EXTRA_A}/**)" in matches
    assert f"*({_EXTRA_B}/**)" not in matches


def test_unrelated_user_rules_survive_sync():
    user_rules = [
        GovernanceRule(
            match="Bash(npm *)",
            action=GovernanceAction.ALLOW,
            reason="user added",
        ),
    ]
    after = _sync_extra_project_dir_rules(
        user_rules,
        _WS,
        _PRIMARY,
        [_EXTRA_A],
    )
    assert any(rule.match == "Bash(npm *)" for rule in after)


def test_load_governance_policy_syncs_extras(tmp_path):
    policy = load_governance_policy(
        str(tmp_path),
        _WS,
        _PRIMARY,
        extra_project_dirs=[_EXTRA_A],
    )
    matches = {rule.match for rule in policy.user_rules}
    assert f"*({_EXTRA_A}/**)" in matches


# ---------------------------------------------------------------------------
# Governor: dedupe + sandbox mounts
# ---------------------------------------------------------------------------


def test_governor_dedupes_extra_dirs():
    governor = ResourceGovernor(
        _WS,
        coding_project_dir=_PRIMARY,
        extra_project_dirs=[
            _EXTRA_A,
            _EXTRA_A,  # duplicate
            _PRIMARY,  # same as primary
            _WS,  # same as workspace
            _EXTRA_B,
        ],
    )
    assert governor.extra_project_dirs == [
        Path(_EXTRA_A),
        Path(_EXTRA_B),
    ]


def test_sandbox_config_mounts_every_root(tmp_path):
    governor = ResourceGovernor(
        _WS,
        governance_dir=str(tmp_path),
        coding_project_dir=_PRIMARY,
        extra_project_dirs=[_EXTRA_A],
    )
    governor._policy = load_governance_policy(
        str(tmp_path / "policy"),
        _WS,
        _PRIMARY,
        extra_project_dirs=[_EXTRA_A],
    )

    spec = ToolCallSpec(
        tool_name="Bash",
        target="echo hi",
        agent_id="a",
        session_id="s",
    )
    config = governor.compile_sandbox_config(spec)
    mounted = {mount.path for mount in config.mounts}
    assert _WS in mounted
    assert _PRIMARY in mounted
    assert _EXTRA_A in mounted
    # All project roots are writable mounts.
    by_path = {mount.path: mount for mount in config.mounts}
    assert by_path[_PRIMARY].writable is True
    assert by_path[_EXTRA_A].writable is True


@pytest.mark.parametrize("extra", [_EXTRA_A])
def test_extra_mounts_are_not_duplicated(tmp_path, extra):
    governor = ResourceGovernor(
        _WS,
        governance_dir=str(tmp_path),
        coding_project_dir=_PRIMARY,
        extra_project_dirs=[extra, extra],
    )
    governor._policy = load_governance_policy(
        str(tmp_path / "policy"),
        _WS,
        _PRIMARY,
        extra_project_dirs=[extra],
    )
    spec = ToolCallSpec(
        tool_name="Bash",
        target="echo hi",
        agent_id="a",
        session_id="s",
    )
    config = governor.compile_sandbox_config(spec)
    paths = [mount.path for mount in config.mounts]
    assert paths.count(extra) == 1
