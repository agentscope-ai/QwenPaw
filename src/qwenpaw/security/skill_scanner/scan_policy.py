# -*- coding: utf-8 -*-
"""Scan policy: org-customisable allowlists and rule scoping.

Every organisation has a different security bar.  A ``ScanPolicy``
captures what counts as benign, which rules fire on which file
types, which credentials are test-only, and so on.

Usage
-----
    from qwenpaw.security.skill_scanner.scan_policy import ScanPolicy

    # Load built-in defaults
    policy = ScanPolicy.default()

    # Load an org policy (merges on top of defaults)
    policy = ScanPolicy.from_yaml("my_policy.yaml")

    # Dump the current (including default) policy for editing
    policy.to_yaml("generated_policy.yaml")

Analysers receive the policy at construction time and use it in place of their
previously-hardcoded sets/lists.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_MAX_PATTERN_LENGTH = 1000

# Where the built-in default policy lives (ships with the package)
_DATA_DIR = Path(__file__).resolve().parent / "data"
_DEFAULT_POLICY_PATH = _DATA_DIR / "default_policy.yaml"

# Named preset policies
# TODO: add "strict" and "permissive" presets once their YAML files are shipped
_PRESET_POLICIES: dict[str, Path] = {
    "balanced": _DEFAULT_POLICY_PATH,
}


def _safe_compile(
    pattern: str,
    flags: int = 0,
    *,
    max_length: int = _MAX_PATTERN_LENGTH,
) -> re.Pattern | None:
    if len(pattern) > max_length:
        logger.warning(
            "Regex pattern too long (%d chars), skipping: %.60s...",
            len(pattern),
            pattern,
        )
        return None
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        logger.warning("Invalid regex pattern %r: %s", pattern, exc)
        return None


# ---------------------------------------------------------------------------
# Data classes for each policy section
# ---------------------------------------------------------------------------


@dataclass
class HiddenFilePolicy:
    """Controls which dotfiles/dotdirs are treated as benign."""

    benign_dotfiles: set[str] = field(default_factory=set)
    benign_dotdirs: set[str] = field(default_factory=set)


@dataclass
class RuleScopingPolicy:
    """Controls which rule sets fire on which file categories."""

    # Rule names → only fire on SKILL.md + scripts
    skillmd_and_scripts_only: set[str] = field(default_factory=set)
    # Rule names → skip when file is in a documentation path
    skip_in_docs: set[str] = field(default_factory=set)
    # Rule names → only fire on code files (.py, .sh, etc.)
    code_only: set[str] = field(default_factory=set)
    # Path components that mark a directory as "documentation"
    doc_path_indicators: set[str] = field(default_factory=set)
    # Regex patterns that match educational/example filenames
    doc_filename_patterns: list[str] = field(default_factory=list)
    # De-duplicate identical findings emitted by multiple static scan passes
    dedupe_duplicate_findings: bool = True


@dataclass
class CredentialPolicy:
    """Controls which well-known test credentials are auto-suppressed."""

    known_test_values: set[str] = field(default_factory=set)
    placeholder_markers: set[str] = field(default_factory=set)


@dataclass
class FileClassificationPolicy:
    """Controls how file extensions are classified for analysis routing."""

    # Extensions treated as inert (images, fonts, etc.)
    inert_extensions: set[str] = field(default_factory=set)
    # Extensions treated as structured data (SVG, PDF)
    structured_extensions: set[str] = field(default_factory=set)
    # Extensions treated as archives
    archive_extensions: set[str] = field(default_factory=set)
    # Extensions considered executable code
    code_extensions: set[str] = field(default_factory=set)


@dataclass
class FileLimitsPolicy:
    """Numeric thresholds for file inventory checks."""

    max_file_count: int = 100
    max_file_size_bytes: int = 5_242_880  # 5 MB
    max_reference_depth: int = 5
    max_name_length: int = 64
    max_description_length: int = 1024
    min_description_length: int = 20


@dataclass
class AnalysisThresholdsPolicy:
    """Numeric thresholds for analysis tuning."""

    min_confidence_pct: int = 80
    max_regex_pattern_length: int = 1000


@dataclass
class SeverityOverride:
    """A per-rule severity override."""

    rule_id: str
    severity: str  # CRITICAL / HIGH / MEDIUM / LOW / INFO
    reason: str = ""


# ---------------------------------------------------------------------------
# The top-level policy object
# ---------------------------------------------------------------------------


@dataclass
class ScanPolicy:
    """Organisational scan policy."""

    # Metadata
    policy_name: str = "default"
    policy_version: str = "1.0"
    preset_base: str = "balanced"

    # Sections
    hidden_files: HiddenFilePolicy = field(default_factory=HiddenFilePolicy)
    rule_scoping: RuleScopingPolicy = field(default_factory=RuleScopingPolicy)
    credentials: CredentialPolicy = field(default_factory=CredentialPolicy)
    file_classification: FileClassificationPolicy = field(
        default_factory=FileClassificationPolicy,
    )
    file_limits: FileLimitsPolicy = field(default_factory=FileLimitsPolicy)
    analysis_thresholds: AnalysisThresholdsPolicy = field(
        default_factory=AnalysisThresholdsPolicy,
    )
    severity_overrides: list[SeverityOverride] = field(default_factory=list)
    disabled_rules: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_severity_override(self, rule_id: str) -> str | None:
        """Return the overridden severity for *rule_id*, or ``None``."""
        for ovr in self.severity_overrides:
            if ovr.rule_id == rule_id:
                return ovr.severity
        return None

    def is_rule_disabled(self, rule_id: str) -> bool:
        """Return *True* if the rule has been disabled by the policy."""
        return rule_id in self.disabled_rules

    def is_doc_path(self, rel_path: str) -> bool:
        """Check if a relative file path belongs to a documentation area."""
        parts = Path(rel_path).parts
        doc_indicators = self.rule_scoping.doc_path_indicators
        if any(p.lower() in doc_indicators for p in parts):
            return True
        doc_re = self._compiled_doc_filename_re
        if doc_re and doc_re.search(Path(rel_path).stem):
            return True
        return False

    @property
    def _compiled_doc_filename_re(self) -> re.Pattern | None:
        """Lazy-compiled regex from ``rule_scoping.doc_filename_patterns``."""
        if not hasattr(self, "_doc_fn_re_cache"):
            patterns = self.rule_scoping.doc_filename_patterns
            if patterns:
                max_pat_len = self.analysis_thresholds.max_regex_pattern_length
                compiled = [
                    _safe_compile(p, re.IGNORECASE, max_length=max_pat_len)
                    for p in patterns
                ]
                valid = [c for c in compiled if c is not None]
                if valid:
                    combined = "|".join(f"(?:{c.pattern})" for c in valid)
                    limit = max_pat_len * max(len(valid), 1) + len(valid) * 4
                    self._doc_fn_re_cache = _safe_compile(
                        combined,
                        re.IGNORECASE,
                        max_length=limit,
                    )
                else:
                    self._doc_fn_re_cache = None
            else:
                self._doc_fn_re_cache = None
        # type: ignore[attr-defined, no-any-return]
        return self._doc_fn_re_cache  # type: ignore

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> ScanPolicy:
        """Load the built-in default policy that ships with the package."""
        if _DEFAULT_POLICY_PATH.exists():
            return cls.from_yaml(_DEFAULT_POLICY_PATH)
        # Fall back to empty (all defaults) if the YAML hasn't been shipped yet
        return cls()

    @classmethod
    def from_preset(cls, name: str) -> ScanPolicy:
        """Load a named preset policy."""
        name_lower = name.lower()
        if name_lower not in _PRESET_POLICIES:
            raise ValueError(
                f"Unknown preset '{name}'. "
                f"Available: {', '.join(sorted(_PRESET_POLICIES))}",
            )
        return cls.from_yaml(_PRESET_POLICIES[name_lower])

    @classmethod
    def preset_names(cls) -> list[str]:
        """Return available preset policy names."""
        return sorted(_PRESET_POLICIES.keys())

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScanPolicy:
        """Load a policy from a YAML file.

        The YAML is first merged on top of the built-in defaults so that
        users only need to specify the sections they want to override.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")

        with open(path, encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        is_default = path.resolve() == _DEFAULT_POLICY_PATH.resolve()
        if is_default:
            return cls._from_dict(raw)

        # Overlay user customisations on top of defaults
        default_raw = cls._load_default_raw()
        merged = cls._deep_merge(default_raw, raw)
        return cls._from_dict(merged)

    def to_yaml(self, path: str | Path) -> None:
        """Dump the full policy to a YAML file for editing."""
        data = self._to_dict()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# CoPaw Skill Scanner – Scan Policy\n")
            fh.write(
                "# Customise this file to match your"
                " organisation's security bar.\n",
            )
            fh.write(
                "# Only include sections you want to"
                " override; omitted sections\n",
            )
            fh.write("# will use the built-in defaults.\n\n")
            yaml.dump(
                data,
                fh,
                default_flow_style=False,
                sort_keys=False,
                width=120,
            )

    # ------------------------------------------------------------------
    # Internal parsing
    # ------------------------------------------------------------------

    @classmethod
    def _load_default_raw(cls) -> dict[str, Any]:
        if _DEFAULT_POLICY_PATH.exists():
            with open(_DEFAULT_POLICY_PATH, encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        return {}

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge *override* into *base*.

        For lists and sets (represented as lists in YAML) the override
        **replaces** the base so that an org can narrow or expand a list
        without having to repeat every entry.
        """
        result = dict(base)
        for key, val in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(val, dict)
            ):
                result[key] = ScanPolicy._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> ScanPolicy:
        hf = d.get("hidden_files", {})
        rs = d.get("rule_scoping", {})
        cr = d.get("credentials", {})
        fc = d.get("file_classification", {})
        fl = d.get("file_limits", {})
        at = d.get("analysis_thresholds", {})

        severity_overrides = [
            SeverityOverride(**ovr) for ovr in d.get("severity_overrides", [])
        ]

        return cls(
            policy_name=d.get("policy_name", "default"),
            policy_version=d.get("policy_version", "1.0"),
            preset_base=d.get("preset_base", "balanced"),
            hidden_files=HiddenFilePolicy(
                benign_dotfiles=set(hf.get("benign_dotfiles", [])),
                benign_dotdirs=set(hf.get("benign_dotdirs", [])),
            ),
            rule_scoping=RuleScopingPolicy(
                skillmd_and_scripts_only=set(
                    rs.get("skillmd_and_scripts_only", []),
                ),
                skip_in_docs=set(rs.get("skip_in_docs", [])),
                code_only=set(rs.get("code_only", [])),
                doc_path_indicators=set(rs.get("doc_path_indicators", [])),
                doc_filename_patterns=rs.get("doc_filename_patterns", []),
                dedupe_duplicate_findings=rs.get(
                    "dedupe_duplicate_findings",
                    True,
                ),
            ),
            credentials=CredentialPolicy(
                known_test_values=set(cr.get("known_test_values", [])),
                placeholder_markers=set(cr.get("placeholder_markers", [])),
            ),
            file_classification=FileClassificationPolicy(
                inert_extensions=set(fc.get("inert_extensions", [])),
                structured_extensions=set(fc.get("structured_extensions", [])),
                archive_extensions=set(fc.get("archive_extensions", [])),
                code_extensions=set(fc.get("code_extensions", [])),
            ),
            file_limits=FileLimitsPolicy(
                max_file_count=fl.get("max_file_count", 100),
                max_file_size_bytes=fl.get("max_file_size_bytes", 5_242_880),
                max_reference_depth=fl.get("max_reference_depth", 5),
                max_name_length=fl.get("max_name_length", 64),
                max_description_length=fl.get("max_description_length", 1024),
                min_description_length=fl.get("min_description_length", 20),
            ),
            analysis_thresholds=AnalysisThresholdsPolicy(
                min_confidence_pct=at.get("min_confidence_pct", 80),
                max_regex_pattern_length=at.get(
                    "max_regex_pattern_length",
                    1000,
                ),
            ),
            severity_overrides=severity_overrides,
            disabled_rules=set(d.get("disabled_rules", [])),
        )

    def _to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "preset_base": self.preset_base,
            "hidden_files": {
                "benign_dotfiles": sorted(self.hidden_files.benign_dotfiles),
                "benign_dotdirs": sorted(self.hidden_files.benign_dotdirs),
            },
            "rule_scoping": {
                "skillmd_and_scripts_only": sorted(
                    self.rule_scoping.skillmd_and_scripts_only,
                ),
                "skip_in_docs": sorted(self.rule_scoping.skip_in_docs),
                "code_only": sorted(self.rule_scoping.code_only),
                "doc_path_indicators": sorted(
                    self.rule_scoping.doc_path_indicators,
                ),
                "doc_filename_patterns": (
                    self.rule_scoping.doc_filename_patterns
                ),
                "dedupe_duplicate_findings": (
                    self.rule_scoping.dedupe_duplicate_findings
                ),
            },
            "credentials": {
                "known_test_values": sorted(
                    self.credentials.known_test_values,
                ),
                "placeholder_markers": sorted(
                    self.credentials.placeholder_markers,
                ),
            },
            "file_classification": {
                "inert_extensions": sorted(
                    self.file_classification.inert_extensions,
                ),
                "structured_extensions": sorted(
                    self.file_classification.structured_extensions,
                ),
                "archive_extensions": sorted(
                    self.file_classification.archive_extensions,
                ),
                "code_extensions": sorted(
                    self.file_classification.code_extensions,
                ),
            },
            "file_limits": {
                "max_file_count": self.file_limits.max_file_count,
                "max_file_size_bytes": (self.file_limits.max_file_size_bytes),
                "max_reference_depth": (self.file_limits.max_reference_depth),
                "max_name_length": (self.file_limits.max_name_length),
                "max_description_length": (
                    self.file_limits.max_description_length
                ),
                "min_description_length": (
                    self.file_limits.min_description_length
                ),
            },
            "analysis_thresholds": {
                "min_confidence_pct": (
                    self.analysis_thresholds.min_confidence_pct
                ),
                "max_regex_pattern_length": (
                    self.analysis_thresholds.max_regex_pattern_length
                ),
            },
            "severity_overrides": [
                {
                    "rule_id": o.rule_id,
                    "severity": o.severity,
                    "reason": o.reason,
                }
                for o in self.severity_overrides
            ],
            "disabled_rules": sorted(self.disabled_rules),
        }
