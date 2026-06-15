# -*- coding: utf-8 -*-
"""Driver policy data types and coercion helpers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, cast, get_args

from .capabilities import CapabilityKind
from .constants import (
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
    POLICY_EFFECTS,
    POLICY_TARGET_WILDCARD,
)
from .errors import DriverCardError

PolicyEffect: TypeAlias = Literal["allow", "deny", "ask"]
PolicyTargetKind: TypeAlias = CapabilityKind | Literal["*"]

ALLOWED_POLICY_EFFECTS: frozenset[str] = POLICY_EFFECTS
ALLOWED_POLICY_TARGET_KINDS: frozenset[str] = frozenset(
    {*get_args(CapabilityKind), POLICY_TARGET_WILDCARD},
)
_MISSING = object()

__all__ = [
    "ALLOWED_POLICY_EFFECTS",
    "ALLOWED_POLICY_TARGET_KINDS",
    "DriverPolicy",
    "PolicyCondition",
    "PolicyEffect",
    "PolicyPrincipal",
    "PolicyRule",
    "PolicyTarget",
    "PolicyTargetKind",
    "TimeRange",
    "coerce_driver_policy",
]


@dataclass
class TimeRange:
    after: str | None = None
    before: str | None = None
    weekdays: list[int] | None = None


@dataclass
class PolicyCondition:
    time_range: TimeRange | None = None


@dataclass
class PolicyTarget:
    kind: PolicyTargetKind = POLICY_TARGET_WILDCARD
    name: str = POLICY_TARGET_WILDCARD


@dataclass
class PolicyPrincipal:
    """Structured caller selector for Driver policy rules."""

    source_type: str = POLICY_TARGET_WILDCARD
    source_value: str = POLICY_TARGET_WILDCARD
    subject_type: str = POLICY_TARGET_WILDCARD
    subject_value: str = POLICY_TARGET_WILDCARD


@dataclass
class PolicyRule:
    subject: str = POLICY_TARGET_WILDCARD
    effect: PolicyEffect = POLICY_EFFECT_ASK
    target: PolicyTarget = field(default_factory=PolicyTarget)
    principal: PolicyPrincipal = field(default_factory=PolicyPrincipal)
    condition: PolicyCondition | None = None


@dataclass
class DriverPolicy:
    default_effect: PolicyEffect = POLICY_EFFECT_DENY
    rules: list[PolicyRule] = field(default_factory=list)

    def __iter__(self) -> Iterator[PolicyRule]:
        return iter(self.rules)

    def __getitem__(self, index: int) -> PolicyRule:
        return self.rules[index]

    def __len__(self) -> int:
        return len(self.rules)


def coerce_driver_policy(value: Any) -> DriverPolicy:
    """Normalize loose/legacy policy data into the DriverPolicy shape."""
    if isinstance(value, DriverPolicy):
        return DriverPolicy(
            default_effect=_coerce_policy_effect(
                value.default_effect,
                default=POLICY_EFFECT_DENY,
            ),
            rules=[_coerce_policy_rule(item) for item in value.rules],
        )
    if value is None:
        return DriverPolicy()
    if isinstance(value, list):
        return DriverPolicy(
            default_effect=POLICY_EFFECT_DENY,
            rules=[_coerce_policy_rule(item) for item in value],
        )
    if isinstance(value, dict):
        rules = value.get("rules", [])
        if rules is None:
            rules = []
        if not isinstance(rules, list):
            raise DriverCardError("DriverPolicy.rules must be a list")
        return DriverPolicy(
            default_effect=_coerce_policy_effect(
                value.get("default_effect"),
                default=POLICY_EFFECT_DENY,
            ),
            rules=[_coerce_policy_rule(item) for item in rules],
        )
    return DriverPolicy()


def _coerce_policy_rule(value: Any) -> PolicyRule:
    if isinstance(value, PolicyRule):
        return PolicyRule(
            subject=_coerce_subject(value.subject),
            effect=_coerce_policy_effect(
                value.effect,
                default=POLICY_EFFECT_ASK,
            ),
            target=_coerce_policy_target(value.target),
            principal=_coerce_policy_principal(
                getattr(value, "principal", None),
            ),
            condition=value.condition,
        )
    if isinstance(value, dict):
        return PolicyRule(
            subject=_coerce_subject(
                value.get("subject", POLICY_TARGET_WILDCARD),
            ),
            effect=_coerce_policy_effect(
                value.get("effect"),
                default=POLICY_EFFECT_ASK,
            ),
            target=_coerce_policy_target(value.get("target")),
            principal=_coerce_policy_principal(value.get("principal")),
            condition=value.get("condition"),
        )
    return PolicyRule()


def _coerce_policy_target(value: Any) -> PolicyTarget:
    if isinstance(value, PolicyTarget):
        return PolicyTarget(
            kind=_coerce_target_kind(value.kind),
            name=str(value.name or POLICY_TARGET_WILDCARD),
        )
    if isinstance(value, dict):
        return PolicyTarget(
            kind=_coerce_target_kind(value.get("kind")),
            name=str(value.get("name") or POLICY_TARGET_WILDCARD),
        )
    return PolicyTarget()


def _coerce_policy_principal(value: Any) -> PolicyPrincipal:
    if isinstance(value, PolicyPrincipal):
        return PolicyPrincipal(
            source_type=_coerce_selector_value(value.source_type),
            source_value=_coerce_selector_value(value.source_value),
            subject_type=_coerce_selector_value(value.subject_type),
            subject_value=_coerce_selector_value(value.subject_value),
        )
    if isinstance(value, dict):
        return PolicyPrincipal(
            source_type=_coerce_selector_value(
                value.get("source_type", _MISSING),
            ),
            source_value=_coerce_selector_value(
                value.get("source_value", _MISSING),
            ),
            subject_type=_coerce_selector_value(
                value.get("subject_type", _MISSING),
            ),
            subject_value=_coerce_selector_value(
                value.get("subject_value", _MISSING),
            ),
        )
    return PolicyPrincipal()


def _coerce_selector_value(value: Any) -> str:
    if value is _MISSING or value is None:
        return POLICY_TARGET_WILDCARD
    return str(value)


def _coerce_policy_effect(
    value: Any,
    *,
    default: PolicyEffect,
) -> PolicyEffect:
    text = str(value or default)
    if text not in ALLOWED_POLICY_EFFECTS:
        raise DriverCardError(f"invalid policy effect: {text}")
    return cast(PolicyEffect, text)


def _coerce_target_kind(value: Any) -> PolicyTargetKind:
    return cast(PolicyTargetKind, str(value or POLICY_TARGET_WILDCARD))


def _coerce_subject(value: Any) -> str:
    if value is None:
        return POLICY_TARGET_WILDCARD
    return str(value)
