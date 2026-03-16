# -*- coding: utf-8 -*-
"""YAML-signature pattern matching analyzer.

Loads security rules from YAML files (see ``rules/signatures/``) and
performs fast, line-based regex matching with a multiline fallback for
patterns that intentionally span newlines.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from ..models import Finding, Severity, SkillFile, ThreatCategory
from ..scan_policy import ScanPolicy
from . import BaseAnalyzer

logger = logging.getLogger(__name__)

# Matches character-class contents so we can tell whether ``\n`` in a
# pattern is genuinely multiline vs. ``[^\n]``.
_CHAR_CLASS_RE = re.compile(r"\[[^\]]*\]")

# Default signatures directory (shipped with the package).
_DEFAULT_SIGNATURES_DIR = Path(__file__).resolve().parent.parent / "rules" / "signatures"


# ---------------------------------------------------------------------------
# SecurityRule – one YAML rule entry
# ---------------------------------------------------------------------------


class SecurityRule:
    """A single regex-based security detection rule."""

    __slots__ = (
        "id",
        "category",
        "severity",
        "patterns",
        "exclude_patterns",
        "file_types",
        "description",
        "remediation",
        "compiled_patterns",
        "compiled_exclude_patterns",
    )

    def __init__(self, rule_data: dict[str, Any]) -> None:
        self.id: str = rule_data["id"]
        self.category = ThreatCategory(rule_data["category"])
        self.severity = Severity(rule_data["severity"])
        self.patterns: list[str] = rule_data["patterns"]
        self.exclude_patterns: list[str] = rule_data.get("exclude_patterns", [])
        self.file_types: list[str] = rule_data.get("file_types", [])
        self.description: str = rule_data["description"]
        self.remediation: str = rule_data.get("remediation", "")

        self.compiled_patterns: list[re.Pattern[str]] = []
        for pat in self.patterns:
            try:
                self.compiled_patterns.append(re.compile(pat))
            except re.error as exc:
                logger.warning("Bad regex in rule %s: %s", self.id, exc)

        self.compiled_exclude_patterns: list[re.Pattern[str]] = []
        for pat in self.exclude_patterns:
            try:
                self.compiled_exclude_patterns.append(re.compile(pat))
            except re.error as exc:
                logger.warning("Bad exclude regex in rule %s: %s", self.id, exc)

    # ------------------------------------------------------------------

    def matches_file_type(self, file_type: str) -> bool:
        """Return *True* if this rule applies to *file_type*."""
        if not self.file_types:
            return True
        return file_type in self.file_types

    def scan_content(
        self,
        content: str,
        file_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Scan *content* for rule violations.

        Returns a list of match dicts with ``line_number``, ``line_content``,
        ``matched_pattern``, ``matched_text``, and ``file_path``.
        """
        matches: list[dict[str, Any]] = []
        lines = content.split("\n")

        # --- Pass 1: line-based matching (fast) --------------------------
        for line_num, line in enumerate(lines, start=1):
            excluded = any(ep.search(line) for ep in self.compiled_exclude_patterns)
            if excluded:
                continue
            for pattern in self.compiled_patterns:
                m = pattern.search(line)
                if m:
                    matches.append(
                        {
                            "line_number": line_num,
                            "line_content": line.strip(),
                            "matched_pattern": pattern.pattern,
                            "matched_text": m.group(0),
                            "file_path": file_path,
                        }
                    )

        # --- Pass 2: multiline patterns ----------------------------------
        for pattern in self.compiled_patterns:
            stripped = _CHAR_CLASS_RE.sub("", pattern.pattern)
            if "\\n" not in stripped:
                continue
            for m in pattern.finditer(content):
                matched_text = m.group(0)
                excluded = any(ep.search(matched_text) for ep in self.compiled_exclude_patterns)
                if excluded:
                    continue
                start_line = content.count("\n", 0, m.start()) + 1
                snippet = lines[start_line - 1].strip() if 0 <= start_line - 1 < len(lines) else ""
                matches.append(
                    {
                        "line_number": start_line,
                        "line_content": snippet,
                        "matched_pattern": pattern.pattern,
                        "matched_text": matched_text[:200],
                        "file_path": file_path,
                    }
                )

        return matches


# ---------------------------------------------------------------------------
# RuleLoader
# ---------------------------------------------------------------------------


