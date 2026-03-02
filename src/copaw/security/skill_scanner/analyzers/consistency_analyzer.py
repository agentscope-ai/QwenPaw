# -*- coding: utf-8 -*-
"""Consistency / behavioral-pattern analyzer.

Performs heuristic checks:

* Detects file read/write, grep/regex, glob, network, subprocess usage.
* Checks for hidden files (dotfiles / ``__pycache__``).
* Checks for infinite-loop / resource-abuse patterns.
* Filters findings against the active :class:`ScanPolicy`.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from ..models import Finding, Severity, SkillFile, ThreatCategory
from ..scan_policy import ScanPolicy
from . import BaseAnalyzer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-compiled regex patterns (ported from skill-scanner StaticAnalyzer)
# ---------------------------------------------------------------------------

_READ_PATTERNS = [
    re.compile(r"open\([^)]+['\"]r['\"]"),
    re.compile(r"\.read\("),
    re.compile(r"\.readline\("),
    re.compile(r"\.readlines\("),
    re.compile(r"Path\([^)]+\)\.read_text"),
    re.compile(r"Path\([^)]+\)\.read_bytes"),
    re.compile(r"with\s+open\([^)]+['\"]r"),
]

_WRITE_PATTERNS = [
    re.compile(r"open\([^)]+['\"]w['\"]"),
    re.compile(r"\.write\("),
    re.compile(r"\.writelines\("),
    re.compile(r"pathlib\.Path\([^)]+\)\.write"),
    re.compile(r"with\s+open\([^)]+['\"]w"),
]

_GREP_PATTERNS = [
    re.compile(r"re\.search\("),
    re.compile(r"re\.findall\("),
    re.compile(r"re\.match\("),
    re.compile(r"re\.finditer\("),
    re.compile(r"re\.sub\("),
    re.compile(r"grep"),
]

_GLOB_PATTERNS = [
    re.compile(r"glob\.glob\("),
    re.compile(r"glob\.iglob\("),
    re.compile(r"Path\([^)]*\)\.glob\("),
    re.compile(r"\.glob\("),
    re.compile(r"\.rglob\("),
    re.compile(r"fnmatch\."),
]

_EXCEPTION_PATTERNS = [
    re.compile(
        r"except\s+(EOFError|StopIteration|KeyboardInterrupt|Exception|BaseException)"
    ),
    re.compile(r"except\s*:"),
    re.compile(r"break\s*$", re.MULTILINE),
    re.compile(r"return\s*$", re.MULTILINE),
    re.compile(r"sys\.exit\s*\("),
    re.compile(r"raise\s+StopIteration"),
]

_INFINITE_LOOP_PATTERN = re.compile(r"while\s+True\s*:")

_BASH_INDICATORS = [
    "subprocess.run",
    "subprocess.call",
    "subprocess.Popen",
    "subprocess.check_output",
    "os.system",
    "os.popen",
    "commands.getoutput",
    "shell=True",
]

_NETWORK_INDICATORS = [
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "requests.patch",
    "urllib.request",
    "urllib.urlopen",
    "http.client",
    "httpx.",
    "aiohttp.",
    "socket.connect",
    "socket.create_connection",
]

_EXTERNAL_NETWORK_IMPORTS = [
    "import requests",
    "from requests import",
    "import urllib.request",
    "from urllib.request import",
    "import http.client",
    "import httpx",
    "import aiohttp",
]


# ---------------------------------------------------------------------------
# ConsistencyAnalyzer
# ---------------------------------------------------------------------------


class ConsistencyAnalyzer(BaseAnalyzer):
    """Analyzer that performs consistency and behavioral-pattern checks.

    This utilizes the heuristic checks that are **not** covered by
    YAML regex signatures or YARA rules:

    * File I/O detection (read / write patterns)
    * Network usage detection
    * Subprocess / shell execution detection
    * Infinite loop / resource abuse detection
    * Hidden file / ``__pycache__`` detection
    * Credential placeholder filtering

    Parameters
    ----------
    policy:
        Scan policy.  If *None*, uses :meth:`ScanPolicy.default`.
    """

    def __init__(self, policy: ScanPolicy | None = None) -> None:
        super().__init__(name="consistency", policy=policy)

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

        findings.extend(self._check_hidden_files(files))
        findings.extend(self._check_resource_abuse(files))
        findings.extend(self._check_undeclared_capabilities(files, skill_name))

        # Filter disabled rules
        findings = [
            f for f in findings if not self.policy.is_rule_disabled(f.rule_id)
        ]

        # Filter known test credentials
        findings = [
            f for f in findings if not self._is_known_test_credential(f)
        ]

        return findings

    # ------------------------------------------------------------------
    # Capability detection helpers (uses pre-compiled patterns)
    # ------------------------------------------------------------------

    def _content_matches_any(
        self, content: str, patterns: list[re.Pattern]
    ) -> re.Match | None:
        """Return the first match from *patterns* against *content*, or None."""
        for pat in patterns:
            m = pat.search(content)
            if m:
                return m
        return None

    def _code_reads_files(self, files: list[SkillFile]) -> bool:
        for sf in files:
            if sf.file_type not in ("python", "bash"):
                continue
            content = sf.read_content()
            if self._content_matches_any(content, _READ_PATTERNS):
                return True
        return False

    def _code_writes_files(self, files: list[SkillFile]) -> bool:
        for sf in files:
            if sf.file_type not in ("python", "bash"):
                continue
            content = sf.read_content()
            if self._content_matches_any(content, _WRITE_PATTERNS):
                return True
        return False

    def _code_executes_bash(self, files: list[SkillFile]) -> bool:
        if any(sf.file_type == "bash" for sf in files):
            return True
        for sf in files:
            if sf.file_type != "python":
                continue
            content = sf.read_content()
            if any(ind in content for ind in _BASH_INDICATORS):
                return True
        return False

    def _code_uses_grep(self, files: list[SkillFile]) -> bool:
        for sf in files:
            if sf.file_type not in ("python", "bash"):
                continue
            content = sf.read_content()
            if self._content_matches_any(content, _GREP_PATTERNS):
                return True
        return False

    def _code_uses_glob(self, files: list[SkillFile]) -> bool:
        for sf in files:
            if sf.file_type not in ("python", "bash"):
                continue
            content = sf.read_content()
            if self._content_matches_any(content, _GLOB_PATTERNS):
                return True
        return False

    def _code_uses_network(self, files: list[SkillFile]) -> bool:
        for sf in files:
            if sf.file_type not in ("python", "bash"):
                continue
            content = sf.read_content()
            if any(ind in content for ind in _NETWORK_INDICATORS):
                return True
        return False

    def _code_uses_external_network(self, files: list[SkillFile]) -> bool:
        """Check for external (non-localhost) network usage."""
        localhost_markers = {"localhost", "127.0.0.1", "::1"}
        for sf in files:
            if sf.file_type not in ("python", "bash"):
                continue
            content = sf.read_content()
            if any(ind in content for ind in _EXTERNAL_NETWORK_IMPORTS):
                return True
            if "import socket" in content:
                has_connect = (
                    "socket.connect" in content
                    or "socket.create_connection" in content
                )
                is_local = any(m in content for m in localhost_markers)
                if has_connect and not is_local:
                    return True
        return False

    # ------------------------------------------------------------------
    # Check: hidden files
    # ------------------------------------------------------------------

    def _check_hidden_files(self, files: list[SkillFile]) -> list[Finding]:
        """Flag hidden files / ``__pycache__`` not in the policy allowlist."""
        findings: list[Finding] = []
        benign_dotfiles = self.policy.hidden_files.benign_dotfiles
        benign_dotdirs = self.policy.hidden_files.benign_dotdirs
        flagged_pycache: set[str] = set()

        for sf in files:
            parts = Path(sf.relative_path).parts

            # __pycache__ check
            if "__pycache__" in parts:
                pycache_dir = str(
                    Path(*parts[: parts.index("__pycache__") + 1])
                )
                if pycache_dir not in flagged_pycache:
                    flagged_pycache.add(pycache_dir)
                    findings.append(
                        Finding(
                            id=f"HIDDEN_PYCACHE:{pycache_dir}",
                            rule_id="HIDDEN_PYCACHE",
                            category=ThreatCategory.OBFUSCATION,
                            severity=Severity.LOW,
                            title="Python bytecode cache directory found",
                            description=(
                                f"__pycache__ directory '{pycache_dir}' found in skill package. "
                                "Compiled bytecode should not be shipped."
                            ),
                            file_path=sf.relative_path,
                            remediation="Remove __pycache__ directories from the skill package.",
                            analyzer=self.name,
                        )
                    )
                continue

            # Dotfile / dotdir check
            for part in parts:
                if not part.startswith(".") or part == ".":
                    continue
                # Check if it's a benign dotdir
                if part in benign_dotdirs:
                    break
                # Check if it's all within a known dotdir
                idx = parts.index(part)
                if idx > 0 and any(
                    p in benign_dotdirs for p in parts[:idx]
                ):
                    break
                # Check if the file itself is a benign dotfile
                if part == parts[-1] and part in benign_dotfiles:
                    break
                # Flag it
                findings.append(
                    Finding(
                        id=f"HIDDEN_FILE:{sf.relative_path}",
                        rule_id="HIDDEN_FILE",
                        category=ThreatCategory.OBFUSCATION,
                        severity=Severity.MEDIUM,
                        title="Hidden file or directory detected",
                        description=(
                            f"Hidden path component '{part}' in '{sf.relative_path}'. "
                            "Hidden files may conceal malicious content."
                        ),
                        file_path=sf.relative_path,
                        remediation=(
                            "Remove the hidden file or add it to the policy's "
                            "hidden_files.benign_dotfiles / benign_dotdirs allowlist."
                        ),
                        analyzer=self.name,
                    )
                )
                break

        return findings

    # ------------------------------------------------------------------
    # Check: resource abuse (infinite loops)
    # ------------------------------------------------------------------

    def _check_resource_abuse(self, files: list[SkillFile]) -> list[Finding]:
        """Detect ``while True`` loops without exception handlers."""
        findings: list[Finding] = []
        ctx_size = self.policy.analysis_thresholds.exception_handler_context_lines

        for sf in files:
            if sf.file_type != "python":
                continue
            # Skip doc files
            if self.policy.is_doc_path(sf.relative_path):
                continue

            content = sf.read_content()
            if not content:
                continue

            lines = content.split("\n")
            for m in _INFINITE_LOOP_PATTERN.finditer(content):
                line_num = content.count("\n", 0, m.start()) + 1
                # Check surrounding context for exception handlers
                ctx_lines = lines[
                    line_num - 1: min(line_num + ctx_size, len(lines))
                ]
                ctx_text = "\n".join(ctx_lines)
                has_handler = any(
                    p.search(ctx_text) for p in _EXCEPTION_PATTERNS
                )
                if not has_handler:
                    findings.append(
                        Finding(
                            id=f"RESOURCE_ABUSE_INFINITE_LOOP:{sf.relative_path}:{line_num}",
                            rule_id="RESOURCE_ABUSE_INFINITE_LOOP",
                            category=ThreatCategory.RESOURCE_ABUSE,
                            severity=Severity.MEDIUM,
                            title="Potential infinite loop without exit condition",
                            description=(
                                f"'while True' loop at line {line_num} in "
                                f"'{sf.relative_path}' has no visible exception "
                                "handler or break/return within "
                                f"{ctx_size} lines."
                            ),
                            file_path=sf.relative_path,
                            line_number=line_num,
                            snippet=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                            remediation=(
                                "Add a break condition, exception handler, or "
                                "timeout to prevent resource exhaustion."
                            ),
                            analyzer=self.name,
                        )
                    )

        return findings

    # ------------------------------------------------------------------
    # Check: undeclared capabilities
    # ------------------------------------------------------------------

    def _check_undeclared_capabilities(
        self,
        files: list[SkillFile],
        skill_name: str | None,
    ) -> list[Finding]:
        """Flag code that uses network / subprocess without it being obvious.

        This is a lightweight version of the original ``_check_consistency``
        method.  It emits informational findings when code uses capabilities
        that might surprise reviewers.
        """
        findings: list[Finding] = []

        uses_network = self._code_uses_external_network(files)
        uses_subprocess = self._code_executes_bash(files)
        reads_files = self._code_reads_files(files)
        writes_files = self._code_writes_files(files)

        if uses_network:
            findings.append(
                Finding(
                    id=f"CAPABILITY_NETWORK:{skill_name or 'unknown'}",
                    rule_id="UNDECLARED_NETWORK_USE",
                    category=ThreatCategory.DATA_EXFILTRATION,
                    severity=Severity.MEDIUM,
                    title="Code uses external network communication",
                    description=(
                        "The skill code imports networking libraries that can "
                        "communicate with external servers. Verify this is "
                        "expected and declared."
                    ),
                    remediation=(
                        "Declare network usage in the skill manifest or "
                        "remove unnecessary network imports."
                    ),
                    analyzer=self.name,
                    metadata={
                        "capability": "network",
                        "reads_files": reads_files,
                        "writes_files": writes_files,
                    },
                )
            )

        if uses_subprocess:
            findings.append(
                Finding(
                    id=f"CAPABILITY_SUBPROCESS:{skill_name or 'unknown'}",
                    rule_id="UNDECLARED_SUBPROCESS_USE",
                    category=ThreatCategory.COMMAND_INJECTION,
                    severity=Severity.LOW,
                    title="Code executes shell commands",
                    description=(
                        "The skill code invokes subprocess/shell commands. "
                        "Verify the commands are safe and expected."
                    ),
                    remediation=(
                        "Review all subprocess calls and ensure they do not "
                        "accept unsanitized user input."
                    ),
                    analyzer=self.name,
                    metadata={"capability": "subprocess"},
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Credential filtering
    # ------------------------------------------------------------------

    def _is_known_test_credential(self, finding: Finding) -> bool:
        """Check if a finding matches a well-known test/placeholder credential."""
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
