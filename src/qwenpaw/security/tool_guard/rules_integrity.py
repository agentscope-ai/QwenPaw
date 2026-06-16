# -*- coding: utf-8 -*-
"""Backward-compatible re-exports for built-in tool guard rule integrity.

Implementation lives in extension/rule_integrity/. The guardian and routers
keep importing this module path unchanged.
"""
from __future__ import annotations

from qwenpaw.security.rule_integrity_bridge import (
    DANGEROUS_SHELL_RULES_NAME,
    HASH_SCHEME,
    MANIFEST_NAME,
    RECOVERY_SOURCE_URL,
    SIGNATURE_NAME,
    SIGNATURE_SCHEME,
    RuleIntegrityFinding,
    RuleIntegrityRepairResult,
    RuleIntegrityResult,
    _sha256_normalized_content,
    get_last_rule_integrity_status,
    repair_default_builtin_rule_file,
    rule_integrity_lockdown_active,
    verify_builtin_rule_files,
    verify_default_builtin_rule_files,
)

__all__ = [
    "DANGEROUS_SHELL_RULES_NAME",
    "HASH_SCHEME",
    "MANIFEST_NAME",
    "RECOVERY_SOURCE_URL",
    "SIGNATURE_NAME",
    "SIGNATURE_SCHEME",
    "RuleIntegrityFinding",
    "RuleIntegrityRepairResult",
    "RuleIntegrityResult",
    "_sha256_normalized_content",
    "get_last_rule_integrity_status",
    "repair_default_builtin_rule_file",
    "rule_integrity_lockdown_active",
    "verify_builtin_rule_files",
    "verify_default_builtin_rule_files",
]
