# -*- coding: utf-8 -*-
"""Governance layer

Public surface:
    ResourceGovernor  — Core entry point (assert_and_audit /
        compile_sandbox_config / add_rule)
    GovernanceAction  — Rule action enum (ALLOW / DENY / ASK /
        SANDBOX_FALLBACK)
    GovernanceDecision — Decision result with action + reason +
        sandbox_config
    ToolCallSpec      — Describes one tool invocation for policy evaluation
"""

from .resource_governor import ResourceGovernor
from .policy import GovernanceAction, GovernanceDecision, ToolCallSpec
from .tool_adapter import PolicyGuardedTool

__all__ = [
    "ResourceGovernor",
    "GovernanceAction",
    "GovernanceDecision",
    "ToolCallSpec",
    "PolicyGuardedTool",
]
