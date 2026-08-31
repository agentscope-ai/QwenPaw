# -*- coding: utf-8 -*-
"""Tests for MCP access-policy transformation helpers.

Covers ``driver_policy_from_mcp_access_update`` (the console -> driver
policy projection), ``_legacy_subject_access_rule`` (legacy subject
string parsing), and ``_is_mcp_tool_default_rule`` (default-rule shape
detection), which previously had no direct coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import pytest
from fastapi import HTTPException

from qwenpaw.app.mcp.config_service import (
    _is_mcp_tool_default_rule,
    _legacy_subject_access_rule,
    driver_policy_from_mcp_access_update,
)
from qwenpaw.app.mcp.schemas import (
    MCPAccessPolicy,
    MCPAccessRule,
    MCPToolAccessOverride,
    MCPToolDefaultPolicy,
)
from qwenpaw.drivers.policy_types import (
    DriverPolicy,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
)


def _managed_tool_default_rule(tool_name: str = "search") -> PolicyRule:
    """A rule shaped like a console-managed MCP tool default."""
    return PolicyRule(
        subject="*",
        effect="allow",
        target=PolicyTarget(kind="tool", name=tool_name),
        principal=PolicyPrincipal(),
    )


def _unmanaged_rule() -> PolicyRule:
    """A rule that is not console-managed (keeps a real subject)."""
    return PolicyRule(
        subject="alice",
        effect="deny",
        target=PolicyTarget(kind="other", name="something"),
        principal=PolicyPrincipal(),
    )


# ---------------------------------------------------------------------------
# driver_policy_from_mcp_access_update
# ---------------------------------------------------------------------------


class TestDriverPolicyFromMcpAccessUpdate:
    def test_unmanaged_rules_are_preserved(self):
        existing = DriverPolicy(
            default_effect="deny",
            rules=[_unmanaged_rule()],
        )
        access = MCPAccessPolicy(default_effect="allow")
        result = driver_policy_from_mcp_access_update(existing, access)
        assert result.default_effect == "allow"
        assert len(result.rules) == 1
        assert result.rules[0].subject == "alice"

    def test_previous_managed_rules_are_dropped(self):
        existing = DriverPolicy(
            default_effect="deny",
            rules=[_managed_tool_default_rule("old_tool"), _unmanaged_rule()],
        )
        access = MCPAccessPolicy(default_effect="allow")
        result = driver_policy_from_mcp_access_update(existing, access)
        # old managed rule removed, unmanaged kept.
        assert len(result.rules) == 1
        assert result.rules[0].subject == "alice"

    def test_tool_defaults_become_managed_rules(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            default_effect="allow",
            tool_defaults=[
                MCPToolDefaultPolicy(tool_name="search", effect="allow"),
                MCPToolDefaultPolicy(tool_name="write", effect="deny"),
            ],
        )
        result = driver_policy_from_mcp_access_update(existing, access)
        assert len(result.rules) == 2
        names = {rule.target.name for rule in result.rules}
        assert names == {"search", "write"}

    def test_duplicate_tool_defaults_deduplicated(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_defaults=[
                MCPToolDefaultPolicy(tool_name="search", effect="allow"),
                MCPToolDefaultPolicy(tool_name="search", effect="deny"),
            ],
        )
        result = driver_policy_from_mcp_access_update(existing, access)
        assert len(result.rules) == 1

    def test_empty_tool_default_name_raises_400(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_defaults=[MCPToolDefaultPolicy(tool_name="  ", effect="allow")],
        )
        with pytest.raises(HTTPException) as exc_info:
            driver_policy_from_mcp_access_update(existing, access)
        assert exc_info.value.status_code == 400

    def test_wildcard_tool_default_name_raises_400(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_defaults=[MCPToolDefaultPolicy(tool_name="*", effect="allow")],
        )
        with pytest.raises(HTTPException) as exc_info:
            driver_policy_from_mcp_access_update(existing, access)
        assert exc_info.value.status_code == 400

    def test_client_override_targets_wildcard(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            client_overrides=[
                MCPAccessRule(
                    source_value="dingtalk",
                    subject_type="all",
                    effect="allow",
                ),
            ],
        )
        result = driver_policy_from_mcp_access_update(existing, access)
        assert len(result.rules) == 1
        rule = result.rules[0]
        assert rule.target.name == "*"  # client-wide
        assert rule.principal.source_value == "dingtalk"

    def test_tool_override_targets_named_tool(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_overrides=[
                MCPToolAccessOverride(
                    tool_name="search",
                    source_value="console",
                    subject_type="user",
                    subject_value="u1",
                    effect="ask",
                ),
            ],
        )
        result = driver_policy_from_mcp_access_update(existing, access)
        assert len(result.rules) == 1
        rule = result.rules[0]
        assert rule.target.name == "search"
        assert rule.principal.subject_value == "u1"
        assert rule.effect == "ask"

    def test_subject_all_clears_subject_value(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_overrides=[
                MCPToolAccessOverride(
                    tool_name="search",
                    source_value="console",
                    subject_type="all",
                    subject_value="should-be-cleared",
                    effect="allow",
                ),
            ],
        )
        result = driver_policy_from_mcp_access_update(existing, access)
        rule = result.rules[0]
        assert rule.principal.subject_type == "all"
        assert rule.principal.subject_value == ""

    def test_user_subject_requires_value(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_overrides=[
                MCPToolAccessOverride(
                    tool_name="search",
                    source_value="console",
                    subject_type="user",
                    subject_value="",
                    effect="allow",
                ),
            ],
        )
        with pytest.raises(HTTPException) as exc_info:
            driver_policy_from_mcp_access_update(existing, access)
        assert exc_info.value.status_code == 400

    def test_empty_source_value_raises_400(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        access = MCPAccessPolicy(
            tool_overrides=[
                MCPToolAccessOverride(
                    tool_name="search",
                    source_value="  ",
                    subject_type="all",
                    effect="allow",
                ),
            ],
        )
        with pytest.raises(HTTPException) as exc_info:
            driver_policy_from_mcp_access_update(existing, access)
        assert exc_info.value.status_code == 400

    def test_duplicate_overrides_deduplicated(self):
        existing = DriverPolicy(default_effect="deny", rules=[])
        override = MCPToolAccessOverride(
            tool_name="search",
            source_value="console",
            subject_type="all",
            effect="allow",
        )
        access = MCPAccessPolicy(tool_overrides=[override, override])
        result = driver_policy_from_mcp_access_update(existing, access)
        assert len(result.rules) == 1


# ---------------------------------------------------------------------------
# _legacy_subject_access_rule
# ---------------------------------------------------------------------------


class TestLegacySubjectAccessRule:
    def test_empty_subject_returns_none(self):
        rule = PolicyRule(
            subject="   ",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        assert _legacy_subject_access_rule(rule) is None

    def test_wildcard_subject_is_console_all(self):
        rule = PolicyRule(
            subject="*",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        parsed = _legacy_subject_access_rule(rule)
        assert parsed is not None
        assert parsed.source_value == "console"
        assert parsed.subject_type == "all"
        assert parsed.effect == "allow"

    def test_channel_prefix_parsed(self):
        rule = PolicyRule(
            subject="channel:dingtalk",
            effect="deny",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        parsed = _legacy_subject_access_rule(rule)
        assert parsed is not None
        assert parsed.source_value == "dingtalk"
        assert parsed.subject_type == "all"
        assert parsed.effect == "deny"

    def test_channel_prefix_empty_value_defaults_to_wildcard(self):
        rule = PolicyRule(
            subject="channel:",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        parsed = _legacy_subject_access_rule(rule)
        assert parsed is not None
        assert parsed.source_value == "*"

    def test_user_prefix_parsed(self):
        rule = PolicyRule(
            subject="user:alice",
            effect="ask",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        parsed = _legacy_subject_access_rule(rule)
        assert parsed is not None
        assert parsed.subject_type == "user"
        assert parsed.subject_value == "alice"

    def test_user_wildcard_is_all(self):
        rule = PolicyRule(
            subject="user:*",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        parsed = _legacy_subject_access_rule(rule)
        assert parsed is not None
        assert parsed.subject_type == "all"
        assert parsed.subject_value == ""

    def test_unknown_subject_shape_returns_none(self):
        rule = PolicyRule(
            subject="role:admin",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        assert _legacy_subject_access_rule(rule) is None


# ---------------------------------------------------------------------------
# _is_mcp_tool_default_rule
# ---------------------------------------------------------------------------


class TestIsMcpToolDefaultRule:
    def test_valid_default_rule(self):
        assert _is_mcp_tool_default_rule(_managed_tool_default_rule()) is True

    def test_wildcard_tool_name_rejected(self):
        rule = _managed_tool_default_rule("*")
        assert _is_mcp_tool_default_rule(rule) is False

    def test_empty_tool_name_rejected(self):
        rule = _managed_tool_default_rule("")
        assert _is_mcp_tool_default_rule(rule) is False

    def test_non_tool_kind_rejected(self):
        rule = PolicyRule(
            subject="*",
            effect="allow",
            target=PolicyTarget(kind="other", name="x"),
            principal=PolicyPrincipal(),
        )
        assert _is_mcp_tool_default_rule(rule) is False

    def test_specific_subject_rejected(self):
        rule = PolicyRule(
            subject="alice",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
        )
        assert _is_mcp_tool_default_rule(rule) is False

    def test_non_default_principal_rejected(self):
        rule = PolicyRule(
            subject="*",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(source_value="console"),
        )
        assert _is_mcp_tool_default_rule(rule) is False

    def test_condition_present_rejected(self):
        rule = PolicyRule(
            subject="*",
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(),
            condition={"some": "cond"},
        )
        assert _is_mcp_tool_default_rule(rule) is False
