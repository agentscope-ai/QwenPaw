# -*- coding: utf-8 -*-
"""Resource Governor layer — Policy evaluation + audit logging + sandbox config compilation.

Public surface:
    ResourceGovernor  — Core entry point (assert_and_audit / compile_sandbox_config / add_rule)
    ToolCallSpec      — Tool call intent specification (tool_name, target, agent_id, session_id)
    ToolRegistry      — Tool metadata registry (type, target param name, name mapping)
    GovernancePolicy  — builtin_rules + user_rules two-layer policy (first-match-wins)
    PolicyRule        — Single policy rule (match + action + grantee + duration)
    PolicyDecision    — Decision result (ALLOW / DENY / ASK / SANDBOX_FALLBACK)
    AuditLog          — Append-only audit log
    AuditEvent        — Single audit record
"""
from .resource_governor import ResourceGovernor
from .policy import (
    GovernancePolicy, PolicyRule, PolicyDecision, PolicyAction,
    ToolCallSpec, generalize_rule_match,
)
from .tool_registry import ToolRegistry, DEFAULT_REGISTRY
from .audit import AuditLog, AuditEvent
from .tool_adapter import PolicyGuardedTool

__all__ = [
    "ResourceGovernor", "ToolCallSpec",
    "ToolRegistry", "DEFAULT_REGISTRY",
    "GovernancePolicy", "PolicyRule", "PolicyDecision", "PolicyAction",
    "generalize_rule_match",
    "AuditLog", "AuditEvent",
    "PolicyGuardedTool",
]
