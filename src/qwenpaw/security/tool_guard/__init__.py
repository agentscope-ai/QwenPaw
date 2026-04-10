# -*- coding: utf-8 -*-
"""
Pre-tool-call guard framework for QwenPaw.

Scans tool execution parameters **before** the agent invokes a tool,
looking for dangerous patterns such as command injection, data
exfiltration, or access to sensitive files.

Architecture
~~~~~~~~~~~~

The guard framework mirrors the skill-scanner's extensible design:

* **BaseToolGuardian** – abstract interface every guardian must implement.
* **RuleBasedToolGuardian** – YAML regex-signature matching on parameter
  values (fast, line-based).
* **ToolGuardEngine** – orchestrator that runs all registered guardians
  and aggregates findings into a :class:`ToolGuardResult`.

Only rule-based detection is shipped today.  The :class:`BaseToolGuardian`
interface is intentionally kept thin so that new engines (LLM-as-a-judge,
semantic analysis, …) can be plugged in without changes to the
orchestrator.

Quick start::

    from qwenpaw.security.tool_guard import ToolGuardEngine

    engine = ToolGuardEngine()
    result = engine.guard("execute_shell_command", {"command": "rm -rf /"})
    if not result.is_safe:
        print(f"WARN: {result.max_severity.value} findings")
"""
from __future__ import annotations

from .models import (
    TOOL_GUARD_DENIED_MARK,
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)
from .engine import ToolGuardEngine
from .guardians import BaseToolGuardian
from .guardians.file_guardian import FilePathToolGuardian
from .guardians.rule_guardian import RuleBasedToolGuardian

__all__ = [
    "TOOL_GUARD_DENIED_MARK",
    "GuardFinding",
    "GuardSeverity",
    "GuardThreatCategory",
    "BaseToolGuardian",
    "FilePathToolGuardian",
    "RuleBasedToolGuardian",
    "ToolGuardEngine",
    "ToolGuardResult",
]
