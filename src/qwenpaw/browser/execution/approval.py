# -*- coding: utf-8 -*-
"""Structured semantic approval policy for the browser execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class PolicyRule:
    origin: str
    action_category: str
    data_category: str = "*"
    scope: str = "*"
    decision: Decision = Decision.CONFIRM


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str
    rule: PolicyRule | None = None
