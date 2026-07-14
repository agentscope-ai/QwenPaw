# -*- coding: utf-8 -*-
"""Deep security detectors for GovernancePolicy Phase 1.

Extracted from the three tool-guard Guardians as pure functions:
- detect_sensitive_paths: FilePathToolGuardian logic
- detect_dangerous_patterns: RuleBasedToolGuardian logic
- detect_shell_evasion: ShellEvasionGuardian logic

These functions are stateless and receive all configuration via parameters
rather than reading global config — configuration lives in policy.yaml.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model (lightweight finding for governance layer)
# ---------------------------------------------------------------------------


@dataclass
class GuardFinding:
    """A single security finding from deep scan."""

    id: str
    rule_id: str
    category: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"
    title: str
    description: str
    tool_name: str
    param_name: str | None = None
    matched_value: str | None = None
    matched_pattern: str | None = None
    snippet: str | None = None
    remediation: str | None = None
    detector: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_deep_scan(
    *,
    tool_name: str,
    target: str,
    tool_type: str,
    sensitive_paths: List[str],
    detection_rules: list[Any],
    shell_evasion_checks: dict[str, bool],
    raw_params: dict[str, Any] | None = None,
) -> list[GuardFinding]:
    """Run all deep security detectors for one tool call.

    Called by GovernancePolicy._deep_security_scan().

    Args:
        tool_name: Policy tool name (e.g. "Read", "Bash")
        target: Tool's primary target argument
        tool_type: Registry tool type ("file", "shell", "browser", etc.)
        sensitive_paths: List of sensitive path prefixes from policy.yaml
        detection_rules: List of DetectionRuleConfig from policy.yaml
        shell_evasion_checks: Per-check enablement map from policy.yaml
        raw_params: Full tool call parameters dict (for param-value scanning)

    Returns:
        Accumulated list of GuardFinding objects.
    """
    findings: list[GuardFinding] = []

    # Detector 1: Sensitive path detection
    if sensitive_paths:
        findings.extend(
            detect_sensitive_paths(
                tool_name=tool_name,
                target=target,
                tool_type=tool_type,
                sensitive_paths=sensitive_paths,
            ),
        )

    # Detector 2: Pattern-based dangerous command detection
    if detection_rules and (target or raw_params):
        findings.extend(
            detect_dangerous_patterns(
                tool_name=tool_name,
                target=target,
                detection_rules=detection_rules,
                raw_params=raw_params,
            ),
        )

    # Detector 3: Shell evasion/obfuscation detection
    if tool_type == "shell" and target and shell_evasion_checks:
        findings.extend(
            detect_shell_evasion(
                command=target,
                checks_config=shell_evasion_checks,
            ),
        )

    return findings


# ---------------------------------------------------------------------------
# Detector 1: Sensitive path detection
# ---------------------------------------------------------------------------


def _normalize_path(raw_path: str) -> str:
    """Normalize a raw path to canonical absolute form."""
    if not isinstance(raw_path, str):
        return ""
    raw = raw_path.strip()
    if not raw:
        return ""
    p = Path(raw).expanduser()
    if not p.is_absolute():
        try:
            p = Path.cwd() / p
        except Exception:
            return raw
    return str(p.resolve(strict=False))


def _is_sensitive(
    abs_path: str,
    sensitive_files: set[str],
    sensitive_dirs: set[str],
) -> bool:
    """Check if abs_path matches any sensitive file or directory prefix."""
    if not abs_path:
        return False
    if abs_path in sensitive_files:
        return True
    for dir_path in sensitive_dirs:
        if not dir_path:
            continue
        trimmed = dir_path.rstrip("/\\")
        if not trimmed:
            continue
        if abs_path == trimmed:
            return True
        if abs_path.startswith(trimmed + "/"):
            return True
        if abs_path.startswith(trimmed + "\\"):
            return True
    return False


def _looks_like_path_token(token: str) -> bool:
    """Heuristic: does this token look like a file path?"""
    if not token or token.startswith("-"):
        return False
    lowered = token.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "data:")):
        return False
    return (
        token.startswith(("~", "/", "./", "../"))
        or "/" in token
        or "\\" in token
    )


def _extract_paths_from_shell_command(command: str) -> list[str]:
    """Extract candidate file paths from a shell command string."""
    use_posix = os.name != "nt"
    try:
        tokens = shlex.split(command, posix=use_posix)
    except ValueError:
        tokens = command.split()

    candidates: list[str] = []
    for token in tokens:
        token = token.strip("'\"")
        if _looks_like_path_token(token):
            candidates.append(token)
    # Deduplicate
    seen: set[str] = set()
    deduped: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


def detect_sensitive_paths(
    *,
    tool_name: str,
    target: str,
    tool_type: str,
    sensitive_paths: List[str],
) -> list[GuardFinding]:
    """Detect access to sensitive file paths.

    Normalizes configured sensitive_paths into files and directories,
    then checks the tool's target against them.
    """
    if not sensitive_paths or not target:
        return []

    # Partition into files and dirs
    sensitive_files: set[str] = set()
    sensitive_dirs: set[str] = set()
    for sp in sensitive_paths:
        if not sp:
            continue
        normalized = _normalize_path(sp)
        if sp.endswith(("/", "\\")):
            sensitive_dirs.add(normalized)
        else:
            # Check if it's actually a directory on disk
            p = Path(normalized)
            if p.is_dir():
                sensitive_dirs.add(normalized)
            else:
                sensitive_files.add(normalized)

    findings: list[GuardFinding] = []

    if tool_type == "shell":
        # Extract paths from shell command
        for raw_path in _extract_paths_from_shell_command(target):
            abs_path = _normalize_path(raw_path)
            if _is_sensitive(abs_path, sensitive_files, sensitive_dirs):
                findings.append(
                    GuardFinding(
                        id=f"GUARD-{uuid.uuid4().hex[:12]}",
                        rule_id="SENSITIVE_FILE_BLOCK",
                        category="sensitive_file_access",
                        severity="HIGH",
                        title="[HIGH] Access to sensitive file is blocked",
                        description=(
                            f"Tool '{tool_name}' attempted to access "
                            f"sensitive file: {raw_path}"
                        ),
                        tool_name=tool_name,
                        param_name="command",
                        matched_value=raw_path,
                        matched_pattern=abs_path,
                        snippet=target[:100],
                        remediation=(
                            "Use a non-sensitive file path, or remove "
                            "this path from policy sensitive_paths."
                        ),
                        detector="sensitive_path_detector",
                        metadata={"resolved_path": abs_path},
                    ),
                )
    else:
        # Direct target check (file tools, etc.)
        abs_path = _normalize_path(target)
        if _is_sensitive(abs_path, sensitive_files, sensitive_dirs):
            findings.append(
                GuardFinding(
                    id=f"GUARD-{uuid.uuid4().hex[:12]}",
                    rule_id="SENSITIVE_FILE_BLOCK",
                    category="sensitive_file_access",
                    severity="HIGH",
                    title="[HIGH] Access to sensitive file is blocked",
                    description=(
                        f"Tool '{tool_name}' attempted to access "
                        f"sensitive file: {target}"
                    ),
                    tool_name=tool_name,
                    param_name="target",
                    matched_value=target,
                    matched_pattern=abs_path,
                    snippet=target,
                    remediation=(
                        "Use a non-sensitive file path, or remove "
                        "this path from policy sensitive_paths."
                    ),
                    detector="sensitive_path_detector",
                    metadata={"resolved_path": abs_path},
                ),
            )

    return findings


# ---------------------------------------------------------------------------
# Detector 2: Pattern-based dangerous command detection
# ---------------------------------------------------------------------------

# Compiled rule cache. Keyed on the rule's pattern *contents*: only
# patterns/exclude_patterns affect the compiled regex, so the cache is
# sound as long as the key reflects them. Keying on id(rule) is unsafe —
# CPython may reuse a freed object's address for a new object, surfacing
# another rule's stale compiled patterns; keying on rule.id alone collides
# when two rules share an id but differ in patterns (e.g. hot-reload).
# Content keys are plain tuples of str, so no dependency on object
# weak-referenceability, and entries survive their source object (acceptable
# — rules are a small static config set).
_COMPILED_CACHE: dict[
    tuple[tuple[str, ...], tuple[str, ...]],
    tuple[
        list[re.Pattern[str]],
        list[re.Pattern[str]],
    ],
] = {}


def _get_compiled_patterns(
    rule: Any,
) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    """Get or compile regex patterns for a detection rule."""
    # Cache key is the rule's pattern contents — the only inputs that shape
    # the compiled regex. Stable across object identity and address reuse.
    cache_key = (
        tuple(rule.patterns),
        tuple(rule.exclude_patterns),
    )
    if cache_key in _COMPILED_CACHE:
        return _COMPILED_CACHE[cache_key]

    compiled: list[re.Pattern[str]] = []
    for pat in rule.patterns:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE))
        except re.error as exc:
            logger.warning("Bad regex in rule %s: %s", rule.id, exc)

    compiled_exclude: list[re.Pattern[str]] = []
    for pat in rule.exclude_patterns:
        try:
            compiled_exclude.append(re.compile(pat, re.IGNORECASE))
        except re.error as exc:
            logger.warning("Bad exclude regex in rule %s: %s", rule.id, exc)

    _COMPILED_CACHE[cache_key] = (compiled, compiled_exclude)
    return compiled, compiled_exclude


def detect_dangerous_patterns(  # noqa: E501  pylint: disable=too-many-locals,too-many-branches
    *,
    tool_name: str,
    target: str,
    detection_rules: list[Any],
    raw_params: dict[str, Any] | None = None,
) -> list[GuardFinding]:
    """Match tool parameter values against regex detection rules.

    Scans the primary `target` and string values in `raw_params`, honoring
    each rule's `params` scope (empty = match all params). Aligns with the
    frontend Security page semantics ("match tool parameter values").
    """
    findings: list[GuardFinding] = []

    # Map governance tool names to tool_guard tool names for rule matching.
    # Policy uses "Bash"; rules use "execute_shell_command".
    tool_aliases = {
        "Bash": "execute_shell_command",
        "Read": "read_file",
        "Write": "write_file",
        "Edit": "edit_file",
    }
    guard_tool_name = tool_aliases.get(tool_name, tool_name)

    # Resolve the registry's primary param name for `target` so that
    # rule.params filtering and finding.param_name use real names
    # (e.g. "command" for Bash, "file_path" for Write).
    from .tool_registry import (
        DEFAULT_REGISTRY,
    )  # pylint: disable=import-outside-toplevel

    target_param_name = (
        DEFAULT_REGISTRY.get_target_param(tool_name) or "target"
    )

    # Collect all scannable (param_name, value) pairs from raw_params.
    # The target value is represented under its real param name.
    scan_entries: list[tuple[str, str]] = []
    if raw_params:
        for param_name, param_value in raw_params.items():
            if isinstance(param_value, str) and param_value:
                scan_entries.append((param_name, param_value))
    # If target is non-empty and not already covered by raw_params, add it
    # under the registry param name (fallback for callers without raw_params).
    if target and not any(v == target for _, v in scan_entries):
        scan_entries.insert(0, (target_param_name, target))

    if not scan_entries:
        return findings

    for rule in detection_rules:
        # Check if rule applies to this tool
        if rule.tools and guard_tool_name not in rule.tools:
            continue

        # rule.params scoping: when non-empty, only scan listed params
        rule_params = getattr(rule, "params", None) or []

        compiled_patterns, compiled_exclude = _get_compiled_patterns(rule)
        matched = False

        for param_name, value in scan_entries:
            if matched:
                break

            # Honor rule.params scope (H1 fix)
            if rule_params and param_name not in rule_params:
                continue

            # Check exclude patterns (against this value)
            if any(ep.search(value) for ep in compiled_exclude):
                continue

            # Check match patterns
            for pattern in compiled_patterns:
                m = pattern.search(value)
                if m:
                    start = max(0, m.start() - 40)
                    end = min(len(value), m.end() + 40)
                    snippet = value[start:end]

                    findings.append(
                        GuardFinding(
                            id=f"GUARD-{uuid.uuid4().hex[:12]}",
                            rule_id=rule.id,
                            category=rule.category,
                            severity=rule.severity,
                            title=f"[{rule.severity}] {rule.description}",
                            description=(
                                rule.description
                                or f"Rule {rule.id} matched parameter "
                                f"'{param_name}' of tool '{tool_name}'."
                            ),
                            tool_name=tool_name,
                            param_name=param_name,
                            matched_value=m.group(0),
                            matched_pattern=pattern.pattern,
                            snippet=snippet,
                            remediation=rule.remediation,
                            detector="pattern_detector",
                        ),
                    )
                    matched = True
                    break  # One match per rule is sufficient

    return findings


# ---------------------------------------------------------------------------
# Detector 3: Shell evasion/obfuscation detection
# ---------------------------------------------------------------------------

# Pre-compiled patterns for command substitution detection
_CMD_SUB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<\("), "process substitution <()"),
    (re.compile(r">\("), "process substitution >()"),
    (re.compile(r"=\("), "Zsh process substitution =()"),
    (re.compile(r"\$\("), "$() command substitution"),
    (re.compile(r"\$\["), "$[] legacy arithmetic expansion"),
]

_ANSI_C_QUOTE_RE = re.compile(r"\$'[^']*'")
_LOCALE_QUOTE_RE = re.compile(r'\$"[^"]*"')
_EMPTY_SPECIAL_QUOTE_DASH_RE = re.compile(r"\$['\"]{2}\s*-")
_EMPTY_QUOTE_DASH_RE = re.compile(r"(?:^|\s)(?:''|\"\")+\s*-")
_SHELL_OPERATORS = frozenset(";|&<>")


class _QuoteState:
    """Tracks shell quoting context character-by-character."""

    __slots__ = ("in_single", "in_double", "escaped")

    def __init__(self) -> None:
        self.in_single = False
        self.in_double = False
        self.escaped = False

    @property
    def in_any_quote(self) -> bool:
        return self.in_single or self.in_double

    def feed(self, char: str) -> None:
        if self.escaped:
            self.escaped = False
            return
        if char == "\\" and not self.in_single:
            self.escaped = True
            return
        if char == "'" and not self.in_double:
            self.in_single = not self.in_single
            return
        if char == '"' and not self.in_single:
            self.in_double = not self.in_double


def _extract_outside_single_quotes(command: str) -> str:
    """Return command with single-quoted content removed."""
    state = _QuoteState()
    parts: list[str] = []
    for ch in command:
        was_single = state.in_single
        state.feed(ch)
        if not was_single and not state.in_single:
            parts.append(ch)
    return "".join(parts)


def _make_evasion_finding(
    rule_id: str,
    severity: str,
    title: str,
    command: str,
    *,
    matched: str | None = None,
) -> GuardFinding:
    """Helper to create shell evasion findings."""
    return GuardFinding(
        id=f"GUARD-{uuid.uuid4().hex[:12]}",
        rule_id=rule_id,
        category="code_execution",
        severity=severity,
        title=f"[{severity}] {title}",
        description=title,
        tool_name="Bash",
        param_name="command",
        matched_value=matched or command[:80],
        snippet=command[:100],
        remediation="Use plain text commands without obfuscation.",
        detector="shell_evasion_detector",
    )


def _check_command_substitution(command: str) -> GuardFinding | None:
    """Detect command substitution patterns."""
    # Backtick check
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch == "`" and not state.in_single and not state.escaped:
            snippet_start = max(0, i - 20)
            snippet_end = min(len(command), i + 20)
            return _make_evasion_finding(
                "SHELL_EVASION_COMMAND_SUBSTITUTION",
                "HIGH",
                "Command contains backtick (`) command substitution",
                command,
                matched=command[snippet_start:snippet_end],
            )

    # Other patterns
    unquoted = _extract_outside_single_quotes(command)
    for pattern, label in _CMD_SUB_PATTERNS:
        m = pattern.search(unquoted)
        if m:
            return _make_evasion_finding(
                "SHELL_EVASION_COMMAND_SUBSTITUTION",
                "HIGH",
                f"Command contains {label}",
                command,
                matched=m.group(0),
            )
    return None


def _check_obfuscated_flags(command: str) -> GuardFinding | None:
    """Detect ANSI-C / locale quoting and flag obfuscation."""
    if _ANSI_C_QUOTE_RE.search(command):
        return _make_evasion_finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            "HIGH",
            "Command contains ANSI-C quoting ($'...') "
            "which can hide characters",
            command,
        )
    if _LOCALE_QUOTE_RE.search(command):
        return _make_evasion_finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            "HIGH",
            'Command contains locale quoting ($"...") '
            "which can hide characters",
            command,
        )
    if _EMPTY_SPECIAL_QUOTE_DASH_RE.search(command):
        return _make_evasion_finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            "HIGH",
            "Command contains empty special quotes before dash",
            command,
        )
    if _EMPTY_QUOTE_DASH_RE.search(command):
        return _make_evasion_finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            "HIGH",
            "Command contains empty quotes before dash",
            command,
        )
    return None


def _check_backslash_escaped_whitespace(command: str) -> GuardFinding | None:
    """Detect backslash-escaped space/tab outside quotes."""
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            if not state.in_double and ch in (" ", "\t"):
                return _make_evasion_finding(
                    "SHELL_EVASION_BACKSLASH_WHITESPACE",
                    "HIGH",
                    "Command contains backslash-escaped whitespace",
                    command,
                    matched=command[max(0, i - 1) : i + 1],
                )
            state.feed(ch)
            continue
        state.feed(ch)
    return None


def _check_backslash_escaped_operators(command: str) -> GuardFinding | None:
    """Detect backslash before shell operators outside quotes."""
    find_exec_re = re.compile(r"-(?:exec|execdir)\b[\s\S]*\{\}\s*\\;$")
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            if not state.in_double and ch in _SHELL_OPERATORS:
                if ch == ";":
                    prefix = command[: i + 1]
                    if find_exec_re.search(prefix):
                        state.feed(ch)
                        continue
                return _make_evasion_finding(
                    "SHELL_EVASION_BACKSLASH_OPERATOR",
                    "HIGH",
                    f"Command contains backslash before shell operator"
                    f" (\\{ch})",
                    command,
                    matched=command[max(0, i - 1) : i + 1],
                )
            state.feed(ch)
            continue
        state.feed(ch)
    return None


def _looks_like_heredoc(command: str) -> bool:
    """Return True when command appears to include a complete heredoc."""
    opener_re = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
    lines = command.splitlines()
    if len(lines) < 2:
        return False
    for i, line in enumerate(lines):
        m = opener_re.search(line)
        if not m:
            continue
        delim = m.group(2)
        for next_line in lines[i + 1 :]:
            if next_line.strip() == delim:
                return True
    return False


def _check_newlines(command: str) -> GuardFinding | None:
    """Detect newlines/carriage returns that could hide commands."""
    if _looks_like_heredoc(command):
        return None

    state = _QuoteState()
    for ch in command:
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch == "\r" and not state.in_double:
            return _make_evasion_finding(
                "SHELL_EVASION_NEWLINE",
                "HIGH",
                "Command contains carriage return (\\r)",
                command,
            )

    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch in ("\n", "\r") and not state.in_any_quote:
            rest = command[i + 1 :]
            if rest.lstrip():
                return _make_evasion_finding(
                    "SHELL_EVASION_NEWLINE",
                    "HIGH",
                    "Command contains newlines that could separate "
                    "multiple commands",
                    command,
                )
    return None


def _check_comment_quote_desync(command: str) -> GuardFinding | None:
    """Detect quote characters inside # comments."""
    if "#" not in command:
        return None
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch == "#" and not state.in_any_quote:
            line_end = command.find("\n", i)
            comment = command[i + 1 : line_end if line_end != -1 else None]
            if re.search(r"['\"]", comment):
                return _make_evasion_finding(
                    "SHELL_EVASION_COMMENT_QUOTE_DESYNC",
                    "HIGH",
                    "Command contains quote characters inside a # comment",
                    command,
                    matched=command[
                        i : (line_end if line_end != -1 else i + 40)
                    ],
                )
            if line_end == -1:
                break
    return None


