# -*- coding: utf-8 -*-
"""Access policy evaluation for Drivers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

from .constants import (
    DRIVER_OPERATION_INVOKE,
    POLICY_EFFECT_ALLOW,
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
    POLICY_TARGET_WILDCARD,
    PRINCIPAL_SOURCE_CHANNEL,
    PRINCIPAL_SUBJECT_ALL,
    PRINCIPAL_SUBJECT_SESSION,
    PRINCIPAL_SUBJECT_USER,
    SUBJECT_UNKNOWN_USER,
)
from .policy_types import (
    DriverPolicy,
    PolicyCondition,
    PolicyEffect,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
    coerce_driver_policy,
)

__all__ = [
    "DriverInvocationContext",
    "PolicyContext",
    "condition_satisfied",
    "context_subjects",
    "evaluate_policy",
    "principal_matches",
    "principal_specificity",
    "specificity",
    "subject_matches",
    "subject_specificity",
    "target_kind_specificity",
    "target_matches",
    "target_name_specificity",
]

_STRICTNESS: dict[str, int] = {
    POLICY_EFFECT_DENY: 3,
    POLICY_EFFECT_ASK: 2,
    POLICY_EFFECT_ALLOW: 1,
}
logger = logging.getLogger(__name__)
_WARNED_UNKNOWN_SOURCE_TYPES: set[str] = set()


@dataclass(frozen=True)
class DriverInvocationContext:
    subject: str
    driver_name: str
    protocol: str
    operation: str = DRIVER_OPERATION_INVOKE
    target: PolicyTarget = field(default_factory=PolicyTarget)
    subjects: tuple[str, ...] = field(default_factory=tuple)
    workspace_id: str = ""
    request_context: dict[str, str] = field(default_factory=dict)
    now: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    extras: dict[str, Any] = field(default_factory=dict)


PolicyContext = DriverInvocationContext


def evaluate_policy(
    policy: DriverPolicy | list[PolicyRule],
    context: DriverInvocationContext,
) -> PolicyEffect:
    """Return allow, deny, or ask for a Driver-local target."""
    driver_policy = coerce_driver_policy(policy)
    subjects = context_subjects(context)
    matches = [
        rule
        for rule in driver_policy.rules
        if any(subject_matches(rule.subject, subject) for subject in subjects)
        and principal_matches(rule.principal, context)
        and target_matches(rule.target, context.target)
        and condition_satisfied(rule.condition, context)
        and rule.effect in _STRICTNESS
    ]
    if not matches:
        default = driver_policy.default_effect
        return default if default in _STRICTNESS else POLICY_EFFECT_DENY

    matches.sort(
        key=lambda rule: (
            target_name_specificity(rule.target),
            target_kind_specificity(rule.target),
            principal_specificity(rule.principal, context),
            max(
                subject_specificity(rule.subject)
                for subject in subjects
                if subject_matches(rule.subject, subject)
            ),
            _STRICTNESS[rule.effect],
        ),
        reverse=True,
    )
    return matches[0].effect


def principal_matches(
    selector: PolicyPrincipal,
    context: DriverInvocationContext,
) -> bool:
    """Match structured source and object constraints with AND semantics."""
    return _source_matches(selector, context) and _subject_scope_matches(
        selector,
        context,
    )


def subject_matches(pattern: str, subject: str) -> bool:
    """Support exact, typed-prefix wildcard, and global wildcard patterns."""
    if not pattern or not subject:
        return False
    if pattern == POLICY_TARGET_WILDCARD:
        return True
    if pattern.endswith(":*"):
        return subject.startswith(pattern[:-1])
    return pattern == subject


def context_subjects(context: DriverInvocationContext) -> tuple[str, ...]:
    """Return the de-duplicated subject set used for one policy check."""
    subjects: list[str] = []
    for subject in (context.subject, *context.subjects):
        if subject and subject not in subjects:
            subjects.append(subject)
    return tuple(subjects or (SUBJECT_UNKNOWN_USER,))


def target_matches(pattern: PolicyTarget, target: PolicyTarget) -> bool:
    """Support exact and wildcard matching for Driver-local targets."""
    return _target_part_matches(
        pattern.kind,
        target.kind,
    ) and _target_part_matches(
        pattern.name,
        target.name,
    )


def _target_part_matches(pattern: str, value: str) -> bool:
    if not pattern or not value:
        return False
    if pattern == POLICY_TARGET_WILDCARD:
        return True
    return pattern == value


def specificity(pattern: str) -> int:
    """Return exact=2, user wildcard=1, global=0."""
    return subject_specificity(pattern)


def subject_specificity(pattern: str) -> int:
    """Return exact=2, typed wildcard=1, global=0."""
    if pattern == "*":
        return 0
    if pattern.endswith(":*"):
        return 1
    return 2


def target_kind_specificity(target: PolicyTarget) -> int:
    return 0 if target.kind == POLICY_TARGET_WILDCARD else 1


def target_name_specificity(target: PolicyTarget) -> int:
    return 0 if target.name == POLICY_TARGET_WILDCARD else 1


def principal_specificity(
    selector: PolicyPrincipal,
    context: DriverInvocationContext,
) -> int:
    """Return a higher score for more specific structured selectors."""
    if not principal_matches(selector, context):
        return -1
    score = 0
    source_type = _normalize_selector_part(selector.source_type)
    source_value = _selector_value(selector.source_value)
    subject_type = _normalize_selector_part(selector.subject_type)
    subject_value = _selector_value(selector.subject_value)
    if source_type != POLICY_TARGET_WILDCARD:
        score += 1
        if source_value not in {"", POLICY_TARGET_WILDCARD}:
            score += 1
    if subject_type != POLICY_TARGET_WILDCARD:
        score += 1
        if subject_type != PRINCIPAL_SUBJECT_ALL and subject_value not in {
            "",
            POLICY_TARGET_WILDCARD,
        }:
            score += 1
    return score


def condition_satisfied(
    condition: PolicyCondition | None,
    context: PolicyContext,
) -> bool:
    """Evaluate supported policy conditions."""
    if condition is None:
        return True
    if condition.time_range is not None and not _time_range_satisfied(
        condition.time_range,
        context.now,
    ):
        return False
    return True


def _source_matches(
    selector: PolicyPrincipal,
    context: DriverInvocationContext,
) -> bool:
    source_type = _normalize_selector_part(selector.source_type)
    source_value = _selector_value(selector.source_value)
    if source_type == POLICY_TARGET_WILDCARD:
        return True
    if source_type == PRINCIPAL_SOURCE_CHANNEL:
        channel = _selector_value(context.request_context.get("channel"))
        if source_value in {"", POLICY_TARGET_WILDCARD}:
            return bool(channel)
        return channel.lower() == source_value.lower()
    if source_type not in _WARNED_UNKNOWN_SOURCE_TYPES:
        _WARNED_UNKNOWN_SOURCE_TYPES.add(source_type)
        logger.warning(
            "Unknown Driver policy source_type '%s'; rule will not match",
            source_type,
        )
    return False


def _subject_scope_matches(
    selector: PolicyPrincipal,
    context: DriverInvocationContext,
) -> bool:
    subject_type = _normalize_selector_part(selector.subject_type)
    subject_value = _selector_value(selector.subject_value)
    if subject_type in {POLICY_TARGET_WILDCARD, PRINCIPAL_SUBJECT_ALL}:
        return True
    if not subject_value:
        return False
    if subject_value == POLICY_TARGET_WILDCARD:
        return True
    if subject_type == PRINCIPAL_SUBJECT_USER:
        return (
            _selector_value(context.request_context.get("user_id"))
            == subject_value
        )
    if subject_type == PRINCIPAL_SUBJECT_SESSION:
        return (
            _selector_value(context.request_context.get("session_id"))
            == subject_value
        )
    return False


def _normalize_selector_part(value: str | None) -> str:
    normalized = _selector_value(value).lower()
    return normalized or POLICY_TARGET_WILDCARD


def _selector_value(value: str | None) -> str:
    return str(value or "").strip()


def _time_range_satisfied(time_range: Any, now: datetime) -> bool:
    if not _weekdays_satisfied(time_range.weekdays, now):
        return False

    after = _parse_clock(time_range.after)
    before = _parse_clock(time_range.before)
    current = now.timetz().replace(tzinfo=None)
    return _clock_range_satisfied(after, before, current)


def _weekdays_satisfied(weekdays_raw: Any, now: datetime) -> bool:
    if weekdays_raw is None:
        return True
    try:
        weekdays = {int(day) for day in weekdays_raw}
    except (TypeError, ValueError):
        return False
    return now.weekday() in weekdays


def _clock_range_satisfied(
    after: time | None,
    before: time | None,
    current: time,
) -> bool:
    if after is not None and before is not None:
        if after <= before:
            return after <= current <= before
        return current >= after or current <= before
    if after is not None:
        return current >= after
    if before is not None:
        return current <= before
    return True


def _parse_clock(value: str | None) -> time | None:
    if value is None:
        return None
    try:
        if len(value.split(":")) == 2:
            return datetime.strptime(value, "%H:%M").time()
        return datetime.strptime(value, "%H:%M:%S").time()
    except ValueError:
        return None
