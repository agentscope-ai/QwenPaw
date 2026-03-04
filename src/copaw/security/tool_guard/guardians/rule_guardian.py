# -*- coding: utf-8 -*-
"""YAML-signature rule-based tool-call guardian.

Loads security rules from YAML files (see ``rules/``) and performs fast
regex matching against the **string representation** of each tool
parameter value.

Rule format (one YAML file per threat category)::

    - id: SHELL_PIPE_TO_EXEC
      tool: execute_shell_command    # optional: empty = match all tools
      params: [command]              # optional: empty = match all params
      category: command_injection
      severity: HIGH
      patterns:
        - "curl.*\\|.*(?:sh|bash)"
        - "wget.*\\|.*(?:sh|bash)"
      exclude_patterns:             # optional
        - "^#"
      description: "Piping downloaded content directly to a shell"
      remediation: "Download to a file first and inspect before execution"
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..models import GuardFinding, GuardSeverity, GuardThreatCategory
from . import BaseToolGuardian

logger = logging.getLogger(__name__)

# Default rules directory (shipped with the package).
_DEFAULT_RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


# ---------------------------------------------------------------------------
# GuardRule – one YAML rule entry
# ---------------------------------------------------------------------------


class GuardRule:
    """A single regex-based guard detection rule."""

    __slots__ = (
        "id",
        "tools",
        "params",
        "category",
        "severity",
        "patterns",
        "exclude_patterns",
        "description",
        "remediation",
        "compiled_patterns",
        "compiled_exclude_patterns",
    )

    def __init__(self, rule_data: dict[str, Any]) -> None:
        self.id: str = rule_data["id"]

        # ``tool`` can be a single string or a list; empty means "all tools"
        raw_tool = rule_data.get("tool", rule_data.get("tools", []))
        if isinstance(raw_tool, str):
            self.tools: list[str] = [raw_tool] if raw_tool else []
        else:
            self.tools = list(raw_tool or [])

        # ``params`` works the same way
        raw_params = rule_data.get("params", rule_data.get("param", []))
        if isinstance(raw_params, str):
            self.params: list[str] = [raw_params] if raw_params else []
        else:
            self.params = list(raw_params or [])

        self.category = GuardThreatCategory(rule_data["category"])
        self.severity = GuardSeverity(rule_data["severity"])
        self.patterns: list[str] = rule_data.get("patterns", [])
        self.exclude_patterns: list[str] = rule_data.get("exclude_patterns", [])
        self.description: str = rule_data.get("description", "")
        self.remediation: str = rule_data.get("remediation", "")

        # Pre-compile regexes
        self.compiled_patterns: list[re.Pattern[str]] = []
        for pat in self.patterns:
            try:
                self.compiled_patterns.append(re.compile(pat, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Bad regex in guard rule %s: %s", self.id, exc)

        self.compiled_exclude_patterns: list[re.Pattern[str]] = []
        for pat in self.exclude_patterns:
            try:
                self.compiled_exclude_patterns.append(re.compile(pat, re.IGNORECASE))
            except re.error as exc:
                logger.warning(
                    "Bad exclude regex in guard rule %s: %s", self.id, exc
                )

    # ------------------------------------------------------------------

    def applies_to_tool(self, tool_name: str) -> bool:
        """Return *True* if this rule should fire for *tool_name*."""
        if not self.tools:
            return True
        return tool_name in self.tools

    def applies_to_param(self, param_name: str) -> bool:
        """Return *True* if this rule should scan *param_name*."""
        if not self.params:
            return True
        return param_name in self.params

    def match(self, value: str) -> tuple[re.Match[str] | None, str | None]:
        """Try to match *value* against a rule pattern.

        Returns ``(match_object, pattern_string)`` on the first hit, or
        ``(None, None)`` if nothing matched.
        """
        # Skip if any exclude pattern matches
        if any(ep.search(value) for ep in self.compiled_exclude_patterns):
            return None, None

        for pattern in self.compiled_patterns:
            m = pattern.search(value)
            if m:
                return m, pattern.pattern
        return None, None


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def load_rules_from_yaml(yaml_path: Path) -> list[GuardRule]:
    """Load guard rules from a single YAML file."""
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            logger.warning("Expected a list in %s, got %s", yaml_path, type(data).__name__)
            return []
        return [GuardRule(item) for item in data if isinstance(item, dict)]
    except Exception as exc:
        logger.warning("Failed to load guard rules from %s: %s", yaml_path, exc)
        return []


def load_rules_from_directory(rules_dir: Path | None = None) -> list[GuardRule]:
    """Load all YAML rule files from a directory."""
    directory = rules_dir or _DEFAULT_RULES_DIR
    if not directory.is_dir():
        logger.warning("Guard rules directory not found: %s", directory)
        return []

    rules: list[GuardRule] = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        rules.extend(load_rules_from_yaml(yaml_file))
    for yaml_file in sorted(directory.glob("*.yml")):
        rules.extend(load_rules_from_yaml(yaml_file))

    logger.debug("Loaded %d guard rules from %s", len(rules), directory)
    return rules


# ---------------------------------------------------------------------------
# RuleBasedToolGuardian
# ---------------------------------------------------------------------------


class RuleBasedToolGuardian(BaseToolGuardian):
    """Guardian that matches tool parameters against YAML regex rules.

    Parameters
    ----------
    rules_dir:
        Directory containing YAML rule files.  Defaults to the bundled
        ``rules/`` directory.
    extra_rules:
        Additional rules to register beyond those loaded from disk.
    """

    def __init__(
        self,
        *,
        rules_dir: Path | None = None,
        extra_rules: list[GuardRule] | None = None,
    ) -> None:
        super().__init__(name="rule_based_tool_guardian")
        self._rules: list[GuardRule] = load_rules_from_directory(rules_dir)
        if extra_rules:
            self._rules.extend(extra_rules)

    @property
    def rules(self) -> list[GuardRule]:
        """Return the loaded rules (read-only view)."""
        return list(self._rules)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        """Scan all string-like parameter values against loaded rules."""
        findings: list[GuardFinding] = []
        applicable_rules = [r for r in self._rules if r.applies_to_tool(tool_name)]

        if not applicable_rules:
            return findings

        for param_name, param_value in params.items():
            # Convert to string for scanning
            value_str = str(param_value) if param_value is not None else ""
            if not value_str:
                continue

            for rule in applicable_rules:
                if not rule.applies_to_param(param_name):
                    continue
                m, pattern_str = rule.match(value_str)
                if m:
                    # Produce a context snippet (up to 120 chars around the match)
                    start = max(0, m.start() - 40)
                    end = min(len(value_str), m.end() + 40)
                    snippet = value_str[start:end]

                    findings.append(
                        GuardFinding(
                            id=f"GUARD-{uuid.uuid4().hex[:8]}",
                            rule_id=rule.id,
                            category=rule.category,
                            severity=rule.severity,
                            title=f"[{rule.severity.value}] {rule.description}",
                            description=(
                                f"Rule {rule.id} matched parameter "
                                f"'{param_name}' of tool '{tool_name}'."
                            ),
                            tool_name=tool_name,
                            param_name=param_name,
                            matched_value=m.group(0),
                            matched_pattern=pattern_str,
                            snippet=snippet,
                            remediation=rule.remediation,
                            guardian=self.name,
                        )
                    )
        return findings