def _check_quoted_newline(command: str) -> GuardFinding | None:
    """Detect newlines inside quoted strings followed by #-prefixed lines."""
    if "\n" not in command or "#" not in command:
        return None
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch == "\n" and state.in_any_quote:
            line_start = i + 1
            next_nl = command.find("\n", line_start)
            line_end = next_nl if next_nl != -1 else len(command)
            next_line = command[line_start:line_end]
            if next_line.strip().startswith("#"):
                return _make_evasion_finding(
                    "SHELL_EVASION_QUOTED_NEWLINE",
                    "HIGH",
                    "Command contains a quoted newline followed by a "
                    "#-prefixed line",
                    command,
                )
    return None


# Check name → function mapping
_EVASION_CHECKS: list[tuple[str, Any]] = [
    ("command_substitution", _check_command_substitution),
    ("obfuscated_flags", _check_obfuscated_flags),
    ("backslash_escaped_whitespace", _check_backslash_escaped_whitespace),
    ("backslash_escaped_operators", _check_backslash_escaped_operators),
    ("newlines", _check_newlines),
    ("comment_quote_desync", _check_comment_quote_desync),
    ("quoted_newline", _check_quoted_newline),
]


def detect_shell_evasion(
    *,
    command: str,
    checks_config: dict[str, bool],
) -> list[GuardFinding]:
    """Detect shell evasion/obfuscation techniques.

    Each check can be individually enabled/disabled via checks_config.
    """
    if not command or not command.strip():
        return []

    findings: list[GuardFinding] = []
    for check_name, check_fn in _EVASION_CHECKS:
        if not checks_config.get(check_name, False):
            continue
        try:
            result = check_fn(command)
            if result is not None:
                findings.append(result)
        except Exception as exc:
            logger.warning(
                "Shell evasion check '%s' failed: %s",
                check_name,
                exc,
            )
    return findings
