# -*- coding: utf-8 -*-
"""Tests for MCP config-service pure helpers.

Covers _display_name_key, _mcp_access_rule_from_rule,
merge_update_with_existing, ensure_mcp_display_name_unique, and
mcp_access_policy_from_card, which the first config-service backfill
pass left uncovered.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.mcp import config_service as cs
from qwenpaw.app.mcp.schemas import MCPAccessPolicy, MCPClientInfo
from qwenpaw.drivers.constants import (
    CAPABILITY_KIND_TOOL,
    POLICY_EFFECT_ALLOW,
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
    PRINCIPAL_SOURCE_CHANNEL,
    PRINCIPAL_SUBJECT_ALL,
    PRINCIPAL_SUBJECT_USER,
)
from qwenpaw.drivers.policy_types import (
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
)


# ---------------------------------------------------------------------------
# _display_name_key
# ---------------------------------------------------------------------------


class TestDisplayNameKey:
    def test_normalized(self):
        assert cs._display_name_key("  My MCP  ") == "my mcp"

    def test_casefolded(self):
        assert cs._display_name_key("ABC") == "abc"

    def test_empty_none(self):
        assert cs._display_name_key(None) == ""
        assert cs._display_name_key("") == ""


# ---------------------------------------------------------------------------
# _mcp_access_rule_from_rule
# ---------------------------------------------------------------------------


def _policy_rule(
    effect=POLICY_EFFECT_ALLOW,
    kind=CAPABILITY_KIND_TOOL,
    name="search",
    source_type=PRINCIPAL_SOURCE_CHANNEL,
    source_value="console",
    subject_type=PRINCIPAL_SUBJECT_ALL,
    subject_value="",
    condition=None,
):
    return PolicyRule(
        effect=effect,
        target=PolicyTarget(kind=kind, name=name),
        principal=PolicyPrincipal(
            source_type=source_type,
            source_value=source_value,
            subject_type=subject_type,
            subject_value=subject_value,
        ),
        condition=condition,
    )


class TestMcpAccessRuleFromRule:
    def test_valid_rule_converted(self):
        result = cs._mcp_access_rule_from_rule(_policy_rule())
        assert result is not None
        assert result.source_value == "console"
        assert result.subject_type == PRINCIPAL_SUBJECT_ALL
        assert result.effect == POLICY_EFFECT_ALLOW

    def test_user_subject_rule(self):
        rule = _policy_rule(
            subject_type=PRINCIPAL_SUBJECT_USER,
            subject_value="alice",
        )
        result = cs._mcp_access_rule_from_rule(rule)
        assert result is not None
        assert result.subject_type == PRINCIPAL_SUBJECT_USER
        assert result.subject_value == "alice"

    def test_condition_rejected(self):
        rule = _policy_rule(condition={"if": True})
        assert cs._mcp_access_rule_from_rule(rule) is None

    def test_non_tool_kind_rejected(self):
        rule = _policy_rule(kind="resource")
        assert cs._mcp_access_rule_from_rule(rule) is None

    def test_empty_tool_name_rejected(self):
        rule = _policy_rule(name="")
        assert cs._mcp_access_rule_from_rule(rule) is None

    def test_unknown_effect_rejected(self):
        rule = _policy_rule(effect="unknown")
        assert cs._mcp_access_rule_from_rule(rule) is None

    def test_non_channel_source_falls_to_legacy(self):
        """A non-channel source with a wildcard subject resolves via the
        legacy path to a console/all rule rather than being rejected."""
        rule = _policy_rule(source_type="other")
        result = cs._mcp_access_rule_from_rule(rule)
        assert result is not None
        assert result.source_value == "console"

    def test_empty_subject_non_channel_returns_none(self):
        """Empty legacy subject and non-channel source yield None."""
        rule = _policy_rule(source_type="other")
        rule.subject = ""
        assert cs._mcp_access_rule_from_rule(rule) is None

    def test_ask_and_deny_effects_accepted(self):
        assert (
            cs._mcp_access_rule_from_rule(
                _policy_rule(effect=POLICY_EFFECT_ASK),
            )
            is not None
        )
        assert (
            cs._mcp_access_rule_from_rule(
                _policy_rule(effect=POLICY_EFFECT_DENY),
            )
            is not None
        )


# ---------------------------------------------------------------------------
# merge_update_with_existing
# ---------------------------------------------------------------------------


class TestMergeUpdateWithExisting:
    def _info(self):
        return MCPClientInfo(
            key="k1",
            name="My MCP",
            enabled=True,
            transport="stdio",
            command="mcp-server",
            args=["--stdio"],
            env={"K": "V"},
        )

    def test_no_updates_returns_create_request(self):
        from qwenpaw.app.mcp.schemas import MCPClientUpdateRequest

        info = self._info()
        result = cs.merge_update_with_existing(info, MCPClientUpdateRequest())
        assert result.name == "My MCP"
        assert result.command == "mcp-server"

    def test_updates_override_existing(self):
        from qwenpaw.app.mcp.schemas import MCPClientUpdateRequest

        info = self._info()
        result = cs.merge_update_with_existing(
            info,
            MCPClientUpdateRequest(name="Renamed"),
        )
        assert result.name == "Renamed"
        assert result.command == "mcp-server"

    def test_none_update_values_ignored(self):
        from qwenpaw.app.mcp.schemas import MCPClientUpdateRequest

        info = self._info()
        result = cs.merge_update_with_existing(
            info,
            MCPClientUpdateRequest(command=None),
        )
        assert result.command == "mcp-server"


# ---------------------------------------------------------------------------
# ensure_mcp_display_name_unique
# ---------------------------------------------------------------------------


class TestEnsureDisplayNameUnique:
    async def test_no_cards_ok(self):
        service = SimpleNamespace(list_cards=AsyncMock(return_value=[]))
        await cs.ensure_mcp_display_name_unique(
            service,
            "My MCP",
            client_key="k1",
        )

    async def test_same_client_key_ok(self):
        card = SimpleNamespace(name="k1", config={})
        service = SimpleNamespace(list_cards=AsyncMock(return_value=[card]))
        await cs.ensure_mcp_display_name_unique(
            service,
            "k1",
            client_key="k1",
        )

    async def test_conflict_with_existing_key(self):
        card = SimpleNamespace(name="duplicate", config={})
        service = SimpleNamespace(list_cards=AsyncMock(return_value=[card]))
        with pytest.raises(Exception) as exc_info:
            await cs.ensure_mcp_display_name_unique(
                service,
                "Duplicate",
                client_key="k1",
            )
        assert "conflicts" in str(exc_info.value.detail)

    async def test_conflict_with_existing_display_name(self):
        card = SimpleNamespace(
            name="k2",
            config={"display_name": "My MCP"},
        )
        service = SimpleNamespace(list_cards=AsyncMock(return_value=[card]))
        with pytest.raises(Exception) as exc_info:
            await cs.ensure_mcp_display_name_unique(
                service,
                "my mcp",
                client_key="k1",
            )
        assert "already exists" in str(exc_info.value.detail)

    async def test_case_insensitive_conflict(self):
        card = SimpleNamespace(name="MyMcp", config={})
        service = SimpleNamespace(list_cards=AsyncMock(return_value=[card]))
        with pytest.raises(Exception):
            await cs.ensure_mcp_display_name_unique(
                service,
                "mymcp",
                client_key="k1",
            )


# ---------------------------------------------------------------------------
# mcp_access_policy_from_card
# ---------------------------------------------------------------------------


class TestMcpAccessPolicyFromCard:
    def test_empty_policy(self):
        from qwenpaw.drivers.policy_types import DriverPolicy

        card = SimpleNamespace(policy=DriverPolicy())
        result = cs.mcp_access_policy_from_card(card)
        assert isinstance(result, MCPAccessPolicy)
        assert result.client_overrides == []
        assert result.tool_defaults == []
        assert result.tool_overrides == []

    def test_condition_rules_filtered(self):
        from qwenpaw.drivers.policy_types import DriverPolicy

        rule = _policy_rule(condition={"if": True})
        card = SimpleNamespace(policy=DriverPolicy(rules=[rule]))
        result = cs.mcp_access_policy_from_card(card)
        assert result.client_overrides == []
        assert result.tool_overrides == []
        assert result.tool_defaults == []

    def test_channel_rule_becomes_tool_override(self):
        from qwenpaw.drivers.policy_types import DriverPolicy

        rule = _policy_rule(
            source_type=PRINCIPAL_SOURCE_CHANNEL,
            source_value="console",
            subject_type=PRINCIPAL_SUBJECT_ALL,
            name="search",
        )
        card = SimpleNamespace(policy=DriverPolicy(rules=[rule]))
        result = cs.mcp_access_policy_from_card(card)
        assert len(result.tool_overrides) == 1
        assert result.tool_overrides[0].tool_name == "search"