class RuleLoader:
    """Loads :class:`SecurityRule` objects from YAML files."""

    def __init__(self, rules_path: Path | None = None) -> None:
        self.rules_path = rules_path or _DEFAULT_SIGNATURES_DIR
        self.rules: list[SecurityRule] = []
        self.rules_by_id: dict[str, SecurityRule] = {}
        self.rules_by_category: dict[ThreatCategory, list[SecurityRule]] = {}

    def load_rules(self) -> list[SecurityRule]:
        """Load and index all rules from the configured path."""
        path = Path(self.rules_path)
        if path.is_dir():
            raw: list[dict[str, Any]] = []
            for yaml_file in sorted(path.glob("*.yaml")):
                try:
                    with open(yaml_file, encoding="utf-8") as fh:
                        data = yaml.safe_load(fh)
                except Exception as exc:
                    raise RuntimeError(f"Failed to load {yaml_file}: {exc}") from exc
                if not isinstance(data, list):
                    raise RuntimeError(f"Expected list in {yaml_file}")
                raw.extend(data)
        else:
            try:
                with open(path, encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh)
            except Exception as exc:
                raise RuntimeError(f"Failed to load {path}: {exc}") from exc
            if not isinstance(raw, list):
                raise RuntimeError(f"Expected list in {path}")

        self.rules = []
        self.rules_by_id = {}
        self.rules_by_category = {}

        for entry in raw:
            try:
                rule = SecurityRule(entry)
                self.rules.append(rule)
                self.rules_by_id[rule.id] = rule
                self.rules_by_category.setdefault(rule.category, []).append(rule)
            except Exception as exc:
                logger.warning("Skipping rule %s: %s", entry.get("id", "?"), exc)

        return self.rules

    def get_rule(self, rule_id: str) -> SecurityRule | None:
        return self.rules_by_id.get(rule_id)

    def get_rules_for_file_type(self, file_type: str) -> list[SecurityRule]:
        return [r for r in self.rules if r.matches_file_type(file_type)]

    def get_rules_for_category(self, category: ThreatCategory) -> list[SecurityRule]:
        return self.rules_by_category.get(category, [])


# ---------------------------------------------------------------------------
# PatternAnalyzer
# ---------------------------------------------------------------------------


class PatternAnalyzer(BaseAnalyzer):
    """Analyzer that matches YAML regex signatures against skill files.

    Parameters
    ----------
    rules_path:
        Path to a YAML file or a directory of YAML files.  Defaults to
        the ``rules/signatures/`` directory shipped with the package.
    policy:
        Optional :class:`ScanPolicy` for rule disabling, severity
        overrides, and doc-path skipping.
    """

    def __init__(
        self,
        rules_path: Path | None = None,
        *,
        policy: ScanPolicy | None = None,
    ) -> None:
        super().__init__(name="pattern", policy=policy)
        loader = RuleLoader(rules_path)
        self._rules = loader.load_rules()
        self._rules_by_file_type: dict[str, list[SecurityRule]] = {}
        logger.debug("PatternAnalyzer loaded %d rules", len(self._rules))

    # ------------------------------------------------------------------
    # BaseAnalyzer interface
    # ------------------------------------------------------------------

    def analyze(
        self,
        skill_dir: Path,
        files: list[SkillFile],
        *,
        skill_name: str | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        skip_in_docs = self.policy.rule_scoping.skip_in_docs

        for sf in files:
            content = sf.read_content()
            if not content:
                continue

            is_doc = self.policy.is_doc_path(sf.relative_path)

            applicable = self._get_rules(sf.file_type)
            for rule in applicable:
                # --- Policy-based rule filtering ---
                # Skip disabled rules early
                if self.policy.is_rule_disabled(rule.id):
                    continue
                # Skip doc-only exclusions
                if is_doc and rule.id in skip_in_docs:
                    continue
                # Code-only rules should not fire on non-code files
                if rule.id in self.policy.rule_scoping.code_only:
                    if sf.file_type not in ("python", "bash", "javascript", "typescript"):
                        continue

                matches = rule.scan_content(content, file_path=sf.relative_path)
                for match in matches:
                    # Apply severity override if configured
                    severity = rule.severity
                    override = self.policy.get_severity_override(rule.id)
                    if override:
                        try:
                            severity = Severity(override)
                        except ValueError:
                            pass

                    findings.append(
                        Finding(
                            id=f"{rule.id}:{sf.relative_path}:{match['line_number']}",
                            rule_id=rule.id,
                            category=rule.category,
                            severity=severity,
                            title=rule.description,
                            description=rule.description,
                            file_path=sf.relative_path,
                            line_number=match["line_number"],
                            snippet=match["line_content"],
                            remediation=rule.remediation,
                            analyzer=self.name,
                            metadata={
                                "matched_pattern": match["matched_pattern"],
                                "matched_text": match["matched_text"],
                            },
                        )
                    )

        # Filter well-known test credentials
        findings = [f for f in findings if not self._is_known_test_credential(f)]

        # De-duplicate if enabled in policy
        if self.policy.rule_scoping.dedupe_duplicate_findings:
            findings = self._dedupe_findings(findings)

        return findings

    # ------------------------------------------------------------------
    # Credential filtering
    # ------------------------------------------------------------------

    def _is_known_test_credential(self, finding: Finding) -> bool:
        """Suppress findings that match known test/placeholder credentials."""
        if finding.category != ThreatCategory.HARDCODED_SECRETS:
            return False
        snippet = (finding.snippet or "").lower()
        for cred in self.policy.credentials.known_test_values:
            if cred.lower() in snippet:
                return True
        for marker in self.policy.credentials.placeholder_markers:
            if marker.lower() in snippet:
                return True
        return False

    # ------------------------------------------------------------------
    # De-duplication
    # ------------------------------------------------------------------

    @staticmethod
    def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
        """Remove exact duplicate findings (same rule + file + line)."""
        seen: set[str] = set()
        unique: list[Finding] = []
        for f in findings:
            key = f"{f.rule_id}:{f.file_path}:{f.line_number}"
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_rules(self, file_type: str) -> list[SecurityRule]:
        """Return rules applicable to *file_type* (cached)."""
        if file_type not in self._rules_by_file_type:
            self._rules_by_file_type[file_type] = [
                r for r in self._rules if r.matches_file_type(file_type)
            ]
        return self._rules_by_file_type[file_type]
