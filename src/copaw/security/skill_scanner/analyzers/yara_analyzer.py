# -*- coding: utf-8 -*-
"""YARA-X rule matching analyzer.

Uses the ``yara-x`` library (Rust-based) to compile ``.yara`` files and
scan skill content.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..models import Finding, Severity, SkillFile, ThreatCategory
from ..scan_policy import ScanPolicy
from . import BaseAnalyzer

logger = logging.getLogger(__name__)

# Default YARA rules directory shipped with the package.
_DEFAULT_YARA_DIR = Path(__file__).resolve().parent.parent / "rules" / "yara"

# Maximum file size for binary-mode YARA scanning (50 MB).
_MAX_SCAN_FILE_SIZE = 50 * 1024 * 1024

# Map YARA meta ``threat_type`` values to our ThreatCategory enum.
# Keys are normalised to upper-case for robust matching.
_THREAT_TYPE_MAP: dict[str, ThreatCategory] = {
    "PROMPT INJECTION": ThreatCategory.PROMPT_INJECTION,
    "COMMAND INJECTION": ThreatCategory.COMMAND_INJECTION,
    "DATA EXFILTRATION": ThreatCategory.DATA_EXFILTRATION,
    "CREDENTIAL HARVESTING": ThreatCategory.HARDCODED_SECRETS,
    "CODE EXECUTION": ThreatCategory.COMMAND_INJECTION,
    "SCRIPT INJECTION": ThreatCategory.COMMAND_INJECTION,
    "SQL INJECTION": ThreatCategory.COMMAND_INJECTION,
    "SYSTEM MANIPULATION": ThreatCategory.COMMAND_INJECTION,
    "TOOL CHAINING ABUSE": ThreatCategory.TOOL_CHAINING_ABUSE,
    "AUTONOMY ABUSE": ThreatCategory.AUTONOMY_ABUSE,
    "CAPABILITY INFLATION": ThreatCategory.UNAUTHORIZED_TOOL_USE,
    "COERCIVE INJECTION": ThreatCategory.PROMPT_INJECTION,
    "INDIRECT PROMPT INJECTION": ThreatCategory.PROMPT_INJECTION,
    "EMBEDDED BINARY": ThreatCategory.OBFUSCATION,
    "SUPPLY CHAIN ATTACK": ThreatCategory.OBFUSCATION,
    "UNICODE STEGANOGRAPHY": ThreatCategory.UNICODE_STEGANOGRAPHY,
}

# Map YARA meta ``classification`` to our Severity enum.
_CLASSIFICATION_SEVERITY: dict[str, Severity] = {
    "harmful": Severity.HIGH,
    "suspicious": Severity.MEDIUM,
    "informational": Severity.INFO,
}


def _yara_x_available() -> bool:
    """Return *True* if the ``yara_x`` package can be imported."""
    try:
        import yara_x  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Low-level YARA scanning wrapper
# ---------------------------------------------------------------------------


class YaraRuleEngine:
    """Compiles and runs YARA-X rules against text / binary content."""

    def __init__(
        self,
        rules_dir: Path | None = None,
        *,
        max_scan_file_size: int = _MAX_SCAN_FILE_SIZE,
    ) -> None:
        self.max_scan_file_size = max_scan_file_size
        self.rules_dir = Path(rules_dir or _DEFAULT_YARA_DIR)
        self._rules: Any = None  # yara_x.Rules | None

        if not _yara_x_available():
            logger.info(
                "yara-x is not installed – YaraAnalyzer will be a no-op. "
                "Install with: pip install yara-x",
            )
            return

        self._compile_rules()

    # ------------------------------------------------------------------

    def _compile_rules(self) -> None:
        import yara_x

        if not self.rules_dir.exists():
            raise FileNotFoundError(f"YARA rules dir not found: {self.rules_dir}")

        yara_files = list(self.rules_dir.glob("*.yara"))
        if not yara_files:
            raise FileNotFoundError(f"No .yara files in {self.rules_dir}")

        compiler = yara_x.Compiler()
        try:
            for yf in yara_files:
                compiler.new_namespace(yf.stem)
                compiler.add_source(yf.read_text(encoding="utf-8"), origin=str(yf))
            self._rules = compiler.build()
        except yara_x.CompileError as exc:
            raise RuntimeError(f"YARA compile error: {exc}") from exc

        logger.debug("YaraRuleEngine compiled %d rule files", len(yara_files))

    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._rules is not None

    # ------------------------------------------------------------------

    def scan_content(
        self,
        content: str,
        file_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Scan *content* (UTF-8 text) and return raw match dicts."""
        if not self._rules:
            return []

        import yara_x

        matches: list[dict[str, Any]] = []
        try:
            content_bytes = content.encode("utf-8")
            results = self._rules.scan(content_bytes)

            for rule in results.matching_rules:
                meta_dict = dict(rule.metadata)

                matched_strings: list[dict[str, Any]] = []
                for pattern in rule.patterns:
                    for m in pattern.matches:
                        data_bytes = content_bytes[m.offset : m.offset + m.length]
                        line_num = content_bytes[: m.offset].count(b"\n") + 1
                        line_start = content_bytes.rfind(b"\n", 0, m.offset) + 1
                        line_end = content_bytes.find(b"\n", m.offset)
                        if line_end == -1:
                            line_end = len(content_bytes)
                        line_content = (
                            content_bytes[line_start:line_end]
                            .decode("utf-8", errors="ignore")
                            .strip()
                        )
                        matched_strings.append(
                            {
                                "identifier": pattern.identifier,
                                "offset": m.offset,
                                "matched_data": data_bytes.decode("utf-8", errors="ignore"),
                                "line_number": line_num,
                                "line_content": line_content,
                            }
                        )

                matches.append(
                    {
                        "rule_name": rule.identifier,
                        "namespace": rule.namespace,
                        "file_path": file_path,
                        "meta": meta_dict,
                        "strings": matched_strings,
                    }
                )
        except yara_x.ScanError as exc:
            logger.warning("YARA scan error: %s", exc)

        return matches

    def scan_file(
        self,
        file_path: Path | str,
        display_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Scan a file – tries text-mode first, binary fallback."""
        file_path_str = str(file_path)
        ctx_path = display_path or file_path_str

        # Try text mode for line-number accuracy.
        try:
            with open(file_path_str, encoding="utf-8") as fh:
                content = fh.read()
            return self.scan_content(content, ctx_path)
        except UnicodeDecodeError:
            pass
        except OSError as exc:
            logger.warning("Cannot read %s: %s", file_path_str, exc)
            return []

        # Binary fallback.
        return self._scan_file_binary(file_path_str, ctx_path)

    # ------------------------------------------------------------------

    def _scan_file_binary(
        self,
        file_path: str,
        display_path: str,
    ) -> list[dict[str, Any]]:
        if not self._rules:
            return []

        import yara_x

        p = Path(file_path)
        try:
            size = p.stat().st_size
        except OSError:
            return []
        if size > self.max_scan_file_size:
            logger.warning("Skipping %s (%d bytes > limit)", file_path, size)
            return []

        matches: list[dict[str, Any]] = []
        try:
            file_bytes = p.read_bytes()
            scanner = yara_x.Scanner(self._rules)
            results = scanner.scan(file_bytes)

            for rule in results.matching_rules:
                meta_dict = dict(rule.metadata)
                matched_strings: list[dict[str, Any]] = []
                for pattern in rule.patterns:
                    for m in pattern.matches:
                        data = file_bytes[m.offset : m.offset + m.length]
                        matched_strings.append(
                            {
                                "identifier": pattern.identifier,
                                "offset": m.offset,
                                "matched_data": data.decode("utf-8", errors="ignore"),
                                "line_number": 0,
                                "line_content": f"[binary @ offset {m.offset}]",
                            }
                        )

                matches.append(
                    {
                        "rule_name": rule.identifier,
                        "namespace": rule.namespace,
                        "file_path": display_path,
                        "meta": meta_dict,
                        "strings": matched_strings,
                    }
                )
        except yara_x.ScanError as exc:
            logger.warning("YARA binary scan error for %s: %s", file_path, exc)

        return matches


# ---------------------------------------------------------------------------
# YaraAnalyzer (BaseAnalyzer implementation)
# ---------------------------------------------------------------------------


class YaraAnalyzer(BaseAnalyzer):
    """Analyzer that applies YARA rules to skill files.

    Parameters
    ----------
    rules_dir:
        Directory containing ``.yara`` files.  Defaults to the bundled
        ``rules/yara/`` directory.
    disabled_rules:
        Set of YARA rule names (identifiers) to skip.
    """

    def __init__(
        self,
        rules_dir: Path | None = None,
        *,
        disabled_rules: set[str] | None = None,
        policy: ScanPolicy | None = None,
    ) -> None:
        super().__init__(name="yara", policy=policy)
        # Merge explicitly disabled rules with policy disabled rules
        self._disabled = set(disabled_rules or set())
        self._disabled.update(self.policy.disabled_rules)
        try:
            self._engine = YaraRuleEngine(rules_dir)
        except Exception as exc:
            logger.warning("YaraAnalyzer disabled: %s", exc)
            self._engine = None  # type: ignore[assignment]

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
        if self._engine is None or not self._engine.available:
            return []

        findings: list[Finding] = []

        for sf in files:
            content = sf.read_content()

            # Prefer text-mode scanning when content is available.
            # If decoding failed (read_content returns "") fall back to
            # file-based scanning which includes binary-mode support so
            # that binary-focused YARA rules can still fire.
            if content:
                raw_matches = self._engine.scan_content(
                    content, file_path=sf.relative_path,
                )
            else:
                raw_matches = self._engine.scan_file(
                    sf.path, display_path=sf.relative_path,
                )
                if not raw_matches:
                    continue
            for match in raw_matches:
                rule_name: str = match["rule_name"]
                if self.policy.is_rule_disabled(f"YARA_{rule_name}") or rule_name in self._disabled:
                    continue

                meta: dict[str, Any] = match.get("meta", {})
                threat_type = str(meta.get("threat_type", "")).upper()
                category = _THREAT_TYPE_MAP.get(threat_type, ThreatCategory.MALWARE)
                classification = str(meta.get("classification", "harmful")).lower()
                severity = _CLASSIFICATION_SEVERITY.get(classification, Severity.MEDIUM)
                description = str(meta.get("description", rule_name))

                # Apply severity override from policy
                sev_override = self.policy.get_severity_override(f"YARA_{rule_name}")
                if sev_override:
                    try:
                        severity = Severity(sev_override)
                    except ValueError:
                        pass

                # Create one finding per matched string location.
                strings = match.get("strings", [])
                if strings:
                    for s in strings:
                        findings.append(
                            self._make_finding(
                                rule_name=rule_name,
                                category=category,
                                severity=severity,
                                description=description,
                                file_path=sf.relative_path,
                                line_number=s.get("line_number"),
                                snippet=s.get("line_content"),
                                match_info=s,
                                meta=meta,
                            )
                        )
                else:
                    # Rule matched without specific string info.
                    findings.append(
                        self._make_finding(
                            rule_name=rule_name,
                            category=category,
                            severity=severity,
                            description=description,
                            file_path=sf.relative_path,
                            meta=meta,
                        )
                    )

        return findings

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _make_finding(
        *,
        rule_name: str,
        category: ThreatCategory,
        severity: Severity,
        description: str,
        file_path: str,
        line_number: int | None = None,
        snippet: str | None = None,
        match_info: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Finding:
        fid = f"YARA:{rule_name}:{file_path}"
        if line_number:
            fid += f":{line_number}"
        return Finding(
            id=fid,
            rule_id=f"YARA_{rule_name}",
            category=category,
            severity=severity,
            title=f"YARA: {description}",
            description=description,
            file_path=file_path,
            line_number=line_number,
            snippet=snippet,
            remediation="Review the flagged content and remove or mitigate the detected threat pattern.",
            analyzer="yara",
            metadata={
                "yara_rule": rule_name,
                **({"match": match_info} if match_info else {}),
                **({"meta": meta} if meta else {}),
            },
        )
