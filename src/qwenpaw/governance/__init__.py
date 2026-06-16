# -*- coding: utf-8 -*-
"""Governance layer

Public surface:
    ResourceGovernor   — Core entry point
    GovernanceAction   — Rule action enum (ALLOW/DENY/ASK/SANDBOX_FALLBACK)
    GovernanceDecision — Decision result with action + reason + sandbox_config
    ToolCallSpec       — Input shape for assert_and_audit
    PolicyGuardedTool  — Tool wrapper that enforces governance
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
