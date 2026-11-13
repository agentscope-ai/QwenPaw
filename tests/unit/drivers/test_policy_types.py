# -*- coding: utf-8 -*-
"""Tests for Driver policy coercion and typed shape."""
from __future__ import annotations

import pytest

from qwenpaw.drivers.constants import (
    POLICY_EFFECT_ALLOW,
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
    POLICY_TARGET_WILDCARD,
)
from qwenpaw.drivers.errors import DriverCardError
from qwenpaw.drivers.policy_types import (
    DriverPolicy,
    PolicyCondition,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
    TimeRange,
    coerce_driver_policy,
)


class TestCoerceDriverPolicy:
    """coerce_driver_policy normalizes legacy/loose input into a safe
    DriverPolicy, defaulting to DENY for unknown shapes."""

    def test_none_returns_default_deny(self):
        # None means "no policy configured" → explicit default-deny, not error.
        p = coerce_driver_policy(None)
        assert p.default_effect == POLICY_EFFECT_DENY
        assert not p.rules

    def test_unknown_type_returns_default(self):
        # Non-mapping/list/Policy value treated as "no policy" — defensive.
        p = coerce_driver_policy("not-a-policy")
        assert isinstance(p, DriverPolicy)
        assert not p.rules

    def test_list_of_rules(self):
        p = coerce_driver_policy([{"effect": "allow", "subject": "*"}])
        assert p.default_effect == POLICY_EFFECT_DENY
        assert len(p.rules) == 1
        assert p.rules[0].effect == POLICY_EFFECT_ALLOW

    def test_dict_with_rules(self):
        p = coerce_driver_policy(
            {"default_effect": "allow", "rules": [{"effect": "deny"}]},
        )
        assert p.default_effect == POLICY_EFFECT_ALLOW
        assert p.rules[0].effect == POLICY_EFFECT_DENY

    def test_dict_rules_none_treated_as_empty(self):
        p = coerce_driver_policy({"rules": None})
        assert not p.rules

    def test_dict_rules_not_list_raises(self):
        with pytest.raises(DriverCardError, match="rules must be a list"):
            coerce_driver_policy({"rules": "x"})

    def test_existing_policy_is_copied_not_aliased(self):
        # Passing a DriverPolicy must return a NEW object with coerced
        # rules, so the caller's input is never mutated downstream.
        src = DriverPolicy(
            default_effect="allow",
            rules=[PolicyRule(effect="ask", subject="*")],
        )
        out = coerce_driver_policy(src)
        assert out is not src
        assert out.rules is not src.rules
        assert out.rules[0].effect == POLICY_EFFECT_ASK

    def test_invalid_rule_effect_raises(self):
        # Security: an unknown effect must never fall through to a
        # permissive default — reject loudly.
        with pytest.raises(DriverCardError, match="invalid policy effect"):
            coerce_driver_policy({"rules": [{"effect": "permit"}]})

    def test_invalid_default_effect_raises(self):
        with pytest.raises(DriverCardError, match="invalid policy effect"):
            coerce_driver_policy({"default_effect": "maybe"})


class TestCoercePolicyRule:
    """Rule coercion preserves structured selectors and applies safe
    wildcards when fields are missing."""

    def test_rule_from_dict_missing_principal_uses_wildcards(self):
        p = coerce_driver_policy([{"effect": "allow"}])
        rule = p.rules[0]
        assert rule.principal.source_type == POLICY_TARGET_WILDCARD
        assert rule.principal.subject_value == POLICY_TARGET_WILDCARD

    def test_rule_from_dict_with_principal(self):
        p = coerce_driver_policy(
            [
                {
                    "effect": "allow",
                    "principal": {
                        "source_type": "channel",
                        "subject_type": "user",
                        "subject_value": "alice",
                    },
                },
            ],
        )
        rule = p.rules[0]
        assert rule.principal.source_type == "channel"
        assert rule.principal.subject_value == "alice"
        # missing source_value falls back to wildcard, not None
        assert rule.principal.source_value == POLICY_TARGET_WILDCARD

    def test_rule_from_policy_rule_object(self):
        src = PolicyRule(
            effect="deny",
            subject="bob",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(subject_value="bob"),
        )
        p = coerce_driver_policy([src])
        out = p.rules[0]
        assert out.subject == "bob"
        assert out.target.name == "x"
        assert out.principal.subject_value == "bob"

    def test_rule_with_target_dict(self):
        p = coerce_driver_policy(
            [{"effect": "ask", "target": {"kind": "tool", "name": "fs"}}],
        )
        rule = p.rules[0]
        assert rule.target.kind == "tool"
        assert rule.target.name == "fs"

    def test_rule_missing_effect_defaults_to_ask(self):
        # A rule dict missing 'effect' defaults to ASK (least privilege for
        # ambiguous rules), not allow.
        p = coerce_driver_policy([{"subject": "x"}])
        assert p.rules[0].effect == POLICY_EFFECT_ASK


class TestDriverPolicyContainer:
    """DriverPolicy acts as an iterable, indexable container of rules."""

    def test_iter_len_getitem(self):
        r1 = PolicyRule(effect="allow")
        r2 = PolicyRule(effect="deny")
        p = DriverPolicy(default_effect="allow", rules=[r1, r2])
        assert len(p) == 2
        assert list(p) == [r1, r2]
        assert p[0] == r1
        assert p[1] == r2


class TestPolicyDataclassDefaults:
    def test_timerange_defaults_none(self):
        tr = TimeRange()
        assert tr.after is None
        assert tr.before is None
        assert tr.weekdays is None

    def test_policy_condition_default(self):
        assert PolicyCondition().time_range is None
